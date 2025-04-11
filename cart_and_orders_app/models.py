from django.db import models
from django.utils import timezone
from django.db.models import Sum, F
from user_app.models import CustomUser, Address
from product_app.models import ProductVariant
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from offer_and_coupon_app.models import Coupon, Wallet

class Cart(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for {self.user.username}"

    def get_total_items(self):
        return self.items.aggregate(total=models.Sum('quantity'))['total'] or 0
    
    def get_subtotal(self):
        total = Decimal('0.0')
        for item in self.items.select_related('variant').all():
            total += Decimal(str(item.quantity)) * Decimal(str(item.variant.best_price['price']))
        return total

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    applied_offer = models.CharField(max_length=20, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('cart', 'variant')

    def __str__(self):
        return f"{self.variant.product.product_name} ({self.quantity}) in {self.cart.user.username}'s cart"

    def get_subtotal(self):
        return self.quantity * (self.price or self.variant.price)
    
    @property
    def product_images(self):
        return self.variant.product.product_images.all()

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
        best_price_info = self.variant.best_price
        self.price = best_price_info['price'] * self.quantity
        self.applied_offer = best_price_info['applied_offer_type']
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.variant}"

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
    discount_amount = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.order_id:
            self.order_id = f"ORD-{timezone.now().strftime('%Y%m%d%H%M%S')}-{self.user.id}"
        super().save(*args, **kwargs)

    def get_total_price(self):
        return sum(item.quantity * item.price for item in self.cart_items.all())

    def decrease_stock(self):
        with transaction.atomic():
            for item in self.cart_items.select_related('variant').all():
                variant = ProductVariant.objects.select_for_update().get(id=item.variant.id)
                if variant.stock >= item.quantity:
                    variant.stock -= item.quantity
                    variant.save()
                else:
                    raise ValueError(f"Insufficient stock for {variant.product.product_name}")

    def restore_stock(self):
        if self.status == 'Cancelled':
            for item in self.cart_items.all():
                variant = item.variant
                variant.stock += item.quantity
                variant.save()

    def __str__(self):
        return f"Order {self.order_id} - {self.user.username}"  

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2) 
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
        if self.is_verified and not self.refund_processed:
            with transaction.atomic():
                wallet, created = Wallet.objects.get_or_create(user=self.order.user)
                wallet.add_funds(self.order.total_amount)
                self.refund_processed = True
                self.save()
                self.order.restore_stock()

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