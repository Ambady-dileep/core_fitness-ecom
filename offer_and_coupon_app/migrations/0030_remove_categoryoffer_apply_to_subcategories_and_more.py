from django.db import migrations, models
from django.utils import timezone
from datetime import timedelta

def update_transaction_types(apps, schema_editor):
    WalletTransaction = apps.get_model('offer_and_coupon_app', 'WalletTransaction')
    WalletTransaction.objects.filter(transaction_type='REFUND').update(transaction_type='CREDIT')
    WalletTransaction.objects.exclude(transaction_type__in=['CREDIT', 'DEBIT']).update(transaction_type='CREDIT')

class Migration(migrations.Migration):
    dependencies = [
        ('offer_and_coupon_app', '0029_alter_wallettransaction_transaction_type'),
    ]

    operations = [
        migrations.RunPython(update_transaction_types, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='CategoryOffer',
            name='apply_to_subcategories',
        ),
        migrations.AlterField(
            model_name='Coupon',
            name='valid_to',
            field=models.DateTimeField(default=lambda: timezone.now() + timedelta(days=30)),
        ),
        migrations.AlterField(
            model_name='WalletTransaction',
            name='transaction_type',
            field=models.CharField(
                choices=[('CREDIT', 'Credit'), ('DEBIT', 'Debit')],
                max_length=6
            ),
        ),
    ]