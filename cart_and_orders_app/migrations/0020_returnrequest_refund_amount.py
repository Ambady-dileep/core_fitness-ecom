# Generated by Django 5.1.6 on 2025-05-19 06:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "cart_and_orders_app",
            "0019_order_address_city_order_address_country_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="returnrequest",
            name="refund_amount",
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=10),
        ),
    ]
