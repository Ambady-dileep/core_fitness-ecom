# Generated by Django 5.1.6 on 2025-04-13 14:02

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("offer_and_coupon_app", "0009_alter_coupon_valid_to"),
    ]

    operations = [
        migrations.AlterField(
            model_name="coupon",
            name="valid_to",
            field=models.DateTimeField(
                default=datetime.datetime(
                    2025, 5, 13, 14, 2, 8, 809140, tzinfo=datetime.timezone.utc
                )
            ),
        ),
    ]
