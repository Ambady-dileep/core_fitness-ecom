from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from datetime import datetime, timedelta
from django.core.exceptions import ValidationError
import re
from cloudinary.models import CloudinaryField
from django.conf import settings

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
        null=True, 
        blank=True,  
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

    is_blocked = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    login_attempts = models.IntegerField(default=0)
    last_login_attempt = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
        if self.is_superuser and not self.phone_number:
            self.phone_number = None
        self.email = self.email.lower()
        self.username = self.username.lower()
        super().save(*args, **kwargs)

    def check_login_attempts(self):
        if self.login_attempts >= 5:
            if self.last_login_attempt:
                block_duration = datetime.now() - self.last_login_attempt.replace(tzinfo=None)
                if block_duration < timedelta(minutes=15):
                    return False
                else:
                    self.login_attempts = 0
                    self.last_login_attempt = None
                    self.save()
        return True    


class Address(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='addresses')
    full_name = models.CharField(max_length=255)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    phone = models.CharField(
        max_length=10,
        validators=[RegexValidator(
            regex=r'^[6-9]\d{9}$',
            message="Phone number must be a valid 10-digit number starting with 6-9."
        )],
        blank=True,
        null=True
    )
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Addresses"

    def save(self, *args, **kwargs):
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).update(is_default=False)
        elif not self.pk and not Address.objects.filter(user=self.user).exists():
            self.is_default = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.address_line1}, {self.city}, {self.country}"


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


class Banner(models.Model):
    title = models.CharField(max_length=100)
    subtitle = models.CharField(max_length=200, blank=True, null=True)
    image = CloudinaryField('banner_image')
    url = models.URLField(blank=True, null=True, help_text="URL to link the banner to (optional)")
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0, help_text="Banners will be displayed in ascending order")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at']
        verbose_name = 'Banner'
        verbose_name_plural = 'Banners'

    def __str__(self):
        return self.title