from django.urls import path
from django.shortcuts import redirect
from . import user_views, admin_views

app_name = 'offer_and_coupon_app'

def redirect_to_offer_list(request, *args, **kwargs):
    return redirect('offer_and_coupon_app:admin_offer_list')

urlpatterns = [
    # User-facing URLs
    path('apply-coupon/', user_views.apply_coupon, name='apply_coupon'),
    path('remove-coupon/', user_views.remove_coupon, name='remove_coupon'),
    path('coupons/', user_views.available_coupons, name='available_coupons'),
    path('view-coupons/', user_views.view_coupons, name='view_coupons'),
    path('cancel-cart-item/<int:item_id>/', user_views.cancel_cart_item, name='cancel_cart_item'),
    path('wallet/', user_views.wallet_dashboard, name='wallet_dashboard'),
    path('add-funds/', user_views.add_funds, name='add_funds'),
    path('add-funds-callback/', user_views.add_funds_callback, name='add_funds_callback'),
    path('referral/dashboard/', user_views.referral_dashboard, name='referral_dashboard'),
    path('referral/signup/', user_views.referral_signup, name='referral_signup'),

    # Admin-facing URLs
    # Coupon Management
    path('admin/coupons/', admin_views.admin_coupon_list, name='admin_coupon_list'),
    path('admin/coupons/add/', admin_views.admin_coupon_add, name='admin_coupon_add'),
    path('admin/coupons/edit/<int:coupon_id>/', admin_views.admin_coupon_edit, name='admin_coupon_edit'),
    path('admin/coupons/delete/<int:coupon_id>/', admin_views.admin_coupon_delete, name='admin_coupon_delete'),
    path('admin/coupons/toggle/<int:coupon_id>/', admin_views.admin_coupon_toggle, name='admin_coupon_toggle'),
    path('admin/coupons/report/', admin_views.coupon_usage_report, name='coupon_usage_report'),

    # Unified Offer Management
    path('admin/offers/', admin_views.admin_offer_list, name='admin_offer_list'),
    path('admin/offers/add/', admin_views.admin_add_offer, name='admin_add_offer'),
    path('admin/offers/<int:offer_id>/edit/', admin_views.admin_edit_offer, name='admin_edit_offer'),
    path('admin/offers/<int:offer_id>/delete/', admin_views.admin_delete_offer, name='admin_delete_offer'),
    path('admin/offers/<int:offer_id>/toggle-product/', admin_views.admin_product_offer_toggle, name='admin_product_offer_toggle'),
    path('admin/offers/<int:offer_id>/toggle-category/', admin_views.admin_category_offer_toggle, name='admin_category_offer_toggle'),
    path('admin/categories/<int:category_id>/offers/', admin_views.admin_category_offers, name='admin_category_offers'),
    path('admin/categories/<int:category_id>/offers/add/', admin_views.admin_add_category_offer, name='admin_add_category_offer'),

    # Redirect old product offer URLs
    path('admin/product-offers/', redirect_to_offer_list, name='admin_product_offer_list'),
    path('admin/product-offers/add/', redirect_to_offer_list, name='admin_product_offer_add'),
    path('admin/product-offers/edit/<int:offer_id>/', redirect_to_offer_list, name='admin_product_offer_edit'),
    path('admin/product-offers/form/<int:offer_id>/', redirect_to_offer_list, name='admin_product_offer_form'),

    # Redirect old category offer URLs
    path('admin/category-offers/', redirect_to_offer_list, name='admin_category_offer_list'),
    path('admin/category-offers/add/', redirect_to_offer_list, name='admin_category_offer_add'),
    path('admin/category-offers/edit/<int:offer_id>/', redirect_to_offer_list, name='admin_category_offer_edit'),
    path('admin/category-offers/delete/<int:offer_id>/', redirect_to_offer_list, name='admin_category_offer_delete'),
]
  