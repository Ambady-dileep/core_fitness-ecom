from django.apps import AppConfig

class OfferAndCouponAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'offer_and_coupon_app'

    def ready(self):
        import offer_and_coupon_app.signals