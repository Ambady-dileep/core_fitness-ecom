# Generated by Django 5.1.6 on 2025-04-20 03:19

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("offer_and_coupon_app", "0031_alter_coupon_valid_to"),
    ]

    operations = [
        migrations.AlterField(
            model_name="coupon",
            name="valid_to",
            field=models.DateTimeField(
                default=datetime.datetime(
                    2025, 5, 20, 3, 19, 17, 432160, tzinfo=datetime.timezone.utc
                )
            ),
        ),
    ]
