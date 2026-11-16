import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

import apps.event_management.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('authentication', '0019_add_saved_filter_preset'),
        ('event_management', '0013_default_email_templates'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExportTemplate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(help_text='Display name of this export template', max_length=200)),
                ('template_type', models.CharField(
                    choices=[
                        ('daily_briefing', 'Daily Briefing'),
                        ('weekly_overview', 'Weekly Overview'),
                        ('event_detail', 'Event Detail'),
                        ('filtered_list', 'Filtered List'),
                        ('custom', 'Custom'),
                    ],
                    help_text='Type of export this template produces',
                    max_length=30,
                )),
                ('docx_file', models.FileField(
                    blank=True,
                    help_text='Uploaded .docx template file. Blank for built-in defaults.',
                    upload_to=apps.event_management.models.export_template_upload_path,
                )),
                ('is_default', models.BooleanField(default=False, help_text='True for built-in system templates')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True, help_text='User who created this template',
                    null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='export_templates_created', to=settings.AUTH_USER_MODEL,
                )),
                ('modified_by', models.ForeignKey(
                    blank=True, help_text='User who last modified this template',
                    null=True, on_delete=django.db.models.deletion.PROTECT,
                    related_name='export_templates_modified', to=settings.AUTH_USER_MODEL,
                )),
                ('office', models.ForeignKey(
                    blank=True, help_text='Office this template belongs to. Null for system defaults.',
                    null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='export_templates', to='authentication.office',
                )),
            ],
            options={
                'verbose_name': 'Export Template',
                'verbose_name_plural': 'Export Templates',
                'db_table': 'export_templates',
                'ordering': ['template_type', 'name'],
                'indexes': [
                    models.Index(fields=['template_type'], name='export_temp_templat_idx'),
                    models.Index(fields=['is_default'], name='export_temp_is_defa_idx'),
                    models.Index(fields=['office'], name='export_temp_office_idx'),
                    models.Index(fields=['created_at'], name='export_temp_created_idx'),
                ],
            },
        ),
    ]
