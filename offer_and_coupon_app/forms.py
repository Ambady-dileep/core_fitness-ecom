# offer_and_coupon_app/forms.py
from django import forms
from .models import Coupon, UserCoupon, WalletTransaction, Wallet, ProductOffer, CategoryOffer
from product_app.models import Product, ProductVariant, Category
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal

class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ['code', 'is_active', 'valid_from', 'valid_to', 'usage_limit', 
                  'minimum_order_amount', 'discount_amount', 'applicable_products']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'valid_from': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'valid_to': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'usage_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'minimum_order_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'discount_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'applicable_products': forms.SelectMultiple(attrs={'class': 'select2'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('valid_from')
        valid_to = cleaned_data.get('valid_to')
        discount_amount = cleaned_data.get('discount_amount')
        minimum_order_amount = cleaned_data.get('minimum_order_amount')
        usage_limit = cleaned_data.get('usage_limit')
        code = cleaned_data.get('code')

        if valid_from and valid_to:
            if valid_from >= valid_to:
                raise ValidationError("Start date must be before end date")

        if discount_amount is not None and discount_amount <= 0:
            raise ValidationError({"discount_amount": "Discount amount must be positive."})
        if minimum_order_amount is not None and minimum_order_amount < 0:
            raise ValidationError({"minimum_order_amount": "Minimum order amount cannot be negative."})
        if usage_limit is not None and usage_limit < 0:
            raise ValidationError({"usage_limit": "Usage limit cannot be negative."})

        # Coupon code format (optional: enforce alphanumeric and uppercase)
        if code and not code.isalnum():
            raise ValidationError({"code": "Coupon code must be alphanumeric."})
        if code:
            cleaned_data['code'] = code.upper()  # Ensure uppercase in form

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
        fields = ['user', 'balance']  # Excludes created_at/updated_at
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