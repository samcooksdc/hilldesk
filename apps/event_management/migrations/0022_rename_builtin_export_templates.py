"""Rename built-in export templates to the 'HillDesk ...' convention."""

import uuid
from django.db import migrations


# (id, old name, new name) for the four seeded built-ins.
RENAMES = [
    (uuid.UUID('a0000001-0000-0000-0000-000000000001'), 'Daily Briefing', 'HillDesk Daily Briefing'),
    (uuid.UUID('a0000001-0000-0000-0000-000000000002'), 'Weekly Overview', 'HillDesk Weekly Overview'),
    (uuid.UUID('a0000001-0000-0000-0000-000000000003'), 'Event Detail', 'HillDesk Event Detail'),
    (uuid.UUID('a0000001-0000-0000-0000-000000000004'), 'Filtered List', 'HillDesk Filtered List'),
]


def rename_forward(apps, schema_editor):
    ExportTemplate = apps.get_model('event_management', 'ExportTemplate')
    for tpl_id, _old, new in RENAMES:
        ExportTemplate.objects.filter(id=tpl_id).update(name=new)


def rename_backward(apps, schema_editor):
    ExportTemplate = apps.get_model('event_management', 'ExportTemplate')
    for tpl_id, old, _new in RENAMES:
        ExportTemplate.objects.filter(id=tpl_id).update(name=old)


class Migration(migrations.Migration):

    dependencies = [
        ('event_management', '0021_alter_eventattachmentversion_file'),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
