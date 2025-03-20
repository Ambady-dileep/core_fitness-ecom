from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from product_app.models import ProductVariant
from user_app.models import CustomUser
from django.core.exceptions import ValidationError

User = get_user_model()

class Coupon(models.Model):
    code = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField()
    usage_limit = models.PositiveIntegerField(default=0)  # 0 means unlimited
    usage_count = models.PositiveIntegerField(default=0)
    minimum_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    applicable_products = models.ManyToManyField(ProductVariant, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  
    updated_at = models.DateTimeField(auto_now=True)      

    def get_discount_amount(self, total_price, cart_items):
        if total_price < self.minimum_order_amount or (self.usage_limit > 0 and self.usage_count >= self.usage_limit):
            return 0
        if self.applicable_products.exists():
            applicable_total = sum(item.quantity * (item.price or item.variant.price) 
                                  for item in cart_items if item.variant in self.applicable_products.all())
            return min(self.discount_amount, applicable_total)
        return min(self.discount_amount, total_price)

    def clean(self):
        """Validate model fields."""
        if self.discount_amount <= 0:
            raise ValidationError("Discount amount must be positive.")
        if self.minimum_order_amount < 0:
            raise ValidationError("Minimum order amount cannot be negative.")
        if self.valid_from >= self.valid_to:
            raise ValidationError("Valid from date must be earlier than valid to date.")
        if self.usage_limit < 0:
            raise ValidationError("Usage limit cannot be negative.")
        
    def apply_to_order(self, order):
        if not self.is_valid:
            raise ValidationError("Coupon is not valid.")
        total_price = order.get_total_price()
        discount = self.get_discount_amount(total_price, order.cart_items.all())
        if discount > 0:
            UserCoupon.objects.create(
                user=order.user,
                coupon=self,
                order=order,
                is_used=True
            )
            return discount
        return 0

    def save(self, *args, **kwargs):
        """Ensure code is uppercase and validate before saving."""
        self.code = self.code.upper()
        self.full_clean()  # Run validation
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        now = timezone.now()
        return (
            self.is_active and
            self.valid_from <= now <= self.valid_to and
            (self.usage_limit == 0 or self.usage_count < self.usage_limit)
        )

    def __str__(self):
        return self.code

    class Meta:
        verbose_name = "Coupon"
        verbose_name_plural = "Coupons"
        ordering = ['-created_at']  # Updated to use created_at

class UserCoupon(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='user_usages')
    coupon = models.ForeignKey('offer_and_coupon_app.Coupon', on_delete=models.SET_NULL, null=True, blank=True)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    order = models.ForeignKey('cart_and_orders_app.Order', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.coupon.code}"

    class Meta:
        unique_together = ('user', 'coupon')
        verbose_name = "User Coupon"
        verbose_name_plural = "User Coupons"
        ordering = ['-used_at', '-id']

class WalletTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('CREDIT', 'Credit'),
        ('DEBIT', 'Debit'),
    )
    wallet = models.ForeignKey('Wallet', on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  # Added back
    updated_at = models.DateTimeField(auto_now=True)      # Added back

    def __str__(self):
        return f"{self.transaction_type} of {self.amount} for {self.wallet.user.username}"

class Wallet(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='wallet',
        help_text="User who owns this wallet"
    )
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Current wallet balance"
    )
    created_at = models.DateTimeField(auto_now_add=True)  # Added back
    updated_at = models.DateTimeField(auto_now=True)      # Added back

    def add_funds(self, amount):
        """Add money to the wallet."""
        self.balance += amount
        self.save()
        WalletTransaction.objects.create(
            wallet=self,
            amount=amount,
            transaction_type='CREDIT',
            description='Refund from order cancellation'
        )

    def __str__(self):
        return f"{self.user.username}'s Wallet - {self.balance}"