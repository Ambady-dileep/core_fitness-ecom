# Generated by Django 5.1.6 on 2025-04-13 17:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "cart_and_orders_app",
            "0004_cartitem_applied_offer_orderitem_applied_offer_and_more",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="cartitem",
            name="applied_offer",
            field=models.CharField(
                blank=True,
                help_text="Type of offer applied (product/category)",
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="cartitem",
            name="price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Unit price after best offer",
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="order",
            name="discount_amount",
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=10),
        ),
        migrations.AlterField(
            model_name="orderitem",
            name="price",
            field=models.DecimalField(
                decimal_places=2, help_text="Unit price after best offer", max_digits=10
            ),
        ),
    ]
