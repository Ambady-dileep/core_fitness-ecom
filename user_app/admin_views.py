from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django.urls import reverse
from .forms import BannerForm
from urllib.parse import urlencode
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from user_app.models import CustomUser, UserProfile, Banner
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Count, Sum, F
from django.utils import timezone
from datetime import datetime, timedelta
from cart_and_orders_app.models import Order, OrderItem
import logging

logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_authenticated and user.is_superuser


@never_cache
@require_http_methods(["GET", "POST"])
def admin_login(request):
    logger = logging.getLogger(__name__)
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('user_app:admin_customer_list')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        try:
            user_obj = CustomUser.objects.get(username=username)
            if not user_obj.is_superuser:
                logger.warning(f"Unauthorized admin access attempt by username: {username}")
                messages.error(request, "You are not authorized to access the admin panel.")
                return render(request, 'admin_login.html')
            
            if user_obj.profile.is_blocked: 
                logger.warning(f"Blocked admin account attempted login: {username}")
                messages.error(request, "Your account has been blocked. Please contact support.")
                return render(request, 'admin_login.html')

            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                logger.info(f"Admin login successful: {username}")
                return redirect('user_app:admin_customer_list')
            else:
                logger.warning(f"Failed admin login attempt: {username}")
                messages.error(request, "Invalid username or password.")
        except CustomUser.DoesNotExist:
            logger.warning(f"Admin login attempt with non-existent username: {username}")
            messages.error(request, "Username does not exist.")
    
    return render(request, 'admin_login.html')


@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    logger.info(f"Admin {request.user.username} accessed the dashboard")

    # Time filter
    time_filter = request.GET.get('time_filter', 'monthly')
    now = timezone.now()
    start_date = now

    if time_filter == 'daily':
        start_date = now - timedelta(days=1)
    elif time_filter == 'weekly':
        start_date = now - timedelta(days=7)
    elif time_filter == 'monthly':
        start_date = now - timedelta(days=30)
    elif time_filter == 'yearly':
        start_date = now - timedelta(days=365)

    # Sales data for chart
    orders = Order.objects.filter(order_date__gte=start_date, status='Delivered')
    sales_data = []
    labels = []
    
    if time_filter == 'daily':
        for hour in range(24):
            hour_start = start_date.replace(hour=hour, minute=0, second=0)
            hour_end = hour_start + timedelta(hours=1)
            amount = orders.filter(order_date__gte=hour_start, order_date__lt=hour_end).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            sales_data.append(float(amount))
            labels.append(hour_start.strftime('%H:%M'))
    elif time_filter == 'weekly':
        for i in range(7):
            day = (start_date + timedelta(days=i)).date()
            amount = orders.filter(order_date__date=day).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            sales_data.append(float(amount))
            labels.append(day.strftime('%a'))
    elif time_filter == 'monthly':
        for i in range(30):
            day = (start_date + timedelta(days=i)).date()
            amount = orders.filter(order_date__date=day).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            sales_data.append(float(amount))
            labels.append(day.strftime('%d %b'))
    elif time_filter == 'yearly':
        for i in range(12):
            month_start = (start_date + timedelta(days=30*i)).replace(day=1)
            month_end = (month_start + timedelta(days=31)).replace(day=1) - timedelta(seconds=1)
            amount = orders.filter(order_date__gte=month_start, order_date__lt=month_end).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            sales_data.append(float(amount))
            labels.append(month_start.strftime('%b'))

    # Top 10 best-selling products
    top_products = OrderItem.objects.filter(order__status='Delivered').values(
        'variant__product__product_name'
    ).annotate(
        total_sold=Sum('quantity'),
        total_revenue=Sum(F('quantity') * F('price'))
    ).order_by('-total_sold')[:10]

    # Top 10 best-selling categories
    top_categories = OrderItem.objects.filter(order__status='Delivered').values(
        'variant__product__category__name'
    ).annotate(
        total_sold=Sum('quantity'),
        total_revenue=Sum(F('quantity') * F('price'))
    ).order_by('-total_sold')[:10]

    # Top 10 best-selling brands
    top_brands = OrderItem.objects.filter(order__status='Delivered').values(
        'variant__product__brand__name'
    ).annotate(
        total_sold=Sum('quantity'),
        total_revenue=Sum(F('quantity') * F('price'))
    ).order_by('-total_sold')[:10]

    # Basic statistics
    total_users = CustomUser.objects.filter(is_superuser=False).count()
    total_orders = orders.count()
    total_revenue = orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    context = {
        'title': 'Admin Dashboard',
        'total_users': total_users,
        'total_orders': total_orders,
        'total_revenue': float(total_revenue),
        'sales_data': sales_data,
        'sales_labels': labels,
        'time_filter': time_filter,
        'top_products': top_products,
        'top_categories': top_categories,
        'top_brands': top_brands,
    }
    return render(request, 'user_app/admin_dashboard.html', context)


@login_required
@user_passes_test(is_admin)
@never_cache
def admin_customer_list(request):
    logger = logging.getLogger(__name__)
    
    # Exclude superusers (admins) from the user list
    users = CustomUser.objects.filter(is_superuser=False).order_by('username')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )
        logger.info(f"Admin {request.user.username} searched for users with query: {search_query}")
    
    # Pagination
    paginator = Paginator(users, 10)  # Show 10 users per page
    page = request.GET.get('page', 1)
    try:
        users_page = paginator.page(page)
    except PageNotAnInteger:
        users_page = paginator.page(1)
    except EmptyPage:
        users_page = paginator.page(paginator.num_pages)
    
    total_users = CustomUser.objects.filter(is_superuser=False).count()
    blocked_users = UserProfile.objects.filter(is_blocked=True, user__is_superuser=False).count()
    active_users = total_users - blocked_users

    context = {
        'users': users_page,
        'search_query': search_query,
        'total_users': total_users,
        'active_users': active_users,
        'blocked_users': blocked_users,
        'title': 'Admin Dashboard',
    }
    return render(request, 'admin_customer_list.html', context)


@login_required
@user_passes_test(is_admin)
@require_POST
def toggle_user_block(request, user_id):
    logger = logging.getLogger(__name__)
    try:
        user = CustomUser.objects.get(id=user_id)
        user_profile, created = UserProfile.objects.get_or_create(user=user)
        user_profile.is_blocked = not user_profile.is_blocked
        user_profile.save()
        status = "blocked" if user_profile.is_blocked else "unblocked"
        logger.info(f"User '{user.username}' {status} by admin {request.user.username}")
        messages.success(request, f"User '{user.username}' has been {status} successfully!")
    except CustomUser.DoesNotExist:
        logger.error(f"User not found for id={user_id}")
        messages.error(request, "User not found!")
    
    search_query = request.POST.get('search_query', '')
    page = request.POST.get('page', '1')
    query_params = {}
    if search_query:
        query_params['search'] = search_query
    if page != '1':
        query_params['page'] = page
    redirect_url = reverse('user_app:admin_customer_list')
    if query_params:
        redirect_url += f"?{urlencode(query_params)}"
    return redirect(redirect_url)



@login_required
@user_passes_test(is_admin)
@never_cache
def admin_banner_list(request):
    logger.info(f"Admin {request.user.username} accessed banner management")
    banners = Banner.objects.all().order_by('display_order', '-created_at')

    # Pagination
    paginator = Paginator(banners, 10)  # Show 10 banners per page
    page = request.GET.get('page', 1)
    try:
        banners_page = paginator.page(page)
    except PageNotAnInteger:
        banners_page = paginator.page(1)
    except EmptyPage:
        banners_page = paginator.page(paginator.num_pages)

    context = {
        'banners': banners_page,
        'title': 'Banner Management',
    }
    return render(request, 'admin_banner_list.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_banner_create(request):
    if request.method == 'POST':
        form = BannerForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Banner created successfully!")
            return redirect('user_app:admin_banner_list')
    else:
        form = BannerForm()
    
    context = {
        'form': form,
        'title': 'Create Banner',
    }
    return render(request, 'admin_banner_form.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_banner_edit(request, banner_id):
    try:
        banner = Banner.objects.get(id=banner_id)
    except Banner.DoesNotExist:
        messages.error(request, "Banner not found!")
        return redirect('user_app:admin_banner_list')
    
    if request.method == 'POST':
        form = BannerForm(request.POST, request.FILES, instance=banner)
        if form.is_valid():
            form.save()
            messages.success(request, "Banner updated successfully!")
            return redirect('user_app:admin_banner_list')
    else:
        form = BannerForm(instance=banner)
    
    context = {
        'form': form,
        'banner': banner,
        'title': 'Edit Banner',
    }
    return render(request, 'admin_banner_form.html', context)

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_banner_delete(request, banner_id):
    try:
        banner = Banner.objects.get(id=banner_id)
        banner.delete()
        messages.success(request, "Banner deleted successfully!")
    except Banner.DoesNotExist:
        messages.error(request, "Banner not found!")
    
    return redirect('user_app:admin_banner_list')

@login_required
@user_passes_test(is_admin)
@require_POST
def admin_banner_toggle_status(request, banner_id):
    try:
        banner = Banner.objects.get(id=banner_id)
        banner.is_active = not banner.is_active
        banner.save()
        status = "activated" if banner.is_active else "deactivated"
        messages.success(request, f"Banner '{banner.title}' {status} successfully!")
    except Banner.DoesNotExist:
        messages.error(request, "Banner not found!")
    
    return redirect('user_app:admin_banner_list')


@login_required
@user_passes_test(is_admin)
@never_cache
def admin_logout(request):
    logout(request)
    request.session.flush()
    return redirect('user_app:admin_login')
