import random
from django.core.cache import cache

def generate_otp():
    """Generate a 6-digit OTP."""
    return random.randint(100000, 999999)

def store_otp(email_or_phone, otp, timeout=120):
    """Store the OTP in Redis with a timeout (default: 120 seconds)."""
    cache.set(f"otp:{email_or_phone}", otp, timeout=timeout)

def get_otp(email_or_phone):
    """Retrieve the OTP from Redis."""
    return cache.get(f"otp:{email_or_phone}")

def delete_otp(email_or_phone):
    """Delete the OTP from Redis after successful validation."""
    cache.delete(f"otp:{email_or_phone}")

def set_otp_cooldown(email_or_phone, timeout=120):
    """Set a cooldown period for resending OTP."""
    cache.set(f"otp_cooldown:{email_or_phone}", "active", timeout=timeout)

def get_otp_cooldown(email_or_phone):
    """Check if a cooldown is active for this email/phone."""
    return cache.get(f"otp_cooldown:{email_or_phone}")


from django.contrib.auth import get_user_model

User = get_user_model()

def reuse_existing_user(strategy, details, backend, user=None, *args, **kwargs):
    """
    Custom pipeline step to reuse an existing user if their email already exists.
    """
    email = details.get('email')
    if not email:
        return  # No email provided, let the pipeline continue

    # Normalize email to match your model's behavior
    email = email.lower()

    # Check if a user with this email already exists
    try:
        existing_user = User.objects.get(email=email)
        if user and user != existing_user:
            # If a different user is already authenticated, handle this case (optional)
            return {'user': existing_user, 'is_new': False}
        if not user:
            # No user is currently authenticated, reuse the existing one
            return {'user': existing_user, 'is_new': False}
    except User.DoesNotExist:
        # No existing user, proceed with creating a new one
        return