from django.core.paginator import Paginator
from django.db.models import Q, Avg, Min, Sum, Max, F
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from product_app.models import Product, Category, ProductVariant
from django.core.exceptions import ValidationError
from cart_and_orders_app.models import Wishlist
from django.utils import timezone
from django.db.models import F, ExpressionWrapper, DecimalField
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from offer_and_coupon_app.models import ProductOffer, CategoryOffer
from django.core.paginator import Paginator
from .models import Product, ProductVariant, Category, Brand, VariantImage, Review
from django.db.models import Q
import logging
from datetime import timedelta
import json
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Min, Max, Q, F, ExpressionWrapper, DecimalField, Avg, Sum
from product_app.models import Product, Category, Brand, ProductVariant
from decimal import Decimal
from django.db import transaction
from django.views.decorators.http import require_POST, require_GET
from .forms import ReviewForm, ProductFilterForm
from cart_and_orders_app.models import Wishlist, Order, OrderItem

logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_superuser or user.is_staff

@login_required
def admin_product_list(request):
    if not is_admin(request.user):
        return redirect('user_app:user_home')

    products = Product.objects.all().select_related('category', 'brand').prefetch_related(
        'variants', 'variants__variant_images', 'reviews', 'product_offers'
    )

    now = timezone.now()
    products = products.annotate(
        calculated_total_stock=Sum('variants__stock'),
        avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))
    )

    # Filtering
    if request.GET.get('q'):
        query = request.GET.get('q')
        search_field = request.GET.get('search_field', 'all')
        if search_field == 'product_name':
            products = products.filter(product_name__icontains=query)
        elif search_field == 'category':
            products = products.filter(category__name__icontains=query)
        elif search_field == 'brand':
            products = products.filter(brand__name__icontains=query)
        else:
            products = products.filter(
                Q(product_name__icontains=query) |
                Q(category__name__icontains=query) |
                Q(brand__name__icontains=query)
            )

    if request.GET.get('brand'):
        products = products.filter(brand__id=request.GET.get('brand'))
    if request.GET.get('status') == 'active':
        products = products.filter(is_active=True)
    elif request.GET.get('status') == 'inactive':
        products = products.filter(is_active=False)

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    sort_options = {
        'new_arrivals': '-created_at',
        '-created_at': '-created_at',
        '-avg_rating': '-avg_rating',
        'rating': '-avg_rating',
        'calculated_total_stock': 'calculated_total_stock',
        'stock_low': 'calculated_total_stock'
    }
    products = products.order_by(sort_options.get(sort_by, '-created_at'))

    # Pagination
    paginator = Paginator(products, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'products': page_obj,
        'filter_form': {'brand': Brand.objects.filter(is_active=True)}, 
        'sort_by': sort_by,
    }
    return render(request, 'product_app/admin_product_list.html', context)

@login_required
def admin_product_form(request, slug=None):
    product = None
    if slug:
        product = get_object_or_404(Product, slug=slug)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                if product:
                    # Update existing product
                    product.product_name = request.POST.get('product_name')
                    product.category = Category.objects.get(id=request.POST.get('category'))
                    product.brand = Brand.objects.get(id=request.POST.get('brand')) if request.POST.get('brand') else None
                    product.description = request.POST.get('description')
                    product.country_of_manufacture = request.POST.get('country_of_manufacture')
                    product.save()
                else:
                    # Create new product
                    product_data = {
                        'product_name': request.POST.get('product_name'),
                        'category': Category.objects.get(id=request.POST.get('category')),
                        'brand': Brand.objects.get(id=request.POST.get('brand')) if request.POST.get('brand') else None,
                        'description': request.POST.get('description'),
                        'country_of_manufacture': request.POST.get('country_of_manufacture'),
                    }
                    product = Product(**product_data)
                    product.save()
                
                # Handle image deletions
                delete_image_ids = request.POST.getlist('delete_image_ids')
                if delete_image_ids:
                    VariantImage.objects.filter(id__in=delete_image_ids).delete()
                
                # Process variants
                variant_count = int(request.POST.get('variant_count', 0))
                for i in range(variant_count):
                    variant_id = request.POST.get(f'variant_id_{i}')
                    is_active = request.POST.get(f'is_active_{i}') == 'on'  # Checkbox returns 'on' when checked
                    if variant_id:
                        variant = ProductVariant.objects.get(id=variant_id)
                        variant.flavor = request.POST.get(f'flavor_{i}')
                        variant.size_weight = request.POST.get(f'size_weight_{i}')
                        variant.original_price = request.POST.get(f'original_price_{i}')
                        variant.discount_percentage = request.POST.get(f'discount_percentage_{i}', 0)
                        variant.stock = request.POST.get(f'stock_{i}')
                        variant.is_active = is_active
                        variant.save()
                    else:
                        variant_data = {
                            'product': product,
                            'flavor': request.POST.get(f'flavor_{i}'),
                            'size_weight': request.POST.get(f'size_weight_{i}'),
                            'original_price': request.POST.get(f'original_price_{i}'),
                            'discount_percentage': request.POST.get(f'discount_percentage_{i}', 0),
                            'stock': request.POST.get(f'stock_{i}'),
                            'is_active': is_active
                        }
                        variant = ProductVariant(**variant_data)
                        variant.save()
                    
                    # Process variant images
                    images = request.FILES.getlist(f'images_{i}')
                    primary_image = request.POST.get(f'primary_image_{i}')
                    new_image_ids = []
                    for idx, image in enumerate(images[:3]):
                        is_primary = (primary_image == f'new_{idx}')
                        variant_image = VariantImage.objects.create(
                            variant=variant,
                            image=image,
                            is_primary=is_primary,
                            alt_text=f"{product.product_name} - {variant.flavor or 'Standard'} {variant.size_weight or ''} image {idx + 1}"
                        )
                        new_image_ids.append(variant_image.id)

                    if variant_id and primary_image and primary_image.startswith('existing_'):
                        existing_image_id = primary_image.split('_')[1]
                        VariantImage.objects.filter(variant=variant).update(is_primary=False)
                        VariantImage.objects.filter(id=existing_image_id).update(is_primary=True)

                    if variant.variant_images.exists() and not variant.variant_images.filter(is_primary=True).exists():
                        first_image = variant.variant_images.first()
                        first_image.is_primary = True
                        first_image.save()
                
                # Ensure at least one active variant for active product
                if product.is_active and not product.variants.filter(is_active=True).exists():
                    if product.variants.exists():
                        first_variant = product.variants.first()
                        first_variant.is_active = True
                        first_variant.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f"Product {'updated' if slug else 'added'} successfully!",
                })
        
        except Exception as e:
            logger.error(f"Error {'updating' if slug else 'adding'} product: {e}")
            return JsonResponse({
                'success': False,
                'message': str(e),
            }, status=400)
    
    # GET request
    context = {
        'product': product,
        'categories': Category.objects.filter(is_active=True),
        'brands': Brand.objects.filter(is_active=True),
        'flavor_choices': ProductVariant.FLAVOR_CHOICES,
    }
    return render(request, 'product_app/admin_add_product.html', context)

@login_required
def admin_add_product(request):
    return admin_product_form(request)

@login_required
def admin_edit_product(request, slug):
    return admin_product_form(request, slug)

@login_required
def admin_product_detail(request, slug):
    product = get_object_or_404(Product.objects.select_related('category', 'brand'), slug=slug)
    variants = ProductVariant.objects.filter(product=product).prefetch_related('variant_images')
    reviews = product.reviews.all().select_related('user').order_by('-created_at')
    stats = {
        'variants_count': variants.count(),
        'active_variants': variants.filter(is_active=True).count(),
        'total_stock': variants.aggregate(total_stock=Sum('stock'))['total_stock'] or 0,
        'avg_rating': product.average_rating, 
        'review_count': reviews.count(),
        'approved_review_count': reviews.filter(is_approved=True).count(),
        'pending_review_count': reviews.filter(is_approved=False).count(),
    }
    thirty_days_ago = timezone.now() - timedelta(days=30)
    sales_stats = {
        'total_units_sold': OrderItem.objects.filter(
            variant__product=product,
            order__created_at__gte=thirty_days_ago
        ).aggregate(total=Sum('quantity'))['total'] or 0,
        'total_revenue': OrderItem.objects.filter(
            variant__product=product,
            order__created_at__gte=thirty_days_ago
        ).aggregate(total=Sum(F('quantity') * F('price')))['total'] or 0, 
        'total_orders': OrderItem.objects.filter(
            variant__product=product,
            order__created_at__gte=thirty_days_ago
        ).values('order').distinct().count(),
    }
    wishlist_count = Wishlist.objects.filter(variant__product=product).count()
    primary_variant = variants.filter(is_active=True).first()  
    
    context = {
        'product': product,
        'variants': variants,
        'reviews': reviews[:10],
        'wishlist_count': wishlist_count,
        'stats': stats,
        'sales_stats': sales_stats,
        'primary_variant': primary_variant,
    }
    
    return render(request, 'product_app/admin_product_detail.html', context)

@login_required
@require_POST
def admin_toggle_product_status(request, product_id):
    if not request.user.is_admin:  # Assuming is_admin is a custom check
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)

    try:
        with transaction.atomic():
            product = get_object_or_404(Product, id=product_id)
            is_active = request.POST.get('is_active') == 'true'

            if is_active:
                # Unblock: Ensure at least one variant exists
                if not product.variants.exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Cannot unblock product without variants.'
                    }, status=400)
                # Activate product and ensure at least one variant is active
                product.is_active = True
                if not product.variants.filter(is_active=True).exists():
                    first_variant = product.variants.first()
                    first_variant.is_active = True
                    first_variant.save()
            else:
                # Block: Set product and all variants to inactive
                product.is_active = False
                product.variants.update(is_active=False)

            product.save()
            return JsonResponse({
                'success': True,
                'message': f'Product {product.product_name} has been {"unblocked" if is_active else "blocked"}.'
            })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)
    
    
@login_required
def get_product_variants(request, product_id):
    try:
        if not is_admin(request.user):
            return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)

        product = get_object_or_404(Product, id=product_id)
        variants = ProductVariant.objects.filter(product_id=product_id).select_related('product')
        
        variants_data = []
        for variant in variants:
            try:
                image_url = variant.primary_image.image.url if variant.primary_image else None
            except Exception as e:
                image_url = None

            # Calculate discounted price
            discounted_price = variant.original_price * (1 - variant.discount_percentage / 100) if variant.discount_percentage else variant.original_price

            variant_data = {
                'id': variant.id,
                'flavor': variant.flavor or 'Standard',
                'size_weight': variant.size_weight or 'N/A',
                'original_price': float(variant.original_price),
                'discount_percentage': float(variant.discount_percentage),
                'discounted_price': float(discounted_price),
                'stock': variant.stock,
                'is_active': variant.is_active,
                'image_url': image_url
            }
            variants_data.append(variant_data)

        response_data = {
            'success': True,
            'variants': variants_data,
            'product_name': product.product_name,
            'product_is_active': product.is_active
        }
        return JsonResponse(response_data)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    

@login_required
@require_POST
def admin_toggle_variant_status(request, variant_id):
    try:
        if not is_admin(request.user):
            return JsonResponse({
                'success': False,
                'message': "Unauthorized access"
            }, status=403)

        variant = ProductVariant.objects.get(id=variant_id)
        product = variant.product

        if not product.is_active and variant.is_active:
            return JsonResponse({
                'success': False,
                'message': "Cannot activate variant for an inactive product"
            }, status=400)

        new_status = not variant.is_active

        # Prevent deactivating the last active variant
        if not new_status and product.variants.filter(is_active=True).count() <= 1 and variant.is_active:
            return JsonResponse({
                'success': False,
                'message': "Cannot deactivate the last active variant. Product must have at least one active variant."
            }, status=400)

        variant.is_active = new_status
        variant.save()

        # If activating a variant and product is inactive, activate the product
        if new_status and not product.is_active:
            product.is_active = True
            product.save()

        # If no variants are active, deactivate the product
        if not product.variants.filter(is_active=True).exists():
            product.is_active = False
            product.save()

        status = "activated" if variant.is_active else "deactivated"
        return JsonResponse({
            'success': True,
            'message': f"Variant {status} successfully!",
            'is_active': variant.is_active,
            'product_is_active': product.is_active
        })
    except ProductVariant.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': "Variant not found"
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)

@csrf_exempt
@login_required
@require_POST
def add_review(request):
    try:
        logger.debug(f"Raw request body: {request.body}")
        data = json.loads(request.body)
        logger.debug(f"Parsed data: {data}")
        product_id = data.get('product_id')
        if not product_id:
            return JsonResponse({'success': False, 'message': 'Product ID is required.'}, status=400)
        product = get_object_or_404(Product, id=product_id, is_active=True)
        if product.has_user_reviewed(request.user):
            return JsonResponse({'success': False, 'message': 'You have already reviewed this product.'}, status=400)

        is_verified_purchase = OrderItem.objects.filter(
            order__user=request.user,
            order__status='Delivered',
            variant__product=product
        ).exists()
        
        if not is_verified_purchase:
            return JsonResponse({'success': False, 'message': 'You must purchase and receive this product to review it.'}, status=400)

        form = ReviewForm(data)
        if form.is_valid():
            review = form.save(commit=False)
            review.product = product
            review.user = request.user
            review.is_verified_purchase = True 
            review.is_approved = True 
            review.save()
            
            product.update_average_rating()
            reviews = product.reviews.filter(is_approved=True)
            review_count = reviews.count()
            
            return JsonResponse({
                'success': True,
                'review': {
                    'id': review.id,
                    'title': review.title,
                    'rating': review.rating,
                    'comment': review.comment,
                    'username': review.user.username,
                    'created_at': review.created_at.strftime('%B %d, %Y'),
                    'is_verified_purchase': True,
                    'is_approved': True
                },
                'average_rating': float(product.average_rating),
                'review_count': review_count,
                'message': 'Thank you for your review!'
            })
        else:
            logger.debug(f"Form errors: {form.errors.as_json()}")
            return JsonResponse({'success': False, 'message': form.errors.as_json()}, status=400)
    
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        return JsonResponse({'success': False, 'message': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f"Error adding review: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
@login_required
@require_POST
def approve_review(request, review_id):
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    try:
        review = Review.objects.get(id=review_id)
        review.is_approved = True
        review.save()
        review.product.update_average_rating()
        return JsonResponse({'success': True, 'message': 'Review approved'})
    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Review not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@require_POST
def delete_review(request, review_id):
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    try:
        review = Review.objects.get(id=review_id)
        review.delete()
        review.product.update_average_rating()
        return JsonResponse({'success': True, 'message': 'Review deleted'})
    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Review not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@require_GET
def autocomplete(request):
    term = request.GET.get('term', '')
    if not term or len(term) < 2:
        return JsonResponse([], safe=False)
    suggestions = Product.objects.filter(
        is_active=True,
        variants__is_active=True
    ).filter(
        Q(product_name__icontains=term) |
        Q(brand__icontains=term) |
        Q(category__name__icontains=term)
    ).values('product_name', 'brand', 'category__name', 'slug').distinct()[:10]
    
    results = [{
        'label': f"{item['product_name']} ({item['brand']} - {item['category__name']})",
        'value': item['product_name'],
        'url': f"/products/{item['slug']}/"  
    } for item in suggestions]
    return JsonResponse(results, safe=False)

###################################################### User Views ###########################################################

def user_product_list(request):
    products = Product.objects.filter(
        is_active=True,
        variants__is_active=True,
        category__is_active=True,  
        brand__is_active=True 
    ).select_related('category', 'brand').prefetch_related(
        'variants', 'variants__variant_images', 'reviews'
    ).distinct()  
    products = products.annotate(
        min_price=Min(
            ExpressionWrapper(
                F('variants__original_price') * (1 - F('variants__discount_percentage') / 100),
                output_field=DecimalField(max_digits=10, decimal_places=0)
            )
        ),
        max_price=Max(
            ExpressionWrapper(
                F('variants__original_price') * (1 - F('variants__discount_percentage') / 100),
                output_field=DecimalField(max_digits=10, decimal_places=0)
            )
        ),
        avg_rating=Avg('reviews__rating')
    )

    # Filtering
    search_query = request.GET.get('search', '')
    if search_query:
        products = products.filter(
            Q(product_name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query) |
            Q(brand__name__icontains=search_query)
        )

    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(category__id=category_id)

    brand_id = request.GET.get('brand')
    if brand_id:
        products = products.filter(brand__id=brand_id)

    min_price = request.GET.get('min_price')
    if min_price:
        products = products.filter(min_price__gte=min_price)

    max_price = request.GET.get('max_price')
    if max_price:
        products = products.filter(max_price__lte=max_price)

    # Sorting
    sort_by = request.GET.get('sort', 'new_arrivals')
    sort_options = {
        'price_low': 'min_price',
        'price_high': '-max_price',
        'ratings': '-avg_rating',
        'new_arrivals': '-created_at',
        'a_to_z': 'product_name',
        'z_to_a': '-product_name',
        'best_sellers': '-variants__stock' 
    }
    products = products.order_by(sort_options.get(sort_by, '-created_at'))

    product_data = []
    for product in products:
        primary_variant = product.primary_variant
        if primary_variant:
            primary_image = None
            if primary_variant.variant_images.filter(is_primary=True).exists():
                primary_image = primary_variant.variant_images.filter(is_primary=True).first()
            
            product_data.append({
                'product': product,
                'variant': primary_variant,
                'primary_image': primary_image,
                'discounted_price': int(primary_variant.discounted_price()),
                'best_price': int(primary_variant.best_price['price']),
                'has_offer': primary_variant.has_offer,
                'best_offer_percentage': primary_variant.best_offer_percentage,
                'avg_rating': product.average_rating,
                'review_count': product.reviews.filter(is_approved=True).count()
            })

    # Pagination
    paginator = Paginator(product_data, 12) 
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Additional context for filters
    max_price_range = products.aggregate(Max('max_price'))['max_price__max'] or 10000

    # Create filter form
    filter_form = ProductFilterForm(request.GET)
    filter_form.fields['category'].queryset = Category.objects.filter(is_active=True)
    filter_form.fields['brand'].queryset = Brand.objects.filter(is_active=True) 

    context = {
        'products': page_obj,
        'filter_form': filter_form,
        'categories': Category.objects.filter(is_active=True),
        'brands': Brand.objects.filter(is_active=True), 
        'sort_by': sort_by,
        'search_query': search_query,
        'max_price': max_price_range,
        'selected_category': category_id,
        'selected_brand': brand_id,
        'page_obj': page_obj,
    }
    return render(request, 'product_app/user_product_list.html', context)


def user_product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related('category', 'brand')
        .prefetch_related('variants', 'variants__variant_images', 'reviews'),
        slug=slug,
        is_active=True,
        category__is_active=True,  
        brand__is_active=True
    )
    
    variants = product.variants.filter(is_active=True).prefetch_related('variant_images')
    reviews = product.reviews.filter(is_approved=True).select_related('user').order_by('-created_at')
    
    can_review = False
    has_reviewed = False
    if request.user.is_authenticated:
        can_review = OrderItem.objects.filter(
            order__user=request.user,
            order__status='Delivered',
            variant__product=product
        ).exists()
        has_reviewed = product.has_user_reviewed(request.user)
    
    min_price = product.min_price()
    max_price = product.max_price()
    total_stock = product.total_stock() 
    related_products = Product.objects.filter(
        category=product.category,
        is_active=True,
        brand__is_active=True
    ).exclude(id=product.id).select_related('category', 'brand').prefetch_related('variants')[:4]
    
    wishlist_variant_ids = set(Wishlist.objects.filter(user=request.user).values_list('variant_id', flat=True)) if request.user.is_authenticated else set()
    variant_data = [
        {
            'variant': variant,
            'images': variant.variant_images.all(),
            'discounted_price': variant.discounted_price(),
            'best_price': variant.best_price['price'], 
            'has_offer': variant.has_offer,
            'best_offer_percentage': variant.best_offer_percentage,
            'is_in_wishlist': variant.id in wishlist_variant_ids,
        } for variant in variants
    ]
    
    # Preprocess related products to include best_price
    related_product_data = [
        {
            'product': rp,
            'best_price': rp.variants.first().best_price['price'] if rp.variants.exists() else 0,
        } for rp in related_products
    ]
    
    context = {
        'product': product,
        'variants': variant_data,
        'min_price': min_price,
        'max_price': max_price,
        'total_stock': total_stock,
        'reviews': reviews[:5],
        'review_count': reviews.count(),
        'avg_rating': product.average_rating,
        'can_review': can_review and not has_reviewed,
        'has_reviewed': has_reviewed,
        'related_products': related_products,  
    }
    return render(request, 'product_app/user_product_detail.html', context)

@require_GET
def get_variant_images(request, variant_id):
    try:
        variant = get_object_or_404(ProductVariant, id=variant_id, is_active=True)
        images = variant.variant_images.all()
        image_data = [{'url': img.image.url, 'alt': img.alt_text} for img in images]
        return JsonResponse({
            'success': True,
            'images': image_data,
            'variant_name': f"{variant.product.product_name} - {variant.flavor or 'Standard'}"
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)