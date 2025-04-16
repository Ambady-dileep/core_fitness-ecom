from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.views.decorators.cache import never_cache
from django.db.models import Q
from .models import Category, Product, Brand
from .forms import CategoryForm
from offer_and_coupon_app.models import CategoryOffer
from django.views.decorators.http import require_POST
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

    # Search filter
    if query:
        categories = categories.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )

    # Status filter
    if status == 'active':
        categories = categories.filter(is_active=True)
    elif status == 'inactive':
        categories = categories.filter(is_active=False)
    # 'all' means no is_active filter

    # Sorting
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

    # Pagination
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

    products = category.products.prefetch_related(
        'variants__variant_images'
    ).order_by('product_name')

    subcategories = category.subcategories.all()
    brands = category.brands.all()

    product_paginator = Paginator(products, 12)
    product_page = request.GET.get('product_page', 1)
    product_page_obj = product_paginator.get_page(product_page)

    context = {
        'category': category,
        'products': product_page_obj,
        'subcategories': subcategories,
        'brands': brands,
        'total_products': products.count(),
        'title': f'Category: {category.name}',
    }
    return render(request, 'product_app/admin_category_detail.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_add_category(request):
    if request.method == 'POST':
        form = CategoryForm(request.POST, request.FILES)
        if form.is_valid():
            category = form.save()
            success_url = reverse('product_app:admin_category_list')
            return redirect(f'{success_url}?success=added&name={category.name}')
        messages.error(request, "Please correct the errors below.")
    else:
        form = CategoryForm()

    context = {
        'form': form,
        'title': 'Add New Category',
        'action': 'Add',
        'category': None,
    }
    return render(request, 'product_app/admin_category_form.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_edit_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if request.method == 'POST':
        form = CategoryForm(request.POST, request.FILES, instance=category)
        if form.is_valid():
            if request.POST.get('image-clear') == 'on' and not request.FILES.get('image'):
                category.image = None
                category.save(update_fields=['image'])
            category = form.save()
            success_url = reverse('product_app:admin_category_list')
            return redirect(f'{success_url}?success=updated&name={category.name}')
        messages.error(request, "Please correct the errors below.")
    else:
        form = CategoryForm(instance=category)

    context = {
        'form': form,
        'category': category,
        'title': f'Edit Category: {category.name}',
        'action': 'Edit',
    }
    return render(request, 'product_app/admin_category_form.html', context)


import logging
logger = logging.getLogger(__name__)
@login_required
@user_passes_test(is_admin)
@require_POST
def admin_delete_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    category_name = category.name
    try:
        category.delete()
        logger.info(f"Admin {request.user.username} soft-deleted category '{category_name}'")
        return JsonResponse({
            'success': True,
            'message': f"Category '{category_name}' has been deactivated!"
        })
    except Exception as e:
        logger.error(f"Error deactivating category '{category_name}': {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f"Failed to deactivate category '{category_name}'."
        }, status=500)


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

@never_cache
def user_category_list(request):
    categories = Category.objects.filter(is_active=True)

    # Search filter
    query = request.GET.get('q', '').strip()
    if query:
        categories = categories.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )

    # Sorting
    sort_by = request.GET.get('sort', '')
    sort_options = {
        'a_to_z': 'name',
        'z_to_a': '-name',
        '': 'name'
    }
    categories = categories.order_by(sort_options.get(sort_by, 'name'))

    # Attach filtered subcategories
    for category in categories:
        category.filtered_subcategories = category.subcategories.filter(is_active=True)[:3]
        category.total_active_subcategories = category.subcategories.filter(is_active=True).count()

    # Fetch active offers
    now = timezone.now()
    category_offers = CategoryOffer.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    ).prefetch_related('categories')

    offers_by_category = {}
    for offer in category_offers:
        for category in offer.categories.all():
            offers_by_category.setdefault(category.id, []).append(offer)

    paginator = Paginator(categories, per_page=12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'title': 'Shop by Category',
        'query': query,
        'sort_by': sort_by,
        'offers_by_category': offers_by_category,
    }
    return render(request, 'product_app/user_category_list.html', context)


@never_cache
@login_required
def user_category_products(request, category_id):
    category = get_object_or_404(Category, id=category_id, is_active=True)
    products = category.products.filter(
        is_active=True, 
        is_listed=True
    ).prefetch_related('variants')
    context = {
        'category': category,
        'products': products,
        'title': f'Products in {category.name}',
    }
    return render(request, 'user_category_products.html', context)

@never_cache
def get_subcategories(request):
    parent_id = request.GET.get('parent_id')
    if not parent_id:
        return JsonResponse({'subcategories': []})
    subcategories = Category.objects.filter(
        parent_id=parent_id,
        is_active=True
    ).values('id', 'name')

    return JsonResponse({'subcategories': list(subcategories)})


################################################################### User Facing #############################################################################################

@never_cache
def user_category_list(request):
    try:
        # Start with all categories, ordered by 'name' to avoid UnorderedObjectListWarning
        categories = Category.objects.all().order_by('name')
        
        # Filter to parent categories only
        parent_categories = categories.filter(parent__isnull=True)
        
        # Search filter
        query = request.GET.get('q', '').strip()
        if query:
            parent_categories = parent_categories.filter(
                Q(name__icontains=query) | 
                Q(description__icontains=query)
            )

        # Active/Inactive filter
        is_active = request.GET.get('is_active', '')
        if is_active == 'true':
            parent_categories = parent_categories.filter(is_active=True)
        elif is_active == 'false':
            parent_categories = parent_categories.filter(is_active=False)

        # Sorting
        sort_by = request.GET.get('sort', '')
        sort_options = {
            'a_to_z': 'name',
            'z_to_a': '-name',
            '': 'name'  # Default sorting
        }
        parent_categories = parent_categories.order_by(sort_options.get(sort_by, 'name'))

        # Fetch active offers
        now = timezone.now()
        category_offers = CategoryOffer.objects.filter(
            is_active=True,
            valid_from__lte=now,
            valid_to__gte=now
        ).prefetch_related('categories')
        
        # Map categories to their active offers
        offers_by_category = {}
        for offer in category_offers:
            for category in offer.categories.all():
                offers_by_category.setdefault(category.id, []).append(offer)

        # Pagination
        paginator = Paginator(parent_categories, per_page=12)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        context = {
            'page_obj': page_obj,
            'title': 'Shop by Category',
            'query': query,
            'sort_by': sort_by,
            'is_active': is_active,
            'offers_by_category': offers_by_category,
        }
        return render(request, 'product_app/user_category_list.html', context)
    
    except Exception as e:
        logger.error(f"Error in user_category_list: {str(e)}", exc_info=True)
        # Return an error page or fallback context
        context = {
            'page_obj': Paginator(Category.objects.none(), per_page=12).get_page(1),
            'title': 'Shop by Category',
            'query': query,
            'sort_by': sort_by,
            'is_active': is_active,
            'offers_by_category': {},  # Ensure it's always a dict
            'error_message': 'An error occurred while loading categories. Please try again later.',
        }
        return render(request, 'product_app/user_category_list.html', context)

@never_cache
def user_category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    products = category.products.filter(is_active=True)
    subcategories = category.subcategories.filter(is_active=True)

    # Fetch active offers
    now = timezone.now()
    category_offers = CategoryOffer.objects.filter(
        categories=category,
        is_active=True,
        valid_from__lte=now,
        valid_to__gte=now
    )

    # Filters
    brand_filter = request.GET.getlist('brand')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    sort_by = request.GET.get('sort', 'newest')

    if brand_filter:
        products = products.filter(brand__name__in=brand_filter)

    if min_price:
        try:
            min_price = float(min_price)
            products = products.filter(variants__discounted_price__gte=min_price)
        except ValueError:
            pass

    if max_price:
        try:
            max_price = float(max_price)
            products = products.filter(variants__discounted_price__lte=max_price)
        except ValueError:
            pass

    sort_options = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'price_low': 'min_price',
        'price_high': '-min_price',
        'name_az': 'product_name',
        'name_za': '-product_name',
        'rating': '-average_rating'
    }
    products = products.order_by(sort_options.get(sort_by, '-created_at'))
    available_brands = products.values_list('brand__name', flat=True).distinct()

    paginator = Paginator(products, per_page=12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'category': category,
        'products': page_obj,
        'subcategories': subcategories,
        'available_brands': available_brands,
        'selected_brands': brand_filter,
        'min_price': min_price,
        'max_price': max_price,
        'sort_by': sort_by,
        'title': category.name,
        'category_offers': category_offers,
    }
    return render(request, 'product_app/user_category_detail.html', context)


@login_required
@user_passes_test(is_admin)
def admin_category_restore(request, category_id):
    if request.method == 'POST' and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        category = get_object_or_404(Category, id=category_id)
        category.restore()
        return JsonResponse({
            'success': True, 
            'message': f'Category "{category.name}" has been restored.'
        })
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)


###############################################################################################################################################################################

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
