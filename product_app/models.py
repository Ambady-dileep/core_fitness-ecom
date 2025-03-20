from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from PIL import Image
from django.db.models import Min, Max, Sum, Avg

# Get the user model (CustomUser from user_app)
User = get_user_model()

# Helper functions for file paths
def product_image_path(instance, filename):
    """Generate a path for product images based on product ID."""
    return f'products/{instance.product.id}/{filename}'

def category_image_path(instance, filename):
    """Generate a path for category images."""
    return f'categories/{instance.name}/{filename}'

def variant_image_path(instance, filename):
    """Generate a path for variant images."""
    return f'products/{instance.variant.product.id}/variants/{instance.variant.id}/{filename}'

class Category(models.Model):
    """Category for organizing products."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to=category_image_path, blank=True, null=True)
    parent = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL,  
        blank=True,
        null=True,
        related_name='subcategories'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Automatically generate a slug if not provided."""
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Category.objects.filter(slug=slug).exclude(id=self.id).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"
        unique_together = ('name', 'parent')

class Tag(models.Model):
    """Tags for categorizing products."""
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)

    def save(self, *args, **kwargs):
        """Automatically generate a slug if not provided."""
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Tag"
        verbose_name_plural = "Tags"

class Product(models.Model):
    """Main product model."""
    product_name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    brand = models.CharField(max_length=100, default="Unknown")
    description = models.TextField(default='No description available')
    tags = models.ManyToManyField(Tag, blank=True, related_name='products')
    is_active = models.BooleanField(default=True)
    average_rating = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Automatically generate a unique slug."""
        if not self.slug:
            base_slug = slugify(self.product_name)
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exclude(id=self.id).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def primary_image(self):
        """Return the primary image of the product."""
        return self.product_images.filter(is_primary=True).first()

    def update_average_rating(self):
        """Update the average rating based on approved reviews."""
        avg = self.reviews.filter(is_approved=True).aggregate(Avg('rating'))['rating__avg']
        self.average_rating = avg if avg is not None else 0.0
        self.save(update_fields=['average_rating'])

    @property
    def min_price(self):
        """Return the minimum price among variants."""
        return self.variants.aggregate(Min('price'))['price__min'] or 0

    @property
    def max_price(self):
        """Return the maximum price among variants."""
        return self.variants.aggregate(Max('price'))['price__max'] or 0

    @property
    def total_stock(self):
        """Return the total stock across all variants."""
        return self.variants.aggregate(Sum('stock'))['stock__sum'] or 0
    
    @property
    def all_images(self):
        """Return all images of the product."""
        return self.product_images.all()
    
    def has_user_reviewed(self, user):
        """Check if a user has reviewed this product."""
        return self.reviews.filter(user=user).exists()
    
    def approved_reviews(self):
        """Return approved reviews for this product."""
        return self.reviews.filter(is_approved=True)

    def __str__(self):
        return self.product_name

class ProductImage(models.Model):
    """Images associated with a product."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='product_images')
    image = models.ImageField(upload_to=product_image_path)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """Process and resize the uploaded image, ensure only one primary image."""
        if self.is_primary:
            ProductImage.objects.filter(product=self.product, is_primary=True).exclude(id=self.id).update(is_primary=False)
        super().save(*args, **kwargs)
        self.process_image()

    def process_image(self):
        """Resize and optimize the image."""
        img = Image.open(self.image.path)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        target_size = (800, 800)
        width, height = img.size
        if width != height:
            size = min(width, height)
            left = (width - size) // 2
            top = (height - size) // 2
            img = img.crop((left, top, left + size, top + size))
        img = img.resize(target_size, Image.Resampling.LANCZOS)
        img.save(self.image.path, quality=85)

    def __str__(self):
        return f"Image for {self.product.product_name}"

class ProductVariant(models.Model):
    """Variants of a product (e.g., different flavors or sizes)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=100, unique=True, blank=True, null=True)
    flavor = models.CharField(max_length=100, blank=True, null=True)
    size_weight = models.CharField(max_length=50, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Automatically generate a unique SKU."""
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
    def image(self):
        """Return the first associated variant image."""
        return self.variant_images.first()

    def __str__(self):
        flavor = self.flavor or "Standard"
        size = self.size_weight or "N/A"
        return f"{self.product.product_name} - {flavor} - {size}"

class VariantImage(models.Model):
    """Images associated with a product variant."""
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='variant_images')
    image = models.ImageField(upload_to=variant_image_path)
    alt_text = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """Process and resize the uploaded image."""
        super().save(*args, **kwargs)
        self.process_image()

    def process_image(self):
        """Resize and optimize the image."""
        img = Image.open(self.image.path)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        target_size = (800, 800)
        width, height = img.size
        if width != height:
            size = min(width, height)
            left = (width - size) // 2
            top = (height - size) // 2
            img = img.crop((left, top, left + size, top + size))
        img = img.resize(target_size, Image.Resampling.LANCZOS)
        img.save(self.image.path, quality=85)

    def __str__(self):
        return f"Image for {self.variant}"

class Review(models.Model):
    """User reviews for products."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    title = models.CharField(max_length=100, blank=True, null=True)
    comment = models.TextField()
    helpful_votes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified_purchase = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.product.product_name} - {self.rating} stars"
    
    def clean(self):
        """Validate rating range."""
        if self.rating < 1 or self.rating > 5:
            raise ValidationError({'rating': 'Rating must be between 1 and 5.'})

    def star_rating(self):
        """Return a string representation of the rating with stars."""
        full_star = '★'
        empty_star = '☆'
        return full_star * self.rating + empty_star * (5 - self.rating)

    def excerpt(self, length=100):
        """Return a truncated version of the comment."""
        return self.comment[:length] + '...' if len(self.comment) > length else self.comment

    def mark_as_helpful(self):
        """Increment helpful votes."""
        self.helpful_votes += 1
        self.save()

    def age(self):
        """Return how long ago the review was posted."""
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