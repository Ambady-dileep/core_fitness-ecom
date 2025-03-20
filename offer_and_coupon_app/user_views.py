from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from cart_and_orders_app.models import Cart
from cart_and_orders_app.forms import CouponApplyForm
from decimal import Decimal
from django.db import models
from .models import Coupon, UserCoupon, Wallet 
from cart_and_orders_app.models import CartItem
from django.contrib import messages


import logging
logger = logging.getLogger(__name__)

@login_required
@require_POST
def apply_coupon(request):
    logger.debug("Received coupon apply request: %s", request.POST)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        form = CouponApplyForm(request.POST)
        if form.is_valid():
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
                total_price = sum(float(item.price or item.variant.price) * item.quantity for item in cart_items)
                discount = coupon.get_discount_amount(total_price, cart_items)
                logger.debug("Total price: %.2f, Discount: %.2f", total_price, discount)
                if discount > 0:
                    request.session['applied_coupon'] = {
                        'code': coupon.code,
                        'discount': float(discount)
                    }
                    request.session.modified = True  # Ensure session saves
                    UserCoupon.objects.get_or_create(
                        user=request.user,
                        coupon=coupon,
                        defaults={'is_used': False}
                    )
                    return JsonResponse({
                        'success': True,
                        'message': 'Coupon applied successfully!',
                        'discount': float(discount),
                        'new_total': float(total_price - discount)
                    })
                else:
                    logger.warning("Discount is 0, total: %.2f, min_amount: %.2f", total_price, coupon.minimum_order_amount)
                    return JsonResponse({
                        'success': False,
                        'message': f'Order total ({total_price}) is below minimum ({coupon.minimum_order_amount}) or coupon is not applicable.',
                    }, status=400)
            except Coupon.DoesNotExist:
                logger.error("Coupon not found: %s", code)
                return JsonResponse({'success': False, 'message': 'Invalid coupon code.'}, status=400)
        else:
            logger.error("Form invalid: %s", form.errors)
            return JsonResponse({'success': False, 'message': 'Invalid coupon code format.'}, status=400)
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

@login_required
@require_POST
def remove_coupon(request):
    if 'applied_coupon' in request.session:
        coupon_code = request.session['applied_coupon']['code']
        try:
            coupon = Coupon.objects.get(code=coupon_code)
            UserCoupon.objects.filter(user=request.user, coupon=coupon, is_used=False).delete()
        except Coupon.DoesNotExist:
            pass  # If coupon no longer exists, just remove from session
        del request.session['applied_coupon']
        cart = get_object_or_404(Cart, user=request.user)
        total_price = sum(float(item.price or item.variant.price) * item.quantity for item in cart.items.all())
        return JsonResponse({
            'success': True,
            'message': 'Coupon removed successfully!',
            'new_total': float(total_price)
        })
    return JsonResponse({'success': False, 'message': 'No coupon applied.'}, status=400)


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
        user_usages__user=request.user,
        user_usages__is_used=True
    ).order_by('-created_at')
    return render(request, 'available_coupons.html', {'coupons': coupons})

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
        user_usages__user=request.user,
        user_usages__is_used=True
    ).order_by('-created_at')
    context = {'coupons': available_coupons}
    return render(request, 'available_coupons.html', context)

@login_required
def cancel_cart_item(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    cart_item.delete()
    cart_items = CartItem.objects.filter(cart__user=request.user)
    total_price = sum(item.quantity * (item.price or item.variant.price) for item in cart_items)
    if 'applied_coupon' in request.session:
        coupon = Coupon.objects.get(code=request.session['applied_coupon'])
        discount = coupon.get_discount_amount(total_price, cart_items)
        if discount == 0:
            wallet, created = Wallet.objects.get_or_create(user=request.user)
            refund_amount = Decimal(request.session['discount_amount'])
            wallet.add_funds(refund_amount)  # This now creates a WalletTransaction
            del request.session['applied_coupon']
            del request.session['discount_amount']
            request.session.modified = True
            messages.info(request, f"Coupon removed and {refund_amount} refunded to your wallet.")
    return redirect('cart_and_orders_app:user_cart_list')

