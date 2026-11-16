# SPDX-License-Identifier: Apache-2.0
"""
API Views for HillDesk.
"""

import logging
from datetime import datetime, time

import json as json_module
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from django.http import StreamingHttpResponse

from rest_framework import status, viewsets, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator

from apps.event_management.models import Event, EventChangeHistory, EmailTemplate, EventChangeSuggestion, EventApproval, ExportTemplate
from apps.email_processing.models import EmailProcessing, EmailResponse
from apps.email_processing.graph_client import MicrosoftGraphClient, GraphAPIError
from apps.email_processing.email_response_service import EmailResponseService, EmailResponseError
from apps.authentication.models import OfficeStaff, UserFilterPreset, UserRoutingPreset
from apps.authentication.permissions import Permissions

from .serializers import (
    EventSerializer, EventListSerializer, EmailProcessingSerializer, EmailTemplateSerializer,
    ExportTemplateSerializer, GraphEmailSerializer, SmartExtractSuggestionSerializer,
    EventEditingPanelDataSerializer
)

logger = logging.getLogger('apps.api')
security_logger = logging.getLogger('security_audit')


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for API results."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _user_editable_event_filter(user) -> Q:
    """Q filter selecting events the given staff-role user can edit.

    Mirrors Permissions.can_edit_event for staff: assigned to the event OR an
    approver on its routing. Returns a Q that matches no rows for anonymous /
    missing users. Admin and scheduler should be checked separately — this
    helper assumes the caller already determined the user lacks EDIT_ANY_EVENT.
    """
    if not user or not user.is_authenticated:
        return Q(pk__in=[])

    # Identifiers used to match Event.staff JSON entries (same logic as the
    # "my_events" filter further up).
    names = []
    full_name = user.get_full_name()
    if full_name:
        names.append(full_name.lower())
    names.append(user.username.lower())
    emails = []
    if user.email:
        emails.append(user.email.lower())
    if getattr(user, 'staff_profile', None):
        names.append(user.staff_profile.name.lower())
        if user.staff_profile.email:
            emails.append(user.staff_profile.email.lower())

    staff_q = Q()
    for name in names:
        staff_q |= Q(staff__icontains=name)
    for email in emails:
        staff_q |= Q(staff__icontains=email)

    approver_event_ids = EventApproval.objects.filter(
        approver=user
    ).values_list('event_id', flat=True)

    return staff_q | Q(id__in=approver_event_ids)


@method_decorator(csrf_protect, name='dispatch')
class EventViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Event CRUD operations.
    Provides full CRUD functionality for events with proper validation and audit trails.
    All data is encrypted in transit via HTTPS (enforced by middleware).
    """
    
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    
    def get_queryset(self):
        """Get events queryset with filtering and search."""
        queryset = Event.objects.select_related(
            'created_by', 'modified_by', 'archived_by'
        ).prefetch_related(
            'change_history__user',
            'source_emails',
            'approvals__approver',
            # Normalized contact/org data rendered by the event modal — prefetch
            # to avoid N+1 when serializing each event's contacts/organizations.
            'contact_links__contact__email_addresses',
            'contact_links__contact__phone_numbers',
            'contact_links__contact__organizations',
            'organization_links__organization__email_addresses',
            'organization_links__organization__phone_numbers',
            'organization_links__organization__contacts__email_addresses',
        )

        # Permission view-scope: restrict to events this user is allowed to see.
        # view_all_events -> everything; view_assigned_events -> only assigned /
        # on-routing events; neither -> nothing. All filters below narrow within
        # this scope.
        queryset = Permissions.scope_events_queryset(self.request.user, queryset)

        # Archive filtering:
        #   archived_only=true  -> the Deleted Events view (only soft-deleted events)
        #   include_archived    -> include archived alongside active
        #   (default)           -> hide archived
        if self.request.query_params.get('archived_only') == 'true':
            queryset = queryset.filter(is_archived=True)
        elif not self.request.query_params.get('include_archived'):
            queryset = queryset.filter(is_archived=False)
        
        # Search functionality - searches across key event fields.
        # NOTE: contact/organization names live in the normalized, ENCRYPTED
        # Contact/Organization models and cannot be substring-searched in SQL.
        # We match a linked contact's email EXACTLY via its blind index; name /
        # organization substring search is no longer available here.
        search = self.request.query_params.get('search')
        if search:
            from apps.contacts.crypto import email_blind_index
            search_q = (
                Q(title__icontains=search) |
                Q(location__icontains=search) |
                Q(description__icontains=search) |
                Q(contact_links__contact__email_addresses__email_key=email_blind_index(search))
            )
            queryset = queryset.filter(search_q).distinct()
        
        # Filter by status (supports multiple values)
        status_filters = self.request.query_params.getlist('status')
        if status_filters:
            queryset = queryset.filter(status__in=status_filters)

        # Filter by type (supports multiple values)
        type_filters = self.request.query_params.getlist('type')
        if type_filters:
            queryset = queryset.filter(type__in=type_filters)

        # "My events" filter — events where user is assigned staff or an approver
        if self.request.query_params.get('my_events') == 'true':
            user = self.request.user
            # Build list of name/email identifiers for this user
            names = []
            if user.get_full_name():
                names.append(user.get_full_name().lower())
            names.append(user.username.lower())
            emails = []
            if user.email:
                emails.append(user.email.lower())
            if hasattr(user, 'staff_profile') and user.staff_profile:
                names.append(user.staff_profile.name.lower())
                if user.staff_profile.email:
                    emails.append(user.staff_profile.email.lower())

            # Staff JSONField contains list of dicts with 'name'/'email' or plain strings
            staff_q = Q()
            for name in names:
                staff_q |= Q(staff__icontains=name)
            for email in emails:
                staff_q |= Q(staff__icontains=email)

            # Approval routing JSONField contains approver references
            approval_q = Q()
            for name in names:
                approval_q |= Q(approval_routing__icontains=name)
            for email in emails:
                approval_q |= Q(approval_routing__icontains=email)

            queryset = queryset.filter(staff_q | approval_q)

        # "Overlapping events" filter — only events that overlap with at least one other.
        # Check against ALL non-archived events so that status/type filters don't
        # exclude the counterpart of a genuine overlap.
        if self.request.query_params.get('overlapping_only') == 'true':
            all_dated = list(
                Event.objects.filter(is_archived=False)
                    .exclude(start_date__isnull=True)
                    .values_list('id', 'start_date', 'start_time', 'end_date', 'end_time')
            )
            overlapping_ids = set()
            for i, (id_a, sd_a, st_a, ed_a, et_a) in enumerate(all_dated):
                a_start = datetime.combine(sd_a, st_a or time(0, 0, 0))
                a_end = datetime.combine(ed_a or sd_a, et_a or time(23, 59, 59))
                for j in range(i + 1, len(all_dated)):
                    id_b, sd_b, st_b, ed_b, et_b = all_dated[j]
                    b_start = datetime.combine(sd_b, st_b or time(0, 0, 0))
                    b_end = datetime.combine(ed_b or sd_b, et_b or time(23, 59, 59))
                    if a_start < b_end and b_start < a_end:
                        overlapping_ids.add(id_a)
                        overlapping_ids.add(id_b)
            queryset = queryset.filter(pk__in=overlapping_ids)

        # "Member attending" filter — events whose assigned staff includes the
        # office's Member of Congress (the OfficeStaff row flagged
        # is_member_of_congress). Mirrors the staff-JSON matching used by the
        # serializer's member_of_congress field and the my_events filter.
        if self.request.query_params.get('member_attending') == 'true':
            from apps.authentication.models import OfficeStaff
            moc_names = [
                n for n in OfficeStaff.objects.filter(
                    is_member_of_congress=True
                ).values_list('name', flat=True) if n
            ]
            if moc_names:
                moc_q = Q()
                for name in moc_names:
                    moc_q |= Q(staff__icontains=name)
                queryset = queryset.filter(moc_q)
            else:
                # No Member of Congress configured → no event can match.
                queryset = queryset.none()

        # Filter by staff name (supports multiple values)
        staff_filters = self.request.query_params.getlist('staff')
        if staff_filters:
            staff_q = Q()
            for name in staff_filters:
                staff_q |= Q(staff__icontains=name)
            queryset = queryset.filter(staff_q)

        # Filter by source (email vs manual)
        source_filters = self.request.query_params.getlist('source')
        if source_filters and set(source_filters) != {'email', 'manual'}:
            # Only filter if not all sources selected
            if 'email' in source_filters and 'manual' not in source_filters:
                # Only events with source emails
                queryset = queryset.filter(source_emails__isnull=False).distinct()
            elif 'manual' in source_filters and 'email' not in source_filters:
                # Only events without source emails
                queryset = queryset.exclude(
                    id__in=Event.objects.filter(source_emails__isnull=False).values_list('id', flat=True)
                )

        # Filter by requires_human_review (for Inbox page)
        requires_review = self.request.query_params.get('requires_human_review')
        include_resolved = self.request.query_params.get('include_resolved_reviews') == 'true'

        if requires_review == 'true':
            # The inbox / human-review queue requires the view_inbox permission.
            if not Permissions.has_permission(self.request.user, Permissions.VIEW_INBOX):
                return queryset.none()

            if include_resolved:
                # Include pending reviews, recently resolved reviews (which have
                # extracted_fields but requires_human_review=False), AND dismissed
                # events. Dismissed false positives may have empty extracted_fields,
                # so they get their own branch rather than the resolved one.
                queryset = queryset.filter(
                    Q(requires_human_review=True) |
                    (Q(requires_human_review=False) & ~Q(extracted_fields={})) |
                    Q(review_decision='dismissed')
                )
            else:
                queryset = queryset.filter(requires_human_review=True)
        elif requires_review == 'false':
            # Reviewed events only: drop AI drafts still awaiting a human and
            # dismissed false positives (used by the global "/" quick search).
            queryset = queryset.filter(requires_human_review=False).exclude(
                review_decision='dismissed'
            )

        if requires_review == 'true':
            # Permission scope: users who can't edit any event only see review
            # items they can act on (assigned to the event OR an approver on it).
            user = self.request.user
            if not Permissions.has_permission(user, Permissions.EDIT_ALL_EVENTS):
                queryset = queryset.filter(_user_editable_event_filter(user))

        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                queryset = queryset.filter(start_date__gte=start_dt)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                queryset = queryset.filter(start_date__lte=end_dt)
            except ValueError:
                pass

        # "Undated only" — the Schedule page's Undated tab. Mirrors the client-side
        # definition exactly: no fixed date (start_date is null) OR a tentative date
        # RANGE (end_date present and different from start_date). Filtering here (not
        # client-side over a full fetch) keeps pagination and the "Tentative Date"
        # sort correct — dateless events no longer hide behind filtered-out rows.
        if self.request.query_params.get('undated_only') == 'true':
            from django.db.models import F
            queryset = queryset.filter(
                Q(start_date__isnull=True) |
                (Q(end_date__isnull=False) & ~Q(end_date=F('start_date')))
            )

        # Ordering - support multiple sort options for Schedule tab
        ordering = self.request.query_params.get('ordering', '-created')
        valid_orderings = [
            # 'group' removed: it is now a derived property, not a DB column.
            'start_date', '-start_date',
            'status', '-status',
            'type', '-type',
            'created', '-created',
            'modified', '-modified',
            'title', '-title',
            'location', '-location'
        ]
        if ordering == 'tentative':
            # Undated tab "Tentative Date" sort: order date-range events by their
            # (soonest) window ascending, with truly-dateless events sorted to the
            # end. nulls_last keeps this consistent across PostgreSQL and SQLite.
            from django.db.models import F
            queryset = queryset.order_by(
                F('start_date').asc(nulls_last=True), 'start_time', '-created'
            )
        elif ordering in valid_orderings:
            queryset = queryset.order_by(ordering)

        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return EventListSerializer
        return EventSerializer
    
    def perform_create(self, serializer):
        """Create event with audit logging."""
        from rest_framework.exceptions import PermissionDenied
        if not Permissions.has_permission(self.request.user, Permissions.CREATE_EVENTS):
            raise PermissionDenied('You do not have permission to create events.')
        event = serializer.save()

        security_logger.info(
            f'Event created via API: {event.title or event.group}',
            extra={
                'user_id': self.request.user.id,
                'action': 'create_event',
                'resource': f'event:{event.id}',
                'ip_address': self.request.META.get('REMOTE_ADDR'),
                'user_agent': self.request.META.get('HTTP_USER_AGENT', '')
            }
        )
    
    def perform_update(self, serializer):
        """Update event with audit logging."""
        from rest_framework.exceptions import PermissionDenied
        instance = serializer.instance
        if not Permissions.can_edit_event(self.request.user, instance):
            raise PermissionDenied('You do not have permission to edit this event.')
        # Changing status requires the change-status permission specifically.
        new_status = serializer.validated_data.get('status')
        if (new_status is not None and new_status != instance.status
                and not Permissions.can_change_status(self.request.user)):
            raise PermissionDenied('You do not have permission to change event status.')
        event = serializer.save()

        security_logger.info(
            f'Event updated via API: {event.title or event.group}',
            extra={
                'user_id': self.request.user.id,
                'action': 'update_event',
                'resource': f'event:{event.id}',
                'ip_address': self.request.META.get('REMOTE_ADDR'),
                'user_agent': self.request.META.get('HTTP_USER_AGENT', '')
            }
        )
    
    def perform_destroy(self, instance):
        """Delete event with audit logging."""
        from rest_framework.exceptions import PermissionDenied
        if not Permissions.has_permission(self.request.user, Permissions.ARCHIVE_DELETE_EVENTS):
            raise PermissionDenied('You do not have permission to delete events.')
        # Create change history record before deletion
        EventChangeHistory.objects.create(
            event=instance,
            user=self.request.user,
            field='deleted',
            old_value='False',
            new_value='True',
            ip_address=self.request.META.get('REMOTE_ADDR'),
            user_agent=self.request.META.get('HTTP_USER_AGENT', '')
        )
        
        security_logger.info(
            f'Event deleted via API: {instance.title or instance.group}',
            extra={
                'user_id': self.request.user.id,
                'action': 'delete_event',
                'resource': f'event:{instance.id}',
                'ip_address': self.request.META.get('REMOTE_ADDR'),
                'user_agent': self.request.META.get('HTTP_USER_AGENT', '')
            }
        )
        
        super().perform_destroy(instance)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Soft-delete an event: move it to Deleted Events (restorable)."""
        if not Permissions.has_permission(request.user, Permissions.ARCHIVE_DELETE_EVENTS):
            return Response(
                {'detail': 'You do not have permission to delete events.'},
                status=status.HTTP_403_FORBIDDEN
            )
        event = get_object_or_404(Event, pk=pk)
        if event.is_archived:
            return Response(
                {'detail': 'Event is already deleted.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event.archive(user=request.user)

        security_logger.info(
            f'Event archived (soft-deleted) via API: {event.title or event.group}',
            extra={
                'user_id': request.user.id,
                'action': 'archive_event',
                'resource': f'event:{event.id}',
                'ip_address': request.META.get('REMOTE_ADDR'),
                'user_agent': request.META.get('HTTP_USER_AGENT', '')
            }
        )
        return Response({'success': True, 'id': str(event.id)}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """Restore a soft-deleted event back to the active schedule."""
        if not Permissions.has_permission(request.user, Permissions.ARCHIVE_DELETE_EVENTS):
            return Response(
                {'detail': 'You do not have permission to restore events.'},
                status=status.HTTP_403_FORBIDDEN
            )
        event = get_object_or_404(Event, pk=pk)
        if not event.is_archived:
            return Response(
                {'detail': 'Event is not deleted.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event.unarchive(user=request.user)

        security_logger.info(
            f'Event restored via API: {event.title or event.group}',
            extra={
                'user_id': request.user.id,
                'action': 'restore_event',
                'resource': f'event:{event.id}',
                'ip_address': request.META.get('REMOTE_ADDR'),
                'user_agent': request.META.get('HTTP_USER_AGENT', '')
            }
        )
        return Response({'success': True, 'id': str(event.id)}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'])
    def update_fields(self, request, pk=None):
        """
        Update specific fields of an event.
        Useful for the event editing interface to update individual fields.
        """
        try:
            event = self.get_object()
            
            # Get the fields to update from request data
            fields_to_update = request.data.get('fields', {})
            
            if not fields_to_update:
                return Response(
                    {'error': 'No fields provided for update'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate that only allowed fields are being updated
            # contact/org fields (group, point_of_contact_*) are normalized and
            # managed via the contacts API, so they are not updatable here.
            allowed_fields = {
                'type', 'format', 'duration', 'title', 'description', 'tags',
                'start_date', 'start_time', 'end_date', 'end_time', 'timezone',
                'time_notes', 'is_date_range', 'is_longer_than_day', 'location',
                'legislative_topics', 'participants', 'notes', 'staff', 'status',
                'data_classification',
            }
            
            invalid_fields = set(fields_to_update.keys()) - allowed_fields
            if invalid_fields:
                return Response(
                    {'error': f'Invalid fields: {", ".join(invalid_fields)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Permission checks: direct field edits require edit rights on this
            # event; status changes additionally require change-status rights.
            if not Permissions.can_edit_event(request.user, event):
                return Response(
                    {'error': 'You do not have permission to edit this event'},
                    status=status.HTTP_403_FORBIDDEN
                )
            if 'status' in fields_to_update and not Permissions.can_change_status(request.user):
                return Response(
                    {'error': 'You do not have permission to change event status'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Use the serializer to validate and update
            serializer = EventSerializer(
                event, 
                data=fields_to_update, 
                partial=True,
                context={'request': request}
            )
            
            if serializer.is_valid():
                updated_event = serializer.save()
                
                security_logger.info(
                    f'Event fields updated via API: {list(fields_to_update.keys())} for event: {event.title or event.group}',
                    extra={
                        'user_id': request.user.id,
                        'action': 'update_event_fields',
                        'resource': f'event:{event.id}',
                        'ip_address': request.META.get('REMOTE_ADDR'),
                        'user_agent': request.META.get('HTTP_USER_AGENT', '')
                    }
                )
                
                return Response({
                    'message': 'Fields updated successfully',
                    'updated_fields': list(fields_to_update.keys()),
                    'event': EventSerializer(updated_event).data
                })
            else:
                return Response(
                    {'error': 'Validation failed', 'details': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"Error updating event fields for event {pk}: {e}")
            return Response(
                {'error': 'Failed to update event fields'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def auto_save(self, request, pk=None):
        """
        Auto-save event data without full validation.
        Useful for the event editing interface to save drafts.
        """
        try:
            event = self.get_object()
            
            # Get the fields to update from request data
            fields_to_update = request.data.get('fields', {})
            
            if not fields_to_update:
                return Response(
                    {'message': 'No fields to save'},
                    status=status.HTTP_200_OK
                )
            
            # Update fields directly without full validation
            from apps.contacts.services import NORMALIZED_EVENT_FIELDS, apply_field_to_event
            updated_fields = []
            for field, value in fields_to_update.items():
                if field in NORMALIZED_EVENT_FIELDS:
                    # Normalized contact/org field: create/link instead of setattr.
                    old_value = getattr(event, field, None)
                    apply_field_to_event(event, field, value, request.user)
                    updated_fields.append(field)
                elif hasattr(event, field):
                    old_value = getattr(event, field, None)
                    setattr(event, field, value)
                    updated_fields.append(field)
                    
                    # Create change history for significant changes
                    if old_value != value and field not in ['modified', 'modified_by']:
                        EventChangeHistory.objects.create(
                            event=event,
                            user=request.user,
                            field=field,
                            old_value=str(old_value) if old_value is not None else '',
                            new_value=str(value) if value is not None else '',
                            ip_address=request.META.get('REMOTE_ADDR'),
                            user_agent=request.META.get('HTTP_USER_AGENT', '')
                        )
            
            # Update modified fields
            event.modified_by = request.user
            event.save()
            
            return Response({
                'message': 'Auto-save completed',
                'saved_fields': updated_fields,
                'timestamp': timezone.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error auto-saving event {pk}: {e}")
            return Response(
                {'error': 'Auto-save failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def editing_panel_data(self, request, pk=None):
        """
        Get complete data for event editing panel.
        Returns event, related emails, change history, and templates.
        """
        try:
            event = self.get_object()

            # Related emails are the union of the event's attached threads and
            # directly-linked emails (minus exclusions) — the link tables are
            # the source of truth. Ordered newest-first for the flat list.
            related_emails = (
                event.get_attached_emails()
                .select_related('processed_by', 'thread')
                .order_by('-received')
            )

            # Get change history (last 20 entries)
            change_history = EventChangeHistory.objects.filter(
                event=event
            ).select_related('user').order_by('-timestamp')[:20]
            
            # Get email templates
            email_templates = EmailTemplate.objects.filter(
                is_default=True
            ).order_by('name')
            
            # Prepare AI suggestions if available
            ai_suggestions = []
            if hasattr(event, '_ai_suggestions') and event._ai_suggestions:
                ai_suggestions = event._ai_suggestions
            
            # Check if SmartExtract mode is enabled
            from .services import EventEditingService
            editing_service = EventEditingService()
            smartextract_enabled = editing_service.is_smartextract_enabled(str(event.id))
            
            panel_data = {
                'event': event,
                'related_emails': related_emails,
                'change_history': change_history,
                'ai_suggestions': ai_suggestions,
                'email_templates': email_templates,
                'smartextract_enabled': smartextract_enabled,
            }
            
            serializer = EventEditingPanelDataSerializer(panel_data)
            
            security_logger.info(
                'Event editing panel data retrieved',
                extra={
                    'user_id': request.user.id,
                    'action': 'get_editing_panel_data',
                    'resource': f'event:{event.id}',
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'message': f'Panel data retrieved for event: {event.group}'
                }
            )
            
            return Response(serializer.data)
            
        except Exception as e:
            logger.error(f"Error retrieving editing panel data for event {pk}: {e}")
            return Response(
                {'error': 'Failed to retrieve editing panel data'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'])
    def attach_email_link(self, request, pk=None):
        """Attach a single email to this event (an off-thread / standalone link)."""
        event = self.get_object()
        email_id = request.data.get('email_id')
        if not email_id:
            return Response({'error': 'email_id is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        email = EmailProcessing.objects.filter(pk=email_id).first()
        if email is None:
            return Response({'error': 'Email not found'},
                            status=status.HTTP_404_NOT_FOUND)
        event.attach_email(
            email, origin='manual', user=request.user,
            is_primary=bool(request.data.get('is_primary', False)),
        )
        event.modified_by = request.user
        event.save(update_fields=['attached_email_ids', 'modified_by', 'modified'])
        return self._email_groups_response(event)

    @action(detail=True, methods=['post'])
    def detach_email_link(self, request, pk=None):
        """Remove a direct email link from this event."""
        event = self.get_object()
        email_id = request.data.get('email_id')
        if not email_id:
            return Response({'error': 'email_id is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        event.detach_email(email_id)
        return self._email_groups_response(event)

    @action(detail=True, methods=['post'])
    def exclude_email_link(self, request, pk=None):
        """Remove a single email from this event even if its thread is attached."""
        event = self.get_object()
        email_id = request.data.get('email_id')
        if not email_id:
            return Response({'error': 'email_id is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        event.exclude_email(email_id, user=request.user)
        return self._email_groups_response(event)

    @action(detail=True, methods=['post'])
    def attach_thread_link(self, request, pk=None):
        """Attach an entire conversation thread (by id or conversationId)."""
        from apps.email_processing.models import EmailThread
        event = self.get_object()
        thread_id = request.data.get('thread_id')
        conversation_id = request.data.get('conversation_id')
        thread = None
        if thread_id:
            thread = EmailThread.objects.filter(pk=thread_id).first()
        elif conversation_id:
            thread = EmailThread.objects.filter(conversation_id=conversation_id).first()
        if thread is None:
            return Response({'error': 'Thread not found'},
                            status=status.HTTP_404_NOT_FOUND)
        event.attach_thread(thread, user=request.user)
        return self._email_groups_response(event)

    @action(detail=True, methods=['post'])
    def detach_thread_link(self, request, pk=None):
        """Detach a conversation thread from this event."""
        event = self.get_object()
        thread_id = request.data.get('thread_id')
        if not thread_id:
            return Response({'error': 'thread_id is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        event.detach_thread(thread_id)
        return self._email_groups_response(event)

    @action(detail=True, methods=['get'])
    def attachable_emails(self, request, pk=None):
        """List emails not yet attached to this event, for the attach picker.

        Supports a `q` search over subject/sender. Each result carries its
        conversation thread (if any) so the picker can offer 'attach email' vs
        'attach whole thread'.
        """
        event = self.get_object()
        query = request.query_params.get('q', '').strip()

        attached_ids = list(event.get_attached_emails().values_list('id', flat=True))
        qs = EmailProcessing.objects.exclude(id__in=attached_ids).select_related('thread')
        if query:
            qs = qs.filter(
                Q(subject__icontains=query)
                | Q(sender__icontains=query)
                | Q(sender_name__icontains=query)
            )
        qs = qs.order_by('-received')[:25]

        results = []
        for email in qs:
            thread = email.thread
            results.append({
                'id': str(email.id),
                'subject': email.subject,
                'sender': email.sender,
                'sender_name': email.sender_name,
                'received': email.received.isoformat() if email.received else None,
                'thread': ({
                    'id': str(thread.id),
                    'conversation_id': thread.conversation_id,
                    'subject': thread.subject,
                    'message_count': thread.message_count,
                } if thread else None),
            })
        return Response({'emails': results})

    def _email_groups_response(self, event):
        """Return the refreshed thread-grouped email payload for the modal."""
        from apps.api.serializers import build_email_groups
        return Response(build_email_groups(event))

    @action(detail=False, methods=['get'])
    def recent_activity(self, request):
        """
        Get recent event changes for the activity feed.
        Returns the most recent field changes across all events.
        """
        try:
            # Get recent changes, ordered by timestamp descending
            changes = EventChangeHistory.objects.select_related(
                'event', 'user'
            ).filter(
                event__isnull=False
            ).order_by('-timestamp')[:50]

            result = []
            for change in changes:
                if change.event:
                    result.append({
                        'id': str(change.id),
                        'event_id': str(change.event.id),
                        'event_title': change.event.title or change.event.group or 'Untitled Event',
                        'field': change.field,
                        'old_value': change.old_value or '',
                        'new_value': change.new_value or '',
                        'timestamp': change.timestamp.isoformat(),
                        'user': change.user.get_display_name() if change.user else 'System'
                    })

            return Response(result)

        except Exception as e:
            logger.error(f"Error fetching recent activity: {e}")
            return Response(
                {'error': 'Failed to fetch recent activity'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def overlaps(self, request, pk=None):
        """
        Return events whose time range overlaps with this event.
        Uses a broad date filter via the ORM, then refines with Python
        because the model stores date and time in separate fields.
        """
        # get_object() outside the try so a missing/archived event yields a clean
        # 404 (via DRF) rather than being swallowed into a generic 500.
        event = self.get_object()
        try:
            # Guard: need full time range to detect overlaps
            if not all([event.start_date, event.start_time,
                        event.end_date, event.end_time]):
                return Response([])

            current_start = datetime.combine(event.start_date, event.start_time)
            current_end = datetime.combine(event.end_date, event.end_time)

            # Broad date filter using indexed columns
            candidates = Event.objects.filter(
                start_date__lte=event.end_date,
            ).filter(
                Q(end_date__gte=event.start_date) | Q(end_date__isnull=True)
            ).exclude(
                pk=event.pk
            ).exclude(
                is_archived=True
            ).exclude(
                # Events marked for human review aren't confirmed schedule items yet,
                # so they shouldn't be surfaced as overlaps.
                requires_human_review=True
            )

            # Python-side refinement: combine date+time and check overlap
            overlapping = []
            for other in candidates:
                if not other.start_date or not other.start_time:
                    continue
                other_start = datetime.combine(other.start_date, other.start_time)
                if other.end_date and other.end_time:
                    other_end = datetime.combine(other.end_date, other.end_time)
                else:
                    # Default: end of the event's start/end date
                    fallback_date = other.end_date or other.start_date
                    other_end = datetime.combine(fallback_date, time(23, 59, 59))

                if other_start < current_end and other_end > current_start:
                    overlapping.append(other)

            # Sort by start ascending
            overlapping.sort(key=lambda e: (e.start_date, e.start_time))

            result = [
                {
                    'id': str(e.id),
                    'title': e.title or e.group or 'Untitled Event',
                    'status': e.status,
                    'start_date': e.start_date.isoformat() if e.start_date else None,
                    'start_time': e.start_time.strftime('%H:%M') if e.start_time else None,
                    'end_date': e.end_date.isoformat() if e.end_date else None,
                    'end_time': e.end_time.strftime('%H:%M') if e.end_time else None,
                }
                for e in overlapping
            ]

            return Response(result)

        except Exception as e:
            logger.error(f"Error fetching overlaps for event {pk}: {e}")
            return Response(
                {'error': 'Failed to fetch overlapping events'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_protect, name='dispatch')
class EmailFetchAPIView(APIView):
    """
    API view for fetching emails from Microsoft Graph API.
    Integrates with Graph API to retrieve emails related to events.
    All data is encrypted in transit via HTTPS (enforced by middleware).
    """
    
    permission_classes = [permissions.IsAuthenticated]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.graph_client = None
        
        # Initialize Graph client if credentials are available
        try:
            if all([
                getattr(settings, 'MICROSOFT_TENANT_ID', None),
                getattr(settings, 'MICROSOFT_CLIENT_ID', None),
                getattr(settings, 'MICROSOFT_CLIENT_SECRET', None)
            ]):
                self.graph_client = MicrosoftGraphClient()
        except Exception as e:
            logger.warning(f"Failed to initialize Graph client: {e}")
    
    def get(self, request, *args, **kwargs):
        """
        Fetch emails from Microsoft Graph API.
        
        Query parameters:
        - user_id: User email address (required)
        - folder: Mail folder (default: inbox)
        - top: Number of emails to fetch (default: 50, max: 1000)
        - skip: Number of emails to skip (default: 0)
        - filter: OData filter query
        - event_id: Event ID to find related emails
        """
        if not self.graph_client:
            return Response(
                {'error': 'Microsoft Graph API not configured'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response(
                {'error': 'user_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Get query parameters
            folder = request.query_params.get('folder', 'inbox')
            top = min(int(request.query_params.get('top', 50)), 1000)
            skip = int(request.query_params.get('skip', 0))
            filter_query = request.query_params.get('filter')
            event_id = request.query_params.get('event_id')
            
            # If event_id is provided, try to find related emails
            if event_id:
                try:
                    event = Event.objects.get(id=event_id)
                    
                    # Build filter to find emails related to this event
                    filters = []
                    
                    # Search by point of contact email
                    if event.point_of_contact_email:
                        filters.append(f"from/emailAddress/address eq '{event.point_of_contact_email}'")
                    
                    # Search by group name in subject
                    if event.group:
                        filters.append(f"contains(subject, '{event.group}')")
                    
                    # Search by original email ID
                    if event.original_email_id:
                        filters.append(f"id eq '{event.original_email_id}'")
                    
                    if filters:
                        filter_query = ' or '.join(filters)
                
                except Event.DoesNotExist:
                    pass
            
            # Fetch emails from Graph API
            response = self.graph_client.get_user_emails(
                user_id=user_id,
                folder=folder,
                top=top,
                skip=skip,
                filter_query=filter_query
            )
            
            # Serialize the email data
            emails = response.get('value', [])
            serialized_emails = []
            
            for email in emails:
                try:
                    serializer = GraphEmailSerializer(data=email)
                    if serializer.is_valid():
                        serialized_emails.append(serializer.data)
                    else:
                        logger.warning(f"Invalid email data: {serializer.errors}")
                except Exception as e:
                    logger.warning(f"Error serializing email: {e}")
                    continue
            
            # Prepare response
            result = {
                'emails': serialized_emails,
                'total_count': len(serialized_emails),
                'has_more': len(emails) == top,  # Indicates if there might be more emails
                'next_skip': skip + top if len(emails) == top else None
            }
            
            security_logger.info(
                'Emails fetched via API',
                extra={
                    'user_id': request.user.id,
                    'action': 'fetch_emails',
                    'resource': f'user:{user_id}',
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'message': f'Fetched {len(serialized_emails)} emails from {folder}'
                }
            )
            
            return Response(result)
            
        except GraphAPIError as e:
            logger.error(f"Graph API error fetching emails: {e}")
            return Response(
                {'error': f'Failed to fetch emails: {str(e)}'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except ValueError as e:
            return Response(
                {'error': f'Invalid parameter: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected error fetching emails: {e}")
            return Response(
                {'error': 'Internal server error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request, *args, **kwargs):
        """
        Send email response via Microsoft Graph API.
        
        Request body:
        - user_id: User email address (required)
        - to_recipients: List of recipient email addresses (required)
        - subject: Email subject (required)
        - body: Email body content (required)
        - cc_recipients: List of CC recipients (optional)
        - bcc_recipients: List of BCC recipients (optional)
        - is_html: Whether body is HTML (default: true)
        - original_email_id: ID of original email if replying (optional)
        """
        if not self.graph_client:
            return Response(
                {'error': 'Microsoft Graph API not configured'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        try:
            # Validate required fields
            user_id = request.data.get('user_id')
            to_recipients = request.data.get('to_recipients', [])
            subject = request.data.get('subject')
            body = request.data.get('body')
            
            if not all([user_id, to_recipients, subject, body]):
                return Response(
                    {'error': 'user_id, to_recipients, subject, and body are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not isinstance(to_recipients, list) or not to_recipients:
                return Response(
                    {'error': 'to_recipients must be a non-empty list'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get optional fields
            cc_recipients = request.data.get('cc_recipients', [])
            bcc_recipients = request.data.get('bcc_recipients', [])
            is_html = request.data.get('is_html', True)
            original_email_id = request.data.get('original_email_id')
            
            # Send email via Graph API
            if original_email_id:
                # Reply to existing email
                response = self.graph_client.reply_to_email(
                    user_id=user_id,
                    email_id=original_email_id,
                    body=body,
                    is_html=is_html
                )
            else:
                # Send new email
                response = self.graph_client.send_email(
                    user_id=user_id,
                    to_recipients=to_recipients,
                    subject=subject,
                    body=body,
                    cc_recipients=cc_recipients,
                    bcc_recipients=bcc_recipients,
                    is_html=is_html
                )
            
            security_logger.info(
                'Email sent via API',
                extra={
                    'user_id': request.user.id,
                    'action': 'send_email',
                    'resource': f'user:{user_id}',
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'message': f'Email sent to {len(to_recipients)} recipients'
                }
            )
            
            return Response({
                'message': 'Email sent successfully',
                'response': response
            })
            
        except GraphAPIError as e:
            logger.error(f"Graph API error sending email: {e}")
            return Response(
                {'error': f'Failed to send email: {str(e)}'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"Unexpected error sending email: {e}")
            return Response(
                {'error': 'Internal server error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@method_decorator(csrf_protect, name='dispatch')
class EmailProcessingViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for EmailProcessing records.
    Provides read-only access to processed emails.
    All data is encrypted in transit via HTTPS (enforced by middleware).
    """
    
    serializer_class = EmailProcessingSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    
    def get_queryset(self):
        """Get email processing records with filtering."""
        queryset = EmailProcessing.objects.select_related(
            'processed_by', 'event'
        ).order_by('-received')
        
        # Filter by event
        event_id = self.request.query_params.get('event_id')
        if event_id:
            queryset = queryset.filter(event_id=event_id)
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by scheduling request
        is_scheduling = self.request.query_params.get('is_scheduling_request')
        if is_scheduling is not None:
            queryset = queryset.filter(
                is_scheduling_request=is_scheduling.lower() == 'true'
            )
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def html_content(self, request, pk=None):
        """
        Get HTML content of an email for display in the event editing interface.
        Returns sanitized HTML content with security measures.
        """
        try:
            email = self.get_object()
            
            # Get email body from complete_email_data
            email_body = email.get_email_body()
            
            if not email_body:
                return Response(
                    {'error': 'No email body data available'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Extract HTML and text content
            html_content = email_body.get('html', '')
            text_content = email_body.get('text', '')
            content_type = email_body.get('contentType', 'text')
            
            # Get attachments
            attachments = email.get_email_attachments()
            
            # Prepare attachment data
            attachment_data = []
            for attachment in attachments:
                attachment_data.append({
                    'id': attachment.get('id', ''),
                    'name': attachment.get('name', 'Unknown'),
                    'contentType': attachment.get('contentType', 'application/octet-stream'),
                    'size': attachment.get('size', 0),
                    'isInline': attachment.get('isInline', False)
                })
            
            # Check for external images in HTML
            has_external_images = False
            if html_content:
                import re
                # Look for img tags with src attributes that are URLs
                img_pattern = r'<img[^>]+src=["\']?(https?://[^"\'\s>]+)["\']?[^>]*>'
                external_images = re.findall(img_pattern, html_content, re.IGNORECASE)
                has_external_images = len(external_images) > 0
            
            # Prepare response data
            response_data = {
                'email_id': str(email.id),
                'subject': email.subject,
                'sender': email.sender,
                'sender_name': email.sender_name,
                'received': email.received.isoformat(),
                'content': {
                    'html': html_content,
                    'text': text_content,
                    'contentType': content_type
                },
                'attachments': attachment_data,
                'has_external_images': has_external_images,
                'security_info': {
                    'external_images_blocked': has_external_images,
                    'content_sanitized': bool(html_content),
                    'safe_to_display': True
                }
            }
            
            security_logger.info(
                'Email HTML content retrieved',
                extra={
                    'user_id': request.user.id,
                    'action': 'get_email_html',
                    'resource': f'email:{email.id}',
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'message': f'HTML content retrieved for email: {email.subject[:50]}'
                }
            )
            
            return Response(response_data)
            
        except Exception as e:
            logger.error(f"Error retrieving HTML content for email {pk}: {e}")
            return Response(
                {'error': 'Failed to retrieve email HTML content'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def event_choices(request):
    """
    Get choices for event form fields.
    Returns office-specific choices for status, type, and format.
    Falls back to global defaults if user has no office.
    """
    try:
        user = request.user
        office = getattr(user, 'office', None)

        if office:
            # Get office-specific choices
            event_statuses = office.get_active_statuses()
            event_types = office.get_active_types()
            event_formats = office.get_active_formats()
        else:
            # Fallback to global defaults
            event_statuses = getattr(settings, 'DEFAULT_EVENT_STATUS_CHOICES', [])
            event_types = getattr(settings, 'DEFAULT_EVENT_TYPE_CHOICES', [])
            event_formats = getattr(settings, 'DEFAULT_EVENT_FORMAT_CHOICES', [])

        choices = {
            'event_types': event_types,
            'event_statuses': event_statuses,
            'event_formats': event_formats,
            # Legacy tuple format for backwards compatibility
            'event_types_legacy': list(getattr(settings, 'EVENT_TYPE_CHOICES', [])),
            'event_statuses_legacy': list(getattr(settings, 'EVENT_STATUS_CHOICES', [])),
            # Other global choices (not office-customizable)
            'staff_recommendations': list(getattr(settings, 'STAFF_RECOMMENDATION_CHOICES', [])),
            'hms_review_statuses': list(getattr(settings, 'HMS_REVIEW_STATUS_CHOICES', [])),
            'data_classifications': list(getattr(settings, 'DATA_CLASSIFICATION_LEVELS', [])),
            'durations': getattr(settings, 'DEFAULT_EVENT_DURATION_CHOICES', []),
            'reminder_times': getattr(settings, 'DEFAULT_REMINDER_TIME_CHOICES', []),
            'timezones': list(getattr(settings, 'TIMEZONE_CHOICES', [])),
        }

        return Response(choices)

    except Exception as e:
        logger.error(f"Error retrieving event choices: {e}")
        return Response(
            {'error': 'Failed to retrieve choices'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _serialize_staff(staff):
    """Serialize an OfficeStaff row, including its linked user account + role."""
    linked_user = None
    acct = getattr(staff, 'user_account', None)
    if acct:
        linked_user = {
            'id': str(acct.id),
            'username': acct.username,
            'full_name': acct.get_display_name(),
            'email': acct.email,
            'role_id': str(acct.office_role_id) if acct.office_role_id else None,
            'role_name': acct.get_role_display_name(),
        }
    return {
        'id': str(staff.id),
        'name': staff.name,
        'position': staff.position,
        'email': staff.email,
        'phone': staff.phone,
        'legislative_areas': staff.legislative_areas,
        'order': staff.order,
        'linked_user': linked_user,
    }


def _serialize_role(role):
    """Serialize an office Role for the customization UI."""
    perms = sorted(Permissions.all_permissions()) if role.is_admin else list(role.permissions or [])
    return {
        'id': str(role.id),
        'name': role.name,
        'slug': role.slug,
        'description': role.description,
        'color': role.color,
        'permissions': perms,
        'is_admin': role.is_admin,
        'is_system': role.is_system,
        'is_editable': role.is_editable,
        'is_deletable': role.is_deletable,
        'user_count': role.users.count(),
    }


def _permission_catalog():
    """The grouped permission catalog for the role-builder UI."""
    return [
        {
            'key': group['key'],
            'label': group['label'],
            'permissions': [
                {'key': k, 'label': label, 'help': help_text}
                for (k, label, help_text) in group['permissions']
            ],
        }
        for group in Permissions.PERMISSION_GROUPS
    ]


@api_view(['GET', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def office_choices(request):
    """
    GET: Get all office choices (including inactive ones for management UI).
    PUT: Update office choices for the current user's office.
    """
    user = request.user
    office = getattr(user, 'office', None)

    if not office:
        return Response(
            {'error': 'User does not belong to an office'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if request.method == 'GET':
        from apps.authentication.models import User

        # Get staff members for this office (with linked user info + role)
        staff_members = [
            _serialize_staff(staff)
            for staff in office.staff_members.filter(is_active=True)
                .select_related('user_account__office_role').order_by('order', 'name')
        ]

        # Office roles + the permission catalog for the role-builder UI
        office.create_default_roles()  # defensive: ensure roles exist
        roles = [_serialize_role(r) for r in office.roles.all()]

        # Get unlinked users (users in the office without a staff_profile)
        unlinked_users = []
        for u in User.objects.filter(office=office, staff_profile__isnull=True, is_active=True).order_by('first_name', 'last_name', 'username'):
            unlinked_users.append({
                'id': str(u.id),
                'username': u.username,
                'full_name': u.get_display_name(),
                'email': u.email,
            })

        return Response({
            # Office information
            'member_name': office.member_name,
            'district': office.district,
            'dc_office_address': office.dc_office_address,
            'district_office_address': office.district_office_address,
            # Event choices
            'event_status_choices': office.event_status_choices,
            'event_type_choices': office.event_type_choices,
            'event_format_choices': office.event_format_choices,
            # Tags
            'default_tags': office.default_tags,
            # Staff
            'staff_members': staff_members,
            # Unlinked users (for linking UI)
            'unlinked_users': unlinked_users,
            # Roles & permission catalog (for the Roles & Permissions section)
            'roles': roles,
            'permission_catalog': _permission_catalog(),
            'permission_dependencies': Permissions.PERMISSION_REQUIRES,
            'can_manage_roles': Permissions.can_manage_roles(user),
        })

    elif request.method == 'PUT':
        if not Permissions.has_permission(user, Permissions.MANAGE_OFFICE_SETTINGS):
            return Response(
                {'error': 'You do not have permission to manage office settings'},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            data = request.data

            # Update office information fields
            if 'member_name' in data:
                office.member_name = str(data['member_name'])[:200]
            if 'district' in data:
                office.district = str(data['district'])[:100]
            if 'dc_office_address' in data:
                office.dc_office_address = str(data['dc_office_address'])
            if 'district_office_address' in data:
                office.district_office_address = str(data['district_office_address'])

            # Update default tags
            if 'default_tags' in data:
                default_tags = data['default_tags']
                if not isinstance(default_tags, list):
                    return Response(
                        {'error': 'default_tags must be a list'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                for tag in default_tags:
                    if not isinstance(tag, dict):
                        return Response(
                            {'error': 'Each tag must be an object'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    if 'value' not in tag or 'label' not in tag:
                        return Response(
                            {'error': 'Each tag must have value and label'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                office.default_tags = default_tags

            # Validate and update status choices
            if 'event_status_choices' in data:
                status_choices = data['event_status_choices']
                if not isinstance(status_choices, list):
                    return Response(
                        {'error': 'event_status_choices must be a list'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Validate each status has required fields
                for choice in status_choices:
                    if not isinstance(choice, dict):
                        return Response(
                            {'error': 'Each status choice must be an object'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    if 'value' not in choice or 'label' not in choice:
                        return Response(
                            {'error': 'Each status choice must have value and label'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                office.event_status_choices = status_choices

            # Validate and update type choices
            if 'event_type_choices' in data:
                type_choices = data['event_type_choices']
                if not isinstance(type_choices, list):
                    return Response(
                        {'error': 'event_type_choices must be a list'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                for choice in type_choices:
                    if not isinstance(choice, dict):
                        return Response(
                            {'error': 'Each type choice must be an object'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    if 'value' not in choice or 'label' not in choice:
                        return Response(
                            {'error': 'Each type choice must have value and label'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                office.event_type_choices = type_choices

            # Validate and update format choices
            if 'event_format_choices' in data:
                format_choices = data['event_format_choices']
                if not isinstance(format_choices, list):
                    return Response(
                        {'error': 'event_format_choices must be a list'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                for choice in format_choices:
                    if not isinstance(choice, dict):
                        return Response(
                            {'error': 'Each format choice must be an object'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    if 'value' not in choice or 'label' not in choice:
                        return Response(
                            {'error': 'Each format choice must have value and label'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                office.event_format_choices = format_choices

            office.save()

            security_logger.info(
                'Office choices updated',
                extra={
                    'user_id': request.user.id,
                    'action': 'update_office_choices',
                    'resource': f'office:{office.id}',
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'details': 'Office customization choices updated'
                }
            )

            return Response({
                'success': True,
                'message': 'Office settings updated successfully',
                'member_name': office.member_name,
                'district': office.district,
                'dc_office_address': office.dc_office_address,
                'district_office_address': office.district_office_address,
                'event_status_choices': office.event_status_choices,
                'event_type_choices': office.event_type_choices,
                'event_format_choices': office.event_format_choices,
                'default_tags': office.default_tags,
            })

        except Exception as e:
            logger.error(f"Error updating office choices: {e}")
            return Response(
                {'error': f'Failed to update office choices: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def check_option_usage(request):
    """
    Check if a status/type/format option is in use by any events.
    Used to determine if an option can be hard-deleted or must be soft-deleted.

    Query params:
    - field: 'status', 'type', or 'format'
    - value: the option value to check
    """
    field = request.query_params.get('field')
    value = request.query_params.get('value')

    if not field or not value:
        return Response(
            {'error': 'field and value query parameters are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if field not in ['status', 'type', 'format']:
        return Response(
            {'error': 'field must be status, type, or format'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Count events using this option value
    filter_kwargs = {field: value}
    count = Event.objects.filter(**filter_kwargs).count()

    return Response({
        'field': field,
        'value': value,
        'in_use': count > 0,
        'event_count': count
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_staff_member(request):
    """
    Create a new staff member for the current user's office.
    """
    user = request.user
    office = getattr(user, 'office', None)

    if not office:
        return Response(
            {'error': 'User does not belong to an office'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not Permissions.has_permission(user, Permissions.MANAGE_STAFF):
        return Response(
            {'error': 'You do not have permission to manage staff'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        data = request.data

        # Validate required fields
        name = data.get('name', '').strip()
        if not name:
            return Response(
                {'error': 'Staff name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the staff member
        staff = OfficeStaff.objects.create(
            office=office,
            name=name[:200],
            position=str(data.get('position', ''))[:200],
            email=str(data.get('email', ''))[:254],
            phone=str(data.get('phone', ''))[:50],
            legislative_areas=data.get('legislative_areas', []),
            order=data.get('order', 0),
            is_active=True,
        )

        security_logger.info(
            'Staff member created',
            extra={
                'user_id': request.user.id,
                'action': 'create_staff',
                'resource': f'staff:{staff.id}',
                'ip_address': request.META.get('REMOTE_ADDR'),
            }
        )

        return Response({
            'success': True,
            'staff': _serialize_staff(staff),
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error creating staff member: {e}")
        return Response(
            {'error': f'Failed to create staff member: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT'])
@permission_classes([permissions.IsAuthenticated])
def update_staff_member(request, staff_id):
    """
    Update a staff member for the current user's office.
    """
    user = request.user
    office = getattr(user, 'office', None)

    if not office:
        return Response(
            {'error': 'User does not belong to an office'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Get the staff member and verify it belongs to the user's office
        staff = OfficeStaff.objects.get(id=staff_id, office=office)
    except OfficeStaff.DoesNotExist:
        return Response(
            {'error': 'Staff member not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if not Permissions.has_permission(user, Permissions.MANAGE_STAFF):
        return Response(
            {'error': 'You do not have permission to manage staff'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        data = request.data

        # Update fields if provided
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return Response(
                    {'error': 'Staff name cannot be empty'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            staff.name = name[:200]

        if 'position' in data:
            staff.position = str(data['position'])[:200]
        if 'email' in data:
            staff.email = str(data['email'])[:254]
        if 'phone' in data:
            staff.phone = str(data['phone'])[:50]
        if 'legislative_areas' in data:
            if not isinstance(data['legislative_areas'], list):
                return Response(
                    {'error': 'legislative_areas must be a list'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            staff.legislative_areas = data['legislative_areas']
        if 'order' in data:
            staff.order = int(data['order'])

        staff.save()

        # Optionally assign a role to the linked user account. Role management is
        # admin-only; silently ignored if the editor isn't an admin or the staff
        # member has no linked user account.
        if 'role_id' in data and Permissions.can_manage_roles(request.user):
            from apps.authentication.models import Role, User
            from django.core.exceptions import ValidationError as DjangoValidationError
            linked = getattr(staff, 'user_account', None)
            role_id = data.get('role_id')
            if linked and role_id:
                try:
                    new_role = Role.objects.get(id=role_id, office=office)
                except (Role.DoesNotExist, ValueError, TypeError, DjangoValidationError):
                    return Response(
                        {'error': 'Selected role not found'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Keep at least one admin in the office.
                if linked.is_office_admin and not new_role.is_admin:
                    admin_count = User.objects.filter(
                        office=office, office_role__is_admin=True
                    ).count()
                    if admin_count <= 1:
                        return Response(
                            {'error': 'Cannot remove the only admin. Assign another '
                                      'user the Admin role first.'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                linked.assign_role(new_role)
                linked.save()

        security_logger.info(
            'Staff member updated',
            extra={
                'user_id': request.user.id,
                'action': 'update_staff',
                'resource': f'staff:{staff.id}',
                'ip_address': request.META.get('REMOTE_ADDR'),
            }
        )

        staff.refresh_from_db()
        return Response({
            'success': True,
            'staff': _serialize_staff(staff),
        })

    except Exception as e:
        logger.error(f"Error updating staff member: {e}")
        return Response(
            {'error': f'Failed to update staff member: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_staff_member(request, staff_id):
    """
    Soft-delete a staff member (set is_active to False).
    """
    user = request.user
    office = getattr(user, 'office', None)

    if not office:
        return Response(
            {'error': 'User does not belong to an office'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Get the staff member and verify it belongs to the user's office
        staff = OfficeStaff.objects.get(id=staff_id, office=office)
    except OfficeStaff.DoesNotExist:
        return Response(
            {'error': 'Staff member not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if not Permissions.has_permission(user, Permissions.MANAGE_STAFF):
        return Response(
            {'error': 'You do not have permission to manage staff'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Soft delete - set is_active to False
        staff.is_active = False
        staff.save()

        security_logger.info(
            'Staff member deleted',
            extra={
                'user_id': request.user.id,
                'action': 'delete_staff',
                'resource': f'staff:{staff.id}',
                'ip_address': request.META.get('REMOTE_ADDR'),
            }
        )

        return Response({
            'success': True,
            'message': 'Staff member removed successfully'
        })

    except Exception as e:
        logger.error(f"Error deleting staff member: {e}")
        return Response(
            {'error': f'Failed to delete staff member: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def link_staff_account(request, staff_id):
    """
    Link a user account to a staff member profile.
    Only office admins can perform this action.
    """
    from apps.authentication.models import User

    user = request.user
    office = getattr(user, 'office', None)

    if not office:
        return Response(
            {'error': 'User does not belong to an office'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Linking an account is part of staff management.
    if not Permissions.has_permission(user, Permissions.MANAGE_STAFF):
        return Response(
            {'error': 'You do not have permission to manage staff'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Get the staff member and verify it belongs to the user's office
        staff = OfficeStaff.objects.get(id=staff_id, office=office)
    except OfficeStaff.DoesNotExist:
        return Response(
            {'error': 'Staff member not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Check if staff already has a linked account
    if hasattr(staff, 'user_account') and staff.user_account:
        return Response(
            {'error': f'Staff member is already linked to {staff.user_account.get_display_name()}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        data = request.data
        user_id = data.get('user_id')

        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get the user to link
        try:
            target_user = User.objects.get(id=user_id, office=office, is_active=True)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found or not in your office'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if target user already has a staff profile
        if target_user.staff_profile:
            return Response(
                {'error': f'{target_user.get_display_name()} is already linked to another staff profile'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Link the user to the staff profile
        target_user.staff_profile = staff
        target_user.save()

        security_logger.info(
            'Staff account linked',
            extra={
                'user_id': request.user.id,
                'action': 'link_staff_account',
                'resource': f'staff:{staff.id}',
                'target_user_id': str(target_user.id),
                'ip_address': request.META.get('REMOTE_ADDR'),
            }
        )

        return Response({
            'success': True,
            'message': f'{target_user.get_display_name()} linked to {staff.name}',
            'linked_user': {
                'id': str(target_user.id),
                'username': target_user.username,
                'full_name': target_user.get_display_name(),
                'email': target_user.email,
            }
        })

    except Exception as e:
        logger.error(f"Error linking staff account: {e}")
        return Response(
            {'error': f'Failed to link account: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def unlink_staff_account(request, staff_id):
    """
    Unlink a user account from a staff member profile.
    Only office admins can perform this action.
    """

    user = request.user
    office = getattr(user, 'office', None)

    if not office:
        return Response(
            {'error': 'User does not belong to an office'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Unlinking an account is part of staff management.
    if not Permissions.has_permission(user, Permissions.MANAGE_STAFF):
        return Response(
            {'error': 'You do not have permission to manage staff'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Get the staff member and verify it belongs to the user's office
        staff = OfficeStaff.objects.get(id=staff_id, office=office)
    except OfficeStaff.DoesNotExist:
        return Response(
            {'error': 'Staff member not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Check if staff has a linked account
    if not hasattr(staff, 'user_account') or not staff.user_account:
        return Response(
            {'error': 'Staff member does not have a linked account'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        linked_user = staff.user_account
        user_name = linked_user.get_display_name()

        # Unlink the user from the staff profile
        linked_user.staff_profile = None
        linked_user.save()

        security_logger.info(
            'Staff account unlinked',
            extra={
                'user_id': request.user.id,
                'action': 'unlink_staff_account',
                'resource': f'staff:{staff.id}',
                'target_user_id': str(linked_user.id),
                'ip_address': request.META.get('REMOTE_ADDR'),
            }
        )

        return Response({
            'success': True,
            'message': f'{user_name} unlinked from {staff.name}'
        })

    except Exception as e:
        logger.error(f"Error unlinking staff account: {e}")
        return Response(
            {'error': f'Failed to unlink account: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _first_role_form_error(form):
    """Return the first human-readable error from a RoleForm."""
    for _field, errors in form.errors.items():
        if errors:
            return errors[0]
    return 'Invalid role data'


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_role(request):
    """Create a custom role for the current user's office (admin only)."""
    office = getattr(request.user, 'office', None)
    if not office:
        return Response({'error': 'User does not belong to an office'},
                        status=status.HTTP_400_BAD_REQUEST)
    if not Permissions.can_manage_roles(request.user):
        return Response({'error': 'Only office administrators can manage roles'},
                        status=status.HTTP_403_FORBIDDEN)

    from apps.authentication.forms import RoleForm
    form = RoleForm(request.data, office=office)
    if not form.is_valid():
        return Response({'error': _first_role_form_error(form)},
                        status=status.HTTP_400_BAD_REQUEST)

    role = form.save()
    security_logger.info(
        'Role created', extra={
            'user_id': str(request.user.id), 'role_slug': role.slug,
            'permissions': role.permissions, 'ip_address': request.META.get('REMOTE_ADDR'),
        }
    )
    return Response({'success': True, 'role': _serialize_role(role)},
                    status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([permissions.IsAuthenticated])
def update_role(request, role_id):
    """Update a custom role (admin only; the Admin role is locked)."""
    from apps.authentication.models import Role
    from apps.authentication.forms import RoleForm

    office = getattr(request.user, 'office', None)
    if not office:
        return Response({'error': 'User does not belong to an office'},
                        status=status.HTTP_400_BAD_REQUEST)
    if not Permissions.can_manage_roles(request.user):
        return Response({'error': 'Only office administrators can manage roles'},
                        status=status.HTTP_403_FORBIDDEN)

    try:
        role = Role.objects.get(id=role_id, office=office)
    except Role.DoesNotExist:
        return Response({'error': 'Role not found'}, status=status.HTTP_404_NOT_FOUND)

    if role.is_admin:
        return Response({'error': 'The Admin role cannot be edited'},
                        status=status.HTTP_400_BAD_REQUEST)

    form = RoleForm(request.data, instance=role, office=office)
    if not form.is_valid():
        return Response({'error': _first_role_form_error(form)},
                        status=status.HTTP_400_BAD_REQUEST)

    role = form.save()
    security_logger.info(
        'Role updated', extra={
            'user_id': str(request.user.id), 'role_slug': role.slug,
            'permissions': role.permissions, 'ip_address': request.META.get('REMOTE_ADDR'),
        }
    )
    return Response({'success': True, 'role': _serialize_role(role)})


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_role(request, role_id):
    """Delete a custom role (admin only; blocked for Admin or roles in use)."""
    from apps.authentication.models import Role

    office = getattr(request.user, 'office', None)
    if not office:
        return Response({'error': 'User does not belong to an office'},
                        status=status.HTTP_400_BAD_REQUEST)
    if not Permissions.can_manage_roles(request.user):
        return Response({'error': 'Only office administrators can manage roles'},
                        status=status.HTTP_403_FORBIDDEN)

    try:
        role = Role.objects.get(id=role_id, office=office)
    except Role.DoesNotExist:
        return Response({'error': 'Role not found'}, status=status.HTTP_404_NOT_FOUND)

    if role.is_admin:
        return Response({'error': 'The Admin role cannot be deleted'},
                        status=status.HTTP_400_BAD_REQUEST)
    if role.users.exists():
        return Response(
            {'error': f'Cannot delete "{role.name}" — {role.users.count()} user(s) still '
                      'have it. Reassign them to another role first.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    name, slug = role.name, role.slug
    role.delete()
    security_logger.info(
        'Role deleted', extra={
            'user_id': str(request.user.id), 'role_slug': slug,
            'ip_address': request.META.get('REMOTE_ADDR'),
        }
    )
    return Response({'success': True, 'message': f'Role "{name}" deleted'})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def validate_event_data(request):
    """
    Validate event data without saving.
    Useful for client-side validation feedback.
    """
    try:
        serializer = EventSerializer(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            return Response({
                'valid': True,
                'message': 'Event data is valid'
            })
        else:
            return Response({
                'valid': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        logger.error(f"Error validating event data: {e}")
        return Response(
            {'error': 'Validation failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class SmartExtractAPIView(APIView):
    """
    API view for SmartExtract AI functionality.
    Handles AI suggestions and review process.
    """
    
    permission_classes = [permissions.IsAuthenticated]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import SmartExtractService
        self.smart_extract_service = SmartExtractService()
    
    def get(self, request, event_id, *args, **kwargs):
        """
        Get AI suggestions for an event.
        
        Path parameters:
        - event_id: Event UUID
        """
        try:
            event = get_object_or_404(Event, id=event_id)
            
            # Generate suggestions
            suggestions = self.smart_extract_service.generate_suggestions(event)
            
            # Serialize suggestions
            serializer = SmartExtractSuggestionSerializer(suggestions, many=True)
            
            security_logger.info(
                'SmartExtract suggestions generated',
                extra={
                    'user_id': request.user.id,
                    'action': 'generate_suggestions',
                    'resource': f'event:{event_id}',
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'message': f'Generated {len(suggestions)} suggestions'
                }
            )
            
            return Response({
                'event_id': event_id,
                'suggestions': serializer.data,
                'total_suggestions': len(suggestions)
            })
            
        except Event.DoesNotExist:
            return Response(
                {'error': 'Event not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error generating suggestions for event {event_id}: {e}")
            return Response(
                {'error': 'Failed to generate suggestions'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request, event_id, *args, **kwargs):
        """
        Approve or reject AI suggestions.
        
        Request body:
        - action: 'approve' or 'reject'
        - field: Field name
        - value: Suggested value (for approve action)
        """
        try:
            event = get_object_or_404(Event, id=event_id)
            
            action = request.data.get('action')
            field = request.data.get('field')
            
            if not action or not field:
                return Response(
                    {'error': 'action and field are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if action == 'approve':
                value = request.data.get('value')
                if value is None:
                    return Response(
                        {'error': 'value is required for approve action'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                success = self.smart_extract_service.approve_suggestion(
                    event, field, value, request.user
                )
                
                if success:
                    security_logger.info(
                        'SmartExtract suggestion approved',
                        extra={
                            'user_id': request.user.id,
                            'action': 'approve_suggestion',
                            'resource': f'event:{event_id}',
                            'ip_address': request.META.get('REMOTE_ADDR'),
                            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                            'message': f'Approved suggestion for field {field}'
                        }
                    )
                    
                    return Response({'message': 'Suggestion approved successfully'})
                else:
                    return Response(
                        {'error': 'Failed to approve suggestion'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            elif action == 'reject':
                success = self.smart_extract_service.reject_suggestion(
                    event, field, request.user
                )
                
                if success:
                    security_logger.info(
                        'SmartExtract suggestion rejected',
                        extra={
                            'user_id': request.user.id,
                            'action': 'reject_suggestion',
                            'resource': f'event:{event_id}',
                            'ip_address': request.META.get('REMOTE_ADDR'),
                            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                            'message': f'Rejected suggestion for field {field}'
                        }
                    )
                    
                    return Response({'message': 'Suggestion rejected successfully'})
                else:
                    return Response(
                        {'error': 'Failed to reject suggestion'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            else:
                return Response(
                    {'error': 'Invalid action. Must be "approve" or "reject"'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
        except Event.DoesNotExist:
            return Response(
                {'error': 'Event not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error processing suggestion for event {event_id}: {e}")
            return Response(
                {'error': 'Failed to process suggestion'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def enable_smartextract_mode(request, event_id):
    """
    Enable SmartExtract mode for an event.
    """
    try:
        from .services import EventEditingService
        
        service = EventEditingService()
        success = service.enable_smartextract_mode(event_id)
        
        if success:
            security_logger.info(
                'SmartExtract mode enabled',
                extra={
                    'user_id': request.user.id,
                    'action': 'enable_smartextract',
                    'resource': f'event:{event_id}',
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'message': 'SmartExtract mode enabled'
                }
            )
            
            return Response({'message': 'SmartExtract mode enabled'})
        else:
            return Response(
                {'error': 'Failed to enable SmartExtract mode'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
    except Exception as e:
        logger.error(f"Error enabling SmartExtract mode for event {event_id}: {e}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def disable_smartextract_mode(request, event_id):
    """
    Disable SmartExtract mode for an event.
    """
    try:
        from .services import EventEditingService
        
        service = EventEditingService()
        success = service.disable_smartextract_mode(event_id)
        
        if success:
            security_logger.info(
                'SmartExtract mode disabled',
                extra={
                    'user_id': request.user.id,
                    'action': 'disable_smartextract',
                    'resource': f'event:{event_id}',
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'message': 'SmartExtract mode disabled'
                }
            )
            
            return Response({'message': 'SmartExtract mode disabled'})
        else:
            return Response(
                {'error': 'Failed to disable SmartExtract mode'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
    except Exception as e:
        logger.error(f"Error disabling SmartExtract mode for event {event_id}: {e}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def smartextract_status(request, event_id):
    """
    Get SmartExtract mode status for an event.
    """
    try:
        from .services import EventEditingService

        service = EventEditingService()
        is_enabled = service.is_smartextract_enabled(event_id)

        return Response({
            'event_id': event_id,
            'smartextract_enabled': is_enabled
        })

    except Exception as e:
        logger.error(f"Error getting SmartExtract status for event {event_id}: {e}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =============================================================================
# Human Review API Endpoints
# =============================================================================

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def review_field(request, event_id):
    """
    Review a single AI-extracted field.

    POST body:
    - field: Field name to review (required)
    - action: 'accept', 'reject', or 'undo_reject' (required)

    Returns:
    - success: Boolean
    - message: Status message
    - review_complete: Whether all fields are reviewed
    - fields_remaining: Count of pending fields
    - extracted_fields: Updated extracted_fields dict
    """
    try:
        from .services import FieldReviewService

        if not Permissions.has_permission(request.user, Permissions.PROCESS_INBOX):
            return Response(
                {'error': 'You do not have permission to process inbox items'},
                status=status.HTTP_403_FORBIDDEN
            )

        event = get_object_or_404(Event, id=event_id)
        service = FieldReviewService()

        field_name = request.data.get('field')
        action = request.data.get('action')

        if not field_name or not action:
            return Response(
                {'error': 'field and action are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        ip_address = request.META.get('REMOTE_ADDR')

        if action == 'accept':
            result = service.accept_field(event, field_name, request.user, ip_address)
        elif action == 'reject':
            result = service.reject_field(event, field_name, request.user, ip_address)
        elif action == 'undo_reject':
            result = service.undo_reject(event, field_name, request.user, ip_address)
        else:
            return Response(
                {'error': 'Invalid action. Use accept, reject, or undo_reject'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if result['success']:
            security_logger.info(
                f'Field review action: {action} on {field_name}',
                extra={
                    'user_id': request.user.id,
                    'action': f'review_field_{action}',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error reviewing field for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to review field'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def review_contact(request, event_id):
    """
    Review a single extracted contact card (multi-contact overhaul).

    POST body:
    - ref: Card ref (e.g. 'c0') (required)
    - action: 'accept', 'reject', or 'undo' (required)
    - On accept, optional resolution overrides: resolution_action
      ('new'|'link'|'link_update'), matched_id, role, is_primary,
      additions[], replaces[], field_edits{}.
    """
    try:
        from .services import FieldReviewService

        if not Permissions.has_permission(request.user, Permissions.PROCESS_INBOX):
            return Response(
                {'error': 'You do not have permission to process inbox items'},
                status=status.HTTP_403_FORBIDDEN
            )

        event = get_object_or_404(Event, id=event_id)
        ref = request.data.get('ref')
        action = request.data.get('action')
        if not ref or not action:
            return Response({'error': 'ref and action are required'},
                            status=status.HTTP_400_BAD_REQUEST)

        ip_address = request.META.get('REMOTE_ADDR')
        result = FieldReviewService().review_contact(
            event, ref, action, request.user, ip_address, payload=request.data,
        )
        if result['success']:
            security_logger.info(
                f'Contact review action: {action} on {ref}',
                extra={
                    'user_id': request.user.id,
                    'action': f'review_contact_{action}',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            return Response(result)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error reviewing contact for event {event_id}: {e}")
        return Response({'error': 'Failed to review contact'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def review_organization(request, event_id):
    """
    Review a single extracted organization card (multi-contact overhaul).

    POST body mirrors review_contact: ref, action, and optional resolution
    overrides on accept (resolution_action, matched_id, is_primary, additions[],
    replaces[], field_edits{}).
    """
    try:
        from .services import FieldReviewService

        if not Permissions.has_permission(request.user, Permissions.PROCESS_INBOX):
            return Response(
                {'error': 'You do not have permission to process inbox items'},
                status=status.HTTP_403_FORBIDDEN
            )

        event = get_object_or_404(Event, id=event_id)
        ref = request.data.get('ref')
        action = request.data.get('action')
        if not ref or not action:
            return Response({'error': 'ref and action are required'},
                            status=status.HTTP_400_BAD_REQUEST)

        ip_address = request.META.get('REMOTE_ADDR')
        result = FieldReviewService().review_organization(
            event, ref, action, request.user, ip_address, payload=request.data,
        )
        if result['success']:
            security_logger.info(
                f'Organization review action: {action} on {ref}',
                extra={
                    'user_id': request.user.id,
                    'action': f'review_organization_{action}',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            return Response(result)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error reviewing organization for event {event_id}: {e}")
        return Response({'error': 'Failed to review organization'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def accept_all_fields(request, event_id):
    """
    Accept all pending fields at once.
    Hidden power-user feature (Ctrl+Shift+A keyboard shortcut).
    Requires security approval before exposing in UI.

    Returns:
    - success: Boolean
    - message: Status message
    - fields_accepted: List of accepted field names
    - review_complete: Boolean (always True on success)
    """
    try:
        from .services import FieldReviewService

        if not Permissions.has_permission(request.user, Permissions.PROCESS_INBOX):
            return Response(
                {'error': 'You do not have permission to process inbox items'},
                status=status.HTTP_403_FORBIDDEN
            )

        event = get_object_or_404(Event, id=event_id)
        service = FieldReviewService()

        ip_address = request.META.get('REMOTE_ADDR')
        result = service.accept_all_fields(event, request.user, ip_address)

        if result['success']:
            security_logger.info(
                'All fields accepted (bulk action)',
                extra={
                    'user_id': request.user.id,
                    'action': 'accept_all_fields',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error accepting all fields for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to accept all fields'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def dismiss_review(request, event_id):
    """
    Dismiss an AI-extracted event as a false positive, or restore a previously
    dismissed event back to the review queue.

    POST body:
    - action: 'dismiss' or 'undo_dismiss' (required)

    Returns:
    - success: Boolean
    - message: Status message
    - review_decision: Updated review decision ('' or 'dismissed')
    """
    try:
        from .services import FieldReviewService

        if not Permissions.has_permission(request.user, Permissions.PROCESS_INBOX):
            return Response(
                {'error': 'You do not have permission to process inbox items'},
                status=status.HTTP_403_FORBIDDEN
            )

        event = get_object_or_404(Event, id=event_id)
        service = FieldReviewService()

        action = request.data.get('action', 'dismiss')
        ip_address = request.META.get('REMOTE_ADDR')

        if action == 'dismiss':
            result = service.dismiss_event(
                event, request.user, ip_address,
                junk=bool(request.data.get('junk', False)),
            )
        elif action == 'undo_dismiss':
            result = service.undo_dismiss(event, request.user, ip_address)
        else:
            return Response(
                {'error': 'Invalid action. Use dismiss or undo_dismiss'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if result['success']:
            security_logger.info(
                f'{action.title()} event {event.group}',
                extra={
                    'user_id': request.user.id,
                    'action': f'review_{action}',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error dismissing event {event_id}: {e}")
        return Response(
            {'error': 'Failed to dismiss event'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def review_status(request, event_id):
    """
    Get review status for an event.

    Returns:
    - requires_human_review: Boolean
    - total_fields: Total extracted fields count
    - pending_count: Fields awaiting review
    - accepted_count: Accepted fields count
    - rejected_count: Rejected fields count
    - fields: Dict with status for each field
    - is_complete: Whether review is complete
    """
    try:
        from .services import FieldReviewService

        event = get_object_or_404(Event, id=event_id)
        service = FieldReviewService()

        status_data = service.get_review_status(event)

        security_logger.info(
            'Review status retrieved',
            extra={
                'user_id': request.user.id,
                'action': 'get_review_status',
                'resource': f'event:{event_id}',
                'ip_address': request.META.get('REMOTE_ADDR'),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            }
        )

        return Response(status_data)

    except Exception as e:
        logger.error(f"Error getting review status for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to get review status'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =============================================================================
# Staff Change Suggestion API Endpoints
# =============================================================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def check_edit_permission(request, event_id):
    """
    Check if user can edit event directly or must suggest changes.

    Returns:
    - can_edit_directly: Boolean - True if user can save changes directly
    - requires_suggestion: Boolean - True if changes must be suggested
    - user_role: User's current role
    - is_assigned: Whether user is assigned to this event
    """
    try:
        event = get_object_or_404(Event, id=event_id)

        can_edit = Permissions.can_edit_event(request.user, event)
        requires_suggestion = Permissions.staff_edit_requires_review(request.user, event)
        is_assigned = event.is_user_assigned(request.user)

        return Response({
            'can_edit_directly': can_edit,
            'requires_suggestion': requires_suggestion,
            'user_role': request.user.role,
            'is_assigned': is_assigned,
            'can_change_status': Permissions.can_change_status(request.user),
            'can_configure_approvals': Permissions.can_configure_approvals(request.user)
        })

    except Exception as e:
        logger.error(f"Error checking edit permission for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to check edit permission'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def create_suggestion(request, event_id):
    """
    Create a change suggestion for an event field.

    POST body:
    - field_name: Name of the field to change (required)
    - new_value: Suggested new value (required)
    - reason: Optional reason for the change

    Returns:
    - success: Boolean
    - suggestion: Created suggestion data
    """
    try:
        from .services import ChangeSuggestionService

        event = get_object_or_404(Event, id=event_id)
        service = ChangeSuggestionService()

        field_name = request.data.get('field_name')
        new_value = request.data.get('new_value')
        reason = request.data.get('reason', '')

        if not field_name:
            return Response(
                {'error': 'field_name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if new_value is None:
            return Response(
                {'error': 'new_value is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        ip_address = request.META.get('REMOTE_ADDR')
        result = service.create_suggestion(
            event, field_name, new_value, request.user, reason, ip_address
        )

        if result['success']:
            security_logger.info(
                f'Change suggestion created for field {field_name}',
                extra={
                    'user_id': request.user.id,
                    'action': 'create_suggestion',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'field_name': field_name
                }
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error creating suggestion for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to create suggestion'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_event_suggestions(request, event_id):
    """
    Get all pending suggestions for an event.

    Returns:
    - suggestions: List of pending suggestions
    - count: Number of pending suggestions
    """
    try:
        from .services import ChangeSuggestionService

        event = get_object_or_404(Event, id=event_id)
        service = ChangeSuggestionService()

        suggestions = service.get_pending_suggestions_for_event(event)

        return Response({
            'suggestions': suggestions,
            'count': len(suggestions)
        })

    except Exception as e:
        logger.error(f"Error getting suggestions for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to get suggestions'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def review_suggestion(request, suggestion_id):
    """
    Approve or reject a change suggestion.

    POST body:
    - action: 'approve' or 'reject' (required)
    - comment: Optional review comment

    Returns:
    - success: Boolean
    - suggestion: Updated suggestion data
    """
    try:
        from .services import ChangeSuggestionService

        service = ChangeSuggestionService()

        action = request.data.get('action')
        comment = request.data.get('comment', '')

        if action not in ('approve', 'reject', 'revert'):
            return Response(
                {'error': "action must be 'approve', 'reject', or 'revert'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ip_address = request.META.get('REMOTE_ADDR')

        if action == 'approve':
            result = service.approve_suggestion(
                suggestion_id, request.user, comment, ip_address,
                # Optional reviewer-edited value from the change-request panel.
                value_override=request.data.get('value'),
            )
        elif action == 'revert':
            result = service.revert_suggestion(suggestion_id, request.user, comment, ip_address)
        else:
            result = service.reject_suggestion(suggestion_id, request.user, comment, ip_address)

        if result['success']:
            security_logger.info(
                f'Suggestion {suggestion_id} {action}ed',
                extra={
                    'user_id': request.user.id,
                    'action': f'{action}_suggestion',
                    'resource': f'suggestion:{suggestion_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error reviewing suggestion {suggestion_id}: {e}")
        return Response(
            {'error': 'Failed to review suggestion'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_inbox_suggestions(request):
    """
    Get all events with pending suggestions for the current user's office.

    Used for inbox filtering to show events needing scheduler attention.

    Returns:
    - events: List of events with pending suggestion counts
    """
    try:
        from .services import ChangeSuggestionService

        # Only schedulers and admins can see this
        if not Permissions.can_approve_suggestions(request.user):
            return Response({
                'events': [],
                'message': 'Only schedulers and admins can view pending suggestions'
            })

        service = ChangeSuggestionService()
        events = service.get_events_with_pending_suggestions(request.user)

        return Response({
            'events': events,
            'count': len(events)
        })

    except Exception as e:
        logger.error(f"Error getting inbox suggestions: {e}")
        return Response(
            {'error': 'Failed to get inbox suggestions'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def bulk_approve_suggestions(request, event_id):
    """
    Approve all pending suggestions for an event.

    POST body:
    - comment: Optional review comment

    Returns:
    - success: Boolean
    - approved_count: Number of suggestions approved
    """
    try:
        from .services import ChangeSuggestionService

        event = get_object_or_404(Event, id=event_id)
        service = ChangeSuggestionService()

        comment = request.data.get('comment', '')
        ip_address = request.META.get('REMOTE_ADDR')

        result = service.bulk_approve_for_event(event, request.user, comment, ip_address)

        if result['success']:
            security_logger.info(
                f'Bulk approved {result["approved_count"]} suggestions for event {event_id}',
                extra={
                    'user_id': request.user.id,
                    'action': 'bulk_approve_suggestions',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'approved_count': result['approved_count']
                }
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error bulk approving suggestions for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to bulk approve suggestions'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =============================================================================
# Approval Routing API Endpoints
# =============================================================================

@api_view(['GET', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def approval_routing(request, event_id):
    """
    GET: Get approval routing configuration and status for an event.
    PUT: Update approval routing configuration (admin/scheduler only).

    PUT body:
    - routing_config: Complete routing configuration object

    Returns:
    - has_routing: Boolean
    - is_complete: Boolean
    - current_stage: Current stage ID or None
    - stages: List of stage status objects
    """
    try:
        from .services import ApprovalRoutingService

        event = get_object_or_404(Event, id=event_id)
        service = ApprovalRoutingService()

        if request.method == 'GET':
            # Debug: Log what's in the event's approval_routing
            import json
            logger.info(
                f"GET approval-routing for event {event_id}: "
                f"event.approval_routing = {json.dumps(event.approval_routing)}"
            )

            routing_status = service.get_routing_status(event, current_user=request.user)
            user_id = str(request.user.id)

            # Include raw routing config so JS can access staff_id/user_id for re-editing
            routing_status['routing'] = event.approval_routing or {}

            # Add user-specific context fields
            routing_status['can_user_approve'] = service.can_user_approve(event, user_id)
            routing_status['is_first_approver'] = service.is_first_approver(event, user_id)

            # Add edit capability info
            edit_info = service.can_edit_routing(event, request.user)
            routing_status['can_edit_routing'] = edit_info.get('can_edit', False)
            routing_status['routing_has_activity'] = edit_info.get('has_activity', False)
            routing_status['edit_warning'] = edit_info.get('warning')

            logger.info(
                f"GET approval-routing response: {json.dumps(routing_status)}"
            )

            return Response(routing_status)

        elif request.method == 'PUT':
            routing_config = request.data.get('routing_config')
            if not routing_config:
                return Response(
                    {'error': 'routing_config is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            ip_address = request.META.get('REMOTE_ADDR')
            result = service.update_routing_config(
                event, routing_config, request.user, ip_address
            )

            if result['success']:
                security_logger.info(
                    f'Approval routing updated for event {event_id}',
                    extra={
                        'user_id': request.user.id,
                        'action': 'update_approval_routing',
                        'resource': f'event:{event_id}',
                        'ip_address': ip_address,
                        'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    }
                )
                return Response(result)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error with approval routing for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to process approval routing request'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def submit_approval(request, event_id):
    """
    Submit an approval decision (approve or send back).

    POST body:
    - action: 'approve' or 'send_back' (required)
    - comment: Optional comment for either action
    - edits: Optional list of edits made during approval turn

    Returns:
    - success: Boolean
    - is_routing_complete: Boolean
    - routing_status: Updated routing status
    """
    try:
        from .services import ApprovalRoutingService

        event = get_object_or_404(Event, id=event_id)
        service = ApprovalRoutingService()

        action = request.data.get('action')
        comment = request.data.get('comment', '')
        edits = request.data.get('edits', [])

        if action not in ('approve', 'send_back'):
            return Response(
                {'error': "action must be 'approve' or 'send_back'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ip_address = request.META.get('REMOTE_ADDR')

        if action == 'approve':
            result = service.approve(event, request.user, comment, ip_address, edits)
        else:
            result = service.send_back(event, request.user, comment, ip_address)

        if result['success']:
            security_logger.info(
                f'Approval {action} submitted for event {event_id}',
                extra={
                    'user_id': request.user.id,
                    'action': f'approval_{action}',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error submitting approval for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to submit approval'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def cancel_review(request, event_id):
    """
    Cancel/remove entire approval routing. Creator only, when it's their turn.

    This allows the creator to cancel the review process after it has been
    sent back to them. They cannot cancel while someone else is reviewing.

    Returns:
    - success: Boolean
    - message: Status message
    """
    try:
        from .services import ApprovalRoutingService

        event = get_object_or_404(Event, id=event_id)
        service = ApprovalRoutingService()

        ip_address = request.META.get('REMOTE_ADDR')
        result = service.cancel_review(event, request.user, ip_address)

        if result['success']:
            security_logger.info(
                f'Review cancelled for event {event_id}',
                extra={
                    'user_id': request.user.id,
                    'action': 'cancel_review',
                    'resource': f'event:{event_id}',
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                }
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error cancelling review for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to cancel review'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def remove_routing(request, event_id):
    """
    Remove approval routing from an event. Scheduler-only operation.

    Unlike cancel_review (which is for creators when it's their turn),
    this allows schedulers to remove routing regardless of state.
    """
    try:
        from .services import ApprovalRoutingService

        event = Event.objects.get(id=event_id)

        service = ApprovalRoutingService()
        ip_address = request.META.get('REMOTE_ADDR')
        result = service.remove_routing(event, request.user, ip_address)

        if result.get('success'):
            # Audit the removal (there is no SecurityAuditLog model; the
            # security_audit logger is the project's audit channel).
            security_logger.info(
                'Approval routing removed',
                extra={
                    'user_id': request.user.id,
                    'action': 'remove_routing',
                    'resource_type': 'event',
                    'resource_id': str(event_id),
                    'ip_address': ip_address,
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                },
            )
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

    except Event.DoesNotExist:
        return Response(
            {'error': 'Event not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error removing routing for event {event_id}: {e}")
        return Response(
            {'error': 'Failed to remove routing'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def events_needing_approval(request):
    """
    Get all events that need the current user's approval.

    Query params:
    - include_resolved: 'false' to exclude resolved (approved/sent_back) items.
      Defaults to including them so the inbox can still show history.

    Returns:
    - events: List of events needing user's approval
    - count: Number of events
    """
    try:
        from .services import ApprovalRoutingService

        include_resolved = request.query_params.get('include_resolved', 'true').lower() != 'false'

        service = ApprovalRoutingService()
        events = service.get_events_needing_user_approval(request.user, include_resolved=include_resolved)

        return Response({
            'events': events,
            'count': len(events)
        })

    except Exception as e:
        logger.error(f"Error getting events needing approval: {e}")
        return Response(
            {'error': 'Failed to get events needing approval'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =============================================================================
# Email Template & Response Endpoints
# =============================================================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def email_templates_list(request):
    """
    Get active templates for user's office, grouped by category.
    Returns system defaults plus office-specific templates.
    """
    try:
        office = getattr(request.user, 'office', None)
        service = EmailResponseService()
        include_inactive = request.query_params.get('include_inactive') in ('1', 'true', 'True')
        templates = service.get_available_templates(
            category=request.query_params.get('category'),
            office=office,
            include_inactive=include_inactive,
        )
        serializer = EmailTemplateSerializer(templates, many=True)

        # Group by category for frontend convenience
        grouped = {}
        for t in serializer.data:
            cat = t['category']
            if cat not in grouped:
                grouped[cat] = {
                    'category': cat,
                    'category_display': t.get('category_display', cat),
                    'templates': []
                }
            grouped[cat]['templates'].append(t)

        return Response({
            'templates': serializer.data,
            'grouped': list(grouped.values()),
            'count': len(templates)
        })
    except Exception as e:
        logger.error(f"Error listing email templates: {e}")
        return Response(
            {'error': 'Failed to list templates'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def email_template_create(request):
    """
    Create a new email template for the user's office.
    Requires MANAGE_EMAIL_TEMPLATES permission (scheduler+).
    """
    if not Permissions.has_permission(request.user, Permissions.MANAGE_EMAIL_TEMPLATES):
        return Response(
            {'error': 'You do not have permission to manage templates'},
            status=status.HTTP_403_FORBIDDEN
        )

    serializer = EmailTemplateSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(
            office=getattr(request.user, 'office', None),
            created_by=request.user,
            modified_by=request.user
        )
        security_logger.info(
            'Email template created',
            extra={
                'user': request.user.email,
                'template_id': str(serializer.instance.id),
                'template_name': serializer.instance.name,
            }
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def email_template_update(request, template_id):
    """
    Update an existing email template.
    Requires MANAGE_EMAIL_TEMPLATES permission (scheduler+).
    """
    if not Permissions.has_permission(request.user, Permissions.MANAGE_EMAIL_TEMPLATES):
        return Response(
            {'error': 'You do not have permission to manage templates'},
            status=status.HTTP_403_FORBIDDEN
        )

    template = get_object_or_404(EmailTemplate, id=template_id)

    # Scope check: can only edit own office templates or system defaults if admin
    office = getattr(request.user, 'office', None)
    if template.office and template.office != office:
        return Response(
            {'error': 'Cannot edit templates from another office'},
            status=status.HTTP_403_FORBIDDEN
        )

    partial = request.method == 'PATCH'
    serializer = EmailTemplateSerializer(template, data=request.data, partial=partial)
    if serializer.is_valid():
        serializer.save(modified_by=request.user)
        security_logger.info(
            'Email template updated',
            extra={
                'user': request.user.email,
                'template_id': str(template.id),
                'template_name': template.name,
            }
        )
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def email_template_delete(request, template_id):
    """
    Delete an email template (including system defaults).
    Requires MANAGE_EMAIL_TEMPLATES permission (scheduler+).
    """
    if not Permissions.has_permission(request.user, Permissions.MANAGE_EMAIL_TEMPLATES):
        return Response(
            {'error': 'You do not have permission to manage templates'},
            status=status.HTTP_403_FORBIDDEN
        )

    template = get_object_or_404(EmailTemplate, id=template_id)

    office = getattr(request.user, 'office', None)
    if template.office and template.office != office:
        return Response(
            {'error': 'Cannot delete templates from another office'},
            status=status.HTTP_403_FORBIDDEN
        )

    template_name = template.name
    template.delete()
    security_logger.info(
        'Email template deleted',
        extra={
            'user': request.user.email,
            'template_id': str(template_id),
            'template_name': template_name,
        }
    )
    return Response({'message': f'Template "{template_name}" deleted'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def send_email_response(request):
    """
    Send an email response. Accepts:
    - email_id: UUID of the EmailProcessing record
    - subject: Email subject
    - body: Email body (HTML or plain text)
    - is_html: Whether body is HTML (default True)
    - template_id: Optional template UUID used
    - cc_recipients: Optional list of CC addresses
    - bcc_recipients: Optional list of BCC addresses
    """
    email_id = request.data.get('email_id')
    if not email_id:
        return Response({'error': 'email_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    email_processing = get_object_or_404(EmailProcessing, id=email_id)
    user_email = request.user.email

    subject = request.data.get('subject', '')
    body = request.data.get('body', '')
    is_html = request.data.get('is_html', True)
    template_id = request.data.get('template_id')
    cc_recipients = request.data.get('cc_recipients', [])
    bcc_recipients = request.data.get('bcc_recipients', [])

    try:
        service = EmailResponseService(user_email=user_email)

        if template_id:
            template = get_object_or_404(EmailTemplate, id=template_id)
            response_obj = service.send_templated_response(
                email_processing=email_processing,
                template=template,
                context_data={'subject_override': subject, 'body_override': body},
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients
            )
        else:
            response_obj = service.create_custom_response(
                email_processing=email_processing,
                subject=subject,
                body=body,
                is_html=is_html,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients
            )

        return Response({
            'id': str(response_obj.id),
            'status': response_obj.status,
            'sent_at': response_obj.sent_at.isoformat() if response_obj.sent_at else None,
            'message': 'Response sent successfully' if response_obj.status == 'sent' else 'Response created'
        }, status=status.HTTP_201_CREATED)

    except EmailResponseError as e:
        logger.error(f"Failed to send email response: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        logger.error(f"Unexpected error sending email response: {e}")
        return Response(
            {'error': 'Failed to send response'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def email_response_history(request, email_id):
    """
    Get sent responses for an email, ordered chronologically.
    """
    email_processing = get_object_or_404(EmailProcessing, id=email_id)
    responses = EmailResponse.objects.filter(
        original_email=email_processing
    ).order_by('-sent_at', '-created')

    data = []
    for resp in responses:
        data.append({
            'id': str(resp.id),
            'subject': resp.subject,
            'body': resp.body,
            'is_html': resp.is_html,
            'status': resp.status,
            'sent_at': resp.sent_at.isoformat() if resp.sent_at else None,
            'created': resp.created.isoformat() if hasattr(resp, 'created') and resp.created else None,
            'sender': resp.sender,
            'recipient': resp.recipient,
            'template_name': resp.template_used.name if resp.template_used else None,
        })

    return Response({
        'responses': data,
        'count': len(data)
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def generate_email_draft(request):
    """
    Generate an AI email draft. Supports SSE streaming via stream=true parameter.

    Accepts:
    - email_id: UUID of the EmailProcessing record
    - event_id: Optional UUID of the related Event
    - template_id: Optional UUID of template to base draft on
    - refinement: Optional (shorter/more_formal/more_friendly/try_again)
    - previous_draft: Optional previous draft text for refinement
    - session_count: Number of drafts already generated in this session
    - stream: Boolean, if true returns SSE stream
    """
    from apps.email_processing.draft_generation_service import DraftGenerationService, DraftLimitExceeded

    email_id = request.data.get('email_id')
    if not email_id:
        return Response({'error': 'email_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    event_id = request.data.get('event_id')
    template_id = request.data.get('template_id')
    refinement = request.data.get('refinement')
    previous_draft = request.data.get('previous_draft')
    session_count = int(request.data.get('session_count', 0))
    use_stream = request.data.get('stream', False)
    user_prompt = request.data.get('user_prompt')

    service = DraftGenerationService()

    try:
        if use_stream:
            def event_stream():
                try:
                    for chunk in service.generate_draft_stream(
                        email_processing_id=email_id,
                        event_id=event_id,
                        template_id=template_id,
                        refinement=refinement,
                        previous_draft=previous_draft,
                        session_count=session_count,
                        user=request.user,
                        user_prompt=user_prompt,
                    ):
                        yield f"data: {json_module.dumps({'text': chunk})}\n\n"
                    yield f"data: {json_module.dumps({'done': True})}\n\n"
                except DraftLimitExceeded as e:
                    yield f"data: {json_module.dumps({'error': str(e)})}\n\n"
                except Exception as e:
                    logger.error(f"Streaming draft generation error: {e}")
                    yield f"data: {json_module.dumps({'error': 'Draft generation failed'})}\n\n"

            response = StreamingHttpResponse(
                event_stream(),
                content_type='text/event-stream'
            )
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        else:
            result = service.generate_draft(
                email_processing_id=email_id,
                event_id=event_id,
                template_id=template_id,
                refinement=refinement,
                previous_draft=previous_draft,
                session_count=session_count,
                user=request.user,
                user_prompt=user_prompt,
            )
            return Response(result.to_dict())

    except DraftLimitExceeded as e:
        return Response({'error': str(e)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    except Exception as e:
        logger.error(f"Draft generation error: {e}")
        return Response(
            {'error': 'Draft generation failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =====================================================================
# Filter Preset Endpoints
# =====================================================================

def _serialize_filter_preset(preset):
    """Serialize a UserFilterPreset to a plain dict for the API."""
    return {
        'id': preset.id,
        'name': preset.name,
        'data': preset.data or {},
        'is_default': preset.is_default,
    }


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def filter_presets(request):
    """
    GET  -> list the user's named filter presets (user-level, not office-level).
    POST -> create a new preset, or update the existing one with the same name.
            Body: {"name": str, "data": object, "is_default": bool?}
            Setting is_default=True clears the flag on the user's other presets.
    """
    if request.method == 'GET':
        presets = request.user.filter_presets.all()
        return Response([_serialize_filter_preset(p) for p in presets])

    # POST: create or upsert by name
    name = (request.data.get('name') or '').strip()
    data = request.data.get('data')
    is_default = bool(request.data.get('is_default', False))

    if not name:
        return Response(
            {'error': 'A preset name is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    if not isinstance(data, dict):
        return Response(
            {'error': 'Preset data must be a JSON object'},
            status=status.HTTP_400_BAD_REQUEST
        )

    preset, _created = UserFilterPreset.objects.update_or_create(
        user=request.user,
        name=name,
        defaults={'data': data, 'is_default': is_default},
    )

    # Only one default per user
    if is_default:
        request.user.filter_presets.exclude(pk=preset.pk).filter(
            is_default=True
        ).update(is_default=False)

    return Response(
        _serialize_filter_preset(preset),
        status=status.HTTP_201_CREATED if _created else status.HTTP_200_OK,
    )


@api_view(['PATCH', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def filter_preset_detail(request, preset_id):
    """
    PATCH  -> update a preset. Body may include name/data/is_default.
              Setting is_default=True clears it on the user's other presets;
              False clears it on this one (no default).
    DELETE -> remove the preset.
    """
    try:
        preset = request.user.filter_presets.get(pk=preset_id)
    except UserFilterPreset.DoesNotExist:
        return Response(
            {'error': 'Preset not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'DELETE':
        preset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH
    update_fields = []
    if 'name' in request.data:
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response(
                {'error': 'A preset name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        preset.name = name
        update_fields.append('name')
    if 'data' in request.data:
        data = request.data.get('data')
        if not isinstance(data, dict):
            return Response(
                {'error': 'Preset data must be a JSON object'},
                status=status.HTTP_400_BAD_REQUEST
            )
        preset.data = data
        update_fields.append('data')
    if 'is_default' in request.data:
        preset.is_default = bool(request.data.get('is_default'))
        update_fields.append('is_default')

    if update_fields:
        preset.save(update_fields=update_fields + ['modified'])

    if preset.is_default:
        request.user.filter_presets.exclude(pk=preset.pk).filter(
            is_default=True
        ).update(is_default=False)

    return Response(_serialize_filter_preset(preset))


# =====================================================================
# Routing Preset Endpoints
# =====================================================================

def _serialize_routing_preset(preset):
    """Serialize a UserRoutingPreset to a plain dict for the API."""
    return {
        'id': preset.id,
        'name': preset.name,
        'data': preset.data or {},
        'is_default': preset.is_default,
    }


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def routing_presets(request):
    """
    GET  -> list the user's named approval-routing presets (user-level).
    POST -> create a new preset, or update the existing one with the same name.
            Body: {"name": str, "data": object, "is_default": bool?}
            Setting is_default=True clears the flag on the user's other presets.
    """
    if request.method == 'GET':
        presets = request.user.routing_presets.all()
        return Response([_serialize_routing_preset(p) for p in presets])

    # POST: create or upsert by name
    name = (request.data.get('name') or '').strip()
    data = request.data.get('data')
    is_default = bool(request.data.get('is_default', False))

    if not name:
        return Response(
            {'error': 'A preset name is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    if not isinstance(data, dict):
        return Response(
            {'error': 'Preset data must be a JSON object'},
            status=status.HTTP_400_BAD_REQUEST
        )

    preset, _created = UserRoutingPreset.objects.update_or_create(
        user=request.user,
        name=name,
        defaults={'data': data, 'is_default': is_default},
    )

    # Only one default per user
    if is_default:
        request.user.routing_presets.exclude(pk=preset.pk).filter(
            is_default=True
        ).update(is_default=False)

    return Response(
        _serialize_routing_preset(preset),
        status=status.HTTP_201_CREATED if _created else status.HTTP_200_OK,
    )


@api_view(['PATCH', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def routing_preset_detail(request, preset_id):
    """
    PATCH  -> update a preset. Body may include name/data/is_default.
              Setting is_default=True clears it on the user's other presets.
    DELETE -> remove the preset.
    """
    try:
        preset = request.user.routing_presets.get(pk=preset_id)
    except UserRoutingPreset.DoesNotExist:
        return Response(
            {'error': 'Preset not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'DELETE':
        preset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH
    update_fields = []
    if 'name' in request.data:
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response(
                {'error': 'A preset name is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        preset.name = name
        update_fields.append('name')
    if 'data' in request.data:
        data = request.data.get('data')
        if not isinstance(data, dict):
            return Response(
                {'error': 'Preset data must be a JSON object'},
                status=status.HTTP_400_BAD_REQUEST
            )
        preset.data = data
        update_fields.append('data')
    if 'is_default' in request.data:
        preset.is_default = bool(request.data.get('is_default'))
        update_fields.append('is_default')

    if update_fields:
        preset.save(update_fields=update_fields + ['modified'])

    if preset.is_default:
        request.user.routing_presets.exclude(pk=preset.pk).filter(
            is_default=True
        ).update(is_default=False)

    return Response(_serialize_routing_preset(preset))


# =====================================================================
# Export Endpoints
# =====================================================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_templates_list(request):
    """
    List export templates available to the user's office.
    Returns system defaults plus any office-uploaded custom templates.
    """
    try:
        office = getattr(request.user, 'office', None)

        # Built-in defaults + office-specific
        templates = ExportTemplate.objects.filter(
            Q(is_default=True) | Q(office=office)
        ).order_by('template_type', 'name')

        serializer = ExportTemplateSerializer(templates, many=True)

        # Group by template_type for frontend convenience
        grouped = {}
        for t in serializer.data:
            ttype = t['template_type']
            if ttype not in grouped:
                grouped[ttype] = {
                    'template_type': ttype,
                    'template_type_display': t.get('template_type_display', ttype),
                    'templates': [],
                }
            grouped[ttype]['templates'].append(t)

        return Response({
            'templates': serializer.data,
            'grouped': list(grouped.values()),
            'count': len(templates),
        })
    except Exception as e:
        logger.error(f'Error listing export templates: {e}')
        return Response(
            {'error': 'Failed to list export templates'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def export_template_upload(request):
    """
    Upload a custom .docx export template for the user's office.
    Requires MANAGE_EXPORT_TEMPLATES permission (admin/scheduler).

    Accepts multipart form data with:
    - file: .docx file
    - name: Template display name
    - template_type: One of daily_briefing, weekly_overview, event_detail, filtered_list, custom
    """
    if not Permissions.has_permission(request.user, Permissions.MANAGE_EXPORT_TEMPLATES):
        return Response(
            {'error': 'You do not have permission to manage export templates'},
            status=status.HTTP_403_FORBIDDEN,
        )

    docx_file = request.FILES.get('file')
    if not docx_file:
        return Response(
            {'error': 'No file uploaded. Send a .docx file as "file".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Size check
    max_size = getattr(settings, 'EXPORT_TEMPLATE_MAX_SIZE', 5 * 1024 * 1024)
    if docx_file.size > max_size:
        return Response(
            {'error': f'File too large. Maximum size is {max_size // (1024 * 1024)}MB.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Extension check
    if not docx_file.name.endswith('.docx'):
        return Response(
            {'error': 'Only .docx files are accepted.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate template renders correctly
    from apps.event_management.services.export_service import ExportService
    service = ExportService()
    validation = service.validate_template(docx_file)
    if not validation['valid']:
        return Response(
            {'error': 'Template validation failed', 'details': validation['errors']},
            status=status.HTTP_400_BAD_REQUEST,
        )

    name = request.data.get('name', docx_file.name.replace('.docx', ''))
    template_type = request.data.get('template_type', 'custom')

    valid_types = [c[0] for c in ExportTemplate.TEMPLATE_TYPE_CHOICES]
    if template_type not in valid_types:
        return Response(
            {'error': f'Invalid template_type. Must be one of: {", ".join(valid_types)}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    office = getattr(request.user, 'office', None)

    # One template per type: replace any existing office upload of this type.
    ExportTemplate.objects.filter(
        office=office,
        template_type=template_type,
        is_default=False,
    ).delete()

    template = ExportTemplate.objects.create(
        name=name,
        template_type=template_type,
        docx_file=docx_file,
        office=office,
        is_default=False,
        created_by=request.user,
        modified_by=request.user,
    )

    security_logger.info(
        'Export template uploaded',
        extra={
            'user': request.user.email,
            'template_id': str(template.id),
            'template_name': name,
        },
    )

    serializer = ExportTemplateSerializer(template)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def export_template_delete(request, template_id):
    """
    Delete an export template — a custom office upload or a built-in default.
    Once the last template for a type is gone, exports of that type prompt the
    user to upload one first.
    Requires MANAGE_EXPORT_TEMPLATES permission (admin/scheduler).
    """
    if not Permissions.has_permission(request.user, Permissions.MANAGE_EXPORT_TEMPLATES):
        return Response(
            {'error': 'You do not have permission to manage export templates'},
            status=status.HTTP_403_FORBIDDEN,
        )

    template = get_object_or_404(ExportTemplate, id=template_id)

    office = getattr(request.user, 'office', None)
    if template.office and template.office != office:
        return Response(
            {'error': 'Cannot delete templates from another office'},
            status=status.HTTP_403_FORBIDDEN,
        )

    template_name = template.name
    template.delete()

    security_logger.info(
        'Export template deleted',
        extra={
            'user': request.user.email,
            'template_id': str(template_id),
            'template_name': template_name,
        },
    )
    return Response({'message': f'Template "{template_name}" deleted'})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_template_download(request, template_id):
    """
    Download the .docx for an export template — a built-in default or one of
    the user's office templates. Lets users grab a built-in as a starting point
    for customization.
    """
    from django.http import FileResponse

    template = get_object_or_404(ExportTemplate, id=template_id)

    # Built-ins are downloadable by anyone; office templates only by that office.
    office = getattr(request.user, 'office', None)
    if not template.is_default and template.office and template.office != office:
        return Response(
            {'error': 'Cannot download templates from another office'},
            status=status.HTTP_403_FORBIDDEN,
        )

    from apps.event_management.services.export_service import ExportService
    try:
        path = ExportService().get_template_path(template)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f'Export template download failed for {template_id}: {e}')
        return Response(
            {'error': 'Template file is unavailable.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    download_name = f'{template.name}.docx' if not template.name.endswith('.docx') else template.name
    response = FileResponse(
        open(path, 'rb'),
        as_attachment=True,
        filename=download_name,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    return response


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def export_events_docx(request):
    """
    Generate a .docx export of events.

    Accepts JSON body:
    - template_type: daily_briefing | weekly_overview | event_detail | filtered_list
    - event_ids: list of Event UUIDs (optional — defaults to filtered queryset)
    - template_id: specific ExportTemplate UUID (optional)
    - date: ISO date string for daily/weekly (optional, defaults to today)
    - active_filters: list of human-readable filter descriptions (optional)
    - status_filter, type_filter, search: query params for building queryset

    Returns .docx file directly if <= EXPORT_MAX_SYNC_EVENTS events,
    otherwise returns 202 with a Celery task_id for async polling.
    """
    from django.http import HttpResponse
    from apps.event_management.services.export_service import ExportService

    if not Permissions.has_permission(request.user, Permissions.EXPORT_EVENTS):
        return Response(
            {'error': 'You do not have permission to export events'},
            status=status.HTTP_403_FORBIDDEN
        )

    template_type = request.data.get('template_type', 'daily_briefing')
    event_ids = request.data.get('event_ids')
    template_id = request.data.get('template_id')
    target_date_str = request.data.get('date')
    active_filters = request.data.get('active_filters')

    office = getattr(request.user, 'office', None)

    # No template for this export type (e.g. the built-in was deleted and the
    # office hasn't uploaded its own) — prompt to upload rather than 500.
    service = ExportService()
    if not service.resolve_template(template_type, office, template_id):
        return Response(
            {'error': 'Upload a template for this export type first.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Build queryset
    if event_ids:
        queryset = Event.objects.filter(id__in=event_ids)
    else:
        queryset = Event.objects.filter(is_archived=False)
        # Apply basic filters from request
        status_filter = request.data.get('status_filter')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        type_filter = request.data.get('type_filter')
        if type_filter:
            queryset = queryset.filter(type=type_filter)
        search = request.data.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search)
            )
        # Date filter for daily briefing
        if target_date_str and template_type == 'daily_briefing':
            from datetime import date as date_type
            try:
                target = date_type.fromisoformat(target_date_str)
                queryset = queryset.filter(start_date=target)
            except ValueError:
                pass

    queryset = queryset.order_by('start_date', 'start_time')

    # Parse target date
    target_date = None
    if target_date_str:
        from datetime import date as date_type
        try:
            target_date = date_type.fromisoformat(target_date_str)
        except ValueError:
            pass

    # Sync vs async threshold
    max_sync = getattr(settings, 'EXPORT_MAX_SYNC_EVENTS', 200)
    count = queryset.count()

    if count > max_sync:
        from apps.event_management.tasks import generate_export_async
        task = generate_export_async.delay(
            template_type=template_type,
            event_ids=[str(e.id) for e in queryset],
            office_id=str(office.id) if office else None,
            template_id=template_id,
            target_date=target_date_str,
            active_filters=active_filters,
        )
        return Response(
            {'task_id': task.id, 'status': 'processing', 'event_count': count},
            status=status.HTTP_202_ACCEPTED,
        )

    # Synchronous render
    try:
        service = ExportService()
        docx_bytes = service.render_docx(
            template_type=template_type,
            queryset=queryset,
            office=office,
            template_id=template_id,
            target_date=target_date,
            active_filters=active_filters,
        )

        filename = f'{template_type}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.docx'
        response = HttpResponse(
            docx_bytes,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except FileNotFoundError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    except Exception as e:
        logger.error(f'Export generation failed: {e}', exc_info=True)
        return Response(
            {'error': 'Export generation failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_status(request, task_id):
    """
    Poll the status of an async export Celery task.
    Returns the file download URL when complete.
    """
    from celery.result import AsyncResult

    result = AsyncResult(task_id)

    if result.ready():
        if result.successful():
            data = result.result
            return Response({
                'status': 'complete',
                'file_path': data.get('file_path', ''),
                'download_url': f'{settings.MEDIA_URL}{data.get("file_path", "")}',
            })
        else:
            return Response(
                {'status': 'failed', 'error': str(result.result)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    else:
        return Response({'status': 'processing', 'state': result.state})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_events_csv(request):
    """
    Export events as CSV. Uses the same filter query params as the events list.

    Query params:
    - status: Filter by status
    - type: Filter by type
    - search: Free text search
    - start_date / end_date: Date range
    - include_notes: Include notes column (default true)
    - include_description: Include description column (default true)
    """
    from django.http import HttpResponse
    from apps.event_management.services.export_service import ExportService

    if not Permissions.has_permission(request.user, Permissions.EXPORT_EVENTS):
        return Response(
            {'error': 'You do not have permission to export events'},
            status=status.HTTP_403_FORBIDDEN
        )

    # Only export events the user is allowed to view.
    queryset = Permissions.scope_events_queryset(
        request.user, Event.objects.filter(is_archived=False)
    )

    # Apply filters
    status_filter = request.query_params.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    type_filter = request.query_params.get('type')
    if type_filter:
        queryset = queryset.filter(type=type_filter)

    search = request.query_params.get('search')
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search) |
            Q(group__icontains=search) |
            Q(description__icontains=search)
        )

    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    if start_date:
        queryset = queryset.filter(start_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(start_date__lte=end_date)

    queryset = queryset.order_by('start_date', 'start_time')

    include_notes = request.query_params.get('include_notes', 'true').lower() != 'false'
    include_description = request.query_params.get('include_description', 'true').lower() != 'false'

    try:
        service = ExportService()
        csv_content = service.render_csv(
            queryset,
            include_notes=include_notes,
            include_description=include_description,
        )

        filename = f'events_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
        response = HttpResponse(csv_content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f'CSV export failed: {e}', exc_info=True)
        return Response(
            {'error': 'CSV export failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =============================================================================
# TEMPORARY: Demo reset endpoint.
# Wired to the "Reset Demo" button in the DEMO tab of Settings. Spawns the two
# standalone scripts at scripts/create_demo_office.py and
# scripts/populate_office_demo_info.py via subprocess. Remove this endpoint
# (and the matching URL + JS handler) once the DEMO tab is taken out.
# =============================================================================
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_protect
def reset_demo(request):
    """Reset the demo office and seed data by running the two demo scripts.

    Development only: the scripts wipe every office, user and event, so the
    endpoint doesn't exist (404) unless DEBUG=True.
    """
    if not settings.DEBUG:
        from django.http import Http404
        raise Http404()
    if getattr(request.user, 'role', None) != 'admin':
        return Response(
            {'error': 'Only admins can reset the demo.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    import subprocess
    import sys as _sys
    from pathlib import Path

    project_root = Path(settings.BASE_DIR)
    scripts_dir = project_root / 'scripts'
    scripts = [
        scripts_dir / 'create_demo_office.py',
        scripts_dir / 'populate_office_demo_info.py',
    ]

    for script in scripts:
        if not script.exists():
            return Response(
                {'error': f'Demo script missing: {script.name}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    try:
        for script in scripts:
            result = subprocess.run(
                [_sys.executable, str(script)],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0:
                logger.error(
                    f'Demo reset script {script.name} failed (rc={result.returncode}).\n'
                    f'stderr tail: {result.stderr[-2000:]}'
                )
                return Response(
                    {
                        'error': f'{script.name} failed',
                        'stderr': result.stderr[-2000:],
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
    except subprocess.TimeoutExpired:
        return Response(
            {'error': 'Demo reset timed out.'},
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except Exception as e:
        logger.error(f'Demo reset failed: {e}', exc_info=True)
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    security_logger.info(f'Demo reset triggered by {request.user.username}')
    return Response({
        'success': True,
        'message': 'Demo reset complete. Office, users, templates, and 55 events restored.',
    })


# =============================================================================
# Event Attachment endpoints
# =============================================================================

def _client_ip(request):
    """Best-effort client IP for audit logging."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def event_attachments(request, event_id):
    """
    List attachments for an event (GET) or upload a new file (POST).

    Upload accepts multipart form data:
    - file: the file to attach (required)
    - data_classification: one of the configured levels (optional)

    Uploading is restricted to users who can edit the event. Each upload creates
    a new EventAttachment (and its first version). To replace an existing
    attachment's file, POST to the replace endpoint instead.
    """
    from apps.event_management.models import EventAttachment, EventAttachmentVersion
    from apps.event_management.services.attachment_scan_service import (
        scan_file, AttachmentScanError,
    )
    from .serializers import EventAttachmentSerializer

    event = get_object_or_404(Event, id=event_id)

    if request.method == 'GET':
        if not Permissions.can_view_events(request.user):
            return Response(
                {'error': 'You do not have permission to view this event'},
                status=status.HTTP_403_FORBIDDEN,
            )
        attachments = event.attachments.prefetch_related('versions').all()
        serializer = EventAttachmentSerializer(
            attachments, many=True, context={'request': request}
        )
        return Response({'attachments': serializer.data})

    # POST — upload
    if not Permissions.can_edit_event(request.user, event):
        return Response(
            {'error': 'You do not have permission to add attachments to this event'},
            status=status.HTTP_403_FORBIDDEN,
        )

    upload = request.FILES.get('file')
    if not upload:
        return Response(
            {'error': 'No file uploaded. Send the file as "file".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    error = _validate_attachment_upload(upload)
    if error:
        return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

    classification = request.data.get('data_classification', 'confidential')
    valid_levels = [c[0] for c in settings.DATA_CLASSIFICATION_LEVELS]
    if classification not in valid_levels:
        classification = 'confidential'

    try:
        scan_status = scan_file(upload)
    except AttachmentScanError as e:
        logger.error(f'Attachment scan unavailable: {e}')
        return Response(
            {'error': 'File scanning is unavailable; upload rejected.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if scan_status == 'infected':
        security_logger.warning(
            'Infected attachment upload rejected',
            extra={'user': request.user.email, 'event_id': str(event_id),
                   'file_name': upload.name, 'ip': _client_ip(request)},
        )
        return Response(
            {'error': 'The uploaded file failed a malware scan and was rejected.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    attachment = EventAttachment.objects.create(
        event=event,
        original_filename=upload.name[:255],
        data_classification=classification,
        source='upload',
        created_by=request.user,
    )
    version = EventAttachmentVersion(
        attachment=attachment,
        content_type=getattr(upload, 'content_type', '') or '',
        file_size=upload.size,
        version_number=1,
        scan_status=scan_status,
        uploaded_by=request.user,
    )
    # Store under a UUID-based name so the untrusted filename never hits storage.
    version.file.save(_safe_stored_name(upload.name, version.id), upload, save=False)
    version.save()

    security_logger.info(
        'Event attachment uploaded',
        extra={'user': request.user.email, 'event_id': str(event_id),
               'attachment_id': str(attachment.id), 'file_name': upload.name,
               'size': upload.size, 'ip': _client_ip(request)},
    )

    serializer = EventAttachmentSerializer(attachment, context={'request': request})
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def event_attachment_replace(request, event_id, attachment_id):
    """
    Upload a new version of an existing attachment, preserving prior versions.

    Restricted to users who can edit the event. Accepts multipart `file`.
    """
    from apps.event_management.models import EventAttachment, EventAttachmentVersion
    from apps.event_management.services.attachment_scan_service import (
        scan_file, AttachmentScanError,
    )
    from .serializers import EventAttachmentSerializer

    event = get_object_or_404(Event, id=event_id)
    attachment = get_object_or_404(EventAttachment, id=attachment_id, event=event)

    if not Permissions.can_edit_event(request.user, event):
        return Response(
            {'error': 'You do not have permission to modify attachments on this event'},
            status=status.HTTP_403_FORBIDDEN,
        )

    upload = request.FILES.get('file')
    if not upload:
        return Response(
            {'error': 'No file uploaded. Send the file as "file".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    error = _validate_attachment_upload(upload)
    if error:
        return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

    try:
        scan_status = scan_file(upload)
    except AttachmentScanError as e:
        logger.error(f'Attachment scan unavailable: {e}')
        return Response(
            {'error': 'File scanning is unavailable; upload rejected.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if scan_status == 'infected':
        security_logger.warning(
            'Infected attachment upload rejected',
            extra={'user': request.user.email, 'event_id': str(event_id),
                   'file_name': upload.name, 'ip': _client_ip(request)},
        )
        return Response(
            {'error': 'The uploaded file failed a malware scan and was rejected.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    last = attachment.versions.order_by('-version_number').first()
    next_number = (last.version_number + 1) if last else 1

    version = EventAttachmentVersion(
        attachment=attachment,
        content_type=getattr(upload, 'content_type', '') or '',
        file_size=upload.size,
        version_number=next_number,
        scan_status=scan_status,
        uploaded_by=request.user,
    )
    version.file.save(_safe_stored_name(upload.name, version.id), upload, save=False)
    version.save()

    attachment.original_filename = upload.name[:255]
    attachment.save(update_fields=['original_filename', 'modified'])

    security_logger.info(
        'Event attachment replaced',
        extra={'user': request.user.email, 'event_id': str(event_id),
               'attachment_id': str(attachment.id), 'version': next_number,
               'file_name': upload.name, 'ip': _client_ip(request)},
    )

    serializer = EventAttachmentSerializer(attachment, context={'request': request})
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def event_attachment_download(request, event_id, attachment_id, version_id):
    """
    Stream an attachment version back through the application.

    Files are NEVER served from a public/MEDIA URL or presigned S3 link — both
    bypass authorization and break the no-public-egress constraint. Access
    requires view access to the event; downloads are blocked for versions that
    have not passed (or skipped) malware scanning.
    """
    from django.http import FileResponse
    from apps.event_management.models import EventAttachment, EventAttachmentVersion

    event = get_object_or_404(Event, id=event_id)

    if not Permissions.can_view_events(request.user):
        return Response(
            {'error': 'You do not have permission to download this file'},
            status=status.HTTP_403_FORBIDDEN,
        )

    attachment = get_object_or_404(EventAttachment, id=attachment_id, event=event)
    version = get_object_or_404(EventAttachmentVersion, id=version_id, attachment=attachment)

    if not version.is_downloadable:
        return Response(
            {'error': 'This file has not cleared malware scanning yet.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    security_logger.info(
        'Event attachment downloaded',
        extra={'user': request.user.email, 'event_id': str(event_id),
               'attachment_id': str(attachment.id), 'version': version.version_number,
               'ip': _client_ip(request)},
    )

    response = FileResponse(
        version.file.open('rb'),
        as_attachment=True,
        filename=attachment.original_filename,
    )
    if version.content_type:
        response['Content-Type'] = version.content_type
    return response


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def event_attachment_delete(request, event_id, attachment_id):
    """
    Delete an attachment and all its versions (and their stored files).

    Restricted to users who can edit the event. File blobs are removed by the
    post_delete signal on EventAttachmentVersion.
    """
    from apps.event_management.models import EventAttachment

    event = get_object_or_404(Event, id=event_id)
    attachment = get_object_or_404(EventAttachment, id=attachment_id, event=event)

    if not Permissions.can_edit_event(request.user, event):
        return Response(
            {'error': 'You do not have permission to delete attachments on this event'},
            status=status.HTTP_403_FORBIDDEN,
        )

    filename = attachment.original_filename
    attachment.delete()

    security_logger.info(
        'Event attachment deleted',
        extra={'user': request.user.email, 'event_id': str(event_id),
               'attachment_id': str(attachment_id), 'file_name': filename,
               'ip': _client_ip(request)},
    )
    return Response({'message': f'Attachment "{filename}" deleted'})


def _validate_attachment_upload(upload):
    """Return an error string if the upload violates size/extension rules, else None."""
    import os

    max_size = getattr(settings, 'EVENT_ATTACHMENT_MAX_SIZE', 10 * 1024 * 1024)
    if upload.size > max_size:
        return f'File too large. Maximum size is {max_size // (1024 * 1024)}MB.'

    allowed = getattr(settings, 'EVENT_ATTACHMENT_ALLOWED_EXTENSIONS', [])
    ext = os.path.splitext(upload.name)[1].lower()
    if allowed and ext not in allowed:
        return f'File type "{ext or "unknown"}" is not allowed. Allowed: {", ".join(allowed)}.'
    return None


def _safe_stored_name(original_name, version_id):
    """Build a UUID-based storage filename that preserves the original extension."""
    import os
    ext = os.path.splitext(original_name)[1].lower()
    return f'{version_id}{ext}'

# =============================================================================
# Email ingestion review surfaces (spec §10)
# =============================================================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def change_suggestions_feed(request):
    """
    The inbox's third feed (ingestion spec §10.2): pending change suggestions
    grouped per source candidate, so a multi-field reschedule renders as ONE
    card with a field-level diff.

    Query params:
    - origin: suggestion origin (default 'email_ingestion')
    - status: suggestion status (default 'pending')
    """
    try:
        if not Permissions.has_permission(request.user, Permissions.PROCESS_INBOX):
            return Response(
                {'error': 'You do not have permission to process inbox items'},
                status=status.HTTP_403_FORBIDDEN
            )

        origin = request.query_params.get('origin', 'email_ingestion')
        suggestion_status = request.query_params.get('status', 'pending')

        base = (EventChangeSuggestion.objects
                .filter(origin=origin, status=suggestion_status))
        # Keep a candidate-group whole while ANY of its rows is still pending:
        # the review panel shows resolved rows (with Revert) next to open ones.
        candidate_ids = [c for c in base.values_list('source_candidate_id', flat=True) if c]
        suggestions = (EventChangeSuggestion.objects
                       .filter(Q(pk__in=base.values('pk'))
                               | Q(origin=origin, source_candidate_id__in=candidate_ids))
                       .select_related('event', 'source_candidate')
                       .order_by('-suggested_at'))

        groups = {}
        for suggestion in suggestions:
            key = str(suggestion.source_candidate_id or suggestion.id)
            group = groups.get(key)
            if group is None:
                candidate = suggestion.source_candidate
                verbatim = {}
                intent = 'RESCHEDULE'
                if candidate is not None:
                    verbatim = (candidate.payload or {}).get('verbatim') or {}
                    intent = candidate.intent
                elif suggestion.field_name == 'status':
                    intent = 'CANCELLATION'
                group = groups[key] = {
                    'candidate_id': str(candidate.id) if candidate else None,
                    'intent': intent,
                    'origin': suggestion.origin,
                    'created_at': suggestion.suggested_at.isoformat(),
                    'reason': suggestion.reason,
                    'verbatim': verbatim,
                    'event': {
                        'id': str(suggestion.event.id),
                        'title': suggestion.event.title,
                        'start_date': (suggestion.event.start_date.isoformat()
                                       if suggestion.event.start_date else None),
                        'start_time': (suggestion.event.start_time.isoformat()
                                       if suggestion.event.start_time else None),
                        'status': suggestion.event.status,
                    },
                    'suggestions': [],
                }
            group['suggestions'].append({
                'id': str(suggestion.id),
                'field_name': suggestion.field_name,
                'current_value': suggestion.current_value,
                'suggested_value': suggestion.suggested_value,
                'status': suggestion.status,
            })

        results = sorted(groups.values(), key=lambda g: g['created_at'], reverse=True)
        return Response({'results': results, 'count': len(results)})

    except Exception as e:
        logger.error(f"Error building change-suggestions feed: {e}")
        return Response({'error': 'Failed to load change suggestions'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _apply_series_end_bound(series, data) -> None:
    """Apply a reviewer-chosen end bound to ``series`` (not saved).

    The recurrence UI offers "ends on <date>" OR "after <n> occurrences".
    Whichever is sent replaces the other, so a count the model extracted can't
    silently override a reviewer-chosen end date (count wins in build_rrule).
    """
    from datetime import date as date_type

    until_raw = data.get('until_date')
    count_raw = data.get('count')
    if until_raw:
        series.until_date = date_type.fromisoformat(str(until_raw))
        if not count_raw:
            series.count = None
    if count_raw:
        count_value = int(count_raw)
        if count_value < 1:
            raise ValueError('count must be at least 1')
        series.count = count_value
        if not until_raw:
            series.until_date = None


@api_view(['POST', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def event_series(request, event_id):
    """
    Make an event recurring from the event editing modal's "Repeats" section.

    POST {rrule, until_date | count}: create (or update the pending) series
    anchored at the event's start date/time, with the event as its first
    occurrence, then activate it — materializing the occurrences. An end
    bound is required (no open-ended series).

    DELETE: discard a PENDING (inactive) series — e.g. the model flagged a
    one-off as recurring. Active series are never deleted here.

    Both are refused while the event still needs human review: the recurrence
    is only confirmed after the extracted fields are approved.
    """
    try:
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.db import transaction

        from apps.event_management.models import EventSeries

        event = get_object_or_404(
            Permissions.scope_events_queryset(request.user, Event.objects.all()), id=event_id)
        if not Permissions.can_edit_event(request.user, event):
            return Response({'error': 'You do not have permission to edit this event'},
                            status=status.HTTP_403_FORBIDDEN)
        if event.requires_human_review:
            return Response({'error': 'Complete human review first'},
                            status=status.HTTP_400_BAD_REQUEST)

        series = event.series
        if series is not None and series.is_active:
            return Response({'error': 'This event is already part of an active series'},
                            status=status.HTTP_400_BAD_REQUEST)

        if request.method == 'DELETE':
            if series is None:
                return Response({'success': True, 'deleted': False})
            series_pk = str(series.id)
            with transaction.atomic():
                event.series = None
                event.series_occurrence_date = None
                event.save(update_fields=['series', 'series_occurrence_date', 'modified'])
                # Only drop the rule if no other event still points at it.
                if not series.events.exists():
                    series.delete()
            security_logger.info(
                'Pending event series discarded',
                extra={'user_id': request.user.id, 'event_id': str(event.id),
                       'series_id': series_pk},
            )
            return Response({'success': True, 'deleted': True})

        rrule = str(request.data.get('rrule') or '').strip()[:500]
        if not rrule:
            return Response({'error': 'rrule is required'}, status=status.HTTP_400_BAD_REQUEST)
        if event.start_date is None:
            return Response({'error': 'Set a start date before making the event repeat'},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            if series is None:
                series = EventSeries(created_by=request.user)
            series.rrule = rrule
            series.dtstart_date = event.start_date
            series.dtstart_time = event.start_time
            series.timezone = event.timezone or series.timezone
            series.title_template = event.title or ''
            _apply_series_end_bound(series, request.data)
            if not (series.until_date or series.count):
                return Response(
                    {'error': 'An end bound is required: set until_date or count'},
                    status=status.HTTP_400_BAD_REQUEST)
            series.save()

            # The event is the series' first occurrence.
            event.series = series
            event.series_occurrence_date = event.start_date
            event.save(update_fields=['series', 'series_occurrence_date', 'modified'])

            created = series.activate(reviewer=request.user)

        security_logger.info(
            'Event series created from editor',
            extra={'user_id': request.user.id, 'event_id': str(event.id),
                   'series_id': str(series.id), 'rrule': series.rrule,
                   'occurrences_created': len(created)},
        )
        return Response({
            'success': True,
            'series_id': str(series.id),
            'occurrences_created': len(created),
            'series': {
                'id': str(series.id),
                'rrule': series.rrule,
                'is_active': series.is_active,
                'until_date': series.until_date.isoformat() if series.until_date else None,
                'count': series.count,
            },
        })

    except (ValueError, DjangoValidationError) as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error saving series for event {event_id}: {e}")
        return Response({'error': 'Failed to save the recurring series'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def activate_event_series(request, series_id):
    """
    Reviewer confirms a recurring candidate's rule (ingestion spec §9): the
    series activates and materializes occurrences ONLY when an end bound
    (until_date or count) is present — no open-ended series, enforced here and
    at the model level.

    POST body (all optional; merged onto the pending series):
    - rrule: edited RFC-5545 rule
    - until_date: ISO date end bound
    - count: integer occurrence count
    """
    try:
        from django.core.exceptions import ValidationError as DjangoValidationError

        from apps.event_management.models import EventSeries

        if not Permissions.has_permission(request.user, Permissions.PROCESS_INBOX):
            return Response(
                {'error': 'You do not have permission to process inbox items'},
                status=status.HTTP_403_FORBIDDEN
            )

        series = get_object_or_404(EventSeries, id=series_id)
        if series.is_active:
            return Response({'error': 'Series is already active'},
                            status=status.HTTP_400_BAD_REQUEST)

        if request.data.get('rrule'):
            series.rrule = str(request.data['rrule'])[:500]
        _apply_series_end_bound(series, request.data)

        if not (series.until_date or series.count):
            return Response(
                {'error': 'An end bound is required: set until_date or count'},
                status=status.HTTP_400_BAD_REQUEST
            )

        created = series.activate(reviewer=request.user)

        security_logger.info(
            'Event series activated',
            extra={'user_id': request.user.id, 'series_id': str(series.id),
                   'occurrences_created': len(created)},
        )
        return Response({
            'success': True,
            'series_id': str(series.id),
            'occurrences_created': len(created),
            'materialized_through': (series.materialized_through.isoformat()
                                     if series.materialized_through else None),
        })

    except (ValueError, DjangoValidationError) as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error activating series {series_id}: {e}")
        return Response({'error': 'Failed to activate series'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def block_sender(request):
    """
    Blocklist a sender (the accept side increments reputation silently; this
    is the junk-dismiss "block this sender" action — ingestion spec §10.7).

    POST body:
    - sender_email: address to block (required)
    - notes: optional reason
    """
    try:
        from apps.contacts.crypto import email_blind_index
        from apps.email_processing.models import SenderReputation

        if not Permissions.has_permission(request.user, Permissions.PROCESS_INBOX):
            return Response(
                {'error': 'You do not have permission to process inbox items'},
                status=status.HTTP_403_FORBIDDEN
            )

        sender_email = (request.data.get('sender_email') or '').strip()
        if not sender_email or '@' not in sender_email:
            return Response({'error': 'A valid sender_email is required'},
                            status=status.HTTP_400_BAD_REQUEST)

        rep = SenderReputation.objects.filter(
            sender_key=email_blind_index(sender_email)).first()
        if rep is None:
            rep = SenderReputation(sender_email=sender_email)
        rep.list = 'block'
        rep.added_by = request.user
        if request.data.get('notes'):
            rep.notes = str(request.data['notes'])[:500]
        rep.save()

        security_logger.info(
            'Sender blocklisted',
            extra={'user_id': request.user.id, 'timestamp': timezone.now().isoformat()},
        )
        return Response({'success': True, 'list': rep.list})

    except Exception as e:
        logger.error(f"Error blocking sender: {e}")
        return Response({'error': 'Failed to block sender'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
