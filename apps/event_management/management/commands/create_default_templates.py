# SPDX-License-Identifier: Apache-2.0
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.event_management.models import EmailTemplate

User = get_user_model()


class Command(BaseCommand):
    help = 'Create default email templates for responses'

    def handle(self, *args, **options):
        # Get or create a system user for template creation
        system_user, created = User.objects.get_or_create(
            username='system',
            defaults={
                'email': 'system@example.com',
                'first_name': 'System',
                'last_name': 'User',
                'is_staff': True,
            }
        )

        templates = [
            {
                'name': 'Meeting Request Acknowledgment',
                'subject': 'Re: {{subject}} - Meeting Request Received',
                'body': '''Dear {{sender_name}},

Thank you for your meeting request regarding {{event_type}} with {{organization}}.

We have received your request and it is currently under review. Our staff will evaluate the request and respond within 5-7 business days.

Meeting Details Received:
- Date: {{event_date}}
- Location: {{event_location}}
- Organization: {{organization}}

If you have any questions or need to provide additional information, please don't hesitate to contact our office.

Best regards,
{{staff_name}}
Congressional Staff''',
                'variables': ['sender_name', 'subject', 'event_type', 'organization', 'event_date', 'event_location', 'staff_name'],
                'is_default': True
            },
            {
                'name': 'Speaking Engagement Response',
                'subject': 'Re: {{subject}} - Speaking Engagement Request',
                'body': '''Dear {{sender_name}},

Thank you for inviting our office to participate in your {{event_type}} event.

We appreciate the invitation from {{organization}} and will review this request with our scheduling team. Due to the high volume of requests we receive, we will need some time to evaluate this opportunity.

Event Details:
- Date: {{event_date}}
- Location: {{event_location}}
- Organization: {{organization}}

We will respond within 10 business days with our availability and any additional requirements.

Thank you for thinking of our office for this opportunity.

Sincerely,
{{staff_name}}
Congressional Staff''',
                'variables': ['sender_name', 'subject', 'event_type', 'organization', 'event_date', 'event_location', 'staff_name'],
                'is_default': True
            },
            {
                'name': 'Request Declined',
                'subject': 'Re: {{subject}} - Unable to Accommodate Request',
                'body': '''Dear {{sender_name}},

Thank you for your interest in meeting with our office regarding {{event_type}}.

Unfortunately, due to scheduling conflicts and prior commitments, we will not be able to accommodate your request for {{event_date}}.

We appreciate your understanding and encourage you to reach out to our office in the future for other opportunities to engage.

If you have urgent concerns that need to be addressed, please contact our office directly at [phone number] or [email address].

Best regards,
{{staff_name}}
Congressional Staff''',
                'variables': ['sender_name', 'subject', 'event_type', 'event_date', 'staff_name'],
                'is_default': True
            },
            {
                'name': 'Request for Additional Information',
                'subject': 'Re: {{subject}} - Additional Information Needed',
                'body': '''Dear {{sender_name}},

Thank you for your {{event_type}} request with {{organization}}.

To better evaluate your request, we need some additional information:

1. Specific topics or issues you would like to discuss
2. Expected number of attendees
3. Preferred meeting format (in-person, virtual, etc.)
4. Any materials or background information you can provide
5. Alternative dates if {{event_date}} is not available

Please provide this information at your earliest convenience so we can properly review your request.

Thank you for your patience.

Best regards,
{{staff_name}}
Congressional Staff''',
                'variables': ['sender_name', 'subject', 'event_type', 'organization', 'event_date', 'staff_name'],
                'is_default': True
            },
            {
                'name': 'Meeting Confirmed',
                'subject': 'Re: {{subject}} - Meeting Confirmed',
                'body': '''Dear {{sender_name}},

We are pleased to confirm your meeting request.

Meeting Details:
- Date: {{event_date}}
- Time: [Time to be confirmed]
- Location: {{event_location}}
- Organization: {{organization}}
- Type: {{event_type}}

Please confirm your attendance and let us know if you have any special requirements or if you need to make any changes to these arrangements.

We look forward to meeting with you.

Best regards,
{{staff_name}}
Congressional Staff''',
                'variables': ['sender_name', 'subject', 'event_date', 'event_location', 'organization', 'event_type', 'staff_name'],
                'is_default': True
            }
        ]

        created_count = 0
        for template_data in templates:
            template, created = EmailTemplate.objects.get_or_create(
                name=template_data['name'],
                defaults={
                    'subject': template_data['subject'],
                    'body': template_data['body'],
                    'variables': template_data['variables'],
                    'is_default': template_data['is_default'],
                    'created_by': system_user,
                    'modified_by': system_user,
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created template: {template.name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Template already exists: {template.name}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} email templates')
        )