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
    path('admin/orders/<str:order_id>/delivered/', views.admin_mark_delivered, name='admin_mark_delivered'),

    # User side - Cart
    path('cart/', views.user_cart_list, name='user_cart_list'),
    path('cart/add/', views.add_to_cart, name='add_to_cart'),
    path('cart/buy-now/', views.buy_now, name='buy_now'),
    path('cart/update/<int:item_id>/', views.update_cart_quantity, name='update_cart_quantity'),
    path('cart/clear/', views.clear_cart, name='clear_cart'),
    path('initiate-payment/', views.initiate_payment, name='initiate_payment'),

    # User side - Wishlist
    path('wishlist/', views.user_wishlist, name='user_wishlist'),
    path('wishlist/toggle/', views.toggle_wishlist, name='toggle_wishlist'),

    # Checkout URLs
    path('checkout/', views.user_checkout, name='user_checkout'),
    path('place-order/', views.place_order, name='place_order'),
    path('cart/razorpay-callback/', views.razorpay_callback, name='razorpay_callback'),
    path('order/<str:order_id>/success/', views.user_order_success, name='user_order_success'),
    path('order/<str:order_id>/failure/', views.user_order_failure, name='user_order_failure'),

    # Order Management URLs
    path('orders/', views.user_order_list, name='user_order_list'),
    path('orders/<str:order_id>/', views.user_order_detail, name='user_order_detail'),
    path('orders/<str:order_id>/cancel/', views.user_cancel_order, name='user_cancel_order'),
    path('orders/<str:order_id>/cancel-item/<int:item_id>/', views.user_cancel_order_item, name='user_cancel_order_item'),
    path('orders/<str:order_id>/return/', views.user_return_order, name='user_return_order'),
    path('orders/<str:order_id>/generate-pdf/', views.generate_pdf, name='generate_pdf'),
    path('orders/<str:order_id>/retry-payment/', views.retry_payment, name='retry_payment'),

    # Sales Dashboard and Reports
    path('sales/dashboard/', views.sales_dashboard, name='sales_dashboard'),
    path('sales/report/generate/', views.generate_sales_report, name='generate_sales_report'),
    path('sales/report/<int:report_id>/', views.sales_report_detail, name='sales_report_detail'),
]