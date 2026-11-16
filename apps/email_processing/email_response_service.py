# SPDX-License-Identifier: Apache-2.0
"""
Email response service for HillDesk.
Handles template-based email responses to scheduling requests.
"""

import logging
import re
from typing import Dict, List, Optional, Any
from django.utils import timezone
from django.conf import settings
from django.db.models import Q

from .graph_client import MicrosoftGraphClient, GraphAPIError
from .models import EmailProcessing, EmailResponse
from apps.event_management.models import EmailTemplate
from apps.authentication.models import User

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')


class EmailResponseError(Exception):
    """Exception raised for email response errors."""
    pass


class EmailResponseService:
    """
    Service for managing email responses to scheduling requests.
    Handles template-based responses and tracking.
    """
    
    def __init__(self, user_email: str = None):
        """
        Initialize email response service.

        Args:
            user_email: Email address of the user for email operations
        """
        self.user_email = user_email
        self._graph_client = None

    @property
    def graph_client(self):
        """Lazy-load the Graph client only when email operations are needed."""
        if self._graph_client is None:
            self._graph_client = MicrosoftGraphClient()
        return self._graph_client

    def _deliver(self, email_processing: EmailProcessing, body: str, is_html: bool) -> None:
        """
        Deliver the reply via Microsoft Graph.

        In development (MOCK_MICROSOFT_GRAPH=True) the send is simulated so the
        reply flow can be tested end-to-end without Graph credentials — the
        EmailResponse is still recorded and marked as sent.
        """
        if getattr(settings, 'MOCK_MICROSOFT_GRAPH', False):
            logger.info(
                "MOCK_MICROSOFT_GRAPH enabled — simulating email send for %s (not actually delivered)",
                email_processing.email_id,
            )
            return

        self.graph_client.reply_to_email(
            user_id=self.user_email,
            email_id=email_processing.email_id,
            body=body,
            is_html=is_html,
        )
    
    def get_available_templates(self, category: str = None, office=None, include_inactive: bool = False) -> List[EmailTemplate]:
        """
        Get available email templates, optionally filtered by category and scoped to office.

        Returns templates belonging to the given office plus system defaults (office=None).

        Args:
            category: Optional category to filter templates
            office: Optional Office instance to scope templates
            include_inactive: When True, also return deactivated templates
                (used by the settings management UI). Defaults to False so
                callers that actually send email only ever see active ones.

        Returns:
            List of EmailTemplate objects
        """
        queryset = EmailTemplate.objects.all()
        if not include_inactive:
            queryset = queryset.filter(is_active=True)

        if office:
            queryset = queryset.filter(Q(office=office) | Q(office__isnull=True))
        else:
            queryset = queryset.filter(office__isnull=True)

        if category:
            queryset = queryset.filter(category=category)

        return list(queryset.order_by('category', 'name'))
    
    def get_template_by_id(self, template_id: str) -> Optional[EmailTemplate]:
        """
        Get a specific email template by ID.
        
        Args:
            template_id: ID of the template to retrieve
            
        Returns:
            EmailTemplate object if found, None otherwise
        """
        try:
            return EmailTemplate.objects.get(id=template_id)
        except EmailTemplate.DoesNotExist:
            logger.warning(f"Template with ID {template_id} not found")
            return None
    
    @staticmethod
    def render_bracket_variables(text: str, context: Dict[str, Any]) -> str:
        """
        Replace {variable_name} placeholders with context values.
        Unmatched variables remain as-is (e.g., {custom_1} stays visible).

        Args:
            text: Template text with {variable} placeholders
            context: Dictionary of variable values

        Returns:
            Rendered text
        """
        return re.sub(
            r'\{(\w+)\}',
            lambda m: str(context.get(m.group(1), m.group(0))),
            text
        )

    def render_template(self, template: EmailTemplate, context_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Render an email template with the provided context data.
        Uses {variable} bracket syntax for intuitive staff editing.

        Args:
            template: EmailTemplate object to render
            context_data: Dictionary of context data for template rendering

        Returns:
            Dictionary with rendered subject and body
        """
        try:
            rendered_subject = self.render_bracket_variables(template.subject, context_data)
            rendered_body = self.render_bracket_variables(template.body, context_data)

            return {
                'subject': rendered_subject,
                'body': rendered_body,
                'is_html': template.is_html
            }
        except Exception as e:
            logger.error(f"Error rendering template {template.id}: {e}")
            raise EmailResponseError(f"Template rendering failed: {e}")
    
    def send_templated_response(self, 
                               email_processing: EmailProcessing,
                               template: EmailTemplate,
                               context_data: Dict[str, Any] = None,
                               cc_recipients: List[str] = None,
                               bcc_recipients: List[str] = None) -> EmailResponse:
        """
        Send a templated email response to a scheduling request.
        
        Args:
            email_processing: EmailProcessing object for the original email
            template: EmailTemplate to use for the response
            context_data: Dictionary of context data for template rendering
            cc_recipients: List of CC recipients
            bcc_recipients: List of BCC recipients
            
        Returns:
            EmailResponse object for the sent response
            
        Raises:
            EmailResponseError: If sending the response fails
        """
        if not self.user_email:
            raise EmailResponseError("User email not provided for email response service")
        
        if not email_processing.sender:
            raise EmailResponseError("Original email has no sender")
        
        # Prepare context data
        if context_data is None:
            context_data = {}
            
        # Add standard context variables
        # staffer_name = the staff member drafting the response (the logged-in
        # user). Prefer the User's full name; fall back to an email-derived
        # display name when the lookup fails (e.g. preview / system user).
        staffer_user = User.objects.filter(email__iexact=self.user_email).first()
        staffer_display = (
            staffer_user.get_full_name() if staffer_user and staffer_user.get_full_name()
            else self.user_email.split('@')[0].replace('.', ' ').title()
        )

        context_data.update({
            'sender_name': email_processing.sender_name or 'Constituent',
            'recipient_name': self.user_email.split('@')[0].replace('.', ' ').title(),
            'staffer_name': staffer_display,
            'office_name': settings.OFFICE_NAME if hasattr(settings, 'OFFICE_NAME') else 'Congressional Office',
            'date': timezone.now().strftime('%B %d, %Y'),
            'original_subject': email_processing.subject or '',
        })
        
        # Add event data if available
        if hasattr(email_processing, 'event') and email_processing.event:
            event = email_processing.event
            context_data.update({
                'event_type': event.type,
                'event_date': event.start_date.strftime('%B %d, %Y') if event.start_date else '',
                'event_time': event.time_display,
                'event_location': event.location or '',
                'event_details': event.description or '',
                'event_status': event.get_status_display_from_office(),
            })
        
        try:
            # Render the template
            rendered = self.render_template(template, context_data)
            
            # Create EmailResponse record
            response = EmailResponse.objects.create(
                original_email=email_processing,
                template_used=template,
                subject=rendered['subject'],
                body=rendered['body'],
                is_html=rendered['is_html'],
                sender=self.user_email,
                recipient=email_processing.sender,
                cc_recipients=cc_recipients or [],
                bcc_recipients=bcc_recipients or [],
                status='pending',
                created_by=User.objects.get(email=self.user_email) if User.objects.filter(email=self.user_email).exists() else None
            )
            
            # Send the email via Graph API (simulated in mock/dev mode)
            try:
                self._deliver(email_processing, rendered['body'], rendered['is_html'])

                # Update response status to sent
                response.status = 'sent'
                response.sent_at = timezone.now()
                response.save(update_fields=['status', 'sent_at'])
                
                # Log the response
                security_logger.info(
                    'Email response sent',
                    extra={
                        'user_email': self.user_email,
                        'original_email_id': email_processing.email_id,
                        'response_id': str(response.id),
                        'template_id': str(template.id),
                        'template_name': template.name,
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                
                return response
                
            except GraphAPIError as e:
                # Update response status to failed
                response.status = 'failed'
                response.error_message = str(e)
                response.save(update_fields=['status', 'error_message'])
                
                logger.error(f"Failed to send email response: {e}")
                raise EmailResponseError(f"Failed to send email response: {e}")
                
        except Exception as e:
            logger.error(f"Error sending templated response: {e}")
            raise EmailResponseError(f"Error sending templated response: {e}")
    
    def get_response_history(self, email_processing: EmailProcessing) -> List[EmailResponse]:
        """
        Get history of responses for a specific email.
        
        Args:
            email_processing: EmailProcessing object
            
        Returns:
            List of EmailResponse objects
        """
        return list(EmailResponse.objects.filter(original_email=email_processing).order_by('-created'))
    
    def create_custom_response(self, 
                             email_processing: EmailProcessing,
                             subject: str,
                             body: str,
                             is_html: bool = False,
                             cc_recipients: List[str] = None,
                             bcc_recipients: List[str] = None) -> EmailResponse:
        """
        Create and send a custom (non-templated) email response.
        
        Args:
            email_processing: EmailProcessing object for the original email
            subject: Email subject
            body: Email body
            is_html: Whether the body is HTML
            cc_recipients: List of CC recipients
            bcc_recipients: List of BCC recipients
            
        Returns:
            EmailResponse object for the sent response
            
        Raises:
            EmailResponseError: If sending the response fails
        """
        if not self.user_email:
            raise EmailResponseError("User email not provided for email response service")
        
        if not email_processing.sender:
            raise EmailResponseError("Original email has no sender")
        
        try:
            # Create EmailResponse record
            response = EmailResponse.objects.create(
                original_email=email_processing,
                template_used=None,  # No template used
                subject=subject,
                body=body,
                is_html=is_html,
                sender=self.user_email,
                recipient=email_processing.sender,
                cc_recipients=cc_recipients or [],
                bcc_recipients=bcc_recipients or [],
                status='pending',
                created_by=User.objects.get(email=self.user_email) if User.objects.filter(email=self.user_email).exists() else None
            )
            
            # Send the email via Graph API (simulated in mock/dev mode)
            try:
                self._deliver(email_processing, body, is_html)

                # Update response status to sent
                response.status = 'sent'
                response.sent_at = timezone.now()
                response.save(update_fields=['status', 'sent_at'])
                
                # Log the response
                security_logger.info(
                    'Custom email response sent',
                    extra={
                        'user_email': self.user_email,
                        'original_email_id': email_processing.email_id,
                        'response_id': str(response.id),
                        'timestamp': timezone.now().isoformat(),
                    }
                )
                
                return response
                
            except GraphAPIError as e:
                # Update response status to failed
                response.status = 'failed'
                response.error_message = str(e)
                response.save(update_fields=['status', 'error_message'])
                
                logger.error(f"Failed to send custom email response: {e}")
                raise EmailResponseError(f"Failed to send custom email response: {e}")
                
        except Exception as e:
            logger.error(f"Error sending custom response: {e}")
            raise EmailResponseError(f"Error sending custom response: {e}")
    
    def get_default_templates(self) -> Dict[str, EmailTemplate]:
        """
        Get default templates for common response types.
        
        Returns:
            Dictionary mapping response types to templates
        """
        defaults = {}
        
        # Get default templates by category
        for category in ['accept', 'decline', 'reschedule', 'acknowledge']:
            try:
                template = EmailTemplate.objects.filter(
                    category=category,
                    is_active=True,
                    is_default=True
                ).first()
                
                if template:
                    defaults[category] = template
            except Exception as e:
                logger.warning(f"Error getting default template for {category}: {e}")
        
        return defaults


def send_templated_response(email_processing_id: str, template_id: str, user_email: str, 
                          context_data: Dict[str, Any] = None) -> bool:
    """
    Convenience function to send a templated email response.
    
    Args:
        email_processing_id: ID of the EmailProcessing object
        template_id: ID of the EmailTemplate to use
        user_email: Email address of the sender
        context_data: Dictionary of context data for template rendering
        
    Returns:
        True if response was sent successfully, False otherwise
    """
    try:
        email_processing = EmailProcessing.objects.get(id=email_processing_id)
        template = EmailTemplate.objects.get(id=template_id)
        
        service = EmailResponseService(user_email)
        response = service.send_templated_response(email_processing, template, context_data)
        
        return response.status == 'sent'
    except Exception as e:
        logger.error(f"Error in send_templated_response: {e}")
        return False