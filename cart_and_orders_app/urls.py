from django.urls import path
from . import views

app_name = 'cart_and_orders_app'

urlpatterns = [
    # Admin side
    path('admin/orders/', views.admin_orders_list, name='admin_orders_list'),
    path('admin/orders/<str:order_id>/', views.admin_order_detail, name='admin_order_detail'),
    path('admin/returns/<int:return_id>/verify/', views.admin_verify_return_request, name='admin_verify_return_request'),
    path('admin/bulk-actions/', views.admin_bulk_actions, name='admin_bulk_actions'),
    path('admin/update-stock/<int:variant_id>/', views.admin_update_stock, name='admin_update_stock'),
    path('admin/mark-shipped/<str:order_id>/', views.admin_mark_shipped, name='admin_mark_shipped'),
    path('admin/cancel-order/<str:order_id>/', views.admin_cancel_order, name='admin_cancel_order'),
    path('admin/inventory/', views.admin_inventory_list, name='admin_inventory_list'),

    # User side - Cart
    path('cart/', views.user_cart_list, name='user_cart_list'),
    path('cart/add-to-cart/<int:variant_id>/', views.user_add_to_cart, name='user_add_to_cart_by_variant'),
    path('cart/update/<int:item_id>/', views.user_update_cart_quantity, name='user_update_cart_quantity'),
    path('cart/buy-now/', views.buy_now, name='user_buy_now'),
    path('cart/set-buy-now-flag/', views.set_buy_now_flag, name='set_buy_now_flag'),
    path('orders/<str:order_id>/retry-payment/', views.retry_payment, name='retry_payment'),

    # User side - Wishlist
    path('wishlist/', views.user_wishlist, name='user_wishlist'),
    path('add-to-wishlist/<int:variant_id>/', views.user_add_to_wishlist, name='user_add_to_wishlist'),
    path('wishlist/remove-by-variant/<int:variant_id>/', views.user_remove_from_wishlist_by_variant, name='remove_from_wishlist_by_variant'),
    path('wishlist/check-variant/', views.check_wishlist_variant, name='check_wishlist_variant'),
    path('wishlist/check/', views.check_wishlist, name='check_wishlist'),
    path('wishlist/remove/<int:variant_id>/', views.user_remove_from_wishlist_by_variant, name='user_remove_from_wishlist_by_variant'),

    # Checkout URLs
    path('checkout/', views.user_checkout, name='user_checkout'),
    path('place-order/', views.place_order, name='place_order'),
    path('cart/razorpay-callback/', views.razorpay_callback, name='razorpay_callback'),  
    path('order/success/<str:order_id>/', views.user_order_success, name='order_success'),  
    path('order/failure/<str:order_id>/', views.user_order_failure, name='order_failure'),
    path('log-payment-error/', views.log_payment_error, name='log_payment_error'),
    path('cart/clear/', views.clear_cart, name='clear_cart'),
    path('initiate-payment/', views.initiate_payment, name='initiate_payment'),

    # Order Management URLs
    path('orders/', views.user_order_list, name='user_order_list'),
    path('orders/<str:order_id>/', views.user_order_detail, name='user_order_detail'),
    path('orders/<str:order_id>/cancel/', views.user_cancel_order, name='user_cancel_order'),
    path('orders/<str:order_id>/cancel-item/<int:item_id>/', views.user_cancel_order_item, name='user_cancel_order_item'),
    path('orders/<str:order_id>/return/', views.user_return_order, name='user_return_order'),
    path('orders/<str:order_id>/download-invoice/', views.download_invoice, name='download_invoice'),
    path('admin/orders/<str:order_id>/delivered/', views.admin_mark_delivered, name='admin_mark_delivered'),

    path('sales/dashboard/', views.sales_dashboard, name='sales_dashboard'),
    path('sales/report/generate/', views.generate_sales_report, name='generate_sales_report'),
    path('sales/report/<int:report_id>/', views.sales_report_detail, name='sales_report_detail'),
]
