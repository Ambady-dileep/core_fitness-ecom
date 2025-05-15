import logging
import re
from .forms import AddressForm, GenerateOTPForm, ValidateOTPForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.contrib import messages
from django.db.models import Q
from product_app.models import Product, Category
from django.shortcuts import render, redirect, get_object_or_404
from .models import CustomUser as User
from decimal import Decimal
from django.db import transaction
from user_app.models import UserProfile, Referral
from django.views.decorators.http import require_POST, require_http_methods
from .models import Address
from .forms import UserProfileForm, ProfileForm, CustomPasswordChangeForm, CustomUserCreationForm
from .models import Banner
from django.conf import settings
from offer_and_coupon_app.models import Wallet, WalletTransaction
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from product_app.models import Product, Category, Review
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.http import JsonResponse
from cart_and_orders_app.models import Order
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.cache import cache_control,never_cache
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
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        try:
            user = User.objects.get(username=username)
            
            if hasattr(user, 'userprofile') and user.userprofile.is_blocked:
                error_message = "Your account has been blocked. Please contact support."
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_message})
                messages.error(request, error_message)
                return render(request, 'signup_login.html')
            
            if hasattr(user, 'check_login_attempts') and not user.check_login_attempts():
                error_message = "Too many failed attempts. Please try again after 15 minutes."
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_message})
                messages.error(request, error_message)
                return render(request, 'signup_login.html')
            
            authenticated_user = authenticate(request, username=username, password=password)
            
            if authenticated_user:
                login(request, authenticated_user)
                if hasattr(user, 'login_attempts'):
                    user.login_attempts = 0
                    user.save()
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'redirect_url': reverse('user_app:user_home')
                    })
                return redirect('user_app:user_home')
            else:
                if hasattr(user, 'login_attempts'):
                    user.login_attempts += 1
                    user.save()
                error_message = "Invalid username or password."
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_message})
                messages.error(request, error_message)
                
        except User.DoesNotExist:
            error_message = "Invalid username or password."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
    
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
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')
        full_name = request.POST.get('full_name', '').strip()
        referral_code = request.POST.get('referral_code', request.session.get('referral_code', '')).strip().upper()

        logger.debug(f"Received signup form data: username={username}, email={email}, phone_number={phone_number}, full_name={full_name}, referral_code={referral_code}")

        context['form_data'] = {
            'username': username,
            'email': email,
            'phone_number': phone_number,
            'full_name': full_name,
            'referral_code': referral_code
        }
        
        # Validation checks
        if not username or len(username) < 3 or len(username) > 20 or not username.isalnum():
            error_message = "Username must be 3-20 characters long and alphanumeric."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
            return render(request, 'signup_login.html', context)
        
        try:
            validate_email(email)
        except ValidationError:
            error_message = "Please enter a valid email address."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
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
            error_message = "Password must be 8+ characters with uppercase, lowercase, number, and special character."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
            return render(request, 'signup_login.html', context)
        
        # Check if password is too similar to username
        if username.lower() in password1.lower() or password1.lower() in username.lower():
            error_message = "The password is too similar to the username."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
            return render(request, 'signup_login.html', context)
        
        if not re.match(r'^[6-9]\d{9}$', phone_number):
            error_message = "Invalid phone number. Must be 10 digits starting with 6-9."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
            return render(request, 'signup_login.html', context)
        
        # Check for existing users
        if User.objects.filter(Q(username__iexact=username) | 
                              Q(email__iexact=email) | 
                              Q(phone_number=phone_number)).exists():
            error_message = "Username, email, or phone number already exists."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
            return render(request, 'signup_login.html', context)
        
        stored_otp = get_otp(email)
        if stored_otp and 'signup_data' in request.session and request.session['signup_data'].get('email') == email:
            error_message = "A signup process is already in progress for this email. Please verify the OTP or wait 1.5 minutes to try again."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
            return render(request, 'signup_login.html', context)

        # Generate and send OTP
        if get_otp_cooldown(email):
            error_message = "Please wait 1.5 minutes before requesting a new OTP."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
            return render(request, 'signup_login.html', context)

        try:
            logger.debug("Generating OTP...")
            otp = generate_otp()
            logger.debug(f"Generated OTP: {otp}")

            logger.debug("Storing OTP...")
            store_otp(email, otp, timeout=90)  
            logger.debug("OTP stored successfully")

            logger.debug("Setting OTP cooldown...")
            set_otp_cooldown(email, timeout=90)  
            logger.debug("OTP cooldown set successfully")

            logger.info(f"Attempting to send OTP to {email} with OTP: {otp}")
            logger.debug(f"Email settings: EMAIL_HOST={settings.EMAIL_HOST}, EMAIL_PORT={settings.EMAIL_PORT}, EMAIL_HOST_USER={settings.EMAIL_HOST_USER}")

            send_mail(
                subject="Core Fitness - Verify Your Email",
                message=f"Your OTP for signup is: {otp}. It expires in 1.5 minutes.",
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

            success_message = "An OTP has been sent to your email. Please verify to complete signup."
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': success_message,
                    'redirect_url': reverse('user_app:verify_otp_signup_page', kwargs={'email': email})
                })
            messages.success(request, success_message)
            return redirect('user_app:verify_otp_signup_page', email=email)

        except Exception as e:
            logger.error(f"Failed to send OTP during signup: {str(e)}", exc_info=True)
            error_message = f"Failed to send OTP: {str(e)}. Please try again."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
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
@csrf_protect
def change_password(request):
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        form = CustomPasswordChangeForm(user=request.user, data=request.POST)
        
        if form.is_valid():
            try:
                form.save()
                update_session_auth_hash(request, form.user)
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'message': 'Your password was successfully updated!'
                    })
                messages.success(request, "Your password was successfully updated!")
                return redirect('user_app:my_profile')
            except Exception as e:
                logger.error(f"Error saving new password for user {request.user.username}: {str(e)}")
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'message': 'An error occurred while updating your password.'
                    }, status=500)
                messages.error(request, "An error occurred while updating your password.")
                return redirect('user_app:my_profile')
        else:
            errors = {}
            for field, error_list in form.errors.items():
                errors[field] = error_list[0] if isinstance(error_list, list) else error_list
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'errors': errors,
                    'message': 'Please correct the errors below.'
                }, status=400)
            for error in errors.values():
                messages.error(request, error)
            return redirect('user_app:my_profile')
    
    return redirect('user_app:my_profile')


@login_required 
def user_home(request):
    print("Authenticated user:", request.user)
    # Fetch active banners
    banners = Banner.objects.filter(is_active=True)

    # Fetch active categories
    categories = Category.objects.filter(is_active=True)

    # Helper function to annotate products with price and discount
    def annotate_products(products):
        annotated_products = []
        for product in products:
            primary_variant = product.primary_variant
            if primary_variant and primary_variant.is_active:
                best_price_info = primary_variant.best_price
                original_price = best_price_info['original_price']
                sales_price = best_price_info['price']
                # Calculate discount percentage
                if original_price > sales_price:
                    discount = ((original_price - sales_price) / original_price * 100).quantize(Decimal('1'))
                else:
                    discount = Decimal('0')
                annotated_products.append({
                    'product': product,
                    'sales_price': sales_price,
                    'original_price': original_price,
                    'discount': discount
                })
            else:
                # Skip products without active primary variants
                continue
        return annotated_products

    # Fetch featured products, ensuring category and brand are active
    featured_products = Product.objects.filter(
        is_active=True,
        variants__is_active=True,
        category__is_active=True,
        brand__is_active=True
    ).distinct()[:8]
    featured_products = annotate_products(featured_products)

    # Fetch new arrivals, ensuring category and brand are active
    new_arrivals = Product.objects.filter(
        is_active=True,
        variants__is_active=True,
        category__is_active=True,
        brand__is_active=True
    ).order_by('-created_at').distinct()[:8]
    new_arrivals = annotate_products(new_arrivals)

    context = {
        'banners': banners,
        'categories': categories,
        'featured_products': featured_products,
        'new_arrivals': new_arrivals,
    }
    return render(request, 'user_app/user_home.html', context)

def about_us(request):
    return render(request, 'about_us.html')

def privacy_policy(request):
    return render(request, 'privacy_policy.html')

def faq(request):
    return render(request, 'faq.html')

@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def my_profile(request):
    """Display user profile with orders and addresses."""
    print("helo")
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
    profile = getattr(user, 'profile', None)

    if request.method == 'POST':
        user_form = UserProfileForm(request.POST, instance=user)
        profile_form = ProfileForm(request.POST, request.FILES, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile = profile_form.save(commit=False)
            profile.user = user
            profile.save()
            return JsonResponse({
                'success': True,
                'message': 'Profile updated successfully',
                'profile_image_url': profile.profile_image.url if profile.profile_image else None
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
        logger.debug(f"Received OTP generation request: {request.POST}")
        if form.is_valid():
            email = form.cleaned_data['email']
            logger.debug(f"Valid email: {email}")
            if get_otp_cooldown(email):
                logger.warning(f"Cooldown active for {email}")
                return JsonResponse(
                    {'success': False, 'error': 'Please wait 120 seconds before requesting a new OTP.'},
                    status=429
                )
            try:
                user = User.objects.get(email=email)
                logger.debug(f"User found: {user.username}")
                # Delete any existing OTP to invalidate it
                delete_otp(email)
                otp = generate_otp()
                logger.debug(f"Generated OTP: {otp}")
                store_otp(email, otp, timeout=120)
                set_otp_cooldown(email, timeout=120)
                logger.debug(f"OTP stored in Redis for {email}")
                send_mail(
                    subject="Your OTP for Password Reset",
                    message=f"Your OTP for resetting your password is: {otp}. It expires in 2 minutes.",
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[email],
                    fail_silently=False,
                )
                logger.info(f"OTP email sent to {email}")
                return JsonResponse({
                    'success': True,
                    'message': 'OTP sent to your email.',
                    'next_step': 'validate_otp',  # Indicate next step
                    'email': email  # Pass email for frontend to use in OTP validation
                })
            except User.DoesNotExist:
                logger.error(f"No user found for email: {email}")
                return JsonResponse({'success': False, 'error': 'No account found with this email.'})
            except Exception as e:
                logger.error(f"Failed to send OTP for {email}: {str(e)}", exc_info=True)
                return JsonResponse(
                    {'success': False, 'error': f'Failed to send OTP: {str(e)}'},
                    status=500
                )
        logger.warning(f"Invalid form data: {form.errors}")
        return JsonResponse(
            {'success': False, 'error': form.errors.get('email', ['Invalid email format.'])[0]},
            status=400
        )
    logger.error("Invalid request: Not an AJAX request")
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
            logger.warning("Resend OTP: No email provided")
            return JsonResponse({'success': False, 'error': 'No email provided.'}, status=400)
        if get_otp_cooldown(email):
            logger.info(f"Cooldown active for {email}")
            return JsonResponse(
                {'success': False, 'error': 'Please wait 120 seconds before resending.'},
                status=429
            )
        try:
            user = User.objects.get(email=email)
            new_otp = generate_otp()
            logger.debug(f"Generated new OTP for resend: {new_otp}")
            store_otp(email, new_otp, timeout=120)  # Update to 120 seconds
            set_otp_cooldown(email, timeout=120)  # Update to 120 seconds
            send_mail(
                subject="Your New OTP for Password Reset",
                message=f"Your new OTP for resetting your password is: {new_otp}. It expires in 2 minutes.",
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[email],
                fail_silently=False,
            )
            logger.info(f"Resend OTP email sent successfully to {email}")
            return JsonResponse({'success': True, 'message': 'New OTP sent to your email.'})
        except User.DoesNotExist:
            logger.warning(f"No user found for email: {email}")
            return JsonResponse({'success': False, 'error': 'No account found with this email.'})
        except Exception as e:
            logger.error(f"Failed to resend OTP for {email}: {str(e)}", exc_info=True)
            return JsonResponse(
                {'success': False, 'error': 'Failed to resend OTP. Please try again.'},
                status=500
            )
    logger.warning("Invalid request: Not an AJAX request")
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)



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
            errors = {}

            # Validate new_password1
            if not new_password1:
                errors['new_password1'] = 'Password is required.'
            elif len(new_password1) < 8:
                errors['new_password1'] = 'Password must be at least 8 characters.'
            elif not re.search(r'[A-Z]', new_password1):
                errors['new_password1'] = 'Password must contain at least one uppercase letter.'
            elif not re.search(r'[a-z]', new_password1):
                errors['new_password1'] = 'Password must contain at least one lowercase letter.'
            elif not re.search(r'\d', new_password1):
                errors['new_password1'] = 'Password must contain at least one number.'
            elif not re.search(r'[!@#$%^&*()+\-_=\[\]{};:\'",.<>?]', new_password1):
                errors['new_password1'] = 'Password must contain at least one special character.'

            # Validate new_password2
            if not new_password2:
                errors['new_password2'] = 'Please confirm your password.'
            elif new_password1 and new_password2 and new_password1 != new_password2:
                errors['new_password2'] = 'Passwords do not match.'

            if errors:
                return render(request, 'password_reset.html', {
                    'validlink': True,
                    'uidb64': uidb64,
                    'token': token,
                    'errors': errors
                })

            # If validation passes, set the new password
            user.set_password(new_password1)
            user.save()
            return redirect('user_app:user_login')  # Redirect to login page after success
        else:
            return render(request, 'password_reset.html', {
                'validlink': True,
                'uidb64': uidb64,
                'token': token
            })
    else:
        return render(request, 'password_reset.html', {'validlink': False})


@require_http_methods(["GET", "POST"])
def verify_otp_signup_page(request, email):
    if request.user.is_authenticated:
        return redirect('user_app:user_home')
    
    signup_data = request.session.get('signup_data')
    if not signup_data or signup_data.get('email') != email:
        messages.error(request, "Invalid signup session or email.")
        return redirect('user_app:user_signup')
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if request.method == 'POST':
        user_otp = request.POST.get('otp')
        stored_otp = get_otp(email)
        
        if not stored_otp:
            error_message = "OTP has expired. Please request a new one."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
            return render(request, 'otp_verification.html', {'email': email})
        
        try:
            if int(user_otp) == stored_otp:
                try:
                    with transaction.atomic():
                        # Create user
                        user = User.objects.create_user(
                            username=signup_data['username'],
                            email=signup_data['email'],
                            password=signup_data['password'],
                            full_name=signup_data['full_name'],
                            phone_number=signup_data['phone_number'],
                            is_verified=True
                        )
                        
                        # Create user profile
                        UserProfile.objects.create(user=user)
                        
                        # Create user wallet
                        wallet = Wallet.objects.create(user=user)
                        
                        # Handle referral if code provided
                        referral_code = signup_data.get('referral_code')
                        if referral_code:
                            try:
                                referrer = User.objects.get(referral_code=referral_code, is_active=True, is_blocked=False)
                                if referrer == user:
                                    raise ValidationError("Cannot use own referral code.")
                                apply_referral_bonuses(referrer, user)
                            except (User.DoesNotExist, ValidationError) as e:
                                logger.warning(f"Invalid referral code {referral_code} during signup: {str(e)}")
                                messages.warning(request, "Referral code is invalid, but your account was created.")
                
                    # Clean up
                    delete_otp(email)
                    if 'signup_data' in request.session:
                        del request.session['signup_data']
                    if 'referral_code' in request.session:
                        del request.session['referral_code']
                
                    # Log in user
                    user = authenticate(request, username=signup_data['username'], password=signup_data['password'])
                    if user:
                        login(request, user)
                
                    success_message = "Account created successfully!"
                    if is_ajax:
                        return JsonResponse({'success': True, 'redirect': reverse('user_app:user_home')})
                    messages.success(request, success_message)
                    return redirect('user_app:user_home')
                
                except Exception as e:
                    logger.error(f"Error creating user: {str(e)}", exc_info=True)
                    error_message = "An error occurred during account creation. Please try again."
                    if is_ajax:
                        return JsonResponse({'success': False, 'error': error_message})
                    messages.error(request, error_message)
                    return render(request, 'otp_verification.html', {'email': email})
            else:
                error_message = "Invalid OTP. Please try again."
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_message})
                messages.error(request, error_message)
        except ValueError:
            error_message = "OTP must be a number."
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_message})
            messages.error(request, error_message)
    
    return render(request, 'otp_verification.html', {'email': email})


def get_referral_transactions(user, page_number):
    """
    Fetch paginated referral-related transactions for the user's wallet.
    Returns a paginated queryset of transactions with 'Referral bonus' or 'Welcome bonus' in description.
    """
    try:
        wallet, _ = Wallet.objects.get_or_create(user=user)
        transactions = WalletTransaction.objects.filter(
            Q(description__icontains='Referral bonus') | Q(description__icontains='Welcome bonus'),
            wallet=wallet
        ).order_by('-created_at')
        
        paginator = Paginator(transactions, 10)  # 10 transactions per page
        page_obj = paginator.get_page(page_number)
        return page_obj
    except Exception as e:
        logger.error(f"Error fetching referral transactions for user {user.username}: {str(e)}")
        return None

@login_required
def referral_dashboard(request):
    referral_code = request.user.referral_code
    referral_url = request.build_absolute_uri(
        reverse('user_app:referral_link', kwargs={'referral_code': referral_code})
    )
    
    referrals = Referral.objects.filter(referrer=request.user).select_related('referred_user')
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    
    # Get paginated referral transactions
    page_number = request.GET.get('page')
    page_obj = get_referral_transactions(request.user, page_number)
    
    context = {
        'referral_code': referral_code,
        'referral_url': referral_url,
        'referrals': referrals,
        'wallet': wallet,
        'transactions': page_obj,
        'page_obj': page_obj,
    }
    
    return render(request, 'user_app/referral_dashboard.html', context)



def referral_link(request, referral_code):
    """Store the referral code in session and redirect to signup page"""
    try:
        referrer = User.objects.get(referral_code=referral_code, is_active=True, is_blocked=False)
        request.session['referral_code'] = referral_code
        if request.user.is_authenticated:
            messages.info(request, "You are already logged in. Referral codes can only be used when signing up.")
            return redirect('user_app:user_home')
        messages.info(request, "You're signing up with a referral. Both you and your friend will receive bonuses!")
        return redirect('user_app:user_signup')
    except User.DoesNotExist:
        messages.error(request, "Invalid or inactive referral code.")
        return redirect('user_app:user_signup')

def ensure_wallet_exists(user):
    """Ensure the user has a wallet, creating one if necessary"""
    wallet, created = Wallet.objects.get_or_create(user=user)
    return wallet

def apply_referral_bonuses(referrer, referred_user):
    """Apply referral bonuses to both referrer and referred user"""
    from decimal import Decimal
    
    with transaction.atomic():
        # Get or create wallets for both users
        referrer_wallet = ensure_wallet_exists(referrer)
        referred_wallet = ensure_wallet_exists(referred_user)
        
        # Add 200 rupees to referrer's wallet
        referrer_wallet.add_funds(
            Decimal('200.00'), 
            f"Referral bonus for {referred_user.username} signup"
        )
        
        # Add 100 rupees to referred user's wallet
        referred_wallet.add_funds(
            Decimal('100.00'),
            f"Welcome bonus from referral by {referrer.username}"
        )
        
        # Get or create referral record
        referral, created = Referral.objects.get_or_create(
            referrer=referrer,
            referred_user=referred_user,
            defaults={
                'referrer_rewarded': True,
                'referred_rewarded': True
            }
        )
        
        # If not created, update the reward status
        if not created:
            referral.referrer_rewarded = True
            referral.referred_rewarded = True
            referral.save()
        
        return True

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
                    
                    # Clear session data after successful user creation
                    del request.session['signup_data']
                    if 'referral_code' in request.session:
                        del request.session['referral_code']
                    
                    authenticated_user = authenticate(request, username=signup_data['username'], password=signup_data['password'])
                    if authenticated_user:
                        login(request, authenticated_user)
                        
                    messages.success(request, "Account created successfully! Welcome to Core Fitness.")
                    return redirect('user_app:user_home')
                else:
                    # Instead of showing form errors on OTP page, redirect back to signup with errors
                    for field, errors in form.errors.items():
                        for error in errors:
                            messages.error(request, f"{field}: {error}")
                    
                    # Preserve form data for repopulating the signup form
                    request.session['form_data'] = {
                        'username': signup_data['username'],
                        'email': signup_data['email'],
                        'phone_number': signup_data['phone_number'],
                        'full_name': signup_data['full_name'],
                        'referral_code': signup_data.get('referral_code', '')
                    }
                    
                    # Clean up OTP and signup data
                    del request.session['signup_data']
                    
                    return redirect('user_app:user_signup')
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


@require_POST
def verify_referral_code(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        referral_code = request.POST.get('referral_code', '').strip().upper()
        if not referral_code:
            return JsonResponse({'success': False, 'error': 'Referral code is required.'}, status=400)
        
        if not re.match(r'^[A-Z0-9]{8}$', referral_code):
            return JsonResponse({'success': False, 'error': 'Referral code must be 8 alphanumeric characters.'}, status=400)
        
        try:
            referrer = User.objects.get(referral_code=referral_code, is_active=True, is_blocked=False)
            # Prevent self-referral by checking email if signup data exists
            signup_data = request.session.get('signup_data', {})
            if signup_data.get('email', '').lower() == referrer.email.lower():
                return JsonResponse({'success': False, 'error': 'You cannot use your own referral code.'}, status=400)
            return JsonResponse({'success': True, 'message': 'Valid referral code!'})
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Invalid or inactive referral code.'}, status=400)
        except Exception as e:
            logger.error(f"Error verifying referral code {referral_code}: {str(e)}", exc_info=True)
            return JsonResponse({'success': False, 'error': 'An error occurred while verifying the referral code.'}, status=500)
    
    return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

