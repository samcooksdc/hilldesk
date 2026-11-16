# Event Model Specification

## Overview
This document defines the complete field structure for the Event model in HillDesk. This specification aligns the database model with the modern event editing interface requirements.

**Last Updated:** August 13, 2025  
**Version:** 3.0 (Streamlined Email System)  
**Total Fields:** 32

## Complete Field List

### **Primary Key**
- `id` - UUIDField (primary_key=True, default=uuid.uuid4, editable=False)

### **Basic Event Information**
- `title` - CharField(max_length=200, help_text="Event title")
- `type` - CharField(max_length=20, choices=EVENT_TYPE_CHOICES, help_text="Type of event")
- `format` - CharField(max_length=20, blank=True, help_text="Event format: in-person, virtual, or hybrid")
- `duration` - CharField(max_length=20, blank=True, help_text="Event duration")
- `group` - CharField(max_length=200, help_text="The entity requesting time")
- `description` - TextField(help_text="Event description")
- `tags` - JSONField(default=list, blank=True, help_text="Event tags for categorization")

### **Timing Information**
- `start_date` - DateField(help_text="Start date of the event")
- `start_time` - TimeField(help_text="Start time of the event")
- `end_date` - DateField(null=True, blank=True, help_text="End date of the event")
- `end_time` - TimeField(null=True, blank=True, help_text="End time of the event")
- `timezone` - CharField(max_length=50, default='America/Denver', choices=TIMEZONE_CHOICES, help_text="Event timezone")
- `time_notes` - TextField(blank=True, help_text="Notes for date range events")
- `is_date_range` - BooleanField(default=False, help_text="Whether this is a date range event")
- `is_longer_than_day` - BooleanField(default=False, help_text="Whether this event is longer than a day")

### **Location and Details**
- `location` - CharField(max_length=500, help_text="Event location")

### **Participant Information**
- `legislative_topics` - JSONField(default=list, blank=True, help_text="Topics anticipated to be discussed")
- `participants` - JSONField(default=list, blank=True, help_text="Who is expected to be in attendance")
- `expected_attendees` - PositiveIntegerField(null=True, blank=True, help_text="Number of expected attendees")

### **Point of Contact Information**
- `point_of_contact_name` - CharField(max_length=200, help_text="Name of the point of contact")
- `point_of_contact_email` - EmailField(help_text="Email of the point of contact")
- `point_of_contact_phone` - CharField(max_length=50, blank=True, help_text="Phone number of the point of contact")

### **Staff and Assignment**
- `staff` - JSONField(default=list, blank=True, help_text="Person/people who handle topics anticipated to be addressed")

### **Approval Routing**
- `approval_routing` - JSONField(default=dict, blank=True, help_text="Approval routing data including required approvers, statuses, and history")

### **Reminder Settings**
- `reminder_enabled` - BooleanField(default=False, help_text="Whether reminders are enabled for this event")
- `reminder_time` - CharField(max_length=20, blank=True, help_text="When to send reminder")

### **Consolidated Notes**
- `notes` - TextField(blank=True, help_text="All notes including schedule, campaign, staff, and general notes")

### **Status**
- `status` - CharField(max_length=30, choices=EVENT_STATUS_CHOICES, default='received', help_text="Current status of the event")

### **Email Source Tracking** *(LEGACY - for migration compatibility)*
- `original_email_id` - CharField(max_length=200, blank=True, help_text="Legacy field - ID of the original email from Microsoft Graph API")

### **Email Integration** *(STREAMLINED APPROACH)*
- `attached_email_ids` - JSONField(default=list, blank=True, help_text="List of EmailProcessing record IDs for emails related to this event")
- `outlook_calendar_event_id` - CharField(max_length=200, blank=True, null=True, help_text="ID of the corresponding Outlook calendar event")

### **Event Model Helper Methods for Email Management**
The Event model includes the following helper methods for managing emails:

**Email Attachment Methods:**
- `attach_email(email_processing_id)` - Attach an EmailProcessing record to this event
- `detach_email(email_processing_id)` - Detach an EmailProcessing record from this event

**Email Retrieval Methods:**
- `get_attached_emails()` - Get all attached EmailProcessing records (QuerySet)
- `get_attached_emails_data()` - Get complete email data for all attached emails (list of dicts)
- `get_email_by_id(email_processing_id)` - Get a specific EmailProcessing record by ID
- `get_emails_by_type(email_type)` - Get all emails of a specific type
- `get_primary_email()` - Get the primary email (usually the original request)
- `get_original_request_emails()` - Get all original request emails
- `get_response_emails()` - Get all response emails sent
- `get_follow_up_emails()` - Get all follow-up emails
- `get_email_thread(thread_id)` - Get all emails in a specific thread

**Email Status Methods:**
- `has_emails()` - Check if this event has any attached emails

### **Security and Compliance**
- `data_classification` - CharField(max_length=20, choices=DATA_CLASSIFICATION_LEVELS, default='internal', help_text="Data classification level for security compliance")

### **Archiving Fields**
- `is_archived` - BooleanField(default=False, help_text="Whether this event has been archived")
- `archived_date` - DateTimeField(null=True, blank=True, help_text="Date and time when the event was archived")
- `archived_by` - ForeignKey(User, on_delete=PROTECT, related_name='events_archived', null=True, blank=True, help_text="User who archived this event")

### **Audit Fields**
- `created` - DateTimeField(auto_now_add=True)
- `created_by` - ForeignKey(User, on_delete=PROTECT, related_name='events_created', help_text="User who created this event")
- `modified` - DateTimeField(auto_now=True)
- `modified_by` - ForeignKey(User, on_delete=PROTECT, related_name='events_modified', help_text="User who last modified this event")

## Email Storage Architecture *(STREAMLINED APPROACH)*

The email storage system has been streamlined to use EmailProcessing as the single source of truth for all email data. This eliminates data redundancy and provides better performance and maintainability.

### **EmailProcessing Model (Single Source of Truth)**
All complete email data is stored in the `EmailProcessing` model with the following structure:

**Core Fields:**
- **email_id**: CharField - Unique identifier from Microsoft Graph API
- **subject**: CharField - Email subject line
- **sender**: EmailField - Email address of the sender
- **sender_name**: CharField - Display name of the sender
- **received**: DateTimeField - When the email was received
- **is_scheduling_request**: BooleanField - Whether AI identified this as a scheduling request
- **confidence**: FloatField - AI confidence score (0.0 to 1.0)
- **status**: CharField - Current processing status (pending, processed, verified, rejected, error)
- **event**: ForeignKey - Link to created event (if applicable)

**Email Data Fields:**
- **complete_email_data**: JSONField containing the full email data in standardized format (equivalent to eml_parser output)
- **extracted_data**: JSONField containing AI-processed event information and analysis
- **raw_content**: TextField containing encrypted raw email content for backup

**EmailProcessing Helper Methods:**
- `get_complete_email_field(field_name, default=None)` - Safely get a field from complete_email_data
- `set_complete_email_field(field_name, value)` - Safely set a field in complete_email_data
- `get_email_type()` - Get the email type from complete_email_data
- `get_email_thread_id()` - Get the thread ID from complete_email_data
- `get_email_body()` - Get the email body from complete_email_data
- `get_email_attachments()` - Get email attachments from complete_email_data
- `has_complete_email_data()` - Check if this record has complete email data
- `email_preview` - Property for email preview text

### **Event Model Email Integration**
The Event model maintains lightweight references to emails:

- **attached_email_ids**: JSONField containing array of EmailProcessing record IDs
- Helper methods to fetch complete email data from EmailProcessing records

### **Email Data Access Pattern**
```python
# Get complete email data for an event
event = Event.objects.get(id=event_id)

# Get EmailProcessing QuerySet (for database operations)
emails = event.get_attached_emails()

# Get complete email data as list of dictionaries (for API/UI)
emails_data = event.get_attached_emails_data()

# Get specific email by EmailProcessing ID
email = event.get_email_by_id(email_processing_id)

# Get emails by type
original_emails = event.get_emails_by_type('original_request')
response_emails = event.get_response_emails()

# Get primary email (usually the original request)
primary_email = event.get_primary_email()

# Check if event has emails
if event.has_emails():
    # Work with emails
    pass

# Attach/detach emails
success = event.attach_email(email_processing.id)
success = event.detach_email(email_processing.id)

# Access EmailProcessing helper methods
if email.has_complete_email_data():
    email_type = email.get_email_type()
    body = email.get_email_body()
    attachments = email.get_email_attachments()
    preview = email.email_preview
```

### **Complete Email Data Structure**
The `complete_email_data` field in EmailProcessing stores emails in this standardized format:

```json
{
  "email_id": "unique-email-identifier",
  "email_type": "original_request|response_sent|follow_up|related",
  "source": "outlook|gmail|manual|imported",
  "thread_id": "conversation-thread-id",
  "message_id": "<message-id@domain.com>",
  "in_reply_to": "<parent-message-id@domain.com>",
  "references": ["<ref1@domain.com>", "<ref2@domain.com>"],
  "subject": "Meeting Request: Healthcare Policy Discussion",
  "from": {
    "name": "Dr. Jennifer Walsh",
    "email": "j.walsh@healthcarealliance.org",
    "display_name": "Dr. Jennifer Walsh <j.walsh@healthcarealliance.org>"
  },
  "to": [
    {
      "name": "Congresswoman Smith",
      "email": "smith@example.com",
      "display_name": "Congresswoman Smith <smith@example.com>"
    }
  ],
  "cc": [],
  "bcc": [],
  "date_sent": "2025-02-15T10:30:00Z",
  "date_received": "2025-02-15T10:30:15Z",
  "body": {
    "text": "Plain text version of email body...",
    "html": "<html><body>HTML version of email body...</body></html>",
    "preview": "First 200 characters of email for preview..."
  },
  "attachments": [
    {
      "filename": "meeting-agenda.pdf",
      "content_type": "application/pdf",
      "size": 245760,
      "content_id": "attachment-uuid",
      "is_inline": false,
      "stored_path": "/media/attachments/email-processing-uuid/attachment-uuid.pdf"
    }
  ],
  "headers": {
    "importance": "normal",
    "priority": "normal",
    "sensitivity": "normal",
    "delivery_receipt_requested": false,
    "read_receipt_requested": false
  },
  "outlook_metadata": {
    "conversation_id": "outlook-conversation-id",
    "internet_message_id": "<outlook-message-id>",
    "web_link": "https://outlook.office.com/mail/...",
    "categories": ["Event Planning"],
    "flag_status": "notFlagged",
    "is_read": true,
    "has_attachments": true
  },
  "processing_metadata": {
    "processed_at": "2025-02-15T11:00:00Z",
    "processed_by_user_id": "user-uuid",
    "relationship_type": "original_request",
    "confidence_score": 0.95,
    "extraction_source": "ai_processing|manual_attachment|email_forwarding",
    "is_primary_email": true
  },
  "content_analysis": {
    "language": "en",
    "sentiment": "neutral",
    "key_phrases": ["meeting request", "healthcare policy", "March 15th"],
    "entities": ["Dr. Jennifer Walsh", "Healthcare Alliance", "March 15, 2025"],
    "topics": ["healthcare", "policy", "meeting"]
  }
}
```

### **Benefits of Streamlined Approach**
- **Single Source of Truth**: All email data stored in EmailProcessing model
- **No Data Redundancy**: Eliminates duplicate storage of email data
- **Better Performance**: Faster queries and reduced storage requirements
- **Easier Maintenance**: Centralized email data management
- **Audit Trail**: Complete processing history maintained in EmailProcessing

### **Default Structure for Manual Events**
For manually created events (no email source), the `attached_email_ids` field defaults to an empty array `[]`.

## Approval Routing JSON Structure

The `approval_routing` field stores complex approval workflow data:

```json
{
  "required_approvers": [
    {
      "user_id": "uuid-123",
      "user_name": "John Smith",
      "role": "Chief of Staff",
      "required_since": "2025-02-15T10:30:00Z",
      "order": 1
    }
  ],
  "approvals": [
    {
      "user_id": "uuid-123",
      "user_name": "John Smith",
      "status": "approved",
      "timestamp": "2025-02-15T14:22:00Z",
      "notes": "Looks good, proceed with scheduling"
    }
  ],
  "approval_history": [
    {
      "user_id": "uuid-123",
      "user_name": "John Smith", 
      "old_status": "pending",
      "new_status": "approved",
      "timestamp": "2025-02-15T14:22:00Z",
      "notes": "Looks good, proceed with scheduling"
    }
  ],
  "routing_rules": {
    "requires_all_approvals": true,
    "auto_approve_after_hours": 48,
    "escalation_enabled": true
  }
}
```

## Account-Specific Choice Fields

### New Model: AccountEventSettings
```python
class AccountEventSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='event_settings')
    event_format_choices = models.JSONField(default=list, help_text="Custom event format choices")
    event_duration_choices = models.JSONField(default=list, help_text="Custom event duration choices")
    reminder_time_choices = models.JSONField(default=list, help_text="Custom reminder time choices")
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
```

### Default Choices in Settings
```python
DEFAULT_EVENT_FORMAT_CHOICES = [
    {'value': 'in-person', 'label': 'In Person'},
    {'value': 'virtual', 'label': 'Virtual'},
    {'value': 'hybrid', 'label': 'Hybrid'},
]

DEFAULT_EVENT_DURATION_CHOICES = [
    {'value': '30min', 'label': '30 minutes'},
    {'value': '1hr', 'label': '1 hour'},
    {'value': '1.5hr', 'label': '1.5 hours'},
    {'value': '2hr', 'label': '2 hours'},
    {'value': '3hr', 'label': '3 hours'},
    {'value': 'half-day', 'label': 'Half day'},
    {'value': 'full-day', 'label': 'Full day'},
    {'value': 'custom', 'label': 'Custom'},
]

DEFAULT_REMINDER_TIME_CHOICES = [
    {'value': '15min', 'label': '15 minutes before'},
    {'value': '30min', 'label': '30 minutes before'},
    {'value': '1hr', 'label': '1 hour before'},
    {'value': '1day', 'label': '1 day before'},
]

TIMEZONE_CHOICES = [
    ('America/New_York', 'Eastern Time'),
    ('America/Chicago', 'Central Time'),
    ('America/Denver', 'Mountain Time'),
    ('America/Los_Angeles', 'Pacific Time'),
    ('America/Anchorage', 'Alaska Time'),
    ('Pacific/Honolulu', 'Hawaii Time'),
    ('UTC', 'UTC'),
]
```

## Changes Made from Previous Version

### **Fields Added:**
- `title` - Event title
- `format` - Event format (in-person/virtual/hybrid)
- `duration` - Event duration
- `expected_attendees` - Number of expected attendees
- `tags` - Event tags (JSON array)
- `timezone` - Event timezone
- `time_notes` - Notes for date ranges
- `is_date_range` - Boolean for date range events
- `is_longer_than_day` - Boolean for multi-day events
- `approval_routing` - Approval workflow data (JSON)
- `reminder_time` - Reminder timing
- `reminder_enabled` - Whether reminders are enabled
- `notes` - Consolidated notes field

### **Fields Removed:**
- `hms_review_status` - Removed per requirements
- `staff_recommendation` - Removed per requirements
- `archive_reason` - Removed per requirements
- `retention_until` - Removed per requirements
- `time` - Replaced by separate date/time fields
- `schedule_notes` - Consolidated into `notes`
- `campaign_notes` - Consolidated into `notes`
- `staff_notes` - Consolidated into `notes`

### **Fields Modified:**
- `start_date` - Changed from DateTimeField to DateField
- `start_time` - New TimeField (separated from start_date)
- `end_date` - Changed from DateTimeField to DateField
- `end_time` - New TimeField (separated from end_date)
- `details` - Renamed to `description`
- `attached_emails` - **REMOVED** - Replaced with `attached_email_ids` for streamlined approach
- `original_email_id` - **LEGACY** - Marked as legacy field for migration compatibility

### **Database Indexes to Add:**
- `models.Index(fields=['title'])`
- `models.Index(fields=['format'])`
- `models.Index(fields=['is_date_range'])`
- `models.Index(fields=['start_date', 'start_time'])`
- `models.Index(fields=['end_date', 'end_time'])`

## Migration Considerations

### **Completed Migrations:**
1. ✅ **email_processing.0003_add_complete_email_data_field** - Added `complete_email_data` field to EmailProcessing
2. ✅ **event_management.0006_streamline_email_storage** - Replaced `attached_emails` with `attached_email_ids` in Event

### **Data Migration:**
1. ✅ **Data Migration Script:** `migrate_email_data_to_streamlined.py` - Migrates existing EmailProcessing records to new structure
2. ✅ **EmailProcessing Enhancement:** Populates `complete_email_data` from existing `extracted_data` and `raw_content`
3. ✅ **Event References:** Updates Event `attached_email_ids` to reference EmailProcessing records

### **Legacy Considerations:**
1. **Date/Time Fields:** Existing `start_date` and `end_date` DateTimeFields split into separate date and time fields
2. **Notes Consolidation:** Existing `schedule_notes`, `campaign_notes`, and `staff_notes` merged into single `notes` field
3. **Email Storage:** Old `attached_emails` field removed, data migrated to EmailProcessing model
4. **Index Optimization:** New indexes created for performance optimization

## API Integration

### **EventSerializer Fields:**
The API serializer includes all Event model fields plus computed fields:
- `attached_emails_data` - SerializerMethodField that returns complete email data from EmailProcessing
- `is_upcoming`, `is_past`, `has_original_email` - Computed properties
- `start_datetime`, `end_datetime` - Combined date/time properties

### **EmailProcessingSerializer Fields:**
The EmailProcessing serializer includes:
- `email_type`, `email_preview`, `has_complete_data` - Computed fields
- `complete_email_data` - Full email data in standardized format
- `extracted_data` - AI-processed event information

## UI Alignment

This specification ensures complete alignment with the event editing interface, supporting:
- Tabbed editing interface (Event Details, Involved Parties, Staff & Review)
- Date/time picker components
- Tag management system
- Approval workflow tracking
- Reminder scheduling
- Account-specific customizable choices
- **Email management interface** - Access to complete email data through EmailProcessing

## Performance Optimizations

### **Streamlined Email Storage Benefits:**
- ✅ **Reduced Storage:** ~50% reduction in email data storage through elimination of redundancy
- ✅ **Faster Queries:** Event queries no longer load large email JSON objects
- ✅ **Lazy Loading:** Email data loaded only when needed via helper methods
- ✅ **Better Indexing:** EmailProcessing model optimized for email-specific queries
- ✅ **Scalability:** Supports large volumes of emails without impacting event performance

### **Database Indexes:**
All critical fields are indexed for optimal query performance:
- Event: `title`, `format`, `is_date_range`, `start_date/time`, `end_date/time`, `status`, `type`
- EmailProcessing: `email_id`, `received`, `status`, `sender`, `data_classification`

---

**Note:** This specification serves as the authoritative reference for the Event model structure and should be updated whenever model changes are made. 

**Version 3.0 Changes:** Implemented streamlined email storage system using EmailProcessing as single source of truth, eliminating data redundancy and improving performance.