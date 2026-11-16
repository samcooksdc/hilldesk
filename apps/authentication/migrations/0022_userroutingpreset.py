import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0021_alter_user_mfa_secret_userfilterpreset'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserRoutingPreset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='User-facing preset name', max_length=100)),
                ('data', models.JSONField(blank=True, default=dict, help_text='Approval routing config captured by this preset')),
                ('is_default', models.BooleanField(default=False, help_text="Pre-load this route when configuring a new event's routing")),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='routing_presets', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'auth_user_routing_preset',
                'ordering': ['name'],
                'constraints': [models.UniqueConstraint(fields=('user', 'name'), name='unique_user_routing_preset_name')],
            },
        ),
    ]
