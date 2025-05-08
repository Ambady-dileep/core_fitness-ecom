from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from decimal import Decimal, ROUND_UP
from datetime import timedelta
from django.db import transaction


User = get_user_model()

def default_valid_to():
    return timezone.now() + timedelta(days=30)

class Coupon(models.Model):
    code = models.CharField(max_length=50, unique=True)
    discount_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        validators=[MinValueValidator(0.01), MaxValueValidator(50.00)],
        help_text="Discount percentage (0.01-50)"
    )
    minimum_order_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00, 
        validators=[MinValueValidator(0.00)],
        help_text="Minimum order amount required to apply the coupon"
    )
    max_discount_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        validators=[MinValueValidator(0.00)],
        help_text="Maximum discount amount (0 means no cap)"
    )
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(default=default_valid_to)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.valid_to <= self.valid_from:
            raise ValidationError("Valid to date must be after valid from date")
        if self.discount_percentage <= 0:
            raise ValidationError("Discount percentage must be greater than 0")


    def is_valid(self):
        now = timezone.now()
        return self.is_active and self.valid_from <= now <= self.valid_to

    def is_expired(self):
        return timezone.now() > self.valid_to

    def deactivate_if_expired(self):
        if self.is_expired() and self.is_active:
            self.is_active = False
            self.save()
            return True
        return False

    def apply_to_subtotal(self, subtotal):
        if self.is_valid() and subtotal >= self.minimum_order_amount:
            discount = (self.discount_percentage / 100) * subtotal
            if self.max_discount_amount > 0 and discount > self.max_discount_amount:
                discount = self.max_discount_amount
            if discount > subtotal:
                discount = subtotal
            return round(subtotal - discount, 2), discount
        return subtotal, Decimal('0.00')

    def calculate_item_coupon_share(self, item_total, order_subtotal):
        """
        Calculate the portion of the coupon discount attributable to a specific item.
        Used for partial refunds: item_refund = item_total - (coupon_share * (item_total / order_subtotal)).
        """
        if not self.is_valid() or order_subtotal <= 0 or item_total <= 0:
            return Decimal('0.00')
        _, total_discount = self.apply_to_subtotal(order_subtotal)
        proportion = item_total / order_subtotal
        item_coupon_share = total_discount * proportion
        return item_coupon_share.quantize(Decimal('0.01'), rounding=ROUND_UP)

    def __str__(self):
        return self.code

class UserCoupon(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_coupons')
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='user_coupons')
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    order = models.ForeignKey('cart_and_orders_app.Order', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'coupon')
    
    def __str__(self):
        return f"{self.user.username} - {self.coupon.code}"

    def reset(self):
        self.is_used = False
        self.used_at = None
        self.order = None
        self.save()

    def clean(self):
        if self.coupon and not self.coupon.is_valid():
            raise ValidationError("Cannot assign an expired or inactive coupon.")

class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Wallet - Balance: {self.balance}"
    
    def add_funds(self, amount, description="Added funds"):
        amount = Decimal(amount)
        if amount <= 0:
            raise ValidationError("Amount must be greater than 0.")
        with transaction.atomic():
            self.balance += amount
            self.save()
            WalletTransaction.objects.create(
                wallet=self,
                amount=amount,
                transaction_type='CREDIT',
                description=description
            )

    def deduct_funds(self, amount, description="Payment deduction"):
        amount = Decimal(amount)
        if amount <= 0:
            raise ValidationError("Amount must be greater than 0.")
        if self.balance < amount:
            raise ValidationError("Insufficient wallet balance.")
        with transaction.atomic():
            self.balance -= amount
            self.save()
            WalletTransaction.objects.create(
                wallet=self,
                amount=amount,
                transaction_type='DEBIT',
                description=description
            )

    def add_refunded_funds(self, amount, description="Refund"):
        amount = Decimal(amount)
        if amount <= 0:
            raise ValidationError("Amount must be greater than 0.")
        with transaction.atomic():
            self.balance += amount
            self.save()
            WalletTransaction.objects.create(
                wallet=self,
                amount=amount,
                transaction_type='REFUND',
                description=description
            )

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
