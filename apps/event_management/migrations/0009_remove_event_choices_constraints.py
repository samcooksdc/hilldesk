# Generated migration to remove choices constraints from Event type and status fields
# These choices are now managed at the office level

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('event_management', '0008_add_human_review_fields'),
    ]

    operations = [
        # Remove choices constraint from type field
        migrations.AlterField(
            model_name='event',
            name='type',
            field=models.CharField(
                blank=True,
                help_text='Type of event: Event, Meeting, or Speaking engagement',
                max_length=20
            ),
        ),
        # Remove choices constraint from status field
        migrations.AlterField(
            model_name='event',
            name='status',
            field=models.CharField(
                default='received',
                help_text='Current status of the event',
                max_length=30
            ),
        ),
    ]
