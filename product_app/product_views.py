from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q, Avg, Min, Count, Sum
from django.views.decorators.cache import never_cache
from .forms import ReviewForm
from .models import Product, ProductImage, VariantImage, ProductVariant
from .forms import ProductForm, ProductVariantFormSet, ProductVariantForm
import logging
from django.views.decorators.csrf import csrf_exempt
from .models import Product, Category
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Review, Product
from .forms import ProductFilterForm 
from django.utils.text import slugify
import json
from django.db import transaction
from .models import Product, ProductImage, VariantImage, ProductVariant, Tag 
from cart_and_orders_app.models import Order, OrderItem

logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_superuser or user.is_staff


@login_required
@user_passes_test(is_admin)
@never_cache
def admin_product_list(request):
    products = Product.objects.all().prefetch_related('variants', 'tags')
    filter_form = ProductFilterForm(request.GET)

    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if data.get('search'):
            products = products.filter(
                Q(product_name__icontains=data['search']) |
                Q(description__icontains=data['search']) |
                Q(category__name__icontains=data['search'])
            )
        if data.get('category'):
            products = products.filter(category=data['category'])
        if data.get('brand'):
            products = products.filter(brand__icontains=data['brand'])
        if data.get('min_price') is not None:
            products = products.filter(variants__price__gte=data['min_price'])
        if data.get('max_price') is not None:
            products = products.filter(variants__price__lte=data['max_price'])
        if data.get('is_active'):
            products = products.filter(is_active=True)
        if data.get('tags'):
            products = products.filter(tags__in=data['tags'])
        if data.get('stock_status') == 'in_stock':
            products = products.filter(variants__stock__gt=0)
        elif data.get('stock_status') == 'out_of_stock':
            products = products.filter(variants__stock=0)

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    if sort_by == 'price_low':
        products = products.annotate(min_price=Min('variants__price')).order_by('min_price')
    elif sort_by == 'price_high':
        products = products.annotate(min_price=Min('variants__price')).order_by('-min_price')
    elif sort_by == 'a_to_z':
        products = products.order_by('product_name')
    elif sort_by == 'z_to_a':
        products = products.order_by('-product_name')
    elif sort_by == 'new_arrivals':
        products = products.order_by('-created_at')
    elif sort_by == 'rating':
        products = products.annotate(avg_rating=Avg('reviews__rating')).order_by('-avg_rating')
    elif sort_by == 'stock_low':
        products = products.annotate(total_stock=Sum('variants__stock')).order_by('total_stock')
    elif sort_by == 'stock_high':
        products = products.annotate(total_stock=Sum('variants__stock')).order_by('-total_stock')

    # Pagination
    paginator = Paginator(products, 10)
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)

    context = {
        'products': products,
        'filter_form': filter_form,
        'categories': Category.objects.all(),
        'brands': Product.objects.values_list('brand', flat=True).distinct(),
        'tags': Tag.objects.all(),
        'sort_by': sort_by,
    }
    return render(request, 'admin_product_list.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_add_product(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        variant_formset = ProductVariantFormSet(request.POST, request.FILES, prefix='variants')

        if form.is_valid():
            try:
                with transaction.atomic():
                    # Save product first
                    product = form.save(commit=False)
                    product.save()

                    # Save product images
                    images = request.FILES.getlist('images')
                    for i, image in enumerate(images):
                        ProductImage.objects.create(
                            product=product,
                            image=image,
                            is_primary=(i == 0)  # First image is primary
                        )

                    # Save tags (many-to-many field)
                    if form.cleaned_data.get('tags'):
                        product.tags.set(form.cleaned_data['tags'])

                    # Validate and save variants
                    if variant_formset.is_valid():
                        variants = variant_formset.save(commit=False)
                        for variant in variants:
                            variant.product = product
                            variant.save()

                            # Save variant image
                            for variant_form in variant_formset:
                                if variant_form.instance == variant:
                                    variant_image = variant_form.cleaned_data.get('variant_image')
                                    if variant_image:
                                        VariantImage.objects.create(
                                            variant=variant,
                                            image=variant_image,
                                            alt_text=f"{product.product_name} - {variant.flavor or ''} {variant.size_weight or ''}"
                                        )

                        messages.success(request, f"Product '{product.product_name}' created successfully.")
                        return redirect('product_app:admin_product_list')
                    else:
                        # Rollback transaction if variant validation fails
                        transaction.set_rollback(True)
                        for i, variant_form in enumerate(variant_formset):
                            for field, errors in variant_form.errors.items():
                                for error in errors:
                                    messages.error(request, f"Variant {i+1} - {field}: {error}")
            except Exception as e:
                logger.error(f"Error creating product: {str(e)}")
                messages.error(request, f"Error creating product: {str(e)}")
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = ProductForm()
        variant_formset = ProductVariantFormSet(prefix='variants')

    context = {
        'form': form,
        'variant_formset': variant_formset,
        'title': 'Add Product',
    }
    return render(request, 'admin_add_product.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_edit_variant(request, slug, variant_id):
    """
    Admin view to edit an existing product variant.
    """
    product = get_object_or_404(Product, slug=slug)
    variant = get_object_or_404(ProductVariant, id=variant_id, product=product)

    if request.method == 'POST':
        form = ProductVariantForm(request.POST, request.FILES, instance=variant)
        if form.is_valid():
            try:
                # Save the variant
                variant = form.save(commit=False)
                variant.product = product
                variant.save()

                # Handle variant image
                variant_image = form.cleaned_data.get('variant_image')
                if variant_image:
                    # Delete existing variant images if new one is uploaded
                    variant.variant_images.all().delete()
                    # Create new variant image
                    VariantImage.objects.create(
                        variant=variant,
                        image=variant_image,
                        alt_text=f"{product.product_name} - {variant.flavor or ''} {variant.size_weight or ''}"
                    )

                messages.success(request, f"Variant '{variant.flavor or 'N/A'} {variant.size_weight or ''}' updated successfully.")
                return redirect('product_app:admin_product_list')
            except Exception as e:
                logger.error(f"Error updating variant: {str(e)}")
                messages.error(request, f"Error updating variant: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = ProductVariantForm(instance=variant)

    context = {
        'form': form,
        'product': product,
        'variant': variant,
        'title': f'Edit Variant for {product.product_name}',
    }
    return render(request, 'admin_edit_variant.html', context)


@login_required
@user_passes_test(is_admin)
@never_cache
def admin_edit_product(request, slug):
    """
    Admin view to edit an existing product.
    """
    product = get_object_or_404(Product, slug=slug)
    
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        variant_formset = ProductVariantFormSet(request.POST, request.FILES, instance=product, prefix='variants')
        
        if form.is_valid() and variant_formset.is_valid():
            try:
                with transaction.atomic():
                    # Save product without committing to handle images
                    product = form.save()
                    
                    # Handle product images if new ones are uploaded
                    if 'images' in request.FILES:
                        images = form.cleaned_data.get('images', [])
                        if images:
                            # Delete old images
                            product.product_images.all().delete()
                            
                            # Add new images
                            if not isinstance(images, list):
                                images = [images]
                                
                            for i, image in enumerate(images):
                                ProductImage.objects.create(
                                    product=product,
                                    image=image,
                                    is_primary=(i == 0)  # First image is primary
                                )
                    
                    # Save tags
                    if 'tags' in form.cleaned_data:
                        product.tags.set(form.cleaned_data['tags'])
                    
                    # Save variants
                    variant_formset.save(commit=False)
                    
                    # Process each variant form
                    for variant_form in variant_formset:
                        if variant_form.is_valid():
                            if variant_form.cleaned_data.get('DELETE', False):
                                if variant_form.instance.pk:
                                    variant_form.instance.delete()
                            else:
                                variant = variant_form.save(commit=False)
                                variant.product = product
                                variant.save()
                                
                                # Handle variant image
                                variant_image = variant_form.cleaned_data.get('variant_image')
                                if variant_image:
                                    # Delete old image if exists
                                    variant.variant_images.all().delete()
                                    
                                    # Create new image
                                    VariantImage.objects.create(
                                        variant=variant,
                                        image=variant_image,
                                        alt_text=f"{product.product_name} - {variant.flavor or ''} {variant.size_weight or ''}"
                                    )
                    
                    messages.success(request, f"Product '{product.product_name}' updated successfully.")
                    return redirect('product_app:admin_product_list')
                    
            except Exception as e:
                logger.error(f"Error updating product: {str(e)}")
                messages.error(request, f"Error updating product: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
            
            for i, variant_form in enumerate(variant_formset):
                for field, errors in variant_form.errors.items():
                    for error in errors:
                        messages.error(request, f"Variant {i+1} - {field}: {error}")
    else:
        form = ProductForm(instance=product)
        variant_formset = ProductVariantFormSet(instance=product, prefix='variants')

    context = {
        'form': form,
        'variant_formset': variant_formset,
        'product': product,
        'title': 'Edit Product',
    }
    return render(request, 'admin_add_product.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_delete_variant(request, variant_id):
    """
    Admin view to delete a product variant.
    """
    variant = get_object_or_404(ProductVariant, id=variant_id)
    product = variant.product
    variant_name = f"{variant.flavor or 'N/A'} {variant.size_weight or ''}".strip()
    variant.delete()
    messages.success(request, f"Variant '{variant_name}' for product '{product.product_name}' has been deleted.")
    return redirect('product_app:admin_product_list')

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_delete_product(request, slug):
    """
    Admin view to delete a product (soft delete by setting is_active=False).
    """
    product = get_object_or_404(Product, slug=slug)
    product.is_active = False
    product.save()
    messages.success(request, f"Product '{product.product_name}' has been deactivated.")
    return redirect('product_app:admin_product_list')

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_permanent_delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product_name = product.product_name
    product.delete()
    messages.success(request, f"Product '{product_name}' has been permanently deleted.")
    return redirect('product_app:admin_product_list')

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_restore_product(request, slug):
    """
    Admin view to restore a deactivated product.
    """
    product = get_object_or_404(Product, slug=slug)
    product.is_active = True
    product.save()
    messages.success(request, f"Product '{product.product_name}' has been restored.")
    return redirect('product_app:admin_product_list')

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_product_detail(request, slug):
    """
    Admin view to see detailed product information.
    """
    product = get_object_or_404(Product, slug=slug)
    product.view_count += 1
    product.save()

    variants = product.variants.filter(is_active=True)
    images = product.product_images.all()
    reviews = product.reviews.all()  
    review_count = reviews.count()  
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0  
    is_out_of_stock = product.total_stock == 0
    related_products = Product.objects.filter(
        Q(category=product.category) | Q(tags__in=product.tags.all())
    ).exclude(id=product.id).distinct()[:4]

    context = {
        'product': product,
        'variants': variants,
        'images': images,
        'reviews': reviews,
        'review_count': review_count,
        'average_rating': average_rating,
        'is_out_of_stock': is_out_of_stock,
        'related_products': related_products,
    }
    return render(request, 'admin_product_detail.html', context)



###################################################### User Views ###########################################################


def user_home(request):
    """
    Display the user homepage with a hero banner, categories, and featured products.
    """
    # Fetch active products and categories
    products = Product.objects.filter(is_active=True, is_listed=True).prefetch_related('variants', 'product_images')
    categories = Category.objects.filter(is_active=True)

    # Filter form handling
    filter_form = ProductFilterForm(request.GET)
    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if data.get('search'):
            products = products.filter(
                Q(product_name__icontains=data['search']) |
                Q(description__icontains=data['search']) |
                Q(category__name__icontains=data['search'])
            )
        if data.get('category'):
            products = products.filter(category=data['category'])
        if data.get('brand'):
            products = products.filter(brand__icontains=data['brand'])
        if data.get('min_price') is not None:
            products = products.filter(variants__price__gte=data['min_price'])
        if data.get('max_price') is not None:
            products = products.filter(variants__price__lte=data['max_price'])

    # Sorting
    sort_by = request.GET.get('sort', 'new_arrivals')
    if sort_by == 'price_low':
        products = products.annotate(min_price=Min('variants__price')).order_by('min_price')
    elif sort_by == 'price_high':
        products = products.annotate(min_price=Min('variants__price')).order_by('-min_price')
    elif sort_by == 'a_to_z':
        products = products.order_by('product_name')
    elif sort_by == 'z_to_a':
        products = products.order_by('-product_name')
    elif sort_by == 'new_arrivals':
        products = products.order_by('-created_at')

    # Precompute primary images for each product
    product_list = []
    for product in products:
        primary_image = product.product_images.filter(is_primary=True).first()
        product_list.append({
            'product': product,
            'primary_image': primary_image,
        })

    context = {
        'products': product_list,  
        'categories': categories,
        'filter_form': filter_form,
        'sort_by': sort_by,
    }
    return render(request, 'user_home.html', context)

def user_product_list(request):
    products = Product.objects.filter(is_active=True).prefetch_related('variants', 'product_images')
    filter_form = ProductFilterForm(request.GET)

    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if data.get('search'):
            products = products.filter(
                Q(product_name__icontains=data['search']) |
                Q(description__icontains=data['search']) |
                Q(category__name__icontains=data['search'])
            )
        if data.get('category'):
            products = products.filter(category=data['category'])
        if data.get('brand'):
            products = products.filter(brand__icontains=data['brand'])
        if data.get('min_price') is not None:
            products = products.filter(variants__price__gte=data['min_price'])
        if data.get('max_price') is not None:
            products = products.filter(variants__price__lte=data['max_price'])
        if data.get('rating'):
            products = products.annotate(avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))).filter(avg_rating__gte=data['rating'])
        if data.get('stock_status') == 'in_stock':
            products = products.filter(variants__stock__gt=0)
        elif data.get('stock_status') == 'out_of_stock':
            products = products.filter(variants__stock=0)

    # Sorting
    sort_by = request.GET.get('sort', 'new_arrivals')
    if sort_by == 'price_low':
        products = products.annotate(min_price=Min('variants__price')).order_by('min_price')
    elif sort_by == 'price_high':
        products = products.annotate(min_price=Min('variants__price')).order_by('-min_price')
    elif sort_by == 'a_to_z':
        products = products.order_by('product_name')
    elif sort_by == 'z_to_a':
        products = products.order_by('-product_name')
    elif sort_by == 'new_arrivals':
        products = products.order_by('-created_at')
    elif sort_by == 'rating':
        products = products.annotate(avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))).order_by('-avg_rating')
    elif sort_by == 'popularity':
        products = products.annotate(view_count=Count('views')).order_by('-view_count')

    # Pagination
    paginator = Paginator(products, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Precompute data for each product card
    product_list = []
    for product in page_obj:
        primary_image = product.product_images.filter(is_primary=True).first()
        variant = product.variants.filter(is_active=True).first()
        product_list.append({
            'product': product,
            'primary_image': primary_image,
            'variant': variant,
            'avg_rating': product.average_rating,  # Use stored average_rating (updated on approval)
        })

    context = {
        'products': product_list,
        'page_obj': page_obj,
        'filter_form': filter_form,
        'categories': Category.objects.filter(is_active=True),
        'brands': Product.objects.values_list('brand', flat=True).distinct(),
        'tags': Tag.objects.all(),
        'sort_by': sort_by,
    }
    return render(request, 'user_product_list.html', context)

def user_product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    variants = product.variants.filter(is_active=True)
    images = product.product_images.all()

    reviews = product.reviews.all()
    review_count = reviews.count()
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0
    logger.debug(f"Average rating for product {product.product_name}: {average_rating} (based on {review_count} reviews)")

    is_out_of_stock = product.total_stock == 0
    related_products = Product.objects.filter(
        Q(category=product.category) | Q(tags__in=product.tags.all())
    ).exclude(id=product.id).distinct()[:4]

    context = {
        'product': product,
        'variants': variants,
        'images': images,
        'reviews': reviews,
        'review_count': review_count,
        'average_rating': average_rating,
        'is_out_of_stock': is_out_of_stock,
        'related_products': related_products,
    }
    return render(request, 'user_product_detail.html', context)


@login_required
@user_passes_test(is_admin)
@never_cache
def admin_approve_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)
    product = review.product
    if not review.is_approved:
        review.is_approved = True
        review.save()

        # Calculate and update average_rating based on approved reviews only
        approved_reviews = product.reviews.filter(is_approved=True)
        product.average_rating = approved_reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0
        product.save()

        messages.success(request, f"Review for '{product.product_name}' approved.")
    else:
        messages.info(request, "Review is already approved.")
    return redirect('product_app:admin_product_detail', slug=product.slug)

@csrf_exempt
@login_required
def add_review(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product = get_object_or_404(Product, id=data['product_id'], is_active=True)

            if product.has_user_reviewed(request.user):
                return JsonResponse({'success': False, 'message': 'You have already reviewed this product.'}, status=400)

            # Create a form instance with the data
            form = ReviewForm(data)
            if form.is_valid():
                is_verified_purchase = OrderItem.objects.filter(
                    order__user=request.user,
                    order__status='Delivered',
                    variant__product=product
                ).exists()

                review = form.save(commit=False)
                review.product = product
                review.user = request.user
                review.is_verified_purchase = is_verified_purchase
                review.is_approved = True
                review.save()

                # Update the product's average rating
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
                        'is_verified_purchase': review.is_verified_purchase,
                        'is_approved': review.is_approved
                    },
                    'average_rating': float(product.average_rating),
                    'review_count': review_count
                })
            else:
                return JsonResponse({'success': False, 'message': form.errors}, status=400)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Invalid JSON data'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)