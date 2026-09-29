# Generated to assign the Administrator role to superuser accounts.

from django.db import migrations


def assign_admin_role(apps, schema_editor):
    User = apps.get_model('core', 'User')
    User.objects.filter(is_superuser=True, role='staff').update(role='admin')


def rollback_admin_role(apps, schema_editor):
    User = apps.get_model('core', 'User')
    User.objects.filter(is_superuser=True, role='admin').update(role='staff')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_scan_crawl_log'),
    ]

    operations = [
        migrations.RunPython(assign_admin_role, rollback_admin_role),
    ]