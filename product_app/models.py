from django.db import models
from django.utils import timezone
from decimal import Decimal, ROUND_UP
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
    brands = models.ManyToManyField('Brand', related_name='categories', blank=True)
    offer_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Offer percentage for all products in this category"
    )
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
        if self.offer_percentage is None or self.offer_percentage == '':
            self.offer_percentage = 0.00
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"

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
    average_rating = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(5.0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"

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
    
    @property
    def primary_image(self):
        primary_variant = self.primary_variant
        if primary_variant:
            return primary_variant.primary_image
        return None
    
    @property
    def review_count(self):
        """Return the number of approved reviews."""
        return self.reviews.filter(is_approved=True).count()
    
    def update_average_rating(self):
        approved_reviews = self.reviews.filter(is_approved=True)
        avg_rating = approved_reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0
        # Update the average_rating field directly
        self.average_rating = round(float(avg_rating), 1) if avg_rating else 0.0
        self.save(update_fields=['average_rating'])

    def min_price(self):
        variants = self.variants.filter(is_active=True)
        if not variants.exists():
            return 0
        return min(variant.best_price['price'] for variant in variants)

    def max_price(self):
        variants = self.variants.filter(is_active=True)
        if not variants.exists():
            return 0
        return max(variant.best_price['price'] for variant in variants)

    def total_stock(self):
        return self.variants.filter(is_active=True).aggregate(total_stock=Sum('stock'))['total_stock'] or 0

    @property
    def all_variant_images(self):
        variants = self.variants.prefetch_related('variant_images')
        return [img for variant in variants for img in variant.variant_images.all()]

    def has_user_reviewed(self, user):
        return self.reviews.filter(user=user).exists()

    def approved_reviews(self):
        return self.reviews.filter(is_approved=True)
    
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
    offer_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Product-specific offer percentage",
        blank=True
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
    
    @property
    def best_price(self):
        category_offer = self.product.category.offer_percentage or 0
        product_offer = self.offer_percentage or 0

        # Keep all values as Decimal
        category_offer = Decimal(category_offer)
        product_offer = Decimal(product_offer)
        max_discount = max(category_offer, product_offer)

        discount_multiplier = Decimal('1.0') - (max_discount / Decimal('100'))

        # ROUND UP to the nearest integer
        price = (self.original_price * discount_multiplier).quantize(Decimal('1'), rounding=ROUND_UP)

        applied_offer_type = 'category' if category_offer >= product_offer else 'product'

        return {
            'price': price,  
            'original_price': self.original_price,
            'applied_offer_type': applied_offer_type
        }
    
    

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
    rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating from 1 to 5 stars"
    )
    title = models.CharField(max_length=100, blank=True, null=True)
    comment = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified_purchase = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.product.product_name} - {self.rating} stars"

    def excerpt(self, length=100):
        return self.comment[:length] + '...' if len(self.comment) > length else self.comment

    @property
    def star_rating(self):
        """Return a dictionary for star rendering in templates."""
        whole_stars = self.rating
        return {
            'whole_stars': whole_stars,
            'empty_stars': 5 - whole_stars
        }

    @property
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