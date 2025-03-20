from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from datetime import datetime, timedelta
from django.core.exceptions import ValidationError
import re
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

def validate_full_name(value):
    if not value:
        raise ValidationError("Full name is required.")
    
    if len(value.strip()) < 4:
        raise ValidationError("Full name must be at least 4 characters long.")
    
    if not re.match(r'^[a-zA-Z\s]*$', value):
        raise ValidationError("Full name can only contain letters and spaces.")
    
    if len(value.split()) < 2:
        raise ValidationError("Please provide both first and last name.")

class CustomUser(AbstractUser):
    full_name = models.CharField(
        max_length=255,
        validators=[validate_full_name],
        help_text="Enter your full name (first and last name)",
        null=True, 
        blank=True,
        db_index=True
    )
    
    email = models.EmailField(
        unique=True,
        error_messages={
            'unique': "A user with this email already exists.",
        }
    )
    
    phone_regex = RegexValidator(
        regex=r'^[6-9]\d{9}$',
        message="Phone number must be a valid 10-digit number starting with 6-9."
    )
    
    phone_number = models.CharField(
        validators=[phone_regex],
        max_length=10,
        unique=True,
        error_messages={
            'unique': "This phone number is already registered.",
        },
        null=True,  # Allow null for superuser
        blank=True,  # Allow blank in forms
        db_index=True
    )

    username = models.CharField(
        max_length=30,
        unique=True,
        validators=[
            RegexValidator(
                regex='^[a-zA-Z0-9._]+$',
                message='Username can only contain letters, numbers, dots and underscores'
            ),
        ],
        error_messages={
            'unique': "This username is already taken.",
        },
        db_index=True
    )

    # Status fields
    is_blocked = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    
    
    # Timestamp fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Login attempt tracking
    last_login_attempt = models.DateTimeField(null=True, blank=True)
    login_attempts = models.IntegerField(default=0)

    # Override the default groups field
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_users',
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )

    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_users',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )

    class Meta:
        db_table = 'custom_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.username} - {self.full_name or 'No name'}"

    def save(self, *args, **kwargs):
        # Allow superuser to be created without phone number
        if self.is_superuser and not self.phone_number:
            self.phone_number = None
        # Ensure email and username are lowercase
        self.email = self.email.lower()
        self.username = self.username.lower()
        super().save(*args, **kwargs)

    def check_login_attempts(self):
        """
        Check if user can attempt login or is temporarily blocked
        Returns True if user can attempt login, False otherwise
        """
        if self.login_attempts >= 5:
            if self.last_login_attempt:
                block_duration = datetime.now() - self.last_login_attempt.replace(tzinfo=None)
                if block_duration < timedelta(minutes=15):
                    return False
                else:
                    # Reset attempts after 15 minutes
                    self.login_attempts = 0
                    self.last_login_attempt = None
                    self.save()
        return True

    def increment_login_attempts(self):
        """
        Increment the number of failed login attempts
        """
        self.login_attempts += 1
        self.last_login_attempt = datetime.now()
        self.save()

    def reset_login_attempts(self):
        """
        Reset login attempts after successful login
        """
        self.login_attempts = 0
        self.last_login_attempt = None
        self.save()


class Address(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='addresses')
    full_name = models.CharField(max_length=255)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Addresses"

    def save(self, *args, **kwargs):
        # If this is marked as default, unmark all other addresses
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).update(is_default=False)
        # If this is the first address, mark it as default
        elif not self.pk and not Address.objects.filter(user=self.user).exists():
            self.is_default = True
        super().save(*args, **kwargs)
            
    def __str__(self):
        return f"{self.address_line1}, {self.city}, {self.country}"

class LoginAttempt(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'login_attempts'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.username} - {'Success' if self.success else 'Failed'}"


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    is_blocked = models.BooleanField(default=False)
    profile_image = models.ImageField(upload_to='profile_images/', null=True, blank=True)
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

@receiver(post_save, sender=CustomUser)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created: 
        UserProfile.objects.create(user=instance)
    elif hasattr(instance, 'profile'):
        instance.profile.save()