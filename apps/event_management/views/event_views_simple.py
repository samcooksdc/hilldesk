# SPDX-License-Identifier: Apache-2.0
"""
Simple event views for HillDesk.
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required

from ..models import Event
from apps.event_management.utils.json_embed import script_safe_json


@login_required
def event_editing_interface(request, event_id):
    """
    Main view for the event editing interface.
    Renders the split-panel interface for editing events.
    """

    try:
        # Same visibility rule as the events API (archived events included so
        # Settings -> Deleted events can still open them).
        from apps.authentication.permissions import Permissions
        event = get_object_or_404(
            Permissions.scope_events_queryset(request.user, Event.objects.all()), id=event_id
        )

        # Related emails are the union of attached threads + direct links (the
        # link tables are the source of truth). Flat list newest-first, plus a
        # grouped view (by conversation thread) for the redesigned email panel.
        related_emails = []
        email_groups = {'threads': [], 'standalone': []}
        try:
            related_emails = event.get_attached_emails().order_by('-received')
            email_groups = event.get_email_groups()

            # Annotate each email with the OTHER events it is on, for a
            # shared-email badge. Bounded to the few emails shown in the modal.
            def _other_event_titles(email):
                return [e.title for e in event.other_events_for_email(email)]

            for _group in email_groups['threads']:
                for _msg in _group['emails']:
                    _msg.also_on_titles = _other_event_titles(_msg)
            for _msg in email_groups['standalone']:
                _msg.also_on_titles = _other_event_titles(_msg)
        except Exception as e:
            print(f"Error building related emails: {e}")

        # Serialize extracted_fields for JavaScript (review mode)
        extracted_fields_json = '{}'
        if event.extracted_fields:
            try:
                extracted_fields_json = script_safe_json(event.extracted_fields)
            except (TypeError, ValueError):
                pass

        # Email-ingestion change requests (reviewed inside this modal by the
        # EventChangeReview module, same surface as the extraction review):
        # pending suggestions, plus resolved siblings of a candidate that still
        # has a pending row, so mixed state renders with Undo.
        change_suggestions_json = '[]'
        try:
            from django.db.models import Q

            from ..models import EventChangeSuggestion

            pending = EventChangeSuggestion.objects.filter(
                event=event, origin='email_ingestion', status='pending')
            candidate_ids = [c for c in pending.values_list('source_candidate_id', flat=True) if c]
            rows = (EventChangeSuggestion.objects
                    .filter(Q(pk__in=pending.values('pk'))
                            | Q(event=event, origin='email_ingestion',
                                source_candidate_id__in=candidate_ids))
                    .select_related('source_candidate')
                    .order_by('suggested_at'))
            payload = []
            for s in rows:
                candidate = s.source_candidate
                payload.append({
                    'id': str(s.id),
                    'field_name': s.field_name,
                    'current_value': s.current_value,
                    'suggested_value': s.suggested_value,
                    'status': s.status,
                    'reason': s.reason,
                    'intent': candidate.intent if candidate else (
                        'CANCELLATION' if s.field_name == 'status' else 'RESCHEDULE'),
                    'verbatim': ((candidate.payload or {}).get('verbatim') or {}) if candidate else {},
                })
            change_suggestions_json = script_safe_json(payload)
        except Exception as e:
            print(f"Error building change suggestions: {e}")

        context = {
            'event': event,
            'related_emails': related_emails,
            'email_groups': email_groups,
            'change_history': [],
            'email_templates': [],
            'extracted_fields_json': extracted_fields_json,
            'change_suggestions_json': change_suggestions_json,
        }

        return render(request, 'event_management/event_editing_interface.html', context)
        
    except Exception as e:
        print(f"Error in event_editing_interface: {e}")
        import traceback
        traceback.print_exc()
        raise