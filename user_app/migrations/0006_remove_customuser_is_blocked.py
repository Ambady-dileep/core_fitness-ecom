# Generated by Django 5.1.6 on 2025-05-01 09:55

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("user_app", "0005_contactmessage"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="customuser",
            name="is_blocked",
        ),
    ]
