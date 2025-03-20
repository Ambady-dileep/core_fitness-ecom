from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.views.decorators.cache import never_cache
from django.db.models import Q
from django.urls import reverse
from .models import Category, Product
from .forms import CategoryForm

def is_admin(user):
    """Check if the user is an admin (staff or superuser)."""
    return user.is_staff or user.is_superuser

# Admin Views
@login_required
@user_passes_test(is_admin)
@never_cache
def admin_category_list(request):
    """
    Display a paginated list of all categories for admin.
    """
    query = request.GET.get('q')
    sort_by = request.GET.get('sort', '')
    categories = Category.objects.all()

    if query:
        categories = categories.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )

    # Apply sorting
    if sort_by == 'a_to_z':
        categories = categories.order_by('name')
    elif sort_by == 'z_to_a':
        categories = categories.order_by('-name')
    else:
        categories = categories.order_by('name')  # Default sorting

    paginator = Paginator(categories, 10)  # 10 categories per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'title': 'Admin Categories',
        'query': query,
        'sort_by': sort_by,
    }
    return render(request, 'admin_category_list.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def category_detail(request, category_id):
    """
    Display details of a specific category for admin.
    """
    category = get_object_or_404(Category, id=category_id)
    products = category.products.prefetch_related('variants')
    context = {
        'category': category,
        'products': products,
        'title': f'Category: {category.name}',
    }
    return render(request, 'admin_category_detail.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def add_category(request):
    """
    Add a new category (admin only).
    """
    if request.method == 'POST':
        form = CategoryForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Category added successfully!")
            return redirect('product_app:admin_category_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CategoryForm()
    
    context = {
        'form': form,
        'title': 'Add New Category',
    }
    return render(request, 'admin_add_category.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def edit_category(request, category_id):
    """
    Edit an existing category (admin only).
    """
    category = get_object_or_404(Category, id=category_id)
    if request.method == 'POST':
        form = CategoryForm(request.POST, request.FILES, instance=category)
        if form.is_valid():
            category = form.save()
            messages.success(request, f"Category '{category.name}' updated successfully!")
            return redirect('product_app:admin_category_list')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CategoryForm(instance=category)
    
    context = {
        'form': form,
        'category': category,
        'title': f'Edit Category: {category.name}',
    }
    return render(request, 'admin_edit_category.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def delete_category(request, category_id):
    """
    Delete a category (admin only). Uses CASCADE for related products.
    """
    category = get_object_or_404(Category, id=category_id)
    if request.method == 'POST':
        category_name = category.name
        category.delete()
        messages.success(request, f'Category "{category_name}" deleted successfully.')
        return redirect('product_app:admin_category_list')
    context = {
        'category': category,
        'title': f'Delete Category: {category.name}',
    }
    return render(request, 'admin_delete_category.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_category_products(request, category_id):
    """
    Display products for a specific category in admin panel.
    """
    category = get_object_or_404(Category, id=category_id)
    products = category.products.prefetch_related('variants')
    context = {
        'category': category,
        'products': products,
        'title': f'Products in {category.name}',
    }
    return render(request, 'admin_category_products.html', context)

# User Views
@never_cache
@login_required
def user_category_list(request):
    """
    Display a paginated list of active categories for users.
    """
    query = request.GET.get('q')
    sort_by = request.GET.get('sort', '')
    categories = Category.objects.filter(is_active=True)  # Removed prefetch_related

    if query:
        categories = categories.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )

    # Apply sorting
    if sort_by == 'a_to_z':
        categories = categories.order_by('name')
    elif sort_by == 'z_to_a':
        categories = categories.order_by('-name')
    else:
        categories = categories.order_by('name')  # Default sorting

    paginator = Paginator(categories, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'title': 'Categories',
        'query': query,
        'sort_by': sort_by,
    }
    return render(request, 'user_category_list.html', context)


@login_required
@never_cache
def user_category_products(request, category_id):
    """
    Display products under a specific category for users.
    """
    category = get_object_or_404(Category, id=category_id, is_active=True)
    products = category.products.filter(is_active=True, is_listed=True).prefetch_related('variants')
    context = {
        'category': category,
        'products': products,
        'title': f'Products in {category.name}',
    }
    return render(request, 'user_category_products.html', context)