from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from user_app.models import CustomUser
from .models import UserProfile
from django.shortcuts import render, redirect
from django.db.models import Q
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from user_app.models import CustomUser, UserProfile, LoginAttempt
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django.urls import reverse
from urllib.parse import urlencode
import logging
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_authenticated and user.is_superuser

@never_cache
@require_http_methods(["GET", "POST"])
def admin_login(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('user_app:admin_dashboard')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        try:
            user = CustomUser.objects.get(username=username)
            if not user.is_superuser:
                messages.error(request, "You are not authorized to access the admin panel.")
                return render(request, 'admin_login.html')
            
            if user.profile.is_blocked: 
                messages.error(request, "Your account has been blocked. Please contact support.")
                return render(request, 'admin_login.html')

            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                user.reset_login_attempts()  # Reset attempts on successful login
                return redirect('user_app:admin_dashboard')
            else:
                user.increment_login_attempts()  # Increment failed attempts
                if not user.check_login_attempts():
                    messages.error(request, "Too many failed attempts. Account locked for 15 minutes.")
                else:
                    messages.error(request, "Invalid username or password.")
        except CustomUser.DoesNotExist:
            messages.error(request, "Username does not exist.")
    
    return render(request, 'admin_login.html')


@login_required
@user_passes_test(is_admin)
@never_cache
def admin_dashboard(request):
    search_query = request.GET.get('search', '')
    
    # User list
    if search_query:
        users = CustomUser.objects.filter(
            Q(username__icontains=search_query) | 
            Q(email__icontains=search_query) |
            Q(full_name__icontains=search_query)
        ).filter(is_superuser=False).select_related('profile')
    else:
        users = CustomUser.objects.filter(is_superuser=False).select_related('profile')
    
    users = users.order_by('-date_joined')
    
    # Pagination
    page = request.GET.get('page', 1)
    items_per_page = 10
    paginator = Paginator(users, items_per_page)
    try:
        users_page = paginator.page(page)
    except PageNotAnInteger:
        users_page = paginator.page(1)
    except EmptyPage:
        users_page = paginator.page(paginator.num_pages)
    
    # Basic stats for dashboard
    total_users = CustomUser.objects.filter(is_superuser=False).count()
    blocked_users = UserProfile.objects.filter(is_blocked=True).count()
    active_users = total_users - blocked_users
    
    context = {
        'users': users_page,
        'search_query': search_query,
        'total_users': total_users,
        'blocked_users': blocked_users,
        'active_users': active_users,
    }
    return render(request, 'admin_dashboard.html', context)


@login_required
@user_passes_test(is_admin)
@require_POST
def toggle_user_block(request, user_id):
    try:
        user = CustomUser.objects.get(id=user_id)
        # Get or create UserProfile to ensure it exists
        user_profile, created = UserProfile.objects.get_or_create(user=user)
        user_profile.is_blocked = not user_profile.is_blocked
        user_profile.save()
        status = "blocked" if user_profile.is_blocked else "unblocked"
        messages.success(request, f"User '{user.username}' has been {status} successfully!")
    except CustomUser.DoesNotExist:
        logger.error(f"User not found for id={user_id}")
        messages.error(request, "User not found!")
    
    # Redirect with preserved parameters
    search_query = request.POST.get('search_query', '')
    page = request.POST.get('page', '1')
    query_params = {}
    if search_query:
        query_params['search'] = search_query
    if page != '1':
        query_params['page'] = page
    redirect_url = reverse('user_app:admin_dashboard')
    if query_params:
        redirect_url += f"?{urlencode(query_params)}"
    return redirect(redirect_url)

@login_required
@user_passes_test(is_admin)
@require_POST
def delete_user(request, user_id):
    try:
        user = CustomUser.objects.get(id=user_id)
        if user.is_superuser:
            messages.error(request, "Cannot delete a superuser account!")
        else:
            user.delete()
            messages.success(request, f"User '{user.username}' has been deleted successfully!")
    except CustomUser.DoesNotExist:
        logger.error(f"User not found for deletion, id={user_id}")
        messages.error(request, "User not found!")
    
    # Redirect with preserved parameters
    search_query = request.POST.get('search_query', '')
    page = request.POST.get('page', '1')
    query_params = {}
    if search_query:
        query_params['search'] = search_query
    if page != '1':
        query_params['page'] = page
    redirect_url = reverse('user_app:admin_dashboard')
    if query_params:
        redirect_url += f"?{urlencode(query_params)}"
    return redirect(redirect_url)

@login_required
@user_passes_test(is_admin)
@never_cache
def user_stats(request, user_id=None):
    if user_id:
        # Detailed stats for a specific user
        try:
            user = CustomUser.objects.get(id=user_id)
            login_attempts = LoginAttempt.objects.filter(user=user).order_by('-timestamp')[:10]
            total_logins = LoginAttempt.objects.filter(user=user, success=True).count()
            failed_logins = LoginAttempt.objects.filter(user=user, success=False).count()
            context = {
                'user': user,
                'login_attempts': login_attempts,
                'total_logins': total_logins,
                'failed_logins': failed_logins,
            }
            return render(request, 'user_stats.html', context)
        except CustomUser.DoesNotExist:
            messages.error(request, "User not found!")
            return redirect('user_app:admin_dashboard')
    else:
        # Overall user stats
        total_users = CustomUser.objects.filter(is_superuser=False).count()
        blocked_users = UserProfile.objects.filter(is_blocked=True).count()
        active_users = total_users - blocked_users
        successful_logins = LoginAttempt.objects.filter(success=True).count()
        failed_logins = LoginAttempt.objects.filter(success=False).count()
        context = {
            'total_users': total_users,
            'blocked_users': blocked_users,
            'active_users': active_users,
            'successful_logins': successful_logins,
            'failed_logins': failed_logins,
        }
        return render(request, 'admin_stats.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_logout(request):
    logout(request)
    request.session.flush()
    return redirect('user_app:admin_login')
