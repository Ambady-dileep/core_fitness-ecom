# Generated by Django 5.1.6 on 2025-04-22 15:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("offer_and_coupon_app", "0041_alter_coupon_valid_to"),
    ]

    operations = [
        migrations.AlterField(
            model_name="wallettransaction",
            name="transaction_type",
            field=models.CharField(
                choices=[("CREDIT", "Credit"), ("DEBIT", "Debit")], max_length=9
            ),
        ),
    ]
