# Generated manually for approval routing system

from django.db import migrations, models
import django.db.models.deletion
import uuid
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('event_management', '0010_eventchangesuggestion'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventApproval',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('stage_id', models.CharField(help_text='ID of the approval stage (matches stage_id in approval_routing)', max_length=50)),
                ('stage_order', models.PositiveIntegerField(help_text='Order of this stage in the approval chain')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('sent_back', 'Sent Back')], default='pending', help_text='Current status of this approval', max_length=20)),
                ('comment', models.TextField(blank=True, help_text='Comment provided when approving or sending back')),
                ('decided_at', models.DateTimeField(blank=True, help_text='When this approval decision was made', null=True)),
                ('edits_made', models.JSONField(default=list, help_text='List of field changes made by approver during their turn')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, help_text='IP address when decision was made', null=True)),
                ('event', models.ForeignKey(help_text='Event being approved', on_delete=django.db.models.deletion.CASCADE, related_name='approvals', to='event_management.event')),
                ('approver', models.ForeignKey(help_text='User assigned to approve', on_delete=django.db.models.deletion.PROTECT, related_name='event_approvals', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Event Approval',
                'verbose_name_plural': 'Event Approvals',
                'db_table': 'event_approvals',
                'ordering': ['stage_order', 'created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='eventapproval',
            index=models.Index(fields=['event', 'status'], name='event_appro_event_i_3f2d8a_idx'),
        ),
        migrations.AddIndex(
            model_name='eventapproval',
            index=models.Index(fields=['approver', 'status'], name='event_appro_approve_8c1f47_idx'),
        ),
        migrations.AddIndex(
            model_name='eventapproval',
            index=models.Index(fields=['event', 'stage_id', 'status'], name='event_appro_event_i_b9c2e1_idx'),
        ),
        migrations.AddIndex(
            model_name='eventapproval',
            index=models.Index(fields=['status', 'decided_at'], name='event_appro_status_4d5e2c_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='eventapproval',
            unique_together={('event', 'stage_id', 'approver')},
        ),
    ]
