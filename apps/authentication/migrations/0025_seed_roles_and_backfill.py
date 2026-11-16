"""
Seed default roles (Admin/Scheduler/Staff) for every existing office and
backfill each user's office_role from their legacy `role` slug.

The role -> permission-key data is inlined here (rather than imported from
apps.authentication.permissions) so the migration stays self-contained and
keeps working even if the catalog evolves later.
"""
from django.db import migrations


# Inlined default-role specs. Keep in sync conceptually with
# apps.authentication.permissions.DEFAULT_ROLE_SPECS, but this snapshot is
# frozen for the migration. `permissions=None` => admin (all perms via is_admin).
SCHEDULER_PERMS = [
    'view_all_events', 'edit_all_events', 'edit_assigned_events',
    'create_events', 'change_event_status', 'archive_delete_events',
    'approve_staff_changes', 'configure_approval_routing',
    'view_inbox', 'process_inbox', 'export_events',
    'manage_email_templates', 'manage_export_templates',
]
STAFF_PERMS = ['view_assigned_events', 'edit_assigned_events', 'view_inbox']

ROLE_SPECS = [
    {'slug': 'admin', 'name': 'Admin', 'color': '#dc2626', 'is_admin': True,
     'is_system': True, 'order': 0,
     'description': 'Full access. Manages roles, office settings, and all events.',
     'permissions': []},
    {'slug': 'scheduler', 'name': 'Scheduler', 'color': '#2563eb', 'is_admin': False,
     'is_system': True, 'order': 1,
     'description': 'Manages events, status, approvals, inbox, and templates.',
     'permissions': SCHEDULER_PERMS},
    {'slug': 'staff', 'name': 'Staff', 'color': '#22c55e', 'is_admin': False,
     'is_system': True, 'order': 2,
     'description': 'Views and edits assigned events. Other edits go to review.',
     'permissions': STAFF_PERMS},
]


def seed_roles_and_backfill(apps, schema_editor):
    Office = apps.get_model('authentication', 'Office')
    Role = apps.get_model('authentication', 'Role')
    User = apps.get_model('authentication', 'User')

    for office in Office.objects.all():
        slug_to_role = {}
        for spec in ROLE_SPECS:
            role, _created = Role.objects.get_or_create(
                office=office,
                slug=spec['slug'],
                defaults={
                    'name': spec['name'],
                    'color': spec['color'],
                    'is_admin': spec['is_admin'],
                    'is_system': spec['is_system'],
                    'order': spec['order'],
                    'description': spec['description'],
                    'permissions': spec['permissions'],
                },
            )
            slug_to_role[spec['slug']] = role

        # Backfill office_role for users in this office based on their role slug.
        for user in User.objects.filter(office=office, office_role__isnull=True):
            target = slug_to_role.get(user.role) or slug_to_role.get('staff')
            if target is not None:
                user.office_role = target
                user.save(update_fields=['office_role'])

    # Users with no office can't be assigned a role; leave office_role null
    # (permission checks fall back to the legacy `role` slug mapping).


def unseed(apps, schema_editor):
    """Reverse: detach office_role from users and delete seeded roles."""
    Role = apps.get_model('authentication', 'Role')
    User = apps.get_model('authentication', 'User')
    User.objects.update(office_role=None)
    Role.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0024_add_role_model'),
    ]

    operations = [
        migrations.RunPython(seed_roles_and_backfill, unseed),
    ]
