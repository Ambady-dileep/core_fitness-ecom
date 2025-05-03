from django.urls import path
from .product_views import (
    admin_product_list,
    admin_product_detail,
    user_product_list,
    user_product_detail,
    admin_add_product,
    admin_toggle_product_status,
    admin_edit_product,
    approve_review,
    delete_review,
    submit_review,
    admin_toggle_variant_status,
)
from .category_views import (
    admin_category_list,
    admin_category_detail,
    admin_add_category,
    admin_edit_category,
    admin_toggle_category_status,
    user_category_list,
    admin_brand_list,
    admin_brand_create,
    admin_brand_edit,
    admin_brand_delete,
    admin_brand_detail,
    admin_toggle_brand_status,
)

app_name = 'product_app'

urlpatterns = [
    # User Routes
    path('products/', user_product_list, name='user_product_list'),
    path('products/<slug:slug>/', user_product_detail, name='user_product_detail'),
    path('products/<slug:slug>/review/', submit_review, name='submit_review'),
    path('admin/reviews/<int:review_id>/approve/', approve_review, name='approve_review'),
    path('admin/reviews/<int:review_id>/delete/', delete_review, name='delete_review'),

    # User-Facing Category Routes
    path('categories/', user_category_list, name='user_category_list'),

    # Admin Product Routes
    path('admin/products/', admin_product_list, name='admin_product_list'),
    path('admin/products/add/', admin_add_product, name='admin_add_product'),
    path('admin/products/<slug:slug>/', admin_product_detail, name='admin_product_detail'),
    path('admin/products/<slug:slug>/edit/', admin_edit_product, name='admin_edit_product'),
    path('admin/product/<int:product_id>/toggle-status/', admin_toggle_product_status, name='admin_toggle_product_status'),
    path('admin/product/variant/<int:variant_id>/toggle-status/', admin_toggle_variant_status, name='admin_toggle_variant_status'),
        
    # Admin Category Routes
    path('admin/categories/', admin_category_list, name='admin_category_list'),
    path('admin/categories/add/', admin_add_category, name='admin_add_category'),
    path('admin/categories/<int:category_id>/', admin_category_detail, name='admin_category_detail'),
    path('admin/categories/<slug:slug>/', admin_category_detail, name='admin_category_detail_by_slug'),
    path('admin/categories/<int:category_id>/edit/', admin_edit_category, name='admin_edit_category'),
    path('admin/categories/<int:category_id>/toggle-status/', admin_toggle_category_status, name='admin_toggle_category_status'),

    # Admin Brand Routes
    path('admin/brands/', admin_brand_list, name='admin_brand_list'),
    path('admin/brands/create/', admin_brand_create, name='admin_brand_create'),
    path('admin/brands/<int:brand_id>/edit/', admin_brand_edit, name='admin_brand_edit'),
    path('admin/brands/<int:brand_id>/delete/', admin_brand_delete, name='admin_brand_delete'),
    path('admin/brands/<int:brand_id>/detail/', admin_brand_detail, name='admin_brand_detail'),
    path('admin/brands/<int:brand_id>/toggle-status/', admin_toggle_brand_status, name='admin_toggle_brand_status'),
]