from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST,require_GET
from django.utils import timezone
from .forms import CouponForm, CouponApplyForm
from django.core.paginator import Paginator
from cart_and_orders_app.models import Cart, CartItem
from cart_and_orders_app.forms import CouponApplyForm
from decimal import Decimal
from django.db import models, transaction
from .models import Coupon, UserCoupon, Wallet, WalletTransaction, ProductOffer, CategoryOffer
from django.contrib import messages
from django.shortcuts import redirect, render
from decimal import InvalidOperation
from django.urls import reverse
import json
from .utils import apply_offers_to_cart
from django.contrib import messages
from django.conf import settings
from .models import ReferralCode, Referral
from django.db.models import Q, F
from django.views.decorators.csrf import csrf_exempt
import razorpay
from django.conf import settings
import logging
logger = logging.getLogger(__name__)


@login_required
@require_POST
def apply_coupon(request):
    coupon_code = request.POST.get('coupon_code', '').strip().upper()
    if not coupon_code:
        logger.warning(f"User {request.user.username} submitted empty coupon code")
        return JsonResponse({'success': False, 'message': 'Please enter a valid coupon code.'}, status=400)

    try:
        cart = Cart.objects.filter(user=request.user).first()
        if not cart or not cart.items.exists():
            logger.warning(f"User {request.user.username} has no cart or empty cart")
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=400)

        coupon = Coupon.objects.get(code=coupon_code)
        if not coupon.is_valid():
            logger.info(f"User {request.user.username} attempted to apply invalid coupon {coupon_code}")
            return JsonResponse({'success': False, 'message': f"Coupon '{coupon_code}' is expired or invalid."}, status=400)

        cart_items = cart.items.select_related('variant__product').all()
        subtotal = Decimal('0.00')
        offer_details = []
        
        for item in cart_items:
            best_price_info = item.variant.best_price
            unit_price = best_price_info['price']
            quantity = Decimal(str(item.quantity))
            subtotal += unit_price * quantity
            if best_price_info['applied_offer_type'] in ['product', 'category']:
                offer_details.append({
                    'product': item.variant.product.product_name,
                    'offer_type': best_price_info['applied_offer_type'],
                    'discount': float((best_price_info['original_price'] - unit_price) * quantity)
                })

        if coupon.minimum_order_amount > subtotal:
            logger.info(f"User {request.user.username} attempted to apply coupon {coupon_code} below minimum order amount {coupon.minimum_order_amount}")
            return JsonResponse({
                'success': False,
                'message': f"This coupon requires a minimum order of ₹{coupon.minimum_order_amount:.2f}. Your cart total is ₹{subtotal:.2f}."
            }, status=400)

        # Apply coupon
        total, discount_info = apply_offers_to_cart(cart_items, coupon, request.user)
        request.session['applied_coupon'] = {
            'code': coupon.code,
            'discount': float(discount_info['coupon_discount']),
            'coupon_id': coupon.id
        }
        request.session['applied_offers'] = offer_details
        request.session.modified = True
        logger.info(f"User {request.user.username} applied coupon {coupon_code} successfully. Subtotal: {subtotal}, Coupon Discount: {discount_info['coupon_discount']}, Offers: {offer_details}")
        return JsonResponse({
            'success': True,
            'message': f"Coupon '{coupon_code}' applied successfully! You saved ₹{discount_info['coupon_discount']:.2f}.",
            'subtotal': float(subtotal),
            'total': float(total),
            'discount_info': {
                'coupon_discount': float(discount_info['coupon_discount']),
                'offer_discount': float(discount_info.get('offer_discount', 0)),
                'shipping_cost': float(discount_info['shipping_cost'])
            },
            'offer_details': offer_details
        })

    except Coupon.DoesNotExist:
        logger.warning(f"User {request.user.username} attempted to apply non-existent coupon {coupon_code}")
        return JsonResponse({'success': False, 'message': f"Coupon '{coupon_code}' does not exist."}, status=400)
    except Exception as e:
        logger.error(f"Error applying coupon {coupon_code} for user {request.user.username}: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': 'An unexpected error occurred. Please try again.'}, status=500)

@login_required
@require_POST
def remove_coupon(request):
    try:
        if 'applied_coupon' not in request.session:
            logger.info(f"User {request.user.username} attempted to remove non-existent coupon")
            return JsonResponse({'success': False, 'message': 'No coupon is applied.'}, status=400)

        cart = Cart.objects.filter(user=request.user).first()
        if not cart or not cart.items.exists():
            logger.warning(f"User {request.user.username} has no cart or empty cart")
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=400)

        coupon_code = request.session['applied_coupon']['code']
        del request.session['applied_coupon']
        request.session.modified = True

        # Recalculate cart totals without coupon
        cart_items = cart.items.select_related('variant__product').all()
        subtotal = Decimal('0.00')
        offer_details = []
        for item in cart_items:
            best_price_info = item.variant.best_price
            unit_price = best_price_info['price']
            quantity = Decimal(str(item.quantity))
            subtotal += unit_price * quantity
            if best_price_info['applied_offer_type'] in ['product', 'category']:
                offer_details.append({
                    'product': item.variant.product.product_name,
                    'offer_type': best_price_info['applied_offer_type'],
                    'discount': float((best_price_info['original_price'] - unit_price) * quantity)
                })

        total, discount_info = apply_offers_to_cart(cart_items, None, request.user)
        request.session['applied_offers'] = offer_details
        request.session.modified = True

        logger.info(f"User {request.user.username} removed coupon {coupon_code} successfully.")
        return JsonResponse({
            'success': True,
            'message': f"Coupon '{coupon_code}' removed successfully.",
            'subtotal': float(subtotal),
            'total': float(total),
            'discount_info': {
                'coupon_discount': 0.0,
                'offer_discount': float(discount_info.get('offer_discount', 0)),
                'shipping_cost': float(discount_info['shipping_cost'])
            },
            'offer_details': offer_details
        })

    except Exception as e:
        logger.error(f"Error removing coupon for user {request.user.username}: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': 'An unexpected error occurred. Please try again.'}, status=500)

def apply_offers_to_product(product, price):
    best_price = price
    now = timezone.now()
    product_offers = ProductOffer.objects.filter(
        products=product,
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    )
    category_offers = CategoryOffer.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    )
    
    applicable_category_offers = []
    if hasattr(product, 'category'): 
        for offer in category_offers:
            applicable_categories = offer.get_all_categories()
            if product.category in applicable_categories:
                applicable_category_offers.append(offer)
    
    for offer in product_offers:
        discount = offer.calculate_discount(price)
        if discount > (price - best_price):
            best_price = price - discount
    
    for offer in applicable_category_offers:
        discount = offer.calculate_discount(price)
        if discount > (price - best_price):
            best_price = price - discount
    
    return max(Decimal('0.00'), best_price)

@login_required
@require_GET
def available_coupons(request):
    try:
        cart = Cart.objects.filter(user=request.user).first()
        if not cart:
            logger.warning(f"No cart found for user {request.user.username}")
            return JsonResponse({'success': False, 'message': 'No cart available.'}, status=200)

        cart_items = cart.items.select_related('variant__product').all()
        if not cart_items.exists():
            logger.warning(f"Cart for user {request.user.username} is empty")
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=200)

        subtotal = cart.get_subtotal()
        if subtotal <= 0:
            logger.warning(f"Invalid subtotal {subtotal} for user {request.user.username}")
            return JsonResponse({'success': False, 'message': 'Invalid cart subtotal.'}, status=200)

        valid_coupons = Coupon.objects.filter(
            is_active=True,
            valid_from__lte=timezone.now(),
            valid_to__gte=timezone.now(),
            minimum_order_amount__lte=subtotal
        ).filter(
            models.Q(usage_limit=0) | models.Q(usage_count__lt=models.F('usage_limit'))
        ).exclude(
            user_coupons__user=request.user,
            user_coupons__is_used=True
        ).select_related().order_by('-discount_percentage')

        coupons_data = [{
            'id': coupon.id,
            'code': coupon.code,
            'discount_percentage': float(coupon.discount_percentage),
            'minimum_order_amount': float(coupon.minimum_order_amount),
            'valid_to': coupon.valid_to.isoformat()
        } for coupon in valid_coupons]

        # Calculate offer savings
        offer_savings = Decimal('0.00')
        offer_details = []
        for item in cart_items:
            try:
                best_price_info = item.variant.best_price
                original_price = best_price_info.get('original_price', Decimal('0.00'))
                discounted_price = best_price_info.get('price', Decimal('0.00'))
                quantity = Decimal(str(item.quantity))
                item_discount = (original_price - discounted_price) * quantity
                if item_discount > 0:
                    offer_savings += item_discount
                    offer_details.append({
                        'product': item.variant.product.product_name,
                        'offer_type': best_price_info.get('applied_offer_type', 'None'),
                        'discount': float(item_discount)
                    })
            except (AttributeError, KeyError, ValueError) as e:
                logger.error(f"Error calculating offer savings for item {item.id}: {str(e)}")
                continue

        response_data = {
            'success': True,
            'coupons': coupons_data,
            'offer_savings': float(offer_savings) if offer_savings else None,
            'offer_details': offer_details
        }

        # Include applied coupon info if present
        if request.GET.get('for_checkout') and 'applied_coupon' in request.session:
            applied_coupon = request.session['applied_coupon']
            response_data['applied_coupon'] = {
                'code': applied_coupon['code'],
                'discount': applied_coupon['discount'],
                'coupon_id': applied_coupon['coupon_id']
            }

        logger.info(f"User {request.user.username} fetched {len(coupons_data)} available coupons. Subtotal: {subtotal}")
        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Error fetching available coupons for user {request.user.username}: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': 'Failed to load coupons. Please try again.'}, status=500)

@login_required
def view_coupons(request):
    now = timezone.now()
    coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    ).filter(
        Q(usage_limit=0) | Q(usage_count__lt=F('usage_limit'))
    ).exclude(
        user_coupons__user=request.user,
        user_coupons__is_used=True
    ).order_by('-created_at')
    
    # Check if JSON response requested
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        coupons_data = []
        for coupon in coupons:
            coupons_data.append({
                'id': coupon.id,
                'code': coupon.code,
                'discount_percentage': float(coupon.discount_percentage),
                'minimum_order_amount': float(coupon.minimum_order_amount),
                'valid_from': coupon.valid_from.strftime('%Y-%m-%d %H:%M'),
                'valid_to': coupon.valid_to.strftime('%Y-%m-%d %H:%M'),
                'usage_limit': coupon.usage_limit,
                'usage_count': coupon.usage_count,
                'description': f"{coupon.discount_percentage}% off on orders above ₹{coupon.minimum_order_amount}"
            })
        return JsonResponse({'coupons': coupons_data})
    
    # Regular template response
    highlighted_coupon = request.GET.get('highlight')
    context = {
        'coupons': coupons,
        'highlighted_coupon': highlighted_coupon,
        'now': now
    }
    return render(request, 'offer_and_coupon_app/available_coupons.html', context)

@login_required
def cancel_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    item_name = cart_item.variant.product.product_name
    cart_item.delete()
    logger.info(f"User {request.user.username} removed cart item {item_name} (ID: {item_id})")
    
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.select_related('variant__product').all()
    
    # Clear any residual coupon session data
    if 'applied_coupon' in request.session:
        del request.session['applied_coupon']
        request.session.modified = True
        messages.info(request, "Coupon data cleared from cart.")

    # Calculate totals with offers only
    total_price, discount_info = apply_offers_to_cart(cart_items, None, request.user)
    
    # Update session with new offer details
    offer_details = []
    for item in cart_items:
        best_price_info = item.variant.best_price
        if best_price_info['applied_offer_type'] in ['product', 'category']:
            offer_details.append({
                'product': item.variant.product.product_name,
                'offer_type': best_price_info['applied_offer_type'],
                'discount': float((best_price_info['original_price'] - best_price_info['price']) * Decimal(str(item.quantity)))
            })
    request.session['applied_offers'] = offer_details
    request.session.modified = True

    messages.success(request, f"{item_name} removed from cart.")
    logger.info(f"Cart updated for user {request.user.username}. Total: {total_price}, Discounts: {discount_info}")
    return redirect('cart_and_orders_app:user_cart_list')

@login_required
def view_coupons(request):
    now = timezone.now()
    available_coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    ).filter(
        Q(usage_limit=0) | Q(usage_count__lt=F('usage_limit'))
    ).exclude(
        user_coupons__user=request.user,
        user_coupons__is_used=True
    ).prefetch_related('applicable_products').order_by('-created_at') 
    highlighted_coupon = request.GET.get('highlight', None)
    context = {
        'coupons': available_coupons,
        'highlighted_coupon': highlighted_coupon,
        'now': now
    }
    return render(request, 'offer_and_coupon_app/available_coupons.html', context)

@login_required
def wallet_dashboard(request):
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')[:10]  
    return render(request, 'offer_and_coupon_app/user_wallet_dashboard.html', {
        'wallet': wallet,
        'transactions': transactions
    })

def coupon_usage_report(request):
    coupons = Coupon.objects.annotate(
        total_users=models.Count('user_usages', distinct=True),
        total_discount=models.Sum('user_usages__order__discount_amount')
    ).order_by('-usage_count')
    return render(request, 'admin_coupon_usage_report.html', {'coupons': coupons})

@login_required
def add_funds(request):
    if request.method != 'POST':
        logger.warning("Invalid request method for add_funds: %s", request.method)
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    amount = request.POST.get('amount')
    if not amount:  
        logger.error("Amount is missing or empty")
        return JsonResponse({'success': False, 'message': 'Amount is required.'}, status=400)
    try:
        amount = Decimal(amount)
        if amount <= 0:
            logger.warning("Invalid amount for adding funds: %s", amount)
            return JsonResponse({'success': False, 'message': 'Amount must be greater than zero.'}, status=400)
        amount_in_paise = int(amount * 100)
    except (ValueError, TypeError, InvalidOperation):
        logger.error("Invalid amount format: %s", amount)
        return JsonResponse({'success': False, 'message': 'Invalid amount format.'}, status=400)
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    try:
        razorpay_order = client.order.create({
            'amount': amount_in_paise,  
            'currency': 'INR',
            'payment_capture': 1
        })
    except Exception as e:
        logger.error("Razorpay order creation failed: %s", str(e))
        return JsonResponse({'success': False, 'message': 'Failed to create payment order.'}, status=500)

    return JsonResponse({
        'success': True,
        'razorpay_order': razorpay_order,
        'razorpay_key': settings.RAZORPAY_KEY_ID,
        'amount': amount_in_paise,
        'currency': 'INR',
        'name': 'Core Fitness',
        'description': 'Add Funds to Wallet',
        'callback_url': '/offer/add-funds-callback/',
        'prefill': {
            'name': request.user.get_full_name() or request.user.username,
            'email': request.user.email,
            'contact': ''
        }
    })

@login_required
def add_funds_callback(request):
    if request.method != 'POST':
        logger.warning("Invalid request method for add_funds_callback: %s", request.method)
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    
    try:
        data = json.loads(request.body.decode('utf-8'))
        payment_id = data.get('razorpay_payment_id')
        razorpay_order_id = data.get('razorpay_order_id')
        signature = data.get('razorpay_signature')
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error("Failed to parse JSON payload: %s", str(e))
        return JsonResponse({'success': False, 'message': 'Invalid request data'}, status=400)
    
    if not all([payment_id, razorpay_order_id, signature]):
        logger.error("Missing Razorpay parameters: payment_id=%s, order_id=%s, signature=%s", payment_id, razorpay_order_id, signature)
        return JsonResponse({'success': False, 'message': 'Missing payment details'}, status=400)

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    params_dict = {
        'razorpay_order_id': razorpay_order_id,
        'razorpay_payment_id': payment_id,
        'razorpay_signature': signature
    }
    try:
        client.utility.verify_payment_signature(params_dict)
    except Exception as e:
        logger.error("Payment verification failed: %s", str(e))
        return JsonResponse({'success': False, 'message': 'Payment verification failed'}, status=400)
    
    try:
        amount = Decimal(str(client.order.fetch(razorpay_order_id)['amount'])) / 100 
        wallet = Wallet.objects.get(user=request.user)
        with transaction.atomic():
            wallet.balance += amount
            wallet.save()
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type='CREDIT',
                description=f'Added funds via Razorpay (Order ID: {razorpay_order_id})'
            )
            logger.info("Funds added successfully for user %s: %.2f", request.user.username, amount)
            return JsonResponse({
                'success': True,
                'message': 'Funds added successfully!',
                'redirect': '/wallet/'
            })
    except Exception as e:
        logger.error("Failed to add funds: %s", str(e))
        return JsonResponse({'success': False, 'message': 'Failed to add funds.'}, status=500)
    
@login_required
def referral_dashboard(request):
    user = request.user
    try:
        referral_code = user.referral_code 
    except ReferralCode.DoesNotExist:
        referral_code = ReferralCode.objects.create(user=user)
    if settings.DEBUG:
        domain = "http://127.0.0.1:8000"
    else:
        domain = "https://yourdomain.com"  
    referral_url = f"{domain}{reverse('referral_signup')}?code={referral_code.code}"
    referrals = Referral.objects.filter(referrer=user)
    referral_coupons = user.user_coupons.filter(coupon__in=[r.coupon for r in referrals if r.coupon])
    
    context = {
        'referral_code': referral_code.code,
        'referral_url': referral_url,
        'referrals': referrals,
        'referral_coupons': referral_coupons,
    }
    
    return render(request, 'offer_and_coupon_app/referral_dashboard.html', context)

def referral_signup(request):
    code = request.GET.get('code')
    if code:
        request.session['referral_code'] = code
    return redirect('user_app:user_signup')