from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST,require_GET
from django.utils import timezone
from .forms import CouponForm, CouponApplyForm
from django.core.paginator import Paginator
from cart_and_orders_app.models import Cart, CartItem
from decimal import Decimal
from django.db import models, transaction
from .models import Coupon, UserCoupon, Wallet, WalletTransaction
from django.contrib import messages
from django.shortcuts import redirect, render
from decimal import InvalidOperation
from django.urls import reverse
import json
from django.contrib import messages
from django.conf import settings
from django.db.models import Q, F
from django.views.decorators.csrf import csrf_exempt
import razorpay
from django.conf import settings
import logging
logger = logging.getLogger(__name__)

@login_required
@require_POST
def apply_coupon(request):
    form = CouponApplyForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'success': False, 'message': form.errors['coupon_code'][0]}, status=400)

    try:
        coupon = Coupon.objects.get(code=form.cleaned_data['coupon_code'])
        cart = get_object_or_404(Cart, user=request.user)
        if not cart.items.exists():
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=400)

        # Check if user has already used this coupon
        if UserCoupon.objects.filter(user=request.user, coupon=coupon, is_used=True).exists():
            return JsonResponse({'success': False, 'message': 'This coupon has already been used.'}, status=400)

        # Use Cart.get_totals for consistent calculations
        totals = cart.get_totals(coupon=coupon)
        if totals['subtotal'] < coupon.minimum_order_amount:
            return JsonResponse({
                'success': False,
                'message': f'This coupon requires a minimum order amount of ₹{coupon.minimum_order_amount}.'
            }, status=400)

        # Create or get UserCoupon
        UserCoupon.objects.get_or_create(
            user=request.user,
            coupon=coupon,
            defaults={'is_used': False}
        )

        request.session['applied_coupon'] = {
            'coupon_id': coupon.id,
            'code': coupon.code,
            'discount': float(totals['coupon_discount'])
        }
        request.session.modified = True

        logger.info(f"Coupon {coupon.code} applied by user {request.user.username}")
        return JsonResponse({
            'success': True,
            'message': f'Coupon {coupon.code} applied successfully!',
            'discount_info': {
                'subtotal': float(totals['subtotal']),
                'offer_discount': float(totals['offer_discount']),
                'coupon_discount': float(totals['coupon_discount']),
                'coupon_code': coupon.code,
                'shipping_cost': float(totals['shipping_cost']),
                'total': float(totals['total'])
            }
        })
    except Coupon.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Invalid coupon code.'}, status=400)
    except Exception as e:
        logger.error(f"Apply Coupon Error for user {request.user.username}: {str(e)}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    

@login_required
@require_POST
def remove_coupon(request):
    if 'applied_coupon' not in request.session:
        return JsonResponse({'success': False, 'message': 'No coupon applied.'}, status=400)

    cart = get_object_or_404(Cart, user=request.user)
    if not cart.items.exists():
        return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=400)

    # Use Cart.get_totals without coupon
    totals = cart.get_totals()

    del request.session['applied_coupon']
    request.session.modified = True

    logger.info(f"Coupon removed by user {request.user.username}")
    return JsonResponse({
        'success': True,
        'message': 'Coupon removed successfully!',
        'discount_info': {
            'subtotal': float(totals['subtotal']),
            'offer_discount': float(totals['offer_discount']),
            'coupon_discount': 0.0,
            'coupon_code': None,
            'shipping_cost': float(totals['shipping_cost']),
            'total': float(totals['total'])
        }
    })
      
@login_required
@require_GET
def available_coupons(request):
    try:
        cart = Cart.objects.filter(user=request.user).first()
        if not cart:
            logger.warning(f"No cart found for user {request.user.username}")
            return JsonResponse({'success': False, 'message': 'No cart available.'}, status=200)

        if not cart.items.exists():
            logger.warning(f"Cart for user {request.user.username} is empty")
            return JsonResponse({'success': False, 'message': 'Your cart is empty.'}, status=200)

        totals = cart.get_totals()
        subtotal = totals['subtotal']
        if subtotal <= 0:
            logger.warning(f"Invalid subtotal {subtotal} for user {request.user.username}")
            return JsonResponse({'success': False, 'message': 'Invalid cart subtotal.'}, status=200)

        valid_coupons = Coupon.objects.filter(
            is_active=True,
            valid_from__lte=timezone.now(),
            valid_to__gte=timezone.now(),
            minimum_order_amount__lte=subtotal
        ).exclude(
            user_coupons__user=request.user,
            user_coupons__is_used=True
        ).order_by('-discount_percentage')

        coupons_data = [{
            'id': coupon.id,
            'code': coupon.code,
            'discount_percentage': float(coupon.discount_percentage),
            'minimum_order_amount': float(coupon.minimum_order_amount),
            'valid_to': coupon.valid_to.isoformat()
        } for coupon in valid_coupons]

        response_data = {
            'success': True,
            'coupons': coupons_data,
            'offer_savings': float(totals['offer_discount']),
            'offer_details': totals.get('offer_details', [])
        }

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
        logger.error(f"Error fetching available coupons for user {request.user.username}: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Failed to load coupons.'}, status=500)

@login_required
def view_coupons(request):
    now = timezone.now()
    available_coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    ).exclude(
        user_coupons__user=request.user,
        user_coupons__is_used=True
    ).order_by('-created_at')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        coupons_data = [{
            'id': coupon.id,
            'code': coupon.code,
            'discount_percentage': float(coupon.discount_percentage),
            'minimum_order_amount': float(coupon.minimum_order_amount),
            'valid_from': coupon.valid_from.strftime('%Y-%m-%d %H:%M'),
            'valid_to': coupon.valid_to.strftime('%Y-%m-%d %H:%M'),
            'description': f"{coupon.discount_percentage}% off on orders above ₹{coupon.minimum_order_amount}"
        } for coupon in available_coupons]
        return JsonResponse({'coupons': coupons_data})

    highlighted_coupon = request.GET.get('highlight')
    context = {
        'coupons': available_coupons,
        'highlighted_coupon': highlighted_coupon,
        'now': now
    }
    return render(request, 'offer_and_coupon_app/available_coupons.html', context)

@login_required
def view_coupons(request):
    now = timezone.now()
    available_coupons = Coupon.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    ).exclude(
        user_coupons__user=request.user,
        user_coupons__is_used=True
    ).order_by('-created_at')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        coupons_data = [{
            'id': coupon.id,
            'code': coupon.code,
            'discount_percentage': float(coupon.discount_percentage),
            'minimum_order_amount': float(coupon.minimum_order_amount),
            'valid_from': coupon.valid_from.strftime('%Y-%m-%d %H:%M'),
            'valid_to': coupon.valid_to.strftime('%Y-%m-%d %H:%M'),
            'description': f"{coupon.discount_percentage}% off on orders above ₹{coupon.minimum_order_amount}"
        } for coupon in available_coupons]
        return JsonResponse({'coupons': coupons_data})

    highlighted_coupon = request.GET.get('highlight')
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

@login_required
@require_GET
def wallet_balance(request):
    try:
        wallet = Wallet.objects.get(user=request.user)
        return JsonResponse({'success': True, 'balance': float(wallet.balance)})
    except Wallet.DoesNotExist:
        return JsonResponse({'success': True, 'balance': 0.0})
    except Exception as e:
        logger.error(f"Error fetching wallet balance for user {request.user.username}: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Unable to fetch wallet balance'}, status=500)

@login_required
def coupon_usage_report(request):
    coupons = Coupon.objects.annotate(
        total_users=models.Count('user_coupons', distinct=True),
        total_discount=models.Sum('user_coupons__order__coupon_discount')
    ).order_by('-total_users')
    return render(request, 'offer_and_coupon_app/admin_coupon_usage_report.html', {'coupons': coupons})

@login_required
@require_POST
def add_funds(request):
    try:
        amount = Decimal(request.POST.get('amount', '0'))
        if amount <= 0:
            logger.warning(f"Invalid amount for add_funds by user {request.user.username}: {amount}")
            return JsonResponse({'success': False, 'message': 'Amount must be greater than zero.'}, status=400)
    except (ValueError, TypeError):
        logger.error(f"Invalid amount format for add_funds by user {request.user.username}")
        return JsonResponse({'success': False, 'message': 'Invalid amount format.'}, status=400)

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    try:
        razorpay_order = client.order.create({
            'amount': int(amount * 100),
            'currency': 'INR',
            'payment_capture': 1
        })
        logger.info(f"Razorpay order created for add_funds by user {request.user.username}: {razorpay_order['id']}")
        return JsonResponse({
            'success': True,
            'razorpay_order': razorpay_order,
            'razorpay_key': settings.RAZORPAY_KEY_ID,
            'amount': int(amount * 100),
            'currency': 'INR',
            'name': 'Core Fitness',
            'description': 'Add Funds to Wallet',
            'callback_url': request.build_absolute_uri(reverse('offer_and_coupon_app:add_funds_callback')),
            'prefill': {
                'name': request.user.get_full_name() or request.user.username,
                'email': request.user.email,
                'contact': ''
            }
        })
    except Exception as e:
        logger.error(f"Razorpay order creation failed for user {request.user.username}: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Failed to create payment order.'}, status=500)

@login_required
@require_POST
def add_funds_callback(request):
    payment_id = request.POST.get('razorpay_payment_id')
    razorpay_order_id = request.POST.get('razorpay_order_id')
    signature = request.POST.get('razorpay_signature')

    if not all([payment_id, razorpay_order_id, signature]):
        logger.error(f"Missing Razorpay parameters for user {request.user.username}: payment_id={payment_id}, order_id={razorpay_order_id}")
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
        logger.error(f"Payment verification failed for user {request.user.username}: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Payment verification failed'}, status=400)

    try:
        amount = Decimal(client.order.fetch(razorpay_order_id)['amount']) / 100
        wallet, created = Wallet.objects.get_or_create(user=request.user)
        with transaction.atomic():
            wallet.balance += amount
            wallet.save()
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type='CREDIT',
                description=f'Added funds via Razorpay (Order ID: {razorpay_order_id})'
            )
        logger.info(f"Funds added successfully for user {request.user.username}: {amount}")
        return JsonResponse({
            'success': True,
            'message': 'Funds added successfully!',
            'redirect': reverse('offer_and_coupon_app:wallet_dashboard')
        })
    except Exception as e:
        logger.error(f"Failed to add funds for user {request.user.username}: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Failed to add funds.'}, status=500)
    