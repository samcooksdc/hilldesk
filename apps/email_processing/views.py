# SPDX-License-Identifier: Apache-2.0
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.urls import reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q

from .models import EmailProcessing, EmailResponse, FilterLog, RawMessage
from apps.event_management.models import Event, EmailTemplate
from apps.contacts.services import link_extraction_to_event
from apps.contacts.crypto import email_blind_index
from apps.authentication.permissions import Permissions

# NOTE (email ingestion migration): the legacy verification views
# (email_verification_list, verify_email, reject_email, reprocess_email,
# verification_dashboard, update_field_confidence) were retired in Phase 5 —
# the inbox is the review surface and the triage list (below) replaces the
# escalation queue. See docs/EMAIL_INGESTION_BUILD_PLAN.md.


@login_required
def inbox_view(request):
    """
    Display inbox view with non-reviewed entries, email preview, and verification interface.
    """
    # Get search and filter parameters
    search_query = request.GET.get('search', '').strip()
    confidence_filter = request.GET.get('confidence', '')
    status_filter = request.GET.get('status', '')
    
    # Base queryset - emails that need review
    emails = EmailProcessing.objects.filter(
        is_scheduling_request=True,
        status__in=['pending', 'processed']
    )
    
    # Apply search filter
    if search_query:
        emails = emails.filter(
            Q(subject__icontains=search_query) |
            Q(sender__icontains=search_query) |
            Q(sender_name__icontains=search_query) |
            Q(extracted_data__group__icontains=search_query) |
            Q(extracted_data__details__icontains=search_query)
        )
    
    # Apply confidence filter
    if confidence_filter:
        if confidence_filter == 'high':
            emails = emails.filter(confidence__gte=0.8)
        elif confidence_filter == 'medium':
            emails = emails.filter(confidence__gte=0.5, confidence__lt=0.8)
        elif confidence_filter == 'low':
            emails = emails.filter(confidence__lt=0.5)
    
    # Apply status filter
    if status_filter:
        emails = emails.filter(status=status_filter)
    
    # Order by received date (newest first)
    emails = emails.order_by('-received')
    
    # Get statistics
    total_pending = EmailProcessing.objects.filter(
        is_scheduling_request=True,
        status__in=['pending', 'processed']
    ).count()
    
    high_confidence = EmailProcessing.objects.filter(
        is_scheduling_request=True,
        status__in=['pending', 'processed'],
        confidence__gte=0.8
    ).count()
    
    # Pagination
    paginator = Paginator(emails, 20)  # Show 20 emails per page
    page_number = request.GET.get('page')
    emails_page = paginator.get_page(page_number)

    context = {
        'emails': emails_page,
        'search_query': search_query,
        'confidence_filter': confidence_filter,
        'status_filter': status_filter,
        'total_pending': total_pending,
        'high_confidence': high_confidence,
        'page_title': 'Inbox',
    }

    return render(request, 'email_processing/inbox.html', context)


@login_required
def email_preview(request, email_id):
    """
    Display email preview with extracted information.
    """
    email_processing = get_object_or_404(EmailProcessing, id=email_id)
    
    # Get extracted data with confidence levels
    extracted_data = email_processing.extracted_data or {}
    confidence_levels = extracted_data.get('confidence_levels', {})
    
    # Calculate field confidence levels
    field_confidences = {}
    for field in ['type', 'start_date', 'end_date', 'location', 'group', 'details']:
        field_confidences[field] = confidence_levels.get(field, email_processing.confidence)
    
    context = {
        'email': email_processing,
        'extracted_data': extracted_data,
        'field_confidences': field_confidences,
    }
    
    return render(request, 'email_processing/email_preview.html', context)


@login_required
def email_response_interface(request, email_id):
    """
    Display interface for responding to emails with template selection.
    """
    email_processing = get_object_or_404(EmailProcessing, id=email_id)
    
    # Get available email templates
    templates = EmailTemplate.objects.all().order_by('name')
    
    # Handle POST request (send response)
    if request.method == 'POST':
        template_id = request.POST.get('template_id')
        custom_subject = request.POST.get('subject', '')
        custom_body = request.POST.get('body', '')
        
        # Create email response record
        response = EmailResponse.objects.create(
            original_email=email_processing,
            template_used_id=template_id if template_id else None,
            subject=custom_subject,
            body=custom_body,
            sender=request.user.email,
            recipient=email_processing.sender,
            created_by=request.user,
            status='pending'
        )
        
        # TODO: Integrate with email sending service
        # For now, mark as sent
        response.status = 'sent'
        response.sent_at = timezone.now()
        response.save()
        
        messages.success(request, 'Response sent successfully!')
        return redirect('email_processing:inbox')
    
    # Get extracted data for template variables
    extracted_data = email_processing.extracted_data or {}
    
    context = {
        'email': email_processing,
        'templates': templates,
        'extracted_data': extracted_data,
    }
    
    return render(request, 'email_processing/email_response.html', context)


@login_required
@require_POST
def bulk_actions(request):
    """
    Handle bulk actions on selected emails.
    """
    action = request.POST.get('action')
    selected_emails = request.POST.getlist('selected_emails')
    
    if not selected_emails:
        messages.error(request, 'No emails selected.')
        return redirect('email_processing:inbox')
    
    emails = EmailProcessing.objects.filter(id__in=selected_emails)
    
    if action == 'bulk_approve':
        # Bulk approve emails (create events)
        approved_count = 0
        for email in emails:
            if email.confidence >= 0.8:  # Only approve high confidence emails
                # Create event from extracted data
                extracted_data = email.extracted_data or {}
                
                # Create event. Contact/org normalized via link_extraction_to_event below.
                event = Event.objects.create(
                    type=extracted_data.get('type', 'meeting'),
                    start_date=extracted_data.get('start_date'),
                    end_date=extracted_data.get('end_date'),
                    time=extracted_data.get('time', ''),
                    location=extracted_data.get('location', ''),
                    details=extracted_data.get('details', ''),
                    status='received',
                    created_by=request.user
                )
                
                # Update email status
                email.status = 'verified'
                email.processed_by = request.user
                email.event = event
                email.save()

                # Normalize extracted contact/org into Contact/Organization
                # models and link to the event (dual-write with legacy fields).
                link_extraction_to_event(event, extracted_data, request.user)

                approved_count += 1
        
        messages.success(request, f'{approved_count} emails approved and events created.')
    
    elif action == 'bulk_reject':
        # Bulk reject emails
        emails.update(
            status='rejected',
            processed_by=request.user
        )
        messages.success(request, f'{len(selected_emails)} emails rejected.')
    
    elif action == 'bulk_assign':
        # TODO: Implement bulk assignment functionality
        messages.info(request, 'Bulk assignment functionality coming soon.')
    
    return redirect('email_processing:inbox')

# =============================================================================
# Divert-store browse (email ingestion pipeline)
# =============================================================================

def divert_reason(stage, signals):
    """Plain-language (label, explanation) for why the funnel diverted a message."""
    signals = signals or {}
    if signals.get('reason') == 'triage_divert':
        return ('Diverted by a staffer',
                'Someone in the office reviewed this email in the inbox and set it aside.')
    if signals.get('bulk_headers'):
        return ('Bulk or list mail',
                'It carried mailing-list or bulk-mail headers ('
                + ', '.join(signals['bulk_headers']) + '), the mark of newsletters and mass mail.')
    if signals.get('automated_sender'):
        return ('Automated sender',
                f"It came from an automated address ({signals['automated_sender']}@...), "
                'such as a no-reply or notification account.')
    if signals.get('reputation') == 'block':
        return ('Blocked sender', 'The sender is on the office block list.')
    if signals.get('duplicate_of'):
        return ('Duplicate', 'HillDesk already received this same message.')
    if stage == '0_scope':
        return ('Outside the scheduling mailboxes',
                'It was not addressed to a mailbox HillDesk reads for scheduling.')
    if stage == '4_content':
        return ('No scheduling request found',
                'It had no dates, times or meeting language that suggest a scheduling request.')
    return ('Filtered out', 'HillDesk filtered this message before reading it for scheduling details.')


def _diverted_queryset(query=''):
    """Messages whose pipeline ended in divert and that were never promoted.

    The divert store is a query over RawMessage + FilterLog, not a table: a
    promoted message gains extract/escalate log rows and drops out.
    """
    qs = (
        RawMessage.objects
        .filter(filter_logs__outcome='divert')
        .exclude(filter_logs__outcome__in=['extract', 'escalate'])
        .distinct()
        .prefetch_related('filter_logs')
        .order_by('-received_at')
    )
    query = (query or '').strip()
    if query:
        if '@' in query:
            # Sender is encrypted; exact-match search goes through the blind index.
            qs = qs.filter(sender_key=email_blind_index(query))
        else:
            qs = qs.filter(subject__icontains=query)
    return qs


@login_required
def diverted_items_api(request):
    """JSON feed for the inbox's "Diverted" tab (spec §10.6).

    Guarantees the office can always find a message it received, even one the
    funnel filtered out. ?search= narrows by subject (or exact sender address).
    """
    _require_inbox(request.user)
    qs = _diverted_queryset(request.GET.get('search', ''))
    total = qs.count()
    results = []
    for raw in qs[:300]:
        divert_log = next(
            (log for log in reversed(list(raw.filter_logs.all())) if log.outcome == 'divert'),
            None,
        )
        label, explanation = divert_reason(
            divert_log.stage if divert_log else '', divert_log.signals if divert_log else {}
        )
        results.append({
            'id': str(raw.id),
            'reason_label': label,
            'explanation': explanation,
            'subject': raw.subject or '',
            'sender': raw.sender or '',
            'sender_name': raw.sender_name or '',
            'received_at': raw.received_at.isoformat() if raw.received_at else None,
            'body_text': (raw.body_text or '')[:20000],
        })
    return JsonResponse({'count': total, 'results': results})


@login_required
def divert_store(request):
    """Old standalone page: diverted mail now lives in the inbox's Diverted tab."""
    return redirect(reverse('event_management:inbox') + '?view=diverted')


@login_required
@require_POST
def promote_diverted(request, raw_message_id):
    """Promote a diverted message into extraction (force past the funnel)."""
    from .tasks.pipeline import run_pipeline

    _require_inbox(request.user)
    raw = get_object_or_404(RawMessage, pk=raw_message_id)
    run_pipeline.delay(str(raw.id), force_extract=True)
    if _wants_json(request):
        return JsonResponse({'success': True, 'action': 'promote'})
    messages.success(
        request,
        f'"{raw.subject[:60]}" was sent to extraction. It will appear in the inbox for review.'
    )
    return redirect(reverse('event_management:inbox') + '?view=diverted')


# =============================================================================
# Triage list (email ingestion pipeline — replaces the verification views)
# =============================================================================

# Plain-language reasons shown on the inbox "Needs a decision" cards.
TRIAGE_REASON_LABELS = {
    'auth_failure': (
        'Sender failed authentication',
        'The message failed sender checks (SPF/DKIM/DMARC). It may be spoofed or '
        'phishing, so HillDesk did not read it for scheduling details.'),
    'digest_suspect': (
        'Looks like a newsletter or digest',
        'It lists too many dates to treat as one request. Extract it only if it '
        'really is a scheduling request.'),
    'rate_gate': (
        'Unusual burst from this sender',
        'This sender (or the mailbox) sent more mail than usual in a short window, '
        'so HillDesk paused automatic reading.'),
    'cancellation_of_unknown_event': (
        'Cancellation for an unknown event',
        'The email cancels something, but HillDesk could not match it to an event '
        'on the calendar.'),
    'reschedule_of_unknown_event': (
        'Reschedule for an unknown event',
        'The email moves something, but HillDesk could not match it to an event on '
        'the calendar.'),
}
DEFAULT_TRIAGE_REASON = (
    'Needs a decision',
    'HillDesk set this email aside instead of guessing what to do with it.')


def collect_triage_items():
    """Escalated pipeline items awaiting a human decision, newest first.

    Two sources, merged: escalated EmailProcessing records (auth failures,
    digest suspects, rate-gate bursts, unreadable attachments, malformed
    extractions, candidate-cap collapses) and escalated ExtractionCandidates
    (reschedule/cancellation of an unknown event).
    """
    from .models import ExtractionCandidate

    items = []
    escalated_records = (
        EmailProcessing.objects.filter(status='escalated')
        .select_related('raw_message')
        .order_by('-received')[:200]
    )
    for record in escalated_records:
        escalation = record.get_extracted_field('escalation', {}) or {}
        reason = escalation.get('reason')
        if not reason:
            # Funnel-stage escalations (auth fail, rate gate, digest) carry
            # their reason in the FilterLog, not extracted_data.
            log = (FilterLog.objects
                   .filter(raw_message=record.raw_message, outcome='escalate')
                   .order_by('-created_at').first()) if record.raw_message_id else None
            if log is not None:
                reason = (log.signals.get('reason')
                          or ('auth_failure' if log.signals.get('auth_failures')
                              else 'digest_suspect' if log.signals.get('digest_suspect')
                              else 'rate_gate' if log.stage == 'rate_gate'
                              else log.stage))
        items.append({
            'kind': 'message',
            'record': record,
            'raw': record.raw_message,
            'reason': reason or 'escalated',
            'detail': escalation.get('detail', ''),
            'when': record.received,
        })

    unmatched = (
        ExtractionCandidate.objects.filter(status='escalated')
        .select_related('raw_message', 'email_processing')
        .order_by('-created_at')[:200]
    )
    for cand in unmatched:
        payload = cand.payload or {}
        hint = (payload.get('cancellation_target_hint')
                or payload.get('reschedule_target_hint') or '')
        items.append({
            'kind': 'candidate',
            'candidate': cand,
            'record': cand.email_processing,
            'raw': cand.raw_message,
            'reason': f'{cand.intent.lower()}_of_unknown_event',
            'detail': hint,
            'when': cand.created_at,
        })

    items.sort(key=lambda i: i['when'], reverse=True)
    return items


def _require_inbox(user):
    if not Permissions.has_permission(user, Permissions.VIEW_INBOX):
        raise PermissionDenied('You do not have access to the inbox.')


def _wants_json(request):
    return 'application/json' in request.headers.get('Accept', '')


@login_required
def triage_items_api(request):
    """JSON feed of triage items for the inbox "Needs a decision" cards."""
    _require_inbox(request.user)
    results = []
    seen = set()
    for item in collect_triage_items():
        raw = item['raw']
        if raw is None or raw.id in seen:
            continue
        seen.add(raw.id)
        label, explanation = TRIAGE_REASON_LABELS.get(item['reason'], DEFAULT_TRIAGE_REASON)
        results.append({
            'id': str(raw.id),
            'kind': item['kind'],
            'reason': item['reason'],
            'reason_label': label,
            'explanation': explanation,
            'detail': item['detail'] or '',
            'subject': raw.subject or '',
            'sender': raw.sender or '',
            'sender_name': raw.sender_name or '',
            'mailbox': raw.mailbox or '',
            'received_at': raw.received_at.isoformat() if raw.received_at else None,
            'body_text': (raw.body_text or '')[:20000],
        })
    return JsonResponse({'count': len(results), 'results': results})


@login_required
def triage_list(request):
    """Escalations plus mailbox delivery health (operations view).

    Day to day, these items appear in the inbox as "Needs a decision" cards;
    this page adds subscription/delivery health for whoever runs ingestion.
    """
    _require_inbox(request.user)
    items = collect_triage_items()

    # Reconciliation / delivery health (hardening loop): subscription state per
    # mailbox, plus gap counts — with webhooks on, every sweep-sourced message
    # is one the webhook silently missed.
    from datetime import timedelta

    from django.conf import settings as dj_settings

    from .models import SubscriptionState

    week_ago = timezone.now() - timedelta(days=7)
    subscriptions = list(SubscriptionState.objects.all())
    lapsed = [s for s in subscriptions if s.status == 'lapsed']
    webhook_enabled = getattr(dj_settings, 'GRAPH_WEBHOOK_ENABLED', False)
    gap_count = (
        RawMessage.objects.filter(source='sweep', fetched_at__gte=week_ago).count()
        if webhook_enabled else None
    )

    return render(request, 'email_processing/triage_list.html', {
        'items': items,
        'total_count': len(items),
        'subscriptions': subscriptions,
        'lapsed_subscriptions': lapsed,
        'webhook_enabled': webhook_enabled,
        'gap_count': gap_count,
        'ingested_this_week': RawMessage.objects.filter(fetched_at__gte=week_ago).count(),
    })


@login_required
@require_POST
def triage_extract_anyway(request, raw_message_id):
    """Force an escalated message through extraction (human said it's real)."""
    from .tasks.pipeline import run_pipeline

    _require_inbox(request.user)
    raw = get_object_or_404(RawMessage, pk=raw_message_id)
    run_pipeline.delay(str(raw.id), force_extract=True)
    if _wants_json(request):
        return JsonResponse({'success': True, 'action': 'extract'})
    messages.success(request, f'Message "{raw.subject[:60]}" queued for extraction.')
    return redirect('email_processing:triage_list')


@login_required
@require_POST
def triage_divert(request, raw_message_id):
    """Human confirmed the escalation is noise — set it aside.

    The message stays findable in the divert store; the pipeline records the
    human decision on the record/candidates.
    """
    from .models import ExtractionCandidate

    _require_inbox(request.user)
    raw = get_object_or_404(RawMessage, pk=raw_message_id)
    EmailProcessing.objects.filter(raw_message=raw, status='escalated').update(
        status='rejected', processed_by=request.user,
    )
    ExtractionCandidate.objects.filter(raw_message=raw, status='escalated').update(
        status='rejected',
    )
    FilterLog.objects.create(
        raw_message=raw, stage='postprocess', outcome='divert',
        signals={'reason': 'triage_divert', 'by': str(request.user.id)},
    )
    if _wants_json(request):
        return JsonResponse({'success': True, 'action': 'divert'})
    messages.success(request, f'Message "{raw.subject[:60]}" diverted.')
    return redirect('email_processing:triage_list')
