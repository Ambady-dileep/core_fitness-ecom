from django.db import migrations, models
from django.utils import timezone
from datetime import timedelta

def get_default_valid_to():
    return timezone.now() + timedelta(days=30)

class Migration(migrations.Migration):
    dependencies = [
        ('offer_and_coupon_app', '0026_alter_coupon_valid_to'),
    ]

    operations = [
        migrations.AlterField(
            model_name='Coupon',
            name='valid_to',
            field=models.DateTimeField(default=get_default_valid_to),
        ),
    ]