"""Seed built-in export template records."""

import uuid
from django.db import migrations


BUILT_IN_TEMPLATES = [
    {
        'id': uuid.UUID('a0000001-0000-0000-0000-000000000001'),
        'name': 'HillDesk Daily Briefing',
        'template_type': 'daily_briefing',
        'is_default': True,
    },
    {
        'id': uuid.UUID('a0000001-0000-0000-0000-000000000002'),
        'name': 'HillDesk Weekly Overview',
        'template_type': 'weekly_overview',
        'is_default': True,
    },
    {
        'id': uuid.UUID('a0000001-0000-0000-0000-000000000003'),
        'name': 'HillDesk Event Detail',
        'template_type': 'event_detail',
        'is_default': True,
    },
    {
        'id': uuid.UUID('a0000001-0000-0000-0000-000000000004'),
        'name': 'HillDesk Filtered List',
        'template_type': 'filtered_list',
        'is_default': True,
    },
]


def seed_templates(apps, schema_editor):
    ExportTemplate = apps.get_model('event_management', 'ExportTemplate')
    for tpl in BUILT_IN_TEMPLATES:
        ExportTemplate.objects.get_or_create(
            id=tpl['id'],
            defaults={
                'name': tpl['name'],
                'template_type': tpl['template_type'],
                'is_default': tpl['is_default'],
            },
        )


def remove_templates(apps, schema_editor):
    ExportTemplate = apps.get_model('event_management', 'ExportTemplate')
    ids = [tpl['id'] for tpl in BUILT_IN_TEMPLATES]
    ExportTemplate.objects.filter(id__in=ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('event_management', '0014_exporttemplate'),
    ]

    operations = [
        migrations.RunPython(seed_templates, remove_templates),
    ]
