from django.urls import path
from . import user_views, admin_views

app_name = 'offer_and_coupon_app'

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
    path('admin/coupons/', admin_views.admin_coupon_list, name='admin_coupon_list'),
    path('admin/coupons/add/', admin_views.admin_coupon_add, name='admin_coupon_add'),
    path('admin/coupons/edit/<int:coupon_id>/', admin_views.admin_coupon_edit, name='admin_coupon_edit'),
    path('admin/coupons/delete/<int:coupon_id>/', admin_views.admin_coupon_delete, name='admin_coupon_delete'),
    path('admin/coupons/report/', admin_views.coupon_usage_report, name='coupon_usage_report'),
    path('admin/offers/add/', admin_views.admin_add_offer, name='admin_add_offer'),
    path('admin/offers/', admin_views.admin_offer_list, name='admin_offer_list'),
    path('admin/offers/<int:offer_id>/edit/', admin_views.admin_edit_offer, name='admin_edit_offer'),
    path('admin/offers/<int:offer_id>/delete/', admin_views.admin_delete_offer, name='admin_delete_offer'),

    path('admin/product-offers/', admin_views.admin_product_offer_list, name='admin_product_offer_list'),
    path('admin/product-offers/add/', admin_views.admin_product_offer_add, name='admin_product_offer_add'),
    path('admin/product-offers/edit/<int:offer_id>/', admin_views.admin_product_offer_edit, name='admin_product_offer_edit'),
    path('admin/product-offers/toggle/<int:offer_id>/', admin_views.admin_product_offer_toggle, name='admin_product_offer_toggle'),
    path('admin/category-offers/', admin_views.admin_category_offer_list, name='admin_category_offer_list'),
    path('admin/category-offers/add/', admin_views.admin_category_offer_add, name='admin_category_offer_add'),
    path('admin/category-offers/add-for-category/<int:category_id>/', admin_views.admin_add_category_offer, name='admin_add_category_offer'), 
    path('admin/category-offers/toggle/<int:offer_id>/', admin_views.admin_category_offer_toggle, name='admin_category_offer_toggle'),
    path('admin/category-offers/', admin_views.admin_category_offer_list, name='admin_category_offer_list'),
    path('admin/category-offers/<int:offer_id>/edit/', admin_views.admin_category_offer_edit, name='admin_category_offer_edit'),
    path('admin/category-offers/<int:offer_id>/delete/', admin_views.admin_category_offer_delete, name='admin_category_offer_delete'),
    path('admin/category-offers/<int:offer_id>/toggle/', admin_views.admin_category_offer_toggle, name='admin_category_offer_toggle'),
    path('admin/categories/<int:category_id>/offers/', admin_views.admin_category_offers, name='admin_category_offers'),

]