from django.db import models
from django.utils import timezone
from django.db.models import Sum
from user_app.models import CustomUser, Address
from product_app.models import ProductVariant
from offer_and_coupon_app.models import UserCoupon, Coupon, Wallet, WalletTransaction
from decimal import Decimal, ROUND_UP
from django.conf import settings
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

class Cart(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def get_subtotal(self):
        subtotal = Decimal('0.00')
        for item in self.items.select_related('variant__product').all():
            try:
                best_price_info = item.variant.best_price
                unit_price = best_price_info['price']
                subtotal += unit_price * item.quantity
            except (AttributeError, KeyError, ValueError) as e:
                logger.error(f"Error calculating subtotal for cart {self.id}, item {item.id}: {str(e)}")
                continue
        return subtotal

    def get_totals(self, coupon=None):
        subtotal = self.get_subtotal()
        original_total = Decimal('0.00')
        offer_discount = Decimal('0.00')
        total_quantity = 0
        offer_details = []

        for item in self.items.select_related('variant__product').all():
            best_price_info = item.variant.best_price
            unit_price = best_price_info['price']
            original_price = best_price_info['original_price']
            quantity = item.quantity
            original_total += original_price * quantity
            discount = (original_price - unit_price) * quantity
            total_quantity += quantity
            if discount > 0:
                offer_details.append({
                    'product': item.variant.product.product_name,
                    'offer_type': best_price_info['applied_offer_type'],
                    'discount': float(discount),
                    'variant_id': item.variant.id
                })

        offer_discount = original_total - subtotal
        coupon_discount = Decimal('0.00')
        coupon_code = None

        if coupon and coupon.is_valid() and subtotal >= coupon.minimum_order_amount:
            coupon_discount = (coupon.discount_percentage / 100) * subtotal
            if coupon.max_discount_amount > 0 and coupon_discount > coupon.max_discount_amount:
                coupon_discount = coupon.max_discount_amount
            if coupon_discount > subtotal:
                coupon_discount = subtotal
            coupon_code = coupon.code

        total = subtotal - coupon_discount 
        return {
            'subtotal': subtotal,
            'original_total': original_total,
            'offer_discount': offer_discount,
            'coupon_discount': coupon_discount,
            'coupon_code': coupon_code,
            'shipping_cost': Decimal('0.00'), 
            'total': total,
            'total_quantity': total_quantity,
            'offer_details': offer_details
        }
    
    def get_total_items(self):
        return sum(item.quantity for item in self.items.all())
    
    def get_total_items_in_cart(self):
        return self.items.count()

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('cart', 'variant')

    def __str__(self):
        return f"{self.quantity} x {self.variant}"

    def get_subtotal(self):
        best_price_info = self.variant.best_price
        unit_price = best_price_info['price']
        return unit_price * Decimal(self.quantity)

    def get_discount_amount(self):
        best_price_info = self.variant.best_price
        original_price = best_price_info['original_price']
        discounted_price = best_price_info['price']
        discount_per_unit = original_price - discounted_price
        return discount_per_unit * Decimal(str(self.quantity))

    @property
    def product_name(self):
        return self.variant.product.product_name

    @property
    def variant_details(self):
        details = []
        if self.variant.flavor:
            details.append(f"Flavor: {self.variant.flavor}")
        if self.variant.size_weight:
            details.append(f"Size: {self.variant.size_weight}")
        return ", ".join(details) if details else "Standard"

    @property
    def primary_image(self):
        primary_img = self.variant.primary_image
        if primary_img:
            return primary_img
        return self.variant.product.primary_image

    def save(self, *args, **kwargs):
        if self.quantity > self.variant.stock:
            logger.warning(f"CartItem quantity {self.quantity} exceeds stock {self.variant.stock} for variant {self.variant}")
            raise ValueError(f"Quantity {self.quantity} exceeds available stock for {self.variant}")
        super().save(*args, **kwargs)

class Wishlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlists')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'variant')

    def __str__(self):
        return f"{self.user.username} - {self.variant.product.product_name}"
    
    @property
    def product(self):
        return self.variant.product
    
    @property
    def primary_image(self):
        primary_img = self.variant.primary_image
        if primary_img:
            return primary_img
        return self.variant.product.primary_image
    
    @property
    def best_price(self):
        return self.variant.best_price
    
    @property
    def is_in_stock(self):
        return self.variant.stock > 0

class Order(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Processing', 'Processing'),
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
    PAYMENT_STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
    )

    order_id = models.CharField(max_length=30, unique=True, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='orders')
    order_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='COD')
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True)
    coupon_discount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)

    def get_subtotal(self):
        return sum(item.price * Decimal(item.quantity) for item in self.items.all())

    def get_coupon_discount(self):
        if self.coupon and self.coupon.is_valid():
            subtotal = self.get_subtotal()
            _, discount = self.coupon.apply_to_subtotal(subtotal)
            return discount
        return Decimal('0.00')

    def get_item_refund(self, order_item):
        """
        Calculate the refund for a single item using the formula:
        item_refund = item_total - (coupon_share * (item_total / order_subtotal)).
        """
        item_total = order_item.price * Decimal(order_item.quantity)
        order_subtotal = self.get_subtotal()
        total_coupon_discount = self.get_coupon_discount()

        if order_subtotal <= 0 or total_coupon_discount <= 0:
            return item_total

        coupon_share = self.coupon.calculate_item_coupon_share(item_total, order_subtotal) if self.coupon else Decimal('0.00')
        refund_amount = item_total - coupon_share
        return refund_amount.quantize(Decimal('0.01'), rounding=ROUND_UP)

    def cancel_item(self, order_item, reason=None):
        if self.status not in ['Pending', 'Processing']:
            raise ValueError("Order cannot be cancelled in its current status.")
        with transaction.atomic():
            variant = order_item.variant
            variant.stock += order_item.quantity
            variant.save()
            refund_amount = self.get_item_refund(order_item)
            wallet, created = Wallet.objects.get_or_create(user=self.user)
            wallet.add_funds(refund_amount)
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=refund_amount,
                transaction_type='REFUND',
                description=f"Refund for cancelled item {order_item.variant} in order {self.order_id}"
            )
            OrderCancellation.objects.create(
                order=self,
                item=order_item,
                reason=reason,
                refunded_amount=refund_amount
            )
            order_item.delete()
            self.needs_recalculation = True  # Trigger recalculation
            if self.coupon and self.get_subtotal() < self.coupon.minimum_order_amount:
                try:
                    user_coupon = UserCoupon.objects.get(user=self.user, coupon=self.coupon, order=self)
                    user_coupon.reset()
                    self.coupon = None
                except UserCoupon.DoesNotExist:
                    self.coupon = None
            if not self.items.exists():
                self.status = 'Cancelled'
            self.save()
            logger.info(f"Item {order_item} cancelled for order {self.order_id}, refunded {refund_amount}")

    def cancel_order(self, reason=None):
        if self.status not in ['Pending', 'Processing']:
            raise ValueError("Order cannot be cancelled in its current status.")

        with transaction.atomic():
            self.restore_stock()
            refund_amount = self.total_amount

            wallet, created = Wallet.objects.get_or_create(user=self.user)
            wallet.add_funds(refund_amount)
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=refund_amount,
                transaction_type='REFUND',
                description=f"Refund for cancelled order {self.order_id}"
            )

            OrderCancellation.objects.create(
                order=self,
                reason=reason,
                refunded_amount=refund_amount
            )

            if self.coupon:
                try:
                    user_coupon = UserCoupon.objects.get(user=self.user, coupon=self.coupon, order=self)
                    user_coupon.reset()
                except UserCoupon.DoesNotExist:
                    pass

            self.coupon = None
            self.status = 'Cancelled'
            self.save()

            logger.info(f"Order {self.order_id} cancelled, refunded {refund_amount}")

    def recalculate_totals(self):
        subtotal = self.get_subtotal()
        coupon_discount = Decimal('0.00')
        if self.coupon and self.coupon.is_valid() and subtotal >= self.coupon.minimum_order_amount:
            coupon_discount = self.coupon.apply_to_subtotal(subtotal)
        total = subtotal - coupon_discount
        total = max(total, Decimal('0.00'))
        self.coupon_discount = coupon_discount
        self.total_amount = total

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Only recalculate for modifications like cancellations or returns
        if hasattr(self, 'needs_recalculation') and self.needs_recalculation:
            self.recalculate_totals()
            self.needs_recalculation = False
            super().save(update_fields=['total_amount', 'coupon_discount'])

        if self.pk and self.coupon and self.coupon.is_valid():
            try:
                user_coupon = UserCoupon.objects.get(user=self.user, coupon=self.coupon, is_used=False)
                user_coupon.is_used = True
                user_coupon.used_at = timezone.now()
                user_coupon.order = self
                user_coupon.save()
                logger.info(f"UserCoupon updated for order {self.order_id}, coupon {self.coupon.code}")
            except UserCoupon.DoesNotExist:
                logger.warning(f"No valid UserCoupon found for user {self.user.id}, coupon {self.coupon.code}")
                self.coupon = None
                self.recalculate_totals()
                super().save(update_fields=['total_amount', 'coupon_discount'])

    def decrease_stock(self):
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
        for item in self.items.all():
            variant = item.variant
            variant.stock += item.quantity
            variant.save()
            logger.info(f"Restored {item.quantity} stock for {variant.product.product_name}")

    def get_cancelled_items_count(self):
        return self.cancellations.filter(item__isnull=False).count()

    class Meta:
        indexes = [
            models.Index(fields=['order_id']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f"Order {self.order_id} - {self.user.username}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Unit price after best offer")
    applied_offer = models.CharField(max_length=20, blank=True, null=True)

    @property
    def total_price(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.variant.product.product_name} ({self.quantity})"

class OrderCancellation(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='cancellations')
    item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, null=True, blank=True, related_name='cancellations')
    reason = models.TextField(blank=True, null=True)
    cancelled_at = models.DateTimeField(default=timezone.now)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        indexes = [
            models.Index(fields=['order']),
        ]

    def __str__(self):
        return f"Cancellation for Order {self.order.order_id} - Item: {self.item or 'Entire Order'}"

class ReturnRequest(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='return_requests')
    items = models.ManyToManyField(OrderItem, blank=True, related_name='return_requests')
    reason = models.TextField()
    requested_at = models.DateTimeField(default=timezone.now)
    is_verified = models.BooleanField(default=False)
    refund_processed = models.BooleanField(default=False)

    def process_refund(self):
        if not self.is_verified or self.refund_processed:
            return

        with transaction.atomic():
            wallet, created = Wallet.objects.get_or_create(user=self.order.user)
            refund_amount = Decimal('0.00')

            if self.items.exists():
                # Partial return
                for item in self.items.all():
                    item_refund = self.order.get_item_refund(item)
                    refund_amount += item_refund
                    item.variant.stock += item.quantity
                    item.variant.save()
            else:
                # Full return
                refund_amount = self.order.total_amount
                self.order.restore_stock()
                if self.order.coupon:
                    try:
                        user_coupon = UserCoupon.objects.get(user=self.order.user, coupon=self.order.coupon, order=self.order)
                        user_coupon.reset()
                    except UserCoupon.DoesNotExist:
                        pass
                self.order.coupon = None
                self.order.recalculate_totals()
                self.order.save()

            wallet.add_funds(refund_amount)
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=refund_amount,
                transaction_type='REFUND',
                description=f"Refund for return request on order {self.order.order_id} ({'partial' if self.items.exists() else 'full'})"
            )

            self.refund_processed = True
            self.save()
            logger.info(f"Processed refund of {refund_amount} for order {self.order.order_id}")

    def __str__(self):
        return f"Return for Order {self.order.order_id}"

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