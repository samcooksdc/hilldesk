"""
Data migration to create default email response templates.
These system templates provide starter content for common congressional scheduling responses.
"""

from django.db import migrations


STANDARD_VARIABLES = [
    'member_name', 'staffer_name', 'event_title', 'event_date',
    'event_time', 'event_location', 'organization', 'sender_name',
    'sender_title', 'custom_1', 'custom_2', 'custom_3',
]

DEFAULT_TEMPLATES = [
    # RSVP category
    {
        'name': 'Accept — Confirm Attendance',
        'category': 'rsvp',
        'subject': 'RE: {event_title} — Confirmed',
        'body': (
            'Dear {sender_name},\n\n'
            'Thank you for the invitation. I am pleased to confirm that {member_name} '
            'will attend {event_title} on {event_date} at {event_time}.\n\n'
            'Please let us know if there are any logistical details we should be aware of, '
            'including parking, building access, or any materials to review in advance.\n\n'
            'We look forward to it.\n\n'
            'Best regards,\n'
            '{staffer_name}'
        ),
    },
    {
        'name': 'Decline — Scheduling Conflict',
        'category': 'rsvp',
        'subject': 'RE: {event_title} — Unable to Attend',
        'body': (
            'Dear {sender_name},\n\n'
            'Thank you for the invitation to {event_title} on {event_date}. '
            'Unfortunately, {member_name} has a prior commitment at that time and '
            'will be unable to attend.\n\n'
            'We appreciate you thinking of us and hope to participate in future events. '
            'Please do not hesitate to reach out with any other opportunities.\n\n'
            'Best regards,\n'
            '{staffer_name}'
        ),
    },
    {
        'name': 'Decline — Policy Conflict',
        'category': 'rsvp',
        'subject': 'RE: {event_title} — Respectfully Declining',
        'body': (
            'Dear {sender_name},\n\n'
            'Thank you for the invitation to {event_title}. After careful consideration, '
            '{member_name} will not be able to participate at this time. '
            'The office will follow up on this matter if appropriate.\n\n'
            'We appreciate your understanding and your engagement with our office.\n\n'
            'Best regards,\n'
            '{staffer_name}'
        ),
    },
    {
        'name': 'Tentative — Pending Confirmation',
        'category': 'rsvp',
        'subject': 'RE: {event_title} — Tentative',
        'body': (
            'Dear {sender_name},\n\n'
            'Thank you for the invitation to {event_title} on {event_date}. '
            '{member_name} is tentatively planning to attend, but we are awaiting '
            'confirmation on a few scheduling details.\n\n'
            'We will follow up with a definitive answer by {custom_1}. '
            'In the meantime, please feel free to send along any relevant materials.\n\n'
            'Best regards,\n'
            '{staffer_name}'
        ),
    },
    {
        'name': 'Request More Information',
        'category': 'rsvp',
        'subject': 'RE: {event_title} — Additional Information Needed',
        'body': (
            'Dear {sender_name},\n\n'
            'Thank you for the invitation to {event_title}. Before we can confirm attendance, '
            'we would appreciate some additional details:\n\n'
            '- Expected duration of the event\n'
            '- Venue address and parking information\n'
            '- Agenda or list of topics to be covered\n'
            '- Other confirmed attendees\n\n'
            'Once we have this information, we will be happy to provide a prompt response.\n\n'
            'Best regards,\n'
            '{staffer_name}'
        ),
    },
    # Follow-up category
    {
        'name': 'Post-Meeting Thank You',
        'category': 'follow_up',
        'subject': 'Thank You — {event_title}',
        'body': (
            'Dear {sender_name},\n\n'
            'Thank you for taking the time to meet with {member_name} regarding {event_title} '
            'on {event_date}. We appreciated the opportunity to discuss these important matters '
            'with {organization}.\n\n'
            'If there is anything further our office can assist with, please do not hesitate '
            'to reach out.\n\n'
            'Best regards,\n'
            '{staffer_name}'
        ),
    },
    {
        'name': 'Post-Meeting Action Items',
        'category': 'follow_up',
        'subject': 'Follow Up — {event_title} Action Items',
        'body': (
            'Dear {sender_name},\n\n'
            'Thank you for the productive meeting on {event_date} regarding {event_title}. '
            'As discussed, here are the action items we identified:\n\n'
            '1. {custom_1}\n'
            '2. {custom_2}\n'
            '3. {custom_3}\n\n'
            'Please let us know if we missed anything or if you have additional items to add. '
            'We look forward to continuing this work with {organization}.\n\n'
            'Best regards,\n'
            '{staffer_name}'
        ),
    },
    # Scheduling category
    {
        'name': 'Propose Alternative Time',
        'category': 'scheduling',
        'subject': 'RE: {event_title} — Alternative Time',
        'body': (
            'Dear {sender_name},\n\n'
            'Thank you for the invitation to {event_title}. Unfortunately, {member_name} '
            'is unavailable on {event_date} at {event_time}.\n\n'
            'Would any of the following alternative times work?\n\n'
            '- {custom_1}\n'
            '- {custom_2}\n'
            '- {custom_3}\n\n'
            'We are flexible and happy to work around your schedule. '
            'Please let us know what works best.\n\n'
            'Best regards,\n'
            '{staffer_name}'
        ),
    },
]


def create_default_templates(apps, schema_editor):
    """Create default email response templates."""
    EmailTemplate = apps.get_model('event_management', 'EmailTemplate')

    for template_data in DEFAULT_TEMPLATES:
        EmailTemplate.objects.create(
            name=template_data['name'],
            category=template_data['category'],
            subject=template_data['subject'],
            body=template_data['body'],
            variables=STANDARD_VARIABLES,
            is_default=True,
            is_active=True,
            is_html=False,
            office=None,
            created_by=None,
            modified_by=None,
        )


def remove_default_templates(apps, schema_editor):
    """Remove default templates on migration rollback."""
    EmailTemplate = apps.get_model('event_management', 'EmailTemplate')
    EmailTemplate.objects.filter(is_default=True, office__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('event_management', '0012_emailtemplate_category_active_html_office'),
    ]

    operations = [
        migrations.RunPython(create_default_templates, remove_default_templates),
    ]
