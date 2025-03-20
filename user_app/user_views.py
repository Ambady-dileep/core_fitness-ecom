import logging
import re
from .forms import AddressForm, GenerateOTPForm, ValidateOTPForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.contrib import messages
from django.shortcuts import render, redirect
from .models import CustomUser as User
from django.views.decorators.http import require_POST
from .forms import UserProfileForm, ProfileForm
from django.views.decorators.http import require_http_methods
from .models import Address, UserProfile
from .forms import UserProfileForm, ProfileForm, CustomPasswordChangeForm
from django.conf import settings
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.views.decorators.cache import never_cache
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db.models import Q, Min
from django.http import JsonResponse
from cart_and_orders_app.models import Order  
from django.shortcuts import get_object_or_404
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from product_app.models import Product, Category
from .utils.otp_utils import generate_otp, store_otp, get_otp, delete_otp, set_otp_cooldown, get_otp_cooldown

logger = logging.getLogger(__name__)

@cache_control(no_cache=True, no_store=True, must_revalidate=True)
@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie  # Ensure CSRF token is set for AJAX calls
def user_login(request):
    """Handle user login functionality and provide context for OTP modal."""
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
    
    # Context for GET request to include OTP form
    context = {
        'generate_otp_form': GenerateOTPForm(),  # Pass form for modal
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
                'full_name': full_name
            }

            messages.success(request, "An OTP has been sent to your email. Please verify to complete signup.")
            return redirect('user_app:verify_otp_signup_page', email=email)

        except Exception as e:
            logger.error(f"Failed to send OTP during signup: {str(e)}", exc_info=True)
            messages.error(request, f"Failed to send OTP: {str(e)}. Please try again.")
            return render(request, 'signup_login.html', context)
    
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

# USER SIDE BELOW
@never_cache
@login_required
def user_home(request):
    if not request.user.is_authenticated:
        return redirect('user_login')
    
    category_id = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    brand = request.GET.get('brand')
    sort_by = request.GET.get('sort')
    search_query = request.GET.get('search')

    products = Product.objects.filter(
        variants__isnull=False
    ).annotate(
        lowest_price=Min('variants__price')
    ).distinct()

    if category_id:
        products = products.filter(category_id=category_id)
    if min_price and max_price:
        products = products.filter(lowest_price__gte=min_price, lowest_price__lte=max_price)
    elif min_price:
        products = products.filter(lowest_price__gte=min_price)
    elif max_price:
        products = products.filter(lowest_price__lte=max_price)
    if brand:
        products = products.filter(brand=brand)
    if search_query:
        products = products.filter(
            Q(product_name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )

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
    else:
        products = products.order_by('-created_at')

    categories = Category.objects.filter(is_active=True)
    brands = Product.objects.values_list('brand', flat=True).distinct()

    context = {
        'products': products.distinct(),
        'categories': categories,
        'brands': brands,
        'selected_category': category_id,
        'min_price': min_price,
        'max_price': max_price,
        'selected_brand': brand,
        'sort_by': sort_by,
        'search_query': search_query,
    }
    return render(request, 'user_home.html', context)

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
    return render(request, 'user_profile.html', context)

@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
@require_http_methods(["GET", "POST"])

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
    """Edit an address via AJAX."""
    address = Address.objects.get(id=address_id, user=request.user)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        if request.method == 'GET':
            return JsonResponse({
                'success': True,
                'address': {
                    'full_name': address.full_name,
                    'address_line1': address.address_line1,
                    'address_line2': address.address_line2 or '',
                    'city': address.city,
                    'state': address.state,
                    'postal_code': address.postal_code,
                    'country': address.country,
                    'is_default': address.is_default,
                }
            })
        elif request.method == 'POST':
            form = AddressForm(request.POST, instance=address)
            if form.is_valid():
                address = form.save()
                return JsonResponse({
                    'success': True,
                    'message': 'Address updated successfully!',
                    'address': {
                        'id': address.id,
                        'full_name': address.full_name,
                        'address_line1': address.address_line1,
                        'address_line2': address.address_line2 or '',
                        'city': address.city,
                        'state': address.state,
                        'postal_code': address.postal_code,
                        'country': address.country,
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
def delete_address(request, address_id):
    """Delete an address."""
    address = Address.objects.get(id=address_id, user=request.user)
    if request.method == 'POST':
        address.delete()
        return_url = request.GET.get('next', reverse('user_app:my_profile'))
        return redirect(return_url)
    return redirect('user_app:my_profile')

@login_required
@require_POST
def set_default_address(request, address_id):
    address = get_object_or_404(Address, id=address_id, user=request.user)
    Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
    address.is_default = True
    address.save()
    messages.success(request, "Default address updated successfully!")
    return redirect('user_app:my_profile')

@login_required
def user_address_list(request):
    """Redirect to profile page since addresses are displayed there."""
    return redirect('user_app:my_profile')

@require_http_methods(["POST"])
def generate_and_send_otp(request):
    """Generate and send OTP via AJAX for password reset."""
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
    """Validate OTP via AJAX and redirect to password reset page."""
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
    """Resend OTP via AJAX."""
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
    """Handle password reset confirmation after OTP validation."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            new_password1 = request.POST.get('new_password1')
            new_password2 = request.POST.get('new_password2')

            # Password validation (consistent with user_signup)
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

            # Re-render form with errors
            return render(request, 'password_reset_confirm.html', {
                'validlink': True,
                'uidb64': uidb64,
                'token': token,
            })

        # GET request: Show the password reset form
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
    """Render the OTP verification page for signup."""
    logger.info(f"Accessing verify_otp_signup_page for email: {email}")
    
    try:
        # Check if signup data exists in the session
        if 'signup_data' not in request.session:
            logger.warning("Session expired: 'signup_data' not found in session")
            messages.error(request, 'Session expired. Please sign up again.')
            return redirect('user_app:user_signup')

        # Ensure the email matches the one in the session
        signup_data = request.session['signup_data']
        logger.debug(f"Session signup_data: {signup_data}")
        if signup_data.get('email') != email:
            logger.warning(f"Email mismatch: session email={signup_data.get('email')}, URL email={email}")
            messages.error(request, 'Invalid email. Please sign up again.')
            return redirect('user_app:user_signup')

        # Render the OTP verification page
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
    """Verify OTP for signup and create user account if valid."""
    if request.method == 'POST':
        email = request.POST.get('email')
        user_otp = request.POST.get('otp')

        # Check if signup data exists in the session and matches the email
        signup_data = request.session.get('signup_data')
        if not signup_data or signup_data.get('email') != email:
            messages.error(request, 'Invalid session or email. Please sign up again.')
            return redirect('user_app:user_signup')

        # Validate OTP
        stored_otp = get_otp(email)
        try:
            if stored_otp and int(user_otp) == stored_otp:
                # OTP is valid, create the user
                try:
                    user = User.objects.create_user(
                        username=signup_data['username'],
                        email=signup_data['email'],
                        phone_number=signup_data['phone_number'],
                        password=signup_data['password'],
                        full_name=signup_data['full_name']
                    )
                    user.is_active = True
                    user.is_verified = True  # Mark as verified since OTP is confirmed
                    user.save()

                    # Log the user in
                    authenticated_user = authenticate(request, username=signup_data['username'], password=signup_data['password'])
                    if authenticated_user:
                        login(request, authenticated_user)

                    # Clean up: delete OTP and session data
                    delete_otp(email)
                    del request.session['signup_data']

                    messages.success(request, "Account created successfully! Welcome to Core Fitness.")
                    return redirect('user_app:user_home')
                except Exception as e:
                    logger.error(f"Error creating user after OTP verification: {str(e)}")
                    messages.error(request, "An error occurred while creating your account. Please try again.")
                    return redirect('user_app:user_signup')
            else:
                messages.error(request, "Invalid or expired OTP. Please try again.")
                return redirect('user_app:verify_otp_signup_page', email=email)
        except ValueError:
            messages.error(request, "OTP must be a number.")
            return redirect('user_app:verify_otp_signup_page', email=email)

    return redirect('user_app:user_signup')


@require_http_methods(["POST"])
def resend_otp_signup(request):
    """Resend OTP via AJAX for signup verification."""
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        email = request.POST.get('email')
        if not email:
            return JsonResponse({'success': False, 'error': 'No email provided.'}, status=400)

        # Check if signup data exists in the session and matches the email
        signup_data = request.session.get('signup_data')
        if not signup_data or signup_data.get('email') != email:
            return JsonResponse({'success': False, 'error': 'Invalid session or email. Please sign up again.'}, status=400)

        # Check OTP cooldown
        if get_otp_cooldown(email):
            return JsonResponse({'success': False, 'error': 'Please wait 3 minutes before resending.'}, status=429)

        try:
            # Generate and store new OTP
            new_otp = generate_otp()
            store_otp(email, new_otp, timeout=180)  # Store OTP for 3 minutes
            set_otp_cooldown(email, timeout=180)  # Set cooldown for 3 minutes

            # Send new OTP via email
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