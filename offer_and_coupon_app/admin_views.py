# offer_and_coupon_app/admin_views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, F
from django.views.decorators.http import require_http_methods
from django.contrib.admin.views.decorators import staff_member_required as admin_required
from django.http import JsonResponse
from .models import ProductOffer
from product_app.models import Product
from django.utils import timezone
from .forms import CouponForm, ProductOfferForm, CategoryOfferForm
from .models import Coupon, ProductOffer, CategoryOffer
from product_app.models import Category
import logging
from django.db import models

logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_staff or user.is_superuser

@login_required
@user_passes_test(admin_required)
def admin_coupon_list(request):
    coupons = Coupon.objects.all()

    # Search filter
    search_query = request.GET.get('search', '')
    if search_query:
        coupons = coupons.filter(Q(code__icontains=search_query) | Q(discount_percentage__icontains=search_query))

    # Status filter
    status = request.GET.get('status', '')
    if status == 'active':
        coupons = coupons.filter(
            is_active=True,
            valid_from__lte=timezone.now(),
            valid_to__gte=timezone.now()
        ).filter(
            models.ExpressionWrapper(
                Q(usage_limit=0) | Q(usage_count__lt=F('usage_limit')),
                output_field=models.BooleanField()
            )
        )
    elif status == 'inactive':
        coupons = coupons.filter(
            Q(is_active=False) |
            Q(valid_from__gt=timezone.now()) |
            Q(valid_to__lt=timezone.now()) |
            (Q(usage_limit__gt=0) & Q(usage_count__gte=F('usage_limit')))
        )

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = [
        'code', '-code', 'discount_percentage', '-discount_percentage',
        'minimum_order_amount', '-minimum_order_amount',
        'valid_from', '-valid_from', 'valid_to', '-valid_to',
        'usage_count', '-usage_count', 'created_at', '-created_at'
    ]
    if sort_by in allowed_sorts:
        coupons = coupons.order_by(sort_by)
    else:
        coupons = coupons.order_by('-created_at')

    # Pagination
    paginator = Paginator(coupons, 10)  # Increased to 10
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'status': status,
        'sort_by': sort_by,
        'title': 'Coupon List',
    }
    logger.info(f"Admin {request.user.username} accessed coupon list with search='{search_query}', status='{status}', sort='{sort_by}'")
    return render(request, 'offer_and_coupon_app/admin_coupon_list.html', context)


@login_required
@user_passes_test(admin_required)
@require_http_methods(["GET", "POST"])
def admin_coupon_add(request):
    if request.method == 'POST':
        form = CouponForm(request.POST)
        if form.is_valid():
            coupon = form.save()
            logger.info(f"Admin {request.user.username} added coupon '{coupon.code}'")
            messages.success(request, f"Coupon '{coupon.code}' added successfully!")
            return redirect('offer_and_coupon_app:admin_coupon_list')
        else:
            logger.warning(f"Admin {request.user.username} failed to add coupon: {form.errors}")
            messages.error(request, "Please correct the errors below.")
    else:
        form = CouponForm()
    context = {
        'form': form,
        'title': 'Add Coupon',
        'action': 'Add',
    }
    return render(request, 'offer_and_coupon_app/admin_coupon_form.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_coupon_edit(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    if request.method == 'POST':
        form = CouponForm(request.POST, instance=coupon)
        if form.is_valid():
            coupon = form.save()
            logger.info(f"Admin {request.user.username} updated coupon '{coupon.code}'")
            messages.success(request, f"Coupon '{coupon.code}' updated successfully!")
            return redirect('offer_and_coupon_app:admin_coupon_list')
        else:
            messages.error(request, "Please correct the errors below.")
            logger.warning(f"Admin {request.user.username} failed to update coupon {coupon_id}: {form.errors}")
    else:
        form = CouponForm(instance=coupon)
    context = {
        'form': form,
        'title': f'Edit Coupon: {coupon.code}',
        'action': 'Edit',
        'coupon': coupon,
    }
    return render(request, 'offer_and_coupon_app/admin_coupon_form.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_coupon_delete(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon_code = coupon.code
    coupon.delete()
    logger.info(f"Admin {request.user.username} deleted coupon '{coupon_code}'")
    messages.success(request, f"Coupon '{coupon_code}' deleted successfully!")
    return redirect('offer_and_coupon_app:admin_coupon_list')

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_coupon_toggle(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon.is_active = not coupon.is_active
    coupon.save()
    status = "activated" if coupon.is_active else "deactivated"
    logger.info(f"Admin {request.user.username} {status} coupon '{coupon.code}'")
    messages.success(request, f"Coupon '{coupon.code}' {status} successfully!")
    return redirect('offer_and_coupon_app:admin_coupon_list')

@login_required
@user_passes_test(is_admin)
def coupon_usage_report(request):
    coupons = Coupon.objects.annotate(
        total_users=models.Count('user_coupons', distinct=True),
        # Assuming Order has discount_amount; adjust if different
        total_discount=models.Sum('user_coupons__order__discount_amount')
    ).order_by('-usage_count')
    context = {
        'coupons': coupons,
        'title': 'Coupon Usage Report',
    }
    logger.info(f"Admin {request.user.username} accessed coupon usage report")
    return render(request, 'offer_and_coupon_app/admin_coupon_usage_report.html', context)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_product_offer_edit(request, offer_id):
    offer = get_object_or_404(ProductOffer, id=offer_id)
    if request.method == 'POST':
        form = ProductOfferForm(request.POST, instance=offer)
        if form.is_valid():
            offer = form.save()
            logger.info(f"Admin {request.user.username} updated product offer '{offer.name}'")
            messages.success(request, f"Product offer '{offer.name}' updated successfully!")
            return redirect('offer_and_coupon_app:admin_product_offer_list')
        else:
            messages.error(request, "Please correct the errors below.")
            logger.warning(f"Admin {request.user.username} failed to update product offer {offer_id}: {form.errors}")
    else:
        form = ProductOfferForm(instance=offer)
    context = {
        'form': form,
        'title': f'Edit Product Offer: {offer.name}',
        'action': 'Edit',
        'offer': offer,
    }
    return render(request, 'offer_and_coupon_app/admin_offer_form.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_product_offer_toggle(request, offer_id):
    offer = get_object_or_404(ProductOffer, id=offer_id)
    offer.is_active = not offer.is_active
    offer.save()
    status = "activated" if offer.is_active else "deactivated"
    logger.info(f"Admin {request.user.username} {status} product offer '{offer.name}'")
    return JsonResponse({
        'success': True,
        'message': f"Product offer '{offer.name}' {status} successfully!",
        'is_active': offer.is_active,
    })

@login_required
def admin_product_offer_form(request, offer_id=None):
    if not is_admin(request.user):
        messages.error(request, "Unauthorized access")
        return redirect('user_app:user_home')

    product_id = request.GET.get('product_id')
    product = get_object_or_404(Product, id=product_id) if product_id else None
    instance = get_object_or_404(ProductOffer, id=offer_id) if offer_id else None

    if request.method == 'POST':
        form = ProductOfferForm(request.POST, instance=instance)
        if form.is_valid():
            offer = form.save()
            if product and not offer.products.filter(id=product.id).exists():
                offer.products.add(product)
            messages.success(request, f"Offer {'updated' if instance else 'created'} successfully!")
            return redirect('product_app:admin_product_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ProductOfferForm(instance=instance)
        if product and not instance:
            form.initial['products'] = [product.id]

    context = {
        'form': form,
        'product': product,
        'offer': instance,
        'title': 'Edit Offer' if instance else 'Add Offer',
    }
    return render(request, 'offer_and_coupon_app/admin_product_offer_form.html', context)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_category_offer_edit(request, offer_id):
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    if request.method == 'POST':
        form = CategoryOfferForm(request.POST, instance=offer)
        if form.is_valid():
            offer = form.save()
            logger.info(f"Admin {request.user.username} updated category offer '{offer.name}'")
            messages.success(request, f"Category offer '{offer.name}' updated successfully!")
            return redirect('offer_and_coupon_app:admin_category_offer_list')
        else:
            messages.error(request, "Please correct the errors below.")
            logger.warning(f"Admin {request.user.username} failed to update category offer {offer_id}: {form.errors}")
    else:
        form = CategoryOfferForm(instance=offer)
    context = {
        'form': form,
        'title': f'Edit Category Offer: {offer.name}',
        'action': 'Edit',
        'offer': offer,
    }
    return render(request, 'offer_and_coupon_app/admin_offer_form.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_category_offer_delete(request, offer_id):
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    offer_name = offer.name
    offer.delete()
    logger.info(f"Admin {request.user.username} deleted category offer '{offer_name}'")
    messages.success(request, f"Category offer '{offer_name}' deleted successfully!")
    return redirect('offer_and_coupon_app:admin_category_offer_list')

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_category_offer_toggle(request, offer_id):
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    offer.is_active = not offer.is_active
    offer.save(update_fields=['is_active', 'updated_at'])
    status = "activated" if offer.is_active else "deactivated"
    logger.info(f"Admin {request.user.username} {status} category offer '{offer.name}'")
    return JsonResponse({
        'success': True,
        'is_active': offer.is_active,
        'message': f"Category offer '{offer.name}' {status} successfully!",
    })

@login_required
@user_passes_test(is_admin)
def admin_category_offers(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    offers = CategoryOffer.objects.filter(categories=category).order_by('-valid_to')

    # Pagination
    paginator = Paginator(offers, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'category': category,
        'page_obj': page_obj,
        'title': f"Offers for {category.name}",
        'now': timezone.now(),
    }
    logger.info(f"Admin {request.user.username} accessed offers for category '{category.name}'")
    return render(request, 'offer_and_coupon_app/admin_category_offers.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_add_offer(request):
    product_offer_form = ProductOfferForm()
    category_offer_form = CategoryOfferForm()

    if request.method == 'POST':
        offer_type = request.POST.get('offer_type')
        if offer_type == 'product':
            product_offer_form = ProductOfferForm(request.POST)
            if product_offer_form.is_valid():
                offer = product_offer_form.save()
                logger.info(f"Admin {request.user.username} added product offer '{offer.name}'")
                messages.success(request, f"Product offer '{offer.name}' created successfully!")
                return redirect('offer_and_coupon_app:admin_offer_list')
            else:
                messages.error(request, "Please correct the errors in the product offer form.")
                logger.warning(f"Admin {request.user.username} failed to add product offer: {product_offer_form.errors}")
        elif offer_type == 'category':
            category_offer_form = CategoryOfferForm(request.POST)
            if category_offer_form.is_valid():
                offer = category_offer_form.save()
                logger.info(f"Admin {request.user.username} added category offer '{offer.name}'")
                messages.success(request, f"Category offer '{offer.name}' created successfully!")
                return redirect('offer_and_coupon_app:admin_offer_list')
            else:
                messages.error(request, "Please correct the errors in the category offer form.")
                logger.warning(f"Admin {request.user.username} failed to add category offer: {category_offer_form.errors}")

    context = {
        'product_offer_form': product_offer_form,
        'category_offer_form': category_offer_form,
        'title': 'Add Offer',
        'action': 'Add',
    }
    return render(request, 'offer_and_coupon_app/admin_add_offer.html', context)

@login_required
@user_passes_test(is_admin)
def admin_offer_list(request):
    # Fetch product and category offers
    product_offers = ProductOffer.objects.all()
    category_offers = CategoryOffer.objects.all()

    # Apply search filter
    search_query = request.GET.get('search', '')
    if search_query:
        product_offers = product_offers.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )
        category_offers = category_offers.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query)
        )

    # Apply status filter
    status = request.GET.get('status', '')
    now = timezone.now()
    if status == 'active':
        product_offers = product_offers.filter(
            is_active=True,
            valid_from__lte=now,
            valid_to__gte=now
        )
        category_offers = category_offers.filter(
            is_active=True,
            valid_from__lte=now,
            valid_to__gte=now
        )
    elif status == 'inactive':
        product_offers = product_offers.filter(
            Q(is_active=False) |
            Q(valid_from__gt=now) |
            Q(valid_to__lt=now)
        )
        category_offers = category_offers.filter(
            Q(is_active=False) |
            Q(valid_from__gt=now) |
            Q(valid_to__lt=now)
        )

    # Apply sorting
    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = ['name', '-name', 'discount_value', '-discount_value', 
                     'valid_from', '-valid_from', 'valid_to', '-valid_to', 
                     'created_at', '-created_at']
    if sort_by in allowed_sorts:
        product_offers = product_offers.order_by(sort_by)
        category_offers = category_offers.order_by(sort_by)
    else:
        product_offers = product_offers.order_by('-created_at')
        category_offers = category_offers.order_by('-created_at')

    # Paginate results
    product_paginator = Paginator(product_offers, 10)
    category_paginator = Paginator(category_offers, 10)
    product_page_number = request.GET.get('product_page')
    category_page_number = request.GET.get('category_page')
    product_page_obj = product_paginator.get_page(product_page_number)
    category_page_obj = category_paginator.get_page(category_page_number)

    # Initialize forms for modals
    product_offer_form = ProductOfferForm()
    category_offer_form = CategoryOfferForm()

    context = {
        'product_page_obj': product_page_obj,
        'category_page_obj': category_page_obj,
        'product_offer_form': product_offer_form,
        'category_offer_form': category_offer_form,
        'title': 'Offer Management',
        'search_query': search_query,
        'status': status,
        'sort_by': sort_by,
        'now': timezone.now(),
    }
    logger.info(f"Admin {request.user.username} accessed offer list with search='{search_query}', status='{status}', sort='{sort_by}'")
    return render(request, 'offer_and_coupon_app/admin_offer_list.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_edit_offer(request, offer_id):
    offer = ProductOffer.objects.filter(id=offer_id).first()
    form_class = ProductOfferForm
    title = 'Edit Product Offer'
    if not offer:
        offer = CategoryOffer.objects.filter(id=offer_id).first()
        form_class = CategoryOfferForm
        title = 'Edit Category Offer'
    if not offer:
        logger.warning(f"Admin {request.user.username} attempted to edit non-existent offer ID {offer_id}")
        messages.error(request, 'Offer not found.')
        return redirect('offer_and_coupon_app:admin_offer_list')

    if request.method == 'POST':
        form = form_class(request.POST, instance=offer)
        if form.is_valid():
            offer = form.save()
            logger.info(f"Admin {request.user.username} updated {title.split()[1].lower()} offer '{offer.name}'")
            messages.success(request, f"{title.split()[1]} '{offer.name}' updated successfully!")
            return redirect('offer_and_coupon_app:admin_offer_list')
        else:
            messages.error(request, "Please correct the errors below.")
            logger.warning(f"Admin {request.user.username} failed to update {title.split()[1].lower()} offer {offer_id}: {form.errors}")
    else:
        form = form_class(instance=offer)

    context = {
        'form': form,
        'title': title,
        'action': 'Edit',
        'offer': offer,
    }
    return render(request, 'offer_and_coupon_app/admin_offer_form.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def admin_delete_offer(request, offer_id):
    try:
        offer = ProductOffer.objects.get(id=offer_id)
    except ProductOffer.DoesNotExist:
        try:
            offer = CategoryOffer.objects.get(id=offer_id)
        except CategoryOffer.DoesNotExist:
            logger.warning(f"Admin {request.user.username} attempted to delete non-existent offer ID {offer_id}")
            return JsonResponse({'success': False, 'message': 'Offer not found.'}, status=404)
    offer_name = offer.name
    offer_type = 'Product' if isinstance(offer, ProductOffer) else 'Category'
    offer.delete()
    logger.info(f"Admin {request.user.username} deleted {offer_type.lower()} offer '{offer_name}'")
    return JsonResponse({'success': True, 'message': f"{offer_type} offer '{offer_name}' deleted successfully!"})

@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_add_category_offer(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if request.method == 'POST':
        form = CategoryOfferForm(request.POST)
        if form.is_valid():
            offer = form.save(commit=False)
            offer.save()
            offer.categories.add(category)
            logger.info(f"Admin {request.user.username} added category offer '{offer.name}' for category '{category.name}'")
            messages.success(request, f"Category offer '{offer.name}' added successfully for category '{category.name}'!")
            return redirect('product_app:admin_category_detail', category_id=category.id)
        else:
            messages.error(request, "Please correct the errors below.")
            logger.warning(f"Admin {request.user.username} failed to add category offer for category {category_id}: {form.errors}")
    else:
        initial_data = {'categories': [category]}
        form = CategoryOfferForm(initial=initial_data)
    context = {
        'form': form,
        'title': f'Add Offer for {category.name}',
        'action': 'Add',
        'category': category,
    }
    return render(request, 'offer_and_coupon_app/admin_category_offer_add.html', context)



