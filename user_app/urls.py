# user_app/urls.py
from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import user_views
from . import admin_views

app_name = 'user_app'  

urlpatterns = [
    # Authentication URLs
    path('', user_views.user_login, name='user_login'),
    path('signup/', user_views.user_signup, name='user_signup'),
    path('home/', user_views.user_home, name='user_home'),
    path('logout/', user_views.user_logout, name='user_logout'),
    path('change-password/', user_views.change_password, name='change_password'),

    # Address Management URLs
    path('profile/addresses/', user_views.user_address_list, name='user_address_list'), 
    path('profile/address/add/', user_views.add_address, name='add_address'),
    path('profile/address/<int:address_id>/edit/', user_views.edit_address, name='edit_address'),
    path('profile/address/<int:address_id>/delete/', user_views.delete_address, name='delete_address'),
    path('profile/address/<int:address_id>/set-default/', user_views.set_default_address, name='set_default_address'),

    # Admin URLs
    path('admin/login/', admin_views.admin_login, name='admin_login'),
    path('admin/dashboard/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin/customer-list/', admin_views.admin_customer_list, name='admin_customer_list'),
    path('admin/logout/', admin_views.admin_logout, name='admin_logout'),
    path('admin/toggle_user_block/<int:user_id>/', admin_views.toggle_user_block, name='toggle_user_block'),
    path('contact-us/', admin_views.contact_us, name='contact_us'),

    # Static Pages and Profile URLs
    path('faq/', user_views.faq, name='faq'),
    path('about-us/', user_views.about_us, name='about_us'),
    path('privacy-policy/', user_views.privacy_policy, name='privacy_policy'),
    path('edit-profile/', user_views.edit_profile, name='edit_profile'),
    path('contact-us/', user_views.contact_us, name='contact_us'),
    path('profile/', user_views.my_profile, name='my_profile'),

    # Password Reset and OTP URLs
    path('generate-otp/', user_views.generate_and_send_otp, name='generate_otp'), 
    path('validate-otp/', user_views.validate_otp, name='validate_otp'),
    path('resend-otp/', user_views.resend_otp, name='resend_otp'),
    path('password-reset-confirm/<uidb64>/<token>/', user_views.password_reset_confirm, name='password_reset_confirm'),

    # OTP Verification for Signup
    path('verify-otp-signup/', user_views.verify_otp_signup, name='verify_otp_signup'),
    path('resend-otp-signup/', user_views.resend_otp_signup, name='resend_otp_signup'),
    path('verify-otp-signup/<str:email>/', user_views.verify_otp_signup_page, name='verify_otp_signup_page'),

    # Banner Management
    path('admin/banners/', admin_views.admin_banner_list, name='admin_banner_list'),
    path('admin/banners/create/', admin_views.admin_banner_create, name='admin_banner_create'),
    path('admin/banners/edit/<int:banner_id>/', admin_views.admin_banner_edit, name='admin_banner_edit'),
    path('admin/banners/delete/<int:banner_id>/', admin_views.admin_banner_delete, name='admin_banner_delete'),
    path('admin/banners/toggle-status/<int:banner_id>/', admin_views.admin_banner_toggle_status, name='admin_banner_toggle_status'),

    path('referral/dashboard/', user_views.referral_dashboard, name='referral_dashboard'),
    path('referral/<str:referral_code>/', user_views.referral_link, name='referral_link'),
    path('verify-referral-code/', user_views.verify_referral_code, name='verify_referral_code')
    
]

