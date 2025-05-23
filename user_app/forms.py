from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, Banner
from .models import ContactMessage
from .models import Address, CustomUser, UserProfile, validate_full_name


class AdminLoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter username',
            'id': 'username'
        }),
        error_messages={
            'required': 'Username is required'
        }
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password',
            'id': 'password'
        }),
        error_messages={
            'required': 'Password is required'
        }
    )

    
class UserProfileForm(forms.ModelForm):
    phone_regex = RegexValidator(
        regex=r'^[6-9]\d{9}$',
        message="Phone number must be a valid 10-digit number starting with 6-9."
    )

    phone_number = forms.CharField(
        validators=[phone_regex],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Phone Number (e.g., 9876543210)'
        })
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'full_name', 'phone_number']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Username',
                'readonly': True  # Prevent editing username
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Email',
                'readonly': True  # Prevent editing email
            }),
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Full Name'
            }),
        }

    def clean_full_name(self):
        full_name = self.cleaned_data['full_name']
        validate_full_name(full_name)  # Use the validator from models.py
        return full_name

    def clean_email(self):
        email = self.cleaned_data['email'].lower()  # Match CustomUser's lowercase convention
        if CustomUser.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("A user with this email already exists.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data['phone_number']
        if CustomUser.objects.filter(phone_number=phone_number).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This phone number is already registered.")
        return phone_number

class ProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['profile_image', 'is_blocked']
        widgets = {
            'profile_image': forms.FileInput(attrs={'class': 'form-control'}),
            'is_blocked': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['full_name','address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country','phone', 'is_default']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name'}),
            'address_line1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Street address, P.O. box, company name'}),
            'address_line2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apartment, suite, unit, building, floor, etc.'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State/Province/Region'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ZIP / Postal code'}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Country'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number (e.g., 9876543210)'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'is_default': 'Set as default address',
        }

        def clean_phone(self):
            phone = self.cleaned_data.get('phone')
            if phone and not Address.objects.filter(phone=phone).exclude(id=self.instance.id).exists():
                return phone
            elif phone and Address.objects.filter(phone=phone).exclude(id=self.instance.id).exists():
                raise forms.ValidationError("This phone number is already in use.")
            return phone


class CustomPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'id': 'old_password'}),
        label="Current Password"
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'id': 'new_password1'}),
        label="New Password"
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'id': 'new_password2'}),
        label="Confirm New Password"
    )

    class Meta:
        model = CustomUser
        fields = ('old_password', 'new_password1', 'new_password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].widget.attrs.update({'style': 'border-radius: 8px; border: 1px solid #e2e8f0;'})
        self.fields['new_password1'].widget.attrs.update({'style': 'border-radius: 8px; border: 1px solid #e2e8f0;'})
        self.fields['new_password2'].widget.attrs.update({'style': 'border-radius: 8px; border: 1px solid #e2e8f0;'})

    def clean_old_password(self):
        old_password = self.cleaned_data.get('old_password')
        if not old_password:
            raise ValidationError("Current password is required.")
        if not self.user.check_password(old_password):
            raise ValidationError("Current password is incorrect.")
        return old_password

    def clean_new_password1(self):
        new_password1 = self.cleaned_data.get('new_password1')
        old_password = self.cleaned_data.get('old_password')

        if not new_password1:
            raise ValidationError("New password is required.")

        if old_password and new_password1 == old_password:
            raise ValidationError("New password cannot be the same as the current password.")

        if not all([
            len(new_password1) >= 8,
            any(char.isupper() for char in new_password1),
            any(char.islower() for char in new_password1),
            any(char.isdigit() for char in new_password1),
            any(char in "!@#$%^&*()+-_=[]{};:,.<>?" for char in new_password1),
        ]):
            raise ValidationError(
                "Password must be at least 8 characters long and contain an uppercase letter, "
                "a lowercase letter, a number, and a special character (e.g., !@#$%^&*)."
            )

        # Check if password is too similar to username
        if self.user.username.lower() in new_password1.lower() or new_password1.lower() in self.user.username.lower():
            raise ValidationError("The password is too similar to the username.")

        return new_password1

    def clean_new_password2(self):
        new_password2 = self.cleaned_data.get('new_password2')
        if not new_password2:
            raise ValidationError("Please confirm your new password.")
        return new_password2

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')

        if new_password1 and new_password2 and new_password1 != new_password2:
            raise ValidationError({"new_password2": "The new passwords do not match."})
        return cleaned_data



class GenerateOTPForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'id': 'email_generate',
            'placeholder': 'Enter your email',
            'required': True
        }),
        label="Email"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure no default disabled state
        self.fields['email'].widget.attrs.pop('disabled', None)

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if not CustomUser.objects.filter(email=email).exists():
            raise ValidationError("No account is associated with this email.")
        return email

class ValidateOTPForm(forms.Form):
    otp = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'otp_validate',
            'placeholder': 'Enter OTP',
            'required': True
        }),
        label="OTP"
    )

    def clean_otp(self):
        otp = self.cleaned_data['otp']
        if not otp.isdigit() or len(otp) != 6:
            raise forms.ValidationError("OTP must be a 6-digit number.")
        return otp        

class CustomUserCreationForm(UserCreationForm):
    referral_code = forms.CharField(max_length=20, required=False, help_text="Optional: Enter referral code if you have one")
    
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'full_name', 'phone_number', 'password1', 'password2')

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        username = self.cleaned_data.get('username')

        if not password1:
            raise ValidationError("Password is required.")

        if not all([
            len(password1) >= 8,
            any(char.isupper() for char in password1),
            any(char.islower() for char in password1),
            any(char.isdigit() for char in password1),
            any(char in "!@#$%^&*()+-_=[]{};:,.<>?" for char in password1),
        ]):
            raise ValidationError(
                "Password must be at least 8 characters long and contain an uppercase letter, "
                "a lowercase letter, a number, and a special character (e.g., !@#$%^&*)."
            )

        if username and (username.lower() in password1.lower() or password1.lower() in username.lower()):
            raise ValidationError("The password is too similar to the username.")

        return password1
    

class BannerForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = ['title', 'subtitle', 'image', 'url', 'is_active', 'display_order']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Banner Title'}),
            'subtitle': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Banner Subtitle (Optional)'}),
            'url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://example.com/page'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'is_active': 'Active',
        }


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Your Name', 'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Your Email', 'class': 'form-control'}),
            'subject': forms.TextInput(attrs={'placeholder': 'Subject', 'class': 'form-control'}),
            'message': forms.Textarea(attrs={'placeholder': 'Your Message', 'class': 'form-control', 'rows': 5}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise forms.ValidationError("Email is required.")
        return email