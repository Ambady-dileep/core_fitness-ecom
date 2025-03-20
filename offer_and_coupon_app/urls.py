from django.urls import path
from . import user_views, admin_views

app_name = 'offer_and_coupon'

urlpatterns = [
    # User-facing URLs
    path('apply-coupon/', user_views.apply_coupon, name='apply_coupon'),
    path('coupons/', user_views.available_coupons, name='available_coupons'), 
    path('remove-coupon/', user_views.remove_coupon, name='remove_coupon'),

    # Admin-facing URLs
    path('admin/coupons/', admin_views.admin_coupon_list, name='admin_coupon_list'),
    path('admin/coupons/add/', admin_views.admin_coupon_add, name='admin_coupon_add'),
    path('admin/coupons/<int:coupon_id>/edit/', admin_views.admin_coupon_edit, name='admin_coupon_edit'),
    path('admin/coupons/<int:coupon_id>/delete/', admin_views.admin_coupon_delete, name='admin_coupon_delete'),
    # Optional: Add usage report if implemented
    #path('admin/coupons/usage-report/', admin_views.coupon_usage_report, name='coupon_usage_report'),
]