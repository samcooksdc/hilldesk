# Data migration to fix the "received" status label from "New" to "Received"

from django.db import migrations


def fix_received_status_label(apps, schema_editor):
    """Fix the 'received' status label to say 'Received' instead of 'New'."""
    Office = apps.get_model('authentication', 'Office')

    for office in Office.objects.all():
        status_choices = office.event_status_choices
        updated = False

        for status in status_choices:
            if status.get('value') == 'received' and status.get('label') != 'Received':
                status['label'] = 'Received'
                # Also reset to default blue color
                status['color'] = '#3b82f6'
                status['bg_color'] = '#dbeafe'
                updated = True

        if updated:
            office.event_status_choices = status_choices
            office.save()
            print(f"Fixed 'received' status label for office: {office.name}")


def reverse_migration(apps, schema_editor):
    """No-op reverse - we don't want to put "New" back."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0015_create_default_office'),
    ]

    operations = [
        migrations.RunPython(fix_received_status_label, reverse_migration),
    ]
