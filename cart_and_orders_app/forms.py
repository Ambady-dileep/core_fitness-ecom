from django import forms
from django.db import models
from django.utils import timezone
from offer_and_coupon_app.models import Coupon
from user_app.models import Address
from .models import Order, OrderItem, ReturnRequest, SalesReport

class OrderStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = Order.STATUS_CHOICES

class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['shipping_address', 'payment_method']
        widgets = {
            'shipping_address': forms.Select(attrs={'class': 'form-select'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
        }
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['shipping_address'].queryset = Address.objects.filter(user=user)
            default_address = Address.objects.filter(user=user, is_default=True).first()
            if default_address:
                self.fields['shipping_address'].initial = default_address

    def clean(self):
        cleaned_data = super().clean()
        shipping_address = cleaned_data.get('shipping_address')
        payment_method = cleaned_data.get('payment_method')
        
        if not shipping_address:
            raise forms.ValidationError("Please select a shipping address.")
        if payment_method not in [choice[0] for choice in Order.PAYMENT_CHOICES]:
            raise forms.ValidationError("Invalid payment method selected.")
        return cleaned_data

class OrderCancellationForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        required=False,
        label="Reason for Cancellation (Optional)"
    )


class OrderItemCancellationForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        required=False,
        label="Reason for Cancellation (Optional)"
    )
    order_item = forms.ModelChoiceField(
        queryset=OrderItem.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Select Item to Cancel"
    )

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        if order:
            self.fields['order_item'].queryset = order.items.all()

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
    def __init__(self, *args, **kwargs):
        self.order = kwargs.pop('order', None)
        super().__init__(*args, **kwargs)

    def clean_reason(self):
        reason = self.cleaned_data['reason']
        if len(reason) < 10:
            raise forms.ValidationError("Please provide a more detailed reason (minimum 10 characters)")
        return reason

    def clean(self):
        cleaned_data = super().clean()
        if self.order and self.order.status != 'Delivered':
            raise forms.ValidationError("This order cannot be returned as it has not been delivered.")
        return cleaned_data

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
            if not coupon.is_valid():
                raise forms.ValidationError("This coupon is not valid or has expired")
            # Store the coupon object for use in views
            self.cleaned_data['coupon'] = coupon
        except Coupon.DoesNotExist:
            raise forms.ValidationError("Invalid coupon code")
        return code
    

class SalesReportForm(forms.Form):
    report_type = forms.ChoiceField(choices=SalesReport.REPORT_TYPES, widget=forms.RadioSelect)
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
        help_text="Required for custom range"
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
        help_text="Required for custom range"
    )
    export = forms.BooleanField(
        required=False,
        label="Export to CSV",
        initial=False
    )
    
    def clean(self):
        cleaned_data = super().clean()
        report_type = cleaned_data.get('report_type')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if report_type == 'CUSTOM':
            if not start_date:
                self.add_error('start_date', 'Start date is required for custom range')
            if not end_date:
                self.add_error('end_date', 'End date is required for custom range')
            if start_date and end_date and start_date > end_date:
                self.add_error('end_date', 'End date must be after start date')
                
        return cleaned_data