# Django core imports
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.conf import settings
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count, F, Q, DecimalField
from django.db.models.expressions import Subquery, OuterRef
from django.db.models.functions import TruncDay, TruncMonth
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache

# App model imports
from product_app.models import ProductVariant
from user_app.models import Address
from offer_and_coupon_app.models import Coupon, UserCoupon, Wallet, WalletTransaction
from .models import (
    Cart, CartItem, Wishlist, Order, OrderItem, 
    ReturnRequest, OrderCancellation, SalesReport
)

# Form imports
from .forms import (
    SalesReportForm, OrderCreateForm, OrderStatusForm, 
    ReturnRequestForm, OrderItemCancellationForm, OrderCancellationForm
)

# Third-party imports
import razorpay
import weasyprint
import csv
import json
from decimal import Decimal
from datetime import datetime, timedelta

def is_admin(user):
    return user.is_staff or user.is_superuser


@login_required
def user_cart_list(request):
    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        cart = Cart.objects.create(user=request.user)
    cart_items = cart.items.select_related('variant__product').prefetch_related('variant__variant_images').all()
    issues = []
    has_unavailable_items = False
    for item in cart_items:
        # Check if item is unavailable but do not delete it
        if not item.variant.is_active or not item.variant.product.is_active or not item.variant.product.category.is_active or not item.variant.product.brand.is_active:
            issues.append(f"{item.variant.product.product_name} ({item.variant_details}) is no longer available.")
            has_unavailable_items = True
            continue
        if item.quantity > item.variant.stock:
            issues.append(f"{item.variant.product.product_name} ({item.variant_details}) has only {item.variant.stock} items in stock.")
    totals = cart.get_totals()  
    cart_subtotal = totals['subtotal']
    shipping_cost = Decimal('0.00')
    cart_total = totals['total']
    request.session.pop('applied_offers', None)
    request.session.modified = True
    for issue in issues:
        messages.warning(request, issue)
    context = {
        'cart_items': cart_items,
        'cart_total_items': cart.get_total_items_in_cart(),
        'cart_subtotal': float(cart_subtotal),
        'shipping_cost': float(shipping_cost),
        'cart_total': float(cart_total),
        'has_out_of_stock': any(item.quantity > item.variant.stock for item in cart_items),
        'has_unavailable_items': has_unavailable_items,
        'is_free_delivery': cart_total > 0,  
    }
    return render(request, 'cart_and_orders_app/user_cart_list.html', context)


@login_required
@require_POST
def add_to_cart(request):
    try:
        data = json.loads(request.body)
        variant_id = data.get('variant_id')
        quantity = int(data.get('quantity', 1))
        
        if quantity < 1:
            return JsonResponse({'success': False, 'error': 'Invalid quantity'}, status=400)
        
        variant = get_object_or_404(ProductVariant, id=variant_id, is_active=True)
        if not variant.product.is_active or not variant.product.category.is_active or not variant.product.brand.is_active:
            return JsonResponse({'success': False, 'error': 'This product is not available'}, status=400)
        if variant.stock < quantity:
            return JsonResponse({'success': False, 'error': f'Only {variant.stock} items left in stock'}, status=400)
        
        cart, _ = Cart.objects.get_or_create(user=request.user)
        
        cart_item, created = cart.items.get_or_create(
            variant=variant, 
            defaults={'quantity': quantity}
        )
        
        if not created:
            new_quantity = cart_item.quantity + quantity
            if new_quantity > variant.stock:
                return JsonResponse({'success': False, 'error': f'Cannot exceed available stock ({variant.stock} items)'}, status=400)
            if new_quantity > 10:
                return JsonResponse({'success': False, 'error': 'Maximum quantity limit of 10 reached'}, status=400)
            cart_item.quantity = new_quantity
            cart_item.save()
        
        cart_count = cart.get_total_items_in_cart()
        
        return JsonResponse({
            'success': True,
            'cart_count': cart_count,
            'message': 'Added to cart successfully'
        })
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@require_POST
@login_required
def update_cart_quantity(request, item_id):
    action = request.POST.get('action')
    if action not in ['increment', 'decrement', 'remove']:
        return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
    
    try:
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        cart = cart_item.cart
        
        # Check if item is unavailable
        if not cart_item.variant.is_active or not cart_item.variant.product.is_active or not cart_item.variant.product.category.is_active or not cart_item.variant.product.brand.is_active:
            if action != 'remove':
                return JsonResponse({
                    'success': False,
                    'message': f'{cart_item.variant.product.product_name} is currently unavailable and cannot be modified. Please remove it from your cart.'
                }, status=400)
        
        if action == 'increment':
            if cart_item.quantity >= cart_item.variant.stock:
                return JsonResponse({
                    'success': False,
                    'message': f'Only {cart_item.variant.stock} items available in stock'
                }, status=400)
            if cart_item.quantity >= 5:
                return JsonResponse({
                    'success': False,
                    'message': 'Maximum quantity limit of 5 reached'
                }, status=400)
            cart_item.quantity += 1
            cart_item.save()
        elif action == 'decrement':
            if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Quantity cannot be less than 1'
                }, status=400)
        elif action == 'remove':
            cart_item.delete()
        
        totals = cart.get_totals()  
        cart_subtotal = totals['subtotal']
        shipping_cost = Decimal('0.00')
        cart_total = totals['total']
        
        item_subtotal = Decimal('0.0') if action == 'remove' else cart_item.get_subtotal()
        cart_count = cart.get_total_items_in_cart()
        
        return JsonResponse({
            'success': True,
            'quantity': 0 if action == 'remove' else cart_item.quantity,
            'subtotal': float(item_subtotal),
            'cart_subtotal': float(cart_subtotal),
            'shipping_cost': float(shipping_cost),
            'cart_total': float(cart_total),
            'cart_count': cart_count
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

    
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
def toggle_wishlist(request):
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = json.loads(request.body)
        variant_id = data.get('variant_id')
        
        try:
            variant = ProductVariant.objects.get(id=variant_id)
            wishlist_item = Wishlist.objects.filter(user=request.user, variant=variant)
            
            if wishlist_item.exists():
                # Remove from wishlist
                wishlist_item.delete()
                is_in_wishlist = False
            else:
                # Add to wishlist
                Wishlist.objects.create(user=request.user, variant=variant)
                is_in_wishlist = True
                
            # Count wishlist items for this user
            wishlist_count = Wishlist.objects.filter(user=request.user).count()
            
            return JsonResponse({
                'success': True,
                'is_in_wishlist': is_in_wishlist,
                'wishlist_count': wishlist_count
            })
            
        except ProductVariant.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Product variant not found'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@require_POST
@login_required
def buy_now(request):
    try:
        data = json.loads(request.body) if request.body else request.POST
        variant_id = data.get('variant_id')
        quantity = int(data.get('quantity', 1))
        variant = get_object_or_404(ProductVariant, id=variant_id)
        if not variant.is_active or not variant.product.is_active or not variant.product.category.is_active or not variant.product.brand.is_active:
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

@login_required
@never_cache
def user_checkout(request):
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.select_related('variant__product').all()
    if not cart_items:
        messages.error(request, "Your cart is empty.")
        return redirect('cart_and_orders_app:user_cart_list')
    
    # Check for unavailable or out-of-stock items
    unavailable_items = []
    out_of_stock_issues = []
    for item in cart_items:
        if not item.variant.is_active or not item.variant.product.is_active or not item.variant.product.category.is_active or not item.variant.product.brand.is_active:
            unavailable_items.append({
                'name': item.variant.product.product_name,
                'variant_details': item.variant_details
            })
        if item.quantity > item.variant.stock:
            out_of_stock_issues.append(f"{item.variant.product.product_name} ({item.variant_details}) has only {item.variant.stock} items in stock.")
    
    # If there are unavailable items, return JSON for AJAX/SweetAlert
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if unavailable_items:
            return JsonResponse({
                'success': False,
                'message': 'Some items in your cart are currently unavailable. Please remove them to proceed to checkout.',
                'unavailable_items': unavailable_items
            }, status=400)
        if out_of_stock_issues:
            return JsonResponse({
                'success': False,
                'message': 'Some items are out of stock. Please update your cart.',
                'issues': out_of_stock_issues
            }, status=400)
        return JsonResponse({'success': True})
    
    # For non-AJAX requests, handle redirects with messages
    if unavailable_items:
        for item in unavailable_items:
            messages.warning(request, f"{item['name']} ({item['variant_details']}) is no longer available.")
        messages.error(request, "Please remove unavailable items from your cart to proceed.")
        return redirect('cart_and_orders_app:user_cart_list')
    
    if out_of_stock_issues:
        for issue in out_of_stock_issues:
            messages.warning(request, issue)
        messages.error(request, "Some items are out of stock. Please update your cart.")
        return redirect('cart_and_orders_app:user_cart_list')
    
    # Get user addresses (no redirect if empty)
    addresses = Address.objects.filter(user=request.user)
    default_address = addresses.filter(is_default=True).first()
    
    applied_coupon = request.session.get('applied_coupon')
    coupon = None
    if applied_coupon:
        try:
            coupon = Coupon.objects.get(id=applied_coupon['coupon_id'], code=applied_coupon['code'])
            if not coupon.is_valid():
                del request.session['applied_coupon']
                request.session.modified = True
                messages.warning(request, "The applied coupon is invalid or expired and has been removed.")
                coupon = None
        except Coupon.DoesNotExist:
            del request.session['applied_coupon']
            request.session.modified = True
            messages.warning(request, "The applied coupon is invalid and has been removed.")
    
    totals = cart.get_totals(coupon=coupon)
    applicable_coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=timezone.now(),
        valid_to__gte=timezone.now(),
        minimum_order_amount__lte=totals['subtotal']
    ).exclude(
        id__in=UserCoupon.objects.filter(
            user=request.user,
            is_used=True
        ).values('coupon_id')
    ).order_by('-discount_percentage')
    
    cod_available = totals['total'] <= 1000
    initial_data = {
        'shipping_address': default_address,
        'payment_method': 'COD' if cod_available else 'CARD',
    }
    form = OrderCreateForm(user=request.user, initial=initial_data)
    
    try:
        wallet = Wallet.objects.get(user=request.user)
        wallet_balance = wallet.balance
        wallet_available = wallet_balance >= totals['total']
    except Wallet.DoesNotExist:
        wallet_balance = Decimal('0.00')
        wallet_available = False
    
    context = {
        'cart_items': cart_items,
        'addresses': addresses,
        'default_address': default_address,
        'subtotal': float(totals['subtotal']),
        'original_total': float(totals['original_total']),
        'offer_discount': float(totals['offer_discount']),
        'coupon_discount': float(totals['coupon_discount']),
        'coupon_code': totals['coupon_code'],
        'shipping_cost': float(Decimal('0.00')),
        'total': float(totals['total']),
        'total_quantity': totals['total_quantity'],
        'is_buy_now': request.session.get('from_buy_now', False),
        'form': form,
        'wallet_balance': float(wallet_balance),
        'wallet_available': wallet_available,
        'cod_available': cod_available,
        'is_free_delivery': True,
        'applicable_coupons': applicable_coupons,
    }
    
    if 'from_buy_now' in request.session:
        del request.session['from_buy_now']
        request.session.modified = True
    
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
        cart = get_object_or_404(Cart, user=user)
        cart_items = cart.items.select_related('variant__product').all()
        if not cart_items:
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=400)
        out_of_stock_items = []
        for item in cart_items:
            if item.quantity > item.variant.stock:
                out_of_stock_items.append(f"{item.variant.product.product_name} (Available: {item.variant.stock}, Requested: {item.quantity})")
        if out_of_stock_items:
            error_message = f"Insufficient stock for: {', '.join(out_of_stock_items)}"
            return JsonResponse({'success': False, 'message': error_message}, status=400)
        form = OrderCreateForm(request.POST, user=user)
        if not form.is_valid():
            error_message = 'Please correct the following errors: '
            for field, errors in form.errors.items():
                if field == '__all__':
                    error_message += '; '.join(errors)
                else:
                    error_message += f'{field}: {"; ".join(errors)} '
            return JsonResponse({
                'success': False,
                'message': error_message.strip(),
                'errors': form.errors
            }, status=400)
        shipping_address = form.cleaned_data['shipping_address']
        payment_method = form.cleaned_data['payment_method']
        if payment_method not in ['COD', 'CARD', 'WALLET']:
            return JsonResponse({'success': False, 'message': 'Invalid payment method.'}, status=400)
        applied_coupon = request.session.get('applied_coupon')
        coupon = None
        if applied_coupon:
            try:
                coupon = Coupon.objects.get(id=applied_coupon['coupon_id'], code=applied_coupon['code'])
                if not coupon.is_valid():
                    del request.session['applied_coupon']
                    request.session.modified = True
                    coupon = None
            except Coupon.DoesNotExist:
                del request.session['applied_coupon']
                request.session.modified = True
        totals = cart.get_totals(coupon=coupon)
        if totals['subtotal'] <= 0:
            return JsonResponse({'success': False, 'message': 'Invalid cart total.'}, status=400)
        
        with transaction.atomic():
            # Create the order
            order = Order(
                user=user,
                shipping_address=shipping_address,
                payment_method=payment_method,
                total_amount=totals['total'],
                coupon_discount=totals['coupon_discount'],
                coupon=coupon,
                status='Pending',
                payment_status='PENDING',
                order_date=timezone.now(),
                order_id=f"ORD-{timezone.now().strftime('%Y%m%d%H%M%S')}-{user.id}",
                address_full_name=shipping_address.full_name,
                address_line1=shipping_address.address_line1,
                address_line2=shipping_address.address_line2,
                address_city=shipping_address.city,
                address_state=shipping_address.state,
                address_postal_code=shipping_address.postal_code,
                address_country=shipping_address.country,
                address_phone=shipping_address.phone
            )
            order.save()

            # Create order items
            order_items = []
            for item in cart_items:
                order_items.append(
                    OrderItem(
                        order=order,
                        variant=item.variant,
                        quantity=item.quantity,
                        price=item.variant.best_price['price'],
                        applied_offer=item.variant.best_price.get('applied_offer_type', '')
                    )
                )
            OrderItem.objects.bulk_create(order_items)

            # Mark UserCoupon as used
            if coupon:
                try:
                    user_coupon = UserCoupon.objects.get(user=user, coupon=coupon, is_used=False)
                    user_coupon.is_used = True
                    user_coupon.used_at = timezone.now()
                    user_coupon.order = order
                    user_coupon.save()
                except UserCoupon.DoesNotExist:
                    order.coupon = None
                    order.recalculate_totals()
                    order.save()

            # Clear cart and session data
            cart.items.all().delete()
            request.session.pop('applied_coupon', None)
            request.session.modified = True
            if payment_method == 'COD':
                if totals['total'] > Decimal('1000.00'):
                    return JsonResponse({
                        'success': False,
                        'message': 'Cash on Delivery is not available for orders above ₹1000.'
                    }, status=400)
                order.status = 'Pending'
                order.payment_status = 'PENDING'
                order.decrease_stock()
                if coupon and coupon.is_valid():
                    try:
                        user_coupon = UserCoupon.objects.get(user=user, coupon=coupon, is_used=False)
                        user_coupon.is_used = True
                        user_coupon.used_at = timezone.now()
                        user_coupon.order = order
                        user_coupon.save()
                    except UserCoupon.DoesNotExist:
                        order.coupon = None
                        order.recalculate_totals()
                        order.save()
                order.save()
                return JsonResponse({
                    'success': True,
                    'message': 'Order placed successfully!',
                    'order_id': order.order_id,
                    'redirect': reverse('cart_and_orders_app:user_order_success', args=[order.order_id])  
                })
            elif payment_method == 'WALLET':
                try:
                    wallet = Wallet.objects.get(user=user)
                    if wallet.balance < totals['total']:
                        order.payment_status = 'FAILED'
                        order.save()
                        return JsonResponse({
                            'success': False,
                            'message': f'Insufficient wallet balance. Available: ₹{wallet.balance}, Required: ₹{totals["total"]}',
                            'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                        }, status=400)
                    with transaction.atomic():
                        wallet.balance -= totals['total']
                        wallet.save()
                        WalletTransaction.objects.create(
                            wallet=wallet,
                            amount=totals['total'],
                            transaction_type='DEBIT',
                            description=f"Order {order.order_id}"
                        )
                        order.status = 'Confirmed'
                        order.payment_status = 'PAID'
                        order.decrease_stock()
                        if coupon and coupon.is_valid():
                            try:
                                user_coupon = UserCoupon.objects.get(user=user, coupon=coupon, is_used=False)
                                user_coupon.is_used = True
                                user_coupon.used_at = timezone.now()
                                user_coupon.order = order
                                user_coupon.save()
                            except UserCoupon.DoesNotExist:
                                order.coupon = None
                                order.recalculate_totals()
                                order.save()
                        order.save()
                    return JsonResponse({
                        'success': True,
                        'message': 'Order placed successfully!',
                        'order_id': order.order_id,
                        'redirect': reverse('cart_and_orders_app:user_order_success', args=[order.order_id])
                    })
                except Exception as e:
                    order.payment_status = 'FAILED'
                    order.save()
                    return JsonResponse({
                        'success': False,
                        'message': f'Failed to process wallet payment: {str(e)}',
                        'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                    }, status=500)
            elif payment_method == 'CARD':
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                payment_data = {
                    'amount': int(totals['total'] * 100),
                    'currency': 'INR',
                    'receipt': f'order_{order.order_id}',
                    'payment_capture': 1
                }
                try:
                    razorpay_order = client.order.create(data=payment_data)
                    order.razorpay_order_id = razorpay_order['id']
                    order.total_amount = totals['total']
                    order.payment_status = 'PENDING'
                    order.save()
                    return JsonResponse({
                        'success': True,
                        'razorpay_order_id': razorpay_order['id'],
                        'amount': int(totals['total'] * 100),
                        'currency': 'INR',
                        'key': settings.RAZORPAY_KEY_ID,
                        'description': f'Payment for order {order.order_id}',
                        'callback_url': request.build_absolute_uri(reverse('cart_and_orders_app:razorpay_callback')),
                        'order_id': order.order_id,
                        'prefill': {
                            'name': user.get_full_name() or user.username,
                            'email': user.email or '',
                            'contact': shipping_address.phone if hasattr(shipping_address, 'phone') else ''
                        }
                    })
                except razorpay.errors.BadRequestError as e:
                    order.payment_status = 'FAILED'
                    order.save()
                    return JsonResponse({
                        'success': False,
                        'message': f'Payment processing failed: {str(e)}. Please try again.',
                        'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                    }, status=400)
                except razorpay.errors.ServerError as e:
                    order.payment_status = 'FAILED'
                    order.save()
                    return JsonResponse({
                        'success': False,
                        'message': 'Payment processing failed due to a server error. Please try again later.',
                        'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                    }, status=500)
                except Exception as e:
                    order.payment_status = 'FAILED'
                    order.save()
                    return JsonResponse({
                        'success': False,
                        'message': 'An unexpected error occurred during payment processing. Please try again.',
                        'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                    }, status=500)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An error occurred while placing the order: {str(e)}',
            'redirect': reverse('cart_and_orders_app:user_checkout')
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
            order = Order.objects.filter(razorpay_order_id=razorpay_order_id, user=request.user, status='Pending').first()
            if order:
                order.payment_status = 'FAILED'
                order.save()
            return JsonResponse({
                'success': False,
                'message': 'Missing payment details',
                'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id]) if order else reverse('cart_and_orders_app:user_order_list')
            }, status=400)
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }
        try:
            client.utility.verify_payment_signature(params_dict)
        except Exception as e:
            order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user, status='Pending')
            order.payment_status = 'FAILED'
            order.save()
            return JsonResponse({
                'success': False,
                'message': 'Payment verification failed',
                'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
            }, status=400)
        order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user, status='Pending')
        
        with transaction.atomic():
            order.status = 'Confirmed'
            order.payment_status = 'PAID'
            order.razorpay_payment_id = payment_id
            order.razorpay_signature = signature
            try:
                order.decrease_stock()
            except ValueError as e:
                order.payment_status = 'FAILED'
                order.save()
                return JsonResponse({
                    'success': False,
                    'message': f'Failed to update stock: {str(e)}',
                    'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                }, status=400)
            if order.coupon and order.coupon.is_valid():
                try:
                    user_coupon = UserCoupon.objects.get(user=request.user, coupon=order.coupon, is_used=False)
                    user_coupon.is_used = True
                    user_coupon.used_at = timezone.now()
                    user_coupon.order = order
                    user_coupon.save()
                except UserCoupon.DoesNotExist:
                    order.coupon = None
                    order.recalculate_totals()
                    order.save()
            order.save()
            request.session.pop('applied_coupon', None)
            request.session.pop('from_buy_now', None)
            request.session.modified = True
            return JsonResponse({
                'success': True,
                'message': 'Payment successful!',
                'redirect': reverse('cart_and_orders_app:user_order_success', args=[order.order_id])
            })
    except Order.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Order not found.',
            'redirect': reverse('cart_and_orders_app:user_order_list')
        }, status=400)
    except Exception as e:
        try:
            order = Order.objects.get(razorpay_order_id=razorpay_order_id, user=request.user)
            order.payment_status = 'FAILED'
            order.save()
            return JsonResponse({
                'success': False,
                'message': 'Failed to process payment.',
                'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
            }, status=500)
        except Order.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Order not found.',
                'redirect': reverse('cart_and_orders_app:user_order_list')
            }, status=400)
        
        
@login_required
@csrf_exempt
def initiate_payment(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.all()
    if not cart_items:
        return JsonResponse({'success': False, 'message': 'Cart is empty'}, status=400)
    applied_coupon = request.session.get('applied_coupon')
    coupon = None
    if applied_coupon:
        try:
            coupon = Coupon.objects.get(id=applied_coupon['coupon_id'], code=applied_coupon['code'])
            if not coupon.is_valid():
                coupon = None
                del request.session['applied_coupon']
                request.session.modified = True
        except Coupon.DoesNotExist:
            del request.session['applied_coupon']
            request.session.modified = True
    totals = cart.get_totals(coupon=coupon)
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    try:
        razorpay_order = client.order.create({
            'amount': int(totals['total'] * 100),
            'currency': 'INR',
            'payment_capture': 1
        })
        return JsonResponse({
            'success': True,
            'razorpay_key': settings.RAZORPAY_KEY_ID,
            'amount': int(totals['total'] * 100),
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
        return JsonResponse({'success': False, 'message': f'Failed to initiate payment: {str(e)}'}, status=500)

import logging
logger = logging.getLogger(__name__)
@login_required
@require_POST
def retry_payment(request, order_id):
    order = get_object_or_404(
        Order,
        order_id=order_id,
        user=request.user,
        payment_method='CARD',
        razorpay_payment_id__isnull=True,
        status='Pending',
        payment_status='FAILED'
    )
    try:
        # Log Razorpay keys for debugging
        logger.debug(f"RAZORPAY_KEY_ID: {settings.RAZORPAY_KEY_ID}")
        logger.debug(f"RAZORPAY_KEY_SECRET: {settings.RAZORPAY_KEY_SECRET}")

        # Check if a coupon was previously applied (even if order.coupon is None)
        user_coupon = UserCoupon.objects.filter(order=order, user=request.user).first()
        if user_coupon and user_coupon.coupon.is_valid():
            # Restore the coupon if it was previously applied and is still valid
            order.coupon = user_coupon.coupon
            # Recalculate coupon discount based on the current subtotal
            subtotal = sum(item.price * item.quantity for item in order.items.all())
            _, order.coupon_discount = user_coupon.coupon.apply_to_subtotal(subtotal)
            order.save()
        elif order.coupon:
            # If coupon exists but is invalid, clear it
            if not order.coupon.is_valid():
                UserCoupon.objects.filter(user=request.user, coupon=order.coupon, order=order).update(is_used=False, used_at=None, order=None)
                order.coupon = None
                order.coupon_discount = Decimal('0.00')
                order.save()

        # Initiate Razorpay payment
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        razorpay_order = client.order.create({
            'amount': int(order.total_amount * 100),
            'currency': 'INR',
            'payment_capture': 1
        })
        order.razorpay_order_id = razorpay_order['id']
        order.save()

        # Prepare prefill data
        prefill = {
            'name': request.user.get_full_name() or request.user.username,
            'email': request.user.email or '',
            'contact': order.shipping_address.phone if order.shipping_address and hasattr(order.shipping_address, 'phone') else ''
        }

        return JsonResponse({
            'success': True,
            'razorpay_order_id': razorpay_order['id'],
            'amount': int(order.total_amount * 100),
            'currency': 'INR',
            'key': settings.RAZORPAY_KEY_ID,
            'description': f'Payment for order {order.order_id}',
            'callback_url': reverse('cart_and_orders_app:razorpay_callback'),
            'order_id': order.order_id,
            'prefill': prefill
        })
    except Exception as e:
        logger.error(f"Error in retry_payment for order {order_id}: {str(e)}")
        return JsonResponse({'success': False, 'message': f'An error occurred while retrying payment: {str(e)}'}, status=500)


@login_required
@require_POST
def mark_payment_failed(request, order_id):
    try:
        order = get_object_or_404(
            Order,
            order_id=order_id,
            user=request.user,
            payment_method='CARD',
            razorpay_payment_id__isnull=True,
            status='Pending'
        )
        if order.payment_status == 'FAILED':
            return JsonResponse({'success': True, 'message': 'Payment status already marked as FAILED'})
        order.payment_status = 'FAILED'
        order.save()

        # Reset the coupon if applied
        if order.coupon:
            UserCoupon.objects.filter(user=request.user, coupon=order.coupon, order=order).update(is_used=False, used_at=None, order=None)

        return JsonResponse({'success': True, 'message': 'Payment status updated to FAILED'})
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'An error occurred while updating payment status'}, status=500)

########################################################################################################################
########################################################################################################################
########################################################################################################################
########################################################################################################################


@login_required
@user_passes_test(is_admin)
@never_cache
def admin_orders_list(request):
    search_query = request.GET.get('q', '')
    sort_by = request.GET.get('sort', '-order_date')
    status_filter = request.GET.get('status', '')

    orders = Order.objects.all().select_related('user', 'shipping_address', 'coupon').annotate(
        cancelled_items_count=Count('cancellations', filter=Q(cancellations__item__isnull=False))
    )
    
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

    for order in orders:
        cancellations = order.cancellations.all()
        order.has_cancellations = cancellations.exists()
        order.partial_cancellation = any(cancellation.item for cancellation in cancellations) if cancellations.exists() else False
        order.total_refunded = sum(cancellation.refunded_amount for cancellation in cancellations) if cancellations.exists() else Decimal('0.00')
        # Ensure original total is calculated correctly
        order.get_original_total_amount = order.get_original_total_amount()

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
            if order.coupon and order.coupon.is_valid():
                try:
                    user_coupon = UserCoupon.objects.get(user=order.user, coupon=order.coupon, is_used=False)
                    user_coupon.is_used = True
                    user_coupon.used_at = timezone.now()
                    user_coupon.order = order
                    user_coupon.save()
                except UserCoupon.DoesNotExist:
                    order.coupon = None
                    order.recalculate_totals()
                    order.save()
        return JsonResponse({'success': True, 'message': 'Order marked as delivered.'})
    return render(request, 'cart_and_orders_app/admin_order_detail.html', {'order': order})

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related('user', 'shipping_address', 'coupon')
                    .prefetch_related('items__variant__product', 'cancellations', 'return_requests__items__variant__product'),
        order_id=order_id
    )
    form = OrderStatusForm(instance=order)
    item_cancel_form = OrderItemCancellationForm()
    
    if request.method == 'POST':
        if order.status == 'Cancelled':
            messages.error(request, f"Order {order.order_id} is cancelled and its status cannot be updated.")
            return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)
        
        form = OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, f"Order {order.order_id} status updated to {order.status}.")
                return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)
            except Exception as e:
                messages.error(request, "An error occurred while updating the order status.")
        else:
            messages.error(request, "Invalid form submission. Please check the input.")

    context = {
        'order': order,
        'form': form,
        'item_cancel_form': item_cancel_form,
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
@never_cache
def admin_cancel_order(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related('user', 'coupon').prefetch_related('items__variant__product'),
        order_id=order_id
    )
    form = OrderCancellationForm()
    
    if order.status not in ['Pending', 'Processing']:
        messages.error(request, f"Order {order.order_id} cannot be cancelled in its current status ({order.status}).")
        return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)
    
    if request.method == 'POST':
        form = OrderCancellationForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['reason']
            try:
                order.cancel_order(reason=reason)
                messages.success(request, f"Order {order.order_id} has been cancelled successfully.")
                return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)
            except ValueError as e:
                messages.error(request, str(e))
                return render(request, 'cart_and_orders_app/admin_cancel_order.html', {'order': order, 'form': form})
            except Exception as e:
                messages.error(request, "An error occurred while cancelling the order.")
                return render(request, 'cart_and_orders_app/admin_cancel_order.html', {'order': order, 'form': form})
    
    return render(request, 'cart_and_orders_app/admin_cancel_order.html', {'order': order, 'form': form})

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_cancel_order_item(request, order_id):
    order = get_object_or_404(Order, order_id=order_id)
    if order.status not in ['Pending', 'Processing']:
        messages.error(request, "Order is not in a cancellable state.")
        return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)
    
    form = OrderItemCancellationForm(request.POST, order=order)
    if not form.is_valid():
        messages.error(request, "Invalid cancellation reason or item selection.")
        return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)
    
    try:
        with transaction.atomic():
            items = form.cleaned_data['items']
            reason = form.cleaned_data['combined_reason']
            cancelled_items = []
            
            for order_item in items:
                if order_item.order != order:
                    raise ValidationError(f"Item {order_item.id} does not belong to order {order.order_id}.")
                order.cancel_item(order_item, reason=reason)
                cancelled_items.append(order_item.variant.product.product_name)
            
            cancelled_items_str = ", ".join(cancelled_items)
            messages.success(request, f"Items cancelled successfully: {cancelled_items_str}.")
            return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)
    except Exception as e:
        messages.error(request, "An error occurred while cancelling the items.")
        return redirect('cart_and_orders_app:admin_order_detail', order_id=order.order_id)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_verify_return_request(request, return_request_id):
    return_request = get_object_or_404(ReturnRequest, id=return_request_id)
    if request.method == 'POST':
        try:
            if not return_request.is_verified:
                return_request.is_verified = True
                return_request.save()
                return_request.process_refund()
                messages.success(request, f"Return request for order {return_request.order.order_id} verified and refund processed.")
            else:
                messages.warning(request, "Return request is already verified.")
            return redirect('cart_and_orders_app:admin_order_detail', order_id=return_request.order.order_id)
        except Exception as e:
            messages.error(request, "An error occurred while verifying the return request.")
            return redirect('cart_and_orders_app:admin_order_detail', order_id=return_request.order.order_id)
    return redirect('cart_and_orders_app:admin_order_detail', order_id=return_request.order.order_id)

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
                return redirect('cart_and_orders_app:admin_inventory_list')
            else:
                messages.error(request, "Stock cannot be negative")
        except ValueError:
            messages.error(request, "Invalid stock value")
    context = {'variant': variant}
    return render(request, 'cart_and_orders_app/admin_update_stock.html', context)




@staff_member_required
def sales_dashboard(request):
    today = timezone.now().date()
    
    # Optimize query for today's orders
    today_orders = Order.objects.filter(order_date__date=today).select_related('user', 'coupon').prefetch_related('items__variant__product')
    
    # Total orders (all statuses)
    total_orders = Order.objects.count()
    
    # Subquery to calculate total_refunded per order
    total_refunded_subquery = Subquery(
        OrderCancellation.objects.filter(order=OuterRef('pk')).values('order').annotate(
            total_refunded=Sum('refunded_amount')
        ).values('total_refunded'),
        output_field=DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    )
    
    # Delivered orders for revenue and average order value
    delivered_orders = Order.objects.filter(status='Delivered').select_related('coupon').annotate(
        cancelled_items_count=Count('cancellations', filter=Q(cancellations__item__isnull=False)),
        total_refunded=total_refunded_subquery
    )
    
    # Total revenue: (total_amount - total_refunded) for Delivered orders
    revenue_data = delivered_orders.aggregate(
        total_amount_sum=Sum('total_amount'),
        total_refunded_sum=Sum('total_refunded')
    )
    total_revenue = (revenue_data['total_amount_sum'] or Decimal('0.00')) - (revenue_data['total_refunded_sum'] or Decimal('0.00'))
    
    # Total coupon discount for Delivered orders
    total_coupon_discount = delivered_orders.aggregate(Sum('coupon_discount'))['coupon_discount__sum'] or Decimal('0.00')
    
    # Total refunded amount (all orders)
    total_refunded = OrderCancellation.objects.aggregate(Sum('refunded_amount'))['refunded_amount__sum'] or Decimal('0.00')
    
    # Average order value: total_revenue / count of Delivered orders
    delivered_orders_count = delivered_orders.count()
    average_order_value = total_revenue / delivered_orders_count if delivered_orders_count > 0 else Decimal('0.00')
    
    # Annotate today_orders with cancelled items count and original total
    for order in today_orders:
        cancellations = order.cancellations.all()
        order.cancelled_items_count = cancellations.filter(item__isnull=False).count()
        order.original_total = order.get_original_total_amount()
    
    context = {
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'total_coupon_discount': total_coupon_discount,
        'total_refunded': total_refunded,
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
                group_by = 'day'
            elif report_type == 'WEEKLY':
                start_date = today - timedelta(days=today.weekday())
                end_date = start_date + timedelta(days=6)
                group_by = 'day'
            elif report_type == 'MONTHLY':
                start_date = today.replace(day=1)
                if today.month == 12:
                    end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
                group_by = 'day'
            elif report_type == 'YEARLY':
                start_date = today.replace(month=1, day=1)
                end_date = today.replace(month=12, day=31)
                group_by = 'month'
            else:
                start_date = form.cleaned_data['start_date']
                end_date = form.cleaned_data['end_date']
                date_range_days = (end_date - start_date).days + 1
                group_by = 'day' if date_range_days <= 30 else 'month'
            
            orders = Order.objects.filter(
                order_date__date__gte=start_date,
                order_date__date__lte=end_date
            ).select_related('user').order_by('-order_date')
            
            total_orders = orders.count()
            total_sales = orders.aggregate(total=Sum('total_amount'))['total'] or 0
            
            # Calculate period-based totals
            period_totals = []
            if group_by == 'day':
                daily_totals = orders.annotate(
                    day=TruncDay('order_date')
                ).values('day').annotate(
                    total=Sum('total_amount'),
                    count=Count('id')
                ).order_by('day')
                
                for entry in daily_totals:
                    period_totals.append({
                        'period': entry['day'].date(),
                        'total': entry['total'] or 0,
                        'orders': entry['count']
                    })
            else:
                monthly_totals = orders.annotate(
                    month=TruncMonth('order_date')
                ).values('month').annotate(
                    total=Sum('total_amount'),
                    count=Count('id')
                ).order_by('month')
                
                for entry in monthly_totals:
                    period_totals.append({
                        'period': entry['month'].date(),
                        'total': entry['total'] or 0,
                        'orders': entry['count']
                    })
            
            report = SalesReport.objects.create(
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
                total_orders=total_orders,
                total_sales=total_sales,
                total_discount=0  # Discounts not displayed
            )
            
            if 'export' in request.POST:
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = f'attachment; filename="sales_report_{start_date}_to_{end_date}.csv"'
                
                writer = csv.writer(response)
                writer.writerow(['Order ID', 'Date', 'Customer', 'Total Amount', 'Status'])
                
                for order in orders:
                    writer.writerow([
                        order.order_id,
                        order.order_date.strftime('%Y-%m-%d %H:%M'),
                        order.user.username,
                        order.total_amount,
                        order.status
                    ])
                return response
            
            # Redirect to sales_report_detail with report ID
            return redirect('cart_and_orders_app:sales_report_detail', report_id=report.id)
    else:
        form = SalesReportForm()
    
    return render(request, 'cart_and_orders_app/generate_sales_report.html', {'form': form})

@staff_member_required
def sales_report_detail(request, report_id):
    report = SalesReport.objects.get(id=report_id)
    orders = Order.objects.filter(
        order_date__date__gte=report.start_date,
        order_date__date__lte=report.end_date
    ).select_related('user').order_by('-order_date')
    
    # Determine grouping
    date_range_days = (report.end_date - report.start_date).days + 1
    if report.report_type in ['DAILY', 'WEEKLY', 'MONTHLY'] or (report.report_type == 'CUSTOM' and date_range_days <= 30):
        group_by = 'day'
    else:
        group_by = 'month'
    
    # Calculate period-based totals
    period_totals = []
    if group_by == 'day':
        daily_totals = orders.annotate(
            day=TruncDay('order_date')
        ).values('day').annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('day')
        
        for entry in daily_totals:
            period_totals.append({
                'period': entry['day'].date(),
                'total': entry['total'] or 0,
                'orders': entry['count']
            })
    else:
        monthly_totals = orders.annotate(
            month=TruncMonth('order_date')
        ).values('month').annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('month')
        
        for entry in monthly_totals:
            period_totals.append({
                'period': entry['month'].date(),
                'total': entry['total'] or 0,
                'orders': entry['count']
            })
    
    # Pagination
    paginator = Paginator(orders, 10)  # 10 orders per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'report': report,
        'page_obj': page_obj,
        'period_totals': period_totals,
        'group_by': group_by,
    }
    return render(request, 'cart_and_orders_app/sales_report.html', context)

def user_order_success(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    # Allow 'PENDING' payment_status for COD orders
    if order.payment_status not in ['PAID', 'PENDING'] or order.status not in ['Pending', 'Confirmed']:
        messages.error(request, "Invalid order status.")
        return redirect('cart_and_orders_app:user_order_list')
    subtotal = sum(item.price * item.quantity for item in order.items.all())
    total_offer_discount = sum(
        (item.variant.best_price['original_price'] - item.variant.best_price['price']) * item.quantity
        for item in order.items.all()
    )
    original_total = sum(item.variant.best_price['original_price'] * item.quantity for item in order.items.all())
    shipping_cost = Decimal('0.00')
    # Ensure coupon discount is correct
    coupon_discount = order.coupon_discount or Decimal('0.00')
    if coupon_discount == 0 and order.coupon and order.coupon.is_valid():
        # Recalculate coupon discount if it's 0 but a valid coupon exists
        _, coupon_discount = order.coupon.apply_to_subtotal(subtotal)
        order.coupon_discount = coupon_discount
        order.save()
    elif coupon_discount == 0:
        # Fallback to UserCoupon if order.coupon is not set
        user_coupon = UserCoupon.objects.filter(order=order, user=request.user, is_used=True).first()
        if user_coupon and user_coupon.coupon.is_valid():
            _, coupon_discount = user_coupon.coupon.apply_to_subtotal(subtotal)
            order.coupon = user_coupon.coupon
            order.coupon_discount = coupon_discount
            order.save()
    context = {
        'order': order,
        'title': 'Order Success',
        'subtotal': subtotal,
        'total_offer_discount': total_offer_discount,
        'shipping_cost': shipping_cost,
        'coupon_discount': coupon_discount,
        'is_free_delivery': order.total_amount > 0,
    }
    return render(request, 'cart_and_orders_app/user_order_success.html', context)

@login_required
def user_order_failure(request, order_id):
    try:
        order = Order.objects.get(order_id=order_id, user=request.user)
        # Calculate totals for display
        subtotal = order.total_amount + order.coupon_discount
        total_offer_discount = sum(
            (item.variant.best_price['original_price'] - item.price) * item.quantity
            for item in order.items.all()
        )
        coupon_discount = order.coupon_discount
        coupon_code = order.coupon.code if order.coupon else None

        context = {
            'order': order,
            'subtotal': subtotal,
            'total_offer_discount': total_offer_discount,
            'coupon_discount': coupon_discount,
            'coupon_code': coupon_code,  # Add coupon code to context
            'shipping_cost': Decimal('0.00'),
        }
        return render(request, 'cart_and_orders_app/user_order_failure.html', context)
    except Order.DoesNotExist:
        context = {
            'order': None,
            'subtotal': Decimal('0.00'),
            'total_offer_discount': Decimal('0.00'),
            'coupon_discount': Decimal('0.00'),
            'coupon_code': None,
            'shipping_cost': Decimal('0.00'),
        }
        return render(request, 'cart_and_orders_app/user_order_failure.html', context)

@login_required
@never_cache
def user_order_list(request):
    orders = Order.objects.filter(user=request.user).select_related('coupon', 'shipping_address').prefetch_related('items__variant__product').order_by('-created_at')
    incomplete_razorpay_orders = Order.objects.filter(
        user=request.user,
        payment_method='CARD',
        razorpay_payment_id__isnull=True,
        payment_status='FAILED',
        status='Pending'
    ).select_related('shipping_address')
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    if search_query:
        orders = orders.filter(Q(order_id__icontains=search_query))
    if status_filter:
        orders = orders.filter(status=status_filter)
    status_choices = Order.STATUS_CHOICES
    context = {
        'orders': orders,
        'incomplete_razorpay_orders': incomplete_razorpay_orders,
        'search_query': search_query,
        'status_filter': status_filter,
        'status_choices': status_choices,
    }
    return render(request, 'cart_and_orders_app/user_order_list.html', context)


@login_required
def user_order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related('user', 'coupon', 'shipping_address')
                    .prefetch_related('items__variant__product'),
        order_id=order_id,
        user=request.user
    )
    subtotal = sum(item.price * item.quantity for item in order.items.all())
    total_offer_discount = sum(
        (item.variant.best_price['original_price'] - item.price) * item.quantity
        for item in order.items.all()
    )
    shipping_cost = Decimal('0.00')
    
    # Get coupon details
    coupon_discount = order.coupon_discount or Decimal('0.00')
    coupon_code = None
    if order.coupon:
        coupon_code = order.coupon.code
        # Recalculate discount if coupon_discount is 0 but coupon exists
        if coupon_discount == 0 and order.coupon.is_valid():
            _, coupon_discount = order.coupon.apply_to_subtotal(subtotal)
    else:
        # Fallback to UserCoupon if order.coupon is not set
        user_coupon = UserCoupon.objects.filter(order=order, is_used=True).select_related('coupon').first()
        if user_coupon and user_coupon.coupon.is_valid():
            coupon_code = user_coupon.coupon.code
            _, coupon_discount = user_coupon.coupon.apply_to_subtotal(subtotal)

    cancel_item_form = OrderItemCancellationForm()
    return_form = ReturnRequestForm(order=order)
    
    # Compute cancelled items and their count
    cancelled_items = order.cancellations.filter(item__isnull=False)
    cancelled_items_count = cancelled_items.count()

    context = {
        'order': order,
        'subtotal': float(subtotal),
        'total_offer_discount': float(total_offer_discount),
        'shipping_cost': float(shipping_cost),
        'coupon_discount': float(coupon_discount),
        'coupon_code': coupon_code,  # New context variable for coupon code
        'return_form': return_form,
        'cancel_item_form': cancel_item_form,
        'is_free_delivery': order.total_amount > 0,
        'cancelled_items': cancelled_items,
        'cancelled_items_count': cancelled_items_count,
    }
    return render(request, 'cart_and_orders_app/user_order_detail.html', context)

@login_required
@require_POST
def user_cancel_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)

    # Check if the order is in a cancellable status
    if order.status not in ['Pending', 'Processing', 'Confirmed']:
        return JsonResponse({
            'success': False,
            'message': f"Order {order.order_id} cannot be cancelled in its current status ({order.status})."
        }, status=400)

    # Check if the payment status is valid for cancellation
    if order.payment_status not in ['PAID', 'PENDING']:
        return JsonResponse({
            'success': False,
            'message': f"Order {order.order_id} cannot be cancelled because the payment status is {order.payment_status}."
        }, status=400)

    # Process the cancellation
    form = OrderCancellationForm(request.POST)
    if form.is_valid():
        reason = form.cleaned_data.get('reason', '')
        try:
            order.cancel_order(reason=reason)
            return JsonResponse({
                'success': True,
                'message': f"Order {order.order_id} has been successfully cancelled."
            })
        except ValidationError as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=400)
    else:
        return JsonResponse({
            'success': False,
            'message': 'Invalid cancellation form data.'
        }, status=400)

@login_required
@require_POST
def user_cancel_order_item(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if order.status not in ['Pending', 'Processing', 'Confirmed']:
        return JsonResponse({
            'success': False,
            'message': 'Items cannot be cancelled at this stage (order must be in Pending, Processing, or Confirmed status).'
        }, status=400)
    
    form = OrderItemCancellationForm(request.POST, order=order)
    if not form.is_valid():
        return JsonResponse({
            'success': False,
            'message': 'Invalid cancellation data provided.',
            'errors': form.errors
        }, status=400)
    
    try:
        with transaction.atomic():
            items = form.cleaned_data['items']
            reason = form.cleaned_data['combined_reason']
            cancelled_items = []
            
            for order_item in items:
                if order_item.order != order:
                    raise ValidationError(f"Item {order_item.id} does not belong to order {order.order_id}.")
                order.cancel_item(order_item, reason=reason)
                cancelled_items.append(order_item.variant.product.product_name)
            
            cancelled_items_str = ", ".join(cancelled_items)
            
            response_data = {
                'success': True,
                'message': f"Items cancelled successfully: {cancelled_items_str}.",
            }
            if order.status == 'Cancelled':
                response_data['redirect'] = reverse('cart_and_orders_app:user_order_list')
            else:
                response_data['redirect'] = reverse('cart_and_orders_app:user_order_detail', args=[order.order_id])
            
            return JsonResponse(response_data)
    except ValidationError as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while cancelling the items.'
        }, status=500)

@login_required
@require_POST
def user_return_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if order.status != 'Delivered':
        messages.error(request, "This order cannot be returned.")
        return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    if order.return_requests.exists():
        messages.error(request, "A return request has already been submitted for this order.")
        return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    form = ReturnRequestForm(request.POST, order=order)
    if not form.is_valid():
        messages.error(request, "Invalid return request. Please provide a valid reason and select items if applicable.")
        return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    try:
        with transaction.atomic():
            return_request = ReturnRequest.objects.create(
                order=order,
                reason=form.cleaned_data['reason'],
                requested_at=timezone.now(),
                is_verified=False,
                refund_processed=False
            )
            if form.cleaned_data.get('items'):
                return_request.items.set(form.cleaned_data['items'])
            messages.success(request, "Return request submitted. We will process it shortly.")
            return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)


def generate_pdf(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    items = order.items.select_related('variant__product').all()
    subtotal = sum(item.price * item.quantity for item in items)
    total_offer_discount = sum(
        (item.variant.best_price['original_price'] - item.variant.best_price['price']) * item.quantity
        for item in items
    )
    context = {
        'order': order,
        'items': items,
        'user': request.user,
        'subtotal': subtotal,
        'total_offer_discount': total_offer_discount,
        'coupon_discount': order.coupon_discount,
        'is_free_delivery': order.total_amount > 0,
    }
    html_string = render_to_string('cart_and_orders_app/invoice.html', context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="order_{order.order_id}.pdf"'
    weasyprint.HTML(string=html_string).write_pdf(response)
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
            valid_orders = orders.filter(status__in=['Pending', 'Processing'])
            count = valid_orders.update(status='Shipped')
            if count > 0:
                messages.success(request, f"Marked {count} order(s) as Shipped.")
            else:
                messages.warning(request, "No eligible orders were marked as Shipped.")
        elif action == 'mark_delivered':
            valid_orders = orders.filter(status='Shipped')
            count = valid_orders.count()
            if count > 0:
                for order in valid_orders:
                    order.status = 'Delivered'
                    order.delivered_at = timezone.now()
                    order.save()
                    if order.coupon:
                        try:
                            user_coupon = UserCoupon.objects.get(user=order.user, coupon=order.coupon, is_used=False)
                            user_coupon.is_used = True
                            user_coupon.used_at = timezone.now()
                            user_coupon.order = order
                            user_coupon.save()
                        except UserCoupon.DoesNotExist:
                            order.coupon = None
                            order.recalculate_totals()
                            order.save()
                messages.success(request, f"Marked {count} order(s) as Delivered.")
            else:
                messages.warning(request, "No Shipped orders were marked as Delivered.")
        elif action == 'cancel':
            valid_orders = orders.filter(status__in=['Pending', 'Processing'])
            count = valid_orders.count()
            if count > 0:
                for order in valid_orders:
                    order.cancel_order(reason="Cancelled by admin")
                messages.success(request, f"Cancelled {count} order(s) and processed refunds.")
            else:
                messages.warning(request, "No eligible orders were cancelled.")
        else:
            messages.error(request, "Invalid action selected.")
        return redirect('cart_and_orders_app:admin_orders_list')
    return redirect('cart_and_orders_app:admin_orders_list')

