from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.decorators.http import require_http_methods
from .models import Coupon, UserCoupon, WalletTransaction, Wallet
from .forms import CouponForm, UserCouponForm
from django.utils import timezone
from cart_and_orders_app.models import Order
import logging
from django.db import models

logger = logging.getLogger(__name__)

@staff_member_required
def admin_coupon_list(request):
    from django.utils import timezone
    from datetime import datetime

    coupons = Coupon.objects.all()
    search_query = request.GET.get('search', '')
    if search_query:
        coupons = coupons.filter(Q(code__icontains=search_query))

    status = request.GET.get('status', '')
    today = timezone.now().date()  # Use date-only for comparisons
    if status == 'active':
        coupons = coupons.filter(
            is_active=True,
            valid_from__date__lte=today,
            valid_to__date__gte=today
        )
    elif status == 'pending':
        coupons = coupons.filter(
            is_active=True,
            valid_from__date__gt=today
        )
    elif status == 'expired':
        coupons = coupons.filter(
            valid_to__date__lt=today
        )
    elif status == 'disabled':
        coupons = coupons.filter(is_active=False)

    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = [
        'code', '-code',
        'discount_percentage', '-discount_percentage',
        'minimum_order_amount', '-minimum_order_amount',
        'valid_from', '-valid_from',
        'valid_to', '-valid_to',
        'created_at', '-created_at'
    ]
    if sort_by in allowed_sorts:
        coupons = coupons.order_by(sort_by)

    paginator = Paginator(coupons, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status': status,
        'sort_by': sort_by,
        'title': 'Coupon List',
        'today': today,  # Pass today's date for template comparisons
    }
    logger.info(f"Admin {request.user.username} accessed coupon list with search='{search_query}', status='{status}', sort='{sort_by}'")
    return render(request, 'offer_and_coupon_app/admin_coupon_list.html', context)

@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_coupon_add(request):
    if request.method == 'POST':
        form = CouponForm(request.POST)
        if form.is_valid():
            coupon = form.save()
            logger.info(f"Admin {request.user.username} added coupon '{coupon.code}'")
            messages.success(request, f"Coupon '{coupon.code}' added successfully!")
            return redirect('offer_and_coupon_app:admin_coupon_list')
        else:
            logger.warning(f"Admin {request.user.username} failed to add coupon: {form.errors}")
            # Don't add a general message as we're showing inline errors now
    else:
        form = CouponForm()
    
    context = {
        'form': form,
        'title': 'Add Coupon',
        'action': 'Add',
    }
    return render(request, 'offer_and_coupon_app/admin_coupon_form.html', context)


@staff_member_required
@require_http_methods(["GET", "POST"])
def admin_coupon_edit(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    if request.method == 'POST':
        form = CouponForm(request.POST, instance=coupon)
        if form.is_valid():
            coupon = form.save()
            logger.info(f"Admin {request.user.username} updated coupon '{coupon.code}'")
            messages.success(request, f"Coupon '{coupon.code}' updated successfully!")
            return redirect('offer_and_coupon_app:admin_coupon_list')
        else:
            logger.warning(f"Admin {request.user.username} failed to update coupon {coupon_id}: {form.errors}")
    else:
        form = CouponForm(instance=coupon)
    
    context = {
        'form': form,
        'title': f'Edit Coupon: {coupon.code}',
        'action': 'Update',
        'coupon': coupon,
    }
    return render(request, 'offer_and_coupon_app/admin_coupon_form.html', context)

@staff_member_required
@require_http_methods(["POST"])
def admin_coupon_delete(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon_code = coupon.code
    coupon.delete()
    logger.info(f"Admin {request.user.username} deleted coupon '{coupon_code}'")
    messages.success(request, f"Coupon '{coupon_code}' deleted successfully!")
    return redirect('offer_and_coupon_app:admin_coupon_list')

@staff_member_required
@require_http_methods(["POST"])
def admin_coupon_toggle(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon.is_active = not coupon.is_active
    coupon.save()
    status = "activated" if coupon.is_active else "deactivated"
    logger.info(f"Admin {request.user.username} {status} coupon '{coupon.code}'")
    messages.success(request, f"Coupon '{coupon.code}' {status} successfully!")
    return redirect('offer_and_coupon_app:admin_coupon_list')

@staff_member_required
def coupon_usage_report(request):
    coupons = Coupon.objects.annotate(
        total_users=models.Count('user_coupons', distinct=True),
        total_discount=models.Sum('user_coupons__order__coupon_discount')
    ).order_by('-total_users')
    context = {
        'coupons': coupons,
        'title': 'Coupon Usage Report',
    }
    logger.info(f"Admin {request.user.username} accessed coupon usage report")
    return render(request, 'offer_and_coupon_app/admin_coupon_usage_report.html', context)

@staff_member_required
def admin_wallet_transactions(request):
    transactions = WalletTransaction.objects.select_related('wallet__user').all()
    search_query = request.GET.get('search', '')
    if search_query:
        transactions = transactions.filter(
            Q(wallet__user__username__icontains=search_query) |
            Q(wallet__user__email__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    transaction_type = request.GET.get('type', '')
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)

    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = [
        'created_at', '-created_at',
        'amount', '-amount',
        'transaction_type', '-transaction_type'
    ]
    if sort_by in allowed_sorts:
        transactions = transactions.order_by(sort_by)

    paginator = Paginator(transactions, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'transaction_type': transaction_type,
        'sort_by': sort_by,
        'title': 'Wallet Transactions',
        'transaction_types': WalletTransaction.TRANSACTION_TYPES,
    }
    logger.info(f"Admin {request.user.username} accessed wallet transactions with search='{search_query}', type='{transaction_type}', sort='{sort_by}'")
    return render(request, 'offer_and_coupon_app/admin_wallet_transactions.html', context)

@staff_member_required
def admin_wallet_transaction_detail(request, transaction_id):
    transaction = get_object_or_404(WalletTransaction, id=transaction_id)
    order = None
    if transaction.transaction_type == 'REFUND' and transaction.description:
        try:
            order_id = transaction.description.split('Order ')[1].split()[0]
            order = Order.objects.filter(order_id=order_id).first()
        except (IndexError, AttributeError):
            logger.warning(f"Could not parse order_id from transaction {transaction_id} description: {transaction.description}")
    
    context = {
        'transaction': transaction,
        'order': order,
        'title': f'Transaction {transaction.id}',
    }
    logger.info(f"Admin {request.user.username} viewed details for transaction {transaction_id}")
    return render(request, 'offer_and_coupon_app/admin_wallet_transaction_detail.html', context)