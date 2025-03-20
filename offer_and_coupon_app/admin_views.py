from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from .models import Coupon
from .forms import CouponForm

def admin_required(user):
    return user.is_staff or user.is_superuser

@user_passes_test(admin_required, login_url='user_app:user_login')
def admin_coupon_list(request):
    coupons = Coupon.objects.all().order_by('-created_at')
    return render(request, 'admin_coupon_list.html', {'coupons': coupons})

@user_passes_test(admin_required, login_url='user_app:user_login')
def admin_coupon_add(request):
    if request.method == 'POST':
        form = CouponForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('offer_and_coupon:admin_coupon_list')
    else:
        form = CouponForm()
    return render(request, 'admin_coupon_form.html', {'form': form, 'action': 'Add'})

@user_passes_test(admin_required, login_url='user_app:user_login')
def admin_coupon_edit(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    if request.method == 'POST':
        form = CouponForm(request.POST, instance=coupon)
        if form.is_valid():
            form.save()
            return redirect('offer_and_coupon:admin_coupon_list')
    else:
        form = CouponForm(instance=coupon)
    return render(request, 'admin_coupon_form.html', {'form': form, 'action': 'Edit', 'coupon': coupon})

@user_passes_test(admin_required, login_url='user_app:user_login')
def admin_coupon_delete(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    if request.method == 'POST':
        coupon.delete()
        return redirect('offer_and_coupon:admin_coupon_list')
    return render(request, 'admin_coupon_confirm_delete.html', {'coupon': coupon})


from django.contrib.auth.decorators import user_passes_test

@user_passes_test(admin_required, login_url='user_app:user_login')
def coupon_usage_report(request):
    coupons = Coupon.objects.all().order_by('-usage_count')
    return render(request, 'admin_coupon_usage_report.html', {'coupons': coupons})