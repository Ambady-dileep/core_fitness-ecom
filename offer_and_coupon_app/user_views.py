from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
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
from django.contrib.auth.decorators import login_required
from django.urls import reverse
import json
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
    logger.debug("Received coupon apply request: %s", request.POST)
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

    form = CouponApplyForm(request.POST)
    if not form.is_valid():
        logger.error("Form invalid: %s", form.errors)
        return JsonResponse({'success': False, 'message': 'Invalid coupon code format.'}, status=400)

    code = form.cleaned_data['coupon_code']
    logger.debug("Coupon code: %s", code)

    if 'applied_coupon' in request.session:
        logger.warning("Coupon already applied: %s", request.session['applied_coupon'])
        return JsonResponse({'success': False, 'message': 'A coupon is already applied. Remove it first.'}, status=400)

    try:
        coupon = Coupon.objects.get(code=code)
        logger.debug("Coupon found: %s, is_valid: %s", coupon.code, coupon.is_valid)
        if not coupon.is_valid:
            return JsonResponse({'success': False, 'message': 'Coupon is expired or invalid.'}, status=400)

        if UserCoupon.objects.filter(user=request.user, coupon=coupon, is_used=True).exists():
            logger.warning("Coupon already used by user: %s", request.user.username)
            return JsonResponse({'success': False, 'message': 'You have already used this coupon.'}, status=400)

        cart = get_object_or_404(Cart, user=request.user)
        cart_items = cart.items.all()
        
        total_price = Decimal('0.00')
        for item in cart_items:
            product = item.variant.product
            base_price = Decimal(str(item.price or item.variant.price))
            discounted_price = apply_offers_to_product(product, base_price)
            total_price += discounted_price * item.quantity
        
        discount = coupon.get_discount_amount(total_price, cart_items)
        logger.debug("Total price: %.2f, Discount: %.2f", total_price, discount)

        if discount <= 0:
            logger.warning("Discount is 0, total: %.2f, min_amount: %.2f", total_price, coupon.minimum_order_amount)
            return JsonResponse({
                'success': False,
                'message': f'Order total ({total_price}) is below minimum ({coupon.minimum_order_amount}) or coupon is not applicable.',
            }, status=400)
        
        with transaction.atomic():
            request.session['applied_coupon'] = {
                'code': coupon.code,
                'discount': float(discount),
                'coupon_id': coupon.id
            }
            request.session.modified = True
            UserCoupon.objects.get_or_create(
                user=request.user,
                coupon=coupon,
                defaults={'is_used': False}
            )

        return JsonResponse({
            'success': True,
            'message': 'Coupon applied successfully! (Will be counted after payment)',
            'discount': float(discount),
            'new_total': float(total_price - discount)
        })

    except Coupon.DoesNotExist:
        logger.error("Coupon not found: %s", code)
        return JsonResponse({'success': False, 'message': 'Invalid coupon code.'}, status=400)

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
@require_POST
def remove_coupon(request):
    if 'applied_coupon' not in request.session:
        return JsonResponse({'success': False, 'message': 'No coupon applied.'}, status=400)

    coupon_code = request.session['applied_coupon']['code']
    try:
        coupon = Coupon.objects.get(code=coupon_code)
        UserCoupon.objects.filter(user=request.user, coupon=coupon, is_used=False).delete()
    except Coupon.DoesNotExist:
        logger.warning("Coupon not found during removal: %s", coupon_code)
        pass  # If coupon no longer exists, just remove from session

    del request.session['applied_coupon']
    request.session.modified = True
    
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.all()
    
    # Calculate total with offers applied
    total_price = Decimal('0.00')
    for item in cart_items:
        product = item.variant.product
        base_price = Decimal(str(item.price or item.variant.price))
        # Apply offers to each product
        discounted_price = apply_offers_to_product(product, base_price)
        total_price += discounted_price * item.quantity
    
    return JsonResponse({
        'success': True,
        'message': 'Coupon removed successfully!',
        'new_total': float(total_price)
    })

@login_required
def available_coupons(request):
    now = timezone.now()
    coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    ).filter(
        models.Q(usage_limit=0) | models.Q(usage_count__lt=models.F('usage_limit'))
    ).exclude(
        user_coupons__user=request.user,
        user_coupons__is_used=True
    ).prefetch_related('applicable_products').order_by('-created_at') 
    logger.debug(f"Found {coupons.count()} available coupons for user {request.user.username}")
    return render(request, 'available_coupons.html', {'coupons': coupons})


@login_required
def cancel_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    cart_item.delete()
    
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.all()
    
    # Calculate total with offers applied
    total_price = Decimal('0.00')
    for item in cart_items:
        product = item.variant.product
        base_price = Decimal(str(item.price or item.variant.price))
        # Apply offers to each product
        discounted_price = apply_offers_to_product(product, base_price)
        total_price += discounted_price * item.quantity

    if 'applied_coupon' in request.session:
        try:
            coupon = Coupon.objects.get(code=request.session['applied_coupon']['code'])
            discount = coupon.get_discount_amount(total_price, cart_items)
            if discount == 0:
                wallet, created = Wallet.objects.get_or_create(user=request.user)
                refund_amount = Decimal(str(request.session['applied_coupon']['discount']))
                wallet.add_funds(refund_amount)
                del request.session['applied_coupon']
                request.session.modified = True
                messages.info(request, f"Coupon removed and {refund_amount} refunded to your wallet.")
        except Coupon.DoesNotExist:
            logger.warning("Coupon not found during cart item cancellation: %s", request.session['applied_coupon']['code'])
            del request.session['applied_coupon']
            request.session.modified = True
            messages.info(request, "Coupon removed due to invalid coupon code.")

    return redirect('cart_and_orders_app:user_cart_list')

@login_required
def view_coupons(request):
    now = timezone.now()
    available_coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    ).filter(
        models.Q(usage_limit=0) | models.Q(usage_count__lt=models.F('usage_limit'))
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
    return render(request, 'available_coupons.html', context)

@login_required
def wallet_dashboard(request):
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')[:10]  
    return render(request, 'user_wallet_dashboard.html', {
        'wallet': wallet,
        'transactions': transactions
    })

def admin_coupon_list(request):
    coupons = Coupon.objects.all().order_by('-created_at')
    paginator = Paginator(coupons, 5) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin_coupon_list.html', {'page_obj': page_obj})


def admin_coupon_add(request):
    if request.method == 'POST':
        form = CouponForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Coupon added successfully!")
            return redirect('offer_and_coupon:admin_coupon_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CouponForm()
    return render(request, 'admin_coupon_form.html', {'form': form, 'action': 'Add'})

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
@csrf_exempt
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