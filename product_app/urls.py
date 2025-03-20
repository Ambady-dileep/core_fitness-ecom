# product_app/urls.py
from django.urls import path
from .product_views import (
    admin_product_list,
    admin_add_product,
    admin_edit_product,
    admin_delete_product,
    admin_permanent_delete_product,
    admin_restore_product,
    admin_product_detail,
    user_product_list,
    user_product_detail,
    admin_delete_variant,
    add_review,
    admin_edit_variant,
    admin_approve_review,  
)
from .category_views import (
    category_detail,
    edit_category,
    delete_category,
    admin_category_list,
    admin_category_products,
    user_category_products,
    user_category_list,
    add_category,
)

app_name = 'product_app'

urlpatterns = [

    # User-Facing Product Routes
    path('products/', user_product_list, name='user_product_list'),
    path('products/<slug:slug>/', user_product_detail, name='user_product_detail'),
    path('add-review/', add_review, name='add_review'),

    # User-Facing Category Routes
    path('categories/', user_category_list, name='user_category_list'),
    path('categories/<int:category_id>/products/', user_category_products, name='user_category_products'),

    # Admin Product Routes
    path('admin/products/', admin_product_list, name='admin_product_list'), 
    path('admin/products/add/', admin_add_product, name='admin_add_product'),
    path('admin/products/edit/<slug:slug>/', admin_edit_product, name='admin_edit_product'),
    path('admin/products/delete/<slug:slug>/', admin_delete_product, name='admin_delete_product'),
    path('products/permanent-delete/<int:product_id>/', admin_permanent_delete_product, name='admin_permanent_delete_product'),
    path('admin/products/restore/<slug:slug>/', admin_restore_product, name='admin_restore_product'),
    path('admin/products/<slug:slug>/', admin_product_detail, name='admin_product_detail'),
    path('admin/reviews/approve/<int:review_id>/', admin_approve_review, name='admin_approve_review'), 

    # Admin Category Routes
    path('admin/categories/add/', add_category, name='add_category'),
    path('admin/categories/', admin_category_list, name='admin_category_list'), 
    path('admin/categories/<int:category_id>/edit/', edit_category, name='edit_category'),
    path('admin/categories/<int:category_id>/delete/', delete_category, name='delete_category'),
    path('admin/categories/<int:category_id>/', category_detail, name='category_detail'),
    path('admin/categories/<int:category_id>/products/', admin_category_products, name='admin_category_products'),

    # Admin Variant Routes
    path('admin/product/<slug:slug>/variant/<int:variant_id>/edit/', admin_edit_variant, name='admin_edit_variant'),
    path('admin/variant/<int:variant_id>/delete/', admin_delete_variant, name='admin_delete_variant'),

]