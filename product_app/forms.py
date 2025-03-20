from django import forms
from django.forms import inlineformset_factory
from .models import Product, ProductVariant, Category, Tag, Review, ProductImage, VariantImage


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description', 'image', 'parent', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent'].queryset = Category.objects.filter(is_active=True)


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ProductForm(forms.ModelForm):
    images = MultipleFileField(
        label="Product Images",
        help_text="Upload at least 3 images for the product.",
        required=True,
        widget=MultipleFileInput(attrs={
            'multiple': True,
            'accept': 'image/*',
            'class': 'form-control'
        })
    )
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.all(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False
    )

    class Meta:
        model = Product
        fields = [
            'product_name',
            'category',
            'brand',
            'description',
            'tags',
            'is_active',
        ]
        widgets = {
            'product_name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'brand': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'product_name': "Product Name",
            'category': "Category",
            'brand': "Brand",
            'description': "Description",
            'tags': "Tags",
            'is_active': "Active",
        }

    def clean_product_name(self):
        product_name = self.cleaned_data['product_name']
        if Product.objects.filter(product_name=product_name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A product with this name already exists.")
        return product_name

    def clean_images(self):
        images = self.cleaned_data['images']
        if not isinstance(images, list):
            images = [images]  # Ensure images is always a list
        if len(images) < 3:
            raise forms.ValidationError("You must upload at least 3 images.")
        for image in images:
            if not image.content_type.startswith('image/'):
                raise forms.ValidationError(f"{image.name} is not a valid image file.")
        return images

    def save(self, commit=True):
        product = super().save(commit=False)
        if commit:
            product.save()
            self.save_m2m()  # Save the tags (many-to-many field)
            # Save the images
            images = self.cleaned_data['images']
            for i, image in enumerate(images):
                ProductImage.objects.create(
                    product=product,
                    image=image,
                    is_primary=(i == 0)  # First image is primary
                )
        return product


class ProductVariantForm(forms.ModelForm):
    """
    Form for creating/updating a ProductVariant.
    Includes a single mandatory image field.
    """
    variant_image = forms.ImageField(
        widget=forms.ClearableFileInput(attrs={
            'accept': 'image/*',
            'class': 'form-control'
        }),
        label="Variant Image",
        help_text="Upload exactly one image for this variant.",
        required=True
    )

    class Meta:
        model = ProductVariant
        fields = [
            'flavor',
            'size_weight',
            'price',
            'stock',
            'is_active',
        ]
        widgets = {
            'flavor': forms.TextInput(attrs={'class': 'form-control'}),
            'size_weight': forms.TextInput(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'flavor': "Flavor",
            'size_weight': "Size/Weight",
            'price': "Price",
            'stock': "Stock",
            'is_active': "Active",
        }

    def clean_variant_image(self):
        image = self.cleaned_data['variant_image']
        if not image.content_type.startswith('image/'):
            raise forms.ValidationError("The uploaded file is not a valid image.")
        return image

    def clean(self):
        cleaned_data = super().clean()
        flavor = cleaned_data.get('flavor')
        size_weight = cleaned_data.get('size_weight')

        # Only validate uniqueness if the product is assigned
        if hasattr(self.instance, 'product') and self.instance.product and flavor and size_weight:
            if ProductVariant.objects.filter(
                product=self.instance.product,
                flavor=flavor,
                size_weight=size_weight
            ).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("A variant with this flavor and size/weight already exists.")
        return cleaned_data

    def save(self, commit=True):
        variant = super().save(commit=False)
        if commit:
            variant.save()
            # Save the variant image
            image = self.cleaned_data['variant_image']
            VariantImage.objects.create(
                variant=variant,
                image=image,
                alt_text=f"{variant.product.product_name} - {variant.flavor} - {variant.size_weight}"
            )
        return variant


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'title', 'comment']
        widgets = {
            'rating': forms.Select(choices=[(i, str(i)) for i in range(1, 6)], attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter review title'}),
            'comment': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Write your review here'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure the rating field is required
        self.fields['rating'].required = True
        # Add custom validation for rating (optional, since ModelForm uses model constraints)
        self.fields['rating'].validators = []

    def clean_rating(self):
        """Custom validation to ensure rating is between 1 and 5 (handled by model, but added for form-level check)."""
        rating = self.cleaned_data['rating']
        if rating < 1 or rating > 5:
            raise forms.ValidationError("Rating must be between 1 and 5.")
        return rating

class ProductFilterForm(forms.Form):
    """
    Form for filtering products on a listing page.
    """
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search products...'})
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    brand = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    min_price = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    max_price = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    is_active = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].empty_label = "All Categories"

ProductVariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    extra=1,
    can_delete=True,
)