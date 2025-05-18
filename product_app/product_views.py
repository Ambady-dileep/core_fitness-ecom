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
            products = products.filter(variants__original_price__gte=min_price)
        if max_price is not None:
            products = products.filter(variants__original_price__lte=max_price)

    status = request.GET.get('status', 'all')
    if status == 'active':
        products = products.filter(is_active=True)
    elif status == 'inactive':
        products = products.filter(is_active=False)

    # Sorting
    sort_by = filter_form.cleaned_data.get('sort') or request.GET.get('sort', '-created_at')
    sort_options = {
        'price_low': 'min_price',
        'price_high': '-max_price',
        'a_to_z': 'product_name',
        'z_to_a': '-product_name',
        'new_arrivals': '-created_at',
        '-created_at': '-created_at',
        'rating': '-average_rating',
        '-average_rating': '-average_rating',
        'stock_low': 'total_stock',
        'calculated_total_stock': 'total_stock',
    }

    if sort_by in ('price_low', 'price_high'):
        # Annotate min and max prices for sorting
        products = products.annotate(
            min_price=Min('variants__original_price'),
            max_price=Max('variants__original_price')
        ).order_by(sort_options.get(sort_by, '-created_at'))
    elif sort_by in ('stock_low', 'calculated_total_stock'):
        products = products.annotate(total_stock=Sum('variants__stock')).order_by(sort_options.get(sort_by, '-created_at'))
    else:
        products = products.order_by(sort_options.get(sort_by, '-created_at'))

    # Ensure distinct results to avoid duplicates from variant joins
    products = products.distinct()

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
                        logger.debug(f"Processing variant {i + 1}: variant_id={variant_id}, flavor={flavor}, size_weight={size_weight}, "
                                     f"original_price={original_price}, offer_percentage={offer_percentage}, stock={stock}, "
                                     f"images_count={len(images)}, primary_image={primary_image}, delete_image_ids={delete_image_ids}")

                        # Validate required fields
                        if not original_price or not stock:
                            logger.warning(f"Validation failed for variant {i + 1}: Missing original_price or stock")
                            return JsonResponse({
                                'success': False,
                                'message': f'Original price and stock are required for variant {i + 1}.'
                            }, status=400)

                        # Validate size_weight
                        if size_weight and len(size_weight) > 50:
                            logger.warning(f"Validation failed for variant {i + 1}: Size/Weight exceeds 50 characters")
                            return JsonResponse({
                                'success': False,
                                'message': f'Size/Weight for variant {i + 1} cannot exceed 50 characters.'
                            }, status=400)

                        # Create or update variant
                        if variant_id and variant_id.isdigit():
                            variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
                            logger.debug(f"Updating existing variant {variant.id}")
                            submitted_variant_ids.append(int(variant_id))
                        else:
                            variant = ProductVariant(product=product)
                            logger.debug(f"Creating new variant for product {product.id}")

                        variant.flavor = flavor
                        variant.size_weight = size_weight
                        variant.is_active = True

                        # Handle original_price
                        try:
                            original_price_float = float(original_price)
                            if original_price_float < 0:
                                logger.warning(f"Validation failed for variant {i + 1}: Negative original price")
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Original price for variant {i + 1} must be non-negative.'
                                }, status=400)
                            variant.original_price = original_price_float
                        except (ValueError, TypeError):
                            logger.warning(f"Validation failed for variant {i + 1}: Invalid original price")
                            return JsonResponse({
                                'success': False,
                                'message': f'Invalid original price for variant {i + 1}.'
                            }, status=400)

                        # Handle offer_percentage
                        if offer_percentage.strip():
                            try:
                                offer_percentage_float = float(offer_percentage)
                                if offer_percentage_float < 0 or offer_percentage_float > 100:
                                    logger.warning(f"Validation failed for variant {i + 1}: Offer percentage out of range")
                                    return JsonResponse({
                                        'success': False,
                                        'message': f'Offer percentage for variant {i + 1} must be between 0 and 100.'
                                    }, status=400)
                                variant.offer_percentage = offer_percentage_float
                            except (ValueError, TypeError):
                                variant.offer_percentage = 0.00
                                logger.debug(f"Set offer_percentage to 0.00 for variant {i + 1} due to invalid input")
                        else:
                            variant.offer_percentage = 0.00
                            logger.debug(f"Set offer_percentage to 0.00 for variant {i + 1} (empty input)")

                        # Handle stock
                        try:
                            stock_int = int(stock)
                            if stock_int < 0:
                                logger.warning(f"Validation failed for variant {i + 1}: Negative stock")
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Stock for variant {i + 1} must be non-negative.'
                                }, status=400)
                            variant.stock = stock_int
                        except (ValueError, TypeError):
                            logger.warning(f"Validation failed for variant {i + 1}: Invalid stock")
                            return JsonResponse({
                                'success': False,
                                'message': f'Invalid stock value for variant {i + 1}.'
                            }, status=400)

                        # Save the variant
                        variant.save()
                        logger.debug(f"Variant {i + 1} saved with ID {variant.id}")

                        # Add the variant ID to submitted_variant_ids (for new variants)
                        submitted_variant_ids.append(variant.id)

                        # Delete specified images
                        if delete_image_ids:
                            deleted_count = VariantImage.objects.filter(id__in=delete_image_ids, variant=variant).delete()[0]
                            logger.debug(f"Deleted {deleted_count} images for variant {variant.id}: {delete_image_ids}")

                        # Calculate total images after deletion
                        existing_images = variant.variant_images.count()
                        total_images = existing_images + len(images)
                        logger.debug(f"Variant {i + 1}: existing_images={existing_images}, new_images={len(images)}, total_images={total_images}")

                        # Validate image count
                        if total_images < 1:
                            logger.warning(f"Validation failed for variant {i + 1}: No images")
                            return JsonResponse({
                                'success': False,
                                'message': f'At least one image is required for variant {i + 1}.'
                            }, status=400)
                        if total_images > 3:
                            logger.warning(f"Validation failed for variant {i + 1}: Too many images")
                            return JsonResponse({
                                'success': False,
                                'message': f'Maximum 3 images allowed for variant {i + 1}.'
                            }, status=400)

                        # Validate image size and type
                        for image in images:
                            if image.size > 10 * 1024 * 1024:
                                logger.warning(f"Validation failed for variant {i + 1}: Image exceeds 10MB")
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Image for variant {i + 1} exceeds 10MB.'
                                }, status=400)
                            if not image.content_type.startswith('image/'):
                                logger.warning(f"Validation failed for variant {i + 1}: Invalid image type")
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Invalid image type for variant {i + 1}.'
                                }, status=400)

                        # Reset primary image status for existing images
                        VariantImage.objects.filter(variant=variant).update(is_primary=False)
                        logger.debug(f"Reset primary image status for variant {variant.id}")

                        # Add new images
                        for idx, image in enumerate(images):
                            is_primary = (primary_image == f'new_{idx}')
                            variant_image = VariantImage(
                                variant=variant,
                                image=image,
                                is_primary=is_primary,
                                alt_text=f"{product.product_name} - {variant.flavor or 'Standard'} {variant.size_weight or ''} image {idx + 1}",
                                image_type='primary' if is_primary else 'detail'
                            )
                            variant_image.save()
                            logger.debug(f"Added new image for variant {variant.id}, is_primary={is_primary}")

                        # Set primary image for existing images
                        if primary_image and primary_image.startswith('existing_'):
                            existing_image_id = primary_image.split('_')[1]
                            if existing_image_id.isdigit():
                                if not VariantImage.objects.filter(id=existing_image_id, variant=variant).exists():
                                    logger.warning(f"Validation failed for variant {i + 1}: Invalid primary image ID")
                                    return JsonResponse({
                                        'success': False,
                                        'message': f'Invalid primary image ID for variant {i + 1}: Image does not exist.'
                                    }, status=400)
                                VariantImage.objects.filter(id=existing_image_id, variant=variant).update(is_primary=True)
                                logger.debug(f"Set primary image for variant {variant.id} to existing image {existing_image_id}")
                            else:
                                logger.warning(f"Validation failed for variant {i + 1}: Invalid primary image ID format")
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Invalid primary image ID for variant {i + 1}.'
                                }, status=400)

                        # Ensure a primary image is set
                        primary_image_exists = variant.variant_images.filter(is_primary=True).exists()
                        if total_images > 0 and not primary_image_exists:
                            first_image = variant.variant_images.first()
                            if first_image:
                                first_image.is_primary = True
                                first_image.image_type = 'primary'
                                first_image.save()
                                logger.debug(f"Automatically set first image as primary for variant {variant.id}")
                            else:
                                logger.warning(f"Validation failed for variant {i + 1}: No primary image selected")
                                return JsonResponse({
                                    'success': False,
                                    'message': f'Please select a primary image for variant {i + 1}.'
                                }, status=400)

                    # Delete variants not included in the form
                    deleted_variants = product.variants.exclude(id__in=submitted_variant_ids).delete()[0]
                    logger.debug(f"Deleted {deleted_variants} variants not in submitted_variant_ids: {submitted_variant_ids}")

                    return JsonResponse({
                        'success': True,
                        'message': f"Product '{product.product_name}' updated successfully!"
                    })
            except ValidationError as e:
                logger.error(f"Validation error during product update: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'message': f"Validation error: {str(e)}"
                }, status=400)
            except Exception as e:
                logger.error(f"Error updating product: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'message': f"Error updating product: {str(e)}"
                }, status=500)
        else:
            errors = product_form.errors.as_json()
            logger.warning(f"Form validation failed: {errors}")
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
        'avg_rating': product.average_rating,  # Use stored value
        'approved_review_count': product.review_count,  # Use property
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
            review.save()  # This will trigger update_average_rating via the form's save method
            
            review_count = product.review_count  # Use the property
            
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
                'average_rating': float(product.average_rating),  # Use stored value
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
        review.product.update_average_rating()  # Ensure the average rating is updated
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
        product = review.product  # Store the product reference before deleting the review
        review.delete()
        product.update_average_rating()  # Update the average rating after deletion
        return JsonResponse({'success': True, 'message': 'Review deleted'})
    except Review.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Review not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

###################################################### User Views ###########################################################

def user_product_list(request):
    # Initialize filter form
    filter_form = ProductFilterForm(request.GET or None)

    user_wishlist_variants = []
    if request.user.is_authenticated:
        # Fetch the variant IDs that are in the user's wishlist
        user_wishlist_variants = Wishlist.objects.filter(user=request.user).values_list('variant_id', flat=True)
    
    # Start with all active products, prefetch related data
    products = Product.objects.filter(is_active=True,
    category__is_active=True,
    brand__is_active=True).select_related(
        'category', 'brand'
    ).prefetch_related(
        'variants',
        'variants__variant_images',
    )
    
    # Get all form data
    search_query = request.GET.get('search', '')
    category_id = request.GET.get('category', '')
    brand_id = request.GET.get('brand', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    sort_by = request.GET.get('sort', '')
    
    # Validate price inputs
    valid_min_price = None
    valid_max_price = None
    
    if min_price:
        try:
            valid_min_price = float(min_price)
            if valid_min_price < 0:
                valid_min_price = None
        except ValueError:
            valid_min_price = None
            
    if max_price:
        try:
            valid_max_price = float(max_price)
            if valid_max_price < 0:
                valid_max_price = None
        except ValueError:
            valid_max_price = None
    
    # Apply filters
    if search_query:
        products = products.filter(
            Q(product_name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(brand__name__icontains=search_query)
        )
    
    if category_id and category_id.isdigit():
        products = products.filter(category_id=category_id)
    
    if brand_id and brand_id.isdigit():
        products = products.filter(brand_id=brand_id)
    
    # Process products with their active variants
    product_data = []
    for product in products:
        # Get active variants with stock
        active_variants = [v for v in product.variants.all() if v.is_active]
        if not active_variants:
            continue
        
        # Calculate min and max prices across variants using best_price
        variant_prices = [v.best_price['price'] for v in active_variants]
        if not variant_prices:
            continue
            
        product_min_price = min(variant_prices)
        product_max_price = max(variant_prices)
        
        # Apply price range filter
        if valid_min_price is not None and product_max_price < valid_min_price:
            continue
        if valid_max_price is not None and product_min_price > valid_max_price:
            continue
            
        # Get primary variant for display
        primary_variant = product.primary_variant
        if not primary_variant or not primary_variant.is_active:
            # Fallback to first active variant
            primary_variant = next((v for v in active_variants), None)
            if not primary_variant:
                continue
                
        # Get primary image
        primary_image = primary_variant.primary_image
            
        # Calculate discount percentage
        discount_percentage = Decimal('0.00')
        if primary_variant.best_price['price'] < primary_variant.original_price:
            discount_percentage = ((primary_variant.original_price - primary_variant.best_price['price']) /primary_variant.original_price * 100).quantize(Decimal('0.01'))
        
        # Use stored review data
        review_count = product.review_count
        avg_rating = product.average_rating
        whole_stars = int(avg_rating)
        star_rating = {
            'whole_stars': whole_stars,
            'empty_stars': 5 - whole_stars
        }
        
        # Enhanced logging for debugging
        logger.debug(f"Product {product.product_name}: review_count={review_count}, avg_rating={avg_rating}, whole_stars={whole_stars}, empty_stars={star_rating['empty_stars']}")
        
        # Add product to filtered results
        product_data.append({
            'product': product,
            'variant': primary_variant,
            'primary_image': primary_image,
            'original_price': primary_variant.original_price,
            'best_price': primary_variant.best_price['price'],
            'min_price': product_min_price,  # For sorting
            'max_price': product_max_price,  # For sorting
            'has_offer': primary_variant.best_price['price'] < primary_variant.original_price,
            'offer_type': primary_variant.best_price['applied_offer_type'],
            'discount_percentage': discount_percentage,
            'total_stock': sum(v.stock for v in active_variants),
            'user_wishlist_variants': user_wishlist_variants,
            'average_rating': avg_rating,
            'review_count': review_count,
            'star_rating': star_rating,
        })
    
    # Apply sorting to the processed products
    if sort_by == 'price_low':
        product_data = sorted(product_data, key=lambda x: x['min_price'])
    elif sort_by == 'price_high':
        product_data = sorted(product_data, key=lambda x: x['max_price'], reverse=True)
    elif sort_by == 'a_to_z':
        product_data = sorted(product_data, key=lambda x: x['product'].product_name.lower())
    elif sort_by == 'z_to_a':
        product_data = sorted(product_data, key=lambda x: x['product'].product_name.lower(), reverse=True)
    else:
        # Default sorting by most recent
        product_data = sorted(product_data, key=lambda x: x['product'].created_at, reverse=True)
    
    # Pagination
    paginator = Paginator(product_data, 12)  # 12 products per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Calculate overall price range for filter options
    all_products = Product.objects.filter(is_active=True, category__is_active=True,
    brand__is_active=True)
    all_variants = ProductVariant.objects.filter(is_active=True, product__in=all_products)
    
    if all_variants.exists():
        price_range = {
            'min': 0,  # Start from zero
            'max': 9999  # Set a reasonable upper limit
        }
        
        # Try to get actual min/max from active products
        try:
            # Use aggregate for approximate price range
            min_original = all_variants.aggregate(Min('original_price'))['original_price__min'] or 0
            max_original = all_variants.aggregate(Max('original_price'))['original_price__max'] or 9999
            
            # Round for cleaner UI
            price_range['min'] = int(min_original)
            price_range['max'] = int(max_original * 1.1)  # Give some headroom
        except:
            pass  # Use default values if anything fails
    else:
        price_range = {'min': 0, 'max': 1000}
    
    context = {
        'filter_form': filter_form,
        'products': page_obj,  # Paginated product data
        'page_obj': page_obj,  # For pagination controls
        'sort_by': sort_by,
        'search_query': search_query,
        'price_range': price_range,
        'min_price': min_price,
        'max_price': max_price,
        'clear_filters': any([search_query, category_id, brand_id, min_price, max_price]),
        'debug': True
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

    # Review permissions
    can_review = request.user.is_authenticated
    has_reviewed = product.has_user_reviewed(request.user) if request.user.is_authenticated else False

    # Price and stock calculations
    min_price = product.min_price()
    max_price = product.max_price()
    total_stock = product.total_stock()

    # Related products
    related_products = Product.objects.filter(
        category=product.category,
        is_active=True,
        brand__is_active=True
    ).exclude(id=product.id).select_related('category', 'brand').prefetch_related('variants')[:4]

    # Wishlist status
    wishlist_variant_ids = set(Wishlist.objects.filter(user=request.user).values_list('variant_id', flat=True)) if request.user.is_authenticated else set()

    # Prepare variant data
    variant_data = []
    for variant in variants:
        best_price_info = variant.best_price
        best_price = best_price_info['price']
        has_offer = best_price < variant.original_price
        best_offer_percentage = Decimal('0.00')
        if has_offer:
            best_offer_percentage = ((variant.original_price - best_price) / variant.original_price * 100).quantize(Decimal('0.01'))

        variant_data.append({
            'variant': variant,
            'images': variant.variant_images.all(),
            'discounted_price': best_price,
            'best_price': best_price,
            'has_offer': has_offer,
            'best_offer_percentage': best_offer_percentage,
            'is_in_wishlist': variant.id in wishlist_variant_ids,
        })

    # Review data
    reviews = product.approved_reviews().order_by('-created_at')[:5]
    review_count = product.review_count  # Use property
    avg_rating = product.average_rating  # Use stored value

    # Related products data
    related_product_data = [
        {
            'product': rp,
            'best_price': rp.variants.first().best_price['price'] if rp.variants.exists() else 0,
            'primary_image': rp.primary_variant.primary_image if rp.primary_variant else None,
        } for rp in related_products
    ]

    context = {
        'product': product,
        'variants': variant_data,
        'min_price': min_price,
        'max_price': max_price,
        'total_stock': total_stock,
        'reviews': reviews,
        'review_count': review_count,
        'avg_rating': avg_rating,
        'can_review': can_review and not has_reviewed,
        'has_reviewed': has_reviewed,
        'related_products': related_product_data,
    }
    return render(request, 'product_app/user_product_detail.html', context)

@csrf_exempt
@login_required
@require_POST
def submit_review(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)

    # Check if user has already reviewed
    if product.has_user_reviewed(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'You have already reviewed this product'}, status=400)
        return redirect('product_app:user_product_detail', slug=slug)

    # Verify purchase
    is_verified_purchase = OrderItem.objects.filter(
        order__user=request.user,
        order__status='Delivered',
        variant__product=product
    ).exists()
    if not is_verified_purchase:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'You must purchase and receive this product to review it'}, status=400)
        return redirect('product_app:user_product_detail', slug=slug)

    # Handle AJAX and non-AJAX requests
    form = ReviewForm(request.POST)
    if form.is_valid():
        try:
            review = form.save(commit=False)
            review.product = product
            review.user = request.user
            review.is_verified_purchase = is_verified_purchase
            review.is_approved = True  # Auto-approve for verified purchases
            review.save()  # This will trigger update_average_rating via the form's save method

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'review': {
                        'id': review.id,
                        'title': review.title,
                        'rating': review.rating,
                        'comment': review.comment,
                        'username': review.user.username,
                        'created_at': review.created_at.strftime('%B %d, %Y'),
                        'is_verified_purchase': review.is_verified_purchase,
                        'is_approved': review.is_approved
                    },
                    'average_rating': float(product.average_rating),  # Use stored value
                    'review_count': product.review_count,  # Use property
                    'message': 'Thank you for your review!'
                })
            return redirect('product_app:user_product_detail', slug=slug)
        except Exception as e:
            logger.error(f"Error saving review: {str(e)}", exc_info=True)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            form.add_error(None, str(e))
    else:
        logger.debug(f"Form errors: {form.errors.as_json()}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            errors = {field: error[0] for field, error in form.errors.items()}
            return JsonResponse({'success': False, 'error': errors}, status=400)

    # Fallback for non-AJAX invalid form
    return redirect('product_app:user_product_detail', slug=slug)