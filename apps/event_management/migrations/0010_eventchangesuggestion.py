# Generated manually for change suggestion system

from django.db import migrations, models
import django.db.models.deletion
import uuid
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('event_management', '0009_remove_event_choices_constraints'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventChangeSuggestion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('field_name', models.CharField(help_text="Name of the field being changed (e.g., 'title', 'location')", max_length=100)),
                ('current_value', models.TextField(blank=True, help_text='Current value of the field (JSON serialized for complex types)')),
                ('suggested_value', models.TextField(help_text='Suggested new value for the field (JSON serialized for complex types)')),
                ('status', models.CharField(choices=[('pending', 'Pending Review'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', help_text='Current status of this suggestion', max_length=20)),
                ('reason', models.TextField(blank=True, help_text='Optional reason provided by the suggester for this change')),
                ('suggested_at', models.DateTimeField(auto_now_add=True, help_text='When this suggestion was created')),
                ('reviewed_at', models.DateTimeField(blank=True, help_text='When this suggestion was reviewed', null=True)),
                ('review_comment', models.TextField(blank=True, help_text='Optional comment from reviewer when approving/rejecting')),
                ('ip_address', models.GenericIPAddressField(blank=True, help_text='IP address of the suggester', null=True)),
                ('event', models.ForeignKey(help_text='Event this suggestion applies to', on_delete=django.db.models.deletion.CASCADE, related_name='change_suggestions', to='event_management.event')),
                ('reviewed_by', models.ForeignKey(blank=True, help_text='User who reviewed this suggestion', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='suggestions_reviewed', to=settings.AUTH_USER_MODEL)),
                ('suggested_by', models.ForeignKey(help_text='User who suggested this change', on_delete=django.db.models.deletion.PROTECT, related_name='suggestions_made', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Event Change Suggestion',
                'verbose_name_plural': 'Event Change Suggestions',
                'db_table': 'event_change_suggestions',
                'ordering': ['-suggested_at'],
            },
        ),
        migrations.AddIndex(
            model_name='eventchangesuggestion',
            index=models.Index(fields=['event', 'status'], name='event_chang_event_i_09db9e_idx'),
        ),
        migrations.AddIndex(
            model_name='eventchangesuggestion',
            index=models.Index(fields=['suggested_by', 'status'], name='event_chang_suggest_6d16b5_idx'),
        ),
        migrations.AddIndex(
            model_name='eventchangesuggestion',
            index=models.Index(fields=['status', 'suggested_at'], name='event_chang_status_fc8c90_idx'),
        ),
        migrations.AddIndex(
            model_name='eventchangesuggestion',
            index=models.Index(fields=['event', 'field_name', 'status'], name='event_chang_event_i_6b1a85_idx'),
        ),
    ]
