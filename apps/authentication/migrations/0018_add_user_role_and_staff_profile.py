# Generated manually for role-based permission system

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


def link_users_to_staff_profiles(apps, schema_editor):
    """
    Data migration to link existing users to OfficeStaff profiles.
    Matches by email address (case-insensitive).
    """
    User = apps.get_model('authentication', 'User')
    OfficeStaff = apps.get_model('authentication', 'OfficeStaff')

    for user in User.objects.filter(email__isnull=False).exclude(email=''):
        # Try to find a matching staff profile by email
        matching_staff = OfficeStaff.objects.filter(
            email__iexact=user.email,
            office=user.office,
            is_active=True
        ).first()

        if matching_staff:
            user.staff_profile = matching_staff
            user.save()


def set_first_user_as_admin(apps, schema_editor):
    """
    Data migration to set the first user of each office as admin.
    All other users remain as staff.
    """
    Office = apps.get_model('authentication', 'Office')
    User = apps.get_model('authentication', 'User')

    for office in Office.objects.all():
        # Get the first user for this office (by creation date)
        first_user = User.objects.filter(office=office).order_by('date_joined').first()
        if first_user:
            first_user.role = 'admin'
            first_user.save()


def reverse_admin_setup(apps, schema_editor):
    """Reverse: set all users back to staff role."""
    User = apps.get_model('authentication', 'User')
    User.objects.all().update(role='staff')


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0017_add_office_info_staff_tags'),
    ]

    operations = [
        # Add role field to User
        migrations.AddField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('admin', 'Admin'), ('scheduler', 'Scheduler'), ('staff', 'Staff')],
                default='staff',
                help_text="User's role for permission-based access control",
                max_length=20,
            ),
        ),

        # Add staff_profile OneToOne link to User
        migrations.AddField(
            model_name='user',
            name='staff_profile',
            field=models.OneToOneField(
                blank=True,
                help_text='Link to OfficeStaff profile for event assignment matching',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='user_account',
                to='authentication.officestaff',
            ),
        ),

        # Add office setup tracking fields to Office
        migrations.AddField(
            model_name='office',
            name='is_setup_complete',
            field=models.BooleanField(
                default=False,
                help_text='Whether office setup wizard has been completed',
            ),
        ),
        migrations.AddField(
            model_name='office',
            name='setup_completed_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the office setup was completed',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='office',
            name='setup_completed_by',
            field=models.ForeignKey(
                blank=True,
                help_text='User who completed the office setup',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='offices_setup',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # Data migration: Link users to staff profiles by email
        migrations.RunPython(link_users_to_staff_profiles, migrations.RunPython.noop),

        # Data migration: Set first user of each office as admin
        migrations.RunPython(set_first_user_as_admin, reverse_admin_setup),
    ]
