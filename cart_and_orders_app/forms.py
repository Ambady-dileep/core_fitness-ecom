from django import forms
from django.db import models
from django.utils import timezone
from .models import Order, ReturnRequest
from offer_and_coupon_app.models import Coupon

class OrderStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['shipping_address', 'payment_method', 'coupon']
        widgets = {
            'shipping_address': forms.Select(attrs={'class': 'form-select'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'coupon': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter shipping_address to show only user's addresses
        if user:
            self.fields['shipping_address'].queryset = user.addresses.all()
            
        # Filter coupons to show only valid ones
        self.fields['coupon'].queryset = Coupon.objects.filter(
            is_active=True,
            valid_from__lte=timezone.now(),
            valid_to__gte=timezone.now()
        ).exclude(
            usage_limit__gt=0,
            usage_count__gte=models.F('usage_limit')
        )
        self.fields['coupon'].required = False

class ReturnRequestForm(forms.ModelForm):
    class Meta:
        model = ReturnRequest
        fields = ['reason']
        widgets = {
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Please explain why you want to return this order'
            }),
        }

    def clean_reason(self):
        reason = self.cleaned_data['reason']
        if len(reason) < 10:
            raise forms.ValidationError("Please provide a more detailed reason (minimum 10 characters)")
        return reason

class CouponApplyForm(forms.Form):
    coupon_code = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter coupon code'
        })
    )

    def clean_coupon_code(self):
        code = self.cleaned_data['coupon_code'].upper()
        try:
            coupon = Coupon.objects.get(code=code)
            if not coupon.is_valid:
                raise forms.ValidationError("This coupon is not valid or has expired")
        except Coupon.DoesNotExist:
            raise forms.ValidationError("Invalid coupon code")
        return code