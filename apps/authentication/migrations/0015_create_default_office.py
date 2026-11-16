# Data migration to create default office and assign all users to it

from django.db import migrations
from django.conf import settings


def create_default_office(apps, schema_editor):
    """Create default office with default choices and assign all users to it."""
    Office = apps.get_model('authentication', 'Office')
    User = apps.get_model('authentication', 'User')

    # Default status choices with colors
    default_status_choices = [
        {'value': 'received', 'label': 'Received', 'color': '#3b82f6', 'bg_color': '#dbeafe', 'is_active': True, 'order': 1},
        {'value': 'hold', 'label': 'Hold', 'color': '#f59e0b', 'bg_color': '#fef3c7', 'is_active': True, 'order': 2},
        {'value': 'referred', 'label': 'Referred', 'color': '#8b5cf6', 'bg_color': '#ede9fe', 'is_active': True, 'order': 3},
        {'value': 'fyied', 'label': "FYI'ed", 'color': '#f97316', 'bg_color': '#ffedd5', 'is_active': True, 'order': 4},
        {'value': 'scheduling_in_progress', 'label': 'Scheduling in Progress', 'color': '#22c55e', 'bg_color': '#dcfce7', 'is_active': True, 'order': 5},
        {'value': 'scheduled', 'label': 'Scheduled', 'color': '#10b981', 'bg_color': '#d1fae5', 'is_active': True, 'order': 6},
        {'value': 'rsvped', 'label': "RSVP'ed", 'color': '#06b6d4', 'bg_color': '#cffafe', 'is_active': True, 'order': 7},
        {'value': 'regrets_sent', 'label': 'Regrets Sent', 'color': '#ef4444', 'bg_color': '#fee2e2', 'is_active': True, 'order': 8},
        {'value': 'passed', 'label': 'Passed', 'color': '#6b7280', 'bg_color': '#f3f4f6', 'is_active': True, 'order': 9},
        {'value': 'canceled', 'label': 'Canceled / Request Withdrawn', 'color': '#9ca3af', 'bg_color': '#f9fafb', 'is_active': True, 'order': 10},
        {'value': 'requires_hms_review', 'label': 'Requires HMS Review', 'color': '#eab308', 'bg_color': '#fef9c3', 'is_active': True, 'order': 11},
    ]

    # Default type choices (no colors)
    default_type_choices = [
        {'value': 'event', 'label': 'Event', 'is_active': True, 'order': 1},
        {'value': 'meeting', 'label': 'Meeting', 'is_active': True, 'order': 2},
        {'value': 'speaking', 'label': 'Speaking', 'is_active': True, 'order': 3},
    ]

    # Default format choices (no colors)
    default_format_choices = [
        {'value': 'in-person', 'label': 'In Person', 'is_active': True, 'order': 1},
        {'value': 'virtual', 'label': 'Virtual', 'is_active': True, 'order': 2},
        {'value': 'hybrid', 'label': 'Hybrid', 'is_active': True, 'order': 3},
    ]

    # Create the default office
    default_office = Office.objects.create(
        name='Default Office',
        event_status_choices=default_status_choices,
        event_type_choices=default_type_choices,
        event_format_choices=default_format_choices,
    )

    # Assign all existing users to the default office
    User.objects.filter(office__isnull=True).update(office=default_office)


def reverse_default_office(apps, schema_editor):
    """Remove default office assignment from users and delete the default office."""
    Office = apps.get_model('authentication', 'Office')
    User = apps.get_model('authentication', 'User')

    # Unassign users from default office
    User.objects.filter(office__name='Default Office').update(office=None)

    # Delete the default office
    Office.objects.filter(name='Default Office').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0014_office_and_user_office'),
    ]

    operations = [
        migrations.RunPython(create_default_office, reverse_default_office),
    ]
