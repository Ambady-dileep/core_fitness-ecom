import logging
import re
from .forms import AddressForm, GenerateOTPForm, ValidateOTPForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.contrib import messages
from django.db.models import Q, Min, Count, Avg
from product_app.models import Product, Category
from django.shortcuts import render, redirect
from .models import CustomUser as User
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from .models import Address
from .forms import UserProfileForm, ProfileForm, CustomPasswordChangeForm
from .models import Banner
from django.conf import settings
from product_app.models import Product, Category, Review
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.views.decorators.cache import never_cache
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.http import JsonResponse
from cart_and_orders_app.models import Order  
from .forms import CustomUserCreationForm
from django.shortcuts import get_object_or_404
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from .utils.otp_utils import generate_otp, store_otp, get_otp, delete_otp, set_otp_cooldown, get_otp_cooldown

logger = logging.getLogger(__name__)

@cache_control(no_cache=True, no_store=True, must_revalidate=True)
@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie  
def user_login(request):
    if request.user.is_authenticated:
        return redirect('user_app:user_home')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        try:
            user = User.objects.get(username=username)
            
            if hasattr(user, 'userprofile') and user.userprofile.is_blocked:
                messages.error(request, "Your account has been blocked. Please contact support.")
                return render(request, 'signup_login.html')
            
            if hasattr(user, 'check_login_attempts') and not user.check_login_attempts():
                messages.error(request, "Too many failed attempts. Please try again after 15 minutes.")
                return render(request, 'signup_login.html')
            
            authenticated_user = authenticate(request, username=username, password=password)
            
            if authenticated_user:
                login(request, authenticated_user)
                if hasattr(user, 'login_attempts'):
                    user.login_attempts = 0
                    user.save()
                return redirect('user_app:user_home')
            else:
                if hasattr(user, 'login_attempts'):
                    user.login_attempts += 1
                    user.save()
                messages.error(request, "Invalid username or password.")
                
        except User.DoesNotExist:
            messages.error(request, "Invalid username or password.")
    
    context = {
        'generate_otp_form': GenerateOTPForm(), 
    }
    return render(request, 'signup_login.html', context)

@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def user_signup(request):
    """Handle user registration with OTP verification."""
    if request.user.is_authenticated:
        return redirect("user_app:user_home")
    
    context = {
        'login_messages': [],
        'signup_messages': [],
        'signup_active': True,
        'form_data': {}
    }
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')
        full_name = request.POST.get('full_name', '').strip()
        referral_code = request.POST.get('referral_code', request.session.get('referral_code', '')).strip()

        logger.debug(f"Received signup form data: username={username}, email={email}, phone_number={phone_number}, full_name={full_name}")

        context['form_data'] = {
            'username': username,
            'email': email,
            'phone_number': phone_number,
            'full_name': full_name
        }
        
        # Validation checks
        if not username or len(username) < 3 or len(username) > 20 or not username.isalnum():
            messages.error(request, "Username must be 3-20 characters long and alphanumeric.")
            return render(request, 'signup_login.html', context)
        
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return render(request, 'signup_login.html', context)
        
        # Password validation
        if not all([
            len(password1) >= 8,
            any(char.isupper() for char in password1),
            any(char.islower() for char in password1),
            any(char.isdigit() for char in password1),
            any(char in "!@#$%^&*()+-_=[]{};:,.<>?" for char in password1),
            password1 == password2
        ]):
            messages.error(request, "Password must be 8+ characters with uppercase, lowercase, number, and special character.")
            return render(request, 'signup_login.html', context)
        
        if not re.match(r'^[6-9]\d{9}$', phone_number):
            messages.error(request, "Invalid phone number. Must be 10 digits starting with 6-9.")
            return render(request, 'signup_login.html', context)
        
        # Check for existing users
        if User.objects.filter(Q(username__iexact=username) | 
                              Q(email__iexact=email) | 
                              Q(phone_number=phone_number)).exists():
            messages.error(request, "Username, email, or phone number already exists.")
            return render(request, 'signup_login.html', context)
        
        stored_otp = get_otp(email)
        if stored_otp and 'signup_data' in request.session and request.session['signup_data'].get('email') == email:
            messages.error(request, "A signup process is already in progress for this email. Please verify the OTP or wait 3 minutes to try again.")
            return render(request, 'signup_login.html', context)

        # Generate and send OTP
        if get_otp_cooldown(email):
            messages.error(request, "Please wait 3 minutes before requesting a new OTP.")
            return render(request, 'signup_login.html', context)

        try:
            logger.debug("Generating OTP...")
            otp = generate_otp()
            logger.debug(f"Generated OTP: {otp}")

            logger.debug("Storing OTP...")
            store_otp(email, otp, timeout=180)  # Store OTP for 3 minutes
            logger.debug("OTP stored successfully")

            logger.debug("Setting OTP cooldown...")
            set_otp_cooldown(email, timeout=180)  # Set cooldown for 3 minutes
            logger.debug("OTP cooldown set successfully")

            logger.info(f"Attempting to send OTP to {email} with OTP: {otp}")
            logger.debug(f"Email settings: EMAIL_HOST={settings.EMAIL_HOST}, EMAIL_PORT={settings.EMAIL_PORT}, EMAIL_HOST_USER={settings.EMAIL_HOST_USER}")

            send_mail(
                subject="Core Fitness - Verify Your Email",
                message=f"Your OTP for signup is: {otp}. It expires in 3 minutes.",
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
                fail_silently=False,
            )

            logger.info(f"OTP email sent successfully to {email}")

            # Store signup data in session
            request.session['signup_data'] = {
                'username': username,
                'email': email,
                'phone_number': phone_number,
                'password': password1,
                'full_name': full_name,
                'referral_code': referral_code
            }

            messages.success(request, "An OTP has been sent to your email. Please verify to complete signup.")
            return redirect('user_app:verify_otp_signup_page', email=email)

        except Exception as e:
            logger.error(f"Failed to send OTP during signup: {str(e)}", exc_info=True)
            messages.error(request, f"Failed to send OTP: {str(e)}. Please try again.")
            return render(request, 'signup_login.html', context)
        
    if 'referral_code' in request.session:
        context['form_data']['referral_code'] = request.session['referral_code']
    
    return render(request, 'signup_login.html', context)

@cache_control(no_cache=True, no_store=True, must_revalidate=True)
@login_required
def user_logout(request):
    logout(request)
    request.session.flush()
    return redirect('user_app:user_login')

@login_required
@require_http_methods(["GET", "POST"])
def change_password(request):
    if request.method == 'POST':
        form = CustomPasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)  # Keep user logged in
            messages.success(request, "Your password was successfully updated!")
            return redirect('user_app:my_profile')
        else:
            # Pass form errors as messages
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
            return redirect('user_app:my_profile')
    return redirect('user_app:my_profile')

@never_cache
@login_required
def user_home(request):
    if not request.user.is_authenticated:
        return redirect('user_app:user_login')

    category_id = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    brand = request.GET.get('brand')
    sort_by = request.GET.get('sort')
    search_query = request.GET.get('search')
    availability = request.GET.get('availability')
    rating = request.GET.get('rating')
    banners = Banner.objects.filter(is_active=True).order_by('display_order')

    # Base queryset: Active products with active variants from active categories and brands
    products = Product.objects.filter(
        is_active=True,
        category__is_active=True,  # Filter by active categories
        variants__isnull=False,
        variants__is_active=True
    ).annotate(
        lowest_price=Min('variants__original_price')
    ).distinct()

    # Add filter for active brands (only if brand is not null)
    products = products.filter(
        Q(brand__isnull=True) | Q(brand__is_active=True)
    )

    # Apply filters
    if category_id:
        # Ensure we only filter by active categories
        products = products.filter(category_id=category_id, category__is_active=True)
    
    if min_price and max_price:
        products = products.filter(lowest_price__gte=min_price, lowest_price__lte=max_price)
    elif min_price:
        products = products.filter(lowest_price__gte=min_price)
    elif max_price:
        products = products.filter(lowest_price__lte=max_price)
    
    if brand:
        # Ensure we only filter by active brands
        products = products.filter(brand=brand, brand__is_active=True)
    
    if search_query:
        products = products.filter(
            Q(product_name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query) |
            Q(brand__icontains=search_query)
        )
    
    if availability:
        if availability == 'in_stock':
            products = products.filter(variants__stock__gt=0)
        elif availability == 'out_of_stock':
            products = products.filter(variants__stock=0)
    
    if rating:
        try:
            rating_float = float(rating)
            products = products.filter(average_rating__gte=rating_float)
        except ValueError:
            pass

    # Apply sorting
    if sort_by == 'price_low':
        products = products.order_by('lowest_price')
    elif sort_by == 'price_high':
        products = products.order_by('-lowest_price')
    elif sort_by == 'a_to_z':
        products = products.order_by('product_name')
    elif sort_by == 'z_to_a':
        products = products.order_by('-product_name')
    elif sort_by == 'new_arrivals':
        products = products.order_by('-created_at')
    elif sort_by == 'best_sellers':
        products = products.annotate(
            order_count=Count('orderitem')
        ).order_by('-order_count')
    else:
        products = products.order_by('-created_at')

    # Specific product sections - update to include category and brand active status
    featured_products = Product.objects.filter(
        is_active=True,
        category__is_active=True,
        variants__is_active=True
    ).filter(
        Q(brand__isnull=True) | Q(brand__is_active=True)
    ).annotate(
        avg_rating=Avg('reviews__rating')
    ).order_by('-avg_rating')[:8]
    
    new_arrivals = Product.objects.filter(
        is_active=True,
        category__is_active=True,
        variants__is_active=True
    ).filter(
        Q(brand__isnull=True) | Q(brand__is_active=True)
    ).order_by('-created_at')[:8]
    
    top_rated = Product.objects.filter(
        is_active=True,
        category__is_active=True,
        variants__is_active=True
    ).filter(
        Q(brand__isnull=True) | Q(brand__is_active=True)
    ).annotate(
        avg_rating=Avg('reviews__rating')
    ).filter(avg_rating__gte=4.0).order_by('-avg_rating')[:8]
    
    recent_reviews = Review.objects.filter(
        is_approved=True,
        product__is_active=True,
        product__category__is_active=True,
    ).filter(
        Q(product__brand__isnull=True) | Q(product__brand__is_active=True)
    ).order_by('-created_at')[:3]

    categories = Category.objects.filter(is_active=True)
    brands = Product.objects.filter(
        is_active=True,
        category__is_active=True,
        variants__is_active=True,
        brand__is_active=True
    ).values_list('brand', flat=True).distinct()

    context = {
        'products': products,
        'featured_products': featured_products,
        'new_arrivals': new_arrivals,
        'top_rated': top_rated,
        'recent_reviews': recent_reviews,
        'categories': categories,
        'brands': brands,
        'selected_category': category_id,
        'min_price': min_price,
        'max_price': max_price,
        'selected_brand': brand,
        'sort_by': sort_by,
        'search_query': search_query,
        'banners': banners,
    }
    return render(request, 'user_app/user_home.html', context)

def about_us(request):
    return render(request, 'about_us.html')

def privacy_policy(request):
    return render(request, 'privacy_policy.html')

def faq(request):
    return render(request, 'faq.html')

def contact_us(request):
    return render(request, 'contact_us.html')

@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def my_profile(request):
    """Display user profile with orders and addresses."""
    user = request.user
    orders = Order.objects.filter(user=user).order_by('-order_date')
    addresses = Address.objects.filter(user=user)
    address_form = AddressForm()
    context = {
        'user': user,
        'orders': orders,
        'addresses': addresses,
        'address_form': address_form,
    }
    return render(request, 'user_app/user_profile.html', context)

@login_required
@require_http_methods(["GET", "POST"])
def edit_profile(request):
    user = request.user
    # Use the correct related_name 'profile' from UserProfile model
    profile = getattr(user, 'profile', None)

    if request.method == 'POST':
        user_form = UserProfileForm(request.POST, instance=user)
        profile_form = ProfileForm(request.POST, request.FILES, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile = profile_form.save(commit=False)
            profile.user = user  # Ensure the user is set
            profile.save()
            return JsonResponse({
                'success': True,
                'message': 'Profile updated successfully'
            })
        else:
            errors = {}
            for form in (user_form, profile_form):
                for field, error in form.errors.items():
                    errors[field] = error.as_text()
            return JsonResponse({
                'success': False,
                'message': 'Please correct the errors below',
                'errors': errors
            }, status=400)

    else:  # GET request
        user_form = UserProfileForm(instance=user)
        profile_form = ProfileForm(instance=profile)
        return render(request, 'user_edit_profile.html', {
            'user_form': user_form,
            'profile_form': profile_form,
            'user': user
        })

@login_required
@csrf_protect
def add_address(request):
    """Add a new address via AJAX."""
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.save()
            return JsonResponse({
                'success': True,
                'message': 'Address added successfully!',
                'address': {
                    'id': address.id,
                    'full_name': address.full_name,
                    'address_line1': address.address_line1,
                    'address_line2': address.address_line2 or '',
                    'city': address.city,
                    'state': address.state,
                    'postal_code': address.postal_code,
                    'country': address.country,
                    'phone': address.phone,
                    'is_default': address.is_default,
                }
            })
        return JsonResponse({
            'success': False,
            'message': 'Invalid form data',
            'errors': form.errors
        }, status=400)
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

@login_required
@csrf_protect
def edit_address(request, address_id):
    address = get_object_or_404(Address, id=address_id, user=request.user)

    if request.method == 'GET' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            response_data = {
                'success': True,
                'address': {
                    'full_name': address.full_name,
                    'address_line1': address.address_line1,
                    'address_line2': address.address_line2 or '',
                    'city': address.city,
                    'state': address.state,
                    'postal_code': address.postal_code,
                    'country': address.country,
                    'phone': address.phone,
                    'is_default': address.is_default,
                }
            }
            logger.debug(f"Retrieved address {address_id} for editing by user {request.user.username}, phone: {address.phone}")
            return JsonResponse(response_data)
        except Exception as e:
            logger.error(f"Error retrieving address {address_id} for user {request.user.username}: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': f'Failed to load address: {str(e)}'
            }, status=500)

    elif request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            form = AddressForm(request.POST, instance=address)
            logger.debug(f"Form data for address {address_id}: {request.POST}")
            if form.is_valid():
                updated_address = form.save()
                logger.info(f"Address {address_id} updated successfully for user {request.user.username}, phone: {updated_address.phone}")

                # Handle default address logic
                if form.cleaned_data.get('is_default'):
                    Address.objects.filter(user=request.user, is_default=True).exclude(id=address_id).update(is_default=False)
                    updated_address.is_default = True
                    updated_address.save()
                    logger.info(f"Set address {address_id} as default for user {request.user.username}")

                return JsonResponse({
                    'success': True,
                    'message': 'Address updated successfully!',
                    'address': {
                        'id': updated_address.id,
                        'full_name': updated_address.full_name,
                        'address_line1': updated_address.address_line1,
                        'address_line2': updated_address.address_line2 or '',
                        'city': updated_address.city,
                        'state': updated_address.state,
                        'postal_code': updated_address.postal_code,
                        'country': updated_address.country,
                        'phone': updated_address.phone or '',
                        'is_default': updated_address.is_default,
                    }
                })
            else:
                logger.warning(f"Invalid address form submitted by user {request.user.username} for address {address_id}: {form.errors}")
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid form data',
                    'errors': form.errors.as_json()
                }, status=400)
        except Exception as e:
            logger.error(f"Error updating address {address_id} for user {request.user.username}: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': f'Failed to update address: {str(e)}'
            }, status=500)
    else:
        logger.warning(f"Invalid request to edit_address by user {request.user.username}: method={request.method}, is_ajax={request.headers.get('x-requested-with')}")
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method or not an AJAX request'
        }, status=400)

@login_required
def delete_address(request, address_id):
    if request.method == 'POST':
        address = get_object_or_404(Address, id=address_id, user=request.user)
        address.delete()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Address deleted successfully'})
        else:
            messages.success(request, "Address deleted successfully!")
            return redirect('user_app:my_profile')
            
    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

@login_required
@require_POST
def set_default_address(request, address_id):
    address = get_object_or_404(Address, id=address_id, user=request.user)
    Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
    address.is_default = True
    address.save()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Default address updated successfully!'})
    else:
        messages.success(request, "Default address updated successfully!")
        return redirect('user_app:my_profile')

@login_required
def user_address_list(request):
    return redirect('user_app:my_profile')

@require_http_methods(["POST"])
def generate_and_send_otp(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        form = GenerateOTPForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            if get_otp_cooldown(email):
                return JsonResponse({'success': False, 'error': 'Please wait 3 minutes before requesting a new OTP.'}, status=429)
            try:
                user = User.objects.get(email=email)
                otp = generate_otp()
                store_otp(email, otp, timeout=180)
                set_otp_cooldown(email, timeout=180)
                send_mail(
                    subject="Your OTP for Password Reset",
                    message=f"Your OTP for resetting your password is: {otp}. It expires in 3 minutes.",
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[email],
                    fail_silently=False,
                )
                return JsonResponse({'success': True, 'message': 'OTP sent to your email.'})
            except User.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'No account found with this email.'})
            except Exception as e:
                logger.error(f"Failed to send OTP: {str(e)}")
                return JsonResponse({'success': False, 'error': 'Failed to send OTP. Please try again.'})
        return JsonResponse({'success': False, 'error': form.errors.get('email', ['Invalid email format.'])[0]})
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)

@require_http_methods(["POST"])
def validate_otp(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        form = ValidateOTPForm(request.POST)
        email = request.POST.get('email')
        if not email:
            return JsonResponse({'success': False, 'error': 'Email is required.'})
        if form.is_valid():
            user_otp = form.cleaned_data['otp']
            stored_otp = get_otp(email)
            try:
                if stored_otp and int(user_otp) == stored_otp:
                    delete_otp(email)
                    user = User.objects.get(email=email)
                    uid = urlsafe_base64_encode(force_bytes(user.pk))
                    token = default_token_generator.make_token(user)
                    redirect_url = reverse('user_app:password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
                    return JsonResponse({'success': True, 'redirect_url': redirect_url})
                return JsonResponse({'success': False, 'error': 'Invalid or expired OTP.'})
            except User.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'No account found with this email.'})
            except ValueError:
                return JsonResponse({'success': False, 'error': 'OTP must be a number.'})
        return JsonResponse({'success': False, 'error': form.errors.get('otp', ['Invalid OTP format.'])[0]})
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)

@require_http_methods(["POST"])
def resend_otp(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        email = request.POST.get('email')
        if not email:
            return JsonResponse({'success': False, 'error': 'No email provided.'}, status=400)
        if get_otp_cooldown(email):
            return JsonResponse({'success': False, 'error': 'Please wait 3 minutes before resending.'}, status=429)
        try:
            user = User.objects.get(email=email)
            new_otp = generate_otp()
            store_otp(email, new_otp, timeout=180)
            set_otp_cooldown(email, timeout=180)
            send_mail(
                subject="Your New OTP for Password Reset",
                message=f"Your new OTP for resetting your password is: {new_otp}. It expires in 3 minutes.",
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
                fail_silently=False,
            )
            return JsonResponse({'success': True, 'message': 'New OTP sent to your email.'})
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'No account found with this email.'})
        except Exception as e:
            logger.error(f"Failed to resend OTP: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Failed to resend OTP. Please try again.'})
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)



@require_http_methods(["GET", "POST"])
def password_reset_confirm(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            new_password1 = request.POST.get('new_password1')
            new_password2 = request.POST.get('new_password2')
            if not new_password1 or not new_password2:
                messages.error(request, "Both password fields are required.")
            elif new_password1 != new_password2:
                messages.error(request, "Passwords do not match.")
            elif not all([
                len(new_password1) >= 8,
                any(char.isupper() for char in new_password1),
                any(char.islower() for char in new_password1),
                any(char.isdigit() for char in new_password1),
                any(char in "!@#$%^&*()+-_=[]{};:,.<>?" for char in new_password1),
            ]):
                messages.error(request, "Password must be 8+ characters with uppercase, lowercase, number, and special character.")
            else:
                try:
                    user.set_password(new_password1)
                    user.save()
                    messages.success(request, "Your password has been reset successfully. Please log in with your new password.")
                    return redirect('user_app:user_login')
                except Exception as e:
                    logger.error(f"Password reset error: {str(e)}")
                    messages.error(request, "An error occurred while resetting your password.")
            return render(request, 'password_reset_confirm.html', {
                'validlink': True,
                'uidb64': uidb64,
                'token': token,
            })
        return render(request, 'password_reset_confirm.html', {
            'validlink': True,
            'uidb64': uidb64,
            'token': token,
        })
    else:
        messages.error(request, "The password reset link is invalid or has expired.")
        return render(request, 'password_reset_confirm.html', {'validlink': False})

@require_http_methods(["GET"])
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def verify_otp_signup_page(request, email):
    logger.info(f"Accessing verify_otp_signup_page for email: {email}")
    try:
        if 'signup_data' not in request.session:
            logger.warning("Session expired: 'signup_data' not found in session")
            messages.error(request, 'Session expired. Please sign up again.')
            return redirect('user_app:user_signup')
        signup_data = request.session['signup_data']
        logger.debug(f"Session signup_data: {signup_data}")
        if signup_data.get('email') != email:
            logger.warning(f"Email mismatch: session email={signup_data.get('email')}, URL email={email}")
            messages.error(request, 'Invalid email. Please sign up again.')
            return redirect('user_app:user_signup')
        context = {'email': email}
        logger.info(f"Rendering otp_verification.html with context: {context}")
        response = render(request, 'otp_verification.html', context)
        logger.info(f"Response rendered, content length: {len(response.content)}")
        return response
    except Exception as e:
        logger.error(f"Error in verify_otp_signup_page: {str(e)}", exc_info=True)
        messages.error(request, f"An error occurred: {str(e)}. Please try again.")
        return redirect('user_app:user_signup')

@require_http_methods(["POST"])
def verify_otp_signup(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        user_otp = request.POST.get('otp')
        signup_data = request.session.get('signup_data')
        if not signup_data or signup_data.get('email') != email:
            messages.error(request, 'Invalid session or email. Please sign up again.')
            return redirect('user_app:user_signup')
        stored_otp = get_otp(email)
        try:
            if stored_otp and int(user_otp) == stored_otp:
                delete_otp(email)
                del request.session['signup_data']
                if 'referral_code' in request.session:
                    del request.session['referral_code']
                
                form_data = {
                    'username': signup_data['username'],
                    'email': signup_data['email'],
                    'phone_number': signup_data['phone_number'],
                    'password1': signup_data['password'],
                    'password2': signup_data['password'],
                    'full_name': signup_data['full_name'],
                    'referral_code': signup_data.get('referral_code', '')
                }
                form = CustomUserCreationForm(form_data)
                if form.is_valid():
                    user = form.save(commit=False)
                    user.is_active = True
                    user.is_verified = True
                    user.save()
                    authenticated_user = authenticate(request, username=signup_data['username'], password=signup_data['password'])
                    if authenticated_user:
                        login(request, authenticated_user)
                    messages.success(request, "Account created successfully! Welcome to Core Fitness.")
                    return redirect('user_app:user_home')
                else:
                    context = {'email': email, 'form_errors': form.errors}
                    return render(request, 'otp_verification.html', context)
            else:
                messages.error(request, "Invalid or expired OTP. Please try again.")
                return redirect('user_app:verify_otp_signup_page', email=email)
        except ValueError:
            messages.error(request, "OTP must be a number.")
            return redirect('user_app:verify_otp_signup_page', email=email)
        except Exception as e:
            logger.error(f"Error creating user after OTP verification: {str(e)}")
            messages.error(request, "An error occurred while creating your account. Please try again.")
            return redirect('user_app:user_signup')
    return redirect('user_app:user_signup')


@require_http_methods(["POST"])
def resend_otp_signup(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        email = request.POST.get('email')
        if not email:
            return JsonResponse({'success': False, 'error': 'No email provided.'}, status=400)
        signup_data = request.session.get('signup_data')
        if not signup_data or signup_data.get('email') != email:
            return JsonResponse({'success': False, 'error': 'Invalid session or email. Please sign up again.'}, status=400)
        if get_otp_cooldown(email):
            return JsonResponse({'success': False, 'error': 'Please wait 3 minutes before resending.'}, status=429)
        try:
            new_otp = generate_otp()
            store_otp(email, new_otp, timeout=180)  
            set_otp_cooldown(email, timeout=180)  
            send_mail(
                subject="Core Fitness - Verify Your Email",
                message=f"Your new OTP for signup is: {new_otp}. It expires in 3 minutes.",
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
                fail_silently=False,
            )
            return JsonResponse({'success': True, 'message': 'New OTP sent to your email.'})
        except Exception as e:
            logger.error(f"Failed to resend OTP for signup: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Failed to resend OTP. Please try again.'}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)