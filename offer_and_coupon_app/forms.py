from django import forms
from .models import Coupon, UserCoupon, WalletTransaction, Wallet
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import timedelta

class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ['code', 'discount_percentage', 'minimum_order_amount', 'max_discount_amount', 'valid_from', 'valid_to']
        widgets = {
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter coupon code (will be automatically uppercase)'
            }),
            'discount_percentage': forms.NumberInput(attrs={
                'class': 'form-control', 
                'step': '0.01',
                'min': '0.01',
                'max': '50',
                'placeholder': 'Enter value between 0.01 and 50'
            }),
            'minimum_order_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Minimum order amount to apply coupon'
            }),
            'max_discount_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Enter 0 for no maximum limit'
            }),
            'valid_from': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'valid_to': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default values for valid_from and valid_to
        current_time = timezone.now()
        if not self.instance.pk:  # New coupon
            self.initial['valid_from'] = current_time
            self.initial['valid_to'] = current_time + timedelta(days=30)
        else:  # Editing existing coupon
            if self.instance.valid_to <= current_time:
                self.initial['valid_to'] = current_time + timedelta(days=30)

        # Add help text and error messages
        self.fields['code'].error_messages = {
            'required': 'Please enter a coupon code',
            'unique': 'This coupon code already exists'
        }
        self.fields['discount_percentage'].error_messages = {
            'required': 'Please enter a discount percentage',
            'min_value': 'Discount must be at least 0.01%',
            'max_value': 'Discount cannot exceed 50%'
        }

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        if not code:
            raise ValidationError("Coupon code cannot be empty.")
        
        # Check uniqueness but ignore the current instance if editing
        if Coupon.objects.filter(code=code).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This coupon code already exists.")
            
        return code

    def clean_discount_percentage(self):
        discount = self.cleaned_data['discount_percentage']
        if discount <= 0 or discount > 50: 
            raise ValidationError("Discount percentage must be between 0.01 and 50.")
        return discount

    def clean_minimum_order_amount(self):
        amount = self.cleaned_data['minimum_order_amount']
        if amount < 0:
            raise ValidationError("Minimum order amount cannot be negative.")
        return amount

    def clean_max_discount_amount(self):
        amount = self.cleaned_data['max_discount_amount']
        if amount < 0:
            raise ValidationError("Maximum discount amount cannot be negative.")
        return amount
    
    def clean_valid_from(self):
        valid_from = self.cleaned_data.get('valid_from')
        if valid_from and valid_from < timezone.now():
            raise ValidationError("Valid from date cannot be in the past.")
        return valid_from

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('valid_from')
        valid_to = cleaned_data.get('valid_to')
        minimum_order_amount = cleaned_data.get('minimum_order_amount')
        max_discount_amount = cleaned_data.get('max_discount_amount')

        # Validate dates
        if valid_from and valid_to and valid_to <= valid_from:
            self.add_error('valid_to', "Valid to date must be after valid from date.")

        # Validate amounts: Minimum Order Amount must be greater than Maximum Discount Amount
        if minimum_order_amount is not None and max_discount_amount is not None:
            if max_discount_amount > 0 and minimum_order_amount < max_discount_amount:
                self.add_error('minimum_order_amount', "Minimum order amount must be greater than maximum discount amount.")

        # Auto-set is_active to True for new coupons or keep existing value
        if not self.instance.pk:
            cleaned_data['is_active'] = True
            
        return cleaned_data

    def save(self, commit=True):
        coupon = super().save(commit=False)
        # For new coupons, ensure is_active is set to True
        if not self.instance.pk:
            coupon.is_active = True
        if commit:
            coupon.save()
        return coupon

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
            'description': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise ValidationError("Amount must be greater than 0.")
        return amount

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
    coupon_code = forms.CharField(max_length=50, required=True, label="Coupon Code")

    def clean_coupon_code(self):
        code = self.cleaned_data['coupon_code'].strip().upper()
        try:
            coupon = Coupon.objects.get(code=code)
            if not coupon.is_valid():
                raise ValidationError("This coupon is not valid or has expired.")
        except Coupon.DoesNotExist:
            raise ValidationError("Invalid coupon code.")
        return code
