from django.core.paginator import Paginator
from django.db.models import Q, Avg, Min, Sum, Max, F,DecimalField
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Product, ProductVariant, Category, Brand, VariantImage, Review
import logging
from .forms import ProductForm, ProductVariantFormSet, ProductFilterForm, ReviewForm
from datetime import timedelta
import json
from django.contrib.auth.decorators import login_required,user_passes_test
from product_app.models import Product, Category, Brand, ProductVariant
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_GET
from cart_and_orders_app.models import Wishlist, Order, OrderItem

logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_superuser or user.is_staff

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_product_list(request):
    products = Product.objects.all().select_related('category', 'brand').prefetch_related(
        'variants', 'variants__variant_images', 'reviews'
    )

    # Filtering
    filter_form = ProductFilterForm(request.GET)
    if filter_form.is_valid():
        search = filter_form.cleaned_data.get('search')
        category = filter_form.cleaned_data.get('category')
        brand = filter_form.cleaned_data.get('brand')
        min_price = filter_form.cleaned_data.get('min_price')
        max_price = filter_form.cleaned_data.get('max_price')

        if search:
            products = products.filter(
                Q(product_name__icontains=search) |
                Q(category__name__icontains=search) |
                Q(brand__name__icontains=search)
            )
        if category:
            products = products.filter(category=category)
        if brand:
            products = products.filter(brand=brand)
        if min_price is not None:
            products = products.filter(variants__best_price__price__gte=min_price)
        if max_price is not None:
            products = products.filter(variants__best_price__price__lte=max_price)

    status = request.GET.get('status', 'all')
    if status == 'active':
        products = products.filter(is_active=True)
    elif status == 'inactive':
        products = products.filter(is_active=False)

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    sort_options = {
        'new_arrivals': '-created_at',
        '-created_at': '-created_at',
        'rating': '-average_rating',
        '-average_rating': '-average_rating',
        'stock_low': 'total_stock',
        'calculated_total_stock': 'total_stock',
    }
    if sort_by in ('stock_low', 'calculated_total_stock'):
        products = products.annotate(total_stock=Sum('variants__stock')).order_by(sort_options.get(sort_by, '-created_at'))
    else:
        products = products.order_by(sort_options.get(sort_by, '-created_at'))

    # Pagination
    paginator = Paginator(products, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'filter_form': filter_form,
        'sort_by': sort_by,
        'status': status,
        'title': 'Product Management',
    }
    return render(request, 'product_app/admin_product_list.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_add_product(request):
    if request.method == 'POST':
        product_form = ProductForm(request.POST)
        variant_count = int(request.POST.get('variant_count', 0))

        if product_form.is_valid():
            try:
                with transaction.atomic():
                    # Save product
                    product = product_form.save(commit=False)
                    product.is_active = True
                    product.save()

                    # Process variants manually
                    for i in range(variant_count):
                        variant_id = request.POST.get(f'variant_id_{i}', '')
                        flavor = request.POST.get(f'flavor_{i}', '') or None
                        size_weight = request.POST.get(f'size_weight_{i}', '') or None
                        original_price = request.POST.get(f'original_price_{i}')
                        offer_percentage = request.POST.get(f'offer_percentage_{i}', '')
                        stock = request.POST.get(f'stock_{i}')
                        images = request.FILES.getlist(f'images_{i}')
                        primary_image = request.POST.get(f'primary_image_{i}')
                        delete_image_ids = request.POST.get(f'delete_image_ids_{i}', '').split(',')
                        delete_image_ids = [id for id in delete_image_ids if id.strip() and id.isdigit()]

                        # Validate required fields
                        if not original_price or not stock:
                            return JsonResponse({
                                'success': False,
                                'message': f'Original price and stock are required for variant {i + 1}.'
                            }, status=400)

                        # Validate size_weight
                        if size_weight and len(size_weight) > 50:
                            return JsonResponse({
                                'success': False,
                                'message': f'Size/Weight for variant {i + 1} cannot exceed 50 characters.'
                            }, status=400)

                        # Create or update variant
                        if variant_id and variant_id.isdigit():
                            variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
                        else:
                            variant = ProductVariant(product=product)

                        variant.flavor = flavor
                        variant.size_weight = size_weight
                        variant.is_active = True

                        # Handle original_price
                        try:
                            original_price_float = float(original_price)
                            if original_price_float < 0:
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Original price for variant {i + 1} must be non-negative.'
                                }, status=400)
                            variant.original_price = original_price_float
                        except (ValueError, TypeError):
                            return JsonResponse({
                                'success': False,
                                'message': f'Invalid original price for variant {i + 1}.'
                            }, status=400)

                        # Handle offer_percentage
                        if offer_percentage.strip():
                            try:
                                offer_percentage_float = float(offer_percentage)
                                if offer_percentage_float < 0 or offer_percentage_float > 100:
                                    return JsonResponse({
                                        'success': False,
                                        'message': f'Offer percentage for variant {i + 1} must be between 0 and 100.'
                                    }, status=400)
                                variant.offer_percentage = offer_percentage_float
                            except (ValueError, TypeError):
                                variant.offer_percentage = 0.00
                        else:
                            variant.offer_percentage = 0.00

                        # Handle stock
                        try:
                            stock_int = int(stock)
                            if stock_int < 0:
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Stock for variant {i + 1} must be non-negative.'
                                }, status=400)
                            variant.stock = stock_int
                        except (ValueError, TypeError):
                            return JsonResponse({
                                'success': False,
                                'message': f'Invalid stock value for variant {i + 1}.'
                            }, status=400)

                        variant.save()

                        # Delete specified images
                        if delete_image_ids:
                            VariantImage.objects.filter(id__in=delete_image_ids, variant=variant).delete()

                        # Calculate total images
                        existing_images = variant.variant_images.count()
                        total_images = existing_images + len(images)

                        # Validate minimum one image
                        if total_images < 1:
                            return JsonResponse({
                                'success': False,
                                'message': f'At least one image is required for variant {i + 1}.'
                            }, status=400)

                        # Validate maximum images
                        if total_images > 3:
                            return JsonResponse({
                                'success': False,
                                'message': f'Maximum 3 images allowed for variant {i + 1}.'
                            }, status=400)

                        # Validate image size and type
                        for image in images:
                            if image.size > 10 * 1024 * 1024:
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Image for variant {i + 1} exceeds 10MB.'
                                }, status=400)
                            if not image.content_type.startswith('image/'):
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Invalid image type for variant {i + 1}.'
                                }, status=400)

                        # Add new images
                        for idx, image in enumerate(images):
                            is_primary = (primary_image == f'new_{idx}')
                            VariantImage.objects.create(
                                variant=variant,
                                image=image,
                                is_primary=is_primary,
                                alt_text=f"{product.product_name} - {variant.flavor or 'Standard'} {variant.size_weight or ''} image {idx + 1}",
                                image_type='primary' if is_primary else 'detail'
                            )

                        # Set primary image for existing images
                        if primary_image and primary_image.startswith('existing_'):
                            existing_image_id = primary_image.split('_')[1]
                            if existing_image_id.isdigit():
                                VariantImage.objects.filter(variant=variant).update(is_primary=False)
                                VariantImage.objects.filter(id=existing_image_id, variant=variant).update(is_primary=True)
                            else:
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Invalid primary image ID for variant {i + 1}.'
                                }, status=400)

                        # Validate primary image
                        if total_images > 0 and not primary_image:
                            return JsonResponse({
                                'success': False,
                                'message': f'Please select a primary image for variant {i + 1}.'
                            }, status=400)

                    return JsonResponse({
                        'success': True,
                        'message': f"Product '{product.product_name}' added successfully!"
                    })
            except ValidationError as e:
                return JsonResponse({
                    'success': False,
                    'message': f"Validation error: {str(e)}"
                }, status=400)
            except Exception as e:
                logger.error(f"Error adding product: {e}")
                return JsonResponse({
                    'success': False,
                    'message': f"Error adding product: {str(e)}"
                }, status=500)
        else:
            errors = product_form.errors.as_json()
            return JsonResponse({
                'success': False,
                'message': 'Please correct the errors in the form.',
                'errors': json.loads(errors)
            }, status=400)
    else:
        product_form = ProductForm()
        variant_formset = ProductVariantFormSet()

    context = {
        'product_form': product_form,
        'variant_formset': variant_formset,
        'categories': Category.objects.filter(is_active=True),
        'brands': Brand.objects.filter(is_active=True),
        'flavor_choices': ProductVariant.FLAVOR_CHOICES,
        'title': 'Add New Product',
        'action': 'Add',
    }
    return render(request, 'product_app/admin_add_product.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_edit_product(request, slug):
    product = get_object_or_404(Product, slug=slug)
    if request.method == 'POST':
        product_form = ProductForm(request.POST, instance=product)
        variant_count = int(request.POST.get('variant_count', 0))

        if product_form.is_valid():
            try:
                with transaction.atomic():
                    # Save product
                    product = product_form.save(commit=False)
                    product.is_active = True
                    product.save()

                    submitted_variant_ids = []
                    for i in range(variant_count):
                        variant_id = request.POST.get(f'variant_id_{i}', '')
                        flavor = request.POST.get(f'flavor_{i}', '') or None
                        size_weight = request.POST.get(f'size_weight_{i}', '') or None
                        original_price = request.POST.get(f'original_price_{i}')
                        offer_percentage = request.POST.get(f'offer_percentage_{i}', '')
                        stock = request.POST.get(f'stock_{i}')
                        images = request.FILES.getlist(f'images_{i}')
                        primary_image = request.POST.get(f'primary_image_{i}')
                        delete_image_ids = request.POST.get(f'delete_image_ids_{i}', '').split(',')
                        delete_image_ids = [id for id in delete_image_ids if id.strip() and id.isdigit()]

                        # Log for debugging
                        logger.debug(f"Variant {i + 1}: delete_image_ids = {delete_image_ids}, primary_image = {primary_image}, new_images = {len(images)}")

                        # Validate required fields
                        if not original_price or not stock:
                            return JsonResponse({
                                'success': False,
                                'message': f'Original price and stock are required for variant {i + 1}.'
                            }, status=400)

                        # Validate size_weight
                        if size_weight and len(size_weight) > 50:
                            return JsonResponse({
                                'success': False,
                                'message': f'Size/Weight for variant {i + 1} cannot exceed 50 characters.'
                            }, status=400)

                        # Create or update variant
                        if variant_id and variant_id.isdigit():
                            variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
                            submitted_variant_ids.append(int(variant_id))
                        else:
                            variant = ProductVariant(product=product)

                        variant.flavor = flavor
                        variant.size_weight = size_weight
                        variant.is_active = True

                        # Handle original_price
                        try:
                            original_price_float = float(original_price)
                            if original_price_float < 0:
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Original price for variant {i + 1} must be non-negative.'
                                }, status=400)
                            variant.original_price = original_price_float
                        except (ValueError, TypeError):
                            return JsonResponse({
                                'success': False,
                                'message': f'Invalid original price for variant {i + 1}.'
                            }, status=400)

                        # Handle offer_percentage
                        if offer_percentage.strip():
                            try:
                                offer_percentage_float = float(offer_percentage)
                                if offer_percentage_float < 0 or offer_percentage_float > 100:
                                    return JsonResponse({
                                        'success': False,
                                        'message': f'Offer percentage for variant {i + 1} must be between 0 and 100.'
                                    }, status=400)
                                variant.offer_percentage = offer_percentage_float
                            except (ValueError, TypeError):
                                variant.offer_percentage = 0.00
                        else:
                            variant.offer_percentage = 0.00

                        # Handle stock
                        try:
                            stock_int = int(stock)
                            if stock_int < 0:
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Stock for variant {i + 1} must be non-negative.'
                                }, status=400)
                            variant.stock = stock_int
                        except (ValueError, TypeError):
                            return JsonResponse({
                                'success': False,
                                'message': f'Invalid stock value for variant {i + 1}.'
                            }, status=400)

                        variant.save()

                        # Delete specified images
                        if delete_image_ids:
                            VariantImage.objects.filter(id__in=delete_image_ids, variant=variant).delete()

                        # Calculate total images after deletion
                        existing_images = variant.variant_images.count()
                        total_images = existing_images + len(images)

                        # Validate image count
                        if total_images < 1:
                            return JsonResponse({
                                'success': False,
                                'message': f'At least one image is required for variant {i + 1}.'
                            }, status=400)
                        if total_images > 3:
                            return JsonResponse({
                                'success': False,
                                'message': f'Maximum 3 images allowed for variant {i + 1}.'
                            }, status=400)

                        # Validate image size and type
                        for image in images:
                            if image.size > 10 * 1024 * 1024:
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Image for variant {i + 1} exceeds 10MB.'
                                }, status=400)
                            if not image.content_type.startswith('image/'):
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Invalid image type for variant {i + 1}.'
                                }, status=400)

                        # Reset primary image status for existing images
                        VariantImage.objects.filter(variant=variant).update(is_primary=False)

                        # Add new images
                        for idx, image in enumerate(images):
                            is_primary = (primary_image == f'new_{idx}')
                            VariantImage.objects.create(
                                variant=variant,
                                image=image,
                                is_primary=is_primary,
                                alt_text=f"{product.product_name} - {variant.flavor or 'Standard'} {variant.size_weight or ''} image {idx + 1}",
                                image_type='primary' if is_primary else 'detail'
                            )

                        # Set primary image for existing images
                        if primary_image and primary_image.startswith('existing_'):
                            existing_image_id = primary_image.split('_')[1]
                            if existing_image_id.isdigit():
                                if not VariantImage.objects.filter(id=existing_image_id, variant=variant).exists():
                                    return JsonResponse({
                                        'success': False,
                                        'message': f'Invalid primary image ID for variant {i + 1}: Image does not exist.'
                                    }, status=400)
                                VariantImage.objects.filter(id=existing_image_id, variant=variant).update(is_primary=True)

                        # Ensure a primary image is set
                        primary_image_exists = variant.variant_images.filter(is_primary=True).exists()
                        if total_images > 0 and not primary_image_exists:
                            first_image = variant.variant_images.first()
                            if first_image:
                                first_image.is_primary = True
                                first_image.image_type = 'primary'
                                first_image.save()
                            else:
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Please select a primary image for variant {i + 1}.'
                                }, status=400)

                    # Delete variants not included in the form
                    product.variants.exclude(id__in=submitted_variant_ids).delete()

                    return JsonResponse({
                        'success': True,
                        'message': f"Product '{product.product_name}' updated successfully!"
                    })
            except ValidationError as e:
                return JsonResponse({
                    'success': False,
                    'message': f"Validation error: {str(e)}"
                }, status=400)
            except Exception as e:
                logger.error(f"Error updating product: {e}")
                return JsonResponse({
                    'success': False,
                    'message': f"Error updating product: {str(e)}"
                }, status=500)
        else:
            errors = product_form.errors.as_json()
            return JsonResponse({
                'success': False,
                'message': 'Please correct the errors in the form.',
                'errors': json.loads(errors)
            }, status=400)
    else:
        product_form = ProductForm(instance=product)
        variant_formset = ProductVariantFormSet(
            initial=[{
                'variant_id': variant.id,
                'flavor': variant.flavor,
                'size_weight': variant.size_weight,
                'original_price': variant.original_price,
                'offer_percentage': variant.offer_percentage,
                'stock': variant.stock,
            } for variant in product.variants.all()]
        )

    context = {
        'product_form': product_form,
        'variant_formset': variant_formset,
        'product': product,
        'categories': Category.objects.filter(is_active=True),
        'brands': Brand.objects.filter(is_active=True),
        'flavor_choices': ProductVariant.FLAVOR_CHOICES,
        'title': f'Edit Product: {product.product_name}',
        'action': 'Edit',
    }
    return render(request, 'product_app/admin_add_product.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related('category', 'brand').prefetch_related(
            'variants__variant_images', 'reviews__user'
        ),
        slug=slug
    )
    variants = product.variants.prefetch_related('variant_images')
    reviews = product.reviews.select_related('user').order_by('-created_at')
    
    # Add discount_percentage and compute min/max prices
    variants_with_discount = []
    prices = []
    for variant in variants:
        best_price = variant.best_price
        discount_percentage = Decimal('0.00')
        if variant.original_price > best_price['price'] and variant.original_price > 0:
            discount_percentage = (
                (variant.original_price - best_price['price']) / variant.original_price * 100
            ).quantize(Decimal('0.01'))
        variant.discount_percentage = discount_percentage
        variants_with_discount.append(variant)
        prices.append(best_price['price'])
    
    # Compute min_price and max_price
    min_price = min(prices, default=Decimal('0.00')).quantize(Decimal('0.01'))
    max_price = max(prices, default=Decimal('0.00')).quantize(Decimal('0.01'))
    
    stats = {
        'variants_count': variants.count(),
        'active_variants': variants.filter(is_active=True).count(),
        'total_stock': product.total_stock(),
        'avg_rating': product.average_rating,
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
        ).aggregate(
            total=Sum(F('quantity') * F('price'), output_field=DecimalField(max_digits=12, decimal_places=2))
        )['total'] or Decimal('0.00'),
        'total_orders': OrderItem.objects.filter(
            variant__product=product,
            order__created_at__gte=thirty_days_ago
        ).values('order').distinct().count(),
    }
    
    wishlist_count = Wishlist.objects.filter(variant__product=product).count()
    primary_variant = variants.filter(is_active=True).first()

    context = {
        'product': product,
        'variants': variants_with_discount,
        'reviews': reviews[:10],
        'wishlist_count': wishlist_count,
        'stats': stats,
        'sales_stats': sales_stats,
        'primary_variant': primary_variant,
        'min_price': min_price,
        'max_price': max_price,
        'title': f'Product: {product.product_name}',
    }
    return render(request, 'product_app/admin_product_detail.html', context)

@login_required
@user_passes_test(is_admin)
def admin_product_reviews(request, slug):
    product = get_object_or_404(Product, slug=slug)
    reviews = product.reviews.select_related('user').order_by('-created_at')
    
    paginator = Paginator(reviews, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    html = ''
    for review in page_obj:
        html += f'''
            <div class="card mb-2">
                <div class="card-body">
                    <div class="d-flex justify-content-between">
                        <div>
                            <h6>{review.user.username} <span class="text-muted">({review.age()})</span></h6>
                            <div class="text-warning">{review.star_rating()}</div>
                            <div>{review.rating} stars</div>
                        </div>
                        <div>
                            <span class="badge {'bg-success' if review.is_approved else 'bg-warning text-dark'}">
                                {'Approved' if review.is_approved else 'Pending'}
                            </span>
                            {'<span class="badge bg-info">Verified</span>' if review.is_verified_purchase else ''}
                        </div>
                    </div>
                    <div class="mt-2">
                        <strong>{review.title or 'Untitled'}</strong>
                        <p>{review.excerpt(200)}</p>
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-sm btn-outline-primary view-review" data-bs-toggle="modal" data-bs-target="#reviewModal"
                                data-id="{review.id}" data-user="{review.user.username}" data-rating="{review.rating}"
                                data-title="{review.title or ''}" data-comment="{review.comment}"
                                data-date="{review.age()}" data-verified="{'true' if review.is_verified_purchase else 'false'}"
                                data-approved="{'true' if review.is_approved else 'false'}"
                                data-stars="{review.star_rating()}">
                            <i class="fas fa-eye"></i> View
                        </button>
                        {'<button class="btn btn-sm btn-outline-success approve-review" data-id="' + str(review.id) + '"><i class="fas fa-check"></i> Approve</button>' if not review.is_approved else ''}
                        <button class="btn btn-sm btn-outline-danger delete-review" data-id="{review.id}">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
            </div>
        '''
    
    if page_obj.paginator.num_pages > 1:
        html += '<nav aria-label="Reviews pagination"><ul class="pagination justify-content-center mt-3">'
        if page_obj.has_previous():
            html += f'<li class="page-item"><a class="page-link" href="#" data-page="{page_obj.previous_page_number()}">Previous</a></li>'
        for num in page_obj.paginator.page_range:
            html += f'<li class="page-item {"active" if num == page_obj.number else ""}"><a class="page-link" href="#" data-page="{num}">{num}</a></li>'
        if page_obj.has_next():
            html += f'<li class="page-item"><a class="page-link" href="#" data-page="{page_obj.next_page_number()}">Next</a></li>'
        html += '</ul></nav>'
    
    if not reviews.exists():
        html = '<div class="text-center py-5"><i class="fas fa-comment-slash fa-3x text-muted mb-3"></i><p>No reviews yet for this product.</p></div>'
    
    return JsonResponse({
        'success': True,
        'html': html
    })

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_toggle_product_status(request, product_id):
    try:
        with transaction.atomic():
            product = get_object_or_404(Product, id=product_id)
            is_active = request.POST.get('is_active', 'false').lower() == 'true'
            
            if is_active:
                if not product.variants.exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Cannot activate product without variants.'
                    }, status=400)
                product.is_active = True
                if not product.variants.filter(is_active=True).exists():
                    first_variant = product.variants.first()
                    if first_variant:
                        first_variant.is_active = True
                        first_variant.save()
                    else:
                        return JsonResponse({
                            'success': False,
                            'message': 'No variants available to activate.'
                        }, status=400)
            else:
                product.is_active = False
                product.variants.update(is_active=False)
            
            product.save()
            return JsonResponse({
                'success': True,
                'is_active': product.is_active,
                'message': f'Product "{product.product_name}" has been {"activated" if is_active else "deactivated"}.'
            })
    except Exception as e:
        logger.error(f"Error toggling product {product_id}: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_toggle_variant_status(request, variant_id):
    try:
        variant = get_object_or_404(ProductVariant, id=variant_id)
        product = variant.product

        if not product.is_active and variant.is_active:
            return JsonResponse({
                'success': False,
                'message': "Cannot activate variant for an inactive product."
            }, status=400)

        new_status = not variant.is_active

        if not new_status and product.variants.filter(is_active=True).count() <= 1 and variant.is_active:
            return JsonResponse({
                'success': False,
                'message': "Cannot deactivate the last active variant."
            }, status=400)

        variant.is_active = new_status
        variant.save()

        if new_status and not product.is_active:
            product.is_active = True
            product.save()

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
    except Exception as e:
        logger.error(f"Error toggling variant {variant_id}: {e}")
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

@csrf_exempt
@login_required
@require_POST
def user_add_review(request):
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
    # Initialize filter form
    filter_form = ProductFilterForm(request.GET or None)
    
    # Fetch active products with related data
    products = Product.objects.filter(is_active=True).prefetch_related(
        'variants__images', 'category', 'brand', 'reviews'
    ).annotate(
        min_price=Min('variants__price'),
        max_price=Max('variants__price'),
        avg_rating=Avg('reviews__rating')
    )

    # Apply filters
    if filter_form.is_valid():
        search_query = filter_form.cleaned_data.get('search')
        category = filter_form.cleaned_data.get('category')
        brand = filter_form.cleaned_data.get('brand')
        min_price = filter_form.cleaned_data.get('min_price')
        max_price = filter_form.cleaned_data.get('max_price')

        if search_query:
            products = products.filter(
                Q(product_name__icontains=search_query) |
                Q(description__icontains=search_query)
            )
        if category:
            products = products.filter(category=category)
        if brand:
            products = products.filter(brand=brand)
        if min_price is not None:
            products = products.filter(variants__price__gte=min_price)
        if max_price is not None:
            products = products.filter(variants__price__lte=max_price)

    # Sorting
    sort_by = request.GET.get('sort', 'new_arrivals')
    if sort_by == 'price_low':
        products = products.order_by('min_price')
    elif sort_by == 'price_high':
        products = products.order_by('-max_price')
    elif sort_by == 'ratings':
        products = products.order_by('-avg_rating')
    elif sort_by == 'a_to_z':
        products = products.order_by('product_name')
    elif sort_by == 'z_to_a':
        products = products.order_by('-product_name')
    else:
        products = products.order_by('-created_at')

    # Prepare product data
    product_data = []
    for product in products:
        # Select primary variant or first active variant with stock
        variant = product.primary_variant or product.variants.filter(
            is_active=True, stock__gt=0
        ).order_by('price').first() or product.variants.filter(
            is_active=True
        ).order_by('price').first()

        if not variant:
            continue

        # Get primary image
        primary_image = variant.images.filter(is_primary=True).first()

        # Calculate prices
        discounted_price = variant.discounted_price if hasattr(variant, 'discounted_price') else variant.price
        best_price = discounted_price
        best_offer_percentage = 0
        has_offer = False

        # Check product offer
        product_offer = product.offers.filter(is_active=True).first()
        if product_offer:
            offer_price = discounted_price * (1 - product_offer.discount_percentage / 100)
            if offer_price < best_price:
                best_price = offer_price
                best_offer_percentage = product_offer.discount_percentage
                has_offer = True

        # Check category offer
        category_offer = product.category.offers.filter(is_active=True).first()
        if category_offer:
            offer_price = discounted_price * (1 - category_offer.discount_percentage / 100)
            if offer_price < best_price:
                best_price = offer_price
                best_offer_percentage = category_offer.discount_percentage
                has_offer = True

        product_data.append({
            'product': product,
            'variant': variant,
            'primary_image': primary_image,
            'discounted_price': discounted_price,
            'best_price': best_price,
            'has_offer': has_offer,
            'best_offer_percentage': best_offer_percentage,
            'avg_rating': product.avg_rating or 0,
            'review_count': product.reviews.filter(is_approved=True).count(),
            'variant_name': variant.name if hasattr(variant, 'name') else None,  # Optional: variant name
            'category_name': product.category.name if product.category else None,  # Optional: category name
            'total_stock': sum(v.stock for v in product.variants.filter(is_active=True))  # Optional: total stock
        })

    # Pagination
    paginator = Paginator(product_data, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'filter_form': filter_form,
        'products': page_obj,
        'page_obj': page_obj,
        'sort_by': sort_by,
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