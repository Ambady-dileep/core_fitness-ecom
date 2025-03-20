from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('cart_and_orders_app', '0011_order_cart_items_order_coupon_order_created_at_and_more_squashed_0014_alter_order_cart_items'),
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