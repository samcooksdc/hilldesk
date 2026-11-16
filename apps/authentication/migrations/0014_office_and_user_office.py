# Generated migration for Office model and User.office field

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0013_user_azure_ad_id_alter_user_mfa_secret'),
    ]

    operations = [
        migrations.CreateModel(
            name='Office',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(help_text="Office name (e.g., 'Rep. Smith Office')", max_length=200)),
                ('event_status_choices', models.JSONField(default=list, help_text='Custom event status options with colors')),
                ('event_type_choices', models.JSONField(default=list, help_text='Custom event type options')),
                ('event_format_choices', models.JSONField(default=list, help_text='Custom event format options')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Office',
                'verbose_name_plural': 'Offices',
                'db_table': 'authentication_office',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='user',
            name='office',
            field=models.ForeignKey(
                blank=True,
                help_text='Office this user belongs to',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='users',
                to='authentication.office'
            ),
        ),
    ]
