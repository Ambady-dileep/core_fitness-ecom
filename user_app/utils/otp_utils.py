import random
from django.core.cache import cache

def generate_otp():
    """Generate a 6-digit OTP."""
    return random.randint(100000, 999999)

def store_otp(email_or_phone, otp, timeout=180):
    """Store the OTP in Redis with a timeout (default: 3 minutes)."""
    cache.set(f"otp:{email_or_phone}", otp, timeout=timeout)

def get_otp(email_or_phone):
    """Retrieve the OTP from Redis."""
    return cache.get(f"otp:{email_or_phone}")

def delete_otp(email_or_phone):
    """Delete the OTP from Redis after successful validation."""
    cache.delete(f"otp:{email_or_phone}")

def set_otp_cooldown(email_or_phone, timeout=180): 
    """Set a cooldown period for resending OTP."""
    cache.set(f"otp_cooldown:{email_or_phone}", "active", timeout=timeout)

def get_otp_cooldown(email_or_phone):
    """Check if a cooldown is active for this email/phone."""
    return cache.get(f"otp_cooldown:{email_or_phone}")