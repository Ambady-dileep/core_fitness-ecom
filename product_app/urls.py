from django.urls import path
from .product_views import (
    admin_product_list,
    admin_product_detail,
    user_product_list,
    user_product_detail,
    admin_add_product,
    admin_toggle_product_status,
    get_product_variants,
    admin_edit_product,
    get_variant_images,
    approve_review,
    delete_review,
    admin_toggle_variant_status,
    add_review,
    autocomplete,
)
from .category_views import (
    admin_category_list,
    admin_category_detail,
    admin_add_category,
    admin_edit_category,
    admin_delete_category,
    admin_toggle_category_status,
    user_category_list,
    user_category_detail,
    get_subcategories,
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
    path('add-review/', add_review, name='add_review'),
    path('admin/reviews/<int:review_id>/approve/', approve_review, name='admin_approve_review'),
    path('admin/reviews/<int:review_id>/delete/', delete_review, name='admin_delete_review'),
    path('autocomplete/', autocomplete, name='autocomplete'),

    # User-Facing Category Routes
    path('categories/', user_category_list, name='user_category_list'),
    path('categories/<slug:slug>/', user_category_detail, name='user_category_detail'),
    path('get-subcategories/', get_subcategories, name='get_subcategories'),

    # Admin Product Routes
    path('admin/products/', admin_product_list, name='admin_product_list'),
    path('admin/products/add/', admin_add_product, name='admin_add_product'),
    path('admin/products/<slug:slug>/', admin_product_detail, name='admin_product_detail'),
    path('admin/products/<slug:slug>/edit/', admin_edit_product, name='admin_edit_product'),
    path('admin/product/<int:product_id>/variants/', get_product_variants, name='admin_product_variants'),
    path('admin/product/<int:product_id>/toggle-status/', admin_toggle_product_status, name='admin_toggle_product_status'),
    path('get-variant-images/<int:variant_id>/', get_variant_images, name='get_variant_images'),
    path('admin/product/variant/<int:variant_id>/toggle-status/', admin_toggle_variant_status, name='admin_toggle_variant_status'),

    # Admin Category Routes
    path('admin/categories/', admin_category_list, name='admin_category_list'),
    path('admin/categories/add/', admin_add_category, name='admin_add_category'),
    path('admin/categories/<int:category_id>/', admin_category_detail, name='admin_category_detail'),
    path('admin/categories/<slug:slug>/', admin_category_detail, name='admin_category_detail_by_slug'),
    path('admin/categories/<int:category_id>/edit/', admin_edit_category, name='admin_edit_category'),
    path('admin/categories/<int:category_id>/delete/', admin_delete_category, name='admin_delete_category'),
    path('admin/categories/<int:category_id>/toggle-status/', admin_toggle_category_status, name='admin_toggle_category_status'),

    # Admin Brand Routes
    path('admin/brands/', admin_brand_list, name='admin_brand_list'),
    path('admin/brands/create/', admin_brand_create, name='admin_brand_create'),
    path('admin/brands/<int:brand_id>/edit/', admin_brand_edit, name='admin_brand_edit'),
    path('admin/brands/<int:brand_id>/delete/', admin_brand_delete, name='admin_brand_delete'),
    path('admin/brands/<int:brand_id>/detail/', admin_brand_detail, name='admin_brand_detail'),
    path('admin/brands/<int:brand_id>/toggle-status/', admin_toggle_brand_status, name='admin_toggle_brand_status'),
]