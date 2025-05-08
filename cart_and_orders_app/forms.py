from django import forms
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
    REASON_CHOICES = [
        ('Defective', 'Defective Product'),
        ('Wrong Item', 'Wrong Item Delivered'),
        ('Changed Mind', 'Changed My Mind'),
        ('Other', 'Other'),
    ]
    
    items = forms.ModelMultipleChoiceField(
        queryset=OrderItem.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=True,
        label="Select Items to Cancel"
    )
    reason = forms.ChoiceField(
        choices=REASON_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True,
        label="Reason for Cancellation"
    )
    other_reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        required=False,
        label="Additional Details (if Other is selected)"
    )

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        if order:
            self.fields['items'].queryset = order.items.filter(cancellations__isnull=True)
            self.fields['items'].label = f"Select items to cancel from order {order.order_id}"

    def clean(self):
        cleaned_data = super().clean()
        items = cleaned_data.get('items')
        reason = cleaned_data.get('reason')
        other_reason = cleaned_data.get('other_reason')

        if not items:
            raise forms.ValidationError("Please select at least one item to cancel.")
        
        for item in items:
            if item.cancellations.exists():
                raise forms.ValidationError(f"Item {item.variant.product.product_name} is already cancelled.")
        
        if reason == "Other" and not other_reason:
            raise forms.ValidationError("Please provide additional details for 'Other' reason.")
        
        if reason == "Other" and other_reason:
            cleaned_data['combined_reason'] = f"Other: {other_reason}"
        else:
            cleaned_data['combined_reason'] = reason
        
        return cleaned_data

class ReturnRequestForm(forms.ModelForm):
    items = forms.ModelMultipleChoiceField(
        queryset=OrderItem.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Items to Return"
    )

    class Meta:
        model = ReturnRequest
        fields = ['reason', 'items']
        widgets = {
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Please explain why you want to return this order'
            }),
        }

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        if order:
            self.order = order
            self.fields['items'].queryset = self.order.items.filter(variant__is_active=True)
            self.fields['items'].label = "Select items to return (leave unchecked for full order return)"

    def clean_reason(self):
        reason = self.cleaned_data['reason']
        if len(reason) < 10:
            raise forms.ValidationError("Please provide a more detailed reason (minimum 10 characters)")
        return reason

    def clean(self):
        cleaned_data = super().clean()
        items = cleaned_data.get('items')
        if self.order:
            if self.order.status != 'Delivered':
                raise forms.ValidationError("This order cannot be returned as it has not been delivered.")
            if not items:
                cleaned_data['items'] = self.order.items.filter(is_active=True)  
        return cleaned_data

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