from django.db import migrations
import uuid

def populate_referral_codes(apps, schema_editor):
    CustomUser = apps.get_model('user_app', 'CustomUser')
    for user in CustomUser.objects.filter(referral_code__isnull=True):
        # Generate a unique referral code
        while True:
            new_code = str(uuid.uuid4())[:8].upper()
            if not CustomUser.objects.filter(referral_code=new_code).exists():
                user.referral_code = new_code
                user.save()
                break

class Migration(migrations.Migration):
    dependencies = [
        ('user_app', '0008_customuser_referral_code_referral'),
    ]

    operations = [
        migrations.RunPython(populate_referral_codes, reverse_code=migrations.RunPython.noop),
    ]