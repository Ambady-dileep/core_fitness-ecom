"""
URL configuration for main_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from .views import handler404

urlpatterns = [
    path('', include('user_app.urls')),
    path('', include('product_app.urls')), 
    path('', include('cart_and_orders_app.urls')),
    path('', include('offer_and_coupon_app.urls')),
    path('auth/', include('social_django.urls', namespace='social')),
]+ static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

handler404 = 'main_project.views.handler404'