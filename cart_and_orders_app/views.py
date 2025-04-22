from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from offer_and_coupon_app.user_views import available_coupons
from decimal import Decimal
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count, F, Q
from .models import Order, SalesReport
from .forms import SalesReportForm, OrderCreateForm
from datetime import datetime, timedelta
import csv
from django.http import HttpResponse
from django.utils import timezone
from user_app.models import Address
from .forms import OrderStatusForm, ReturnRequestForm, OrderItemCancellationForm, OrderCancellationForm
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
@user_passes_test(is_admin)
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
        logger.info(f"Admin marked order {order.order_id} as delivered.")
        return JsonResponse({'success': True, 'message': 'Order marked as delivered.'})
    return render(request, 'cart_and_orders_app/admin_order_detail.html', {'order': order})

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
            logger.info(f"Admin updated order {order.order_id} status to {order.status}")
            return redirect('cart_and_orders_app:admin_orders_list')
    else:
        form = OrderStatusForm(instance=order)

    context = {
        'order': order,
        'form': form,
        'order_items': order.items.all(),
        'return_requests': order.return_requests.all(),
    }
    return render(request, 'cart_and_orders_app/admin_order_detail.html', context)

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
            logger.info(f"Admin approved return request for order {order.order_id}")
        elif action == 'reject':
            return_request.is_verified = False
            return_request.refund_processed = False
            return_request.save()
            messages.warning(request, f"Return request for {order.order_id} rejected")
            logger.info(f"Admin rejected return request for order {order.order_id}")
        return redirect('cart_and_orders_app:admin_orders_list')
    context = {'return_request': return_request, 'order': order}
    return render(request, 'cart_and_orders_app/admin_verify_return.html', context)

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
    return render(request, 'cart_and_orders_app/admin_inventory_list.html', context)

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
                logger.info(f"Admin updated stock for variant {variant.id} to {new_stock}")
                return redirect('cart_and_orders_app:admin_inventory_list')
            else:
                messages.error(request, "Stock cannot be negative")
        except ValueError:
            messages.error(request, "Invalid stock value")
    context = {'variant': variant}
    return render(request, 'cart_and_orders_app/admin_update_stock.html', context)

from decimal import Decimal
from django.views.decorators.cache import never_cache
@never_cache
@login_required
def user_cart_list(request):
    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        cart = Cart.objects.create(user=request.user)

    cart_items = cart.items.select_related('variant__product').all()

    # Calculate subtotal using raw prices
    cart_subtotal = sum(Decimal(str(item.price)) * item.quantity for item in cart_items)

    # Shipping cost
    shipping_cost = Decimal('50.0') if cart_subtotal < 2500 else Decimal('0.0')

    # Tax (5%)
    tax = cart_subtotal * Decimal('0.05')

    # Total
    cart_total = cart_subtotal + shipping_cost + tax

    # Clear offer-related session data
    request.session.pop('applied_offers', None)
    request.session.modified = True

    context = {
        'cart_items': cart_items,
        'cart_total_items': cart_items.count(),
        'cart_subtotal': float(cart_subtotal),
        'shipping_cost': float(shipping_cost),
        'tax': float(tax),
        'cart_total': float(cart_total),
        'has_out_of_stock': any(item.variant.stock == 0 for item in cart_items),
    }
    return render(request, 'cart_and_orders_app/user_cart_list.html', context)


@login_required
@require_POST
def user_add_to_cart(request, variant_id=None):
    try:
        request_data = json.loads(request.body) if request.body else {}
        variant_id = variant_id or request_data.get('variant_id')
        if not variant_id:
            return JsonResponse({'success': False, 'message': 'Variant ID is required.'}, status=400)

        variant = ProductVariant.objects.get(id=variant_id, is_active=True)
        if not variant.product.is_active or not variant.product.category.is_active:
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
        cart_item.price = variant.original_price  # Use raw price
        cart_item.applied_offer = None  # No offer applied
        cart_item.save()

        # Remove from wishlist if present
        Wishlist.objects.filter(user=request.user, variant=variant).delete()

        # Calculate cart subtotal
        cart_subtotal = sum(item.price * item.quantity for item in cart.items.all())

        # Get variant image
        variant_image = variant.primary_image.image.url if variant.primary_image else 'https://via.placeholder.com/50?text=No+Image'

        return JsonResponse({
            'success': True,
            'message': f'{variant.product.product_name} added to cart.',
            'cart_count': cart.items.count(),
            'cart_subtotal': float(cart_subtotal),
            'wishlist_count': Wishlist.objects.filter(user=request.user).count(),
            'variant_image': variant_image,
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
    try:
        cart = Cart.objects.get(user=request.user)
        item = CartItem.objects.get(id=item_id, cart=cart)
    except Cart.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Cart not found.'}, status=400)
    except CartItem.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Cart item not found.'}, status=400)

    action = request.POST.get('action')
    if action == 'increment' and item.quantity < item.variant.stock and item.quantity < 10:
        item.quantity += 1
    elif action == 'decrement' and item.quantity > 1:
        item.quantity -= 1
    elif action == 'remove':
        item.delete()
    else:
        return JsonResponse({'success': False, 'message': 'Invalid action.'}, status=400)

    if action != 'remove':
        item.price = item.variant.original_price  # Ensure raw price
        item.applied_offer = None  # No offer applied
        item.save()

    cart_items = cart.items.all()
    cart_subtotal = sum(Decimal(str(item.price)) * item.quantity for item in cart_items)

    response_data = {
        'success': True,
        'message': f'Quantity updated to {item.quantity}' if action != 'remove' else 'Item removed from cart',
        'quantity': item.quantity if action != 'remove' else 0,
        'subtotal': float(item.price * item.quantity) if action != 'remove' else 0.0,
        'cart_count': cart_items.count(),
        'cart_subtotal': float(cart_subtotal),
    }
    return JsonResponse(response_data)

@login_required
def clear_cart(request):
    cart = get_object_or_404(Cart, user=request.user)
    cart.items.all().delete()
    request.session.pop('applied_coupon', None)
    request.session.pop('applied_offers', None)
    request.session.modified = True
    messages.success(request, "Cart cleared successfully.")
    return redirect('cart_and_orders_app:user_cart_list')

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
            'cart_count': cart.items.count(),
            'redirect': '/checkout/',
            'variant_image': variant_image
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


from offer_and_coupon_app.utils import get_best_offer_for_product
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

    # Calculate totals directly
    subtotal = Decimal('0.00')
    offer_details = []
    for item in cart_items:
        best_price_info = item.variant.best_price
        unit_price = best_price_info['price']
        original_price = best_price_info['original_price']
        quantity = Decimal(str(item.quantity))
        item_subtotal = unit_price * quantity
        offer_discount = (original_price - unit_price) * quantity
        subtotal += item_subtotal
        if offer_discount > 0 and best_price_info['applied_offer_type'] in ['product', 'category']:
            offer_details.append({
                'product': item.variant.product.product_name,
                'offer_type': best_price_info['applied_offer_type'],
                'discount': str(offer_discount)
            })

    coupon = None
    coupon_discount = Decimal('0.00')
    coupon_code = None
    applied_coupon = request.session.get('applied_coupon')
    if applied_coupon:
        try:
            coupon = Coupon.objects.get(id=applied_coupon['coupon_id'], code=applied_coupon['code'])
            if coupon.is_valid() and coupon.minimum_order_amount <= subtotal:
                coupon_discount = (coupon.discount_percentage / 100) * subtotal
                if coupon_discount > subtotal:
                    coupon_discount = subtotal
                coupon_code = coupon.code
            else:
                del request.session['applied_coupon']
                request.session.modified = True
                messages.warning(request, "The applied coupon is invalid and has been removed.")
                coupon = None
        except Coupon.DoesNotExist:
            del request.session['applied_coupon']
            request.session.modified = True
            messages.warning(request, "The applied coupon is invalid and has been removed.")
            coupon = None

    tax = subtotal * Decimal('0.05')
    shipping_cost = Decimal('0.00') if subtotal >= 2500 else Decimal('70.00')
    offer_discount = sum((Decimal(str(item['discount'])) for item in offer_details), Decimal('0.00'))
    total = subtotal - offer_discount - coupon_discount + shipping_cost + tax
    cod_available = total <= 1000

    if request.method == 'POST' and 'checkout_form' in request.POST:
        form = OrderCreateForm(request.POST, user=request.user)
        if form.is_valid():
            # Store checkout data in session
            request.session['checkout_data'] = {
                'shipping_address_id': form.cleaned_data['shipping_address'].id,
                'payment_method': form.cleaned_data['payment_method'],
                'subtotal': float(subtotal),
                'offer_discount': float(offer_discount),
                'coupon_discount': float(coupon_discount),
                'shipping_cost': float(shipping_cost),
                'tax': float(tax),
                'total': float(total),
                'coupon_code': coupon_code,
                'offer_details': offer_details,
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
        'offer_details': offer_details,
        'cod_available': cod_available,
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
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({'success': False, 'message': 'User not authenticated'}, status=401)

        # Get cart and items
        cart = get_object_or_404(Cart, user=user)
        cart_items = cart.items.select_related('variant__product').all()
        if not cart_items:
            logger.warning(f"User {user.username} attempted to place order with empty cart")
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=400)

        # Check for out-of-stock items
        out_of_stock_items = [item for item in cart_items if item.quantity > item.variant.stock]
        if out_of_stock_items:
            logger.warning(f"User {user.username} attempted to place order with out-of-stock items")
            return JsonResponse({'success': False, 'message': 'Some items are out of stock.'}, status=400)

        # Check if user has addresses
        if not Address.objects.filter(user=user).exists():
            logger.warning(f"User {user.username} has no shipping addresses")
            return JsonResponse({
                'success': False,
                'message': 'Please add a shipping address before placing an order.',
                'redirect': reverse('user_app:user_address_list')
            }, status=400)

        # Validate checkout data from session or form
        checkout_data = request.session.get('checkout_data')
        if checkout_data:
            shipping_address = Address.objects.get(id=checkout_data['shipping_address_id'])
            payment_method = checkout_data['payment_method']
        else:
            form = OrderCreateForm(request.POST, user=user)
            if not form.is_valid():
                logger.warning(f"User {user.username} submitted invalid order form: {form.errors}")
                error_message = 'Please correct the following errors:'
                for field, errors in form.errors.items():
                    if field == '__all__':
                        error_message += ' ' + '; '.join(errors)
                    else:
                        error_message += f' {field}: {"; ".join(errors)}'
                return JsonResponse({
                    'success': False,
                    'message': error_message,
                    'errors': form.errors
                }, status=400)
            shipping_address = form.cleaned_data['shipping_address']
            payment_method = form.cleaned_data['payment_method']

        if payment_method not in ['COD', 'CARD', 'WALLET']:
            logger.warning(f"User {user.username} selected invalid payment method: {payment_method}")
            return JsonResponse({'success': False, 'message': 'Invalid payment method.'}, status=400)

        # Handle coupon from session
        coupon = None
        coupon_discount = Decimal('0.00')
        applied_coupon = request.session.get('applied_coupon')
        if applied_coupon:
            try:
                coupon = Coupon.objects.get(id=applied_coupon['coupon_id'], code=applied_coupon['code'])
                if coupon.is_valid():
                    subtotal = Decimal(str(checkout_data['subtotal'])) if checkout_data else cart.get_subtotal()
                    if coupon.minimum_order_amount <= subtotal:
                        coupon_discount = (coupon.discount_percentage / 100) * subtotal
                        if coupon_discount > subtotal:
                            coupon_discount = subtotal
            except Coupon.DoesNotExist:
                logger.warning(f"Coupon {applied_coupon['code']} does not exist for user {user.username}")
                del request.session['applied_coupon']
                request.session.modified = True
                coupon = None

        # Use totals from checkout_data if available, otherwise recalculate
        subtotal = Decimal(str(checkout_data['subtotal'])) if checkout_data and 'subtotal' in checkout_data else cart.get_subtotal()
        offer_discount = Decimal(str(checkout_data['offer_discount'])) if checkout_data and 'offer_discount' in checkout_data else sum((item.get_discount_amount() for item in cart_items), Decimal('0.00'))
        shipping_cost = Decimal(str(checkout_data['shipping_cost'])) if checkout_data and 'shipping_cost' in checkout_data else (Decimal('0.00') if subtotal >= 2500 else Decimal('70.00'))
        tax = Decimal(str(checkout_data['tax'])) if checkout_data and 'tax' in checkout_data else subtotal * Decimal('0.05')
        total = Decimal(str(checkout_data['total'])) if checkout_data and 'total' in checkout_data else (subtotal - offer_discount - coupon_discount + shipping_cost + tax)

        if subtotal <= 0:
            logger.error(f"Invalid subtotal {subtotal} for user {user.username}")
            return JsonResponse({'success': False, 'message': 'Invalid cart total.'}, status=400)

        logger.info(f"User {user.username} placing order: subtotal={subtotal}, offer_discount={offer_discount}, "
                    f"coupon_discount={coupon_discount}, shipping_cost={shipping_cost}, tax={tax}, total={total}, "
                    f"payment_method={payment_method}")

        with transaction.atomic():
            order = Order.objects.create(
                user=user,
                shipping_address=shipping_address,
                payment_method=payment_method,
                total_amount=total,
                discount_amount=offer_discount + coupon_discount,
                coupon=coupon,
                status='Pending'
            )
            order.cart_items.set(cart_items)

            if payment_method == 'COD':
                if total > Decimal('1000.00'):
                    logger.warning(f"User {user.username} attempted COD for order above 1000: {total}")
                    return JsonResponse({
                        'success': False,
                        'message': 'Cash on Delivery is not available for orders above ₹1000.'
                    }, status=400)
                order.status = 'Pending'

            elif payment_method == 'WALLET':
                wallet = get_object_or_404(Wallet, user=user)
                if wallet.balance < total:
                    logger.warning(f"User {user.username} has insufficient wallet balance: {wallet.balance} < {total}")
                    return JsonResponse({
                        'success': False,
                        'message': 'Insufficient wallet balance.'
                    }, status=400)
                wallet.balance -= total
                wallet.save()
                WalletTransaction.objects.create(
                    wallet=wallet,
                    amount=-total,
                    transaction_type='PURCHASE',
                    description=f"Order {order.order_id}"
                )
                order.status = 'Confirmed'
                order.decrease_stock()
                order.payment_status = 'PAID'
                logger.info(f"Wallet payment processed for user {user.username}, order {order.order_id}")

            elif payment_method == 'CARD':
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                payment_data = {
                    'amount': int(total * 100),
                    'currency': 'INR',
                    'receipt': f'order_{order.order_id}',
                    'payment_capture': 1
                }
                try:
                    razorpay_order = client.order.create(data=payment_data)
                    order.razorpay_order_id = razorpay_order['id']
                    order.save()
                    return JsonResponse({
                        'success': True,
                        'razorpay_order_id': razorpay_order['id'],
                        'amount': int(total * 100),
                        'currency': 'INR',
                        'key': settings.RAZORPAY_KEY_ID,
                        'description': f'Payment for order {order.order_id}',
                        'callback_url': request.build_absolute_uri(reverse('cart_and_orders_app:razorpay_callback')),
                        'order_id': order.order_id
                    })
                except razorpay.errors.BadRequestError as e:
                    logger.error(f"Razorpay error for user {user.username}: {str(e)}")
                    return JsonResponse({
                        'success': False,
                        'message': 'Payment processing failed. Please try again.'
                    }, status=500)

            order.save()
            if coupon:
                user_coupon, created = UserCoupon.objects.get_or_create(
                    user=user, coupon=coupon, defaults={'is_used': False}
                )
                if not user_coupon.is_used:
                    user_coupon.is_used = True
                    user_coupon.used_at = timezone.now()
                    user_coupon.order = order
                    user_coupon.save()
                    coupon.usage_count += 1
                    coupon.save()

            cart.items.all().delete()
            request.session.pop('applied_coupon', None)
            request.session.pop('applied_offers', None)
            request.session.pop('checkout_data', None)
            request.session.pop('from_buy_now', None)
            request.session.modified = True

            logger.info(f"Order {order.order_id} placed successfully by user {user.username}")

            return JsonResponse({
                'success': True,
                'message': 'Order placed successfully!',
                'order_id': order.order_id,
                'redirect': reverse('cart_and_orders_app:user_order_detail', args=[order.order_id])
            })

    except Exception as e:
        logger.error(f"Error placing order for user {user.username}: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while placing the order. Please try again.'
        }, status=500)

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
            order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user, status='Pending')
            order.payment_status = 'FAILED'
            order.save()
            return JsonResponse({
                'success': False,
                'message': 'Payment verification failed',
                'redirect': reverse('cart_and_orders_app:order_failure', kwargs={'order_id': order.order_id})
            })
        
        try:
            order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user, status='Pending')
            with transaction.atomic():
                order.status = 'Confirmed'
                order.payment_status = 'PAID'
                order.razorpay_payment_id = payment_id
                order.razorpay_signature = signature
                order.decrease_stock()
                order.save()

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
        except Exception as e:
            logger.error(f"Error in Razorpay callback for user {request.user.username}: {str(e)}")
            return JsonResponse({'success': False, 'message': 'Failed to process payment.'}, status=500)
    
    except Exception as e:
        logger.error(f"Unexpected error in Razorpay callback for user {request.user.username}: {str(e)}")
        return JsonResponse({'success': False, 'message': 'An error occurred during callback processing.'}, status=400)

@login_required
def initiate_payment(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.all()
    if not cart_items:
        logger.warning(f"User {request.user.username} attempted to initiate payment with empty cart")
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
        logger.info(f"Initiated Razorpay payment for user {request.user.username}, amount {total}")
        return JsonResponse({
            'success': True,
            'razorpay_key': settings.RAZORPAY_KEY_ID,
            'amount': int(total * 100),
            'currency': 'INR',
            'description': 'Order Payment',
            'razorpay_order': razorpay_order,
            'prefill': {
                'name': request.user.get_full_name() or request.user.username,
                'email': request.user.email,
                'contact': ''
            }
        })
    except Exception as e:
        logger.error(f"Failed to initiate payment for user {request.user.username}: {str(e)}")
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
        'description': 'Order Payment',
        'callback_url': f"/cart/razorpay-callback/?address_id={order.shipping_address.id}",
        'prefill': {
            'name': request.user.get_full_name() or request.user.username,
            'email': request.user.email,
            'contact': order.shipping_address.phone if hasattr(order.shipping_address, 'phone') else ''
        }
    })

@login_required
def download_invoice(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    # Calculate totals
    subtotal = sum(item.price * Decimal(str(item.quantity)) for item in order.items.all())
    total_offer_discount = sum(
        (item.variant.best_price['original_price'] - item.price) * Decimal(str(item.quantity))
        for item in order.items.all()
    )
    shipping_cost = Decimal('50.0') if subtotal < 2500 else Decimal('0.00')
    tax = subtotal * Decimal('0.05')
    coupon_discount = Decimal(str(order.discount_amount - total_offer_discount)) if order.coupon else Decimal('0.00')
    total = subtotal - total_offer_discount - coupon_discount + shipping_cost + tax

    context = {
        'order': order,
        'items': order.items.select_related('variant__product').all(),
        'subtotal': float(subtotal),
        'total_offer_discount': float(total_offer_discount),
        'coupon_discount': float(coupon_discount),
        'shipping_cost': float(shipping_cost),
        'tax': float(tax),
        'total': float(total),
        'company': {
            'name': 'Core Fitness Supplements Store',
            'address': '123 Fitness Lane, Bangalore, India',
            'phone': '+91 123 456 7890',
            'email': 'support@corefitness.com'
        },
        'date': order.order_date.strftime('%d %B %Y'),
        'order_id': order.order_id,
        'payment_method': order.payment_method,
        'shipping_address': order.shipping_address,
    }
    template = get_template('cart_and_orders_app/invoice_pdf.html')
    html = template.render(context)

    buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=buffer)
    if pisa_status.err:
        logger.error(f"Error generating PDF for order {order_id}: {pisa_status.err}")
        return HttpResponse('Error generating PDF', status=500)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
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

@login_required
def user_order_success(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if order.payment_status != 'PAID' or order.status not in ['Pending', 'Confirmed']:
        messages.error(request, "Invalid order status.")
        return redirect('cart_and_orders_app:user_order_list')

    context = {
        'order': order,
        'title': 'Order Success'
    }
    return render(request, 'cart_and_orders_app/order_success.html', context)

@login_required
def user_order_failure(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if order.payment_status != 'FAILED':
        messages.error(request, "Invalid order status.")
        return redirect('cart_and_orders_app:user_order_list')

    context = {
        'order': order,
        'title': 'Order Payment Failed'
    }
    return render(request, 'cart_and_orders_app/order_failure.html', context)

@login_required
def user_order_list(request):
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    incomplete_razorpay_orders = Order.objects.filter(
        user=request.user,
        status='Pending',
        razorpay_order_id__isnull=False,
        razorpay_payment_id__isnull=True
    ).order_by('-created_at')
    context = {
        'orders': orders,
        'incomplete_razorpay_orders': incomplete_razorpay_orders
    }
    return render(request, 'cart_and_orders_app/user_order_list.html', context)

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
        if item.applied_offer in ['product', 'category'] and best_price_info.get('applied_offer_name') != 'No Offer Applied':
            offer_details.append({
                'product': item.variant.product.product_name,
                'offer_type': item.applied_offer,
                'offer_name': best_price_info.get('applied_offer_name', 'No Offer Applied'),
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
        'offer_details': offer_details,
        'return_form': ReturnRequestForm(order=order),
    }
    return render(request, 'cart_and_orders_app/user_order_detail.html', context)

@login_required
@require_POST
def user_cancel_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if request.method == 'POST':
        form = OrderCancellationForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['reason']
            try:
                order.cancel_order(reason)
                messages.success(request, f"Order {order.order_id} has been cancelled.")
                logger.info(f"User {request.user.username} cancelled order {order.order_id}")
            except ValueError as e:
                messages.error(request, str(e))
                logger.warning(f"Failed to cancel order {order.order_id} for user {request.user.username}: {str(e)}")
            return redirect('cart_and_orders_app:user_order_list')
        else:
            messages.error(request, "Invalid cancellation request.")
    else:
        form = OrderCancellationForm()
    context = {'order': order, 'form': form}
    return render(request, 'cart_and_orders_app/cancel_order.html', context)

@login_required
@require_POST
def user_cancel_order_item(request, order_id, item_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    order_item = get_object_or_404(OrderItem, id=item_id, order=order)
    
    if request.method == 'POST':
        form = OrderItemCancellationForm(request.POST, order=order)
        if form.is_valid():
            reason = form.cleaned_data['reason']
            try:
                order.cancel_item(order_item, reason)
                messages.success(request, f"Item {order_item.variant.product.product_name} has been cancelled.")
                logger.info(f"User {request.user.username} cancelled item {order_item.id} in order {order.order_id}")
            except ValueError as e:
                messages.error(request, str(e))
                logger.warning(f"Failed to cancel item {order_item.id} for user {request.user.username}: {str(e)}")
            return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
        else:
            messages.error(request, "Invalid cancellation request.")
    else:
        form = OrderItemCancellationForm(order=order)
    
    context = {'order': order, 'form': form, 'order_item': order_item}
    return render(request, 'cart_and_orders_app/cancel_order_item.html', context)

@login_required
@require_POST  
def user_return_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if request.method == 'POST':
        form = ReturnRequestForm(request.POST, order=order)
        if form.is_valid():
            if order.status == 'Delivered':
                with transaction.atomic():
                    return_request = ReturnRequest.objects.create(order=order, reason=form.cleaned_data['reason'])
                    messages.success(request, "Return request submitted. We will process it shortly.")
                    logger.info(f"User {request.user.username} submitted return request for order {order.order_id}")
                return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
            else:
                messages.error(request, "This order cannot be returned.")
                logger.warning(f"User {request.user.username} attempted to return non-delivered order {order.order_id}")
        else:
            messages.error(request, "Invalid return request. Please provide a valid reason.")
            logger.warning(f"Invalid return request by user {request.user.username} for order {order.order_id}")
        return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    # Remove the GET rendering logic since the modal handles the form
    return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)

@login_required
def generate_pdf(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    # Calculate totals
    subtotal = sum(item.price * Decimal(str(item.quantity)) for item in order.items.all())
    total_offer_discount = sum(
        (item.variant.best_price['original_price'] - item.price) * Decimal(str(item.quantity))
        for item in order.items.all()
    )
    shipping_cost = Decimal('50.0') if subtotal < 2500 else Decimal('0.00')
    tax = subtotal * Decimal('0.05')
    coupon_discount = Decimal(str(order.discount_amount - total_offer_discount)) if order.coupon else Decimal('0.00')
    total = subtotal - total_offer_discount - coupon_discount + shipping_cost + tax

    context = {
        'order': order,
        'items': order.items.select_related('variant__product').all(),
        'subtotal': float(subtotal),
        'total_offer_discount': float(total_offer_discount),
        'coupon_discount': float(coupon_discount),
        'shipping_cost': float(shipping_cost),
        'tax': float(tax),
        'total': float(total),
        'company': {
            'name': 'Core Fitness Supplements Store',
            'address': '123 Fitness Lane, Bangalore, India',
            'phone': '+91 123 456 7890',
            'email': 'support@corefitness.com'
        },
        'date': order.order_date.strftime('%d %B %Y'),
        'order_id': order.order_id,
        'payment_method': order.payment_method,
        'shipping_address': order.shipping_address,
    }
    template = get_template('cart_and_orders_app/invoice.html')
    html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=invoice_{order.order_id}.pdf'
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        logger.error(f"Error generating PDF for order {order_id}: {pisa_status.err}")
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
                logger.info(f"Admin marked {count} orders as shipped")
            else:
                messages.warning(request, "No Pending orders were marked as Shipped.")
        elif action == 'mark_delivered':
            valid_orders = orders.filter(status='Shipped')
            count = valid_orders.update(status='Delivered')
            if count > 0:
                messages.success(request, f"Marked {count} order(s) as Delivered.")
                logger.info(f"Admin marked {count} orders as delivered")
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
                logger.info(f"Admin cancelled {count} orders")
            else:
                messages.warning(request, "No eligible orders were cancelled.")
        else:
            messages.error(request, "Invalid action selected.")
        return redirect('cart_and_orders_app:admin_orders_list')
    return redirect('cart_and_orders_app:admin_orders_list')