import django.db.models.deletion
from django.db import migrations, models
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies = [
        ('cart_and_orders_app', '0010_cartitem_price'),
        ('offer_and_coupon_app', '0005_alter_coupon_code_alter_coupon_discount_amount'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='discount_amount',
            field=models.DecimalField(
                max_digits=5,
                decimal_places=2,
                null=True,
                blank=True
            ),
        ),
    ]