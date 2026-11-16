# SPDX-License-Identifier: Apache-2.0
"""
API Serializers for HillDesk.
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.event_management.models import (
    Event, EventChangeHistory, EmailTemplate, ExportTemplate, EventApproval,
    EventAttachment, EventAttachmentVersion,
)
from apps.email_processing.models import EmailProcessing, EmailResponse

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']


class EventAttachmentVersionSerializer(serializers.ModelSerializer):
    """Serializer for a single uploaded revision of an attachment."""

    uploaded_by_name = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = EventAttachmentVersion
        fields = [
            'id', 'version_number', 'content_type', 'file_size', 'scan_status',
            'uploaded_by_name', 'uploaded_at', 'download_url',
        ]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj):
        return obj.uploaded_by.get_full_name() or obj.uploaded_by.username

    def get_download_url(self, obj):
        from django.urls import reverse
        return reverse('api:event-attachment-download', kwargs={
            'event_id': obj.attachment.event_id,
            'attachment_id': obj.attachment_id,
            'version_id': obj.id,
        })


class EventAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for a logical event attachment with its version history."""

    created_by_name = serializers.SerializerMethodField()
    versions = EventAttachmentVersionSerializer(many=True, read_only=True)
    current_version = serializers.SerializerMethodField()

    class Meta:
        model = EventAttachment
        fields = [
            'id', 'event', 'original_filename', 'data_classification', 'source',
            'created', 'created_by_name', 'modified', 'current_version', 'versions',
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.username

    def get_current_version(self, obj):
        version = obj.current_version
        if not version:
            return None
        return EventAttachmentVersionSerializer(version, context=self.context).data


class EventSerializer(serializers.ModelSerializer):
    """Serializer for Event model with full CRUD support."""

    created_by = UserSerializer(read_only=True)
    modified_by = UserSerializer(read_only=True)
    archived_by = UserSerializer(read_only=True)

    # Add computed properties
    is_upcoming = serializers.ReadOnlyField()
    is_past = serializers.ReadOnlyField()
    has_original_email = serializers.ReadOnlyField()
    start_datetime = serializers.ReadOnlyField()
    end_datetime = serializers.ReadOnlyField()

    # Legacy contact/org fields are now READ-ONLY properties derived from the
    # normalized Contact/Organization models (kept so existing UI keeps working).
    group = serializers.ReadOnlyField()
    point_of_contact_name = serializers.ReadOnlyField()
    point_of_contact_email = serializers.ReadOnlyField()
    point_of_contact_phone = serializers.ReadOnlyField()

    # Structured normalized data for the event modal.
    contacts = serializers.SerializerMethodField()
    organizations = serializers.SerializerMethodField()

    # Email data (computed from EmailProcessing records)
    attached_emails_data = serializers.SerializerMethodField()

    # Uploaded file attachments (with version history)
    attachments = EventAttachmentSerializer(many=True, read_only=True)

    # Approval records for review routing display
    approvals = serializers.SerializerMethodField()

    # Permission info for current user
    can_edit = serializers.SerializerMethodField()
    can_change_status = serializers.SerializerMethodField()

    # Recurrence (email ingestion): pending series info for the confirm block
    series_info = serializers.SerializerMethodField()

    def get_series_info(self, obj):
        """Series membership for the recurrence confirm block (ingestion spec
        §10.4): the review UI needs the rule and whether an end bound is still
        required before the series can activate."""
        if obj.series_id is None:
            return None
        series = obj.series
        return {
            'id': str(series.id),
            'rrule': series.rrule,
            'is_active': series.is_active,
            'until_date': series.until_date.isoformat() if series.until_date else None,
            'count': series.count,
            'needs_end': not (series.until_date or series.count),
            'occurrence_date': (obj.series_occurrence_date.isoformat()
                                if obj.series_occurrence_date else None),
            'is_exception': obj.is_series_exception,
        }

    def get_attached_emails_data(self, obj):
        """Get complete email data for attached emails."""
        return obj.get_attached_emails_data()

    def get_contacts(self, obj):
        """Normalized contacts linked to this event (via EventContact).

        Includes the full email/phone child lists so the event modal can render
        editable cards (not just the primary value).
        """
        return [
            {
                'id': str(link.contact_id),
                'name': link.contact.name,
                'position': link.contact.position or '',
                'email': link.contact.primary_email,
                'phone': link.contact.primary_phone,
                'emails': [
                    {'id': str(e.id), 'email': e.email, 'is_primary': e.is_primary}
                    for e in link.contact.email_addresses.all()
                ],
                'phones': [
                    {'id': str(p.id), 'phone': p.phone, 'is_primary': p.is_primary}
                    for p in link.contact.phone_numbers.all()
                ],
                'organizations': [
                    {'id': str(o.id), 'name': o.name}
                    for o in link.contact.organizations.all()
                ],
                'primary_organization_id': (str(link.contact.primary_organization_id)
                                            if link.contact.primary_organization_id else None),
                'notes': link.contact.notes or '',
                'role': link.role,
                'is_primary': link.is_primary,
            }
            for link in obj.contact_links.select_related('contact').all()
        ]

    def get_organizations(self, obj):
        """Normalized organizations linked to this event (via EventOrganization)."""
        return [
            {
                'id': str(link.organization_id),
                'name': link.organization.name,
                'location': link.organization.location or '',
                'emails': [
                    {'id': str(e.id), 'email': e.email, 'is_primary': e.is_primary}
                    for e in link.organization.email_addresses.all()
                ],
                'phones': [
                    {'id': str(p.id), 'phone': p.phone, 'is_primary': p.is_primary}
                    for p in link.organization.phone_numbers.all()
                ],
                'members': [
                    {'id': str(c.id), 'name': c.name, 'email': c.primary_email}
                    for c in link.organization.contacts.all()
                ],
                'primary_contact_id': (str(link.organization.primary_contact_id)
                                       if link.organization.primary_contact_id else None),
                'notes': link.organization.notes or '',
                'is_primary': link.is_primary,
            }
            for link in obj.organization_links.select_related('organization').all()
        ]

    def get_approvals(self, obj):
        """Get approval records for this event's routing display."""
        approvals = EventApproval.objects.filter(event=obj).select_related('approver')
        return [
            {
                'stage_id': a.stage_id,
                'approver_id': str(a.approver_id),
                'approver_name': a.approver.get_display_name(),
                'status': a.status,
                'decided_at': a.decided_at.isoformat() if a.decided_at else None,
                'comment': a.comment or '',
            }
            for a in approvals
        ]

    def get_can_edit(self, obj):
        """Check if the current user can edit this event."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False

        from apps.authentication.permissions import Permissions
        can_edit = Permissions.can_edit_event(request.user, obj)

        # Debug logging
        import logging
        logger = logging.getLogger('apps.api')
        logger.debug(
            f'can_edit check: user={request.user.username}, role={getattr(request.user, "role", "unknown")}, '
            f'event={obj.id}, staff={obj.staff}, can_edit={can_edit}'
        )

        return can_edit

    def get_can_change_status(self, obj):
        """Check if the current user can change event status (admin/scheduler only)."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        from apps.authentication.permissions import Permissions
        return Permissions.can_change_status(request.user)

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'type', 'format', 'duration', 'start_date', 'start_time',
            'end_date', 'end_time', 'timezone', 'time_notes', 'is_date_range',
            'is_longer_than_day', 'location', 'group', 'description', 'tags',
            'legislative_topics', 'participants', 'expected_attendees',
            'point_of_contact_name', 'point_of_contact_email', 'point_of_contact_phone',
            'contacts', 'organizations',
            'staff', 'primary_staff', 'approval_routing', 'approvals', 'reminder_enabled', 'reminder_time', 'notes',
            'status', 'attached_email_ids', 'attached_emails_data', 'attachments', 'original_email_id', 'outlook_calendar_event_id',
            'data_classification', 'is_archived', 'archived_date', 'archived_by',
            'created', 'created_by', 'modified', 'modified_by', 'is_upcoming',
            'is_past', 'has_original_email', 'start_datetime', 'end_datetime',
            # Human Review fields
            'requires_human_review', 'extracted_fields',
            'review_decision', 'dismissed_at', 'dismissed_by',
            # Recurrence (email ingestion)
            'series_info',
            # Permission info
            'can_edit', 'can_change_status'
        ]
        read_only_fields = [
            'id', 'created', 'created_by', 'modified', 'modified_by',
            'is_upcoming', 'is_past', 'has_original_email', 'start_datetime',
            'end_datetime', 'archived_date', 'archived_by', 'attached_emails_data',
            # contact/org fields are normalized; read-only here, managed via contacts API
            'group', 'point_of_contact_name', 'point_of_contact_email',
            'point_of_contact_phone', 'contacts', 'organizations',
            # review_decision/dismissal are managed via the dedicated dismiss endpoint
            'review_decision', 'dismissed_at', 'dismissed_by',
            # approval_routing is managed via dedicated API endpoint to prevent accidental overwrites
            'approval_routing', 'can_edit', 'can_change_status'
        ]
    
    def validate_legislative_topics(self, value):
        """Validate legislative_topics is a list."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Legislative topics must be a list.")
        return value
    
    def validate_participants(self, value):
        """Validate participants is a list."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Participants must be a list.")
        return value
    
    def validate_staff(self, value):
        """Validate staff is a list."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Staff must be a list.")
        return value
    
    def validate_tags(self, value):
        """Validate tags is a list."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Tags must be a list.")
        return value
    
    def validate_approval_routing(self, value):
        """Validate approval_routing is a dictionary."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Approval routing must be a dictionary.")
        return value
    
    def validate_attached_email_ids(self, value):
        """Validate attached_email_ids is a list of valid EmailProcessing IDs."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Attached email IDs must be a list.")
        
        # Validate each ID is a valid UUID string
        from uuid import UUID
        
        for i, email_id in enumerate(value):
            try:
                # Try to convert to UUID to validate format
                UUID(str(email_id))
            except (ValueError, TypeError):
                raise serializers.ValidationError(f"Email ID at index {i} is not a valid UUID.")
        
        return value
    
    def validate(self, data):
        """Validate event data with flexible validation for autosave."""
        from datetime import datetime, timedelta
        
        # For autosave, we want to be more lenient with validation
        # Only validate if we have complete date/time information
        start_date = data.get('start_date')
        start_time = data.get('start_time')
        end_date = data.get('end_date')
        end_time = data.get('end_time')
        
        # Only validate if all date/time fields are present
        if all([start_date, start_time, end_date, end_time]):
            try:
                start_datetime = datetime.combine(start_date, start_time)
                end_datetime = datetime.combine(end_date, end_time)
                
                # If end is not after start, automatically adjust it
                if end_datetime <= start_datetime:
                    # Adjust end time to be 1 hour after start time
                    adjusted_end = start_datetime + timedelta(hours=1)
                    data['end_date'] = adjusted_end.date()
                    data['end_time'] = adjusted_end.time()
                    
                    # Log the adjustment for debugging
                    import logging
                    logger = logging.getLogger('apps.api')
                    logger.info(f"Auto-adjusted end time from {end_datetime} to {adjusted_end}")
                    
            except (ValueError, TypeError) as e:
                # If there's an error with date/time parsing, just log it and continue
                import logging
                logger = logging.getLogger('apps.api')
                logger.warning(f"Date/time validation error (continuing anyway): {e}")
        
        # Validate dates only (without times) if provided
        elif start_date and end_date and end_date < start_date:
            # Adjust end date to match start date
            data['end_date'] = start_date
        
        return data
    
    def create(self, validated_data):
        """Create event with audit trail."""
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
            validated_data['modified_by'] = request.user
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Update event with audit trail."""
        request = self.context.get('request')
        if request and request.user:
            validated_data['modified_by'] = request.user
            
            # Track changes for audit
            for field, new_value in validated_data.items():
                if field in ['created_by', 'modified_by']:
                    continue
                    
                old_value = getattr(instance, field, None)
                if old_value != new_value:
                    EventChangeHistory.objects.create(
                        event=instance,
                        user=request.user,
                        field=field,
                        old_value=str(old_value) if old_value is not None else '',
                        new_value=str(new_value) if new_value is not None else '',
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')
                    )
        
        return super().update(instance, validated_data)


class EventListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for event lists."""

    created_by = serializers.StringRelatedField()
    modified_by = serializers.StringRelatedField()
    archived_by = serializers.StringRelatedField()
    start_datetime = serializers.ReadOnlyField()
    staff = serializers.SerializerMethodField()
    member_of_congress = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_change_status = serializers.SerializerMethodField()
    # Derived from normalized Contact/Organization models (read-only).
    group = serializers.ReadOnlyField()
    point_of_contact_name = serializers.ReadOnlyField()
    # Minimal normalized contact/org lists for the spreadsheet's primary +
    # "involved parties / involved orgs" columns (clickable → read-only popup).
    contacts = serializers.SerializerMethodField()
    organizations = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'type', 'format', 'timezone', 'start_date', 'start_time',
            'end_date', 'end_time', 'location', 'group', 'status', 'description',
            'point_of_contact_name', 'contacts', 'organizations',
            'created', 'created_by',
            'modified', 'modified_by', 'start_datetime', 'staff', 'primary_staff',
            'member_of_congress', 'tags',
            'requires_human_review', 'review_decision', 'dismissed_at',
            'can_edit', 'can_change_status',
            'is_archived', 'archived_date', 'archived_by'
        ]

    def get_contacts(self, obj):
        """Minimal contacts (id/name/is_primary) for the involved-parties column."""
        return [
            {'id': str(link.contact_id), 'name': link.contact.name,
             'is_primary': link.is_primary}
            for link in obj.contact_links.all()
        ]

    def get_organizations(self, obj):
        """Minimal organizations (id/name/is_primary) for the involved-orgs column."""
        return [
            {'id': str(link.organization_id), 'name': link.organization.name,
             'is_primary': link.is_primary}
            for link in obj.organization_links.all()
        ]

    def get_staff(self, obj):
        """Return list of staff names assigned to this event."""
        # Staff is stored as a JSON list (not a ManyToMany relation)
        if hasattr(obj, 'staff') and obj.staff:
            if isinstance(obj.staff, list):
                return obj.staff
        return []

    def get_member_of_congress(self, obj):
        """Return the Member of Congress's name if they are assigned to this event.

        Staff is stored as a JSON list of names; an OfficeStaff row flagged
        ``is_member_of_congress`` identifies the Member. The lookup is memoized
        per office so rendering a list of events stays a single extra query.
        """
        staff = obj.staff if isinstance(obj.staff, list) else []
        if not staff:
            return None
        office = obj.get_office()
        if not office:
            return None
        cache = getattr(self, '_moc_name_cache', None)
        if cache is None:
            cache = {}
            self._moc_name_cache = cache
        if office.id not in cache:
            moc = office.staff_members.filter(is_member_of_congress=True).first()
            cache[office.id] = moc.name if moc else None
        moc_name = cache[office.id]
        return moc_name if moc_name and moc_name in staff else None

    def get_can_edit(self, obj):
        """Check if the current user can edit this event."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        from apps.authentication.permissions import Permissions
        return Permissions.can_edit_event(request.user, obj)

    def get_can_change_status(self, obj):
        """Check if the current user can change event status (admin/scheduler only)."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        from apps.authentication.permissions import Permissions
        return Permissions.can_change_status(request.user)


class EventChangeHistorySerializer(serializers.ModelSerializer):
    """Serializer for Event change history."""
    
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = EventChangeHistory
        fields = [
            'id', 'timestamp', 'user', 'field', 'old_value', 'new_value',
            'ip_address', 'user_agent'
        ]
        read_only_fields = ['id', 'timestamp']


class EmailProcessingSerializer(serializers.ModelSerializer):
    """Serializer for EmailProcessing model with streamlined email storage."""
    
    processed_by = UserSerializer(read_only=True)
    event = EventListSerializer(read_only=True)
    
    # Email data fields
    email_type = serializers.SerializerMethodField()
    email_preview = serializers.ReadOnlyField()
    has_complete_data = serializers.SerializerMethodField()
    
    class Meta:
        model = EmailProcessing
        fields = [
            'id', 'email_id', 'subject', 'sender', 'sender_name', 'received',
            'is_scheduling_request', 'confidence', 'complete_email_data', 'extracted_data', 
            'processed', 'status', 'event', 'error_message', 'data_classification', 
            'processed_by', 'email_type', 'email_preview', 'has_complete_data'
        ]
        read_only_fields = [
            'id', 'processed', 'processed_by', 'event', 'email_type', 
            'email_preview', 'has_complete_data'
        ]
    
    def get_email_type(self, obj):
        """Get email type from complete_email_data."""
        return obj.get_email_type()
    
    def get_has_complete_data(self, obj):
        """Check if email has complete data."""
        return obj.has_complete_email_data()
    
    def validate_complete_email_data(self, value):
        """Validate complete_email_data is a dictionary."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Complete email data must be a dictionary.")
        return value
    
    def validate_extracted_data(self, value):
        """Validate extracted_data is a dictionary."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Extracted data must be a dictionary.")
        return value
    
    def validate_confidence(self, value):
        """Validate confidence is between 0.0 and 1.0."""
        if not (0.0 <= value <= 1.0):
            raise serializers.ValidationError("Confidence must be between 0.0 and 1.0.")
        return value


class EmailResponseSerializer(serializers.ModelSerializer):
    """Serializer for EmailResponse model."""
    
    original_email = EmailProcessingSerializer(read_only=True)
    template_used = serializers.StringRelatedField(read_only=True)
    created_by = UserSerializer(read_only=True)
    modified_by = UserSerializer(read_only=True)
    
    class Meta:
        model = EmailResponse
        fields = [
            'id', 'original_email', 'template_used', 'subject', 'body', 'is_html',
            'sender', 'recipient', 'cc_recipients', 'bcc_recipients', 'status',
            'sent_at', 'scheduled_for', 'outlook_message_id', 'error_message',
            'created', 'created_by', 'modified', 'modified_by'
        ]
        read_only_fields = [
            'id', 'original_email', 'template_used', 'sent_at', 'outlook_message_id',
            'created', 'created_by', 'modified', 'modified_by'
        ]
    
    def validate_cc_recipients(self, value):
        """Validate CC recipients is a list."""
        if not isinstance(value, list):
            raise serializers.ValidationError("CC recipients must be a list.")
        return value
    
    def validate_bcc_recipients(self, value):
        """Validate BCC recipients is a list."""
        if not isinstance(value, list):
            raise serializers.ValidationError("BCC recipients must be a list.")
        return value


class EmailTemplateSerializer(serializers.ModelSerializer):
    """Serializer for EmailTemplate model."""

    created_by = UserSerializer(read_only=True)
    modified_by = UserSerializer(read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = EmailTemplate
        fields = [
            'id', 'name', 'category', 'category_display', 'subject', 'body',
            'variables', 'is_default', 'is_active', 'is_html', 'office',
            'created', 'created_by', 'modified', 'modified_by'
        ]
        read_only_fields = [
            'id', 'office', 'created', 'created_by', 'modified', 'modified_by'
        ]

    def validate_variables(self, value):
        """Validate variables is a list."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Variables must be a list.")
        return value


class ExportTemplateSerializer(serializers.ModelSerializer):
    """Serializer for ExportTemplate model."""

    created_by = UserSerializer(read_only=True)
    modified_by = UserSerializer(read_only=True)
    template_type_display = serializers.CharField(
        source='get_template_type_display', read_only=True
    )

    class Meta:
        model = ExportTemplate
        fields = [
            'id', 'name', 'template_type', 'template_type_display',
            'docx_file', 'is_default', 'office',
            'created_at', 'created_by', 'updated_at', 'modified_by',
        ]
        read_only_fields = [
            'id', 'office', 'is_default',
            'created_at', 'created_by', 'updated_at', 'modified_by',
        ]


class GraphEmailSerializer(serializers.Serializer):
    """Serializer for Microsoft Graph email data."""

    id = serializers.CharField()
    subject = serializers.CharField()
    sender = serializers.DictField()
    toRecipients = serializers.ListField(child=serializers.DictField(), required=False)
    ccRecipients = serializers.ListField(child=serializers.DictField(), required=False)
    bccRecipients = serializers.ListField(child=serializers.DictField(), required=False)
    receivedDateTime = serializers.DateTimeField()
    sentDateTime = serializers.DateTimeField(required=False)
    body = serializers.DictField()
    bodyPreview = serializers.CharField(required=False)
    hasAttachments = serializers.BooleanField(required=False)
    importance = serializers.CharField(required=False)
    isRead = serializers.BooleanField(required=False)
    conversationId = serializers.CharField(required=False)
    
    def to_representation(self, instance):
        """Convert Graph API email to simplified format."""
        data = super().to_representation(instance)
        
        # Simplify sender information
        if 'sender' in data and 'emailAddress' in data['sender']:
            sender_info = data['sender']['emailAddress']
            data['sender_email'] = sender_info.get('address', '')
            data['sender_name'] = sender_info.get('name', '')
        
        # Simplify body content
        if 'body' in data:
            body_info = data['body']
            data['body_content'] = body_info.get('content', '')
            data['body_type'] = body_info.get('contentType', 'text')
        
        # Convert datetime strings to ISO format
        for field in ['receivedDateTime', 'sentDateTime']:
            if field in data and data[field]:
                if isinstance(data[field], str):
                    # Already a string, keep as is
                    pass
                else:
                    # Convert datetime object to ISO string
                    data[field] = data[field].isoformat()
        
        return data


class SmartExtractSuggestionSerializer(serializers.Serializer):
    """Serializer for AI SmartExtract suggestions."""
    
    field = serializers.CharField()
    value = serializers.JSONField()
    confidence = serializers.FloatField(min_value=0.0, max_value=1.0)
    source_email_id = serializers.CharField()
    source_text_range = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=2,
        max_length=2
    )
    reasoning = serializers.CharField(required=False)
    
    def validate_source_text_range(self, value):
        """Validate source text range has start and end positions."""
        if len(value) != 2:
            raise serializers.ValidationError("Source text range must have start and end positions.")
        
        start, end = value
        if start >= end:
            raise serializers.ValidationError("Start position must be less than end position.")
        
        if start < 0 or end < 0:
            raise serializers.ValidationError("Positions must be non-negative.")
        
        return value


def build_email_groups(event):
    """Group an event's attached emails by conversation thread for the modal.

    Returns a dict with `email_threads` (each a conversation block with its own
    reply target) and `standalone_emails` (off-thread messages attached
    directly). Each serialized email is annotated with `also_on_events` so the
    UI can flag emails shared with other events.
    """
    groups = event.get_email_groups()

    def serialize_email(email):
        data = EmailProcessingSerializer(email).data
        data['also_on_events'] = [
            {'id': str(e.id), 'title': e.title}
            for e in event.other_events_for_email(email)
        ]
        return data

    email_threads = []
    for group in groups['threads']:
        thread = group['thread']
        msgs = group['emails']
        email_threads.append({
            'conversation_id': thread.conversation_id,
            'subject': thread.subject or (msgs[0].subject if msgs else ''),
            'participants': thread.participants,
            'message_count': len(msgs),
            'last_message_at': msgs[-1].received if msgs else thread.last_message_at,
            # Replies go out on this thread's most recent attached message.
            'reply_to_email_id': str(msgs[-1].id) if msgs else None,
            'emails': [serialize_email(m) for m in msgs],
        })

    standalone_emails = [serialize_email(email) for email in groups['standalone']]
    return {'email_threads': email_threads, 'standalone_emails': standalone_emails}


class EventEditingPanelDataSerializer(serializers.Serializer):
    """Serializer for complete event editing panel data."""

    event = EventSerializer()
    related_emails = EmailProcessingSerializer(many=True)
    change_history = EventChangeHistorySerializer(many=True)
    ai_suggestions = SmartExtractSuggestionSerializer(many=True, required=False)
    email_templates = EmailTemplateSerializer(many=True)
    smartextract_enabled = serializers.BooleanField(default=False)

    def to_representation(self, instance):
        """Custom representation for panel data."""
        # instance should be a dictionary with all the required data
        event = instance['event']
        data = {
            'event': EventSerializer(event).data,
            'related_emails': EmailProcessingSerializer(instance['related_emails'], many=True).data,
            'change_history': EventChangeHistorySerializer(instance['change_history'], many=True).data,
            'ai_suggestions': instance.get('ai_suggestions', []),
            'email_templates': EmailTemplateSerializer(instance['email_templates'], many=True).data,
            'smartextract_enabled': instance.get('smartextract_enabled', False),
        }
        # Thread-grouped view for the redesigned email panel.
        data.update(build_email_groups(event))
        return data