# SPDX-License-Identifier: Apache-2.0
"""
API Services for HillDesk.
"""

import logging
import json
from typing import Dict, List, Any, Optional

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.event_management.models import Event, EventChangeSuggestion, EventChangeHistory, EventApproval
from apps.email_processing.models import EmailProcessing
from apps.email_processing.graph_client import MicrosoftGraphClient

logger = logging.getLogger('apps.api')
User = get_user_model()


class SmartExtractService:
    """
    Service for handling AI-powered SmartExtract functionality.
    Provides AI suggestions for event fields based on email content.
    """
    
    def __init__(self):
        self.graph_client = None

        # Initialize Graph client if available
        try:
            if all([
                getattr(settings, 'MICROSOFT_TENANT_ID', None),
                getattr(settings, 'MICROSOFT_CLIENT_ID', None),
                getattr(settings, 'MICROSOFT_CLIENT_SECRET', None)
            ]):
                self.graph_client = MicrosoftGraphClient()
        except Exception as e:
            logger.warning(f"Graph client not available for SmartExtract: {e}")

    def generate_suggestions(self, event: Event, email_content: str = None) -> List[Dict[str, Any]]:
        """
        Generate AI suggestions for event fields based on email content.

        Reimplemented on the single extraction call (spec §7): the event's
        primary linked email is bundled and sent through
        ``provider.extract_candidates``; the strongest candidate's event fields
        become field-level suggestions where they differ from the event.
        """
        from apps.email_processing.llm_providers import (
            get_llm_provider, validate_candidate_set,
        )
        from apps.email_processing.llm_providers.schema import MessageBundle

        suggestions = []
        try:
            email_record, email_content = self._email_for_event(event, email_content)
            if not email_content:
                logger.warning(f"No email content available for event {event.id}")
                return suggestions

            bundle = MessageBundle(
                subject=(email_record.subject if email_record else event.title) or '',
                new_content=email_content,
                sender_email=(email_record.sender if email_record else '') or '',
                sender_name=(email_record.sender_name if email_record else '') or '',
                received_at_iso=(email_record.received.isoformat()
                                 if email_record else ''),
                office_timezone=getattr(settings, 'TIME_ZONE', 'America/New_York'),
            )
            output = get_llm_provider().extract_candidates(bundle)
            if output.error or validate_candidate_set(output.data):
                logger.warning(f"SmartExtract extraction failed for event {event.id}: "
                               f"{output.error or 'schema-invalid output'}")
                return suggestions

            candidates = output.data.get('candidates', [])
            if not candidates:
                return suggestions
            best = max(candidates, key=lambda c: c.get('confidence', 0.0))
            confidence = best.get('confidence', 0.8)
            source_email_id = email_record.email_id if email_record else ''

            for field, value in (best.get('event') or {}).items():
                if value in (None, '', []):
                    continue
                current_value = getattr(event, field, None)
                if str(value) == str(current_value or ''):
                    continue
                suggestion = self._create_suggestion(
                    field=field,
                    value=value,
                    confidence=confidence,
                    source_email_id=source_email_id,
                    email_content=email_content,
                )
                if suggestion:
                    suggestions.append(suggestion)

            logger.info(f"Generated {len(suggestions)} suggestions for event {event.id}")

        except Exception as e:
            logger.error(f"Error generating suggestions for event {event.id}: {e}")

        return suggestions

    def _email_for_event(self, event: Event, email_content: str = None):
        """Resolve (EmailProcessing, body text) for the event's primary email."""
        link = (event.email_links
                .filter(mode='include')
                .order_by('-is_primary', '-linked_at')
                .select_related('email')
                .first())
        email_record = link.email if link else None
        if not email_content and email_record is not None:
            body = email_record.get_email_body() or {}
            email_content = (body.get('text') or ''
                             or email_record.raw_content or '')
        return email_record, email_content or None
    
    def _create_suggestion(self, field: str, value: Any, confidence: float,
                          source_email_id: str, email_content: str,
                          reasoning: str = '') -> Optional[Dict[str, Any]]:
        """Create a suggestion dictionary."""
        try:
            # Find the source text range (simplified approach)
            source_range = self._find_source_range(str(value), email_content)
            
            suggestion = {
                'field': field,
                'value': value,
                'confidence': min(max(confidence, 0.0), 1.0),  # Clamp between 0 and 1
                'source_email_id': source_email_id,
                'source_text_range': source_range,
                'reasoning': reasoning
            }
            
            return suggestion
            
        except Exception as e:
            logger.warning(f"Error creating suggestion for field {field}: {e}")
            return None
    
    def _find_source_range(self, value: str, email_content: str) -> List[int]:
        """Find the text range in email content that corresponds to the extracted value."""
        try:
            # Simple text search - in a real implementation, this would be more sophisticated
            value_str = str(value).strip()
            if not value_str or not email_content:
                return [0, 0]
            
            # Look for exact match first
            start_pos = email_content.lower().find(value_str.lower())
            if start_pos != -1:
                return [start_pos, start_pos + len(value_str)]
            
            # Look for partial matches or keywords
            words = value_str.split()
            if words:
                first_word = words[0]
                start_pos = email_content.lower().find(first_word.lower())
                if start_pos != -1:
                    # Estimate end position
                    end_pos = min(start_pos + len(value_str), len(email_content))
                    return [start_pos, end_pos]
            
            # Default to beginning of content
            return [0, min(50, len(email_content))]
            
        except Exception as e:
            logger.warning(f"Error finding source range for value '{value}': {e}")
            return [0, 0]
    
    def approve_suggestion(self, event: Event, field: str, value: Any, user) -> bool:
        """
        Approve an AI suggestion and update the event field.
        
        Args:
            event: Event instance to update
            field: Field name to update
            value: New value for the field
            user: User approving the suggestion
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Validate field name
            if not hasattr(event, field):
                logger.warning(f"Invalid field name: {field}")
                return False

            # Normalized contact/org fields are read-only properties; route the
            # approval through the contacts service rather than setattr.
            if field in {'group', 'point_of_contact_name',
                         'point_of_contact_email', 'point_of_contact_phone'}:
                return self._apply_normalized_suggestion(event, field, value, user)

            # Get old value for audit trail
            old_value = getattr(event, field, None)

            # Update the field
            setattr(event, field, value)
            event.modified_by = user
            event.save()
            
            # Create change history record
            from apps.event_management.models import EventChangeHistory
            EventChangeHistory.objects.create(
                event=event,
                user=user,
                field=field,
                old_value=str(old_value) if old_value is not None else '',
                new_value=str(value) if value is not None else '',
                ip_address=getattr(user, 'last_ip', None)
            )
            
            logger.info(f"Approved suggestion for event {event.id}, field {field}")
            return True
            
        except Exception as e:
            logger.error(f"Error approving suggestion for event {event.id}: {e}")
            return False
    
    def _apply_normalized_suggestion(self, event: Event, field: str, value: Any, user) -> bool:
        """Apply an approved suggestion for a normalized contact/org field.

        Creates/links the relevant Contact or Organization instead of writing a
        denormalized column (which no longer exists).
        """
        try:
            from apps.contacts.services import apply_field_to_event
            apply_field_to_event(event, field, value, user)

            from apps.event_management.models import EventChangeHistory
            EventChangeHistory.objects.create(
                event=event, user=user, field=field, old_value='',
                new_value=str(value) if value is not None else '',
                ip_address=getattr(user, 'last_ip', None),
            )
            logger.info(f"Applied normalized suggestion for event {event.id}, field {field}")
            return True
        except Exception as e:
            logger.error(f"Error applying normalized suggestion for event {event.id}: {e}")
            return False

    def reject_suggestion(self, event: Event, field: str, user) -> bool:
        """
        Reject an AI suggestion.

        Args:
            event: Event instance
            field: Field name that was suggested
            user: User rejecting the suggestion

        Returns:
            True if successful, False otherwise
        """
        try:
            # Log the rejection for analytics
            logger.info(f"Suggestion rejected for event {event.id}, field {field} by user {user.id}")

            # In a more sophisticated implementation, we might store rejection data
            # for improving the AI model

            return True

        except Exception as e:
            logger.error(f"Error rejecting suggestion for event {event.id}: {e}")
            return False


class EventEditingService:
    """
    Service for handling event editing operations.
    Provides high-level operations for the event editing interface.
    """
    
    def __init__(self):
        self.smart_extract = SmartExtractService()
    
    def get_editing_panel_data(self, event_id: str, user) -> Dict[str, Any]:
        """
        Get complete data for event editing panel.
        
        Args:
            event_id: Event UUID
            user: Requesting user
            
        Returns:
            Dictionary with all panel data
        """
        try:
            from django.shortcuts import get_object_or_404
            from apps.event_management.models import EventChangeHistory, EmailTemplate
            
            # Get event
            event = get_object_or_404(Event, id=event_id)
            
            # Get related emails
            from django.db import models
            
            related_emails = EmailProcessing.objects.filter(
                models.Q(event=event) | models.Q(email_id=event.original_email_id)
            ).select_related('processed_by').order_by('-received')
            
            # Get change history
            change_history = EventChangeHistory.objects.filter(
                event=event
            ).select_related('user').order_by('-timestamp')[:20]
            
            # Get email templates
            email_templates = EmailTemplate.objects.filter(
                is_default=True
            ).order_by('name')
            
            # Generate AI suggestions if in SmartExtract mode
            ai_suggestions = []
            if hasattr(event, '_smartextract_mode') and event._smartextract_mode:
                ai_suggestions = self.smart_extract.generate_suggestions(event)
            
            return {
                'event': event,
                'related_emails': related_emails,
                'change_history': change_history,
                'ai_suggestions': ai_suggestions,
                'email_templates': email_templates,
            }
            
        except Exception as e:
            logger.error(f"Error getting editing panel data for event {event_id}: {e}")
            raise
    
    def update_event_field(self, event_id: str, field: str, value: Any, user) -> bool:
        """
        Update a single event field with audit trail.
        
        Args:
            event_id: Event UUID
            field: Field name to update
            value: New value
            user: User making the change
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from django.shortcuts import get_object_or_404
            
            event = get_object_or_404(Event, id=event_id)
            
            # Validate field
            if not hasattr(event, field):
                logger.warning(f"Invalid field name: {field}")
                return False
            
            # Get old value
            old_value = getattr(event, field, None)
            
            # Update field
            setattr(event, field, value)
            event.modified_by = user
            event.save()
            
            # Create audit record
            from apps.event_management.models import EventChangeHistory
            EventChangeHistory.objects.create(
                event=event,
                user=user,
                field=field,
                old_value=str(old_value) if old_value is not None else '',
                new_value=str(value) if value is not None else '',
                ip_address=getattr(user, 'last_ip', None)
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating event field {field} for event {event_id}: {e}")
            return False
    
    def enable_smartextract_mode(self, event_id: str) -> bool:
        """
        Enable SmartExtract mode for an event.
        
        Args:
            event_id: Event UUID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from django.shortcuts import get_object_or_404
            
            get_object_or_404(Event, id=event_id)  # validates the event exists
            
            # Set SmartExtract mode flag (this could be stored in cache or as a model field)
            cache_key = f"smartextract_mode_{event_id}"
            cache.set(cache_key, True, timeout=3600)  # 1 hour timeout
            
            logger.info(f"SmartExtract mode enabled for event {event_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error enabling SmartExtract mode for event {event_id}: {e}")
            return False
    
    def disable_smartextract_mode(self, event_id: str) -> bool:
        """
        Disable SmartExtract mode for an event.
        
        Args:
            event_id: Event UUID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cache_key = f"smartextract_mode_{event_id}"
            cache.delete(cache_key)
            
            logger.info(f"SmartExtract mode disabled for event {event_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error disabling SmartExtract mode for event {event_id}: {e}")
            return False
    
    def is_smartextract_enabled(self, event_id: str) -> bool:
        """
        Check if SmartExtract mode is enabled for an event.

        Args:
            event_id: Event UUID

        Returns:
            True if enabled, False otherwise
        """
        cache_key = f"smartextract_mode_{event_id}"
        return cache.get(cache_key, False)


class FieldReviewService:
    """
    Service for handling human review of AI-extracted fields.
    Provides accept, reject, undo, and completion operations.
    Enforces human-in-the-loop review.
    """

    # Fields that can be reviewed
    REVIEWABLE_FIELDS = [
        'title', 'type', 'format', 'start_date', 'start_time', 'end_date',
        'end_time', 'location', 'group', 'description', 'legislative_topics',
        'participants', 'point_of_contact_name', 'point_of_contact_email',
        'point_of_contact_phone', 'duration', 'expected_attendees'
    ]

    # Keys in extracted_fields that are NOT scalar reviewable fields: the v2
    # multi-contact shape stores contacts[]/organizations[] (lists) and a
    # schema_version (int); 'meta' is the email-ingestion pipeline's additive
    # display block (intent, confidence, verbatim strings, duplicate_of). They
    # are not scalar fields and must be skipped by the scalar-field iteration.
    NON_FIELD_KEYS = frozenset({'contacts', 'organizations', 'schema_version', 'meta'})

    def __init__(self):
        self.logger = logging.getLogger('apps.api.review')

    def _scalar_fields(self, event):
        """Yield (name, data) for scalar reviewable fields, skipping v2 structure."""
        for name, data in (event.extracted_fields or {}).items():
            if name in self.NON_FIELD_KEYS:
                continue
            if isinstance(data, dict):
                yield name, data

    def _iter_cards(self, event):
        """Yield (kind, card) for every contact/organization review card."""
        ef = event.extracted_fields or {}
        for kind in ('contacts', 'organizations'):
            for card in (ef.get(kind) or []):
                yield kind, card

    def _find_card(self, event, kind, ref):
        for card in (event.extracted_fields or {}).get(kind) or []:
            if card.get('ref') == ref:
                return card
        return None

    def _card_field_keys(self, card):
        """Extracted field keys on a card that must each be reviewed individually.

        Excludes 'role' — it is staff-assigned, not AI-extracted, so it is not a
        review unit.
        """
        # An exact match with no additions/replaces is just a link to confirm —
        # there is nothing to review field-by-field, so the card itself is the
        # only unit (the reviewer just accepts or rejects it).
        if (card.get('resolution') or {}).get('action') == 'link':
            return []
        fields = card.get('fields', {}) or {}
        return [k for k in fields
                if k != 'role' and isinstance(fields[k], dict) and fields[k].get('value')]

    def _card_unit_counts(self, card):
        """(total, reviewed) review units for a card: the card itself + each field.

        A rejected card is fully closed (its fields are discarded). For a pending
        or accepted card, the card unit is reviewed once it leaves 'pending', and
        each field unit is reviewed once its key is in ``reviewed_fields``.
        """
        fkeys = self._card_field_keys(card)
        total = 1 + len(fkeys)
        status = card.get('status', 'pending')
        if status == 'rejected':
            return total, total
        reviewed = 1 if status != 'pending' else 0
        rf = set(card.get('reviewed_fields') or [])
        reviewed += sum(1 for k in fkeys if k in rf)
        return total, reviewed

    def accept_field(self, event: Event, field_name: str, user, ip_address: str = None) -> Dict[str, Any]:
        """
        Accept an AI-extracted field value.

        Args:
            event: Event instance
            field_name: Name of the field to accept
            user: User performing the action
            ip_address: Optional IP address for audit

        Returns:
            Dictionary with success status and review state
        """
        import json
        from django.utils import timezone
        from apps.event_management.models import EventReviewAuditLog

        if field_name not in self.REVIEWABLE_FIELDS:
            return {"success": False, "message": f"Invalid field: {field_name}"}

        extracted = event.extracted_fields.get(field_name)
        if not extracted:
            return {"success": False, "message": f"No extracted data for {field_name}"}

        # Update extracted_fields status
        event.extracted_fields[field_name]['status'] = 'accepted'
        event.extracted_fields[field_name]['reviewed_by'] = str(user.id)
        event.extracted_fields[field_name]['reviewed_at'] = timezone.now().isoformat()
        event.modified_by = user
        event.save()

        # Log the action
        EventReviewAuditLog.objects.create(
            event=event,
            field_name=field_name,
            action='accept',
            original_value=json.dumps(extracted.get('value', '')),
            user=user,
            ip_address=ip_address
        )

        # Check if all fields are reviewed
        review_complete = self.is_review_complete(event)
        if review_complete:
            self._complete_review(event, user)

        self.logger.info(f"Field {field_name} accepted for event {event.id} by user {user.id}")

        return {
            "success": True,
            "message": f"Field {field_name} accepted",
            "review_complete": review_complete,
            "fields_remaining": self.get_pending_field_count(event),
            "extracted_fields": event.extracted_fields
        }

    def reject_field(self, event: Event, field_name: str, user, ip_address: str = None) -> Dict[str, Any]:
        """
        Reject an AI-extracted field value.
        Clears the field so user can provide their own value.

        Args:
            event: Event instance
            field_name: Name of the field to reject
            user: User performing the action
            ip_address: Optional IP address for audit

        Returns:
            Dictionary with success status and review state
        """
        import json
        from django.utils import timezone
        from apps.event_management.models import EventReviewAuditLog

        if field_name not in self.REVIEWABLE_FIELDS:
            return {"success": False, "message": f"Invalid field: {field_name}"}

        extracted = event.extracted_fields.get(field_name)
        if not extracted:
            return {"success": False, "message": f"No extracted data for {field_name}"}

        # Store original value before rejection
        original_value = extracted.get('value', '')

        # Update status to rejected
        event.extracted_fields[field_name]['status'] = 'rejected'
        event.extracted_fields[field_name]['reviewed_by'] = str(user.id)
        event.extracted_fields[field_name]['reviewed_at'] = timezone.now().isoformat()

        # Clear the actual field value (user will provide their own).
        # Normalized contact/org fields have no column to clear; their links are
        # managed via the contacts API, so skip them here.
        from apps.contacts.services import NORMALIZED_EVENT_FIELDS
        if field_name not in NORMALIZED_EVENT_FIELDS and hasattr(event, field_name):
            field = event._meta.get_field(field_name)
            if field.null:
                setattr(event, field_name, None)
            elif hasattr(field, 'default') and field.default is not None:
                setattr(event, field_name, field.default)
            else:
                # For string fields, set to empty string
                if field.get_internal_type() in ['CharField', 'TextField']:
                    setattr(event, field_name, '')

        event.modified_by = user
        event.save()

        # Log the action
        EventReviewAuditLog.objects.create(
            event=event,
            field_name=field_name,
            action='reject',
            original_value=json.dumps(original_value),
            user=user,
            ip_address=ip_address
        )

        # Check if all fields are reviewed
        review_complete = self.is_review_complete(event)
        if review_complete:
            self._complete_review(event, user)

        self.logger.info(f"Field {field_name} rejected for event {event.id} by user {user.id}")

        return {
            "success": True,
            "message": f"Field {field_name} rejected",
            "review_complete": review_complete,
            "fields_remaining": self.get_pending_field_count(event),
            "extracted_fields": event.extracted_fields
        }

    def undo_reject(self, event: Event, field_name: str, user, ip_address: str = None) -> Dict[str, Any]:
        """
        Undo a rejection and restore the AI-extracted value.

        Args:
            event: Event instance
            field_name: Name of the field to undo rejection
            user: User performing the action
            ip_address: Optional IP address for audit

        Returns:
            Dictionary with success status
        """
        import json
        from apps.event_management.models import EventReviewAuditLog

        extracted = event.extracted_fields.get(field_name)
        if not extracted or extracted.get('status') != 'rejected':
            return {"success": False, "message": "Field is not rejected"}

        # Restore to pending status
        event.extracted_fields[field_name]['status'] = 'pending'
        event.extracted_fields[field_name]['reviewed_by'] = None
        event.extracted_fields[field_name]['reviewed_at'] = None

        # Restore the original AI value to the event field. Normalized
        # contact/org fields are re-linked via the contacts service.
        from apps.contacts.services import NORMALIZED_EVENT_FIELDS, apply_field_to_event
        original_value = extracted.get('value')
        if original_value is not None:
            if field_name in NORMALIZED_EVENT_FIELDS:
                apply_field_to_event(event, field_name, original_value, user)
            elif hasattr(event, field_name):
                setattr(event, field_name, original_value)

        # Ensure review mode is back on
        event.requires_human_review = True
        event.modified_by = user
        event.save()

        # Log the undo
        EventReviewAuditLog.objects.create(
            event=event,
            field_name=field_name,
            action='undo_reject',
            original_value=json.dumps(original_value),
            user=user,
            ip_address=ip_address
        )

        self.logger.info(f"Rejection undone for field {field_name} on event {event.id} by user {user.id}")

        return {
            "success": True,
            "message": f"Rejection undone for {field_name}",
            "fields_remaining": self.get_pending_field_count(event),
            "extracted_fields": event.extracted_fields
        }

    def dismiss_event(self, event: Event, user, ip_address: str = None,
                      junk: bool = False) -> Dict[str, Any]:
        """
        Dismiss an event as a false positive — the source email was not a real
        scheduling request. Clears the review flag without touching extracted
        field values, and records an explicit 'dismissed' decision so the event
        can be surfaced under the inbox's Dismissed filter and later restored.

        Args:
            event: Event instance
            user: User performing the action
            ip_address: Optional IP address for audit

        Returns:
            Dictionary with success status
        """
        from django.utils import timezone
        from apps.event_management.models import EventReviewAuditLog

        if event.review_decision == 'dismissed':
            return {"success": False, "message": "Event is already dismissed"}

        event.requires_human_review = False
        event.review_decision = 'dismissed'
        event.dismissed_at = timezone.now()
        event.dismissed_by = user
        event.modified_by = user
        event.save()

        EventReviewAuditLog.objects.create(
            event=event,
            field_name='',
            action='dismiss',
            user=user,
            ip_address=ip_address
        )

        self.logger.info(f"Event {event.id} dismissed as false positive by user {user.id}")

        result = {
            "success": True,
            "message": "Event dismissed",
            "review_decision": event.review_decision
        }
        if junk:
            # Junk-dismiss counts against the sender and offers blocklisting
            # (ingestion spec §10.7); the actual block is a separate action.
            rep = self._bump_sender_reputation(event, accepted=False, user=user)
            if rep is not None and rep.list != 'block':
                result["offer_block_sender"] = True
                result["sender_email"] = rep.sender_email
        return result

    def undo_dismiss(self, event: Event, user, ip_address: str = None) -> Dict[str, Any]:
        """
        Restore a dismissed event back to the active review queue.

        Args:
            event: Event instance
            user: User performing the action
            ip_address: Optional IP address for audit

        Returns:
            Dictionary with success status
        """
        from apps.event_management.models import EventReviewAuditLog

        if event.review_decision != 'dismissed':
            return {"success": False, "message": "Event is not dismissed"}

        # A dismissed event was always an inbox review candidate, so restoring it
        # returns it to the active review queue.
        event.requires_human_review = True
        event.review_decision = ''
        event.dismissed_at = None
        event.dismissed_by = None
        event.modified_by = user
        event.save()

        EventReviewAuditLog.objects.create(
            event=event,
            field_name='',
            action='undo_dismiss',
            user=user,
            ip_address=ip_address
        )

        self.logger.info(f"Dismissal undone for event {event.id} by user {user.id}")

        return {
            "success": True,
            "message": "Event restored to review queue",
            "review_decision": event.review_decision
        }

    def accept_all_fields(self, event: Event, user, ip_address: str = None) -> Dict[str, Any]:
        """
        Accept all pending fields at once.
        Hidden feature for power users (requires security approval before UI exposure).

        Args:
            event: Event instance
            user: User performing the action
            ip_address: Optional IP address for audit

        Returns:
            Dictionary with success status and accepted fields
        """
        import json
        from django.utils import timezone
        from apps.event_management.models import EventReviewAuditLog

        pending_fields = self.get_pending_fields(event)
        pending_cards = [(kind, card['ref']) for kind, card in self._iter_cards(event)
                         if card.get('status') == 'pending']
        if not pending_fields and not pending_cards:
            return {"success": False, "message": "No pending fields"}

        accepted_fields = []
        now = timezone.now().isoformat()

        for field_name in pending_fields:
            extracted = event.extracted_fields.get(field_name, {})

            # Update status
            event.extracted_fields[field_name]['status'] = 'accepted'
            event.extracted_fields[field_name]['reviewed_by'] = str(user.id)
            event.extracted_fields[field_name]['reviewed_at'] = now

            # Create audit log with special 'accept_all' action
            EventReviewAuditLog.objects.create(
                event=event,
                field_name=field_name,
                action='accept_all',
                original_value=json.dumps(extracted.get('value', '')),
                user=user,
                ip_address=ip_address
            )

            accepted_fields.append(field_name)

        # Accept every pending card AND mark all of its extracted fields reviewed
        # (bulk accept = the reviewer vouching for the whole card at once).
        for kind, ref in pending_cards:
            if kind == 'contacts':
                self.review_contact(event, ref, 'accept', user, ip_address)
            else:
                self.review_organization(event, ref, 'accept', user, ip_address)
            card = self._find_card(event, kind, ref)
            if card is not None:
                card['reviewed_fields'] = self._card_field_keys(card)
            accepted_fields.append(f'{kind}:{ref}')
        event.save()

        # Complete the review
        self._complete_review(event, user)

        self.logger.info(f"All fields accepted for event {event.id} by user {user.id}: {accepted_fields}")

        return {
            "success": True,
            "message": f"Accepted {len(accepted_fields)} fields",
            "fields_accepted": accepted_fields,
            "review_complete": True,
            "extracted_fields": event.extracted_fields
        }

    def get_pending_fields(self, event: Event) -> List[str]:
        """Get list of scalar fields still pending review (excludes contact/org cards)."""
        return [name for name, data in self._scalar_fields(event)
                if data.get('status') == 'pending']

    def get_pending_field_count(self, event: Event) -> int:
        """Count of unreviewed units: scalar fields + each card + each card field."""
        pending = len(self.get_pending_fields(event))
        for _kind, card in self._iter_cards(event):
            total, reviewed = self._card_unit_counts(card)
            pending += (total - reviewed)
        return pending

    def get_total_extracted_count(self, event: Event) -> int:
        """Total reviewable units: scalar fields + each card + each card field."""
        scalar = sum(1 for _ in self._scalar_fields(event))
        cards = sum(self._card_unit_counts(card)[0] for _kind, card in self._iter_cards(event))
        return scalar + cards

    def is_review_complete(self, event: Event) -> bool:
        """Complete when every scalar field, every card, AND every card field is reviewed."""
        if not event.extracted_fields:
            return True
        for _name, data in self._scalar_fields(event):
            if data.get('status') == 'pending':
                return False
        for _kind, card in self._iter_cards(event):
            total, reviewed = self._card_unit_counts(card)
            if reviewed < total:
                return False
        return True

    def _complete_review(self, event: Event, user):
        """Finalize review: commit every accepted card, then clear the review flag.

        Human-in-the-loop policy: NO Contact / Organization / link rows are written
        while review is in progress. Every accepted contact/org card is resolved
        here, in a single pass, only once the WHOLE event (all scalar fields AND all
        cards) has passed review. Rejecting or abandoning a review therefore leaves
        the directory completely untouched.
        """
        self._commit_reviewed_cards(event, user)
        event.requires_human_review = False
        event.modified_by = user
        event.save()

        # Reputation feedback (ingestion spec §10.7): a completed review of an
        # ingestion-created event silently vouches for the sender.
        self._bump_sender_reputation(event, accepted=True, user=user)

        self.logger.info(f"Review completed for event {event.id} by user {user.id}")

    def _bump_sender_reputation(self, event: Event, accepted: bool, user=None):
        """Increment the sender's reputation counters for ingestion-origin
        events. Accept → approve_count++ (silent); junk-dismiss →
        reject_count++ (the caller may offer blocklisting). Never raises —
        reputation is a side signal, not part of the review transaction."""
        try:
            if (event.extracted_fields or {}).get('meta', {}).get('origin') != 'email_ingestion':
                return None
            link = (event.email_links.filter(origin='ai_auto')
                    .select_related('email__raw_message').first())
            raw = link.email.raw_message if link else None
            if raw is None or not raw.sender:
                return None

            from apps.email_processing.models import SenderReputation
            rep = SenderReputation.objects.filter(sender_key=raw.sender_key).first()
            if rep is None:
                rep = SenderReputation(sender_email=raw.sender, list='unknown',
                                       added_by=user)
            if accepted:
                rep.approve_count += 1
            else:
                rep.reject_count += 1
            rep.last_seen = rep.last_seen or event.modified
            rep.save()
            return rep
        except Exception as exc:  # pragma: no cover — never break review flow
            self.logger.warning(f"Reputation bump failed for event {event.id}: {exc}")
            return None

    def _commit_reviewed_cards(self, event, user):
        """Resolve all accepted cards into normalized rows (idempotent, once each).

        Organizations are committed before contacts so a contact's organization
        link reuses the row the org card just created/updated.
        """
        from apps.contacts import services as cs

        ordered = sorted(self._iter_cards(event),
                         key=lambda kc: 0 if kc[0] == 'organizations' else 1)
        for kind, card in ordered:
            if card.get('status') != 'accepted' or card.get('committed'):
                continue
            decision = card.get('decision') or {}
            is_contact = kind == 'contacts'
            party = self._party_from_card(card, decision, is_contact)
            resolution = self._resolution_from_card(card, decision)
            if is_contact:
                obj = cs.resolve_contact(event, party, resolution, user=user)
            else:
                obj = cs.resolve_organization(event, party, resolution, user=user)
            card['committed'] = True
            if obj is not None:
                card['resolved_id'] = str(obj.id)
        # Card mutations live on event.extracted_fields; the caller's save persists them.

    def get_review_status(self, event: Event) -> Dict[str, Any]:
        """
        Get complete review status for an event.

        Args:
            event: Event instance

        Returns:
            Dictionary with full review status information
        """
        fields_status = {}
        accepted_count = 0
        rejected_count = 0
        pending_count = 0

        for field_name, data in self._scalar_fields(event):
            status = data.get('status', 'pending')
            fields_status[field_name] = {
                'status': status,
                'value': data.get('value'),
                'confidence': data.get('confidence'),
                'start_index': data.get('start_index'),
                'end_index': data.get('end_index'),
                'text_snippet': data.get('text_snippet'),
                'reviewed_by': data.get('reviewed_by'),
                'reviewed_at': data.get('reviewed_at')
            }

            if status == 'accepted':
                accepted_count += 1
            elif status == 'rejected':
                rejected_count += 1
            else:
                pending_count += 1

        # Contact/organization cards — the card itself AND each extracted field
        # count toward review completion.
        ef = event.extracted_fields or {}
        for _kind, card in self._iter_cards(event):
            total, reviewed = self._card_unit_counts(card)
            pending_count += (total - reviewed)
            if card.get('status') == 'rejected':
                rejected_count += total
            else:
                accepted_count += reviewed

        return {
            'requires_human_review': event.requires_human_review,
            'total_fields': self.get_total_extracted_count(event),
            'pending_count': pending_count,
            'accepted_count': accepted_count,
            'rejected_count': rejected_count,
            'fields': fields_status,
            'contacts': ef.get('contacts', []),
            'organizations': ef.get('organizations', []),
            'schema_version': ef.get('schema_version'),
            'is_complete': not event.requires_human_review
        }

    # -- Contact / organization card review (multi-contact overhaul) ---------
    #
    # Accepting a card only RECORDS the reviewer's decision on the card; it does
    # not touch the contacts tables. All accepted cards are committed together in
    # _complete_review once the entire event has passed review. The resolution
    # action (new / link / link_update) is derived automatically from the match
    # and the confirmed updates — the reviewer never picks it.

    def _build_decision(self, payload, is_contact):
        """Capture the reviewer's accept decision from the request payload.

        ``additions`` / ``replaces`` are the updates the reviewer explicitly
        confirmed (each is a highlighted item that must be reviewed). additions is
        left as None when the client sends nothing, so the commit step can fall
        back to the card's pre-computed additions (used by accept-all).
        """
        decision = {
            'field_edits': payload.get('field_edits') or {},
            'additions': payload.get('additions'),
            'replaces': [r for r in (payload.get('replaces') or []) if r.get('confirmed')],
        }
        if is_contact:
            decision['role'] = payload.get('role')
            decision['is_primary'] = payload.get('is_primary')
        return decision

    def _party_from_card(self, card, decision, is_contact):
        """Build the party/org dict for resolution from a card + its decision edits."""
        from apps.contacts.constants import EventContactRole
        fields = card.get('fields', {})

        def cell(key):
            return (fields.get(key) or {}).get('value', '')

        edits = decision.get('field_edits') or {}
        keys = (['name', 'email', 'phone', 'position', 'organization']
                if is_contact else ['name', 'location', 'email', 'phone'])
        party = {k: (edits[k] if k in edits else cell(k)) for k in keys}
        if is_contact:
            party['role'] = decision.get('role') or cell('role') or EventContactRole.DEFAULT
        return party

    def _resolution_from_card(self, card, decision):
        """Derive the resolution (action auto-determined) for a card's commit."""
        stored = card.get('resolution') or {}
        matched_id = stored.get('matched_id')
        additions = decision.get('additions')
        if additions is None:
            additions = stored.get('pending_additions') or []
        replaces = decision.get('replaces') or []
        if matched_id:
            action = 'link_update' if (additions or replaces) else 'link'
        else:
            action = 'new'
        return {
            'action': action,
            'matched_id': matched_id,
            'is_primary': decision.get('is_primary'),
            'additions': additions,
            'replaces': replaces,
        }

    def _review_card(self, event, kind, ref, action, user, ip_address, payload):
        """Record accept/reject/undo for a card. Accept does NOT write to the DB."""
        import json
        from django.utils import timezone
        from apps.event_management.models import EventReviewAuditLog

        card = self._find_card(event, kind, ref)
        if card is None:
            return {"success": False, "message": f"No {kind[:-1]} card '{ref}'"}

        audit_action = 'accept'
        if action == 'accept':
            card['status'] = 'accepted'
            card['decision'] = self._build_decision(payload or {}, kind == 'contacts')
        elif action == 'reject':
            card['status'] = 'rejected'
            card.pop('decision', None)
            audit_action = 'reject'
        elif action == 'undo':
            card['status'] = 'pending'
            card.pop('decision', None)
            card.pop('resolved_id', None)
            card['reviewed_fields'] = []   # re-review the fields too
            audit_action = 'undo_reject'
        elif action == 'review_field':
            # Mark one extracted field of the card as individually reviewed.
            field = (payload or {}).get('field')
            if not field:
                return {"success": False, "message": "field is required"}
            reviewed = card.setdefault('reviewed_fields', [])
            if field not in reviewed:
                reviewed.append(field)
            audit_action = 'accept'
        else:
            return {"success": False, "message": "Invalid action"}

        card['reviewed_by'] = str(user.id)
        card['reviewed_at'] = timezone.now().isoformat()
        event.modified_by = user
        event.save()

        audit_name = f'{kind[:-1]}:{ref}'
        if action == 'review_field':
            audit_name += f":{(payload or {}).get('field')}"
        EventReviewAuditLog.objects.create(
            event=event,
            field_name=audit_name,
            action=audit_action,
            original_value=json.dumps((card.get('fields', {}).get('name') or {}).get('value', '')),
            user=user,
            ip_address=ip_address,
        )

        # Commits everything only when this was the final pending item.
        review_complete = self.is_review_complete(event)
        if review_complete:
            self._complete_review(event, user)

        self.logger.info(f"{kind[:-1].title()} card {ref} {action} for event {event.id} by {user.id}")
        return {
            "success": True,
            "message": f"{kind[:-1].title()} {action}",
            "review_complete": review_complete,
            "fields_remaining": self.get_pending_field_count(event),
            "extracted_fields": event.extracted_fields,
        }

    def review_contact(self, event, ref, action, user, ip_address=None, payload=None):
        """Record a decision for one contact card (committed at review completion)."""
        return self._review_card(event, 'contacts', ref, action, user, ip_address, payload)

    def review_organization(self, event, ref, action, user, ip_address=None, payload=None):
        """Record a decision for one organization card (committed at completion)."""
        return self._review_card(event, 'organizations', ref, action, user, ip_address, payload)


class ChangeSuggestionService:
    """
    Service for handling staff change suggestions that require scheduler review.

    When unassigned staff members edit events, their changes are captured as
    suggestions rather than applied directly. This service manages the
    suggestion lifecycle: creation, approval, and rejection.
    """

    # Fields that can be suggested for change
    SUGGESTABLE_FIELDS = [
        'title', 'type', 'format', 'start_date', 'start_time', 'end_date',
        'end_time', 'location', 'group', 'description', 'legislative_topics',
        'participants', 'point_of_contact_name', 'point_of_contact_email',
        'point_of_contact_phone', 'duration', 'expected_attendees', 'notes',
        'tags', 'time_notes', 'reminder_enabled', 'reminder_time'
    ]

    # Fields that staff cannot modify even via suggestion
    RESTRICTED_FIELDS = ['status', 'approval_routing', 'staff']

    def __init__(self):
        self.logger = logging.getLogger('apps.api.suggestions')

    def can_edit_directly(self, event: Event, user) -> bool:
        """
        Check if user can edit this event directly.

        Admin and Scheduler can always edit directly.
        Staff can only edit directly if assigned to the event.

        Args:
            event: Event to check
            user: User attempting to edit

        Returns:
            True if direct edit allowed, False if suggestion required
        """
        from apps.authentication.permissions import Permissions
        return Permissions.can_edit_event(user, event)

    def can_make_suggestion(self, event: Event, user) -> bool:
        """
        Check if user can make suggestions for this event.

        All authenticated users can make suggestions for unassigned events.

        Args:
            event: Event to suggest changes for
            user: User making the suggestion

        Returns:
            True if user can suggest changes
        """
        if not user or not user.is_authenticated:
            return False

        # Staff can always suggest changes for events they're not assigned to
        return True

    def staff_can_remove_self(self, event: Event, user) -> bool:
        """
        Check if staff can remove themselves from event assignment.

        Staff cannot remove themselves from event assignment.
        Only admin/scheduler can modify staff assignments.

        Returns:
            False always - staff cannot remove self
        """
        return False

    def create_suggestion(
        self,
        event: Event,
        field_name: str,
        new_value: Any,
        user,
        reason: str = '',
        ip_address: str = None
    ) -> Dict[str, Any]:
        """
        Create a change suggestion for an event field.

        Args:
            event: Event to suggest change for
            field_name: Name of the field to change
            new_value: Suggested new value
            user: User making the suggestion
            reason: Optional reason for the change
            ip_address: IP address for audit

        Returns:
            Dictionary with success status and suggestion data
        """
        # Validate field name
        if field_name not in self.SUGGESTABLE_FIELDS:
            if field_name in self.RESTRICTED_FIELDS:
                return {
                    'success': False,
                    'message': f"Field '{field_name}' cannot be modified by staff"
                }
            return {
                'success': False,
                'message': f"Invalid field name: {field_name}"
            }

        # Get current value
        current_value = getattr(event, field_name, None)

        # Serialize values for storage
        try:
            current_value_str = json.dumps(current_value) if not isinstance(current_value, str) else current_value
            new_value_str = json.dumps(new_value) if not isinstance(new_value, str) else new_value
        except (TypeError, json.JSONDecodeError):
            current_value_str = str(current_value) if current_value else ''
            new_value_str = str(new_value)

        # Check if suggestion already exists for this field
        existing = EventChangeSuggestion.objects.filter(
            event=event,
            field_name=field_name,
            status='pending'
        ).first()

        if existing:
            # Update existing suggestion
            existing.suggested_value = new_value_str
            existing.reason = reason
            existing.suggested_by = user
            existing.suggested_at = timezone.now()
            existing.ip_address = ip_address
            existing.save()
            suggestion = existing
            is_new = False
        else:
            # Create new suggestion
            suggestion = EventChangeSuggestion.objects.create(
                event=event,
                field_name=field_name,
                current_value=current_value_str,
                suggested_value=new_value_str,
                suggested_by=user,
                reason=reason,
                ip_address=ip_address
            )
            is_new = True

        self.logger.info(
            f"{'Created' if is_new else 'Updated'} suggestion for event {event.id}, "
            f"field {field_name} by user {user.id}"
        )

        return {
            'success': True,
            'message': 'Suggestion created' if is_new else 'Suggestion updated',
            'suggestion': {
                'id': str(suggestion.id),
                'field_name': suggestion.field_name,
                'current_value': suggestion.current_value,
                'suggested_value': suggestion.suggested_value,
                'status': suggestion.status,
                'reason': suggestion.reason,
                'suggested_by': {
                    'id': str(user.id),
                    'name': user.get_display_name()
                },
                'suggested_at': suggestion.suggested_at.isoformat()
            },
            'is_new': is_new
        }

    def approve_suggestion(
        self,
        suggestion_id: str,
        user,
        comment: str = '',
        ip_address: str = None,
        value_override: Any = None,
    ) -> Dict[str, Any]:
        """
        Approve a change suggestion and apply it to the event.

        Args:
            suggestion_id: UUID of the suggestion to approve
            user: User approving (must be admin or scheduler)
            comment: Optional review comment
            ip_address: IP address for audit
            value_override: Optional reviewer-edited value to apply instead of
                the suggested one (the review panel lets the reviewer tweak the
                suggestion before accepting; the original proposal is kept in
                the review comment for audit)

        Returns:
            Dictionary with success status and result
        """
        from apps.authentication.permissions import Permissions

        # Verify user has permission
        if not Permissions.can_approve_suggestions(user):
            return {
                'success': False,
                'message': 'You do not have permission to approve suggestions'
            }

        try:
            suggestion = EventChangeSuggestion.objects.get(id=suggestion_id)
        except EventChangeSuggestion.DoesNotExist:
            return {
                'success': False,
                'message': 'Suggestion not found'
            }

        if suggestion.status != 'pending':
            return {
                'success': False,
                'message': f'Suggestion has already been {suggestion.status}'
            }

        # Reviewer edited the proposed value before accepting: apply the edited
        # value, and preserve the original proposal in the review comment.
        if value_override is not None and str(value_override) != suggestion.suggested_value:
            audit_note = f"edited by reviewer (proposed: {suggestion.suggested_value!r})"
            comment = f"{comment}; {audit_note}" if comment else audit_note
            suggestion.suggested_value = str(value_override)

        # Approve and apply the change
        if suggestion.approve(user, comment, ip_address):
            self.logger.info(
                f"Suggestion {suggestion_id} approved by user {user.id}"
            )

            return {
                'success': True,
                'message': 'Suggestion approved and applied',
                'suggestion': {
                    'id': str(suggestion.id),
                    'field_name': suggestion.field_name,
                    'status': 'approved',
                    'reviewed_by': {
                        'id': str(user.id),
                        'name': user.get_display_name()
                    },
                    'reviewed_at': suggestion.reviewed_at.isoformat()
                }
            }

        return {
            'success': False,
            'message': 'Failed to approve suggestion'
        }

    def reject_suggestion(
        self,
        suggestion_id: str,
        user,
        comment: str = '',
        ip_address: str = None
    ) -> Dict[str, Any]:
        """
        Reject a change suggestion.

        Args:
            suggestion_id: UUID of the suggestion to reject
            user: User rejecting (must be admin or scheduler)
            comment: Optional review comment (required for clarity)
            ip_address: IP address for audit

        Returns:
            Dictionary with success status and result
        """
        from apps.authentication.permissions import Permissions

        # Verify user has permission
        if not Permissions.can_approve_suggestions(user):
            return {
                'success': False,
                'message': 'You do not have permission to reject suggestions'
            }

        try:
            suggestion = EventChangeSuggestion.objects.get(id=suggestion_id)
        except EventChangeSuggestion.DoesNotExist:
            return {
                'success': False,
                'message': 'Suggestion not found'
            }

        if suggestion.status != 'pending':
            return {
                'success': False,
                'message': f'Suggestion has already been {suggestion.status}'
            }

        # Reject the suggestion
        if suggestion.reject(user, comment, ip_address):
            self.logger.info(
                f"Suggestion {suggestion_id} rejected by user {user.id}"
            )

            return {
                'success': True,
                'message': 'Suggestion rejected',
                'suggestion': {
                    'id': str(suggestion.id),
                    'field_name': suggestion.field_name,
                    'status': 'rejected',
                    'review_comment': comment,
                    'reviewed_by': {
                        'id': str(user.id),
                        'name': user.get_display_name()
                    },
                    'reviewed_at': suggestion.reviewed_at.isoformat()
                }
            }

        return {
            'success': False,
            'message': 'Failed to reject suggestion'
        }

    def revert_suggestion(
        self,
        suggestion_id: str,
        user,
        comment: str = '',
        ip_address: str = None
    ) -> Dict[str, Any]:
        """
        Undo a reviewed suggestion and reopen it for a fresh decision.

        - An APPROVED suggestion: the event field is restored to the value it
          had when the suggestion was created (audited via EventChangeHistory),
          and the suggestion returns to 'pending'.
        - A REJECTED suggestion: simply reopened to 'pending'.

        This powers the change-request review panel's "Revert" button.
        """
        from apps.authentication.permissions import Permissions

        if not Permissions.can_approve_suggestions(user):
            return {
                'success': False,
                'message': 'You do not have permission to review suggestions'
            }

        try:
            suggestion = EventChangeSuggestion.objects.get(id=suggestion_id)
        except EventChangeSuggestion.DoesNotExist:
            return {'success': False, 'message': 'Suggestion not found'}

        if suggestion.status == 'pending':
            return {'success': False, 'message': 'Suggestion is not resolved'}

        if suggestion.status == 'approved':
            event = suggestion.event
            field = suggestion.field_name
            if hasattr(event, field):
                applied_value = getattr(event, field, None)
                # Empty string means the field was originally unset — nullable
                # date/time fields must get None back, not ''.
                original = suggestion.current_value
                if original == '' and field in (
                        'start_date', 'start_time', 'end_date', 'end_time'):
                    original = None
                setattr(event, field, original)
                event.modified_by = user
                event.save()
                EventChangeHistory.objects.create(
                    event=event,
                    user=user,
                    field=field,
                    old_value=str(applied_value) if applied_value is not None else '',
                    new_value=suggestion.current_value,
                    ip_address=ip_address,
                )

        suggestion.status = 'pending'
        suggestion.reviewed_by = None
        suggestion.reviewed_at = None
        if comment:
            suggestion.review_comment = comment
        suggestion.save()

        self.logger.info(f"Suggestion {suggestion_id} reverted by user {user.id}")
        return {
            'success': True,
            'message': 'Change reverted; suggestion reopened',
            'suggestion': {
                'id': str(suggestion.id),
                'field_name': suggestion.field_name,
                'status': 'pending',
            }
        }

    def get_pending_suggestions_for_event(self, event: Event) -> List[Dict[str, Any]]:
        """
        Get all pending suggestions for an event.

        Args:
            event: Event to get suggestions for

        Returns:
            List of suggestion dictionaries
        """
        suggestions = EventChangeSuggestion.objects.filter(
            event=event,
            status='pending'
        ).select_related('suggested_by').order_by('-suggested_at')

        return [
            {
                'id': str(s.id),
                'field_name': s.field_name,
                'current_value': s.current_value,
                'suggested_value': s.suggested_value,
                'reason': s.reason,
                'suggested_by': {
                    'id': str(s.suggested_by.id),
                    'name': s.suggested_by.get_display_name()
                },
                'suggested_at': s.suggested_at.isoformat()
            }
            for s in suggestions
        ]

    def get_events_with_pending_suggestions(self, user) -> List[Dict[str, Any]]:
        """
        Get all events that have pending suggestions for review.

        Used for inbox filtering to show events needing scheduler attention.

        Args:
            user: User viewing (for office filtering)

        Returns:
            List of event info dictionaries
        """
        # Get events in user's office with pending suggestions
        office = getattr(user, 'office', None)
        if not office:
            return []

        events_with_suggestions = Event.objects.filter(
            created_by__office=office,
            change_suggestions__status='pending',
            is_archived=False
        ).distinct().select_related('created_by')

        results = []
        for event in events_with_suggestions:
            pending_count = event.change_suggestions.filter(status='pending').count()
            results.append({
                'event_id': str(event.id),
                'title': event.title or event.group,
                'pending_suggestions_count': pending_count,
                'start_date': event.start_date.isoformat() if event.start_date else None
            })

        return results

    def bulk_approve_for_event(
        self,
        event: Event,
        user,
        comment: str = '',
        ip_address: str = None
    ) -> Dict[str, Any]:
        """
        Approve all pending suggestions for an event at once.

        Args:
            event: Event to approve all suggestions for
            user: User approving
            comment: Optional review comment
            ip_address: IP address for audit

        Returns:
            Dictionary with success status and count
        """
        from apps.authentication.permissions import Permissions

        if not Permissions.can_approve_suggestions(user):
            return {
                'success': False,
                'message': 'You do not have permission to approve suggestions'
            }

        pending = EventChangeSuggestion.objects.filter(
            event=event,
            status='pending'
        )

        approved_count = 0
        failed_fields = []

        for suggestion in pending:
            if suggestion.approve(user, comment, ip_address):
                approved_count += 1
            else:
                failed_fields.append(suggestion.field_name)

        self.logger.info(
            f"Bulk approved {approved_count} suggestions for event {event.id}"
        )

        return {
            'success': True,
            'message': f'Approved {approved_count} suggestions',
            'approved_count': approved_count,
            'failed_fields': failed_fields
        }


class ApprovalRoutingService:
    """
    Service for managing event approval routing chains.

    Approval routing allows events to go through a sequence of approvals
    before being finalized. Supports:
    - Sequential stages (one after another)
    - Parallel approvers within a stage (all must approve)
    - Send-back functionality with comments
    - Creator auto-approval (creator is always first approver)
    - Cancel review (creator only, after sent back)

    Approval Routing Structure (stored in Event.approval_routing):
    {
        "version": 1,
        "stages": [
            {
                "stage_id": "stage-creator",
                "order": 0,
                "type": "sequential",
                "approvers": [{"user_id": "uuid", "name": "Creator Name", "required": true}]
            },
            {
                "stage_id": "stage-1",
                "order": 1,
                "type": "parallel",  // all approvers must approve
                "approvers": [
                    {"user_id": "uuid", "name": "Connor", "required": true}
                ],
                "all_required": true
            }
        ]
    }
    """

    def __init__(self):
        self.logger = logging.getLogger('apps.api.approvals')

    def is_first_approver(self, event: Event, user_id: str) -> bool:
        """
        Check if user is in the first stage of the approval chain.
        The first stage is the creator stage (order 0 or lowest order).

        Args:
            event: Event to check
            user_id: User ID to check

        Returns:
            True if user is in the first stage
        """
        routing = event.approval_routing
        if not routing or not routing.get('stages'):
            self.logger.debug(f"is_first_approver: No routing for event {event.id}")
            return False

        stages = sorted(routing['stages'], key=lambda s: s.get('order', 0))
        if not stages:
            self.logger.debug(f"is_first_approver: No stages for event {event.id}")
            return False

        first_stage = stages[0]
        first_stage_approvers = [str(a.get('user_id', '')) for a in first_stage.get('approvers', [])]

        self.logger.info(
            f"is_first_approver check: event={event.id}, user_id={user_id} (type={type(user_id).__name__}), "
            f"first_stage_id={first_stage.get('stage_id')}, "
            f"first_stage_order={first_stage.get('order')}, "
            f"first_stage_approvers={first_stage_approvers}, "
            f"all_stages={[(s.get('stage_id'), s.get('order'), [str(a.get('user_id', '')) for a in s.get('approvers', [])]) for s in stages]}"
        )

        # User is first approver ONLY if they are in the stage with order 0 (creator stage)
        # Not just the first stage in the list
        if first_stage.get('order', 0) != 0:
            self.logger.info(f"is_first_approver: First stage order is {first_stage.get('order')}, not 0 - user is NOT first approver")
            return False

        for approver in first_stage.get('approvers', []):
            approver_user_id = str(approver.get('user_id', ''))
            if approver_user_id == str(user_id):
                self.logger.info(f"is_first_approver: User {user_id} IS first approver (in stage order 0)")
                return True

        self.logger.info(f"is_first_approver: User {user_id} is NOT first approver")
        return False

    def can_edit_routing(self, event: Event, user) -> Dict[str, Any]:
        """
        Check if user can edit routing and get warnings about existing activity.

        Args:
            event: Event to check
            user: User attempting to edit

        Returns:
            Dictionary with can_edit, has_activity, and warning fields
        """
        from apps.authentication.permissions import Permissions

        if not Permissions.can_configure_approvals(user):
            return {
                'can_edit': False,
                'has_activity': False,
                'warning': 'You do not have permission to configure approval routing'
            }

        pending = EventApproval.objects.filter(event=event, status='pending').count()
        approved = EventApproval.objects.filter(event=event, status='approved').count()

        warning = None
        if pending + approved > 0:
            warning = f'Warning: {approved} completed and {pending} pending approvals. Editing will reset progress.'

        return {
            'can_edit': True,
            'has_activity': pending + approved > 0,
            'warning': warning
        }

    def cancel_review(self, event: Event, user, ip_address: str = None) -> Dict[str, Any]:
        """
        Cancel/remove entire approval routing.

        Allowed for:
        - Creator (first approver) when it's their turn (after being sent back)
        - Schedulers (users with can_configure_approvals permission) anytime

        Args:
            event: Event to cancel review for
            user: User attempting to cancel
            ip_address: IP address for audit

        Returns:
            Dictionary with success status and message
        """
        from apps.authentication.permissions import Permissions

        user_id = str(user.id)
        is_scheduler = Permissions.can_configure_approvals(user)
        is_creator = self.is_first_approver(event, user_id)
        can_approve_now = self.can_user_approve(event, user_id)

        # Schedulers can always remove routing
        if is_scheduler:
            pass  # Allowed
        # Creator can cancel when it's their turn
        elif is_creator and can_approve_now:
            pass  # Allowed
        # Creator but not their turn
        elif is_creator:
            return {
                'success': False,
                'message': 'You can only cancel when it is your turn (after being sent back)'
            }
        # Not creator and not scheduler
        else:
            return {
                'success': False,
                'message': 'Only the creator or a scheduler can cancel the review'
            }

        # Delete all EventApproval records
        deleted_count = EventApproval.objects.filter(event=event).delete()[0]

        # Clear routing config
        old_routing = event.approval_routing
        event.approval_routing = {}
        event.modified_by = user
        # Only update the specific fields to avoid overwriting other event data
        event.save(update_fields=['approval_routing', 'modified_by', 'modified'])

        # Log to change history
        EventChangeHistory.objects.create(
            event=event,
            user=user,
            field='approval_routing',
            old_value=json.dumps(old_routing) if old_routing else '',
            new_value='cancelled',
            ip_address=ip_address
        )

        self.logger.info(
            f"Review cancelled for event {event.id} by user {user.id}, "
            f"deleted {deleted_count} approvals"
        )

        return {
            'success': True,
            'message': 'Review cancelled and routing removed'
        }

    def remove_routing(self, event: Event, user, ip_address: str = None) -> Dict[str, Any]:
        """
        Remove approval routing. Scheduler-only operation.

        Unlike cancel_review (which is for creators when it's their turn),
        this allows schedulers to remove routing regardless of state.

        Args:
            event: Event to remove routing from
            user: User attempting to remove (must have configure approval permission)
            ip_address: IP address for audit

        Returns:
            Dictionary with success status and message
        """
        from apps.authentication.permissions import Permissions

        # Verify user has scheduler permission
        if not Permissions.can_configure_approvals(user):
            return {
                'success': False,
                'message': 'Only schedulers can remove routing'
            }

        # Check if routing exists
        if not event.approval_routing or not event.approval_routing.get('stages'):
            return {
                'success': False,
                'message': 'No routing configured for this event'
            }

        # Delete all EventApproval records
        deleted_count = EventApproval.objects.filter(event=event).delete()[0]

        # Clear routing config
        old_routing = event.approval_routing
        event.approval_routing = {}
        event.modified_by = user
        event.save(update_fields=['approval_routing', 'modified_by', 'modified'])

        # Log to change history
        EventChangeHistory.objects.create(
            event=event,
            user=user,
            field='approval_routing',
            old_value=json.dumps(old_routing) if old_routing else '',
            new_value='removed_by_scheduler',
            ip_address=ip_address
        )

        self.logger.info(
            f"Routing removed for event {event.id} by scheduler {user.id}, "
            f"deleted {deleted_count} approvals"
        )

        return {
            'success': True,
            'message': 'Approval routing removed'
        }

    def get_current_stage(self, event: Event) -> Optional[Dict[str, Any]]:
        """
        Get the current active approval stage for an event.

        The current stage is the first stage where not all required
        approvals have been completed.

        Args:
            event: Event to check

        Returns:
            Stage dictionary or None if routing is complete/not configured
        """
        routing = event.approval_routing
        if not routing or not routing.get('stages'):
            return None

        stages = sorted(routing['stages'], key=lambda s: s.get('order', 0))

        for stage in stages:
            stage_id = stage.get('stage_id')
            if not stage_id:
                continue

            # Check if this stage is complete
            if not self._is_stage_complete(event, stage):
                return stage

        return None  # All stages complete

    def get_current_approvers(self, event: Event) -> List[str]:
        """
        Get user IDs of current approvers (those whose turn it is).

        Args:
            event: Event to check

        Returns:
            List of user IDs who need to approve
        """
        current_stage = self.get_current_stage(event)
        if not current_stage:
            return []

        approvers = current_stage.get('approvers', [])
        stage_id = current_stage.get('stage_id')

        # Get pending approvers for this stage
        pending_user_ids = []
        for approver in approvers:
            user_id = approver.get('user_id')
            if not user_id:
                continue

            # Check if this approver has a pending approval
            approval_exists = EventApproval.objects.filter(
                event=event,
                stage_id=stage_id,
                approver_id=user_id,
                status='pending'
            ).exists()

            if approval_exists:
                pending_user_ids.append(user_id)

        return pending_user_ids

    def can_user_approve(self, event: Event, user_id: str) -> bool:
        """
        Check if a user can approve this event right now.

        Args:
            event: Event to check
            user_id: User ID to check

        Returns:
            True if user has a pending approval for the current stage
        """
        current_stage = self.get_current_stage(event)

        self.logger.info(
            f"can_user_approve: event={event.id}, user_id={user_id}, "
            f"current_stage={current_stage}"
        )

        if not current_stage:
            self.logger.info("can_user_approve: No current stage, returning False")
            return False

        stage_id = current_stage.get('stage_id')

        # Debug: List all EventApproval records for this event
        all_approvals = EventApproval.objects.filter(event=event)
        self.logger.info(
            f"can_user_approve: All approvals for event: "
            f"{[(a.stage_id, str(a.approver_id), a.status) for a in all_approvals]}"
        )

        result = EventApproval.objects.filter(
            event=event,
            stage_id=stage_id,
            approver_id=user_id,
            status='pending'
        ).exists()

        self.logger.info(
            f"can_user_approve: Checking stage_id={stage_id}, user_id={user_id}, result={result}"
        )

        return result

    def is_routing_complete(self, event: Event) -> bool:
        """
        Check if all approval stages are complete.

        Args:
            event: Event to check

        Returns:
            True if all required approvals are complete
        """
        return self.get_current_stage(event) is None

    def get_routing_status(self, event: Event, current_user=None) -> Dict[str, Any]:
        """
        Get complete approval routing status for an event.

        Args:
            event: Event to check

        Returns:
            Dictionary with full routing status
        """
        routing = event.approval_routing
        if not routing or not routing.get('stages'):
            return {
                'has_routing': False,
                'is_complete': True,
                'current_stage': None,
                'stages': []
            }

        stages_status = []
        stages = sorted(routing['stages'], key=lambda s: s.get('order', 0))

        for stage in stages:
            stage_id = stage.get('stage_id')
            approvers_status = []

            for approver in stage.get('approvers', []):
                user_id = approver.get('user_id')

                # Get approval record if exists
                approval = EventApproval.objects.filter(
                    event=event,
                    stage_id=stage_id,
                    approver_id=user_id
                ).first()

                # Check if this approver is the current user
                is_current_user = False
                if current_user and user_id:
                    is_current_user = str(current_user.id) == str(user_id)

                # Resolve current display name from User model (not stale JSON)
                display_name = approver.get('name', 'Unknown')
                if user_id:
                    try:
                        approver_user = User.objects.get(id=user_id)
                        display_name = approver_user.get_display_name()
                    except User.DoesNotExist:
                        pass

                approvers_status.append({
                    'user_id': user_id,
                    'name': display_name,
                    'staff_id': approver.get('staff_id'),
                    'required': approver.get('required', True),
                    'status': approval.status if approval else 'not_started',
                    'decided_at': approval.decided_at.isoformat() if approval and approval.decided_at else None,
                    'comment': approval.comment if approval else '',
                    'is_current_user': is_current_user
                })

            stages_status.append({
                'stage_id': stage_id,
                'order': stage.get('order', 0),
                'type': stage.get('type', 'sequential'),
                'is_complete': self._is_stage_complete(event, stage),
                'approvers': approvers_status
            })

        current_stage = self.get_current_stage(event)

        return {
            'has_routing': True,
            'is_complete': current_stage is None,
            'current_stage': current_stage.get('stage_id') if current_stage else None,
            'stages': stages_status
        }

    def approve(
        self,
        event: Event,
        user,
        comment: str = '',
        ip_address: str = None,
        edits: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        Submit an approval decision.

        Args:
            event: Event being approved
            user: User approving
            comment: Optional approval comment
            ip_address: IP address for audit
            edits: List of edits made during approval turn

        Returns:
            Dictionary with success status and result
        """
        # Find the user's pending approval
        current_stage = self.get_current_stage(event)
        if not current_stage:
            return {
                'success': False,
                'message': 'No approval routing configured or already complete'
            }

        stage_id = current_stage.get('stage_id')

        try:
            approval = EventApproval.objects.get(
                event=event,
                stage_id=stage_id,
                approver=user,
                status='pending'
            )
        except EventApproval.DoesNotExist:
            return {
                'success': False,
                'message': 'You do not have a pending approval for this event'
            }

        # Approve
        if approval.approve(comment, ip_address, edits):
            self.logger.info(
                f"Approval submitted for event {event.id} by user {user.id}"
            )

            # After approval, reset any 'sent_back' approvals in the NEXT stage to 'pending'
            # This ensures the person who sent it back can see it again
            current_order = current_stage.get('order', 0)
            routing = event.approval_routing
            stages = routing.get('stages', [])
            for stage in stages:
                if stage.get('order') == current_order + 1:
                    next_stage_id = stage.get('stage_id')
                    reset_count = EventApproval.objects.filter(
                        event=event,
                        stage_id=next_stage_id,
                        status='sent_back'
                    ).update(status='pending', decided_at=None)
                    if reset_count > 0:
                        self.logger.info(
                            f"Reset {reset_count} 'sent_back' approvals to 'pending' in stage {next_stage_id}"
                        )
                    break

            # Check if this completes the routing
            is_complete = self.is_routing_complete(event)

            # Log to change history
            EventChangeHistory.objects.create(
                event=event,
                user=user,
                field='approval_routing',
                old_value='pending',
                new_value='approved',
                ip_address=ip_address
            )

            return {
                'success': True,
                'message': 'Approval submitted',
                'is_routing_complete': is_complete,
                'routing_status': self.get_routing_status(event)
            }

        return {
            'success': False,
            'message': 'Failed to submit approval'
        }

    def send_back(
        self,
        event: Event,
        user,
        comment: str,
        ip_address: str = None
    ) -> Dict[str, Any]:
        """
        Send an event back for revisions.

        When sent back:
        - Parallel stage: resets all approvals in that stage
        - Sequential: resets the previous stage

        Args:
            event: Event to send back
            user: User sending back
            comment: Required explanation (cannot be empty)
            ip_address: IP address for audit

        Returns:
            Dictionary with success status and result
        """
        # Notes are optional when sending back.
        comment = (comment or '').strip()

        current_stage = self.get_current_stage(event)
        if not current_stage:
            return {
                'success': False,
                'message': 'No approval routing configured or already complete'
            }

        stage_id = current_stage.get('stage_id')

        try:
            approval = EventApproval.objects.get(
                event=event,
                stage_id=stage_id,
                approver=user,
                status='pending'
            )
        except EventApproval.DoesNotExist:
            return {
                'success': False,
                'message': 'You do not have a pending approval for this event'
            }

        # Send back
        if approval.send_back(comment, ip_address):
            # Reset other approvals in this stage (for parallel type)
            if current_stage.get('type') == 'parallel':
                EventApproval.objects.filter(
                    event=event,
                    stage_id=stage_id,
                    status='approved'
                ).update(status='pending', decided_at=None, comment='')

            # For SEQUENTIAL stages, reset the PREVIOUS stage to pending
            # This allows the previous approver to see it again and re-approve
            self.logger.info(
                f"send_back: stage_type={current_stage.get('type')}, current_order={current_stage.get('order', 0)}"
            )
            if current_stage.get('type') != 'parallel':
                current_order = current_stage.get('order', 0)
                if current_order > 0:  # There is a previous stage
                    routing = event.approval_routing
                    stages = routing.get('stages', [])
                    self.logger.info(f"send_back: Looking for stage with order {current_order - 1}")
                    for stage in stages:
                        if stage.get('order') == current_order - 1:
                            previous_stage_id = stage.get('stage_id')
                            self.logger.info(f"send_back: Found previous stage {previous_stage_id}, resetting...")
                            reset_count = EventApproval.objects.filter(
                                event=event,
                                stage_id=previous_stage_id,
                                status='approved'
                            ).update(status='pending', decided_at=None, comment='')
                            self.logger.info(
                                f"send_back: Reset {reset_count} approvals in previous stage {previous_stage_id}"
                            )
                            break
                else:
                    self.logger.info("send_back: current_order is 0, no previous stage to reset")

            self.logger.info(
                f"Event {event.id} sent back by user {user.id}: {comment}"
            )

            # Log to change history
            EventChangeHistory.objects.create(
                event=event,
                user=user,
                field='approval_routing',
                old_value='pending',
                new_value='sent_back',
                ip_address=ip_address
            )

            return {
                'success': True,
                'message': 'Event sent back for revisions',
                'routing_status': self.get_routing_status(event)
            }

        return {
            'success': False,
            'message': 'Failed to send back'
        }

    def initialize_approvals(self, event: Event) -> Dict[str, Any]:
        """
        Initialize EventApproval records for an event's routing configuration.

        Should be called when approval routing is first configured or reset.

        Args:
            event: Event to initialize approvals for

        Returns:
            Dictionary with success status and created count
        """
        routing = event.approval_routing
        if not routing or not routing.get('stages'):
            return {
                'success': False,
                'message': 'No approval routing configured'
            }

        # Clear any existing approvals
        EventApproval.objects.filter(event=event).delete()

        created_count = 0
        stages = routing.get('stages', [])

        for stage in stages:
            stage_id = stage.get('stage_id')
            stage_order = stage.get('order', 0)

            for approver in stage.get('approvers', []):
                user_id = approver.get('user_id')
                staff_id = approver.get('staff_id')  # OfficeStaff ID
                approver_name = approver.get('name')
                user = None

                # 1. Try to find user by ID first
                if user_id:
                    try:
                        user = User.objects.get(id=user_id)
                    except User.DoesNotExist:
                        self.logger.warning(
                            f"User {user_id} not found when initializing approvals"
                        )

                # 2. Try to find user by staff_id (OfficeStaff profile link)
                if not user and staff_id:
                    try:
                        user = User.objects.get(staff_profile_id=staff_id)
                        approver['user_id'] = str(user.id)
                        self.logger.info(
                            f"Resolved approver '{approver_name}' via staff_profile to user {user.id}"
                        )
                    except User.DoesNotExist:
                        self.logger.warning(
                            f"No user found with staff_profile_id={staff_id}"
                        )

                # 3. Fall back to name-based resolution
                if not user and approver_name:
                    # Try to match by full name or username
                    user = User.objects.filter(
                        models.Q(first_name__iexact=approver_name.split()[0] if ' ' in approver_name else approver_name) |
                        models.Q(username__iexact=approver_name)
                    ).first()

                    # Also try matching full name
                    if not user:
                        name_parts = approver_name.split()
                        if len(name_parts) >= 2:
                            user = User.objects.filter(
                                first_name__iexact=name_parts[0],
                                last_name__iexact=name_parts[-1]
                            ).first()

                    if user:
                        # Update the approver dict with resolved user_id
                        approver['user_id'] = str(user.id)
                        self.logger.info(
                            f"Resolved approver '{approver_name}' by name to user {user.id}"
                        )

                if not user:
                    self.logger.warning(
                        f"Could not resolve approver: user_id={user_id}, staff_id={staff_id}, name={approver_name}"
                    )
                    continue

                # Keep display name in sync with the resolved user
                current_name = user.get_display_name()
                if current_name and current_name != approver.get('name'):
                    approver['name'] = current_name

                try:
                    EventApproval.objects.create(
                        event=event,
                        stage_id=stage_id,
                        stage_order=stage_order,
                        approver=user,
                        status='pending'
                    )
                    created_count += 1
                except Exception as e:
                    self.logger.error(
                        f"Failed to create approval for user {user.id}: {e}"
                    )

        # Persist any name updates back to the event's routing JSON
        event.approval_routing = routing
        event.save(update_fields=['approval_routing'])

        self.logger.info(
            f"Initialized {created_count} approvals for event {event.id}"
        )

        return {
            'success': True,
            'message': f'Initialized {created_count} approvals',
            'created_count': created_count
        }

    def update_routing_config(
        self,
        event: Event,
        routing_config: Dict[str, Any],
        user,
        ip_address: str = None
    ) -> Dict[str, Any]:
        """
        Update an event's approval routing configuration.

        Args:
            event: Event to update
            routing_config: New routing configuration
            user: User making the change
            ip_address: IP address for audit

        Returns:
            Dictionary with success status
        """
        from apps.authentication.permissions import Permissions

        self.logger.info(
            f"update_routing_config called: event={event.id}, user={user.id}, "
            f"user_role={getattr(user, 'role', None)}, "
            f"routing_config={json.dumps(routing_config)}"
        )

        if not Permissions.can_configure_approvals(user):
            self.logger.warning(
                f"User {user.id} (role={getattr(user, 'role', None)}) "
                f"does not have permission to configure approvals"
            )
            return {
                'success': False,
                'message': f'You do not have permission to configure approval routing. Your role: {getattr(user, "role", "none")}'
            }

        # Validate routing config
        if not isinstance(routing_config, dict):
            return {
                'success': False,
                'message': 'Invalid routing configuration'
            }

        # Ensure version is set
        routing_config.setdefault('version', 1)

        # Prepend creator as Stage 0 (auto-approved on save)
        # The creator is always the first approver
        stages = routing_config.get('stages', [])

        # Check if creator stage already exists
        has_creator_stage = any(
            stage.get('stage_id') == 'stage-creator' for stage in stages
        )

        if not has_creator_stage:
            creator_stage = {
                'stage_id': 'stage-creator',
                'order': 0,
                'type': 'sequential',
                'approvers': [{
                    'user_id': str(user.id),
                    'name': user.get_display_name(),
                    'required': True
                }],
                'all_required': True
            }

            # Renumber existing stages starting from 1
            for i, stage in enumerate(stages):
                stage['order'] = i + 1

            # Prepend creator stage
            routing_config['stages'] = [creator_stage] + stages

        # Store old config for audit
        old_config = event.approval_routing

        # Update event with routing config
        event.approval_routing = routing_config
        event.modified_by = user

        self.logger.info(
            f"BEFORE first save - event.approval_routing: {json.dumps(event.approval_routing)}"
        )

        # Only update the specific fields to avoid overwriting other event data
        event.save(update_fields=['approval_routing', 'modified_by', 'modified'])

        self.logger.info(
            f"AFTER first save - event.approval_routing: {json.dumps(event.approval_routing)}"
        )

        # Initialize approval records (this also resolves user_ids from names)
        init_result = self.initialize_approvals(event)

        self.logger.info(
            f"AFTER initialize_approvals - event.approval_routing: {json.dumps(event.approval_routing)}"
        )

        # Auto-approve creator's stage (stage-creator)
        # This makes saving the routing = their approval
        creator_approval = EventApproval.objects.filter(
            event=event,
            stage_id='stage-creator',
            approver=user
        ).first()

        if creator_approval:
            creator_approval.status = 'approved'
            creator_approval.decided_at = timezone.now()
            creator_approval.comment = 'Auto-approved on routing creation'
            creator_approval.save()
            self.logger.info(
                f"Auto-approved creator stage for event {event.id}, user {user.id}"
            )

        # Save again to persist any resolved user_ids in approval_routing
        event.save(update_fields=['approval_routing', 'modified'])

        self.logger.info(
            f"AFTER second save - event.approval_routing: {json.dumps(event.approval_routing)}"
        )

        # Verify from DB
        event.refresh_from_db()
        self.logger.info(
            f"AFTER refresh_from_db - event.approval_routing: {json.dumps(event.approval_routing)}"
        )

        # Log change
        EventChangeHistory.objects.create(
            event=event,
            user=user,
            field='approval_routing',
            old_value=json.dumps(old_config) if old_config else '',
            new_value=json.dumps(event.approval_routing),  # Use current value
            ip_address=ip_address
        )

        self.logger.info(
            f"Approval routing updated for event {event.id} by user {user.id}"
        )

        return {
            'success': True,
            'message': 'Approval routing updated',
            'approvals_created': init_result.get('created_count', 0),
            'routing_status': self.get_routing_status(event)
        }

    def get_events_needing_user_approval(self, user, include_resolved=True) -> List[Dict[str, Any]]:
        """
        Get all events that need the user's approval, plus recently resolved items.

        Args:
            user: User to check approvals for
            include_resolved: Whether to include resolved (approved/sent_back) items

        Returns:
            List of event info dictionaries (deduplicated by event ID)
        """

        # Get pending approvals
        pending_approvals = EventApproval.objects.filter(
            approver=user,
            status='pending',
            event__is_archived=False
        ).select_related('event')

        # Get resolved approvals (approved or sent_back by this user)
        resolved_approvals = []
        if include_resolved:
            resolved_approvals = EventApproval.objects.filter(
                approver=user,
                status__in=['approved', 'sent_back'],
                event__is_archived=False
            ).select_related('event').order_by('-decided_at')[:50]  # Limit to recent 50

        results = []
        seen_event_ids = set()  # Track event IDs to prevent duplicates

        for approval in pending_approvals:
            event = approval.event
            event_id_str = str(event.id)

            # Skip if we've already added this event
            if event_id_str in seen_event_ids:
                continue

            # Only include if this is the current stage
            if self.can_user_approve(event, str(user.id)):
                seen_event_ids.add(event_id_str)

                # Get the previous approver's name (who sent this for review)
                sent_by_name = ''
                current_stage_order = approval.stage_order or 0
                if current_stage_order > 0:
                    # Find the previous stage's approver who approved
                    prev_approval = EventApproval.objects.filter(
                        event=event,
                        stage_order=current_stage_order - 1,
                        status='approved'
                    ).select_related('approver').first()
                    if prev_approval and prev_approval.approver:
                        sent_by_name = prev_approval.approver.get_display_name()
                else:
                    # Stage 0 - check for creator in routing
                    routing = event.approval_routing or {}
                    stages = routing.get('stages', [])
                    for stage in stages:
                        if stage.get('order') == 0:
                            approvers = stage.get('approvers', [])
                            if approvers:
                                sent_by_name = approvers[0].get('name', '')
                            break

                # Current user's name
                current_user_name = user.get_display_name()

                # Get the next approver's name (who will review after current user)
                next_approver_name = ''
                is_final_approver = True
                routing = event.approval_routing or {}
                stages = sorted(routing.get('stages', []), key=lambda s: s.get('order', 0))
                for stage in stages:
                    if stage.get('order', 0) == current_stage_order + 1:
                        # Found the next stage
                        is_final_approver = False
                        approvers = stage.get('approvers', [])
                        if approvers:
                            next_approver_name = approvers[0].get('name', '')
                        break

                # Check if this is a re-review (event was sent back to the user)
                # This happens when someone in a later stage sent it back
                # We detect this by checking if there's a 'sent_back' approval from a later stage
                sent_back_approval = EventApproval.objects.filter(
                    event=event,
                    status='sent_back',
                    stage_order__gt=current_stage_order
                ).select_related('approver').first()
                is_re_review = sent_back_approval is not None
                sent_back_by_name = ''
                if sent_back_approval and sent_back_approval.approver:
                    sent_back_by_name = sent_back_approval.approver.get_display_name()

                # Return full event data for inbox display (matching EventSerializer fields)
                results.append({
                    'id': event_id_str,
                    'event_id': event_id_str,  # Keep for backwards compat
                    'title': event.title or '',
                    'group': event.group or '',
                    'organization': event.group or '',  # Add organization field
                    'type': event.type or '',
                    'format': event.format or '',
                    'duration': event.duration or '',
                    'status': event.status or '',
                    'description': event.description or '',
                    'location': event.location or '',
                    'start_date': event.start_date.isoformat() if event.start_date else None,
                    'start_time': event.start_time.isoformat() if event.start_time else None,
                    'end_date': event.end_date.isoformat() if event.end_date else None,
                    'end_time': event.end_time.isoformat() if event.end_time else None,
                    'timezone': event.timezone or '',
                    'time_notes': event.time_notes or '',
                    'is_date_range': event.is_date_range,
                    'is_longer_than_day': event.is_longer_than_day,
                    # Use approval.created_at (when review was requested) for inbox sorting
                    'created': approval.created_at.isoformat() if approval.created_at else None,
                    'tags': event.tags or [],
                    'staff': event.staff or [],
                    'notes': event.notes or '',
                    'point_of_contact_name': event.point_of_contact_name or '',
                    'point_of_contact_email': event.point_of_contact_email or '',
                    'point_of_contact_phone': event.point_of_contact_phone or '',
                    'requires_human_review': event.requires_human_review,
                    # Approval-specific fields
                    'stage_id': approval.stage_id,
                    'stage_order': approval.stage_order,
                    'needs_approval': True,  # Flag to indicate this is an approval item
                    'sent_by_name': sent_by_name,
                    'current_approver_name': current_user_name,
                    'next_approver_name': next_approver_name,
                    'is_final_approver': is_final_approver,
                    'user_approval_status': 'pending',  # User's action status
                    'is_resolved': False,
                    'is_re_review': is_re_review,  # True if event was sent back to user
                    'sent_back_by_name': sent_back_by_name  # Name of who sent it back (for re-review)
                })

        # Process resolved approvals (past items)
        for approval in resolved_approvals:
            event = approval.event
            event_id_str = str(event.id)

            # Skip if we've already added this event (pending takes priority)
            if event_id_str in seen_event_ids:
                continue

            seen_event_ids.add(event_id_str)

            # Get previous/next approver names from routing config
            sent_by_name = ''
            sent_back_to_name = ''
            next_approver_name = ''
            is_final_approver = True
            current_stage_order = approval.stage_order or 0
            routing = event.approval_routing or {}
            stages = sorted(routing.get('stages', []), key=lambda s: s.get('order', 0))

            for stage in stages:
                stage_order = stage.get('order', 0)
                approvers = stage.get('approvers', [])
                if stage_order == current_stage_order - 1 and approvers:
                    # Previous stage - who sent it to us OR who we sent back to
                    sent_by_name = approvers[0].get('name', '')
                    sent_back_to_name = approvers[0].get('name', '')
                elif stage_order == current_stage_order + 1 and approvers:
                    # Next stage - who would review after us
                    is_final_approver = False
                    next_approver_name = approvers[0].get('name', '')

            # Current user's name
            current_user_name = user.get_display_name()

            results.append({
                'id': event_id_str,
                'event_id': event_id_str,
                'title': event.title or '',
                'group': event.group or '',
                'organization': event.group or '',
                'type': event.type or '',
                'format': event.format or '',
                'duration': event.duration or '',
                'status': event.status or '',
                'description': event.description or '',
                'location': event.location or '',
                'start_date': event.start_date.isoformat() if event.start_date else None,
                'start_time': event.start_time.isoformat() if event.start_time else None,
                'end_date': event.end_date.isoformat() if event.end_date else None,
                'end_time': event.end_time.isoformat() if event.end_time else None,
                'timezone': event.timezone or '',
                'time_notes': event.time_notes or '',
                'is_date_range': event.is_date_range,
                'is_longer_than_day': event.is_longer_than_day,
                'created': approval.decided_at.isoformat() if approval.decided_at else (
                    approval.created_at.isoformat() if approval.created_at else None
                ),
                'tags': event.tags or [],
                'staff': event.staff or [],
                'notes': event.notes or '',
                'point_of_contact_name': event.point_of_contact_name or '',
                'point_of_contact_email': event.point_of_contact_email or '',
                'point_of_contact_phone': event.point_of_contact_phone or '',
                'requires_human_review': event.requires_human_review,
                'stage_id': approval.stage_id,
                'stage_order': approval.stage_order,
                'needs_approval': False,  # Already resolved
                'sent_by_name': sent_by_name,
                'sent_back_to_name': sent_back_to_name,  # For sent_back events: who you sent it back to
                'current_approver_name': current_user_name,
                'next_approver_name': next_approver_name,
                'is_final_approver': is_final_approver,
                'user_approval_status': approval.status,  # 'approved' or 'sent_back'
                'is_resolved': True
            })

        return results

    def _is_stage_complete(self, event: Event, stage: Dict) -> bool:
        """
        Check if a stage is complete (all required approvals submitted).

        Args:
            event: Event to check
            stage: Stage configuration dictionary

        Returns:
            True if stage is complete
        """
        stage_id = stage.get('stage_id')
        approvers = stage.get('approvers', [])
        all_required = stage.get('all_required', True)

        if not approvers:
            return True

        approved_count = 0
        required_count = 0

        for approver in approvers:
            user_id = approver.get('user_id')
            is_required = approver.get('required', True)

            if is_required:
                required_count += 1

            approval = EventApproval.objects.filter(
                event=event,
                stage_id=stage_id,
                approver_id=user_id,
                status='approved'
            ).first()

            if approval:
                approved_count += 1

        if all_required:
            return approved_count >= required_count
        else:
            # At least one approval is enough
            return approved_count > 0