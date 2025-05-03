from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.template.loader import render_to_string
import weasyprint
from django.db.models import Sum, Avg
from product_app.models import Product, ProductVariant
from decimal import Decimal
import json
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
import json
import logging


logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_staff or user.is_superuser

def user_cart_list(request):
    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        cart = Cart.objects.create(user=request.user)
    cart_items = cart.items.select_related('variant__product').prefetch_related('variant__variant_images').all()
    issues = []
    for item in cart_items:
        if not item.variant.is_active or not item.variant.product.is_active:
            issues.append(f"{item.variant.product.product_name} ({item.variant_details}) is no longer available.")
            item.delete()
            continue
        if item.quantity > item.variant.stock:
            issues.append(f"{item.variant.product.product_name} ({item.variant_details}) has only {item.variant.stock} items in stock.")
    cart_items = cart.items.select_related('variant__product').prefetch_related('variant__variant_images').all()
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
        'is_free_delivery': cart_total > 0,  
    }
    return render(request, 'cart_and_orders_app/user_cart_list.html', context)


@require_POST
@login_required
def add_to_cart(request):
    try:
        data = json.loads(request.body)
        variant_id = data.get('variant_id')
        quantity = int(data.get('quantity', 1))
        
        if quantity < 1:
            return JsonResponse({'success': False, 'error': 'Invalid quantity'}, status=400)
        
        variant = get_object_or_404(ProductVariant, id=variant_id, is_active=True)
        if not variant.product.is_active or not variant.product.category.is_active:
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
    except (ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'error': 'Invalid data'}, status=400)
    except Exception as e:
        logger.error(f"Error adding to cart: {str(e)}")
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
        
        if not cart_item.variant.is_active or not cart_item.variant.product.is_active:
            cart_item.delete()
            return JsonResponse({
                'success': False,
                'message': f'{cart_item.variant.product.product_name} is no longer available.'
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
                    'message': 'Maximum quantity limit of 10 reached'
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
        logger.error(f"Error updating cart quantity: {str(e)}")
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


@login_required
@never_cache
def user_checkout(request):
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.select_related('variant__product').all()
    if not cart_items:
        messages.error(request, "Your cart is empty.")
        return redirect('cart_and_orders_app:user_cart_list')
    issues = []
    for item in cart_items:
        if not item.variant.is_active or not item.variant.product.is_active:
            issues.append(f"{item.variant.product.product_name} ({item.variant_details}) is no longer available.")
            item.delete()
            continue
        if item.quantity > item.variant.stock:
            issues.append(f"{item.variant.product.product_name} ({item.variant_details}) has only {item.variant.stock} items in stock.")
    cart_items = cart.items.select_related('variant__product').all()
    if not cart_items:
        for issue in issues:
            messages.warning(request, issue)
        messages.error(request, "Your cart is empty after removing unavailable items.")
        return redirect('cart_and_orders_app:user_cart_list')
    for issue in issues:
        messages.warning(request, issue)
    if any(item.quantity > item.variant.stock for item in cart_items):
        messages.error(request, "Some items are out of stock. Please update your cart.")
        return redirect('cart_and_orders_app:user_cart_list')
    addresses = Address.objects.filter(user=request.user)
    default_address = addresses.filter(is_default=True).first()
    if not addresses:
        messages.warning(request, "Please add a shipping address.")
        return redirect('user_app:user_address_list')
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
    }
    if 'from_buy_now' in request.session:
        del request.session['from_buy_now']
        request.session.modified = True
    logger.info(f"User {request.user.username} accessed checkout with subtotal INR {totals['subtotal']:.2f}, offer_discount: {totals['offer_discount']:.2f}, coupon: {totals['coupon_code'] or 'None'}, total: {totals['total']:.2f}")
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
            logger.warning(f"User {user.username} attempted to place order with empty cart")
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=400)
        out_of_stock_items = []
        for item in cart_items:
            if item.quantity > item.variant.stock:
                out_of_stock_items.append(f"{item.variant.product.product_name} (Available: {item.variant.stock}, Requested: {item.quantity})")
        if out_of_stock_items:
            error_message = f"Insufficient stock for: {', '.join(out_of_stock_items)}"
            logger.warning(f"User {user.username} attempted to place order with out-of-stock items: {error_message}")
            return JsonResponse({'success': False, 'message': error_message}, status=400)
        form = OrderCreateForm(request.POST, user=user)
        if not form.is_valid():
            logger.warning(f"User {user.username} submitted invalid order form: {form.errors}")
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
            logger.warning(f"User {user.username} selected invalid payment method: {payment_method}")
            return JsonResponse({'success': False, 'message': 'Invalid payment method.'}, status=400)
        applied_coupon = request.session.get('applied_coupon')
        coupon = None
        if applied_coupon:
            try:
                coupon = Coupon.objects.get(id=applied_coupon['coupon_id'], code=applied_coupon['code'])
                if not coupon.is_valid():
                    logger.warning(f"Coupon {applied_coupon['code']} is invalid for user {user.username}")
                    del request.session['applied_coupon']
                    request.session.modified = True
                    coupon = None
            except Coupon.DoesNotExist:
                logger.warning(f"Coupon {applied_coupon['code']} does not exist for user {user.username}")
                del request.session['applied_coupon']
                request.session.modified = True
        totals = cart.get_totals(coupon=coupon)
        if totals['subtotal'] <= 0:
            logger.error(f"Invalid subtotal {totals['subtotal']} for user {user.username}")
            return JsonResponse({'success': False, 'message': 'Invalid cart total.'}, status=400)
        logger.info(f"User {user.username} placing order: subtotal={totals['subtotal']}, offer_discount={totals['offer_discount']}, coupon_discount={totals['coupon_discount']}, total={totals['total']}, payment_method={payment_method}")
        with transaction.atomic():
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
                order_id=f"ORD-{timezone.now().strftime('%Y%m%d%H%M%S')}-{user.id}"
            )
            order.save()
            order_items = []
            for item in cart_items:
                cart_price = item.variant.best_price['price']
                current_price = item.variant.best_price['price']  # Fetch current price
                if cart_price != current_price:
                    logger.warning(f"Price mismatch for variant {item.variant.id}: cart={cart_price}, current={current_price}")
                    return JsonResponse({
                        'success': False,
                        'message': f"Price for {item.variant.product.product_name} has changed. Please review your cart."
                    }, status=400)
                order_items.append(
                    OrderItem(
                        order=order,
                        variant=item.variant,
                        quantity=item.quantity,
                        price=current_price,
                        applied_offer=item.variant.best_price.get('applied_offer_type', '')
                    )
                )
            OrderItem.objects.bulk_create(order_items)
            cart.items.all().delete()
            request.session.pop('applied_coupon', None)
            request.session.pop('from_buy_now', None)
            request.session.modified = True
            if payment_method == 'COD':
                if totals['total'] > Decimal('1000.00'):
                    logger.warning(f"User {user.username} attempted COD for order above 1000: {totals['total']}")
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
                        logger.info(f"UserCoupon updated for order {order.order_id}, coupon {coupon.code}")
                    except UserCoupon.DoesNotExist:
                        logger.warning(f"No valid UserCoupon for user {user.id}, coupon {coupon.code}")
                        order.coupon = None
                        order.recalculate_totals()
                        order.save()
                order.save()
                logger.info(f"COD order {order.order_id} placed successfully by user {user.username}")
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
                        logger.warning(f"User {user.username} has insufficient wallet balance: {wallet.balance} < {totals['total']}")
                        order.payment_status = 'FAILED'
                        order.save()
                        return JsonResponse({
                            'success': False,
                            'message': f'Insufficient wallet balance. Available: ₹{wallet.balance}, Required: ₹{totals['total']}',
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
                                logger.info(f"UserCoupon updated for order {order.order_id}, coupon {coupon.code}")
                            except UserCoupon.DoesNotExist:
                                logger.warning(f"No valid UserCoupon for user {user.id}, coupon {coupon.code}")
                                order.coupon = None
                                order.recalculate_totals()
                                order.save()
                        order.save()
                    logger.info(f"Wallet payment processed for user {user.username}, order {order.order_id}")
                    return JsonResponse({
                        'success': True,
                        'message': 'Order placed successfully!',
                        'order_id': order.order_id,
                        'redirect': reverse('cart_and_orders_app:user_order_success', args=[order.order_id])
                    })
                except Exception as e:
                    logger.error(f"Wallet payment failed for user {user.username}, order {order.order_id}: {str(e)}")
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
                    logger.info(f"Razorpay order initiated for user {user.username}, order {order.order_id}, razorpay_order_id={razorpay_order['id']}")
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
                    logger.error(f"Razorpay BadRequestError for user {user.username}, order {order.order_id}: {str(e)}")
                    order.payment_status = 'FAILED'
                    order.save()
                    return JsonResponse({
                        'success': False,
                        'message': f'Payment processing failed: {str(e)}. Please try again.',
                        'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                    }, status=400)
                except razorpay.errors.ServerError as e:
                    logger.error(f"Razorpay ServerError for user {user.username}, order {order.order_id}: {str(e)}")
                    order.payment_status = 'FAILED'
                    order.save()
                    return JsonResponse({
                        'success': False,
                        'message': 'Payment processing failed due to a server error. Please try again later.',
                        'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                    }, status=500)
                except Exception as e:
                    logger.error(f"Unexpected error in Razorpay for user {user.username}, order {order.order_id}: {str(e)}")
                    order.payment_status = 'FAILED'
                    order.save()
                    return JsonResponse({
                        'success': False,
                        'message': 'An unexpected error occurred during payment processing. Please try again.',
                        'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
                    }, status=500)
    except Exception as e:
        logger.error(f"Error placing order for user {user.username}: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'An error occurred while placing the order: {str(e)}',
            'redirect': reverse('cart_and_orders_app:user_checkout')
        }, status=500)

@login_required
@csrf_exempt
def razorpay_callback(request):
    if request.method != 'POST':
        logger.warning(f"Invalid request method for Razorpay callback by user {request.user.username}")
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    try:
        payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        signature = request.POST.get('razorpay_signature')
        logger.debug(f"Razorpay callback received: payment_id={payment_id}, order_id={razorpay_order_id}")
        if not all([payment_id, razorpay_order_id, signature]):
            logger.warning(f"Missing payment details for user {request.user.username}: payment_id={payment_id}, order_id={razorpay_order_id}")
            order = Order.objects.filter(razorpay_order_id=razorpay_order_id, user=request.user, status='Pending').first()
            if order:
                order.payment_status = 'FAILED'
                order.save()
                logger.info(f"Order {order.order_id} marked as FAILED due to missing payment details")
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
            logger.info(f"Payment signature verified for user {request.user.username}, order_id={razorpay_order_id}")
        except Exception as e:
            logger.error(f"Payment verification failed for user {request.user.username}, order_id={razorpay_order_id}: {str(e)}")
            order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user, status='Pending')
            order.payment_status = 'FAILED'
            order.save()
            logger.info(f"Order {order.order_id} marked as FAILED due to signature verification failure")
            return JsonResponse({
                'success': False,
                'message': 'Payment verification failed',
                'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
            }, status=400)
        order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user, status='Pending')
        logger.debug(f"Processing order {order.order_id} for user {request.user.username}")
        with transaction.atomic():
            order.status = 'Confirmed'
            order.payment_status = 'PAID'
            order.razorpay_payment_id = payment_id
            order.razorpay_signature = signature
            try:
                order.decrease_stock()
                logger.info(f"Stock decreased for order {order.order_id}")
            except ValueError as e:
                logger.error(f"Stock decrease failed for order {order.order_id}: {str(e)}")
                order.payment_status = 'FAILED'
                order.save()
                logger.info(f"Order {order.order_id} marked as FAILED due to stock decrease failure")
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
                    logger.info(f"UserCoupon updated for order {order.order_id}, coupon {order.coupon.code}")
                except UserCoupon.DoesNotExist:
                    logger.warning(f"No valid UserCoupon for user {request.user.id}, coupon {order.coupon.code}")
                    order.coupon = None
                    order.recalculate_totals()
                    order.save()
            order.save()
            request.session.pop('applied_coupon', None)
            request.session.pop('from_buy_now', None)
            request.session.modified = True
            logger.info(f"Razorpay payment successful for user {request.user.username}, order {order.order_id}")
            return JsonResponse({
                'success': True,
                'message': 'Payment successful!',
                'redirect': reverse('cart_and_orders_app:user_order_success', args=[order.order_id])
            })
    except Order.DoesNotExist:
        logger.error(f"Order not found for razorpay_order_id {razorpay_order_id}")
        return JsonResponse({
            'success': False,
            'message': 'Order not found.',
            'redirect': reverse('cart_and_orders_app:user_order_list')
        }, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in Razorpay callback for user {request.user.username}, order_id={razorpay_order_id}: {str(e)}")
        try:
            order = Order.objects.get(razorpay_order_id=razorpay_order_id, user=request.user)
            order.payment_status = 'FAILED'
            order.save()
            logger.info(f"Order {order.order_id} marked as FAILED due to callback error")
            return JsonResponse({
                'success': False,
                'message': 'Failed to process payment.',
                'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
            }, status=500)
        except Order.DoesNotExist:
            logger.error(f"Order not found for razorpay_order_id {razorpay_order_id} in fallback")
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
        logger.warning(f"User {request.user.username} attempted to initiate payment with empty cart")
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
        logger.info(f"Initiated Razorpay payment for user {request.user.username}, amount {totals['total']}")
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
        logger.error(f"Failed to initiate payment for user {request.user.username}: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Failed to initiate payment: {str(e)}'}, status=500)

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
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    try:
        razorpay_order = client.order.create({
            'amount': int(order.total_amount * 100),
            'currency': 'INR',
            'receipt': f'order_{order.order_id}_retry',
            'payment_capture': 1
        })
        order.razorpay_order_id = razorpay_order['id']
        order.payment_status = 'PENDING'
        order.save()
        logger.info(f"Retry payment initiated for user {request.user.username}, order {order.order_id}, razorpay_order_id={razorpay_order['id']}")
        return JsonResponse({
            'success': True,
            'razorpay_order_id': razorpay_order['id'],
            'razorpay_key': settings.RAZORPAY_KEY_ID,
            'amount': int(order.total_amount * 100),
            'currency': 'INR',
            'description': f'Retry Payment for Order {order.order_id}',
            'callback_url': request.build_absolute_uri(reverse('cart_and_orders_app:razorpay_callback')),
            'order_id': order.order_id,
            'prefill': {
                'name': request.user.get_full_name() or request.user.username,
                'email': request.user.email,
                'contact': order.shipping_address.phone if hasattr(order.shipping_address, 'phone') else ''
            }
        })
    except Exception as e:
        logger.error(f"Failed to initiate retry payment for user {request.user.username}, order {order.order_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Failed to initiate retry payment: {str(e)}',
            'redirect': reverse('cart_and_orders_app:user_order_failure', args=[order.order_id])
        }, status=500)



########################################################################################################################
########################################################################################################################
########################################################################################################################
########################################################################################################################




@staff_member_required
def sales_dashboard(request):
    today = timezone.now().date()
    today_orders = Order.objects.filter(order_date__date=today)
    
    total_orders = Order.objects.count()
    total_revenue = Order.objects.filter(status='Delivered').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_coupon_discount = Order.objects.filter(status='Delivered').aggregate(Sum('coupon_discount'))['coupon_discount__sum'] or 0
    average_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    context = {
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'total_coupon_discount': total_coupon_discount,
        'average_order_value': average_order_value,
        'today_orders': today_orders,
    }
    
    return render(request, 'cart_and_orders_app/sales_dashboard.html', context)


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
                    logger.info(f"UserCoupon updated for order {order.order_id}, coupon {order.coupon.code}")
                except UserCoupon.DoesNotExist:
                    logger.warning(f"No valid UserCoupon for user {order.user.id}, coupon {order.coupon.code}")
                    order.coupon = None
                    order.recalculate_totals()
                    order.save()
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
                order.cancel_order(reason="Admin cancelled order")
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
        order.cancel_order(reason="Cancelled by admin")
        messages.success(request, f"Order {order.order_id} has been cancelled.")
        return redirect('cart_and_orders_app:admin_orders_list')
    context = {'order': order}
    return render(request, 'cart_and_orders_app/admin_cancel_order.html', context)

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
            if not return_request.items.exists():
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
    context = {
        'return_request': return_request,
        'order': order,
        'return_items': return_request.items.all(),
    }
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
            total_coupon_discount = orders.aggregate(Sum('coupon_discount'))['coupon_discount__sum'] or 0
            total_offer_discount = sum(
                sum((item.variant.best_price['original_price'] - item.price) * item.quantity for item in order.items.all())
                for order in orders
            )
            
            report = SalesReport.objects.create(
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
                total_orders=total_orders,
                total_sales=total_sales,
                total_discount=total_coupon_discount + total_offer_discount
            )
            
            context = {
                'form': form,
                'report': report,
                'orders': orders,
                'start_date': start_date,
                'end_date': end_date,
                'total_coupon_discount': total_coupon_discount,
                'total_offer_discount': total_offer_discount,
            }
            
            if 'export' in request.POST:
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = f'attachment; filename="sales_report_{start_date}_to_{end_date}.csv"'
                
                writer = csv.writer(response)
                writer.writerow(['Order ID', 'Date', 'Customer', 'Total Amount', 'Coupon Discount', 'Offer Discount', 'Status'])
                
                for order in orders:
                    offer_discount = sum(
                        (item.variant.best_price['original_price'] - item.price) * item.quantity
                        for item in order.items.all()
                    )
                    writer.writerow([
                        order.order_id,
                        order.order_date.strftime('%Y-%m-%d %H:%M'),
                        order.user.username,
                        order.total_amount,
                        order.coupon_discount,
                        offer_discount,
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
    total_coupon_discount = orders.aggregate(Sum('coupon_discount'))['coupon_discount__sum'] or 0
    total_offer_discount = sum(
        (item.variant.best_price['original_price'] - item.variant.best_price['price']) * item.quantity
        for order in orders
        for item in order.items.all()
    )
    context = {
        'report': report,
        'orders': orders,
        'total_coupon_discount': total_coupon_discount,
        'total_offer_discount': total_offer_discount,
    }
    return render(request, 'cart_and_orders_app/sales_report.html', context)

def user_order_success(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if order.payment_status != 'PAID' or order.status not in ['Pending', 'Confirmed']:
        logger.warning(f"User {request.user.username} attempted to access success page for invalid order {order.order_id}: payment_status={order.payment_status}, status={order.status}")
        messages.error(request, "Invalid order status.")
        return redirect('cart_and_orders_app:user_order_list')
    subtotal = sum(item.price * item.quantity for item in order.items.all())
    total_offer_discount = sum(
        (item.variant.best_price['original_price'] - item.variant.best_price['price']) * item.quantity
        for item in order.items.all()
    )
    original_total = sum(item.variant.best_price['original_price'] * item.quantity for item in order.items.all())
    shipping_cost = Decimal('0.00')
    coupon_discount = order.coupon_discount
    context = {
        'order': order,
        'title': 'Order Success',
        'subtotal': subtotal,
        'total_offer_discount': total_offer_discount,
        'shipping_cost': shipping_cost,
        'coupon_discount': coupon_discount,
        'is_free_delivery': order.total_amount > 0,
    }
    logger.info(f"User {request.user.username} accessed success page for order {order.order_id}")
    return render(request, 'cart_and_orders_app/user_order_success.html', context)

@login_required
def user_order_failure(request, order_id):
    try:
        order = Order.objects.get(order_id=order_id, user=request.user)
        # Calculate totals for display (mimicking user_checkout logic)
        totals = {
            'subtotal': order.total_amount + order.coupon_discount,
            'offer_discount': sum(item.price * item.quantity for item in order.items.all()) - order.total_amount,
            'coupon_discount': order.coupon_discount,
        }
        context = {
            'order': order,
            'subtotal': totals['subtotal'],
            'total_offer_discount': totals['offer_discount'],
            'coupon_discount': totals['coupon_discount'],
            'shipping_cost': Decimal('0.00'),
        }
        logger.info(f"User {request.user.username} accessed failure page for order {order_id}")
        return render(request, 'cart_and_orders_app/user_order_failure.html', context)
    except Order.DoesNotExist:
        logger.error(f"Order {order_id} not found for user {request.user.username}")
        context = {
            'order': None,
            'subtotal': Decimal('0.00'),
            'total_offer_discount': Decimal('0.00'),
            'coupon_discount': Decimal('0.00'),
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
    logger.info(f"User {request.user.username} accessed order list with {orders.count()} orders")
    return render(request, 'cart_and_orders_app/user_order_list.html', context)


def user_order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related('user', 'coupon', 'shipping_address')
                    .prefetch_related('items__variant__product'),
        order_id=order_id,
        user=request.user
    )
    subtotal = sum(item.price * item.quantity for item in order.items.all())
    total_offer_discount = sum(
        (item.variant.best_price['original_price'] - item.variant.best_price['price']) * item.quantity
        for item in order.items.all()
    )
    original_total = sum(item.variant.best_price['original_price'] * item.quantity for item in order.items.all())
    shipping_cost = Decimal('0.00')
    coupon_discount = order.coupon_discount
    context = {
        'order': order,
        'subtotal': subtotal,
        'total_offer_discount': total_offer_discount,
        'shipping_cost': shipping_cost,
        'coupon_discount': coupon_discount,
        'return_form': ReturnRequestForm(order=order),
        'cancel_item_form': OrderItemCancellationForm(),
        'is_free_delivery': order.total_amount > 0,
    }
    logger.info(f"User {request.user.username} viewed order detail for {order.order_id}")
    return render(request, 'cart_and_orders_app/user_order_detail.html', context)

@login_required
@require_POST
def user_cancel_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if order.status not in ['Pending', 'Processing', 'Confirmed']:
        logger.warning(f"User {request.user.username} attempted to cancel order {order_id} in invalid status {order.status}")
        return JsonResponse({'success': False, 'message': 'Order cannot be cancelled in its current status.'}, status=400)

    form = OrderCancellationForm(request.POST)
    if form.is_valid():
        reason = form.cleaned_data['reason']
        other_reason = request.POST.get('other_reason', '')
        # Combine reason and other_reason if provided
        combined_reason = reason
        if other_reason and reason == 'Other':
            combined_reason = f"Other: {other_reason}"

        try:
            order.cancel_order(reason=combined_reason)
            logger.info(f"User {request.user.username} cancelled order {order_id}")
            return JsonResponse({'success': True, 'message': 'Order has been cancelled successfully.'})
        except ValueError as e:
            logger.error(f"Error cancelling order {order_id} for user {request.user.username}: {str(e)}")
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    else:
        logger.error(f"Invalid form data for order cancellation {order_id}: {form.errors}")
        return JsonResponse({'success': False, 'message': 'Invalid cancellation data provided.'}, status=400)

@login_required
@require_POST
def user_cancel_order_item(request, order_id, item_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if order.status not in ['Pending', 'Processing', 'Confirmed']:
        logger.warning(f"User {request.user.username} attempted to cancel item {item_id} in order {order_id} with status {order.status}")
        return JsonResponse({
            'success': False,
            'message': 'Items cannot be cancelled at this stage.'
        }, status=400)
    order_item = get_object_or_404(OrderItem, id=item_id, order=order)
    form = OrderItemCancellationForm(request.POST)
    if not form.is_valid():
        logger.warning(f"Invalid item cancellation form for user {request.user.username}, order {order_id}, item {item_id}")
        return JsonResponse({
            'success': False,
            'message': 'Invalid cancellation reason.',
            'errors': form.errors
        }, status=400)
    try:
        with transaction.atomic():
            reason = form.cleaned_data['combined_reason']
            order.cancel_item(order_item, reason=reason)
            logger.info(f"Item {item_id} cancelled for order {order_id} by user {request.user.username} with reason: {reason}")
            return JsonResponse({
                'success': True,
                'message': f'Item {order_item.variant.product.product_name} cancelled successfully.',
                'redirect': reverse('cart_and_orders_app:user_order_list') if order.status == 'Cancelled' else None
            })
    except ValueError as e:
        logger.warning(f"Failed to cancel item {item_id} for order {order_id} by user {request.user.username}: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
    except Exception as e:
        logger.error(f"Error cancelling item {item_id} for order {order_id} by user {request.user.username}: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while cancelling the item.'
        }, status=500)

@login_required
@require_POST
def user_return_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if order.status != 'Delivered':
        logger.warning(f"User {request.user.username} attempted to return non-delivered order {order.order_id}")
        messages.error(request, "This order cannot be returned.")
        return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    if order.return_requests.exists():
        logger.warning(f"User {request.user.username} attempted to submit duplicate return for order {order.order_id}")
        messages.error(request, "A return request has already been submitted for this order.")
        return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    form = ReturnRequestForm(request.POST, order=order)
    if not form.is_valid():
        logger.warning(f"Invalid return request by user {request.user.username} for order {order.order_id}: {form.errors}")
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
            logger.info(f"User {request.user.username} submitted return request for order {order.order_id}")
            return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    except Exception as e:
        logger.error(f"Error submitting return request for order {order_id} by user {request.user.username}: {str(e)}")
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
                logger.info(f"Admin marked {count} orders as shipped")
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
                            logger.info(f"UserCoupon updated for order {order.order_id}, coupon {order.coupon.code}")
                        except UserCoupon.DoesNotExist:
                            logger.warning(f"No valid UserCoupon for user {order.user.id}, coupon {order.coupon.code}")
                            order.coupon = None
                            order.recalculate_totals()
                            order.save()
                messages.success(request, f"Marked {count} order(s) as Delivered.")
                logger.info(f"Admin marked {count} orders as delivered")
            else:
                messages.warning(request, "No Shipped orders were marked as Delivered.")
        elif action == 'cancel':
            valid_orders = orders.exclude(status__in=['Cancelled', 'Delivered'])
            count = valid_orders.count()
            if count > 0:
                for order in valid_orders:
                    order.cancel_order(reason="Cancelled by admin")
                messages.success(request, f"Cancelled {count} order(s) and processed refunds.")
                logger.info(f"Admin cancelled {count} orders")
            else:
                messages.warning(request, "No eligible orders were cancelled.")
        else:
            messages.error(request, "Invalid action selected.")
        return redirect('cart_and_orders_app:admin_orders_list')
    return redirect('cart_and_orders_app:admin_orders_list')
