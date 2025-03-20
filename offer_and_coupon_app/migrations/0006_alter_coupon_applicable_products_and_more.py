from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('cart_and_orders_app', '0011_order_cart_items_order_coupon_order_created_at_and_more_squashed_0014_alter_order_cart_items'),
        ('offer_and_coupon_app', '0005_alter_coupon_code_alter_coupon_discount_amount'),
        ('product_app', '0012_alter_tag_unique_together_alter_tag_slug_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='coupon',
            name='applicable_products',
            field=models.ManyToManyField(blank=True, to='product_app.ProductVariant'),
        ),
    ]