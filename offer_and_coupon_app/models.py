from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from product_app.models import Product, Category, ProductVariant
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from decimal import Decimal
from django.dispatch import receiver

User = get_user_model()

def get_default_valid_to():
    return timezone.now() + timezone.timedelta(days=30)

class Offer(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    discount_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0.01), MaxValueValidator(100.0)],
        help_text="Percentage discount (0.01-100)"
    )
    min_purchase_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        validators=[MinValueValidator(0.00)]
    )
    max_discount_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        blank=True, 
        null=True,
        validators=[MinValueValidator(0.01)],
        help_text="Maximum discount amount when using percentage discount"
    )
    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True
    
    def clean(self):
        if self.valid_from >= self.valid_to:
            raise ValidationError("Start date must be before end date")
        
        if self.discount_value <= 0 or self.discount_value > 100:
            raise ValidationError("Percentage discount must be between 0.01 and 100")
            
    def is_valid(self):
        now = timezone.now()
        return self.is_active and self.valid_from <= now <= self.valid_to
        
    def calculate_discount(self, amount):
        if amount < self.min_purchase_amount:
            return Decimal('0.00')
        
        discount = (self.discount_value / 100) * amount
        if self.max_discount_amount:
            return min(discount, self.max_discount_amount)
        return discount
    
    def __str__(self):
        return self.name

class ProductOffer(Offer):
    products = models.ManyToManyField(
        Product, 
        related_name='product_offers',
        help_text="Products this offer applies to"
    )
    
    def apply_to_product(self, product, price):
        if not self.is_valid() or product not in self.products.all() or price < self.min_purchase_amount:
            return price, Decimal('0.00')
        discount = price * (self.discount_value / 100)
        if self.max_discount_amount:
            discount = min(discount, self.max_discount_amount)
        discounted_price = max(price - discount, Decimal('0.00'))
        return discounted_price, discount
    
    class Meta:
        verbose_name = "Product Offer"
        verbose_name_plural = "Product Offers"

class CategoryOffer(Offer):
    categories = models.ManyToManyField(
        Category, 
        related_name='category_offers',
        help_text="Categories this offer applies to"
    )
    apply_to_subcategories = models.BooleanField(
        default=True,
        help_text="If checked, offer applies to all subcategories as well"
    )
    
    def get_all_categories(self):
        if not self.apply_to_subcategories:
            return self.categories.all()
        all_categories = set(self.categories.all())
        for category in self.categories.all():
            all_categories.update(category.get_descendants(include_self=False))
        return all_categories
    
    def apply_to_product(self, product, price):
        if not self.is_valid() or price < self.min_purchase_amount:
            return price, Decimal('0.00')
        product_categories = set(product.categories.all())
        offer_categories = set(self.get_all_categories())
        if not (product_categories & offer_categories):  
            return price, Decimal('0.00')
        discount = price * (self.discount_value / 100)
        if self.max_discount_amount:
            discount = min(discount, self.max_discount_amount)
        discounted_price = max(price - discount, Decimal('0.00'))
        return discounted_price, discount
    
    class Meta:
        verbose_name = "Category Offer"
        verbose_name_plural = "Category Offers"

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
    valid_to = models.DateTimeField(default=get_default_valid_to)
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
        self.balance += Decimal(str(amount))
        self.save()
        # Create a transaction record
        WalletTransaction.objects.create(
            wallet=self,
            amount=amount,
            transaction_type='CREDIT',
            description=f"Added funds to wallet"
        )
    
    def deduct_funds(self, amount):
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError("Amount to deduct must be positive")
        if self.balance < amount:
            raise ValueError("Insufficient wallet balance")
        self.balance -= amount
        self.save()
        # Create a transaction record
        WalletTransaction.objects.create(
            wallet=self,
            amount=amount,
            transaction_type='DEBIT',
            description=f"Payment for order"
        )

class WalletTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('CREDIT', 'Credit'),
        ('DEBIT', 'Debit'),
        ('REFUND', 'Refund'),
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    transaction_type = models.CharField(max_length=6, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.transaction_type} - {self.amount} - {self.created_at}"

class ReferralCode(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='referral_code')
    code = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username}'s referral code: {self.code}"
    
    def save(self, *args, **kwargs):
        if not self.code:
            import uuid
            self.code = str(uuid.uuid4()).replace('-', '')[:8].upper()
            while ReferralCode.objects.filter(code=self.code).exists():
                self.code = str(uuid.uuid4()).replace('-', '')[:8].upper()
        super().save(*args, **kwargs)

class Referral(models.Model):
    referrer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='referrals_made')
    referred_user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='referred_by')
    coupon_generated = models.BooleanField(default=False)
    coupon = models.ForeignKey('Coupon', on_delete=models.SET_NULL, null=True, blank=True, related_name='referral')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.referrer.username} referred {self.referred_user.username}"
    
    def generate_coupon(self):
        if not self.coupon_generated:
            from datetime import timedelta
            coupon = Coupon.objects.create(
                code=f"REF{str(self.id).zfill(6)}",
                is_active=True,
                valid_from=timezone.now(),
                valid_to=timezone.now() + timedelta(days=30),  
                usage_limit=1, 
                minimum_order_amount=100.00,  
                discount_amount=50.00,  
            )
            self.coupon = coupon
            self.coupon_generated = True
            self.save()
            UserCoupon.objects.create(
                user=self.referrer,
                coupon=coupon,
                is_used=False
            )
            return coupon
        return self.coupon

@receiver(post_save, sender=User)
def create_referral_code(sender, instance, created, **kwargs):
    if created:
        ReferralCode.objects.create(user=instance)