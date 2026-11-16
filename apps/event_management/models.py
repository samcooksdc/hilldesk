# SPDX-License-Identifier: Apache-2.0
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
import uuid

User = get_user_model()


class Event(models.Model):
    """
    Event model for HillDesk.
    Stores all event information with comprehensive metadata and audit trails.
    """
    
    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic event information
    title = models.CharField(
        max_length=200,
        default="",
        blank=True,
        help_text="Event title"
    )
    
    type = models.CharField(
        max_length=20,
        blank=True,
        help_text="Type of event: Event, Meeting, or Speaking engagement"
    )
    
    format = models.CharField(
        max_length=20,
        blank=True,
        help_text="Event format: in-person, virtual, or hybrid"
    )
    
    duration = models.CharField(
        max_length=20,
        blank=True,
        help_text="Event duration"
    )
    
    # NOTE: `group` and `point_of_contact_*` were denormalized columns. They are
    # now read-only properties (see below) derived from the normalized
    # Contact / Organization models via the EventContact / EventOrganization
    # through tables. Writes go through apps.contacts.services.

    description = models.TextField(
        default="",
        blank=True,
        help_text="Event description"
    )
    
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Event tags for categorization"
    )
    
    # Timing information (separated date and time)
    start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Start date of the event"
    )
    
    start_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Start time of the event"
    )
    
    end_date = models.DateField(
        null=True, 
        blank=True,
        help_text="End date of the event"
    )
    
    end_time = models.TimeField(
        null=True,
        blank=True,
        help_text="End time of the event"
    )
    
    timezone = models.CharField(
        max_length=50,
        default='America/New_York',
        choices=settings.TIMEZONE_CHOICES,
        help_text="Event timezone"
    )
    
    time_notes = models.TextField(
        blank=True,
        help_text="Notes for date range events"
    )
    
    is_date_range = models.BooleanField(
        default=False,
        help_text="Whether this is a date range event"
    )
    
    is_longer_than_day = models.BooleanField(
        default=False,
        help_text="Whether this event is longer than a day"
    )
    
    location = models.CharField(
        max_length=500,
        blank=True,
        help_text="Event location"
    )
    
    # Legislative and participant information
    legislative_topics = models.JSONField(
        default=list,
        blank=True,
        help_text="Topics anticipated to be discussed"
    )
    
    participants = models.JSONField(
        default=list,
        blank=True,
        help_text="Who is expected to be in attendance"
    )
    
    expected_attendees = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of expected attendees"
    )
    
    # Point of contact information is now normalized — see the point_of_contact_*
    # properties below (derived from the primary linked Contact).

    # Staff and assignment
    staff = models.JSONField(
        default=list,
        blank=True,
        help_text="Person/people who handle topics anticipated to be addressed"
    )

    primary_staff = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text="The primary assigned staffer (name; must be one of `staff`). Optional.",
    )
    
    # Approval routing
    approval_routing = models.JSONField(
        default=dict,
        blank=True,
        help_text="Approval routing data including required approvers, statuses, and history"
    )
    
    # Reminder settings
    reminder_enabled = models.BooleanField(
        default=False,
        help_text="Whether reminders are enabled for this event"
    )
    
    reminder_time = models.CharField(
        max_length=20,
        blank=True,
        help_text="When to send reminder"
    )
    
    # Consolidated notes
    notes = models.TextField(
        blank=True,
        help_text="All notes including schedule, campaign, staff, and general notes"
    )
    
    # Status (choices are now managed at office level)
    status = models.CharField(
        max_length=30,
        default='received',
        help_text="Current status of the event"
    )

    # Recurrence (occurrences are ordinary Event rows materialized from an
    # EventSeries — calendar/schedule/conflict views need no special handling)
    series = models.ForeignKey(
        'EventSeries',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        help_text="Series this event is an occurrence of"
    )

    series_occurrence_date = models.DateField(
        null=True,
        blank=True,
        help_text="The RRULE instance date this row represents"
    )

    is_series_exception = models.BooleanField(
        default=False,
        help_text="Occurrence was individually edited/detached; series "
                  "regeneration leaves it alone"
    )

    # Human Review fields (for AI-extracted events)
    requires_human_review = models.BooleanField(
        default=False,
        help_text="Whether this event requires human review of AI-extracted fields"
    )

    review_decision = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text=(
            "Human-review outcome: '' (undecided), 'dismissed' (false positive — "
            "the source email was not a real scheduling request). Approved/rejected "
            "outcomes are inferred from extracted_fields field statuses."
        )
    )

    dismissed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this event was dismissed as a false positive"
    )

    dismissed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='events_dismissed',
        null=True,
        blank=True,
        help_text="User who dismissed this event"
    )

    extracted_fields = models.JSONField(
        default=dict,
        blank=True,
        help_text="""AI-extracted field data with review state and source locations.
        Structure: {
            "field_name": {
                "value": <extracted_value>,
                "confidence": 0.85,
                "status": "pending|accepted|rejected",
                "start_index": 145,
                "end_index": 178,
                "text_snippet": "March 15th at 2pm",
                "reviewed_by": null,
                "reviewed_at": null
            }
        }"""
    )
    
    # ------------------------------------------------------------------
    # Normalized contact / organization accessors
    #
    # `group` and `point_of_contact_*` used to be denormalized columns on
    # Event. They are now READ-ONLY properties derived from the normalized
    # Contact / Organization models (linked via EventContact /
    # EventOrganization). To change them, create/link through
    # apps.contacts.services — never assign to these properties.
    # ------------------------------------------------------------------
    @property
    def primary_organization(self):
        """The primary (or first) Organization linked to this event, or None."""
        links = list(self.organization_links.all())
        if not links:
            return None
        chosen = next((l for l in links if l.is_primary), links[0])
        return chosen.organization

    @property
    def primary_contact(self):
        """The primary (or first) Contact linked to this event, or None."""
        links = list(self.contact_links.all())
        if not links:
            return None
        chosen = next((l for l in links if l.is_primary), links[0])
        return chosen.contact

    @property
    def time_display(self) -> str:
        """Human-readable time range ('2:00 PM - 3:00 PM'), '' when untimed.

        Replaces the removed free-text ``time`` column for exports, email
        templates and API payloads.
        """
        def fmt(t):
            return t.strftime('%I:%M %p').lstrip('0')
        if self.start_time and self.end_time:
            return f"{fmt(self.start_time)} - {fmt(self.end_time)}"
        if self.start_time:
            return fmt(self.start_time)
        return ''

    @property
    def group(self):
        """Name of the primary requesting organization (legacy field name)."""
        org = self.primary_organization
        return org.name if org else ''

    @property
    def point_of_contact_name(self):
        contact = self.primary_contact
        return contact.name if contact else ''

    @property
    def point_of_contact_email(self):
        contact = self.primary_contact
        return contact.primary_email if contact else ''

    @property
    def point_of_contact_phone(self):
        contact = self.primary_contact
        return contact.primary_phone if contact else ''

    # Property methods for accessing choices from user's office
    def get_office(self):
        """Get the office for this event (from created_by user)."""
        if self.created_by and hasattr(self.created_by, 'office') and self.created_by.office:
            return self.created_by.office
        return None

    def get_status_choices(self):
        """Get status choices from the user's office."""
        office = self.get_office()
        if office:
            return office.get_active_statuses()
        return getattr(settings, 'DEFAULT_EVENT_STATUS_CHOICES', [])

    def get_type_choices(self):
        """Get type choices from the user's office."""
        office = self.get_office()
        if office:
            return office.get_active_types()
        return getattr(settings, 'DEFAULT_EVENT_TYPE_CHOICES', [])

    def get_format_choices(self):
        """Get format choices from the user's office."""
        office = self.get_office()
        if office:
            return office.get_active_formats()
        return getattr(settings, 'DEFAULT_EVENT_FORMAT_CHOICES', [])

    def get_status_display_from_office(self):
        """Get the display label for the current status from office settings."""
        office = self.get_office()
        if office:
            status_obj = office.get_status_by_value(self.status)
            if status_obj:
                return status_obj.get('label', self.status)
        # Fallback to legacy choices
        for value, label in settings.EVENT_STATUS_CHOICES:
            if value == self.status:
                return label
        return self.status

    def get_type_display_from_office(self):
        """Get the display label for the current type from office settings."""
        office = self.get_office()
        if office:
            type_obj = office.get_type_by_value(self.type)
            if type_obj:
                return type_obj.get('label', self.type)
        # Fallback to legacy choices
        for value, label in settings.EVENT_TYPE_CHOICES:
            if value == self.type:
                return label
        return self.type

    def get_status_color(self):
        """Get the color for the current status from office settings."""
        office = self.get_office()
        if office:
            status_obj = office.get_status_by_value(self.status)
            if status_obj:
                return status_obj.get('color', '#6b7280')
        return '#6b7280'  # Default gray

    def get_status_bg_color(self):
        """Get the background color for the current status from office settings."""
        office = self.get_office()
        if office:
            status_obj = office.get_status_by_value(self.status)
            if status_obj:
                return status_obj.get('bg_color', '#f3f4f6')
        return '#f3f4f6'  # Default light gray

    @property
    def STATUS_CHOICES(self):
        """Legacy property - returns tuple format for backwards compatibility."""
        return settings.EVENT_STATUS_CHOICES

    @property
    def DATA_CLASSIFICATION_CHOICES(self):
        return settings.DATA_CLASSIFICATION_LEVELS

    @property
    def EVENT_FORMAT_CHOICES(self):
        """Get format choices from user's office"""
        return self.get_format_choices()

    @property
    def EVENT_DURATION_CHOICES(self):
        """Get duration choices from user's account settings"""
        return getattr(settings, 'DEFAULT_EVENT_DURATION_CHOICES', [])

    @property
    def REMINDER_TIME_CHOICES(self):
        """Get reminder choices from user's account settings"""
        return getattr(settings, 'DEFAULT_REMINDER_TIME_CHOICES', [])
    
    # Email Integration (Streamlined Approach)
    attached_email_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="List of EmailProcessing record IDs for emails related to this event"
    )
    
    # External system integration
    original_email_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="Legacy field - ID of the original email from Microsoft Graph API"
    )
    
    outlook_calendar_event_id = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="ID of the corresponding Outlook calendar event"
    )
    
    # Security and compliance fields
    data_classification = models.CharField(
        max_length=20,
        choices=settings.DATA_CLASSIFICATION_LEVELS,
        default='internal',
        help_text="Data classification level for security compliance"
    )
    
    # Archiving fields
    is_archived = models.BooleanField(
        default=False,
        help_text="Whether this event has been archived"
    )
    
    archived_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date and time when the event was archived"
    )
    
    archived_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='events_archived',
        null=True,
        blank=True,
        help_text="User who archived this event"
    )
    
    # Audit fields
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='events_created',
        help_text="User who created this event"
    )
    
    modified = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='events_modified',
        help_text="User who last modified this event"
    )
    
    class Meta:
        db_table = 'events'
        verbose_name = 'Event'
        verbose_name_plural = 'Events'
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['start_date', 'start_time']),
            models.Index(fields=['end_date', 'end_time']),
            models.Index(fields=['status']),
            models.Index(fields=['type']),
            models.Index(fields=['format']),
            models.Index(fields=['data_classification']),
            models.Index(fields=['created']),
            models.Index(fields=['is_archived']),
            models.Index(fields=['archived_date']),
            models.Index(fields=['title']),
            models.Index(fields=['is_date_range']),
            models.Index(fields=['requires_human_review']),
        ]
    
    def __str__(self):
        return f"{self.title or self.type.title()}: {self.group} - {self.start_date.strftime('%Y-%m-%d')}"
    
    def clean(self):
        """Validate model data."""
        from django.core.exceptions import ValidationError
        from datetime import datetime
        
        # Validate end_date/time is after start_date/time if provided
        if self.end_date and self.end_time:
            start_datetime = datetime.combine(self.start_date, self.start_time)
            end_datetime = datetime.combine(self.end_date, self.end_time)
            if end_datetime <= start_datetime:
                raise ValidationError("End date/time must be after start date/time.")
        elif self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date must be after start date.")
        
        # Validate JSON fields
        if not isinstance(self.legislative_topics, list):
            raise ValidationError("Legislative topics must be a list.")
        
        if not isinstance(self.participants, list):
            raise ValidationError("Participants must be a list.")
        
        if not isinstance(self.staff, list):
            raise ValidationError("Staff must be a list.")
        
        if not isinstance(self.tags, list):
            raise ValidationError("Tags must be a list.")
        
        if not isinstance(self.approval_routing, dict):
            raise ValidationError("Approval routing must be a dictionary.")
        
        if not isinstance(self.attached_email_ids, list):
            raise ValidationError("Attached email IDs must be a list.")
    
    def save(self, *args, **kwargs):
        """Override save to ensure data validation and audit logging."""
        self.full_clean()
        super().save(*args, **kwargs)
    
    @property
    def is_upcoming(self):
        """Check if event is upcoming (today or later)."""
        if self.start_date is None:
            return False
        return self.start_date >= timezone.now().date()
    
    @property
    def is_past(self):
        """Check if event is in the past."""
        if self.start_date is None:
            return False
        return self.start_date < timezone.now().date()
    
    @property
    def start_datetime(self):
        """Get combined start date and time as datetime object."""
        if self.start_date is None or self.start_time is None:
            return None
        from datetime import datetime
        return datetime.combine(self.start_date, self.start_time)
    
    @property
    def end_datetime(self):
        """Get combined end date and time as datetime object."""
        if self.end_date is None or self.end_time is None:
            return None
        from datetime import datetime
        return datetime.combine(self.end_date, self.end_time)
    
    def archive(self, user):
        """Archive this event with proper audit trail."""
        if self.is_archived:
            return False  # Already archived
        
        self.is_archived = True
        self.archived_date = timezone.now()
        self.archived_by = user
        self.modified_by = user
        self.save()
        
        # Log the archiving action
        EventChangeHistory.objects.create(
            event=self,
            user=user,
            field='archived',
            old_value='False',
            new_value='True',
            ip_address=getattr(user, 'last_ip', None)
        )
        
        return True
    
    def unarchive(self, user):
        """Unarchive this event with proper audit trail."""
        if not self.is_archived:
            return False  # Not archived
        
        self.is_archived = False
        self.archived_date = None
        self.archived_by = None
        self.modified_by = user
        self.save()
        
        # Log the unarchiving action
        EventChangeHistory.objects.create(
            event=self,
            user=user,
            field='unarchived',
            old_value='True',
            new_value='False',
            ip_address=getattr(user, 'last_ip', None)
        )
        
        return True
    
    @property
    def original_email(self):
        """Get the original email that created this event."""
        from apps.email_processing.models import EmailProcessing
        return EmailProcessing.objects.filter(event=self).order_by('processed').first()
    
    @property
    def has_original_email(self):
        """Check if this event has an associated original email."""
        return self.original_email is not None
    
    @property
    def can_be_deleted(self):
        """Check if event can be deleted (simplified - just check if archived)."""
        return self.is_archived
    
    # Email management methods (Streamlined Approach)
    # ------------------------------------------------------------------
    # Email / thread attachment (link-table backed)
    #
    # Source of truth is the EventEmailLink / EventThreadLink through tables.
    # An event's emails are the union of:
    #     (emails whose thread is attached via EventThreadLink)
    #   ∪ (emails directly attached via EventEmailLink mode='include')
    #   − (emails explicitly removed via EventEmailLink mode='exclude')
    # The legacy attached_email_ids JSON list is kept in sync during the
    # transition but is no longer read.
    # ------------------------------------------------------------------
    def _resolve_email(self, email):
        from apps.email_processing.models import EmailProcessing
        if isinstance(email, EmailProcessing):
            return email
        return EmailProcessing.objects.filter(pk=str(email)).first()

    def _resolve_thread(self, thread):
        from apps.email_processing.models import EmailThread
        if isinstance(thread, EmailThread):
            return thread
        return EmailThread.objects.filter(pk=str(thread)).first()

    def attach_email(self, email, *, origin='manual', user=None, is_primary=False):
        """Attach a single email to this event (an 'include' link).

        Accepts an EmailProcessing instance or its id. Re-attaching an excluded
        email flips it back to included; re-attaching never demotes an existing
        primary link (is_primary only promotes). Returns True when the email is
        attached (whether the link was newly created or already existed), False
        only when the email could not be resolved.
        """
        email_obj = self._resolve_email(email)
        if email_obj is None:
            return False

        link, created = EventEmailLink.objects.get_or_create(
            event=self,
            email=email_obj,
            defaults={
                'mode': 'include',
                'origin': origin,
                'is_primary': is_primary,
                'linked_by': user,
            },
        )
        if not created:
            # Ensure it's included again, and promote to primary if requested —
            # but don't silently clobber origin or demote an existing primary.
            updates = []
            if link.mode != 'include':
                link.mode = 'include'
                updates.append('mode')
            if is_primary and not link.is_primary:
                link.is_primary = True
                updates.append('is_primary')
            if updates:
                link.save(update_fields=updates)

        # Keep the legacy JSON list in sync during the transition.
        eid = str(email_obj.id)
        if not isinstance(self.attached_email_ids, list):
            self.attached_email_ids = []
        if eid not in self.attached_email_ids:
            self.attached_email_ids.append(eid)
        return True

    def detach_email(self, email):
        """Remove a direct 'include' link to an email. Does not affect emails
        present only via an attached thread (use exclude_email for those)."""
        email_id = str(getattr(email, 'id', email))
        deleted, _ = self.email_links.filter(
            email_id=email_id, mode='include'
        ).delete()
        if isinstance(self.attached_email_ids, list) and email_id in self.attached_email_ids:
            self.attached_email_ids.remove(email_id)
        return bool(deleted)

    def exclude_email(self, email, user=None):
        """Explicitly remove a single email from this event even though its
        thread is attached (the pressure valve for thread/event drift)."""
        email_obj = self._resolve_email(email)
        if email_obj is None:
            return False
        EventEmailLink.objects.update_or_create(
            event=self,
            email=email_obj,
            defaults={'mode': 'exclude', 'origin': 'manual',
                      'is_primary': False, 'linked_by': user},
        )
        return True

    def attach_thread(self, thread, user=None):
        """Attach an entire conversation thread to this event. New replies on
        the same conversation will appear on the event automatically."""
        thread_obj = self._resolve_thread(thread)
        if thread_obj is None:
            return False
        _, created = EventThreadLink.objects.get_or_create(
            event=self, thread=thread_obj, defaults={'linked_by': user},
        )
        return created

    def detach_thread(self, thread):
        """Detach a conversation thread from this event."""
        thread_id = str(getattr(thread, 'id', thread))
        deleted, _ = self.thread_links.filter(thread_id=thread_id).delete()
        return bool(deleted)

    def get_email_threads(self):
        """Return the EmailThread records attached to this event."""
        from apps.email_processing.models import EmailThread
        return EmailThread.objects.filter(event_links__event=self).distinct()

    def get_email_groups(self):
        """Group this event's attached emails for display.

        Returns a dict:
            {
              'threads': [ {'thread': EmailThread, 'emails': [EmailProcessing, ...]} ],
              'standalone': [EmailProcessing, ...],
            }
        Emails whose thread is attached to the event are grouped under that
        thread (ordered oldest->newest); everything else (directly-attached
        off-thread emails) falls into 'standalone'. Threads are ordered by their
        most recent attached message.
        """
        from apps.email_processing.models import EmailThread

        emails = list(self.get_attached_emails())  # ordered by received asc
        linked_thread_pks = set(self.thread_links.values_list('thread_id', flat=True))

        threads_map = {}
        standalone = []
        for email in emails:
            if email.thread_id and email.thread_id in linked_thread_pks:
                threads_map.setdefault(email.thread_id, []).append(email)
            else:
                standalone.append(email)

        thread_objs = {t.pk: t for t in EmailThread.objects.filter(pk__in=threads_map.keys())}
        threads = [
            {'thread': thread_objs[pk], 'emails': msgs}
            for pk, msgs in threads_map.items() if pk in thread_objs
        ]
        threads.sort(key=lambda g: g['emails'][-1].received)
        return {'threads': threads, 'standalone': standalone}

    def other_events_for_email(self, email):
        """Other events this email is attached to (for the shared-email badge).

        Considers both direct includes and attached threads, and honours
        per-event exclusions. Single source of truth for the 'Also on …' badge.
        """
        from django.db.models import Q

        conditions = Q(email_links__email=email, email_links__mode='include')
        if email.thread_id:
            conditions |= Q(thread_links__thread_id=email.thread_id)
        return (
            Event.objects.filter(conditions)
            .exclude(id=self.id)
            .exclude(email_links__email=email, email_links__mode='exclude')
            .distinct()
        )

    def get_attached_emails(self):
        """Get all emails on this event (the thread ∪ direct − excluded union)."""
        from django.db.models import Q
        from apps.email_processing.models import EmailProcessing

        thread_pks = list(self.thread_links.values_list('thread_id', flat=True))
        include_ids = list(
            self.email_links.filter(mode='include').values_list('email_id', flat=True)
        )
        exclude_ids = list(
            self.email_links.filter(mode='exclude').values_list('email_id', flat=True)
        )

        if not thread_pks and not include_ids:
            return EmailProcessing.objects.none()

        qs = EmailProcessing.objects.filter(
            Q(thread_id__in=thread_pks) | Q(id__in=include_ids)
        )
        if exclude_ids:
            qs = qs.exclude(id__in=exclude_ids)
        return qs.distinct().order_by('received')

    def get_attached_emails_data(self):
        """Get complete email data for all attached emails."""
        emails = self.get_attached_emails()
        return [email.complete_email_data for email in emails if email.has_complete_email_data()]

    def get_email_by_id(self, email_processing_id):
        """Get a specific attached EmailProcessing record by ID."""
        return self.get_attached_emails().filter(pk=str(email_processing_id)).first()

    def get_emails_by_type(self, email_type):
        """Get all attached emails of a specific type."""
        return [email for email in self.get_attached_emails()
                if email.get_email_type() == email_type]

    def get_primary_email(self):
        """Get the primary source email for this event."""
        # A link flagged primary for THIS event wins (primacy is per-event).
        primary_link = (
            self.email_links.filter(mode='include', is_primary=True)
            .select_related('email').first()
        )
        if primary_link:
            return primary_link.email

        emails = list(self.get_attached_emails())

        # Fall back to an email self-describing as primary in its metadata.
        for email in emails:
            processing_metadata = email.get_complete_email_field('processing_metadata', {})
            if processing_metadata.get('is_primary_email', False):
                return email

        # Then the first original request, else the earliest email.
        original_emails = self.get_emails_by_type('original_request')
        if original_emails:
            return original_emails[0]
        return emails[0] if emails else None

    def get_original_request_emails(self):
        """Get all original request emails."""
        return self.get_emails_by_type('original_request')

    def get_response_emails(self):
        """Get all response emails sent."""
        return self.get_emails_by_type('response_sent')

    def get_follow_up_emails(self):
        """Get all follow-up emails."""
        return self.get_emails_by_type('follow_up')

    def has_emails(self):
        """Check if this event has any attached emails."""
        return self.get_attached_emails().exists()

    def get_email_thread(self, thread_id):
        """Get all attached emails belonging to a specific conversationId."""
        return [email for email in self.get_attached_emails()
                if email.get_email_thread_id() == thread_id]
    
    @classmethod
    def get_active_events(cls):
        """Get all non-archived events."""
        return cls.objects.filter(is_archived=False)

    @classmethod
    def get_archived_events(cls):
        """Get all archived events."""
        return cls.objects.filter(is_archived=True)

    @classmethod
    def get_events_for_deletion(cls):
        """Get events that can be deleted (archived events)."""
        return cls.objects.filter(is_archived=True)

    # ==========================================================================
    # Staff Assignment and Permission Methods
    # ==========================================================================

    def is_user_assigned(self, user) -> bool:
        """
        Check if a user is in the event's staff list.

        Matches by:
        1. User's linked staff_profile name/email
        2. User's full name or username
        3. User's email address

        Args:
            user: User instance to check

        Returns:
            True if user is assigned to this event
        """
        if not self.staff:
            return False

        # Get user identifiers
        user_name = user.get_full_name().lower() if user.get_full_name() else user.username.lower()
        user_email = user.email.lower() if user.email else ''

        # Also check linked staff_profile
        staff_profile_name = ''
        staff_profile_email = ''
        if hasattr(user, 'staff_profile') and user.staff_profile:
            staff_profile_name = user.staff_profile.name.lower()
            staff_profile_email = user.staff_profile.email.lower() if user.staff_profile.email else ''

        for staff_entry in self.staff:
            if isinstance(staff_entry, dict):
                entry_name = staff_entry.get('name', '').lower()
                entry_email = staff_entry.get('email', '').lower()

                # Check against staff_profile
                if staff_profile_name and staff_profile_name == entry_name:
                    return True
                if staff_profile_email and staff_profile_email == entry_email:
                    return True

                # Check against user info
                if user_name == entry_name:
                    return True
                if user_email and user_email == entry_email:
                    return True

            elif isinstance(staff_entry, str):
                entry_lower = staff_entry.lower()
                if staff_profile_name == entry_lower:
                    return True
                if user_name == entry_lower:
                    return True

        return False

    def get_pending_suggestions_count(self) -> int:
        """
        Get count of pending change suggestions for this event.

        Returns:
            Number of pending suggestions
        """
        return self.change_suggestions.filter(status='pending').count()

    def has_pending_suggestions(self) -> bool:
        """Check if event has any pending change suggestions."""
        return self.change_suggestions.filter(status='pending').exists()


class EventChangeSuggestion(models.Model):
    """
    Model for staff change suggestions that require scheduler/admin review.

    When a staff member who is not assigned to an event makes changes,
    those changes are captured as suggestions rather than applied directly.
    Schedulers and admins can then approve or reject these suggestions.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='change_suggestions',
        help_text="Event this suggestion applies to"
    )

    field_name = models.CharField(
        max_length=100,
        help_text="Name of the field being changed (e.g., 'title', 'location')"
    )

    current_value = models.TextField(
        blank=True,
        help_text="Current value of the field (JSON serialized for complex types)"
    )

    suggested_value = models.TextField(
        help_text="Suggested new value for the field (JSON serialized for complex types)"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Current status of this suggestion"
    )

    reason = models.TextField(
        blank=True,
        help_text="Optional reason provided by the suggester for this change"
    )

    # Suggester information
    suggested_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='suggestions_made',
        help_text="User who suggested this change (null for system-origin "
                  "suggestions, e.g. email ingestion)"
    )

    suggested_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this suggestion was created"
    )

    # Where the suggestion came from. Email-ingestion suggestions are grouped
    # per source candidate in the inbox's change-request feed.
    ORIGIN_CHOICES = [
        ('staff', 'Staff suggestion'),
        ('email_ingestion', 'Email ingestion'),
    ]
    origin = models.CharField(
        max_length=20,
        choices=ORIGIN_CHOICES,
        default='staff',
        db_index=True,
        help_text="Source of this suggestion"
    )

    source_candidate = models.ForeignKey(
        'email_processing.ExtractionCandidate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='change_suggestions',
        help_text="Extraction candidate that produced this suggestion (a "
                  "multi-field change is N rows sharing one candidate)"
    )

    # Reviewer information (null until reviewed)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='suggestions_reviewed',
        help_text="User who reviewed this suggestion"
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this suggestion was reviewed"
    )

    review_comment = models.TextField(
        blank=True,
        help_text="Optional comment from reviewer when approving/rejecting"
    )

    # Audit fields
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the suggester"
    )

    class Meta:
        db_table = 'event_change_suggestions'
        verbose_name = 'Event Change Suggestion'
        verbose_name_plural = 'Event Change Suggestions'
        ordering = ['-suggested_at']
        indexes = [
            models.Index(fields=['event', 'status']),
            models.Index(fields=['suggested_by', 'status']),
            models.Index(fields=['status', 'suggested_at']),
            models.Index(fields=['event', 'field_name', 'status']),
        ]

    def __str__(self):
        return f"{self.event.title or self.event.group}: {self.field_name} suggestion by {self.suggested_by}"

    def approve(self, reviewer, comment='', ip_address=None):
        """
        Approve this suggestion and apply the change to the event.

        Args:
            reviewer: User approving the suggestion
            comment: Optional review comment
            ip_address: IP address of reviewer

        Returns:
            True if approved successfully
        """
        import json
        from django.utils import timezone

        if self.status != 'pending':
            return False

        # Get the event
        event = self.event

        # Parse the suggested value (may be JSON for complex fields)
        try:
            new_value = json.loads(self.suggested_value)
        except (json.JSONDecodeError, TypeError):
            new_value = self.suggested_value

        # Apply the change to the event
        from apps.contacts.services import NORMALIZED_EVENT_FIELDS, apply_field_to_event
        if self.field_name in NORMALIZED_EVENT_FIELDS:
            # Normalized contact/org field: create/link instead of setattr.
            old_value = getattr(event, self.field_name, '')
            apply_field_to_event(event, self.field_name, new_value, reviewer)
            EventChangeHistory.objects.create(
                event=event,
                user=reviewer,
                field=self.field_name,
                old_value=str(old_value) if old_value is not None else '',
                new_value=str(new_value) if new_value is not None else '',
                ip_address=ip_address
            )
        elif hasattr(event, self.field_name):
            old_value = getattr(event, self.field_name)
            setattr(event, self.field_name, new_value)
            event.modified_by = reviewer
            event.save()

            # Create change history record
            EventChangeHistory.objects.create(
                event=event,
                user=reviewer,
                field=self.field_name,
                old_value=str(old_value) if old_value is not None else '',
                new_value=str(new_value) if new_value is not None else '',
                ip_address=ip_address
            )

        # Update suggestion status
        self.status = 'approved'
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.review_comment = comment
        self.save()

        return True

    def reject(self, reviewer, comment='', ip_address=None):
        """
        Reject this suggestion.

        Args:
            reviewer: User rejecting the suggestion
            comment: Optional review comment
            ip_address: IP address of reviewer

        Returns:
            True if rejected successfully
        """
        from django.utils import timezone

        if self.status != 'pending':
            return False

        self.status = 'rejected'
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.review_comment = comment
        self.save()

        return True


class EventApproval(models.Model):
    """
    Model for tracking individual approvals in an event's approval routing chain.

    Each EventApproval represents one approver's decision for a specific stage
    of the approval routing process. The approval routing structure is stored
    in Event.approval_routing as JSON.

    Approval Routing JSON Structure (in Event.approval_routing):
    {
        "version": 1,
        "stages": [
            {
                "stage_id": "stage-1",
                "order": 1,
                "type": "parallel",  // "parallel" = AND, all must approve
                "approvers": [
                    {"user_id": "uuid", "name": "Connor", "required": true},
                    {"user_id": "uuid", "name": "Prisha", "required": true}
                ],
                "all_required": true
            },
            {
                "stage_id": "stage-2",
                "order": 2,
                "type": "sequential",
                "approvers": [{"user_id": "uuid", "name": "Wyatt", "required": true}]
            }
        ]
    }
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('sent_back', 'Sent Back'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='approvals',
        help_text="Event being approved"
    )

    stage_id = models.CharField(
        max_length=50,
        help_text="ID of the approval stage (matches stage_id in approval_routing)"
    )

    stage_order = models.PositiveIntegerField(
        help_text="Order of this stage in the approval chain"
    )

    approver = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='event_approvals',
        help_text="User assigned to approve"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Current status of this approval"
    )

    comment = models.TextField(
        blank=True,
        help_text="Comment provided when approving or sending back"
    )

    decided_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this approval decision was made"
    )

    # Track edits made during the approver's turn
    edits_made = models.JSONField(
        default=list,
        help_text="List of field changes made by approver during their turn"
    )

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address when decision was made"
    )

    class Meta:
        db_table = 'event_approvals'
        verbose_name = 'Event Approval'
        verbose_name_plural = 'Event Approvals'
        ordering = ['stage_order', 'created_at']
        indexes = [
            models.Index(fields=['event', 'status']),
            models.Index(fields=['approver', 'status']),
            models.Index(fields=['event', 'stage_id', 'status']),
            models.Index(fields=['status', 'decided_at']),
        ]
        # Unique constraint: one approval per approver per stage per event
        unique_together = [['event', 'stage_id', 'approver']]

    def __str__(self):
        return f"{self.event.title or self.event.group}: Stage {self.stage_order} - {self.approver}"

    def approve(self, comment='', ip_address=None, edits=None):
        """
        Mark this approval as approved.

        Args:
            comment: Optional approval comment
            ip_address: IP address for audit
            edits: List of edits made during approval turn

        Returns:
            True if approved successfully
        """
        if self.status != 'pending':
            return False

        self.status = 'approved'
        self.comment = comment
        self.decided_at = timezone.now()
        self.ip_address = ip_address
        if edits:
            self.edits_made = edits
        self.save()
        return True

    def send_back(self, comment, ip_address=None):
        """
        Send this approval back for revisions.

        Args:
            comment: Optional comment explaining why
            ip_address: IP address for audit

        Returns:
            True if sent back successfully
        """
        if self.status != 'pending':
            return False

        self.status = 'sent_back'
        self.comment = comment or ''
        self.decided_at = timezone.now()
        self.ip_address = ip_address
        self.save()
        return True


class EventChangeHistory(models.Model):
    """
    Model to track all changes made to events for audit compliance.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='change_history',
        help_text="Event that was changed"
    )

    timestamp = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        help_text="User who made the change"
    )

    field = models.CharField(
        max_length=100,
        help_text="Field that was changed"
    )

    old_value = models.TextField(
        blank=True,
        help_text="Previous value (JSON serialized if complex)"
    )
    
    new_value = models.TextField(
        blank=True,
        help_text="New value (JSON serialized if complex)"
    )
    
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the user making the change"
    )
    
    user_agent = models.TextField(
        blank=True,
        help_text="User agent string for security auditing"
    )
    
    class Meta:
        db_table = 'event_change_history'
        verbose_name = 'Event Change History'
        verbose_name_plural = 'Event Change Histories'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['event', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]
    
    def __str__(self):
        return f"{self.event} - {self.field} changed by {self.user} at {self.timestamp}"


class EventReviewAuditLog(models.Model):
    """
    Audit log specifically for human review actions on AI-extracted fields.
    Tracks accept/reject/undo actions for the review audit trail.
    """

    ACTION_CHOICES = [
        ('accept', 'Accepted'),
        ('reject', 'Rejected'),
        ('undo_reject', 'Undo Reject'),
        ('edit_after_accept', 'Edited After Accept'),
        ('accept_all', 'Accepted All'),
        ('dismiss', 'Dismissed'),
        ('undo_dismiss', 'Undo Dismiss'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='review_audit_logs',
        help_text="Event being reviewed"
    )

    field_name = models.CharField(
        max_length=100,
        help_text="Field that was reviewed (e.g., 'title', 'start_date')"
    )

    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        help_text="Review action taken"
    )

    original_value = models.TextField(
        blank=True,
        help_text="Original AI-extracted value (JSON serialized)"
    )

    new_value = models.TextField(
        blank=True,
        null=True,
        help_text="New value after action (if applicable)"
    )

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        help_text="User who performed the action"
    )

    timestamp = models.DateTimeField(auto_now_add=True)

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the user"
    )

    class Meta:
        db_table = 'event_review_audit_log'
        verbose_name = 'Event Review Audit Log'
        verbose_name_plural = 'Event Review Audit Logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['event', 'timestamp']),
            models.Index(fields=['field_name']),
            models.Index(fields=['action']),
            models.Index(fields=['user']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.event.id} - {self.field_name} {self.action} by {self.user} at {self.timestamp}"


class EmailTemplate(models.Model):
    """
    Model for storing email response templates.
    Supports office-scoped templates with categories for organized template selection.
    """

    CATEGORY_CHOICES = [
        ('rsvp', 'RSVP'),
        ('follow_up', 'Follow Up'),
        ('scheduling', 'Scheduling'),
        ('decline', 'Decline'),
        ('thank_you', 'Thank You'),
        ('acknowledge', 'Acknowledge'),
        ('custom', 'Custom'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(
        max_length=200,
        help_text="Template name for identification"
    )

    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='custom',
        help_text="Template category for grouping"
    )

    subject = models.CharField(
        max_length=500,
        help_text="Email subject template with {variable} placeholders"
    )

    body = models.TextField(
        help_text="Email body template with {variable} placeholders"
    )

    variables = models.JSONField(
        default=list,
        blank=True,  # a template with no placeholders is valid
        help_text="List of available variables for this template"
    )

    is_default = models.BooleanField(
        default=False,
        help_text="Whether this is a default system template"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether this template is available for use"
    )

    is_html = models.BooleanField(
        default=False,
        help_text="Whether the template body contains HTML"
    )

    office = models.ForeignKey(
        'authentication.Office',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='email_templates',
        help_text="Office this template belongs to (null = system default)"
    )

    # Audit fields
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='templates_created',
        help_text="User who created this template"
    )

    modified = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='templates_modified',
        help_text="User who last modified this template"
    )

    class Meta:
        db_table = 'email_templates'
        verbose_name = 'Email Template'
        verbose_name_plural = 'Email Templates'
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_default']),
            models.Index(fields=['created']),
            models.Index(fields=['category']),
            models.Index(fields=['is_active']),
            models.Index(fields=['office']),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """Validate template data."""
        from django.core.exceptions import ValidationError

        if not isinstance(self.variables, list):
            raise ValidationError("Variables must be a list.")

    def save(self, *args, **kwargs):
        """Override save to ensure data validation."""
        self.full_clean()
        super().save(*args, **kwargs)


def export_template_upload_path(instance, filename):
    """Generate upload path for export template files, scoped by office."""
    office_id = str(instance.office_id) if instance.office_id else 'system'
    return f'export_templates/{office_id}/{filename}'


class ExportTemplate(models.Model):
    """
    Word (.docx) template for exporting events.
    Uses docxtpl Jinja2 syntax for placeholders.

    Built-in templates (is_default=True, office=None) ship with HillDesk.
    Offices can upload custom templates that override or supplement the defaults.
    """

    TEMPLATE_TYPE_CHOICES = [
        ('daily_briefing', 'Daily Briefing'),
        ('weekly_overview', 'Weekly Overview'),
        ('event_detail', 'Event Detail'),
        ('filtered_list', 'Filtered List'),
        ('custom', 'Custom'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    office = models.ForeignKey(
        'authentication.Office',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='export_templates',
        help_text="Office this template belongs to. Null for system defaults."
    )

    name = models.CharField(
        max_length=200,
        help_text="Display name of this export template"
    )

    template_type = models.CharField(
        max_length=30,
        choices=TEMPLATE_TYPE_CHOICES,
        help_text="Type of export this template produces"
    )

    docx_file = models.FileField(
        upload_to=export_template_upload_path,
        blank=True,
        help_text="Uploaded .docx template file. Blank for built-in defaults."
    )

    is_default = models.BooleanField(
        default=False,
        help_text="True for built-in system templates"
    )

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='export_templates_created',
        help_text="User who created this template"
    )

    modified_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='export_templates_modified',
        help_text="User who last modified this template"
    )

    class Meta:
        db_table = 'export_templates'
        verbose_name = 'Export Template'
        verbose_name_plural = 'Export Templates'
        ordering = ['template_type', 'name']
        indexes = [
            models.Index(fields=['template_type']),
            models.Index(fields=['is_default']),
            models.Index(fields=['office']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_template_type_display()})"


class AccountEventSettings(models.Model):
    """
    Account-specific settings for event choices.
    Allows customization of event format, duration, and reminder choices per user.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='event_settings',
        help_text="User who owns these settings"
    )
    
    # JSON fields for customizable choices
    event_format_choices = models.JSONField(
        default=list,
        help_text="Custom event format choices for this account"
    )
    
    event_duration_choices = models.JSONField(
        default=list,
        help_text="Custom event duration choices for this account"
    )
    
    reminder_time_choices = models.JSONField(
        default=list,
        help_text="Custom reminder time choices for this account"
    )
    
    # Audit fields
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'account_event_settings'
        verbose_name = 'Account Event Settings'
        verbose_name_plural = 'Account Event Settings'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['created']),
        ]
    
    def __str__(self):
        return f"Event Settings for {self.user.username}"
    
    def clean(self):
        """Validate settings data."""
        from django.core.exceptions import ValidationError
        
        if not isinstance(self.event_format_choices, list):
            raise ValidationError("Event format choices must be a list.")
        
        if not isinstance(self.event_duration_choices, list):
            raise ValidationError("Event duration choices must be a list.")
        
        if not isinstance(self.reminder_time_choices, list):
            raise ValidationError("Reminder time choices must be a list.")
    
    def save(self, *args, **kwargs):
        """Override save to ensure data validation."""
        self.full_clean()
        super().save(*args, **kwargs)
    
    @classmethod
    def get_or_create_for_user(cls, user):
        """Get or create settings for a user with default values."""
        # (The local used to be named `settings`, shadowing django.conf.settings
        # and raising UnboundLocalError on every call.)
        account_settings, _created = cls.objects.get_or_create(
            user=user,
            defaults={
                'event_format_choices': getattr(settings, 'DEFAULT_EVENT_FORMAT_CHOICES', []),
                'event_duration_choices': getattr(settings, 'DEFAULT_EVENT_DURATION_CHOICES', []),
                'reminder_time_choices': getattr(settings, 'DEFAULT_REMINDER_TIME_CHOICES', []),
            }
        )
        return account_settings


class HouseFloorSchedule(models.Model):
    """Weekly snapshot of the docs.house.gov 'Bills This Week' floor schedule."""

    week_date = models.DateField(
        unique=True,
        db_index=True,
        help_text="Monday of the week the schedule covers (from XML week-date attribute)"
    )
    congress_num = models.IntegerField(null=True, blank=True)
    source_url = models.URLField(max_length=500)
    source_update_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="update-date attribute from XML root — when docs.house.gov last revised the file"
    )
    raw_xml = models.TextField(
        blank=True,
        help_text="Original XML for debugging / reprocessing"
    )
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'house_floor_schedule'
        ordering = ['-week_date']
        verbose_name = 'House Floor Schedule'
        verbose_name_plural = 'House Floor Schedules'

    def __str__(self):
        return f"Floor schedule — week of {self.week_date}"


class HouseFloorItem(models.Model):
    """One bill/resolution on the House floor schedule for a given week."""

    schedule = models.ForeignKey(
        HouseFloorSchedule,
        on_delete=models.CASCADE,
        related_name='items'
    )
    category = models.CharField(
        max_length=255,
        help_text="e.g. 'Items that may be considered under suspension of the rules'"
    )
    category_sort_order = models.IntegerField(default=0)
    item_sort_order = models.IntegerField(default=0)
    external_id = models.CharField(
        max_length=50,
        db_index=True,
        help_text="floor-item id attribute from XML"
    )
    legis_num = models.CharField(max_length=50, blank=True)
    floor_text = models.TextField(blank=True)
    publish_date = models.DateTimeField(null=True, blank=True)
    pdf_url = models.URLField(max_length=1000, blank=True)

    class Meta:
        db_table = 'house_floor_item'
        ordering = ['category_sort_order', 'item_sort_order']
        indexes = [
            models.Index(fields=['schedule', 'category_sort_order', 'item_sort_order']),
        ]

    def __str__(self):
        return f"{self.legis_num} — {self.floor_text[:60]}"


class HouseFloorProceedings(models.Model):
    """Snapshot of one legislative day's live floor proceedings.

    Sourced from the Clerk's feed at clerk.house.gov/floor/{YYYYMMDD}.xml — the
    same data live.house.gov surfaces as its 'Activity' feed.
    """

    legislative_day = models.DateField(
        unique=True,
        db_index=True,
        help_text="Legislative day the proceedings cover (from XML legislative_day date attribute)"
    )
    legislative_header = models.CharField(max_length=255, blank=True)
    congress_num = models.IntegerField(null=True, blank=True)
    session_num = models.IntegerField(null=True, blank=True)
    pub_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="pubDate from the feed — when the Clerk last published the file"
    )
    day_finished = models.BooleanField(
        default=False,
        help_text="legislative_day_finished — the House has adjourned for the day"
    )
    next_convenes = models.DateTimeField(
        null=True,
        blank=True,
        help_text="next-legislative-day-convenes attribute, when present"
    )
    source_url = models.URLField(max_length=500)
    raw_xml = models.TextField(blank=True, help_text="Original XML for debugging / reprocessing")
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'house_floor_proceedings'
        ordering = ['-legislative_day']
        verbose_name = 'House Floor Proceedings'
        verbose_name_plural = 'House Floor Proceedings'

    def __str__(self):
        return f"Floor proceedings — {self.legislative_day}"


class HouseFloorAction(models.Model):
    """One timestamped floor action within a day's proceedings."""

    proceedings = models.ForeignKey(
        HouseFloorProceedings,
        on_delete=models.CASCADE,
        related_name='actions'
    )
    unique_id = models.CharField(
        max_length=50,
        db_index=True,
        help_text="unique-id attribute from XML — stable per action"
    )
    act_id = models.CharField(max_length=50, blank=True)
    action_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Parsed from action_time for-search attribute (Eastern)"
    )
    action_time_display = models.CharField(
        max_length=50,
        blank=True,
        help_text="Display text, e.g. '10:33:15 A.M.'"
    )
    description = models.TextField(blank=True)
    update_date_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'house_floor_action'
        # Newest action first — matches how live.house.gov lists the activity feed.
        ordering = ['-action_time']
        indexes = [
            models.Index(fields=['proceedings', '-action_time']),
        ]

    def __str__(self):
        return f"{self.action_time_display} — {self.description[:60]}"


class EventEmailLink(models.Model):
    """Association between an Event and a single EmailProcessing record.

    This is the source of truth for "which emails are on this event" and makes
    the Event ↔ Email relationship many-to-many (an email can relate to several
    events). `mode='exclude'` removes an email that would otherwise be pulled in
    by an attached thread.
    """

    MODE_CHOICES = [
        ('include', 'Include'),
        ('exclude', 'Exclude'),
    ]
    ORIGIN_CHOICES = [
        ('thread', 'From attached thread'),
        ('manual', 'Manually attached'),
        ('ai_auto', 'Auto-linked by ingestion'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        'Event',
        on_delete=models.CASCADE,
        related_name='email_links',
    )
    email = models.ForeignKey(
        'email_processing.EmailProcessing',
        on_delete=models.CASCADE,
        related_name='event_links',
    )

    mode = models.CharField(
        max_length=10, choices=MODE_CHOICES, default='include',
        help_text="include = on this event; exclude = removed despite an attached thread",
    )
    origin = models.CharField(
        max_length=10, choices=ORIGIN_CHOICES, default='manual',
        help_text="How this link was created",
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Whether this email is the primary source for THIS event (per-event)",
    )
    event_fragment_ref = models.JSONField(
        null=True, blank=True,
        help_text="Reserved: which part of a multi-event email pertains to this event",
    )

    linked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='event_email_links',
    )
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_email_links'
        verbose_name = 'Event Email Link'
        verbose_name_plural = 'Event Email Links'
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'email'], name='uniq_event_email_link'
            ),
        ]
        indexes = [
            models.Index(fields=['event', 'mode']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f"{self.event_id} ←{self.mode}→ {self.email_id}"


class EventThreadLink(models.Model):
    """Association between an Event and an entire EmailThread (conversation).

    Attaching a thread is "living": new emails arriving on the same
    conversationId surface on the event automatically.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        'Event',
        on_delete=models.CASCADE,
        related_name='thread_links',
    )
    thread = models.ForeignKey(
        'email_processing.EmailThread',
        on_delete=models.CASCADE,
        related_name='event_links',
    )

    linked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='event_thread_links',
    )
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_thread_links'
        verbose_name = 'Event Thread Link'
        verbose_name_plural = 'Event Thread Links'
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'thread'], name='uniq_event_thread_link'
            ),
        ]
        indexes = [
            models.Index(fields=['event']),
            models.Index(fields=['thread']),
        ]

    def __str__(self):
        return f"{self.event_id} ← thread {self.thread_id}"


def event_attachment_upload_path(instance, filename):
    """Generate upload path for an event attachment version, scoped by office and event.

    `instance` is an EventAttachmentVersion. The on-disk filename is the version's
    UUID (set by the caller) so untrusted user filenames never touch the storage
    backend; the human-readable name lives on EventAttachment.original_filename.
    """
    attachment = instance.attachment
    office = attachment.event.get_office()
    office_id = str(office.id) if office else 'system'
    return f'event_attachments/{office_id}/{attachment.event_id}/{filename}'


class EventAttachment(models.Model):
    """
    A file attached to an Event (e.g. a memo .docx, a meeting agenda PDF).

    This is the logical attachment: stable identity, display name, and
    classification. The actual file bytes live on EventAttachmentVersion so that
    replacing a file keeps prior versions for the audit trail (congressional
    record-keeping). The current file is the highest version_number.

    Defaults to `confidential` classification because attachments routinely carry
    constituent PII — more conservative than the Event default of `internal`.
    """

    SOURCE_CHOICES = [
        ('upload', 'Direct upload'),
        ('email', 'From email attachment'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='attachments',
        help_text="Event this file is attached to"
    )

    original_filename = models.CharField(
        max_length=255,
        help_text="Original (untrusted) filename, for display only"
    )

    data_classification = models.CharField(
        max_length=20,
        choices=settings.DATA_CLASSIFICATION_LEVELS,
        default='confidential',
        help_text="Data classification level for security compliance"
    )

    source = models.CharField(
        max_length=10,
        choices=SOURCE_CHOICES,
        default='upload',
        help_text="How this attachment entered the system"
    )

    # Audit fields
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='event_attachments_created',
        help_text="User who first uploaded this attachment"
    )
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'event_attachments'
        verbose_name = 'Event Attachment'
        verbose_name_plural = 'Event Attachments'
        ordering = ['-created']
        indexes = [
            models.Index(fields=['event']),
            models.Index(fields=['created']),
        ]

    def __str__(self):
        return f"{self.original_filename} (event {self.event_id})"

    @property
    def current_version(self):
        """The latest version (highest version_number), or None if all deleted."""
        return self.versions.order_by('-version_number').first()


class EventAttachmentVersion(models.Model):
    """
    One uploaded revision of an EventAttachment's file.

    Replacing an attachment creates a new version rather than overwriting, so the
    prior file stays downloadable for the audit trail. The underlying file blob is
    removed by a post_delete signal (see signals.py) to avoid orphaned storage.
    """

    SCAN_STATUS_CHOICES = [
        ('pending', 'Pending scan'),
        ('clean', 'Clean'),
        ('infected', 'Infected'),
        ('skipped', 'Scan skipped'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    attachment = models.ForeignKey(
        EventAttachment,
        on_delete=models.CASCADE,
        related_name='versions',
        help_text="Logical attachment this version belongs to"
    )

    file = models.FileField(
        upload_to=event_attachment_upload_path,
        max_length=255,
        help_text="The stored file for this version"
    )

    content_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="MIME type reported/sniffed at upload"
    )

    file_size = models.PositiveIntegerField(
        default=0,
        help_text="File size in bytes"
    )

    version_number = models.PositiveIntegerField(
        help_text="1-based revision number within the attachment"
    )

    scan_status = models.CharField(
        max_length=10,
        choices=SCAN_STATUS_CHOICES,
        default='pending',
        help_text="Malware scan status; downloads are blocked unless clean/skipped"
    )

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='event_attachment_versions_uploaded',
        help_text="User who uploaded this version"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'event_attachment_versions'
        verbose_name = 'Event Attachment Version'
        verbose_name_plural = 'Event Attachment Versions'
        ordering = ['-version_number']
        constraints = [
            models.UniqueConstraint(
                fields=['attachment', 'version_number'],
                name='uniq_attachment_version_number'
            ),
        ]
        indexes = [
            models.Index(fields=['attachment', 'version_number']),
        ]

    def __str__(self):
        return f"{self.attachment_id} v{self.version_number}"

    @property
    def is_downloadable(self):
        """A version may be served only once it has passed (or skipped) scanning."""
        return self.scan_status in ('clean', 'skipped')

class EventSeries(models.Model):
    """A recurring event rule whose occurrences are materialized as ordinary
    Event rows (spec §3.3).

    Consequences, all intentional: calendar/schedule/conflict views need zero
    changes; single-occurrence edits are ordinary event edits (flagged
    ``is_series_exception``); cancel-one is an ordinary status change; a
    series-level edit regenerates future non-exception occurrences.

    A series cannot activate without an end bound (UNTIL or COUNT) — "no
    open-ended series" is enforced here at the model level and again by the
    review UI.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    rrule = models.CharField(
        max_length=500,
        help_text="RFC-5545 RRULE string (validated with dateutil.rrule)"
    )
    dtstart_date = models.DateField(help_text="First occurrence date")
    dtstart_time = models.TimeField(null=True, blank=True)
    timezone = models.CharField(
        max_length=50,
        default='America/New_York',
        choices=settings.TIMEZONE_CHOICES,
    )
    until_date = models.DateField(
        null=True, blank=True,
        help_text="Series end date (one of until_date/count required to activate)"
    )
    count = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Number of occurrences (one of until_date/count required to activate)"
    )

    title_template = models.CharField(max_length=200, blank=True, default='')
    source_candidate = models.ForeignKey(
        'email_processing.ExtractionCandidate',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='series',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True,
        related_name='event_series_created',
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Inactive until a reviewer confirms the rule AND an end bound"
    )
    materialized_through = models.DateField(
        null=True, blank=True,
        help_text="Occurrence-generation horizon (rolled forward monthly)"
    )

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'event_series'
        verbose_name = 'Event Series'
        verbose_name_plural = 'Event Series'
        ordering = ['-created']

    def __str__(self):
        return f"Series '{self.title_template}' ({self.rrule})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.is_active and not (self.until_date or self.count):
            raise ValidationError(
                "A series cannot activate without an end bound (until_date or count)."
            )
        try:
            self.build_rrule()
        except (ValueError, TypeError) as exc:
            raise ValidationError({'rrule': f'Invalid RRULE: {exc}'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Occurrence generation
    # ------------------------------------------------------------------

    def build_rrule(self):
        """Parse the stored RRULE (with the model-level bound applied) into a
        dateutil rrule anchored at dtstart."""
        from datetime import datetime, time as dt_time
        from dateutil.rrule import rrulestr

        rule = self.rrule.strip()
        upper = rule.upper()
        if self.count and 'COUNT=' not in upper and 'UNTIL=' not in upper:
            rule = f"{rule};COUNT={self.count}"
        elif self.until_date and 'UNTIL=' not in upper and 'COUNT=' not in upper:
            rule = f"{rule};UNTIL={self.until_date.strftime('%Y%m%d')}T235959"
        dtstart = datetime.combine(self.dtstart_date,
                                   self.dtstart_time or dt_time(9, 0))
        return rrulestr(rule, dtstart=dtstart)

    def occurrence_dates(self, through=None):
        """All occurrence dates up to ``through`` (and the end bound)."""
        dates = []
        for occurrence in self.build_rrule():
            occ_date = occurrence.date()
            if self.until_date and occ_date > self.until_date:
                break
            if through and occ_date > through:
                break
            dates.append(occ_date)
        return dates

    def materialize_occurrences(self, through=None, actor=None):
        """Create Event rows for occurrences up to the horizon.

        Idempotent: existing (series, occurrence_date) rows are kept —
        including exceptions — so re-running only fills gaps. Occurrence
        scalars are copied from the template (the earliest non-exception
        occurrence, or the draft event the series was created from).
        """
        from datetime import timedelta
        from django.utils import timezone as dj_tz

        if not self.is_active:
            return []
        horizon_days = getattr(settings, 'SERIES_HORIZON_DAYS', 400)
        through = through or (dj_tz.now().date() + timedelta(days=horizon_days))

        template = (self.events.filter(is_series_exception=False)
                    .order_by('start_date').first())
        existing = set(self.events.exclude(series_occurrence_date=None)
                       .values_list('series_occurrence_date', flat=True))
        created = []
        for occ_date in self.occurrence_dates(through=through):
            if occ_date in existing:
                continue
            created.append(Event.objects.create(
                title=self.title_template or (template.title if template else ''),
                type=template.type if template else 'meeting',
                format=template.format if template else '',
                start_date=occ_date,
                start_time=self.dtstart_time,
                end_date=None,
                end_time=template.end_time if template else None,
                timezone=self.timezone,
                location=template.location if template else '',
                description=template.description if template else '',
                legislative_topics=list(template.legislative_topics) if template else [],
                participants=list(template.participants) if template else [],
                status='received',
                series=self,
                series_occurrence_date=occ_date,
                created_by=actor or self.created_by or (template.created_by if template else None),
                modified_by=actor or self.created_by or (template.modified_by if template else None),
            ))
        self.materialized_through = through
        self.save(update_fields=['materialized_through', 'modified'])
        return created

    def regenerate_future(self, from_date=None, actor=None):
        """Series-level edit: drop future NON-EXCEPTION occurrences and
        re-materialize them under the current rule. Exceptions stay."""
        from django.utils import timezone as dj_tz

        from_date = from_date or dj_tz.now().date()
        (self.events
         .filter(series_occurrence_date__gte=from_date, is_series_exception=False)
         .delete())
        return self.materialize_occurrences(actor=actor)

    def activate(self, reviewer=None):
        """Reviewer confirmed rule + end bound → activate and materialize."""
        self.is_active = True
        if reviewer is not None and self.created_by is None:
            self.created_by = reviewer
        self.save()

        # A dateless draft (the review card the series was created from) is
        # adopted as the first occurrence so it doesn't linger beside the
        # materialized rows.
        draft = (self.events
                 .filter(series_occurrence_date=None, start_date=None)
                 .order_by('created').first())
        if draft is not None:
            first_dates = self.occurrence_dates()
            if first_dates:
                draft.start_date = first_dates[0]
                draft.start_time = draft.start_time or self.dtstart_time
                draft.series_occurrence_date = first_dates[0]
                draft.save()

        return self.materialize_occurrences(actor=reviewer)
