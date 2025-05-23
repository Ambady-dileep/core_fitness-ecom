# Generated by Django 5.1.6 on 2025-04-18 10:46

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cart_and_orders_app", "0007_remove_order_wallet_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("PAID", "Paid"),
                    ("FAILED", "Failed"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="cartitem",
            name="applied_offer",
            field=models.CharField(
                blank=True, help_text="Type of offer applied", max_length=20, null=True
            ),
        ),
        migrations.CreateModel(
            name="CancellationRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("reason", models.TextField(blank=True, null=True)),
                (
                    "requested_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("processed", models.BooleanField(default=False)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cancellation_requests",
                        to="cart_and_orders_app.order",
                    ),
                ),
            ],
        ),
    ]
