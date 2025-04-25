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
    path('wallet/balance/', user_views.wallet_balance, name='wallet_balance'),
    path('add-funds/', user_views.add_funds, name='add_funds'),
    path('add-funds-callback/', user_views.add_funds_callback, name='add_funds_callback'),

    # Admin-facing URLs
    # Coupon Management
    path('admin/coupons/', admin_views.admin_coupon_list, name='admin_coupon_list'),
    path('admin/coupons/add/', admin_views.admin_coupon_add, name='admin_coupon_add'),
    path('admin/coupons/edit/<int:coupon_id>/', admin_views.admin_coupon_edit, name='admin_coupon_edit'),
    path('admin/coupons/delete/<int:coupon_id>/', admin_views.admin_coupon_delete, name='admin_coupon_delete'),
    path('admin/coupons/toggle/<int:coupon_id>/', admin_views.admin_coupon_toggle, name='admin_coupon_toggle'),
    path('admin/coupons/report/', admin_views.coupon_usage_report, name='coupon_usage_report'),

    # Wallet Management
    path('admin/wallet/', admin_views.admin_wallet_transactions, name='admin_wallet_transactions'),
    path('admin/wallet/transactions/<int:transaction_id>/', admin_views.admin_wallet_transaction_detail, name='admin_wallet_transaction_detail'),

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
  