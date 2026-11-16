# SPDX-License-Identifier: Apache-2.0
from django.urls import reverse
from django.views.generic import TemplateView, RedirectView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db.models import Q, Subquery, OuterRef, DateTimeField
from django.db.models.functions import Coalesce, Greatest
from datetime import timedelta

# Re-exported for urls.py (``views.EventDetailView`` etc.).
from .event_crud_views import (  # noqa: F401
    EventDetailView, EventCreateView,
    EventUpdateView, EventDeleteView,
)
from .event_views_simple import event_editing_interface  # noqa: F401

from ..models import (
    Event, EventApproval, HouseFloorSchedule,
    HouseFloorProceedings,
)
from apps.event_management.utils.json_embed import script_safe_json


def _clean_review_note(comment):
    """Return a reviewer note safe to render: trimmed, with the seed-only
    "(demo data)" qualifier removed and whitespace collapsed."""
    note = (comment or '').strip()
    if not note:
        return ''
    note = note.replace('(demo data)', '')
    return ' '.join(note.split())


class DashboardView(LoginRequiredMixin, TemplateView):
    """Dashboard view with two-column layout: stats/inbox/floor + agenda columns."""
    template_name = 'event_management/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        # Use the project's configured timezone so "today" is the user's local
        # calendar day, not the UTC day. Otherwise events on the user's morning
        # can fall outside "start_date__gte=today" when viewed late at night.
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        end_of_week = today + timedelta(days=(6 - today.weekday()))

        # --- Stat cards ---
        user = self.request.user
        pending_approval_qs = EventApproval.objects.filter(
            approver=user,
            status='pending',
            event__is_archived=False
        )
        context['approval_count'] = pending_approval_qs.count()

        # Review items the current user can actually edit. Admin/scheduler see
        # everything; staff only see events they're assigned to or an approver
        # on, mirroring Permissions.can_edit_event.
        from apps.api.views import _user_editable_event_filter
        from apps.authentication.permissions import Permissions
        review_qs = Event.objects.filter(requires_human_review=True)
        if not Permissions.has_permission(user, Permissions.EDIT_ANY_EVENT):
            review_qs = review_qs.filter(_user_editable_event_filter(user))

        context['human_review_count'] = review_qs.count()
        # Exclude events still pending human review — those live in the inbox,
        # not the schedule, until a human accepts the extraction.
        # Everything below is limited to events this user may see (role
        # scope, same as the events API) and excludes deleted (archived) ones.
        visible = Permissions.scope_events_queryset(user, Event.objects.filter(is_archived=False))
        context['week_event_count'] = visible.filter(
            start_date__gte=today,
            start_date__lte=end_of_week,
            requires_human_review=False
        ).count()

        # --- Inbox preview: human review + pending approvals combined ---
        pending_approval_event_ids = set(
            pending_approval_qs.values_list('event_id', flat=True)
        )
        review_ids = set(review_qs.values_list('id', flat=True))
        # Sort by when items arrived in the inbox:
        # - Approval items: use approval.created_at (when routed)
        # - Extraction items: use event.created (when extracted)
        # - Both: use the more recent of the two
        approval_date_subquery = Subquery(
            EventApproval.objects.filter(
                event=OuterRef('pk'),
                approver=user,
                status='pending'
            ).order_by('-created_at').values('created_at')[:1],
            output_field=DateTimeField()
        )
        inbox_items = Event.objects.filter(
            Q(id__in=review_ids) | Q(id__in=pending_approval_event_ids)
        ).annotate(
            approval_received=approval_date_subquery,
            inbox_date=Greatest(
                Coalesce('approval_received', 'created'),
                'created'
            )
        ).order_by('-inbox_date')
        # Render up to 50 items in the dashboard inbox card; the first 20 are
        # visible and the rest are revealed by the Load More button.
        inbox_preview = list(inbox_items[:50])
        # Attach lightweight routing info (sender_name + is_final_approver) to
        # each preview item that is a pending approval, so the template can
        # render "Sender → YOU (Final)" instead of a generic "Pending Approval"
        # badge. Mirrors the richer computation in
        # EventApprovalService.get_events_needing_user_approval.
        pending_approval_by_event = {
            a.event_id: a for a in pending_approval_qs.select_related('approver')
        }

        def _abbrev_sender(name):
            # Abbreviate the first name to an initial: "Kaden Buss" -> "K. Buss".
            # Single-word names are left unchanged.
            parts = (name or '').strip().split()
            if len(parts) >= 2:
                return f"{parts[0][0]}. {' '.join(parts[1:])}"
            return name or ''

        for item in inbox_preview:
            if item.id in pending_approval_event_ids:
                approval = pending_approval_by_event.get(item.id)
                if approval is None:
                    continue
                current_stage_order = approval.stage_order or 0
                sender_name = ''
                if current_stage_order > 0:
                    prev_approval = EventApproval.objects.filter(
                        event=item,
                        stage_order=current_stage_order - 1,
                        status='approved'
                    ).select_related('approver').first()
                    if prev_approval and prev_approval.approver:
                        sender_name = prev_approval.approver.get_display_name()
                else:
                    routing = item.approval_routing or {}
                    for stage in routing.get('stages', []):
                        if stage.get('order') == 0:
                            approvers = stage.get('approvers', [])
                            if approvers:
                                sender_name = approvers[0].get('name', '')
                            break

                is_final_approver = True
                routing = item.approval_routing or {}
                for stage in routing.get('stages', []):
                    if stage.get('order', 0) == current_stage_order + 1:
                        is_final_approver = False
                        break

                item.routing_sender_name = _abbrev_sender(sender_name)
                item.routing_is_final = is_final_approver

        context['inbox_preview'] = inbox_preview

        # Emails set aside for a human decision ("Needs a decision" in the
        # inbox). Listed first so they're never buried under routine reviews.
        decision_preview = []
        if Permissions.has_permission(user, Permissions.VIEW_INBOX):
            from apps.email_processing.views import TRIAGE_REASON_LABELS, DEFAULT_TRIAGE_REASON, collect_triage_items
            seen = set()
            for triage_item in collect_triage_items():
                raw = triage_item['raw']
                if raw is None or raw.id in seen:
                    continue
                seen.add(raw.id)
                decision_preview.append({
                    'subject': raw.subject or '(no subject)',
                    'received': raw.received_at,
                    'reason_label': TRIAGE_REASON_LABELS.get(triage_item['reason'], DEFAULT_TRIAGE_REASON)[0],
                })
        context['decision_preview'] = decision_preview
        context['inbox_count'] = inbox_items.count() + len(decision_preview)
        context['pending_approval_event_ids'] = pending_approval_event_ids

        # --- My Agenda + Assigned-to-you count.
        # Skip events still pending human review (those belong in the inbox). ---
        upcoming_qs = visible.filter(
            start_date__gte=today,
            requires_human_review=False
        ).order_by('start_date', 'start_time')

        my_events = []
        for event in upcoming_qs[:50]:
            if event.is_user_assigned(user):
                my_events.append(event)
            if len(my_events) >= 15:
                break
        context['my_agenda'] = my_events

        # Count of upcoming events assigned to the current user (for the stat
        # card). Uses the same JSON-staff match as _user_editable_event_filter
        # so the DB does the work without hydrating events.
        assigned_names = []
        full_name = user.get_full_name()
        if full_name:
            assigned_names.append(full_name.lower())
        if user.username:
            assigned_names.append(user.username.lower())
        if getattr(user, 'staff_profile', None):
            assigned_names.append(user.staff_profile.name.lower())
        assigned_emails = []
        if user.email:
            assigned_emails.append(user.email.lower())
        if getattr(user, 'staff_profile', None) and user.staff_profile.email:
            assigned_emails.append(user.staff_profile.email.lower())

        assigned_q = Q()
        for n in assigned_names:
            if n:
                assigned_q |= Q(staff__icontains=n)
        for e in assigned_emails:
            assigned_q |= Q(staff__icontains=e)
        if assigned_q:
            context['my_assigned_count'] = upcoming_qs.filter(assigned_q).count()
        else:
            context['my_assigned_count'] = 0

        # --- Office Agenda: all events today + upcoming.
        # Same exclusion as My Agenda — pre-extraction items shouldn't surface. ---
        context['office_agenda'] = visible.filter(
            start_date__gte=today,
            requires_human_review=False
        ).order_by('start_date', 'start_time')[:20]

        context['today_date'] = today
        context['tomorrow_date'] = tomorrow

        # --- Review Tracker: office-wide open approval-routing paths ---
        REVIEW_STATE_LABELS = {
            'created_route': 'Created route',
            'approved': 'Approved',
            'pending': 'Pending',
            'awaiting': 'Awaiting',
            'sent_back': 'Sent back',
        }
        # Every event anywhere in the office that still has a pending approval is
        # an "open review path." Grouped by event, each row shows the routing
        # stages and who the event is currently waiting on. Computed with two
        # bulk queries (events + all their approval rows) to avoid the per-
        # approver N+1 that ApprovalRoutingService.get_routing_status incurs.
        open_event_ids = list(
            EventApproval.objects
            .filter(status='pending', event__is_archived=False)
            .values_list('event_id', flat=True)
            .distinct()
        )
        review_tracker = []
        if open_event_ids:
            events_by_id = {
                e.id: e for e in Event.objects.filter(id__in=open_event_ids)
            }
            approvals_by_event = {}
            approval_rows = (
                EventApproval.objects
                .filter(event_id__in=open_event_ids)
                .select_related('approver')
                .order_by('stage_order', 'created_at')
            )
            for ap in approval_rows:
                approvals_by_event.setdefault(ap.event_id, []).append(ap)

            for event_id in open_event_ids:
                event = events_by_id.get(event_id)
                if event is None:
                    continue
                rows = approvals_by_event.get(event_id, [])
                pending_rows = [r for r in rows if r.status == 'pending']
                if not pending_rows:
                    continue  # safety: nothing actually pending

                # Current stage = lowest stage_order with a pending approver.
                current_order = min(r.stage_order for r in pending_rows)
                current_pending = [
                    r for r in pending_rows if r.stage_order == current_order
                ]
                waiting_on = [
                    {
                        'name': r.approver.get_display_name() if r.approver else 'Unknown',
                        'is_current_user': r.approver_id == user.id,
                    }
                    for r in current_pending
                ]
                waiting_since = min(
                    (r.created_at for r in current_pending), default=None
                )

                # Real approval rows keyed by (stage_id, approver_id) for status
                # lookup when walking the routing JSON stage definitions.
                status_by_key = {
                    (r.stage_id, str(r.approver_id)): r for r in rows
                }
                routing = event.approval_routing or {}
                stages_json = sorted(
                    routing.get('stages', []), key=lambda s: s.get('order', 0)
                )

                # Flatten every approver into its own node, in routing order.
                # Each node carries a human state label and whether the event is
                # currently sitting on it (the current stage's pending approvers).
                flow = []
                node_index = 0
                for s in stages_json:
                    sid = s.get('stage_id')
                    order = s.get('order', 0)
                    is_current_stage = (order == current_order)
                    for a in s.get('approvers', []):
                        uid = str(a.get('user_id') or '')
                        row = status_by_key.get((sid, uid))
                        st = row.status if row else 'not_started'
                        # Map raw status -> display state. The very first approver
                        # who has acted is the one who created/sent the route.
                        # Pending rows exist for future stages too, so only the
                        # current stage reads "Pending" (the event's turn); later
                        # stages read "Awaiting" until the event reaches them.
                        if st == 'sent_back':
                            state = 'sent_back'
                        elif st == 'approved':
                            state = 'created_route' if node_index == 0 else 'approved'
                        elif st == 'pending' and is_current_stage:
                            state = 'pending'
                        else:
                            state = 'awaiting'
                        flow.append({
                            'name': (
                                row.approver.get_display_name()
                                if row and row.approver
                                else a.get('name', 'Unknown')
                            ),
                            'state': state,
                            'label': REVIEW_STATE_LABELS[state],
                            'is_current': is_current_stage and st == 'pending',
                            # A reviewer's note shows on hover. The "(demo data)"
                            # qualifier is a seed-script marker only and must never
                            # render in the UI, so strip it here.
                            'note': _clean_review_note(row.comment if row else ''),
                        })
                        node_index += 1

                # Flag the node just before a sent-back node so its shape can
                # notch inward and the sent-back arrow can point into it.
                for i in range(len(flow) - 1):
                    if flow[i + 1]['state'] == 'sent_back':
                        flow[i]['next_back'] = True

                review_tracker.append({
                    'event': event,
                    'current_stage_order': current_order,
                    'waiting_on': waiting_on,
                    'waiting_since': waiting_since,
                    'flow': flow,
                })

            # Longest-waiting first (oldest waiting_since at the top).
            review_tracker.sort(key=lambda it: it['waiting_since'] or now)

        context['review_tracker'] = review_tracker
        context['review_tracker_count'] = len(review_tracker)
        # All rows render their stepper on a grid of this many columns so the
        # stages line up vertically across rows regardless of how many each has.
        context['review_tracker_max_steps'] = max(
            (len(it['flow']) for it in review_tracker), default=1
        )

        # --- House Floor Schedule (week-ahead, from docs.house.gov) ---
        monday = today - timedelta(days=today.weekday())
        floor_schedule = (
            HouseFloorSchedule.objects
            .filter(week_date=monday)
            .prefetch_related('items')
            .first()
        )
        # Fall back to the most recent stored week if this week isn't published
        # (House is in recess, or the Monday feed hasn't been posted yet).
        if floor_schedule is None:
            floor_schedule = (
                HouseFloorSchedule.objects
                .prefetch_related('items')
                .order_by('-week_date')
                .first()
            )

        floor_categories = []
        if floor_schedule is not None:
            current_category = None
            for item in floor_schedule.items.all():
                if current_category is None or current_category['name'] != item.category:
                    current_category = {'name': item.category, 'items': []}
                    floor_categories.append(current_category)
                current_category['items'].append(item)

        context['floor_schedule'] = floor_schedule
        context['floor_categories'] = floor_categories

        # --- Live floor proceedings (most recent legislative day, from clerk.house.gov) ---
        floor_proceedings = (
            HouseFloorProceedings.objects
            .prefetch_related('actions')
            .order_by('-legislative_day')
            .first()
        )
        context['floor_proceedings'] = floor_proceedings
        context['floor_actions'] = (
            list(floor_proceedings.actions.all()) if floor_proceedings else []
        )
        # The Clerk's YouTube stream only carries video while the House is in
        # session. Approximate "live" from today's proceedings: there's a feed
        # for today and the day hasn't adjourned yet. When false, the Live Stream
        # tab shows an "offline" message instead of YouTube's blocked-embed error.
        context['floor_is_live'] = bool(
            floor_proceedings
            and floor_proceedings.legislative_day == today
            and not floor_proceedings.day_finished
        )

        return context

class ScheduleView(LoginRequiredMixin, TemplateView):
    """Schedule list view with two-panel layout, search, sort, and filters.

    The frontend fetches events via the /api/events/ endpoint.
    This view provides initial filter choices for the sidebar.
    """
    template_name = 'event_management/schedule_list.html'

    def get_context_data(self, **kwargs):
        from django.conf import settings

        context = super().get_context_data(**kwargs)

        # Provide filter choices as JSON for JavaScript
        filter_choices = {
            'event_statuses': list(settings.EVENT_STATUS_CHOICES),
            'event_types': list(settings.EVENT_TYPE_CHOICES),
        }
        context['filter_choices_json'] = script_safe_json(filter_choices)

        return context


class InboxView(LoginRequiredMixin, TemplateView):
    """Inbox view showing events that require human review.

    Similar to ScheduleView but filtered to requires_human_review=True.
    Uses simplified sort options (Newest/Oldest only).
    """
    template_name = 'event_management/inbox_list.html'

    def get_context_data(self, **kwargs):
        from django.conf import settings

        context = super().get_context_data(**kwargs)

        # Provide filter choices as JSON for JavaScript
        filter_choices = {
            'event_statuses': list(settings.EVENT_STATUS_CHOICES),
            'event_types': list(settings.EVENT_TYPE_CHOICES),
        }
        context['filter_choices_json'] = script_safe_json(filter_choices)

        return context


class SettingsView(LoginRequiredMixin, TemplateView):
    """Unified settings view: office info, email templates, customization, and user preferences."""
    template_name = 'event_management/settings_redesign.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # The DEMO tab (reset demo data) exists only in development.
        from django.conf import settings as django_settings
        context['show_demo_tools'] = bool(django_settings.DEBUG)

        # Email templates (for Email Templates tab)
        from ..models import EmailTemplate
        context['email_templates'] = EmailTemplate.objects.filter(
            created_by=self.request.user
        ).order_by('name')

        # Office customization data (for Office Info / Customization tabs)
        office = getattr(self.request.user, 'office', None)
        if office:
            context['office'] = office
            context['office_status_choices'] = office.event_status_choices
            context['office_type_choices'] = office.event_type_choices
            context['office_format_choices'] = office.event_format_choices

        # Linked staff profile drives the Profile tab.
        context['staff_profile'] = getattr(self.request.user, 'staff_profile', None)

        return context


class OfficeView(LoginRequiredMixin, RedirectView):
    """Legacy route — Office Info is now a tab inside Settings."""
    permanent = False
    query_string = False

    def get_redirect_url(self, *args, **kwargs):
        return reverse('event_management:settings') + '?tab=customization'


class TemplateManagementView(LoginRequiredMixin, RedirectView):
    """Legacy route — template management is now the Templates tab in Settings."""
    permanent = False
    query_string = False

    def get_redirect_url(self, *args, **kwargs):
        return reverse('event_management:settings') + '?tab=templates'


# Additional view functions that are referenced in URLs
