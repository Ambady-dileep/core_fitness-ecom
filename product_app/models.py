from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from cloudinary.models import CloudinaryField
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from django import forms
from django.db.models import Min, Max, F, ExpressionWrapper, DecimalField, Sum, Avg

User = get_user_model()

def category_image_path(instance, filename):
    return f'categories/{instance.name}/{filename}'

class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    image = CloudinaryField('image', blank=True, null=True, folder='categories')
    parent = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL,  
        blank=True,
        null=True,
        related_name='subcategories'
    )
    brands = models.ManyToManyField('Brand', related_name='categories', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Category.objects.filter(slug=slug).exclude(id=self.id).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        self.is_active = False
        self.save(update_fields=['is_active'])

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"
        unique_together = ('name', 'parent')

class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    logo = CloudinaryField('image', blank=True, null=True, folder='brands')
    website = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Brand.objects.filter(slug=slug).exclude(id=self.id).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        self.is_active = False
        self.save(update_fields=['is_active'])

    @property
    def product_count(self):
        return self.products.filter(is_active=True).count()

    @property
    def category_count(self):
        return self.categories.filter(is_active=True).count()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class Product(models.Model):
    product_name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, related_name='products', null=True, blank=True)
    description = models.TextField(blank=True, help_text="Detailed description including ingredients, usage instructions, etc.")
    country_of_manufacture = models.CharField(max_length=100, blank=True, help_text="Country where the product is manufactured.")
    is_active = models.BooleanField(default=True)
    average_rating = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.product_name)
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exclude(id=self.id).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        if self.brand and self.category and self.category not in self.brand.categories.all():
            self.brand.categories.add(self.category)
        super().save(*args, **kwargs)

    @property
    def primary_variant(self):
        return self.variants.filter(is_active=True).first()
    
    # Removed duplicate property
    @property
    def primary_image(self):
        primary_variant = self.primary_variant
        if primary_variant:
            return primary_variant.primary_image
        return None
    
    def get_best_offer_price(self, original_price):
        best_price = original_price
        for offer in self.product_offers.filter(is_active=True):
            if offer.is_valid():
                price_after_offer = offer.apply_to_product(self, original_price)
                best_price = min(best_price, price_after_offer)
        return best_price
    
    # Fixed property to make it a calculated field, not overriding the DB field
    @property
    def calculated_average_rating(self):
        return self.reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    def update_average_rating(self):
        avg = self.reviews.filter(is_approved=True).aggregate(Avg('rating'))['rating__avg']
        self.average_rating = avg if avg is not None else 0.0
        self.save(update_fields=['average_rating'])

    def min_price(self):
        discounted = ExpressionWrapper(
            F('original_price') * (1 - F('discount_percentage') / 100),
            output_field=DecimalField(max_digits=10, decimal_places=2)
        )
        result = self.variants.filter(is_active=True).aggregate(min_price=Min(discounted))['min_price'] or 0
        return result

    def max_price(self):
        discounted = ExpressionWrapper(
            F('original_price') * (1 - F('discount_percentage') / 100),
            output_field=DecimalField(max_digits=10, decimal_places=2)
        )
        result = self.variants.filter(is_active=True).aggregate(max_price=Max(discounted))['max_price'] or 0
        return result

    def total_stock(self):
        return self.variants.filter(is_active=True).aggregate(total_stock=Sum('stock'))['total_stock'] or 0

    @property
    def all_variant_images(self):
        from django.db.models import Prefetch
        variants = self.variants.prefetch_related('variant_images')
        return [img for variant in variants for img in variant.variant_images.all()]

    def has_user_reviewed(self, user):
        return self.reviews.filter(user=user).exists()
    
    def get_rating_count(self):
        from django.db.models import Count
        rating_counts = self.reviews.filter(is_approved=True).values('rating').annotate(count=Count('rating'))
        result = {str(int(r['rating'])): r['count'] for r in rating_counts}
        for i in range(1, 6):
            result.setdefault(str(i), 0)
        return result

    def approved_reviews(self):
        return self.reviews.filter(is_approved=True)
    
    # Add this method that might be missing (referenced in the error)
    @property
    def best_price(self):
        # Return a dictionary with price info instead of a tuple
        primary_variant = self.primary_variant
        if not primary_variant:
            return {'price': 0, 'original_price': 0, 'discount': 0}
            
        original_price = primary_variant.original_price
        discount_percentage = primary_variant.discount_percentage
        discounted_price = original_price * (1 - discount_percentage / 100)
        
        # Apply any product offers
        best_offer_price = self.get_best_offer_price(discounted_price)
        
        # Calculate total discount percentage
        total_discount = ((original_price - best_offer_price) / original_price) * 100 if original_price > 0 else 0
        
        return {
            'price': best_offer_price,
            'original_price': original_price,
            'discount': round(total_discount, 2)
        }

    def __str__(self):
        return self.product_name

class ProductVariant(models.Model):
    FLAVOR_CHOICES = [
        ('chocolate', 'Chocolate'),
        ('vanilla', 'Vanilla'),
        ('mango', 'Mango'),
        ('strawberry', 'Strawberry'),
        ('un-flavoured', 'Un-Flavoured'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=100, unique=True, blank=True, null=True)
    flavor = models.CharField(max_length=50, choices=FLAVOR_CHOICES, blank=True, null=True)
    size_weight = models.CharField(max_length=50, blank=True, null=True)
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percentage = models.DecimalField(
    
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Discount percentage to apply (0-100)."
    )
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.sku:
            base = slugify(self.product.product_name)[:10]
            flavor = slugify(self.flavor)[:5] if self.flavor else "std"
            size = slugify(self.size_weight)[:5] if self.size_weight else "std"
            sku = f"{base}-{flavor}-{size}"
            counter = 1
            while ProductVariant.objects.filter(sku=sku).exclude(id=self.id).exists():
                sku = f"{base}-{flavor}-{size}-{counter}"
                counter += 1
            self.sku = sku
        super().save(*args, **kwargs)

    def discounted_price(self):
        original_price = float(self.original_price)
        discount = float(self.discount_percentage)
        discounted = original_price * (1 - discount / 100)
        return int(round(discounted))

    @property
    def best_price(self):
        from offer_and_coupon_app.models import CategoryOffer
        from decimal import Decimal, InvalidOperation
        
        try:
            # Base price after variant discount
            discounted_price = Decimal(str(self.discounted_price()))
        except (TypeError, ValueError, InvalidOperation):
            discounted_price = self.original_price or Decimal('0.00')
        
        # Initialize best price options
        product_offer_price = discounted_price
        category_offer_price = discounted_price
        applied_product_offers = []
        applied_category_offers = []
        
        # Product Offers
        product_offers = self.product.product_offers.filter(is_active=True)
        for offer in product_offers:
            if offer.is_valid():
                price_after_offer = offer.apply_to_product(self.product, discounted_price)
                if isinstance(price_after_offer, tuple):
                    price_after_offer = Decimal(str(price_after_offer[0]))
                elif not isinstance(price_after_offer, Decimal):
                    price_after_offer = Decimal(str(price_after_offer))
                applied_product_offers.append({
                    'name': offer.name,
                    'original_price': discounted_price,
                    'discounted_price': price_after_offer,
                    'discount_value': offer.discount_value
                })
                product_offer_price = min(product_offer_price, price_after_offer)
        
        # Category Offers
        category = self.product.category
        all_relevant_categories = {category}
        while category.parent:
            all_relevant_categories.add(category.parent)
            category = category.parent
        
        category_offers = CategoryOffer.objects.filter(
            is_active=True,
            categories__in=all_relevant_categories
        ).distinct()
        
        for offer in category_offers:
            if offer.is_valid() and self.product.category in offer.get_all_categories():
                price_after_offer = offer.apply_to_product(self.product, discounted_price)
                if isinstance(price_after_offer, tuple):
                    price_after_offer = Decimal(str(price_after_offer[0]))
                elif not isinstance(price_after_offer, Decimal):
                    price_after_offer = Decimal(str(price_after_offer))
                applied_category_offers.append({
                    'name': offer.name,
                    'original_price': discounted_price,
                    'discounted_price': price_after_offer,
                    'discount_value': offer.discount_value
                })
                category_offer_price = min(category_offer_price, price_after_offer)
        
        # Choose the best offer (lowest price)
        final_price = min(product_offer_price, category_offer_price, discounted_price)
        applied_offer_type = (
            'product' if product_offer_price < min(category_offer_price, discounted_price)
            else 'category' if category_offer_price < discounted_price
            else 'variant'
        )
        
        return {
            'price': final_price,
            'product_offers': applied_product_offers if applied_offer_type == 'product' else [],
            'category_offers': applied_category_offers if applied_offer_type == 'category' else [],
            'original_price': self.original_price or Decimal('0.00'),
            'discounted_price': discounted_price,
            'applied_offer_type': applied_offer_type
        }

    @property
    def has_offer(self):
        if self.discount_percentage > 0:
            return True
        if self.product.product_offers.filter(is_active=True).exists():
            for offer in self.product.product_offers.filter(is_active=True):
                if offer.is_valid():
                    return True
        from offer_and_coupon_app.models import CategoryOffer
        category_offers = CategoryOffer.objects.filter(is_active=True, categories=self.product.category)
        if category_offers.exists():
            for offer in category_offers:
                if offer.is_valid():
                    return True
        if self.variant_offers.filter(is_active=True).exists():
            for offer in self.variant_offers.filter(is_active=True):
                if offer.is_valid():
                    return True
        return False

    @property
    def best_offer_percentage(self):
        if self.best_price['price'] < self.original_price:
            discount = (self.original_price - Decimal(str(self.best_price['price']))) / self.original_price * 100
            return float(discount.quantize(Decimal('0.01')))
        return 0.0

    @property
    def primary_image(self):
        return self.variant_images.filter(is_primary=True).first()

    @property
    def all_images(self):
        return self.variant_images.all()

    @property
    def image_count(self):
        return self.variant_images.count()

    def __str__(self):
        flavor = self.flavor or "Standard"
        size = self.size_weight or "N/A"
        return f"{self.product.product_name} - {flavor} - {size}"

class VariantImage(models.Model):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='variant_images')
    image = CloudinaryField('image', blank=True, null=True)
    is_primary = models.BooleanField(default=False)
    alt_text = models.CharField(max_length=200, blank=True)
    image_type = models.CharField(max_length=20, choices=[
        ('primary', 'Primary Image'),
        ('detail', 'Detail Image'),
        ('promotional', 'Promotional Image')
    ], default='primary')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def get_cloudinary_folder(self):
        product_id = self.variant.product.id if self.variant.product and self.variant.product.id else 'temp'
        return f'products/{product_id}/variants/{self.variant.id}'
        
    def save(self, *args, **kwargs):
        if self.image and not hasattr(self.image, 'public_id'):
            from cloudinary.uploader import upload
            import logging
            logger = logging.getLogger(__name__)
            try:
                folder = self.get_cloudinary_folder()
                upload_result = upload(self.image, folder=folder)
                self.image = upload_result['public_id']
            except Exception as e:
                logger.error(f"Failed to upload image to Cloudinary: {e}")
                raise
        if not self.pk and not self.variant.variant_images.exists():
            self.is_primary = True
            self.image_type = 'primary'
        if self.is_primary:
            VariantImage.objects.filter(
                variant=self.variant,
                is_primary=True
            ).exclude(id=self.id).update(is_primary=False)
        if self.is_primary and self.image_type != 'primary':
            self.image_type = 'primary'
        if not self.pk and self.variant.variant_images.count() >= 3:
            raise ValidationError("Maximum of 3 images allowed per variant.")
            
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"{self.image_type} image for {self.variant.product.product_name} - {self.variant}"
        
    class Meta:
        ordering = ['-is_primary', 'created_at']

class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.FloatField()
    title = models.CharField(max_length=100, blank=True, null=True)
    comment = models.TextField(max_length=5000)
    helpful_votes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified_purchase = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.product.product_name} - {self.rating} stars"

    def clean(self):
        if self.rating < 1.0 or self.rating > 5.0:
            raise ValidationError({'rating': 'Rating must be between 1.0 and 5.0.'})

    def clean_rating(self):
        rating = self.cleaned_data.get('rating')
        if rating is None:
            raise forms.ValidationError("Rating is required.")
        if not isinstance(rating, (int, float)) or rating < 1 or rating > 5:
            raise forms.ValidationError("Rating must be a number between 1 and 5.")
        return float(rating)

    def clean_title(self):
        title = self.cleaned_data.get('title', '')
        if len(title) > 100:
            raise forms.ValidationError("Title cannot exceed 100 characters.")
        return title

    def star_rating(self):
        full_star = '★'
        half_star = '½'
        one_third_star = '⅓'
        one_fourth_star = '¼'
        one_fifth_star = '⅕'
        empty_star = '☆'
        whole_stars = int(self.rating)
        fractional_part = self.rating - whole_stars
        stars = full_star * whole_stars
        if fractional_part >= 0.5:
            stars += half_star
        elif 0.3 <= fractional_part < 0.5:
            stars += one_third_star
        elif 0.25 <= fractional_part < 0.3:
            stars += one_fourth_star
        elif 0.2 <= fractional_part < 0.25:
            stars += one_fifth_star

        remaining_slots = 5 - whole_stars - (1 if fractional_part >= 0.2 else 0)
        stars += empty_star * remaining_slots

        return stars

    def excerpt(self, length=100):
        return self.comment[:length] + '...' if len(self.comment) > length else self.comment

    def mark_as_helpful(self):
        self.helpful_votes += 1
        self.save()

    def age(self):
        delta = timezone.now() - self.created_at
        if delta.days > 0:
            return f"{delta.days} days ago"
        elif delta.seconds > 3600:
            return f"{delta.seconds // 3600} hours ago"
        else:
            return f"{delta.seconds // 60} minutes ago"

    class Meta:
        ordering = ['-is_approved', '-created_at']
        unique_together = ('product', 'user')