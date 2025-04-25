from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, F
from django.views.decorators.http import require_http_methods
from django.contrib.admin.views.decorators import staff_member_required as admin_required
from django.http import JsonResponse
from .models import WalletTransaction, Wallet
from product_app.models import Product
from django.utils import timezone
from .forms import CouponForm
from .models import Coupon
from product_app.models import Category
import logging
from django.db import models
from cart_and_orders_app.models import Order

logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_staff or user.is_superuser

@login_required
@user_passes_test(admin_required)
def admin_coupon_list(request):
    coupons = Coupon.objects.all()

    # Search filter
    search_query = request.GET.get('search', '')
    if search_query:
        coupons = coupons.filter(Q(code__icontains=search_query) | Q(discount_percentage__icontains=search_query))

    # Status filter
    status = request.GET.get('status', '')
    if status == 'active':
        coupons = coupons.filter(
            is_active=True,
            valid_from__lte=timezone.now(),
            valid_to__gte=timezone.now()
        ).filter(
            models.ExpressionWrapper(
                Q(usage_limit=0) | Q(usage_count__lt=F('usage_limit')),
                output_field=models.BooleanField()
            )
        )
    elif status == 'inactive':
        coupons = coupons.filter(
            Q(is_active=False) |
            Q(valid_from__gt=timezone.now()) |
            Q(valid_to__lt=timezone.now()) |
            (Q(usage_limit__gt=0) & Q(usage_count__gte=F('usage_limit')))
        )

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = [
        'code', '-code', 'discount_percentage', '-discount_percentage',
        'minimum_order_amount', '-minimum_order_amount',
        'valid_from', '-valid_from', 'valid_to', '-valid_to',
        'usage_count', '-usage_count', 'created_at', '-created_at'
    ]
    if sort_by in allowed_sorts:
        coupons = coupons.order_by(sort_by)
    else:
        coupons = coupons.order_by('-created_at')

    # Pagination
    paginator = Paginator(coupons, 10)  # Increased to 10
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status': status,
        'sort_by': sort_by,
        'title': 'Coupon List',
    }
    logger.info(f"Admin {request.user.username} accessed coupon list with search='{search_query}', status='{status}', sort='{sort_by}'")
    return render(request, 'offer_and_coupon_app/admin_coupon_list.html', context)


@login_required
@user_passes_test(admin_required)
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
            messages.error(request, "Please correct the errors below.")
    else:
        form = CouponForm()
    context = {
        'form': form,
        'title': 'Add Coupon',
        'action': 'Add',
    }
    return render(request, 'offer_and_coupon_app/admin_coupon_form.html', context)

@login_required
@user_passes_test(is_admin)
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
            messages.error(request, "Please correct the errors below.")
            logger.warning(f"Admin {request.user.username} failed to update coupon {coupon_id}: {form.errors}")
    else:
        form = CouponForm(instance=coupon)
    context = {
        'form': form,
        'title': f'Edit Coupon: {coupon.code}',
        'action': 'Edit',
        'coupon': coupon,
    }
    return render(request, 'offer_and_coupon_app/admin_coupon_form.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_coupon_delete(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon_code = coupon.code
    coupon.delete()
    logger.info(f"Admin {request.user.username} deleted coupon '{coupon_code}'")
    messages.success(request, f"Coupon '{coupon_code}' deleted successfully!")
    return redirect('offer_and_coupon_app:admin_coupon_list')

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_coupon_toggle(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon.is_active = not coupon.is_active
    coupon.save()
    status = "activated" if coupon.is_active else "deactivated"
    logger.info(f"Admin {request.user.username} {status} coupon '{coupon.code}'")
    messages.success(request, f"Coupon '{coupon.code}' {status} successfully!")
    return redirect('offer_and_coupon_app:admin_coupon_list')

@login_required
@user_passes_test(is_admin)
def coupon_usage_report(request):
    coupons = Coupon.objects.annotate(
        total_users=models.Count('user_coupons', distinct=True),
        # Assuming Order has discount_amount; adjust if different
        total_discount=models.Sum('user_coupons__order__discount_amount')
    ).order_by('-usage_count')
    context = {
        'coupons': coupons,
        'title': 'Coupon Usage Report',
    }
    logger.info(f"Admin {request.user.username} accessed coupon usage report")
    return render(request, 'offer_and_coupon_app/admin_coupon_usage_report.html', context)


@login_required
@user_passes_test(is_admin)
def admin_wallet_transactions(request):
    transactions = WalletTransaction.objects.all().select_related('wallet__user')
    
    # Search filter
    search_query = request.GET.get('search', '')
    if search_query:
        transactions = transactions.filter(
            Q(wallet__user__username__icontains=search_query) |
            Q(wallet__user__email__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Transaction type filter
    transaction_type = request.GET.get('type', '')
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)
    
    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = [
        'created_at', '-created_at',
        'amount', '-amount',
        'transaction_type', '-transaction_type'
    ]
    if sort_by in allowed_sorts:
        transactions = transactions.order_by(sort_by)
    else:
        transactions = transactions.order_by('-created_at')
    
    # Pagination
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

@login_required
@user_passes_test(is_admin)
def admin_wallet_transaction_detail(request, transaction_id):
    transaction = get_object_or_404(WalletTransaction, id=transaction_id)
    order = None
    if transaction.transaction_type in ['REFunded', 'CANCELLATION'] and transaction.description:
        # Assuming description contains order_id for refunds/cancellations
        try:
            order_id = transaction.description.split('Order ')[1].split(' ')[0]
            order = Order.objects.filter(order_id=order_id).first()
        except IndexError:
            pass
    
    context = {
        'transaction': transaction,
        'order': order,
        'title': f'Transaction {transaction.id}',
    }
    logger.info(f"Admin {request.user.username} viewed details for transaction {transaction_id}")
    return render(request, 'offer_and_coupon_app/admin_wallet_transaction_detail.html', context)