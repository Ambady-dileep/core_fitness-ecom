# Generated by Django 5.1.6 on 2025-03-13 14:52

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('product_app', '0008_product_average_rating_review_helpful_votes'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='tag',
            options={'verbose_name': 'Tag', 'verbose_name_plural': 'Tags'},
        ),
        migrations.AlterUniqueTogether(
            name='tag',
            unique_together={('name', 'slug')},
        ),
    ]
