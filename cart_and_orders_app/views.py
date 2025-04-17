from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from offer_and_coupon_app.user_views import available_coupons
from decimal import Decimal
from django.contrib.admin.views.decorators import staff_member_required
from offer_and_coupon_app.utils import apply_offers_to_cart
from django.db.models import Sum, Count, F, Q
from .models import Order, SalesReport
from .forms import SalesReportForm, OrderCreateForm
from datetime import datetime, timedelta
import csv
from django.http import HttpResponse
from django.utils import timezone
from user_app.models import Address
from .forms import OrderStatusForm, ReturnRequestForm
import razorpay
from .models import Cart, CartItem, Wishlist, Order, OrderItem, ReturnRequest
from product_app.models import ProductVariant
from django.conf import settings
from django.urls import reverse
from offer_and_coupon_app.models import Coupon, UserCoupon, Wallet, WalletTransaction
from xhtml2pdf import pisa
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.template.loader import get_template
from io import BytesIO
import json
import logging

def is_admin(user):
    return user.is_staff or user.is_superuser

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_orders_list(request):
    search_query = request.GET.get('q', '')
    sort_by = request.GET.get('sort', '-order_date')
    status_filter = request.GET.get('status', '')

    orders = Order.objects.all().select_related('user', 'shipping_address', 'coupon')
    
    if search_query:
        orders = orders.filter(
            Q(order_id__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(user__full_name__icontains=search_query)
        )
    
    if status_filter:
        orders = orders.filter(status=status_filter)

    valid_sorts = ['order_date', '-order_date', 'total_amount', '-total_amount']
    sort_by = sort_by if sort_by in valid_sorts else '-order_date'
    orders = orders.order_by(sort_by)

    paginator = Paginator(orders, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    if 'clear' in request.GET:
        return redirect('cart_and_orders_app:admin_orders_list')

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'sort_by': sort_by,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'cart_and_orders_app/admin_orders_list.html', context)

@login_required
def admin_mark_delivered(request, order_id):
    order = get_object_or_404(Order, order_id=order_id)
    if request.method == 'POST':
        with transaction.atomic():
            order.status = 'Delivered'
            order.delivered_at = timezone.now()
            order.save()
            if order.coupon:
                user_coupon = UserCoupon.objects.filter(user=order.user, coupon=order.coupon, is_used=False).first()
                if user_coupon:
                    order.coupon.usage_count += 1
                    order.coupon.save()
                    user_coupon.is_used = True
                    user_coupon.used_at = timezone.now()
                    user_coupon.order = order
                    user_coupon.save()
        return JsonResponse({'success': True, 'message': 'Order marked as delivered.'})
    return render(request, 'admin_order_detail.html', {'order': order})

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_order_detail(request, order_id):
    order = get_object_or_404(Order, order_id=order_id)
    if request.method == 'POST':
        form = OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            old_status = order.status
            order = form.save()
            if order.status == 'Pending' and old_status != 'Pending':
                order.decrease_stock()
            elif order.status == 'Cancelled' and old_status != 'Cancelled':
                order.restore_stock()
            messages.success(request, f"Order {order.order_id} status updated to {order.status}")
            return redirect('cart_and_orders_app:admin_orders_list')
    else:
        form = OrderStatusForm(instance=order)

    context = {
        'order': order,
        'form': form,
        'order_items': order.items.all(),
        'return_requests': order.return_requests.all(),
    }
    return render(request, 'admin_order_detail.html', context)

@login_required
@user_passes_test(is_admin)
def admin_mark_shipped(request, order_id):
    order = get_object_or_404(Order, order_id=order_id)
    order.status = 'Shipped'
    order.save()
    messages.success(request, f"Order {order.order_id} marked as shipped.")
    return redirect('cart_and_orders_app:admin_orders_list')

@login_required
@user_passes_test(is_admin)
def admin_cancel_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id)
    if request.method == 'POST':
        order.status = 'Cancelled'
        order.save()
        order.restore_stock()
        messages.success(request, f"Order {order.order_id} has been cancelled.")
        return redirect('cart_and_orders_app:admin_orders_list')
    context = {'order': order}
    return render(request, 'admin_cancel_order.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_verify_return_request(request, return_id):
    return_request = get_object_or_404(ReturnRequest, id=return_id)
    order = return_request.order
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            return_request.is_verified = True
            return_request.process_refund()
            order.status = 'Cancelled'
            order.save()
            messages.success(request, f"Return request for {order.order_id} approved and refunded")
        elif action == 'reject':
            return_request.is_verified = False
            return_request.refund_processed = False
            return_request.save()
            messages.warning(request, f"Return request for {order.order_id} rejected")
        return redirect('cart_and_orders_app:admin_orders_list')
    context = {'return_request': return_request, 'order': order}
    return render(request, 'admin_verify_return.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_inventory_list(request):
    search_query = request.GET.get('q', '')
    variants = ProductVariant.objects.all().select_related('product')
    if search_query:
        variants = variants.filter(
            Q(product__product_name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(flavor__icontains=search_query) |
            Q(size_weight__icontains=search_query)
        )
    paginator = Paginator(variants, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    if 'clear' in request.GET:
        return redirect('cart_and_orders_app:admin_inventory_list')
    context = {'page_obj': page_obj, 'search_query': search_query}
    return render(request, 'admin_inventory_list.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_update_stock(request, variant_id):
    variant = get_object_or_404(ProductVariant, id=variant_id)
    if request.method == 'POST':
        try:
            new_stock = int(request.POST.get('stock', 0))
            if new_stock >= 0:
                variant.stock = new_stock
                variant.save()
                messages.success(request, f"Stock updated for {variant.product.product_name}")
                return redirect('cart_and_orders_app:admin_inventory_list')
            else:
                messages.error(request, "Stock cannot be negative")
        except ValueError:
            messages.error(request, "Invalid stock value")
    context = {'variant': variant}
    return render(request, 'admin_update_stock.html', context)

@login_required
def user_cart_list(request):
    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = cart.items.select_related('variant__product').all()
        cart_total_items = sum(item.quantity for item in cart_items)
        
        has_out_of_stock = any(item.variant.stock <= 0 for item in cart_items)
        
        total_price, discount_info = apply_offers_to_cart(cart_items, None, request.user)
        
        cart_subtotal = Decimal(str(discount_info['subtotal']))
        offer_discount = Decimal(str(discount_info['offer_discount']))
        shipping_cost = Decimal(str(discount_info['shipping_cost']))
        
        context = {
            'cart_items': cart_items,
            'cart_total_items': cart_total_items,
            'cart_subtotal': float(cart_subtotal),
            'offer_discount': float(offer_discount),
            'shipping_cost': float(shipping_cost),
            'cart_total': float(total_price),
            'has_out_of_stock': has_out_of_stock,
        }
        return render(request, 'cart_and_orders_app/user_cart_list.html', context)
    
    except Cart.DoesNotExist:
        messages.info(request, "Your cart is empty.")
        return render(request, 'cart_and_orders_app/user_cart_list.html', {
            'cart_items': [],
            'cart_total_items': 0,
            'cart_subtotal': 0.0,
            'offer_discount': 0.0,
            'shipping_cost': 0.0,
            'cart_total': 0.0,
            'has_out_of_stock': False,
        })
    except Exception:
        messages.error(request, "An error occurred while loading your cart.")
        return render(request, 'cart_and_orders_app/user_cart_list.html', {
            'cart_items': [],
            'cart_total_items': 0,
            'cart_subtotal': 0.0,
            'offer_discount': 0.0,
            'shipping_cost': 0.0,
            'cart_total': 0.0,
            'has_out_of_stock': False,
        })

@login_required
@require_POST
def user_add_to_cart(request, variant_id=None):
    try:
        request_data = json.loads(request.body) if request.body else {}
        
        if variant_id is None:
            variant_id = request_data.get('variant_id')
        if not variant_id:
            return JsonResponse({'success': False, 'message': 'Variant ID is required.'}, status=400)

        variant = get_object_or_404(ProductVariant, id=variant_id)
        if not variant.is_active or not variant.product.is_active or not variant.product.category.is_active:
            return JsonResponse({'success': False, 'message': 'This product is not available.'}, status=400)

        quantity = request_data.get('quantity', 1)
        try:
            quantity = int(quantity)
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'message': 'Invalid quantity provided.'}, status=400)

        if quantity <= 0:
            return JsonResponse({'success': False, 'message': 'Quantity must be at least 1.'}, status=400)

        if variant.stock < quantity:
            return JsonResponse({'success': False, 'message': f'Only {variant.stock} items left in stock.'}, status=400)

        MAX_QUANTITY = 10
        if quantity > MAX_QUANTITY:
            return JsonResponse({'success': False, 'message': f'Maximum limit of {MAX_QUANTITY} reached.'}, status=400)

        cart, created = Cart.objects.get_or_create(user=request.user)

        cart_item, item_created = CartItem.objects.get_or_create(cart=cart, variant=variant)
        cart_item.quantity = quantity
        best_price_info = variant.best_price
        cart_item.price = best_price_info['price']
        cart_item.applied_offer = best_price_info['applied_offer_type']
        cart_item.save()

        Wishlist.objects.filter(user=request.user, variant=variant).delete()

        cart_total_items = cart.items.count()
        cart_subtotal = cart.get_subtotal()

        offer_details = request.session.get('applied_offers', [])
        existing_offer = next((o for o in offer_details if o['variant_id'] == variant.id), None)
        discount = (best_price_info['original_price'] - best_price_info['price']) * Decimal(str(cart_item.quantity))
        if existing_offer:
            existing_offer['quantity'] = cart_item.quantity
            existing_offer['discount'] = float(discount)
        elif best_price_info['applied_offer_type'] in ['product', 'category']:
            offer_details.append({
                'variant_id': variant.id,
                'product': variant.product.product_name,
                'offer_type': best_price_info['applied_offer_type'],
                'offer_name': best_price_info['applied_offer_name'],
                'quantity': cart_item.quantity,
                'discount': float(discount)
            })
        request.session['applied_offers'] = offer_details
        request.session.modified = True

        variant_image = None
        primary_image = cart_item.variant.primary_image
        if primary_image and primary_image.image:
            variant_image = primary_image.image.url
        elif variant.product.primary_image and variant.product.primary_image.image:
            variant_image = variant.product.primary_image.image.url
        else:
            variant_image = "https://via.placeholder.com/50?text=No+Image"

        return JsonResponse({
            'success': True,
            'message': f'{variant.product.product_name} added to cart.',
            'cart_count': cart_total_items,
            'cart_subtotal': float(cart_subtotal),
            'wishlist_count': Wishlist.objects.filter(user=request.user).count(),
            'variant_image': variant_image,
            'applied_offer': cart_item.applied_offer or 'none',
            'offer_details': offer_details,
            'quantity': cart_item.quantity
        })
    except ProductVariant.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Variant not found.'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
def check_wishlist(request):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        last_check_time = request.session.get('last_wishlist_check', None)
        now = timezone.now()
        request.session['last_wishlist_check'] = now.timestamp()
        if last_check_time is None:
            return JsonResponse({'success': True, 'new_items': []})
        from datetime import timezone as dt_timezone
        last_check = timezone.datetime.fromtimestamp(last_check_time, tz=dt_timezone.utc)
        new_items = Wishlist.objects.filter(
            user=request.user,
            created_at__gt=last_check
        ).select_related('variant__product')
        
        return JsonResponse({
            'success': True,
            'new_items': [{
                'id': item.id,
                'variant_id': item.variant.id,
                'product_name': item.variant.product.product_name,
                'product_slug': item.variant.product.slug,
                'flavor': item.variant.flavor or 'Standard',
                'size_weight': item.variant.size_weight or 'N/A',
                'price': str(item.variant.price),
                'stock': item.variant.stock,
            } for item in new_items]
        })
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

@login_required
@require_POST
def check_wishlist_variant(request):
    try:
        data = json.loads(request.body) if request.body else {}
        variant_id = data.get('variant_id')
        if not variant_id:
            return JsonResponse({'success': False, 'message': 'Variant ID is required.'}, status=400)

        is_in_wishlist = Wishlist.objects.filter(user=request.user, variant_id=variant_id).exists()
        return JsonResponse({'success': True, 'is_in_wishlist': is_in_wishlist})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@require_POST
def user_update_cart_quantity(request, item_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Cart not found for this user'}, status=400)

    try:
        item = CartItem.objects.get(id=item_id, cart=cart)
    except CartItem.DoesNotExist:
        return JsonResponse({'success': False, 'message': f'Cart item with ID {item_id} not found'}, status=400)

    action = request.POST.get('action')
    if action == 'increment' and item.quantity < item.variant.stock and item.quantity < 10:
        item.quantity += 1
        item.save()
        return JsonResponse({
            'success': True,
            'message': f'Quantity updated to {item.quantity}',
            'quantity': item.quantity,
            'subtotal': float(item.get_subtotal()),
            'cart_count': cart.items.count(),
            'cart_subtotal': float(cart.get_subtotal())
        })
    elif action == 'decrement' and item.quantity > 1:
        item.quantity -= 1
        item.save()
        return JsonResponse({
            'success': True,
            'message': f'Quantity updated to {item.quantity}',
            'quantity': item.quantity,
            'subtotal': float(item.get_subtotal()),
            'cart_count': cart.items.count(),
            'cart_subtotal': float(cart.get_subtotal())
        })
    elif action == 'remove':
        item.delete()
        return JsonResponse({
            'success': True,
            'message': 'Item removed from cart',
            'cart_count': cart.items.count(),
            'cart_subtotal': float(cart.get_subtotal())
        })
    else:
        return JsonResponse({'success': False, 'message': f'Invalid action: {action}'}, status=400)

@login_required
def clear_cart(request):
    cart = get_object_or_404(Cart, user=request.user)
    cart.items.all().delete()
    request.session.pop('applied_coupon', None)
    request.session.pop('applied_offers', None)
    request.session.modified = True
    messages.success(request, "Cart cleared successfully.")
    return redirect('cart_and_orders_app:user_cart_list')

@login_required
@require_POST
def buy_now(request):
    try:
        data = json.loads(request.body) if request.body else request.POST
        variant_id = data.get('variant_id')
        quantity = int(data.get('quantity', 1))
        variant = get_object_or_404(ProductVariant, id=variant_id)
        if not variant.is_active or not variant.product.is_active or not variant.product.category.is_active:
            return JsonResponse({'success': False, 'message': 'This product is not available.'}, status=400)
        if variant.stock < quantity:
            return JsonResponse({'success': False, 'message': f'Only {variant.stock} items left in stock.'}, status=400)
        MAX_QUANTITY = 10
        if quantity > MAX_QUANTITY:
            return JsonResponse({'success': False, 'message': f'Maximum limit of {MAX_QUANTITY} reached.'}, status=400)
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart.items.all().delete()
        cart_item = CartItem.objects.create(cart=cart, variant=variant, quantity=quantity)
        primary_image = variant.primary_image
        if primary_image and hasattr(primary_image, 'image') and primary_image.image:
            variant_image = primary_image.image.url
        elif variant.product.primary_image and hasattr(variant.product.primary_image, 'image') and variant.product.primary_image.image:
            variant_image = variant.product.primary_image.image.url
        else:
            variant_image = None
        request.session['from_buy_now'] = True
        return JsonResponse({
            'success': True,
            'message': 'Proceeding to checkout with selected item.',
            'cart_count': cart.get_total_items(),
            'redirect': '/checkout/',
            'variant_image': variant_image
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@require_POST
def set_buy_now_flag(request):
    request.session['buy_now'] = True
    request.session.modified = True
    return JsonResponse({'status': 'success', 'message': 'Buy now flag set'})

@login_required
@never_cache
def user_wishlist(request):
    wishlist_items = Wishlist.objects.filter(user=request.user).select_related(
        'variant__product', 'variant__product__category', 'variant__product__brand'
    ).prefetch_related('variant__variant_images')
    context = {
        'wishlist_items': wishlist_items,
        'wishlist_count': wishlist_items.count(),
    }
    return render(request, 'cart_and_orders_app/user_wishlist.html', context)

@login_required
def user_add_to_wishlist(request, variant_id=None):
    try:
        if variant_id is None:
            data = json.loads(request.body) if request.body else {}
            variant_id = data.get('variant_id')
        variant = get_object_or_404(ProductVariant, id=variant_id)

        if not variant.is_active or not variant.product.is_active or not variant.product.category.is_active:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': 'This product is not available.'}, status=400)
            messages.error(request, "This product is not available.")
            return redirect('product_app:user_product_detail', slug=variant.product.slug)

        wishlist_item, created = Wishlist.objects.get_or_create(user=request.user, variant=variant)
        wishlist_count = Wishlist.objects.filter(user=request.user).count()

        variant_image = variant.primary_image.image.url if variant.primary_image else 'https://via.placeholder.com/40?text=No+Image'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': created,
                'message': f"{variant.product.product_name} {'added to' if created else 'already in'} your wishlist!",
                'wishlist_count': wishlist_count,
                'wishlist_item': {
                    'id': wishlist_item.id,
                    'variant_id': variant.id,
                    'product_name': variant.product.product_name,
                    'product_slug': variant.product.slug,
                    'flavor': variant.flavor or 'Standard',
                    'size_weight': variant.size_weight or 'N/A',
                    'price': str(variant.best_price),
                    'stock': variant.stock,
                    'image': variant_image
                } if created else None
            })

        if created:
            messages.success(request, f"{variant.product.product_name} added to wishlist!")
        else:
            messages.info(request, f"{variant.product.product_name} is already in your wishlist.")
        return redirect('cart_and_orders_app:user_wishlist')
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@require_POST
def user_remove_from_wishlist_by_variant(request, variant_id=None):
    try:
        if variant_id is None:
            data = json.loads(request.body) if request.body else {}
            variant_id = data.get('variant_id')
        if not variant_id:
            return JsonResponse({'success': False, 'message': 'Variant ID is required.'}, status=400)

        wishlist_item = Wishlist.objects.filter(user=request.user, variant_id=variant_id).first()
        if not wishlist_item:
            return JsonResponse({
                'success': False,
                'message': 'Item not found in your wishlist.',
                'wishlist_count': Wishlist.objects.filter(user=request.user).count()
            }, status=404)

        product_name = wishlist_item.variant.product.product_name
        wishlist_item.delete()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f"{product_name} removed from wishlist.",
                'wishlist_count': Wishlist.objects.filter(user=request.user).count()
            })

        messages.success(request, f"{product_name} removed from wishlist.")
        return redirect('cart_and_orders_app:user_wishlist')
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'An error occurred. Please try again.'}, status=500)


import logging
logger = logging.getLogger(__name__)
@login_required
@never_cache
def user_checkout(request):
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.all().select_related('variant__product')
    if not cart_items:
        messages.error(request, "Your cart is empty.")
        return redirect('cart_and_orders_app:user_cart_list')

    out_of_stock_items = [item for item in cart_items if item.quantity > item.variant.stock]
    if out_of_stock_items:
        messages.error(request, "Some items are out of stock. Please update your cart.")
        return redirect('cart_and_orders_app:user_cart_list')

    addresses = Address.objects.filter(user=request.user)
    default_address = addresses.filter(is_default=True).first()
    if not addresses:
        messages.warning(request, "Please add a shipping address.")
        return redirect('user_app:user_address_list')

    coupon = None
    applied_coupon = request.session.get('applied_coupon')
    if applied_coupon:
        try:
            coupon = Coupon.objects.get(id=applied_coupon['coupon_id'], code=applied_coupon['code'])
            if not coupon.is_valid():
                del request.session['applied_coupon']
                request.session.modified = True
                coupon = None
                messages.warning(request, "The applied coupon is no longer valid and has been removed.")
        except Coupon.DoesNotExist:
            del request.session['applied_coupon']
            request.session.modified = True
            coupon = None
            messages.warning(request, "The applied coupon is invalid and has been removed.")

    try:
        total, discount_info = apply_offers_to_cart(cart_items, coupon, user=request.user)
        subtotal = Decimal(str(discount_info['subtotal']))
        if subtotal <= 0 and cart_items.exists():
            messages.error(request, "Cart calculation error. Please check your cart items.")
            return redirect('cart_and_orders_app:user_cart_list')
    except Exception as e:
        logger.error(f"Error calculating cart totals for user {request.user.username}: {str(e)}")
        messages.error(request, "Unable to process cart due to invalid product data.")
        return redirect('cart_and_orders_app:user_cart_list')

    offer_discount = Decimal(str(discount_info['offer_discount']))
    coupon_discount = Decimal(str(discount_info.get('coupon_discount', 0.00)))
    shipping_cost = Decimal(str(discount_info['shipping_cost']))
    coupon_code = applied_coupon['code'] if applied_coupon else None

    offer_details = []
    for item in cart_items:
        best_price_info = item.variant.best_price
        discount = (best_price_info['original_price'] - best_price_info['price']) * Decimal(str(item.quantity))
        if best_price_info.get('applied_offer_type') in ['product', 'category']:
            offer_details.append({
                'variant_id': item.variant.id,
                'product': item.variant.product.product_name,
                'offer_type': best_price_info['applied_offer_type'],
                'offer_name': best_price_info.get('offer_name', 'N/A'),
                'quantity': item.quantity,
                'discount': float(discount)
            })
    request.session['applied_offers'] = offer_details
    request.session.modified = True

    tax = subtotal * Decimal('0.05')
    total = subtotal - offer_discount - coupon_discount + shipping_cost + tax

    if request.method == 'POST' and 'checkout_form' in request.POST:
        form = OrderCreateForm(request.POST, user=request.user)
        if form.is_valid():
            request.session['checkout_data'] = {
                'shipping_address_id': form.cleaned_data['shipping_address'].id,
                'payment_method': form.cleaned_data['payment_method'],
            }
            return redirect('cart_and_orders_app:place_order')
    else:
        initial_data = {
            'shipping_address': default_address,
            'payment_method': 'COD',
        }
        form = OrderCreateForm(user=request.user, initial=initial_data)

    try:
        wallet = Wallet.objects.get(user=request.user)
        wallet_balance = wallet.balance
    except Wallet.DoesNotExist:
        wallet_balance = Decimal('0.00')

    context = {
        'cart_items': cart_items,
        'addresses': addresses,
        'default_address': default_address,
        'subtotal': float(subtotal),
        'offer_discount': float(offer_discount),
        'coupon_discount': float(coupon_discount),
        'coupon_code': coupon_code,
        'shipping_cost': float(shipping_cost),
        'tax': float(tax),
        'total': float(total),
        'is_buy_now': request.session.get('from_buy_now', False),
        'form': form,
        'wallet_balance': float(wallet_balance),
        'offer_details': offer_details
    }
    if 'from_buy_now' in request.session:
        del request.session['from_buy_now']
        request.session.modified = True

    logger.info(f"User {request.user.username} accessed checkout with subtotal INR {subtotal:.2f}, coupon: {coupon_code or 'None'}")
    return render(request, 'cart_and_orders_app/checkout.html', context)

@login_required
@require_POST
@never_cache
def place_order(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

    try:
        cart = get_object_or_404(Cart, user=request.user)
        cart_items = cart.items.all().select_related('variant__product')
        if not cart_items:
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=400)

        out_of_stock_items = [item for item in cart_items if item.quantity > item.variant.stock]
        if out_of_stock_items:
            return JsonResponse({'success': False, 'message': 'Some items are out of stock.'}, status=400)

        shipping_address_id = request.POST.get('selected_address')
        payment_method = request.POST.get('payment_method')
        shipping_address = get_object_or_404(Address, id=shipping_address_id, user=request.user)
        if not shipping_address:
            return JsonResponse({'success': False, 'message': 'Invalid shipping address.'}, status=400)

        if payment_method not in ['COD', 'CARD', 'WALLET']:
            return JsonResponse({'success': False, 'message': 'Invalid payment method.'}, status=400)

        coupon = None
        applied_coupon = request.session.get('applied_coupon')
        if applied_coupon:
            try:
                coupon = Coupon.objects.get(id=applied_coupon['coupon_id'], code=applied_coupon['code'])
            except Coupon.DoesNotExist:
                coupon = None

        # Calculate totals using apply_offers_to_cart for consistency
        total, discount_info = apply_offers_to_cart(cart_items, coupon, user=request.user)
        subtotal = Decimal(str(discount_info['subtotal']))
        offer_discount = Decimal(str(discount_info['offer_discount']))
        coupon_discount = Decimal(str(discount_info['coupon_discount']))
        shipping_cost = Decimal(str(discount_info['shipping_cost']))
        tax = subtotal * Decimal('0.05')
        total = subtotal - offer_discount - coupon_discount + shipping_cost + tax

        offer_details = []
        for item in cart_items:
            best_price_info = item.variant.best_price
            discount = (best_price_info['original_price'] - best_price_info['price']) * Decimal(str(item.quantity))
            if best_price_info.get('applied_offer_type') in ['product', 'category']:
                offer_details.append({
                    'variant_id': item.variant.id,
                    'product': item.variant.product.product_name,
                    'offer_type': best_price_info['applied_offer_type'],
                    'offer_name': best_price_info.get('offer_name', 'N/A'),
                    'quantity': item.quantity,
                    'discount': float(discount)
                })

        if payment_method == 'COD':
            if total > Decimal('1000.0'):
                return JsonResponse({
                    'success': False,
                    'message': 'Cash on Delivery is not available for orders above Rs 1000.'
                }, status=400)
            with transaction.atomic():
                order = Order.objects.create(
                    user=request.user,
                    shipping_address=shipping_address,
                    total_amount=total,
                    discount_amount=offer_discount + coupon_discount,
                    status='Pending',
                    payment_method=payment_method,
                    coupon=coupon
                )
                for item in cart_items:
                    OrderItem.objects.create(
                        order=order,
                        variant=item.variant,
                        quantity=item.quantity,
                        price=Decimal(str(item.variant.best_price['price'])),
                        applied_offer=item.applied_offer
                    )
                order.decrease_stock()
                cart_items.delete()
                if 'applied_coupon' in request.session:
                    coupon_user, created = UserCoupon.objects.get_or_create(user=request.user, coupon=coupon)
                    if not created:
                        coupon_user.is_used = True
                        coupon_user.used_at = timezone.now()
                        coupon_user.order = order
                        coupon_user.save()
                        coupon.usage_count = F('usage_count') + 1
                        coupon.save()
                    del request.session['applied_coupon']
                request.session['applied_offers'] = []
                request.session.modified = True
                logger.info(f"User {request.user.username} placed COD order {order.order_id} for INR {total:.2f}")
                return JsonResponse({
                    'success': True,
                    'message': 'Order placed successfully!',
                    'redirect': reverse('cart_and_orders_app:order_success', kwargs={'order_id': order.order_id})
                })

        elif payment_method == 'WALLET':
            wallet = Wallet.objects.get(user=request.user)
            if wallet.balance < total:
                return JsonResponse({'success': False, 'message': 'Insufficient wallet balance.'}, status=400)
            with transaction.atomic():
                wallet.deduct_funds(total)
                wallet_transaction = WalletTransaction.objects.create(
                    wallet=wallet,
                    amount=total,
                    transaction_type='DEBIT',
                    description=f'Order payment'
                )
                order = Order.objects.create(
                    user=request.user,
                    shipping_address=shipping_address,
                    total_amount=total,
                    discount_amount=offer_discount + coupon_discount,
                    status='Completed',
                    payment_method=payment_method,
                    coupon=coupon
                )
                for item in cart_items:
                    OrderItem.objects.create(
                        order=order,
                        variant=item.variant,
                        quantity=item.quantity,
                        price=Decimal(str(item.variant.best_price['price'])),
                        applied_offer=item.applied_offer
                    )
                order.decrease_stock()
                cart_items.delete()
                if 'applied_coupon' in request.session:
                    coupon_user, created = UserCoupon.objects.get_or_create(user=request.user, coupon=coupon)
                    if not created:
                        coupon_user.is_used = True
                        coupon_user.used_at = timezone.now()
                        coupon_user.order = order
                        coupon_user.save()
                        coupon.usage_count = F('usage_count') + 1
                        coupon.save()
                    del request.session['applied_coupon']
                request.session['applied_offers'] = []
                request.session.modified = True
                logger.info(f"User {request.user.username} placed Wallet order {order.order_id} for INR {total:.2f}")
                return JsonResponse({
                    'success': True,
                    'message': 'Order placed successfully using Wallet!',
                    'redirect': reverse('cart_and_orders_app:order_success', kwargs={'order_id': order.order_id})
                })

        else:  # CARD
            with transaction.atomic():
                order = Order.objects.create(
                    user=request.user,
                    shipping_address=shipping_address,
                    total_amount=total,
                    discount_amount=offer_discount + coupon_discount,
                    status='Pending',
                    payment_method=payment_method,
                    coupon=coupon
                )
                for item in cart_items:
                    OrderItem.objects.create(
                        order=order,
                        variant=item.variant,
                        quantity=item.quantity,
                        price=Decimal(str(item.variant.best_price['price'])),
                        applied_offer=item.applied_offer
                    )
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            razorpay_order = client.order.create({
                'amount': int(total * 100),
                'currency': 'INR',
                'payment_capture': 1
            })
            order.razorpay_order_id = razorpay_order['id']
            order.save()
            request.session['applied_offers'] = offer_details
            request.session.modified = True
            logger.info(f"User {request.user.username} initiated Razorpay order {order.order_id} for INR {total:.2f}")
            return JsonResponse({
                'success': True,
                'razorpay_order': razorpay_order,
                'razorpay_key': settings.RAZORPAY_KEY_ID,
                'amount': int(total * 100),
                'currency': 'INR',
                'name': 'Core Fitness',
                'description': 'Order Payment',
                'callback_url': reverse('cart_and_orders_app:razorpay_callback') + f"?address_id={shipping_address_id}",
                'prefill': {
                    'name': request.user.get_full_name() or request.user.username,
                    'email': request.user.email,
                    'contact': shipping_address.phone if hasattr(shipping_address, 'phone') else ''
                }
            })

    except Exception as e:
        logger.error(f"Error placing order for user {request.user.username}: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': f'An error occurred: {str(e)}'}, status=500)

@login_required
@never_cache
def user_order_success(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    context = {'order': order}
    return render(request, 'order_success.html', context)

@login_required
def user_order_list(request):
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    has_razorpay_fields = hasattr(Order, 'razorpay_order_id')
    
    if has_razorpay_fields:
        incomplete_razorpay_orders = Order.objects.filter(
            user=request.user,
            status='PENDING',
            razorpay_order_id__isnull=False,
            razorpay_payment_id__isnull=True
        ).order_by('-created_at')
    else:
        incomplete_razorpay_orders = Order.objects.filter(
            user=request.user,
            status='PENDING'
        ).order_by('-created_at')
    context = {
        'orders': orders,
        'incomplete_razorpay_orders': incomplete_razorpay_orders
    }
    return render(request, 'user_order_list.html', context)

@login_required
def user_order_detail(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    return_form = ReturnRequestForm(order=order)
    subtotal = sum(item.price * item.quantity for item in order.items.all())
    
    total_offer_discount = Decimal('0.00')
    offer_details = []
    for item in order.items.all():
        best_price_info = item.variant.best_price
        discount = (best_price_info['original_price'] - item.price) * Decimal(str(item.quantity))
        total_offer_discount += discount
        if item.applied_offer in ['product', 'category']:
            offer_details.append({
                'product': item.variant.product.product_name,
                'offer_type': item.applied_offer,
                'offer_name': best_price_info['applied_offer_name'],
                'quantity': item.quantity,
                'discount': float(discount)
            })

    shipping_cost = Decimal('50.0') if subtotal < 2500 else Decimal('0.00')
    
    context = {
        'order': order,
        'return_form': return_form,
        'subtotal': subtotal,
        'total_offer_discount': total_offer_discount,
        'shipping_cost': shipping_cost,
        'offer_details': offer_details
    }
    return render(request, 'cart_and_orders_app/user_order_detail.html', context)

@login_required
@require_POST
def user_cancel_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        if order.status in ['Pending', 'Shipped']:
            order.status = 'Cancelled'
            order.save()
            order.restore_stock()
            messages.success(request, f"Order {order.order_id} has been cancelled.")
            return redirect('cart_and_orders_app:user_order_list')
        else:
            messages.error(request, "This order cannot be cancelled.")
            return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    context = {'order': order}
    return render(request, 'user_cancel_order.html', context)

@login_required
def user_return_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if request.method == 'POST':
        form = ReturnRequestForm(request.POST, order=order)
        if form.is_valid():
            if order.status == 'Delivered':
                ReturnRequest.objects.create(order=order, reason=form.cleaned_data['reason'])
                messages.success(request, "Return request submitted. We will process it shortly.")
                return redirect('cart_and_orders_app:user_order_list')
            else:
                messages.error(request, "This order cannot be returned.")
        else:
            messages.error(request, "Invalid return request. Please provide a valid reason.")
        return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)

def generate_pdf(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    template = get_template('invoice.html')
    context = {'order': order}
    html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=invoice_{order.order_id}.pdf'
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error generating PDF', status=500)
    return response

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_bulk_actions(request):
    if request.method == 'POST':
        order_ids = request.POST.getlist('order_ids')
        action = request.POST.get('action')
        if not order_ids or not action:
            messages.error(request, "No orders or action selected.")
            return redirect('cart_and_orders_app:admin_orders_list')
        orders = Order.objects.filter(id__in=order_ids)
        if not orders.exists():
            messages.error(request, "No valid orders found for the selected action.")
            return redirect('cart_and_orders_app:admin_orders_list')
        if action == 'mark_shipped':
            valid_orders = orders.filter(status='Pending')
            count = valid_orders.update(status='Shipped')
            if count > 0:
                messages.success(request, f"Marked {count} order(s) as Shipped.")
            else:
                messages.warning(request, "No Pending orders were marked as Shipped.")
        
        elif action == 'mark_delivered':
            valid_orders = orders.filter(status='Shipped')
            count = valid_orders.update(status='Delivered')
            if count > 0:
                messages.success(request, f"Marked {count} order(s) as Delivered.")
            else:
                messages.warning(request, "No Shipped orders were marked as Delivered.")
        
        elif action == 'cancel':
            valid_orders = orders.exclude(status__in=['Cancelled', 'Delivered'])
            count = valid_orders.count()
            if count > 0:
                valid_orders.update(status='Cancelled')
                for order in valid_orders:
                    order.restore_stock()
                messages.success(request, f"Cancelled {count} order(s) and restored stock.")
            else:
                messages.warning(request, "No eligible orders were cancelled.")
        
        else:
            messages.error(request, "Invalid action selected.")
        
        return redirect('cart_and_orders_app:admin_orders_list')
    return redirect('cart_and_orders_app:admin_orders_list')

@login_required
@csrf_exempt
def razorpay_callback(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    
    try:
        payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        signature = request.POST.get('razorpay_signature')
        
        if not all([payment_id, razorpay_order_id, signature]):
            return JsonResponse({'success': False, 'message': 'Missing payment details'}, status=400)

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }
        try:
            client.utility.verify_payment_signature(params_dict)
        except Exception:
            return JsonResponse({'success': False, 'message': 'Payment verification failed'}, status=400)
        
        try:
            order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user, status='Pending')
            with transaction.atomic():
                order.status = 'Completed'
                order.payment_id = payment_id
                order.save()
                order.decrease_stock()

                if order.coupon:
                    user_coupon = UserCoupon.objects.filter(user=request.user, coupon=order.coupon, is_used=False).first()
                    if user_coupon:
                        order.coupon.usage_count += 1
                        order.coupon.save()
                        user_coupon.is_used = True
                        user_coupon.used_at = timezone.now()
                        user_coupon.order = order
                        user_coupon.save()
                    if 'applied_coupon' in request.session:
                        del request.session['applied_coupon']
                        request.session.modified = True

                return JsonResponse({
                    'success': True,
                    'message': 'Payment successful!',
                    'redirect': reverse('cart_and_orders_app:order_success', kwargs={'order_id': order.order_id})
                })
        except Order.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Order not found.'}, status=400)
        except Exception:
            return JsonResponse({'success': False, 'message': 'Failed to process payment.'}, status=500)
    
    except Exception:
        return JsonResponse({'success': False, 'message': 'An error occurred during callback processing.'}, status=400)

@login_required
def initiate_payment(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.all()
    if not cart_items:
        return JsonResponse({'success': False, 'message': 'Cart is empty'}, status=400)

    subtotal = sum(Decimal(str(item.variant.best_price)) * item.quantity for item in cart_items)
    shipping_cost = Decimal('50.00')
    tax = subtotal * Decimal('0.05')
    discount = Decimal(request.session.get('applied_coupon', {}).get('discount', 0))
    total = subtotal + shipping_cost + tax - discount

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    
    try:
        razorpay_order = client.order.create({
            'amount': int(total * 100),
            'currency': 'INR',
            'payment_capture': 1
        })

        return JsonResponse({
            'success': True,
            'razorpay_key': settings.RAZORPAY_KEY_ID,
            'amount': int(total * 100),
            'currency': 'INR',
            'name': 'Core Fitness',
            'description': 'Order Payment',
            'razorpay_order': razorpay_order,
            'prefill': {
                'name': request.user.get_full_name() or request.user.username,
                'email': request.user.email,
                'contact': ''
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Failed to initiate payment: {str(e)}'}, status=500)

@login_required
def retry_payment(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user, payment_method='CARD', razorpay_payment_id__isnull=True, status='Pending')
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    razorpay_order = client.order.create({
        'amount': int(order.total_amount * 100),
        'currency': 'INR',
        'payment_capture': 1
    })
    order.razorpay_order_id = razorpay_order['id']
    order.save()
    return JsonResponse({
        'success': True,
        'razorpay_order': razorpay_order,
        'razorpay_key': settings.RAZORPAY_KEY_ID,
        'amount': int(order.total_amount * 100),
        'currency': 'INR',
        'name': 'Core Fitness',
        'description': 'Order Payment',
        'callback_url': f"/cart/razorpay-callback/?address_id={order.shipping_address.id}",
        'prefill': {
            'name': request.user.get_full_name() or request.user.username,
            'email': request.user.email,
            'contact': order.shipping_address.phone if hasattr(order.shipping_address, 'phone') else ''
        }
    })

def download_invoice(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    template = get_template('invoice.html')
    context = {'order': order}
    html = template.render(context)
    buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=buffer)
    if pisa_status.err:
        return HttpResponse('Error generating PDF', status=500)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=invoice_{order.order_id}.pdf'
    return response

@staff_member_required
def sales_dashboard(request):
    today = timezone.now().date()
    today_orders = Order.objects.filter(order_date__date=today)
    
    total_orders = Order.objects.count()
    total_revenue = Order.objects.filter(status='Delivered').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    average_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    context = {
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'average_order_value': average_order_value,
        'today_orders': today_orders,
    }
    
    return render(request, 'cart_and_orders_app/sales_dashboard.html', context)

@staff_member_required
def generate_sales_report(request):
    if request.method == 'POST':
        form = SalesReportForm(request.POST)
        if form.is_valid():
            report_type = form.cleaned_data['report_type']
            
            today = timezone.now().date()
            
            if report_type == 'DAILY':
                start_date = today
                end_date = today
            elif report_type == 'WEEKLY':
                start_date = today - timedelta(days=today.weekday())
                end_date = start_date + timedelta(days=6)
            elif report_type == 'MONTHLY':
                start_date = today.replace(day=1)
                if today.month == 12:
                    end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            elif report_type == 'YEARLY':
                start_date = today.replace(month=1, day=1)
                end_date = today.replace(month=12, day=31)
            else:
                start_date = form.cleaned_data['start_date']
                end_date = form.cleaned_data['end_date']
            
            orders = Order.objects.filter(
                order_date__date__gte=start_date,
                order_date__date__lte=end_date
            )
            
            total_orders = orders.count()
            total_sales = orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            total_discount = orders.aggregate(Sum('discount_amount'))['discount_amount__sum'] or 0
            
            report = SalesReport.objects.create(
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
                total_orders=total_orders,
                total_sales=total_sales,
                total_discount=total_discount
            )
            
            context = {
                'form': form,
                'report': report,
                'orders': orders,
                'start_date': start_date,
                'end_date': end_date,
            }
            
            if 'export' in request.POST:
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = f'attachment; filename="sales_report_{start_date}_to_{end_date}.csv"'
                
                writer = csv.writer(response)
                writer.writerow(['Order ID', 'Date', 'Customer', 'Total Amount', 'Discount', 'Status'])
                
                for order in orders:
                    writer.writerow([
                        order.order_id,
                        order.order_date.strftime('%Y-%m-%d %H:%M'),
                        order.user.username,
                        order.total_amount,
                        order.discount_amount,
                        order.status
                    ])
                
                return response
            
            return render(request, 'cart_and_orders_app/sales_report.html', context)
            
    else:
        form = SalesReportForm()
    
    return render(request, 'cart_and_orders_app/generate_sales_report.html', {'form': form})

@staff_member_required
def sales_report_detail(request, report_id):
    report = SalesReport.objects.get(id=report_id)
    orders = Order.objects.filter(
        order_date__date__gte=report.start_date,
        order_date__date__lte=report.end_date
    )
    
    context = {
        'report': report,
        'orders': orders,
    }
    
    return render(request, 'cart_and_orders_app/sales_report.html', context)