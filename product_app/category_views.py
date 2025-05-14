from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.views.decorators.cache import never_cache
from django.db.models import Q
from .models import Category, Product, Brand
from .forms import CategoryForm
from django.db.models import Count
from django.urls import reverse
from django.http import JsonResponse
from django.utils import timezone
from .forms import BrandForm

def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


@login_required
@user_passes_test(is_admin)
def admin_category_list(request):
    status = request.GET.get('status', 'all')
    query = request.GET.get('q', '')
    sort_by = request.GET.get('sort', 'name')

    categories = Category.objects.all()

    if query:
        categories = categories.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )

    if status == 'active':
        categories = categories.filter(is_active=True)
    elif status == 'inactive':
        categories = categories.filter(is_active=False)

    sort_mapping = {
        'name': 'name',
        'a_to_z': 'name',
        'z_to_a': '-name',
        'newest': '-created_at',
        'oldest': 'created_at',
        'products': '-products_count'
    }
    order_by = sort_mapping.get(sort_by, 'name')
    if sort_by == 'products':
        categories = categories.annotate(products_count=Count('products')).order_by(order_by)
    else:
        categories = categories.order_by(order_by)

    paginator = Paginator(categories, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'title': 'Supplement Categories',
        'query': query,
        'sort_by': sort_by,
        'status': status,
        'total_categories': Category.objects.count(),
        'active_categories': Category.objects.filter(is_active=True).count(),
        'inactive_categories': Category.objects.filter(is_active=False).count(),
    }
    return render(request, 'product_app/admin_category_list.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_category_detail(request, category_id=None, slug=None):
    if slug:
        category = get_object_or_404(Category, slug=slug)
    else:
        category = get_object_or_404(Category, id=category_id)

    products = category.products.prefetch_related('variants__variant_images').order_by('product_name')

    product_paginator = Paginator(products, 12)
    product_page = request.GET.get('product_page', 1)
    product_page_obj = product_paginator.get_page(product_page)

    context = {
        'category': category,
        'products': product_page_obj,
        'total_products': products.count(),
        'title': f'Category: {category.name}',
    }
    return render(request, 'product_app/admin_category_detail.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_add_category(request):
    action = 'Add'
    if request.method == 'POST':
        form = CategoryForm(request.POST, request.FILES)
        if form.is_valid():
            category = form.save()
            messages.success(request, f"Category '{category.name}' added successfully!")
            return redirect('product_app:admin_category_list')
        else:
            # Add an explicit error message when form validation fails
            messages.error(request, "Please correct the errors in the form.")
    else:
        form = CategoryForm()

    context = {
        'form': form,
        'title': 'Add New Category',
        'action': action,
        'category': None,
    }
    return render(request, 'product_app/admin_category_form.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_edit_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    action = 'Edit'
    if request.method == 'POST':
        form = CategoryForm(request.POST, request.FILES, instance=category)
        if form.is_valid():
            if request.POST.get('image-clear') == 'on' and not request.FILES.get('image'):
                category.image = None
                category.save(update_fields=['image'])
            category = form.save(commit=False)
            if form.cleaned_data['offer_percentage'] is None or form.cleaned_data['offer_percentage'] == '':
                category.offer_percentage = 0.00
            category.save()
            messages.success(request, f"Category '{category.name}' updated successfully!")
            return redirect('product_app:admin_category_list')
        else:
            # Add an explicit error message when form validation fails
            messages.error(request, "Please correct the errors in the form.")
    else:
        form = CategoryForm(instance=category)

    context = {
        'form': form,
        'category': category,
        'title': f'Edit Category: {category.name}',
        'action': action,
    }
    return render(request, 'product_app/admin_category_form.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_toggle_category_status(request, category_id):
    if request.method == 'POST' and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        category = get_object_or_404(Category, id=category_id)
        category.is_active = not category.is_active
        category.save(update_fields=['is_active', 'updated_at'])
        
        return JsonResponse({
            'success': True,
            'is_active': category.is_active,
            'message': f'Category "{category.name}" is now {"active" if category.is_active else "inactive"}.'
        })
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)


################################################################### User Facing #############################################################################################


@never_cache
def user_category_list(request):
    # Fetch active categories with related data
    categories = Category.objects.filter(is_active=True).prefetch_related('products')
    
    # Add annotations for better sorting and filtering
    categories = categories.annotate(
    product_count=Count('products', filter=Q(products__is_active=True, products__category__is_active=True, products__brand__is_active=True)),
    brands_count=Count('brands', distinct=True, filter=Q(brands__is_active=True))
    )
    
    # Handle search query
    query = request.GET.get('q', '').strip()
    if query:
        categories = categories.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(brands__name__icontains=query, brands__is_active=True)
        ).distinct()

    # Handle sorting
    sort_by = request.GET.get('sort', '')
    sort_options = {
        'a_to_z': 'name',
        'z_to_a': '-name',
        'newest': '-created_at',
        'oldest': 'created_at',
        'popular': '-product_count',
        'offers': '-offer_percentage',
        '': 'name'  # Default sort
    }
    
    sort_field = sort_options.get(sort_by, 'name')
    categories = categories.order_by(sort_field)
    
    # Get featured categories (those with the most products or highest offers)
    featured_categories = Category.objects.filter(is_active=True)
    featured_categories = featured_categories.annotate(
        product_count=Count('products', filter=Q(products__is_active=True, products__category__is_active=True, products__brand__is_active=True))
    ).order_by('-offer_percentage', '-product_count')[:3]

    # Paginate results
    per_page = int(request.GET.get('per_page', 12))  # Allow customizable items per page
    paginator = Paginator(categories, per_page=per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get popular brands for potential filtering
    popular_brands = Brand.objects.filter(
        is_active=True, 
        categories__in=categories
    ).annotate(
        category_count=Count('categories', distinct=True, filter=Q(categories__is_active=True))
    ).order_by('-category_count')[:5]

    context = {
        'page_obj': page_obj,
        'title': 'Premium Supplements',
        'query': query,
        'sort_by': sort_by,
        'featured_categories': featured_categories,
        'popular_brands': popular_brands,
    }
    
    return render(request, 'product_app/user_category_list.html', context)


###############################################################################################################################################################################

@never_cache
def user_brand_list(request):
    # Fetch active brands with related data
    brands = Brand.objects.filter(is_active=True).prefetch_related('products', 'categories')

    # Annotate with product and category counts
    brands = brands.annotate(
        product_count=Count('products', filter=Q(products__is_active=True, products__category__is_active=True)),
        category_count=Count('categories', filter=Q(categories__is_active=True))
    )

    # Handle search query
    query = request.GET.get('q', '').strip()
    if query:
        logger.info(f"Search query: {query}")
        brands = brands.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(categories__name__icontains=query, categories__is_active=True)
        ).distinct()
        if not brands.exists():
            logger.warning(f"No brands found for query: {query}")

    # Handle sorting
    sort_by = request.GET.get('sort', '')
    sort_options = {
        'a_to_z': 'name',
        'z_to_a': '-name',
        'newest': '-created_at',
        'oldest': 'created_at',
        'popular': '-product_count',
        '': 'name'  # Default sort
    }
    sort_field = sort_options.get(sort_by, 'name')
    logger.info(f"Sorting by: {sort_by} ({sort_field})")
    brands = brands.order_by(sort_field)

    # Get featured brands (those with the most products)
    featured_brands = Brand.objects.filter(is_active=True).annotate(
        product_count=Count('products', filter=Q(products__is_active=True, products__category__is_active=True))
    ).order_by('-product_count')[:3]

    # Paginate results
    per_page = int(request.GET.get('per_page', 9))  
    paginator = Paginator(brands, per_page=per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Debug brand count
    logger.info(f"Total brands after filtering: {brands.count()}")

    context = {
        'page_obj': page_obj,
        'title': 'Our Brands',
        'query': query,
        'sort_by': sort_by,
        'featured_brands': featured_brands,
    }

    return render(request, 'product_app/user_brand_list.html', context)


@login_required
@user_passes_test(is_admin)
def admin_brand_list(request):
    status = request.GET.get('status', 'all')  # Default to 'all'
    search_query = request.GET.get('search', '')

    brands = Brand.objects.all()

    # Apply search filter
    if search_query:
        brands = brands.filter(name__icontains=search_query)

    # Apply status filter
    if status == 'active':
        brands = brands.filter(is_active=True)
    elif status == 'inactive':
        brands = brands.filter(is_active=False)
    # 'all' means no is_active filter

    # Annotate with product count and order
    brands = brands.annotate(products_count=Count('products')).order_by('name')

    # Pagination
    paginator = Paginator(brands, 10)
    page_number = request.GET.get('page', 1)
    brands_page = paginator.get_page(page_number)

    context = {
        'brands': brands_page,
        'status': status,
        'search_query': search_query,
        'total_brands': Brand.objects.count(),
        'active_brands': Brand.objects.filter(is_active=True).count(),
        'inactive_brands': Brand.objects.filter(is_active=False).count(),
        'brands_with_active_products': {brand.id: brand.products.filter(is_active=True) for brand in brands_page},
        'title': 'Brand Management',
    }
    return render(request, 'product_app/admin_brand_list.html', context)


@login_required
@user_passes_test(is_admin)
def admin_brand_create(request):
    if request.method == 'POST':
        form = BrandForm(request.POST, request.FILES)
        if form.is_valid():
            brand = form.save()
            messages.success(request, f'Brand "{brand.name}" has been created successfully.')
            return redirect('product_app:admin_brand_list')
    else:
        form = BrandForm()
    
    context = {
        'form': form,
        'title': 'Add New Brand',
    }
    
    return render(request, 'product_app/admin_brand_form.html', context)

@login_required
@user_passes_test(is_admin)
def admin_brand_edit(request, brand_id):
    brand = get_object_or_404(Brand, id=brand_id)

    if request.method == 'POST':
        form = BrandForm(request.POST, request.FILES, instance=brand)
        if form.is_valid():
            brand = form.save()
            messages.success(request, f'Brand "{brand.name}" has been updated successfully.')
            return redirect('product_app:admin_brand_list')
    else:
        form = BrandForm(instance=brand)

    context = {
        'form': form,
        'brand': brand,
        'title': f'Edit Brand: {brand.name}',
    }
    return render(request, 'product_app/admin_brand_form.html', context)

import logging
logger = logging.getLogger(__name__)
@login_required
@user_passes_test(is_admin)
def admin_brand_delete(request, brand_id):
    if request.method == 'POST' and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        brand = get_object_or_404(Brand, id=brand_id)
        brand_name = brand.name
        try:
            brand.delete()
            return JsonResponse({
                'success': True,
                'message': f'Brand "{brand_name}" has been deactivated.'
            })
        except Exception as e:
            logger.error(f"Error deactivating brand '{brand_name}': {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f"Failed to deactivate brand '{brand_name}'."
            }, status=500)
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def admin_brand_restore(request, brand_id):
    if request.method == 'POST' and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        brand = get_object_or_404(Brand, id=brand_id)
        brand.restore()
        return JsonResponse({'success': True, 'message': f'Brand "{brand.name}" has been restored.'})
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)


@login_required
@user_passes_test(is_admin)
def admin_brand_detail(request, brand_id):
    brand = get_object_or_404(Brand, id=brand_id)
    products = brand.products.filter(is_active=True)
    page = request.GET.get('page', 1)
    paginator = Paginator(products, 10)
    products_page = paginator.get_page(page)
    context = {
        'brand': brand,
        'products': products_page,
        'products_count': products.count(),
    }
    return render(request, 'product_app/admin_brand_detail.html', context)

@login_required
@user_passes_test(is_admin)
def admin_toggle_brand_status(request, brand_id):
    if request.method == 'POST' and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        brand = get_object_or_404(Brand, id=brand_id)
        brand.is_active = not brand.is_active
        brand.save(update_fields=['is_active', 'updated_at'])
        return JsonResponse({
            'success': True,
            'is_active': brand.is_active,
            'message': f'Brand "{brand.name}" is now {"active" if brand.is_active else "inactive"}.'
        })
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)


