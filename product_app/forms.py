from django import forms
import logging
from .models import Category, Review, Brand
from cloudinary.forms import CloudinaryFileField
from django.forms import formset_factory
from django.core.exceptions import ValidationError
from .models import Category, Brand, Product, ProductVariant, VariantImage
from django.utils.text import slugify
import re

logger = logging.getLogger(__name__)

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data and self.required:
            raise forms.ValidationError("This field is required.")
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            if len(data) > 3:
                raise forms.ValidationError("You can upload a maximum of 3 images per variant.")
            if any(file.size > 10 * 1024 * 1024 for file in data):
                raise forms.ValidationError("Each image must be under 10MB.")
            return [super().clean(d, initial) for d in data]
        return [super().clean(data, initial)]

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['product_name', 'category', 'brand', 'description', 'country_of_manufacture']
        widgets = {
            'product_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter product name'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Enter product description'}),
            'country_of_manufacture': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter country of manufacture'}),
        }

    def clean_product_name(self):
        product_name = self.cleaned_data['product_name'].strip()
        if not product_name:
            raise forms.ValidationError("Product name is required.")
        if len(product_name) < 2 or len(product_name) > 200:
            raise forms.ValidationError("Product name must be between 2 and 200 characters.")
        if not re.match(r'^[A-Za-z0-9\s\-\&\(\)]+$', product_name):
            raise forms.ValidationError("Product name can only contain letters, numbers, spaces, hyphens, ampersands, and parentheses.")
        slug = slugify(product_name)
        if Product.objects.filter(slug=slug).exclude(id=self.instance.id if self.instance else None).exists():
            raise forms.ValidationError("A product with this name already exists.")
        return product_name

    def clean_description(self):
        description = self.cleaned_data.get('description')
        if description and len(description) > 2000:
            raise forms.ValidationError("Description cannot exceed 2000 characters.")
        return description

    def clean_country_of_manufacture(self):
        country = self.cleaned_data.get('country_of_manufacture')
        if country and len(country) > 100:
            raise forms.ValidationError("Country of manufacture cannot exceed 100 characters.")
        return country

    def clean(self):
        cleaned_data = super().clean()
        brand = cleaned_data.get('brand')
        category = cleaned_data.get('category')
        if brand and category and category not in brand.categories.all():
            # Automatically add category to brand (handled in model save)
            pass
        return cleaned_data

class ProductVariantForm(forms.ModelForm):
    images = MultipleFileField(required=False, label="Variant Images")
    primary_image = forms.CharField(required=False, widget=forms.HiddenInput())
    delete_image_ids = forms.CharField(required=False, widget=forms.HiddenInput())
    variant_id = forms.CharField(required=False, widget=forms.HiddenInput())  

    class Meta:
        model = ProductVariant
        fields = ['flavor', 'size_weight', 'original_price', 'offer_percentage', 'stock']
        widgets = {
            'flavor': forms.Select(attrs={'class': 'form-select'}),
            'size_weight': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 500g'}),
            'original_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'offer_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100', 'placeholder': 'Leave blank for no offer (0.00%)', 'value': '0.00'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

    def clean_variant_id(self):
        variant_id = self.cleaned_data.get('variant_id')
        if variant_id == '':
            return None
        if variant_id and not variant_id.isdigit():
            raise forms.ValidationError("Variant ID must be a valid number.")
        return variant_id

    def clean_flavor(self):
        flavor = self.cleaned_data.get('flavor')
        if flavor == '':
            return None
        return flavor

    def clean_size_weight(self):
        size_weight = self.cleaned_data.get('size_weight')
        if size_weight and len(size_weight) > 50:
            raise forms.ValidationError("Size/Weight cannot exceed 50 characters.")
        return size_weight

    def clean_offer_percentage(self):
        offer_percentage = self.cleaned_data.get('offer_percentage')
        if offer_percentage is None or offer_percentage == '':
            return 0.00
        return offer_percentage

    def clean(self):
        cleaned_data = super().clean()
        images = cleaned_data.get('images', [])
        delete_image_ids = cleaned_data.get('delete_image_ids', '').split(',')
        delete_image_ids = [id for id in delete_image_ids if id.isdigit()]
        existing_images = 0
        if self.instance and self.instance.pk:
            existing_images = self.instance.variant_images.exclude(id__in=delete_image_ids).count()
        total_images = existing_images + len(images)
        
        if total_images < 1:
            raise forms.ValidationError("At least one image is required for the variant.")
        if total_images > 3:
            raise forms.ValidationError("Maximum of 3 images allowed per variant.")
        if total_images > 1 and not cleaned_data.get('primary_image'):
            raise forms.ValidationError("Please select a primary image.")
        return cleaned_data

# Variant Formset
ProductVariantFormSet = formset_factory(ProductVariantForm, extra=1, can_delete=True)

# Product Filter Form (unchanged)
class ProductFilterForm(forms.Form):
    search = forms.CharField(
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search products...'})
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    brand = forms.ModelChoiceField(
        queryset=Brand.objects.filter(is_active=True),
        required=False,
        empty_label="All Brands",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    min_price = forms.DecimalField(required=False, widget=forms.HiddenInput())
    max_price = forms.DecimalField(required=False, widget=forms.HiddenInput())

class CategoryForm(forms.ModelForm):
    image = CloudinaryFileField(
        options={'folder': 'categories', 'quality': 'auto'},
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'})
    )

    class Meta:
        model = Category
        fields = ['name', 'description', 'image', 'brands', 'offer_percentage', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter category name'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Enter category description'}),
            'offer_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100', 'placeholder': 'Leave blank for no offer (0.00%)', 'value': '0.00'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'required': 'required',
            'minlength': '2',
            'maxlength': '100',
            'pattern': r'^[A-Za-z0-9\s\-\&]+$'
        })
        self.fields['description'].widget.attrs.update({
            'maxlength': '500'
        })
        self.fields['offer_percentage'].widget.attrs.update({
            'placeholder': 'Enter offer percentage (0-100)',
            'required': 'required'
        })

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name:
            raise ValidationError("Category name is required.")
        if len(name) < 2:
            raise ValidationError("Category name must be at least 2 characters long.")
        if len(name) > 100:
            raise ValidationError("Category name cannot exceed 100 characters.")
        if not re.match(r'^[A-Za-z0-9\s\-\&]+$', name):
            raise ValidationError("Category name can only contain letters, numbers, spaces, hyphens, and ampersands.")
        if Category.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError("A category with this name already exists.")
        return name

    def clean_description(self):
        description = self.cleaned_data.get('description')
        if description and len(description) > 500:
            raise ValidationError("Description cannot exceed 500 characters.")
        return description

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image:
            if hasattr(image, 'size'):
                if image.size > 5 * 1024 * 1024:
                    raise ValidationError("Image file size must not exceed 5MB.")
                if not image.content_type.startswith('image/'):
                    raise ValidationError("File must be a valid image (JPEG, PNG, etc.).")
        return image

    def clean_brands(self):
        brands = self.cleaned_data.get('brands')
        if brands.count() > 50:
            raise ValidationError("Cannot associate more than 50 brands with a category.")
        return brands

    def clean_offer_percentage(self):
        offer_percentage = self.cleaned_data.get('offer_percentage')
        if offer_percentage is None or offer_percentage == '':
            return 0.00
        return offer_percentage

class BrandForm(forms.ModelForm):
    logo = CloudinaryFileField(
        options={'folder': 'brands', 'quality': 'auto'}, 
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'})
    )
    
    class Meta:
        model = Brand
        fields = ['name', 'description', 'logo', 'website', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Brand Name',
                'required': 'required',
                'minlength': '2',
                'maxlength': '100',
                'pattern': r'^[A-Za-z0-9\s\-\&]+$'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 
                'placeholder': 'Brand Description', 
                'rows': 3,
                'maxlength': '500'
            }),
            'website': forms.URLInput(attrs={
                'class': 'form-control', 
                'placeholder': 'https://example.com',
                'pattern': r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name:
            raise ValidationError("Brand name is required.")
        if len(name) < 2:
            raise ValidationError("Brand name must be at least 2 characters long.")
        if len(name) > 100:
            raise ValidationError("Brand name cannot exceed 100 characters.")
        if not re.match(r'^[A-Za-z0-9\s\-\&]+$', name):
            raise ValidationError("Brand name can only contain letters, numbers, spaces, hyphens, and ampersands.")
        if Brand.objects.filter(name__iexact=name).exclude(id=self.instance.id if self.instance.id else None).exists():
            raise ValidationError("A brand with this name already exists.")
        return name

    def clean_description(self):
        description = self.cleaned_data.get('description')
        if description and len(description) > 500:
            raise ValidationError("Description cannot exceed 500 characters.")
        return description

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo:
            if hasattr(logo, 'size'): 
                if logo.size > 5 * 1024 * 1024: 
                    raise ValidationError("Logo file size must not exceed 5MB.")
                if not logo.content_type.startswith('image/'):
                    raise ValidationError("File must be a valid image (JPEG, PNG, etc.).")
        return logo

    def clean_website(self):
        website = self.cleaned_data.get('website')
        if website:
            if not re.match(r'^https?://[^\s<>"]+|www\.[^\s<>"]+$', website):
                raise ValidationError("Please enter a valid URL (e.g., https://example.com).")
            if len(website) > 200:
                raise ValidationError("Website URL cannot exceed 200 characters.")
        return website

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'title', 'comment']
        widgets = {
            'rating': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '1.0', 'max': '5.0'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter review title'}),
            'comment': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Write your review here'}),
        }

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

    def clean_comment(self):
        comment = self.cleaned_data['comment']
        if len(comment) < 10:
            raise forms.ValidationError("Comment must be at least 10 characters long.")
        if len(comment) > 5000:
            raise forms.ValidationError("Comment cannot exceed 5000 characters.")
        return comment