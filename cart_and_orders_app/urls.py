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


    # User side

    path('cart/add/<int:variant_id>/', views.user_add_to_cart, name='user_add_to_cart'),
    path('cart/', views.user_cart_list, name='user_cart_list'),
    path('cart/remove/<int:item_id>/', views.user_remove_from_cart, name='user_remove_from_cart'),
    path('cart/update/<int:item_id>/', views.user_update_cart_quantity, name='user_update_cart_quantity'),


    # User wishlist

    path('wishlist/', views.user_wishlist, name='user_wishlist'),
    path('wishlist/add/<int:variant_id>/', views.user_add_to_wishlist, name='user_add_to_wishlist'),
    path('wishlist/remove/<int:wishlist_id>/', views.user_remove_from_wishlist, name='user_remove_from_wishlist'),
    path('wishlist/check/', views.check_wishlist, name='check_wishlist'),


    # Checkout URLs

    path('checkout/', views.user_checkout, name='user_checkout'),
    path('order/success/<str:order_id>/', views.user_order_success, name='order_success'),
    path('place-order/', views.place_order, name='place_order'),
    path('admin/order/<str:order_id>/cancel/', views.admin_cancel_order, name='admin_cancel_order'),


    # Order Management URLs

    path('orders/', views.user_order_list, name='user_order_list'), 
    path('admin/orders/', views.admin_orders_list, name='admin_orders_list'),
    path('admin/orders/<str:order_id>/', views.admin_order_detail, name='admin_order_detail'),
    path('admin/returns/<int:return_id>/verify/', views.admin_verify_return_request, name='admin_verify_return_request'),
    path('admin/inventory/', views.admin_inventory_list, name='admin_inventory_list'),
    path('admin/inventory/<int:variant_id>/update-stock/', views.admin_update_stock, name='admin_update_stock'),
    path('orders/<str:order_id>/', views.user_order_detail, name='user_order_detail'),  
    path('orders/<str:order_id>/cancel/', views.user_cancel_order, name='user_cancel_order'),  
    path('orders/<str:order_id>/return/', views.user_return_order, name='user_return_order'), 
    path('orders/<str:order_id>/download-invoice/', views.download_invoice, name='download_invoice'), 
    path('order/success/<str:order_id>/', views.user_order_success, name='user_order_success'),
    path('admin/order/<str:order_id>/ship/', views.admin_mark_shipped, name='admin_mark_shipped'),
    path('cart/buy-now/', views.buy_now, name='user_buy_now'),
    path('checkout/', views.user_checkout, name='user_checkout'),
    path('set-buy-now-flag/', views.set_buy_now_flag, name='set_buy_now_flag'),
    
    
]