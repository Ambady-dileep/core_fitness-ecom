from django import forms
from .models import Coupon, UserCoupon, WalletTransaction, Wallet
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import timedelta
from datetime import timedelta, datetime

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
            'valid_from': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'valid_to': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_date = timezone.now().date()
        if not self.instance.pk:  # New coupon
            self.initial['valid_from'] = current_date
            self.initial['valid_to'] = current_date + timedelta(days=30)
        else:  # Editing existing coupon
            if self.instance.valid_to.date() <= current_date:
                self.initial['valid_to'] = current_date + timedelta(days=30)
            # Convert existing DateTimeField to date for form display
            self.initial['valid_from'] = self.instance.valid_from.date()
            self.initial['valid_to'] = self.instance.valid_to.date()

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        if not code:
            raise ValidationError("Coupon code cannot be empty.")
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
        current_date = timezone.now().date()
        if valid_from:
            # If valid_from is a datetime (e.g., from existing instance), convert to date
            if isinstance(valid_from, datetime):
                valid_from = valid_from.date()
            if valid_from < current_date:
                raise ValidationError("Valid from date cannot be in the past.")
        return valid_from

    def clean_valid_to(self):
        valid_to = self.cleaned_data.get('valid_to')
        valid_from = self.cleaned_data.get('valid_from')
        if valid_to and isinstance(valid_to, datetime):
            valid_to = valid_to.date()
        if valid_from and isinstance(valid_from, datetime):
            valid_from = valid_from.date()
        if valid_from and valid_to and valid_to <= valid_from:
            raise ValidationError("Valid to date must be after valid from date.")
        return valid_to

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('valid_from')
        valid_to = cleaned_data.get('valid_to')
        minimum_order_amount = cleaned_data.get('minimum_order_amount')
        max_discount_amount = cleaned_data.get('max_discount_amount')

        if valid_from and valid_to:
            # Ensure both are dates for comparison
            valid_from_date = valid_from.date() if isinstance(valid_from, datetime) else valid_from
            valid_to_date = valid_to.date() if isinstance(valid_to, datetime) else valid_to
            if valid_to_date <= valid_from_date:
                self.add_error('valid_to', "Valid to date must be after valid from date.")

        if minimum_order_amount is not None and max_discount_amount is not None:
            if max_discount_amount > 0 and minimum_order_amount < max_discount_amount:
                self.add_error('minimum_order_amount', "Minimum order amount must be greater than maximum discount amount.")

        if not self.instance.pk:
            cleaned_data['is_active'] = True
            
        return cleaned_data

    def save(self, commit=True):
        coupon = super().save(commit=False)
        # Convert date to datetime (start of day in IST)
        if self.cleaned_data['valid_from']:
            valid_from = self.cleaned_data['valid_from']
            if isinstance(valid_from, datetime):
                valid_from = valid_from.date()
            coupon.valid_from = timezone.make_aware(
                datetime.combine(valid_from, datetime.min.time()),
                timezone=timezone.get_current_timezone()
            )
        if self.cleaned_data['valid_to']:
            valid_to = self.cleaned_data['valid_to']
            if isinstance(valid_to, datetime):
                valid_to = valid_to.date()
            # Set valid_to to end of day
            coupon.valid_to = timezone.make_aware(
                datetime.combine(valid_to, datetime.max.time()),
                timezone=timezone.get_current_timezone()
            )
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
