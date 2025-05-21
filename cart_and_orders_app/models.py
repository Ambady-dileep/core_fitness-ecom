from django.db import models
from django.utils import timezone
from django.db.models import Sum
import razorpay
from user_app.models import CustomUser, Address
from product_app.models import ProductVariant
from offer_and_coupon_app.models import UserCoupon, Coupon, Wallet, WalletTransaction
from decimal import Decimal, ROUND_UP
from django.core.exceptions import ValidationError
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
    address_full_name = models.CharField(max_length=255, blank=True, null=True)
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    address_city = models.CharField(max_length=100, blank=True, null=True)
    address_state = models.CharField(max_length=100, blank=True, null=True)
    address_postal_code = models.CharField(max_length=20, blank=True, null=True)
    address_country = models.CharField(max_length=100, blank=True, null=True)
    address_phone = models.CharField(max_length=10, blank=True, null=True)
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
    

    def get_item_refund(self, items):
        """Calculate the refund amount for one or more order items."""
        from decimal import Decimal
        refund_amount = Decimal('0.00')
        
        # Handle single OrderItem by wrapping it in a list
        if isinstance(items, OrderItem):
            items = [items]
        elif not items:  # Handle empty input
            return refund_amount

        # If no coupon is applied, refund the full item total
        if not self.coupon or not self.coupon_discount:
            return sum(item.total_price for item in items).quantize(Decimal('0.01'))

        # If coupon is applied, calculate proportional coupon discount
        total_coupon_discount = self.coupon_discount or Decimal('0.00')
        total_order_items = sum(item.total_price for item in self.items.all())

        for item in items:
            if total_order_items > 0:
                item_proportion = item.total_price / total_order_items
                coupon_share = total_coupon_discount * item_proportion
                refund_amount += item.total_price - coupon_share

        return refund_amount.quantize(Decimal('0.01'))

    def cancel_item(self, order_item, reason=None):

        if self.status not in ['Pending', 'Processing', 'Confirmed']:
            raise ValidationError(f"Order {self.order_id} cannot have items cancelled in status {self.status}.")
        
        if order_item.cancellations.exists():
            raise ValidationError(f"Item {order_item.id} in order {self.order_id} is already cancelled.")
        
        if self.payment_method == 'CARD' and self.payment_status != 'PAID':
            raise ValidationError(f"Cannot refund item in order {self.order_id}: Payment status is {self.payment_status}, expected PAID.")

        with transaction.atomic():
            # Restore stock for the item
            variant = order_item.variant
            variant.stock += order_item.quantity
            variant.save()

            # Calculate refund amount for the item
            refund_amount = self.get_item_refund(order_item)
            if refund_amount <= 0:
                logger.warning(f"No refundable amount for item {order_item.id} in order {self.order_id}")
                refund_amount = Decimal('0.00')

            # Check total refunded amount against original payment
            prior_refunded = sum(c.refunded_amount for c in self.cancellations.all())
            total_proposed_refunded = prior_refunded + refund_amount
            # Use total_amount as the actual amount paid (after coupon)
            original_payment = self.total_amount

            # Ensure refund doesn't exceed payment
            if total_proposed_refunded > original_payment:
                logger.warning(
                    f"Adjusting refund for item {order_item.id} in order {self.order_id}: "
                    f"Total proposed refund ({total_proposed_refunded}) exceeds payment ({original_payment})"
                )
                refund_amount = original_payment - prior_refunded
                if refund_amount < 0:
                    refund_amount = Decimal('0.00')

            # Process refund
            if refund_amount > 0:
                if self.payment_method == 'CARD' and self.payment_status == 'PAID' and self.razorpay_payment_id and not self.coupon:
                    # Refund via Razorpay only if no coupon (per requirement)
                    try:
                        self.process_razorpay_refund(refund_amount, self.razorpay_payment_id)
                    except ValidationError as e:
                        logger.warning(f"Razorpay refund failed for item {order_item.id}: {str(e)}. Redirecting to wallet.")
                        wallet, created = Wallet.objects.get_or_create(user=self.user)
                        wallet.add_funds(refund_amount)
                        WalletTransaction.objects.create(
                            wallet=wallet,
                            amount=refund_amount,
                            transaction_type='REFUND',
                            description=f"Refund for cancelled item {order_item.variant} in order {self.order_id} (Razorpay failed)"
                        )
                        logger.info(f"Refunded {refund_amount} to wallet for item {order_item.id} due to Razorpay failure")
                else:
                    # Refund to wallet for COD, WALLET, or when coupon is applied
                    wallet, created = Wallet.objects.get_or_create(user=self.user)
                    wallet.add_funds(refund_amount)
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        amount=refund_amount,
                        transaction_type='REFUND',
                        description=f"Refund for cancelled item {order_item.variant} in order {self.order_id}"
                    )
                    logger.info(f"Refunded {refund_amount} to wallet for item {order_item.id} in order {self.order_id}")

            # Create cancellation record
            OrderCancellation.objects.create(
                order=self,
                item=order_item,
                product_name=order_item.variant.product.product_name,
                variant_flavor=order_item.variant.flavor,
                variant_size_weight=order_item.variant.size_weight,
                quantity=order_item.quantity,
                reason=reason,
                refunded_amount=refund_amount
            )

            # Delete the canceled item
            order_item.delete()

            # Recalculate order totals and check coupon validity
            self.needs_recalculation = True
            if self.coupon:
                subtotal = self.get_subtotal()
                if subtotal < self.coupon.minimum_order_amount:
                    try:
                        user_coupon = UserCoupon.objects.get(user=self.user, coupon=self.coupon, order=self)
                        user_coupon.reset()
                        logger.info(f"Reset coupon {self.coupon.code} for order {self.order_id} due to insufficient subtotal")
                        self.coupon = None
                        self.coupon_discount = Decimal('0.00')
                    except UserCoupon.DoesNotExist:
                        logger.warning(f"No UserCoupon found for coupon {self.coupon.code} in order {self.order_id}")
                        self.coupon = None
                        self.coupon_discount = Decimal('0.00')

            # If no items remain, mark order as Cancelled
            if not self.items.exists():
                self.status = 'Cancelled'
                self.total_amount = Decimal('0.00')
            else:
                # Recalculate total_amount
                self.total_amount = self.get_subtotal() - (self.coupon_discount if self.coupon else Decimal('0.00'))
                self.total_amount = max(self.total_amount, Decimal('0.00'))

            self.save()
            logger.info(f"Item {order_item.id} cancelled for order {self.order_id}, refunded {refund_amount}")

    def cancel_order(self, reason=None):
        # Check if the order status allows cancellation
        if self.status not in ['Pending', 'Processing', 'Confirmed']:
            raise ValidationError(f"Order {self.order_id} cannot be cancelled in status {self.status}.")

        # Handle payment status
        if self.payment_status == 'PENDING':
            logger.info(f"Order {self.order_id} is in PENDING payment status. No refund will be processed.")
        elif self.payment_status == 'FAILED':
            logger.info(f"Order {self.order_id} is in FAILED payment status. No refund will be processed.")
        elif self.payment_status == 'PAID':
            logger.info(f"Order {self.order_id} is in PAID payment status. Processing refund.")
        else:
            raise ValidationError(f"Order {self.order_id} has an invalid payment status: {self.payment_status}.")

        with transaction.atomic():
            # Restore stock for all items
            self.restore_stock()

            # Calculate refundable amount
            refund_amount = Decimal('0.00')
            if self.payment_status == 'PAID':
                prior_refunded = sum(c.refunded_amount for c in self.cancellations.all())
                refund_amount = self.total_amount - prior_refunded
                if refund_amount <= 0:
                    logger.warning(f"No refundable amount for order {self.order_id}, possibly due to prior cancellations.")
                    refund_amount = Decimal('0.00')

                # For CARD payments, verify refundable amount with Razorpay
                if self.payment_method == 'CARD' and self.razorpay_payment_id:
                    try:
                        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                        payment = client.payment.fetch(self.razorpay_payment_id)
                        payment_amount = Decimal(payment['amount']) / 100  # Convert paise to INR
                        refunded_amount = Decimal(payment.get('refunded_amount', 0)) / 100
                        max_refundable = payment_amount - refunded_amount
                        logger.info(f"Razorpay payment {self.razorpay_payment_id}: total={payment_amount}, refunded={refunded_amount}, max_refundable={max_refundable}")
                        if refund_amount > max_refundable:
                            logger.warning(
                                f"Adjusting refund for order {self.order_id}: "
                                f"Proposed refund ({refund_amount}) exceeds Razorpay max refundable ({max_refundable})"
                            )
                            refund_amount = max_refundable if max_refundable > 0 else Decimal('0.00')
                    except Exception as e:
                        logger.error(f"Failed to fetch Razorpay payment {self.razorpay_payment_id}: {str(e)}. Redirecting to wallet.")
                        refund_amount = self.total_amount - prior_refunded if refund_amount > 0 else Decimal('0.00')

                # Process refund
                if refund_amount > 0:
                    if self.payment_method == 'CARD' and self.razorpay_payment_id:
                        try:
                            self.process_razorpay_refund(refund_amount, self.razorpay_payment_id)
                            logger.info(f"Razorpay refund processed for order {self.order_id}, amount={refund_amount}")
                        except ValidationError as e:
                            logger.warning(f"Razorpay refund failed for order {self.order_id}: {str(e)}. Redirecting to wallet.")
                            wallet, created = Wallet.objects.get_or_create(user=self.user)
                            wallet.add_funds(refund_amount)
                            WalletTransaction.objects.create(
                                wallet=wallet,
                                amount=refund_amount,
                                transaction_type='REFUND',
                                description=f"Refund for cancelled order {self.order_id} (Razorpay failed)"
                            )
                            logger.info(f"Refunded {refund_amount} to wallet for order {self.order_id} due to Razorpay failure")
                    else:
                        # Refund to wallet for COD or WALLET payments
                        wallet, created = Wallet.objects.get_or_create(user=self.user)
                        wallet.add_funds(refund_amount)
                        WalletTransaction.objects.create(
                            wallet=wallet,
                            amount=refund_amount,
                            transaction_type='REFUND',
                            description=f"Refund for cancelled order {self.order_id}"
                        )
                        logger.info(f"Refunded {refund_amount} to wallet for order {self.order_id}")

            # Create cancellation record
            OrderCancellation.objects.create(
                order=self,
                reason=reason,
                refunded_amount=refund_amount
            )

            # Reset coupon if applied
            if self.coupon:
                try:
                    user_coupon = UserCoupon.objects.get(user=self.user, coupon=self.coupon, order=self)
                    user_coupon.reset()
                    logger.info(f"Reset coupon {self.coupon.code} for order {self.order_id}")
                except UserCoupon.DoesNotExist:
                    logger.warning(f"No UserCoupon found for coupon {self.coupon.code} in order {self.order_id}")
                self.coupon = None
                self.coupon_discount = Decimal('0.00')

            # Update order status
            self.status = 'Cancelled'
            self.total_amount = Decimal('0.00')
            self.needs_recalculation = False
            self.save()
            logger.info(f"Order {self.order_id} cancelled successfully, refunded {refund_amount}")


    def process_razorpay_refund(self, amount, payment_id):
        """Process a refund via Razorpay X for the given amount."""
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        try:
            refund = client.payment.refund(payment_id, {
                'amount': int(amount * 100),  # Convert to paise
                'speed': 'normal',
                'notes': {'reason': f'Refund for order {self.order_id}'}
            })
            logger.info(f"Razorpay refund processed for order {self.order_id}, payment_id={payment_id}, amount={amount}: {refund}")
            return refund
        except razorpay.errors.BadRequestError as e:
            logger.error(f"Razorpay refund failed for order {self.order_id}, payment_id={payment_id}: {str(e)}")
            raise ValidationError(f"Refund processing failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in Razorpay refund for order {self.order_id}, payment_id={payment_id}: {str(e)}")
            raise ValidationError(f"Refund processing failed: {str(e)}")
        
    def get_refundable_amount(self):
        """Calculate the refundable amount, accounting for prior cancellations."""
        if self.status == 'Cancelled':
            return Decimal('0.00')
        
        # Sum of already refunded amounts
        prior_refunded = sum(c.refunded_amount for c in self.cancellations.all())
        
        # Calculate remaining items' total
        remaining_items_total = sum(
            item.price * Decimal(item.quantity)
            for item in self.items.filter(cancellations__isnull=True)
        )
        
        # Adjust for coupon discount proportionally
        if self.coupon and self.coupon_discount > 0:
            original_subtotal = self.get_subtotal()
            if original_subtotal > 0:
                remaining_proportion = remaining_items_total / original_subtotal
                remaining_coupon_discount = self.coupon_discount * remaining_proportion
            else:
                remaining_coupon_discount = Decimal('0.00')
        else:
            remaining_coupon_discount = Decimal('0.00')
        
        refundable_amount = remaining_items_total - remaining_coupon_discount
        refundable_amount = max(refundable_amount, Decimal('0.00'))
        
        logger.info(f"Calculated refundable amount for order {self.order_id}: remaining_items_total={remaining_items_total}, "
                    f"remaining_coupon_discount={remaining_coupon_discount}, prior_refunded={prior_refunded}, "
                    f"refundable_amount={refundable_amount}")
        return refundable_amount.quantize(Decimal('0.01'))

    def get_original_total_amount(self):
        """
        Calculate the original total amount of the order, including cancelled items,
        before any coupon discounts.
        """
        # Sum of all active items
        active_items_total = self.get_subtotal()
        # Sum of refunded amounts for cancelled items
        cancelled_items_total = self.cancellations.filter(item__isnull=False).aggregate(
            total_refunded=Sum('refunded_amount')
        )['total_refunded'] or Decimal('0.00')
        # Original total before cancellations
        original_total = active_items_total + cancelled_items_total
        return original_total.quantize(Decimal('0.01'), rounding=ROUND_UP)

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
                if self.coupon_discount <= 0:
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
    product_name = models.CharField(max_length=200, blank=True, null=True, help_text="Name of the product at cancellation")
    variant_flavor = models.CharField(max_length=50, blank=True, null=True, help_text="Flavor of the variant at cancellation")
    variant_size_weight = models.CharField(max_length=50, blank=True, null=True, help_text="Size/weight of the variant at cancellation")
    quantity = models.PositiveIntegerField(default=1, help_text="Quantity cancelled")
    reason = models.TextField(blank=True, null=True)
    cancelled_at = models.DateTimeField(default=timezone.now)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        indexes = [
            models.Index(fields=['order']),
        ]

    def __str__(self):
        item_desc = self.product_name or "Entire Order"
        if self.variant_flavor or self.variant_size_weight:
            variant_desc = f"{self.variant_flavor or 'Standard'} {self.variant_size_weight or ''}".strip()
            item_desc += f" ({variant_desc})"
        if self.quantity > 1:
            item_desc += f" x {self.quantity}"
        return f"Cancellation for Order {self.order.order_id} - {item_desc}"

class ReturnRequest(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='return_requests')
    items = models.ManyToManyField(OrderItem, blank=True, related_name='return_requests')
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
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