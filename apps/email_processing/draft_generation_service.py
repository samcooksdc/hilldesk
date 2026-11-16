# SPDX-License-Identifier: Apache-2.0
"""
Draft generation service for HillDesk email responses.
Orchestrates LLM-based draft generation with congressional guardrails.
"""

import logging
from typing import Dict, Any, Optional, Generator


from .llm_providers.base import DraftGenerationResult

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')


class DraftLimitExceeded(Exception):
    """Raised when the per-session draft regeneration limit is exceeded."""
    pass


class DraftGenerationService:
    """
    Service for generating AI email draft responses.

    Gathers context from inbound emails and events, invokes the LLM provider,
    and applies congressional guardrails. AI drafts are NOT persisted unless
    explicitly saved or sent by staff.
    """

    MAX_REGENERATIONS = 3

    def __init__(self):
        self._provider = None

    @property
    def provider(self):
        """Lazily initialize the LLM provider."""
        if self._provider is None:
            from .llm_providers import get_llm_provider
            self._provider = get_llm_provider()
        return self._provider

    def generate_draft(
        self,
        email_processing_id: str,
        event_id: str = None,
        template_id: str = None,
        refinement: Optional[str] = None,
        previous_draft: Optional[str] = None,
        session_count: int = 0,
        user=None,
        user_prompt: Optional[str] = None,
    ) -> DraftGenerationResult:
        """
        Generate an email draft with guardrails.

        Args:
            email_processing_id: ID of the inbound EmailProcessing record
            event_id: Optional event ID for context
            template_id: Optional template ID to base draft on
            refinement: Optional refinement type (shorter/more_formal/more_friendly/try_again)
            previous_draft: Optional previous draft text for iterative refinement
            session_count: Number of drafts already generated in this session
            user: The requesting user (for audit logging)

        Returns:
            DraftGenerationResult with draft text and metadata

        Raises:
            DraftLimitExceeded: If session_count >= MAX_REGENERATIONS
        """
        if session_count >= self.MAX_REGENERATIONS:
            raise DraftLimitExceeded(
                f"Maximum of {self.MAX_REGENERATIONS} draft generations per session reached."
            )

        # Gather context
        inbound_email, event_context = self._gather_context(
            email_processing_id, event_id, user
        )

        # Get template text if specified
        template_text = None
        if template_id:
            template_text = self._get_template_text(template_id)

        # Generate draft
        result = self.provider.generate_email_draft(
            inbound_email=inbound_email,
            event_context=event_context,
            template_text=template_text,
            refinement=refinement,
            previous_draft=previous_draft,
            user_prompt=user_prompt,
        )

        # Audit log
        security_logger.info(
            'AI email draft generated',
            extra={
                'user': user.email if user else 'unknown',
                'email_processing_id': email_processing_id,
                'event_id': event_id,
                'refinement': refinement,
                'session_count': session_count + 1,
                'provider': self.provider.get_provider_name(),
            }
        )

        return result

    def generate_draft_stream(
        self,
        email_processing_id: str,
        event_id: str = None,
        template_id: str = None,
        refinement: Optional[str] = None,
        previous_draft: Optional[str] = None,
        session_count: int = 0,
        user=None,
        user_prompt: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Generate an email draft with streaming output.

        Yields text chunks as they are generated.
        Same arguments as generate_draft().
        """
        if session_count >= self.MAX_REGENERATIONS:
            raise DraftLimitExceeded(
                f"Maximum of {self.MAX_REGENERATIONS} draft generations per session reached."
            )

        inbound_email, event_context = self._gather_context(
            email_processing_id, event_id, user
        )

        template_text = None
        if template_id:
            template_text = self._get_template_text(template_id)

        security_logger.info(
            'AI email draft generation started (streaming)',
            extra={
                'user': user.email if user else 'unknown',
                'email_processing_id': email_processing_id,
                'event_id': event_id,
                'refinement': refinement,
                'session_count': session_count + 1,
                'provider': self.provider.get_provider_name(),
            }
        )

        yield from self.provider.generate_email_draft_stream(
            inbound_email=inbound_email,
            event_context=event_context,
            template_text=template_text,
            refinement=refinement,
            previous_draft=previous_draft,
            user_prompt=user_prompt,
        )

    def _gather_context(
        self, email_processing_id: str, event_id: str = None, user=None
    ) -> tuple:
        """
        Gather context from the inbound email and event for draft generation.

        Returns:
            Tuple of (inbound_email_text, event_context_dict)
        """
        from .models import EmailProcessing
        from apps.event_management.models import Event

        # Get inbound email
        inbound_email = ""
        try:
            email_proc = EmailProcessing.objects.get(id=email_processing_id)
            subject = email_proc.subject or ''
            body_data = email_proc.get_email_body() if hasattr(email_proc, 'get_email_body') else {}
            body = body_data.get('text', '') if isinstance(body_data, dict) else str(body_data)
            inbound_email = f"Subject: {subject}\n\n{body}"
        except EmailProcessing.DoesNotExist:
            logger.warning(f"EmailProcessing {email_processing_id} not found for draft context")

        # Build event context
        event_context: Dict[str, Any] = {}
        if event_id:
            try:
                event = Event.objects.get(id=event_id)
                event_context['event_title'] = event.title or ''
                event_context['event_date'] = (
                    event.start_date.strftime('%B %d, %Y') if event.start_date else ''
                )
                event_context['event_time'] = (
                    event.start_time.strftime('%I:%M %p').lstrip('0') if event.start_time else ''
                )
                event_context['event_end_date'] = (
                    event.end_date.strftime('%B %d, %Y') if event.end_date else ''
                )
                event_context['event_end_time'] = (
                    event.end_time.strftime('%I:%M %p').lstrip('0') if event.end_time else ''
                )
                event_context['event_location'] = event.location or ''
                event_context['event_description'] = event.description or ''
                event_context['event_status'] = event.get_status_display_from_office() if event.status else ''
                event_context['organization'] = event.group or ''
                event_context['contact_name'] = event.point_of_contact_name or ''
                event_context['contact_email'] = event.point_of_contact_email or ''
                event_context['contact_phone'] = event.point_of_contact_phone or ''
            except Event.DoesNotExist:
                logger.warning(f"Event {event_id} not found for draft context")

        # Add user/office context
        if user:
            event_context['staffer_name'] = user.get_full_name() or user.email
            office = getattr(user, 'office', None)
            if office:
                event_context['member_name'] = getattr(office, 'member_name', '') or ''

        # Add sender info from email
        try:
            email_proc = EmailProcessing.objects.get(id=email_processing_id)
            event_context['sender_name'] = email_proc.sender_name or email_proc.sender or ''
        except EmailProcessing.DoesNotExist:
            pass

        return inbound_email, event_context

    def _get_template_text(self, template_id: str) -> Optional[str]:
        """Get template body text by ID."""
        from apps.event_management.models import EmailTemplate
        try:
            template = EmailTemplate.objects.get(id=template_id)
            return template.body
        except EmailTemplate.DoesNotExist:
            logger.warning(f"Template {template_id} not found for draft generation")
            return None
