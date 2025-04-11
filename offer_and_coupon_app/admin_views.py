from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from .forms import CouponForm
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import models
from django.db.models import Q,F
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from .models import ProductOffer, CategoryOffer
from django.views.decorators.http import require_http_methods
from product_app.models import Category
from user_app.admin_views import is_admin
import logging
from .forms import ProductOfferForm, CategoryOfferForm
from django.http import JsonResponse
from .models import Coupon
from django.utils import timezone

def admin_required(user):
    return user.is_staff or user.is_superuser

@user_passes_test(admin_required)
def admin_coupon_list(request):
    # Base queryset
    coupons = Coupon.objects.all()

    # Search filter
    search_query = request.GET.get('search', '')
    if search_query:
        coupons = coupons.filter(code__icontains=search_query)

    # Status filter
    status = request.GET.get('status', '')
    if status == 'active':
        coupons = coupons.filter(
            Q(is_active=True) &
            Q(valid_from__lte=timezone.now()) &
            Q(valid_to__gte=timezone.now()) &
            (Q(usage_limit=0) | Q(usage_count__lt=F('usage_limit')))
        )
    elif status == 'inactive':
        coupons = coupons.filter(
            Q(is_active=False) |
            Q(valid_from__gt=timezone.now()) |
            Q(valid_to__lt=timezone.now()) |
            Q(usage_limit__gt=0) & Q(usage_count__gte=F('usage_limit'))
        )

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = ['code', '-code', 'discount_amount', '-discount_amount', 
                     'minimum_order_amount', '-minimum_order_amount', 
                     'valid_from', '-valid_from', 'valid_to', '-valid_to', 
                     'usage_count', '-usage_count']
    if sort_by in allowed_sorts:
        coupons = coupons.order_by(sort_by)
    else:
        coupons = coupons.order_by('-created_at')

    # Pagination
    paginator = Paginator(coupons, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin_coupon_list.html', {'page_obj': page_obj})

@user_passes_test(admin_required)
def admin_coupon_add(request):
    if request.method == 'POST':
        form = CouponForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Coupon added successfully!")
            return redirect('offer_and_coupon_app:admin_coupon_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CouponForm()
    return render(request, 'offer_and_coupon_app/admin_coupon_form.html', {'form': form, 'action': 'Add'})

@user_passes_test(admin_required)
def admin_coupon_edit(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    if request.method == 'POST':
        form = CouponForm(request.POST, instance=coupon)
        if form.is_valid():
            form.save()
            messages.success(request, "Coupon updated successfully!")
            return redirect('offer_and_coupon_app:admin_coupon_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CouponForm(instance=coupon)
    return render(request, 'offer_and_coupon_app/admin_coupon_form.html', {'form': form, 'action': 'Edit', 'coupon': coupon})


@user_passes_test(admin_required)
def admin_coupon_delete(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    if request.method == 'POST':
        coupon.delete()
        messages.success(request, f"Coupon '{coupon.code}' deleted successfully!")
        return redirect('offer_and_coupon_app:admin_coupon_list')
    return redirect('offer_and_coupon_app:admin_coupon_list')

@user_passes_test(admin_required)
def coupon_usage_report(request):
    coupons = Coupon.objects.annotate(
        total_users=models.Count('user_usages', distinct=True),
        total_discount=models.Sum('user_usages__order__discount_amount')
    ).order_by('-usage_count')
    return render(request, 'admin_coupon_usage_report.html', {'coupons': coupons})


@login_required
def admin_product_offer_add(request):
    if request.method == 'POST':
        form = ProductOfferForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Product offer added successfully!")
            return redirect('offer_and_coupon_app:admin_product_offer_list')
    else:
        form = ProductOfferForm()
    return render(request, 'offer_and_coupon_app/admin_offer_form.html', {'form': form, 'title': 'Add Product Offer'})

@login_required
def admin_product_offer_edit(request, offer_id):
    try:
        offer = ProductOffer.objects.get(id=offer_id)
    except ProductOffer.DoesNotExist:
        messages.error(request, 'Product offer not found.')
        return redirect('offer_and_coupon_app:admin_product_offer_list')

    if request.method == 'POST':
        form = ProductOfferForm(request.POST, instance=offer)
        if form.is_valid():
            form.save()
            messages.success(request, f'Product Offer "{offer.name}" updated successfully!')
            return redirect('offer_and_coupon_app:admin_product_offer_list')
    else:
        form = ProductOfferForm(instance=offer)

    return render(request, 'offer_and_coupon_app/admin_offer_form.html', {
        'form': form,
        'title': 'Edit Product Offer',
        'offer': offer  
    })

@login_required
def admin_product_offer_toggle(request, offer_id):
    offer = get_object_or_404(ProductOffer, id=offer_id)
    offer.is_active = not offer.is_active
    offer.save()
    return JsonResponse({'success': True, 'message': f'Offer {"activated" if offer.is_active else "deactivated"} successfully!'})

@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_category_offer_add(request):
    if request.method == 'POST':
        form = CategoryOfferForm(request.POST)
        if form.is_valid():
            category_offer = form.save()
            logger.info(f"Admin {request.user.username} added category offer '{category_offer.name}'")
            messages.success(request, f"Category offer '{category_offer.name}' added successfully!")
            return redirect('offer_and_coupon_app:admin_category_offer_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CategoryOfferForm()

    context = {
        'form': form,
        'title': 'Add Category Offer',
        'action': 'Add',
    }
    return render(request, 'offer_and_coupon_app/admin_offer_form.html', context)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_category_offer_edit(request, offer_id):
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    if request.method == 'POST':
        form = CategoryOfferForm(request.POST, instance=offer)
        if form.is_valid():
            category_offer = form.save()
            logger.info(f"Admin {request.user.username} updated category offer '{category_offer.name}'")
            messages.success(request, f"Category offer '{category_offer.name}' updated successfully!")
            return redirect('offer_and_coupon_app:admin_category_offer_list')
        else:
            messages.error(request, "Please correct the errors below.")
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
def admin_category_offer_toggle(request, offer_id):
    if request.method == 'POST' and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        offer = get_object_or_404(CategoryOffer, id=offer_id)
        offer.is_active = not offer.is_active
        offer.save(update_fields=['is_active', 'updated_at'])
        status = "activated" if offer.is_active else "deactivated"
        logger.info(f"Admin {request.user.username} {status} category offer '{offer.name}'")
        return JsonResponse({
            'success': True,
            'is_active': offer.is_active,
            'message': f"Category offer '{offer.name}' {status} successfully!"
        })
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

@login_required
def admin_product_offer_list(request):
    product_offers = ProductOffer.objects.all()
    context = {'product_offers': product_offers, 'title': 'Product Offers'}
    return render(request, 'offer_and_coupon_app/admin_offer_list.html', context)

@login_required
@user_passes_test(is_admin)
def admin_category_offer_list(request):
    # Base queryset
    offers = CategoryOffer.objects.all()

    # Search filter
    search_query = request.GET.get('search', '')
    if search_query:
        offers = offers.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Status filter
    status = request.GET.get('status', '')
    if status == 'active':
        offers = offers.filter(
            is_active=True,
            valid_from__lte=timezone.now(),
            valid_to__gte=timezone.now()
        )
    elif status == 'inactive':
        offers = offers.filter(
            Q(is_active=False) |
            Q(valid_from__gt=timezone.now()) |
            Q(valid_to__lt=timezone.now())
        )

    # Sorting
    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = ['name', '-name', 'discount_value', '-discount_value', 
                     'valid_from', '-valid_from', 'valid_to', '-valid_to']
    if sort_by in allowed_sorts:
        offers = offers.order_by(sort_by)
    else:
        offers = offers.order_by('-created_at')

    # Pagination
    paginator = Paginator(offers, 10) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'title': 'Category Offers',
        'search_query': search_query,
        'status': status,
        'sort_by': sort_by,
        'now': timezone.now(),
    }
    return render(request, 'offer_and_coupon_app/admin_category_offer_list.html', context)

@login_required
@user_passes_test(is_admin)
def admin_category_offers(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    offers = CategoryOffer.objects.filter(categories=category).order_by('-valid_to')
    
    context = {
        'category': category,
        'offers': offers,
        'title': f"Offers for {category.name}",
        'now': timezone.now(),
    }
    return render(request, 'offer_and_coupon_app/admin_category_offers.html', context)

@login_required
def product_offer_toggle_active(request, offer_id):
    offer = get_object_or_404(ProductOffer, id=offer_id)
    offer.is_active = not offer.is_active
    offer.save()
    
    status = "activated" if offer.is_active else "deactivated"
    messages.success(request, f"Product offer '{offer.name}' has been {status}.")
    return redirect('offer_and_coupon:admin_product_offer_list')

@login_required
def category_offer_toggle_active(request, offer_id):
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    offer.is_active = not offer.is_active
    offer.save()
    
    status = "activated" if offer.is_active else "deactivated"
    messages.success(request, f"Category offer '{offer.name}' has been {status}.")
    return redirect('offer_and_coupon:admin_category_offer_list')

# offer_and_coupon_app/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import ProductOfferForm, CategoryOfferForm
from .models import ProductOffer, CategoryOffer

@login_required
def admin_add_offer(request):
    product_offer_form = ProductOfferForm()
    category_offer_form = CategoryOfferForm()

    if request.method == 'POST':
        offer_type = request.POST.get('offer_type')
        if offer_type == 'product':
            product_offer_form = ProductOfferForm(request.POST)
            if product_offer_form.is_valid():
                product_offer = product_offer_form.save()
                messages.success(request, f'Product Offer "{product_offer.name}" created successfully!')
                return redirect('offer_and_coupon_app:admin_offer_list')
        elif offer_type == 'category':
            category_offer_form = CategoryOfferForm(request.POST)
            if category_offer_form.is_valid():
                category_offer = category_offer_form.save()
                messages.success(request, f'Category Offer "{category_offer.name}" created successfully!')
                return redirect('offer_and_coupon_app:admin_offer_list')

    context = {
        'product_offer_form': product_offer_form,
        'category_offer_form': category_offer_form,
    }
    return render(request, 'offer_and_coupon_app/admin_add_offer.html', context)

@login_required
def admin_offer_list(request):
    product_offers = ProductOffer.objects.all()
    category_offers = CategoryOffer.objects.all()
    context = {
        'product_offers': product_offers,
        'category_offers': category_offers,
    }
    return render(request, 'offer_and_coupon_app/admin_offer_list.html', context)

@login_required
def admin_edit_offer(request, offer_id):
    # Determine if it's a ProductOffer or CategoryOffer
    offer = ProductOffer.objects.filter(id=offer_id).first()
    form_class = ProductOfferForm
    title = 'Edit Product Offer'
    if not offer:
        offer = CategoryOffer.objects.filter(id=offer_id).first()
        form_class = CategoryOfferForm
        title = 'Edit Category Offer'
    if not offer:
        messages.error(request, 'Offer not found.')
        return redirect('offer_and_coupon_app:admin_offer_list')

    if request.method == 'POST':
        form = form_class(request.POST, instance=offer)
        if form.is_valid():
            form.save()
            messages.success(request, f'{title.split()[1]} "{offer.name}" updated successfully!')
            return redirect('offer_and_coupon_app:admin_offer_list')
    else:
        form = form_class(instance=offer)

    return render(request, 'offer_and_coupon_app/admin_offer_form.html', {'form': form, 'title': title, 'offer': offer})


@login_required
def admin_delete_offer(request, offer_id):
    try:
        offer = ProductOffer.objects.get(id=offer_id)
    except ProductOffer.DoesNotExist:
        offer = CategoryOffer.objects.get(id=offer_id)
    offer.delete()
    return JsonResponse({'success': True, 'message': f'Offer "{offer.name}" deleted successfully'})


logger = logging.getLogger(__name__)

@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET", "POST"])
def admin_add_category_offer(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if request.method == "POST":
        form = CategoryOfferForm(request.POST)
        if form.is_valid():
            category_offer = form.save(commit=False)
            category_offer.save()
            category_offer.categories.add(category)
            logger.info(f"Admin {request.user.username} added category offer '{category_offer.name}' for category '{category.name}'")
            messages.success(request, f"Offer '{category_offer.name}' added successfully for category '{category.name}'!")
            return redirect('product_app:admin_category_detail', category_id=category.id)
    else:
        initial_data = {'categories': [category]}
        form = CategoryOfferForm(initial=initial_data)

    context = {
        'title': f'Add Offer for {category.name}',
        'form': form,
        'category': category,
        'action': 'Add',
    }
    return render(request, 'offer_and_coupon_app/admin_category_offer_add.html', context)