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
from django.core.mail import send_mail
from django.conf import settings
from .forms import ContactForm
from .models import ContactMessage
from cart_and_orders_app.models import Order, OrderItem, ReturnRequest, ProductVariant
import json
from django.db.models import Q, Count, Sum, F
from django.utils import timezone
from datetime import datetime, timedelta
from cart_and_orders_app.models import Order, OrderItem
from .forms import AdminLoginForm
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
        
    form = AdminLoginForm(request.POST or None)
    
    if request.method == 'POST':
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            
            user = authenticate(request, username=username, password=password)
            if user is None:
                logger.warning(f"Failed admin login attempt: {username}")
                form.add_error(None, "Invalid username or password.")
                return render(request, 'admin_login.html', {'form': form})
                
            try:
                user_obj = CustomUser.objects.get(username=username)
                if not user_obj.is_superuser:
                    logger.warning(f"Unauthorized admin access attempt by username: {username}")
                    form.add_error(None, "You are not authorized to access the admin panel.")
                    return render(request, 'admin_login.html', {'form': form})
                
                login(request, user)
                logger.info(f"Admin login successful: {username}")
                return redirect('user_app:admin_customer_list')
            except CustomUser.DoesNotExist:
                logger.warning(f"Admin login attempt with non-existent username: {username}")
                form.add_error('username', "Username does not exist.")
                return render(request, 'admin_login.html', {'form': form})
        else:
            logger.warning("Form validation failed")
    
    return render(request, 'admin_login.html', {'form': form})

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

    # Sales data for chart - Include 'Confirmed' and 'Delivered' orders
    orders = Order.objects.filter(
        Q(status='Confirmed') | Q(status='Delivered'),
        order_date__gte=start_date
    )
    sales_data = []
    labels = []

    if time_filter == 'daily':
        for hour in range(24):
            hour_start = start_date.replace(hour=hour, minute=0, second=0)
            hour_end = hour_start + timedelta(hours=1)
            # Filter orders by the hour they were confirmed or delivered
            amount = orders.filter(
                order_date__gte=hour_start,
                order_date__lt=hour_end
            ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
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

    # Basic statistics
    total_users = CustomUser.objects.filter(is_superuser=False).count()
    total_orders = orders.count()
    total_revenue = orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    pending_returns = ReturnRequest.objects.filter(is_verified=False, refund_processed=False).count()
    average_order_value = total_revenue / total_orders if total_orders > 0 else 0
    total_coupon_discount = orders.aggregate(Sum('coupon_discount'))['coupon_discount__sum'] or 0
    low_stock_items = ProductVariant.objects.filter(stock__lte=10, is_active=True).count()

    # Recent orders (last 5)
    recent_orders = Order.objects.select_related('user').order_by('-order_date')[:5]

    # Low stock variants (stock <= 10)
    low_stock_variants = ProductVariant.objects.filter(stock__lte=10, is_active=True).select_related('product')[:10]

    # Order status distribution
    order_status_counts = Order.objects.values('status').annotate(count=Count('id'))
    order_status_labels = [status['status'] for status in order_status_counts]
    order_status_data = [status['count'] for status in order_status_counts]

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

    context = {
        'title': 'Admin Dashboard',
        'total_users': total_users,
        'total_orders': total_orders,
        'total_revenue': float(total_revenue),
        'pending_returns': pending_returns,
        'average_order_value': float(average_order_value),
        'total_coupon_discount': float(total_coupon_discount),
        'low_stock_items': low_stock_items,
        'recent_orders': recent_orders,
        'low_stock_variants': low_stock_variants,
        'sales_data': sales_data,
        'sales_labels': json.dumps(labels),
        'order_status_labels': json.dumps(order_status_labels),
        'order_status_data': order_status_data,
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
        if user.is_superuser:
            logger.warning(f"Attempt to block/unblock superuser {user.username} by admin {request.user.username}")
            messages.error(request, "Superusers cannot be blocked or unblocked.")
            return redirect('user_app:admin_customer_list')
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


def contact_us(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            # Save the contact message to the database
            contact_message = form.save()
            
            # Send email notification to admin
            subject = f"New Contact Us Message: {contact_message.subject}"
            message = (
                f"New message from {contact_message.name} ({contact_message.email})\n\n"
                f"Subject: {contact_message.subject}\n\n"
                f"Message:\n{contact_message.message}\n\n"
                f"Received on: {contact_message.created_at}"
            )
            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [settings.DEFAULT_FROM_EMAIL],
                    fail_silently=False,
                )
            except Exception as e:
                messages.error(request, "Message saved, but failed to send email notification. We'll get back to you soon.")
                # Log the error for debugging
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Email sending failed: {str(e)}")
            
            messages.success(request, "Thank you for your message! We'll get back to you soon.")
            return redirect('user_app:contact_us')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ContactForm()

    return render(request, 'contact_us.html', {
        'form': form,
        'title': 'Contact Us',
    })