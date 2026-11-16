# SPDX-License-Identifier: Apache-2.0
"""
Management command to create default email templates.
"""

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.event_management.models import EmailTemplate

logger = logging.getLogger('apps.event_management')


class Command(BaseCommand):
    help = 'Creates default email templates for common response types'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recreation of default templates even if they exist',
        )
    
    def handle(self, *args, **options):
        force = options.get('force', False)
        created_count = 0
        updated_count = 0
        
        # Define default templates
        default_templates = [
            {
                'name': 'Meeting Accepted',
                'category': 'accept',
                'subject': 'RE: {{ original_subject }} - Meeting Accepted',
                'body': '''<p>Dear {{ sender_name }},</p>

<p>Thank you for your email regarding a meeting request. I am pleased to confirm that 
{{ recipient_name }} is available to meet with you on {{ event_date }} at {{ event_time }}{% if event_location %} at {{ event_location }}{% endif %}.</p>

<p>If you have any specific topics you would like to discuss or any materials you would like to share in advance, 
please feel free to send them to our office.</p>

<p>Should you need to make any changes to this appointment or have any questions, 
please don't hesitate to contact our office.</p>

<p>We look forward to meeting with you.</p>

<p>Best regards,<br>
Office of {{ recipient_name }}<br>
{{ office_name }}</p>''',
                'is_html': True,
                'is_default': True,
                'is_active': True,
            },
            {
                'name': 'Meeting Declined',
                'category': 'decline',
                'subject': 'RE: {{ original_subject }} - Unable to Accommodate Meeting Request',
                'body': '''<p>Dear {{ sender_name }},</p>

<p>Thank you for your email requesting a meeting with {{ recipient_name }}.</p>

<p>Unfortunately, due to scheduling constraints and prior commitments, 
{{ recipient_name }} will not be able to accommodate this meeting request at this time.</p>

<p>{{ recipient_name }} appreciates your understanding and would be happy to consider 
future meeting opportunities as they arise.</p>

<p>If there is specific information you would like to share with our office, 
please feel free to send it, and we will ensure it receives appropriate attention.</p>

<p>Thank you for your understanding.</p>

<p>Best regards,<br>
Office of {{ recipient_name }}<br>
{{ office_name }}</p>''',
                'is_html': True,
                'is_default': True,
                'is_active': True,
            },
            {
                'name': 'Meeting Rescheduling Request',
                'category': 'reschedule',
                'subject': 'RE: {{ original_subject }} - Meeting Rescheduling Request',
                'body': '''<p>Dear {{ sender_name }},</p>

<p>Thank you for your email requesting a meeting with {{ recipient_name }}.</p>

<p>Unfortunately, {{ recipient_name }} is unavailable at the time you suggested. 
However, we would be happy to reschedule for a more convenient time.</p>

<p>Would any of the following alternative times work for you?</p>

<ul>
    <li>[ALTERNATIVE DATE/TIME 1]</li>
    <li>[ALTERNATIVE DATE/TIME 2]</li>
    <li>[ALTERNATIVE DATE/TIME 3]</li>
</ul>

<p>If none of these times work, please let us know your availability over the next few weeks, 
and we will do our best to find a suitable time.</p>

<p>We look forward to hearing from you.</p>

<p>Best regards,<br>
Office of {{ recipient_name }}<br>
{{ office_name }}</p>''',
                'is_html': True,
                'is_default': True,
                'is_active': True,
            },
            {
                'name': 'Meeting Acknowledgment',
                'category': 'acknowledge',
                'subject': 'RE: {{ original_subject }} - Meeting Request Received',
                'body': '''<p>Dear {{ sender_name }},</p>

<p>Thank you for your email requesting a meeting with {{ recipient_name }}.</p>

<p>We have received your request and are currently reviewing {{ recipient_name }}'s schedule 
to determine availability. Our office will get back to you shortly with a response.</p>

<p>If you have any additional information that would be helpful for us to know regarding 
this meeting request, please feel free to reply to this email.</p>

<p>Thank you for your patience.</p>

<p>Best regards,<br>
Office of {{ recipient_name }}<br>
{{ office_name }}</p>''',
                'is_html': True,
                'is_default': True,
                'is_active': True,
            },
            {
                'name': 'Additional Information Request',
                'category': 'request_info',
                'subject': 'RE: {{ original_subject }} - Additional Information Requested',
                'body': '''<p>Dear {{ sender_name }},</p>

<p>Thank you for your email requesting a meeting with {{ recipient_name }}.</p>

<p>To better prepare for this potential meeting, we would appreciate if you could provide 
some additional information:</p>

<ul>
    <li>The specific topics you would like to discuss</li>
    <li>Names and titles of all attendees who would join the meeting</li>
    <li>Any preferred dates and times for the meeting</li>
    <li>Estimated duration of the meeting</li>
</ul>

<p>Once we receive this information, we will be better able to evaluate the request 
and check {{ recipient_name }}'s availability.</p>

<p>Thank you for your assistance.</p>

<p>Best regards,<br>
Office of {{ recipient_name }}<br>
{{ office_name }}</p>''',
                'is_html': True,
                'is_default': False,
                'is_active': True,
            },
            {
                'name': 'Follow-up After Meeting',
                'category': 'follow_up',
                'subject': 'Follow-up: Meeting on {{ event_date }}',
                'body': '''<p>Dear {{ sender_name }},</p>

<p>Thank you for meeting with {{ recipient_name }} on {{ event_date }}.</p>

<p>{{ recipient_name }} appreciated the opportunity to discuss [meeting topic] with you 
and found the conversation to be valuable.</p>

<p>As discussed during our meeting, our office will [action item 1]. Additionally, 
if you could provide [requested information], that would be helpful for our next steps.</p>

<p>If you have any questions or need further information, please don't hesitate to contact us.</p>

<p>Thank you again for your time.</p>

<p>Best regards,<br>
Office of {{ recipient_name }}<br>
{{ office_name }}</p>''',
                'is_html': True,
                'is_default': False,
                'is_active': True,
            },
            {
                'name': 'Plain Text Acknowledgment',
                'category': 'acknowledge',
                'subject': 'RE: {{ original_subject }} - Meeting Request Received',
                'body': '''Dear {{ sender_name }},

Thank you for your email requesting a meeting with {{ recipient_name }}.

We have received your request and are currently reviewing {{ recipient_name }}'s schedule 
to determine availability. Our office will get back to you shortly with a response.

If you have any additional information that would be helpful for us to know regarding 
this meeting request, please feel free to reply to this email.

Thank you for your patience.

Best regards,
Office of {{ recipient_name }}
{{ office_name }}''',
                'is_html': False,
                'is_default': False,
                'is_active': True,
            },
        ]
        
        for template_data in default_templates:
            name = template_data['name']
            category = template_data['category']
            
            # Check if template already exists
            existing = EmailTemplate.objects.filter(name=name, category=category).first()
            
            if existing and not force:
                self.stdout.write(f"Template '{name}' already exists, skipping (use --force to override)")
                continue
            
            if existing and force:
                # Update existing template
                for key, value in template_data.items():
                    setattr(existing, key, value)
                existing.modified = timezone.now()
                existing.save()
                updated_count += 1
                self.stdout.write(self.style.SUCCESS(f"Updated template: {name}"))
            else:
                # Create new template
                EmailTemplate.objects.create(**template_data)
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created template: {name}"))
        
        self.stdout.write(self.style.SUCCESS(
            f"Completed: {created_count} templates created, {updated_count} templates updated"
        ))