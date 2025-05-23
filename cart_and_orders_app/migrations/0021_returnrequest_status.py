# Generated by Django 5.1.6 on 2025-05-21 19:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cart_and_orders_app", "0020_returnrequest_refund_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="returnrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("Pending", "Pending"),
                    ("Approved", "Approved"),
                    ("Rejected", "Rejected"),
                ],
                default="Pending",
                max_length=20,
            ),
        ),
    ]
