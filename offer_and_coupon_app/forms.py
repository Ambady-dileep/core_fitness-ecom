from django import forms
from .models import Coupon, UserCoupon, WalletTransaction, Wallet, ProductOffer, CategoryOffer
from product_app.models import Product, ProductVariant, Category
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import timedelta

class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ['code', 'discount_percentage', 'minimum_order_amount', 'valid_from', 'valid_to', 'usage_limit', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'discount_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'minimum_order_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'valid_from': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'valid_to': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'usage_limit': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial['valid_from'] = timezone.now()
            self.initial['valid_to'] = timezone.now() + timedelta(days=30)
            self.initial['is_active'] = True

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        if not code:
            raise ValidationError("Coupon code cannot be empty.")
        return code

    def clean_discount_percentage(self):
        discount = self.cleaned_data['discount_percentage']
        if discount <= 0 or discount > 100:
            raise ValidationError("Discount percentage must be between 0.01 and 100.")
        return discount

    def clean_minimum_order_amount(self):
        amount = self.cleaned_data['minimum_order_amount']
        if amount < 0:
            raise ValidationError("Minimum order amount cannot be negative.")
        return amount

    def clean_usage_limit(self):
        limit = self.cleaned_data['usage_limit']
        if limit < 0:
            raise ValidationError("Usage limit cannot be negative.")
        return limit

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('valid_from')
        valid_to = cleaned_data.get('valid_to')
        if valid_from and valid_to and valid_to <= valid_from:
            raise ValidationError("Valid to date must be after valid from date.")
        return cleaned_data

class UserCouponForm(forms.ModelForm):
    class Meta:
        model = UserCoupon
        fields = ['user', 'coupon', 'is_used', 'used_at', 'order']
        widgets = {
            'used_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['used_at'].required = False  

class WalletTransactionForm(forms.ModelForm):
    class Meta:
        model = WalletTransaction
        fields = ['wallet', 'amount', 'transaction_type', 'description'] 
        widgets = {
            'transaction_type': forms.Select(attrs={'class': 'form-control'}, choices=WalletTransaction.TRANSACTION_TYPES),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

class WalletForm(forms.ModelForm):
    class Meta:
        model = Wallet
        fields = ['user', 'balance']  
        widgets = {
            'balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'readonly': 'readonly'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['balance'].disabled = True 

class CouponApplyForm(forms.Form):
    coupon_code = forms.CharField(max_length=20, required=True, label="Coupon Code")

    def clean_coupon_code(self):
        code = self.cleaned_data['coupon_code'].strip().upper()
        return code

class ProductOfferForm(forms.ModelForm):
    products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.all(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
        required=False
    )

    class Meta:
        model = ProductOffer
        fields = ['name', 'description', 'discount_value', 'min_purchase_amount', 'max_discount_amount', 'valid_from', 'valid_to', 'is_active', 'products']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control'}),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'min_purchase_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'max_discount_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'valid_from': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'valid_to': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class CategoryOfferForm(forms.ModelForm):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.all(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
        required=False
    )

    class Meta:
        model = CategoryOffer
        fields = ['name', 'description', 'discount_value', 'min_purchase_amount', 'max_discount_amount', 'valid_from', 'valid_to', 'is_active', 'categories', 'apply_to_subcategories']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control'}),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'min_purchase_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'max_discount_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'valid_from': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'valid_to': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'apply_to_subcategories': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }