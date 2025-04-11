from django import forms
import logging
from .models import Category, Review, Brand
from cloudinary.forms import CloudinaryFileField

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
            if len(data) > 10:
                raise forms.ValidationError("You can upload a maximum of 10 images.")
            if any(file.size > 10 * 1024 * 1024 for file in data):  # 10MB limit
                raise forms.ValidationError("Each image must be under 10MB.")
            return [super().clean(d, initial) for d in data]
        return [super().clean(data, initial)]


class ProductFilterForm(forms.Form):
    search = forms.CharField(
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search products...'})
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    brand = forms.ModelChoiceField(
        queryset=Brand.objects.none(),
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
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Category
        fields = ['name', 'description', 'image', 'parent', 'brands', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'parent': forms.Select(attrs={'class': 'form-control'}),
            'brands': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent'].queryset = Category.objects.filter(is_active=True).exclude(id=self.instance.id if self.instance.pk else None)
        self.fields['brands'].queryset = Brand.objects.filter(is_active=True, is_deleted=False)

    def clean_parent(self):
        parent = self.cleaned_data.get('parent')
        if parent and self.instance.pk:
            current = parent
            while current:
                if current.id == self.instance.id:
                    raise forms.ValidationError("A category cannot be a parent of itself.")
                current = current.parent
        return parent   

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        parent = cleaned_data.get('parent')
        if name and Category.objects.filter(name=name, parent=parent).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A category with this name and parent already exists.")
        return cleaned_data


class BrandForm(forms.ModelForm):
    logo = CloudinaryFileField(
        options={'folder': 'brands', 'quality': 'auto'}, 
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = Brand
        fields = ['name', 'description', 'logo', 'website', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brand Name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Brand Description', 'rows': 3}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://example.com'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def clean_name(self):
        name = self.cleaned_data['name']
        if Brand.objects.filter(name__iexact=name).exclude(id=self.instance.id if self.instance.id else None).exists():
            raise forms.ValidationError("A brand with this name already exists.")
        return name

    def save(self, commit=True):
        brand = super().save(commit=commit)
        if brand.is_deleted and brand.is_active:
            brand.is_deleted = False
            if commit:
                brand.save(update_fields=['is_deleted'])
        return brand
    
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
    
