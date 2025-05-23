# Generated by Django 5.1.6 on 2025-05-02 11:02

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "offer_and_coupon_app",
            "0046_remove_coupon_usage_count_remove_coupon_usage_limit_and_more",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="usercoupon",
            name="coupon",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="user_coupons",
                to="offer_and_coupon_app.coupon",
            ),
        ),
    ]
