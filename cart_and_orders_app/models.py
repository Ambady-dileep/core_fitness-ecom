from django.db import models
from django.utils import timezone
from django.db.models import Sum, F
from user_app.models import CustomUser, Address
from product_app.models import ProductVariant
from offer_and_coupon_app.utils import get_best_offer_for_product
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from offer_and_coupon_app.models import Coupon, Wallet
import logging

logger = logging.getLogger(__name__)

class Cart(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for {self.user.username}"

    def get_total_items(self):
        return self.items.aggregate(total=Sum('quantity'))['total'] or 0
    
    def get_subtotal(self):
        total = Decimal('0.00')
        for item in self.items.select_related('variant__product').all():
            try:
                best_price_info = item.variant.best_price
                unit_price = best_price_info.get('price', Decimal('0.00'))  # Default to 0 if price is missing
                if not isinstance(unit_price, Decimal):
                    unit_price = Decimal(str(unit_price))
                total += unit_price * Decimal(str(item.quantity))
            except (AttributeError, KeyError, ValueError) as e:
                logger.error(f"Error calculating subtotal for cart {self.id}, item {item.id}: {str(e)}")
                continue  # Skip invalid items
        return total

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Unit price after best offer")
    applied_offer = models.CharField(max_length=20, blank=True, null=True, help_text="Type of offer applied (product/category)")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('cart', 'variant')

    def __str__(self):
        return f"{self.quantity} x {self.variant}"

    def get_subtotal(self):
        """
        Calculate subtotal for this item using the stored price or variant's best price.
        """
        price = self.price or self.variant.best_price['price']
        return price * Decimal(str(self.quantity))
    
    def get_discounted_price(self):
        """
        Calculate total discounted price for this item (price * quantity).
        """
        best_price_info = self.variant.best_price
        unit_price = best_price_info['price']
        return unit_price * Decimal(str(self.quantity))
    
    def get_discount_amount(self):
        """
        Calculate total discount amount for this item.
        """
        best_price_info = self.variant.best_price
        original_price = best_price_info['original_price']
        discounted_price = best_price_info['price']
        discount_per_unit = original_price - discounted_price
        return discount_per_unit * Decimal(str(self.quantity))
    
    @property
    def product_images(self):
        return self.variant.product.all_variant_images

    @property
    def variant_image(self):
        return self.variant.primary_image 
    
    @property
    def primary_image(self):
        variant_img = self.variant_image
        if variant_img and variant_img.image:
            return variant_img
        return self.variant.product.primary_image

    def save(self, *args, **kwargs):
        """
        Update price and applied_offer based on the best offer for the variant.
        """
        best_price_info = self.variant.best_price
        self.price = best_price_info['price']  # Store unit price
        self.applied_offer = best_price_info['applied_offer_type']
        if self.quantity > self.variant.stock:
            logger.warning(f"CartItem quantity {self.quantity} exceeds stock {self.variant.stock} for variant {self.variant}")
            raise ValueError(f"Quantity {self.quantity} exceeds available stock for {self.variant}")
        super().save(*args, **kwargs)

class Order(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Shipped', 'Shipped'),
        ('Out for Delivery', 'Out for Delivery'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    )
    PAYMENT_CHOICES = (
        ('COD', 'Cash on Delivery'),
        ('CARD', 'Credit/Debit Card'),
        ('WALLET', 'Wallet'),
    )
    
    order_id = models.CharField(max_length=30, unique=True, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='orders')
    order_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='COD')
    cart_items = models.ManyToManyField('CartItem', related_name='orders')
    coupon = models.ForeignKey('offer_and_coupon_app.Coupon', on_delete=models.SET_NULL, null=True, blank=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)

    def save(self, *args, **kwargs):
        """
        Set order_id if not present and calculate total_amount and discount_amount.
        """
        if not self.order_id:
            self.order_id = f"ORD-{timezone.now().strftime('%Y%m%d%H%M%S')}-{self.user.id}"
        
        # Calculate totals before saving
        subtotal = Decimal('0.00')
        offer_discount = Decimal('0.00')
        coupon_discount = Decimal('0.00')
        
        for item in self.cart_items.all():
            best_price_info = item.variant.best_price
            unit_price = best_price_info['price']
            original_price = best_price_info['original_price']
            quantity = Decimal(str(item.quantity))
            subtotal += unit_price * quantity
            offer_discount += (original_price - unit_price) * quantity
        
        if self.coupon and self.coupon.is_valid():
            coupon_discount = (self.coupon.discount_percentage / 100) * subtotal
            if coupon_discount > subtotal:
                coupon_discount = subtotal  # Prevent negative total
        
        self.total_amount = subtotal - offer_discount - coupon_discount
        self.discount_amount = offer_discount + coupon_discount
        
        super().save(*args, **kwargs)
        
        # Create OrderItems after saving
        if not self.items.exists():
            for cart_item in self.cart_items.all():
                OrderItem.objects.create(
                    order=self,
                    variant=cart_item.variant,
                    quantity=cart_item.quantity,
                    price=cart_item.price or cart_item.variant.best_price['price'],
                    applied_offer=cart_item.applied_offer
                )

    def get_total_price(self):
        """
        Calculate total price including discounts.
        """
        subtotal = Decimal('0.00')
        for item in self.items.all():
            subtotal += item.price * Decimal(str(item.quantity))
        return subtotal

    def decrease_stock(self):
        """
        Decrease stock for each item in the order.
        """
        with transaction.atomic():
            for item in self.items.select_related('variant').all():
                variant = ProductVariant.objects.select_for_update().get(id=item.variant.id)
                if variant.stock >= item.quantity:
                    variant.stock -= item.quantity
                    variant.save()
                else:
                    logger.error(f"Insufficient stock for {variant.product.product_name}: required {item.quantity}, available {variant.stock}")
                    raise ValueError(f"Insufficient stock for {variant.product.product_name}")

    def restore_stock(self):
        """
        Restore stock if order is cancelled.
        """
        if self.status == 'Cancelled':
            for item in self.items.all():
                variant = item.variant
                variant.stock += item.quantity
                variant.save()
                logger.info(f"Restored {item.quantity} stock for {variant.product.product_name}")

    def __str__(self):
        return f"Order {self.order_id} - {self.user.username}"  

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Unit price after best offer")
    applied_offer = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"{self.variant.product.product_name} ({self.quantity})"

class ReturnRequest(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='return_requests')
    reason = models.TextField()
    requested_at = models.DateTimeField(default=timezone.now)
    is_verified = models.BooleanField(default=False)
    refund_processed = models.BooleanField(default=False)

    def process_refund(self):
        """
        Process refund to wallet and restore stock.
        """
        if self.is_verified and not self.refund_processed:
            with transaction.atomic():
                wallet, created = Wallet.objects.get_or_create(user=self.order.user)
                wallet.add_funds(self.order.total_amount)
                self.refund_processed = True
                self.save()
                self.order.restore_stock()
                logger.info(f"Processed refund of {self.order.total_amount} for order {self.order.order_id}")

    def __str__(self):
        return f"Return for Order {self.order.order_id}"

class Wishlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'variant')

    def __str__(self):
        return f"{self.user.username} - {self.variant.product.product_name}"

class SalesReport(models.Model):
    REPORT_TYPES = (
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('YEARLY', 'Yearly'),
        ('CUSTOM', 'Custom'),
    )
    
    report_type = models.CharField(max_length=10, choices=REPORT_TYPES)
    start_date = models.DateField()
    end_date = models.DateField()
    total_orders = models.IntegerField(default=0)
    total_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.get_report_type_display()} Report: {self.start_date} to {self.end_date}"
    
    class Meta:
        ordering = ['-created_at']