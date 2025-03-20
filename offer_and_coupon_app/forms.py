from django import forms
from .models import Coupon, UserCoupon, WalletTransaction, Wallet
from product_app.models import ProductVariant

class CouponForm(forms.ModelForm):
    applicable_products = forms.ModelMultipleChoiceField(
        queryset=ProductVariant.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'multiple': 'multiple'}),
        label="Applicable Products"
    )

    class Meta:
        model = Coupon
        fields = ['code', 'is_active', 'valid_from', 'valid_to', 'usage_limit', 'usage_count', 
                  'minimum_order_amount', 'discount_amount', 'applicable_products']  # No created_at/updated_at
        widgets = {
            'valid_from': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'valid_to': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'usage_count': forms.NumberInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'minimum_order_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'discount_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['usage_count'].disabled = True  # Disable usage_count as it’s managed by the model

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('valid_from')
        valid_to = cleaned_data.get('valid_to')
        discount_amount = cleaned_data.get('discount_amount')
        minimum_order_amount = cleaned_data.get('minimum_order_amount')
        usage_limit = cleaned_data.get('usage_limit')

        if discount_amount and discount_amount <= 0:
            raise forms.ValidationError("Discount amount must be positive.")
        if minimum_order_amount and minimum_order_amount < 0:
            raise forms.ValidationError("Minimum order amount cannot be negative.")
        if valid_from and valid_to and valid_from >= valid_to:
            raise forms.ValidationError("Valid from date must be earlier than valid to date.")
        if usage_limit and usage_limit < 0:
            raise forms.ValidationError("Usage limit cannot be negative.")

        return cleaned_data

class UserCouponForm(forms.ModelForm):
    class Meta:
        model = UserCoupon
        fields = ['user', 'coupon', 'is_used', 'used_at', 'order']  # No timestamps needed
        widgets = {
            'used_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['used_at'].required = False  # Optional since it can be null in the model

class WalletTransactionForm(forms.ModelForm):
    class Meta:
        model = WalletTransaction
        fields = ['wallet', 'amount', 'transaction_type', 'description']  # Excludes created_at/updated_at
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