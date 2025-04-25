from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import timedelta

User = get_user_model()

def default_valid_to():
    return timezone.now() + timedelta(days=30)

class Coupon(models.Model):
    code = models.CharField(max_length=50, unique=True)
    discount_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        validators=[MinValueValidator(0.01), MaxValueValidator(100.00)],
        help_text="Discount percentage (0.01-100)"
    )
    minimum_order_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00, 
        validators=[MinValueValidator(0.00)]
    )
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(default=default_valid_to)  
    usage_limit = models.PositiveIntegerField(default=0, help_text="0 means unlimited")
    usage_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.valid_to <= self.valid_from:
            raise ValidationError("Valid to date must be after valid from date")
        if self.discount_percentage <= 0:
            raise ValidationError("Discount percentage must be greater than 0")

    def is_valid(self):
        now = timezone.now()
        return (
            self.is_active and
            self.valid_from <= now <= self.valid_to and
            (self.usage_limit == 0 or self.usage_count < self.usage_limit)
        )

    def apply_to_subtotal(self, subtotal):
        if self.is_valid() and subtotal >= self.minimum_order_amount:
            discount = (self.discount_percentage / 100) * subtotal
            return round(subtotal - discount, 2), discount
        return subtotal, Decimal('0.00')

    def __str__(self):
        return self.code

class UserCoupon(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_coupons')
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='user_coupons', null=True, blank=True)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    order = models.ForeignKey('cart_and_orders_app.Order', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'coupon')

class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Wallet - Balance: {self.balance}"
    
    def add_funds(self, amount):
        self.balance += Decimal(amount)  
        self.save()

class WalletTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('CREDIT', 'Credit'),
        ('DEBIT', 'Debit'),
        ('REFUND', 'Refund'),
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    transaction_type = models.CharField(max_length=9, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.transaction_type} - {self.amount} - {self.created_at}"
