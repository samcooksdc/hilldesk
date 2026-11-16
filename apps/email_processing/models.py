# SPDX-License-Identifier: Apache-2.0
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
import uuid

from apps.authentication.fields import EncryptedCharField, EncryptedTextField
from apps.contacts.crypto import email_blind_index

User = get_user_model()


class EmailProcessing(models.Model):
    """
    Model for tracking email processing and AI extraction results.
    """
    
    # Processing status choices
    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
        # Set by the ingestion pipeline when a message needs human triage before
        # any extraction (auth failure, digest suspect, rate-gate burst, …).
        ('escalated', 'Escalated'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Email identification
    email_id = models.CharField(
        max_length=200,
        unique=True,
        help_text="Unique identifier from Microsoft Graph API"
    )
    
    subject = models.CharField(
        max_length=1000,
        help_text="Email subject line"
    )
    
    sender = models.EmailField(
        help_text="Email address of the sender"
    )
    
    sender_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Display name of the sender"
    )
    
    received = models.DateTimeField(
        help_text="When the email was received"
    )
    
    # AI processing results
    is_scheduling_request = models.BooleanField(
        default=False,
        help_text="Whether AI identified this as a scheduling request"
    )
    
    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="AI confidence score (0.0 to 1.0)"
    )
    
    # Complete email data (single source of truth)
    complete_email_data = models.JSONField(
        default=dict,
        help_text="Complete email data in standardized format (eml_parser equivalent)"
    )
    
    # Extracted data (JSON field for AI processing results only)
    extracted_data = models.JSONField(
        default=dict,
        help_text="AI-extracted event information and analysis"
    )
    
    # Processing metadata
    processed = models.DateTimeField(
        auto_now_add=True,
        help_text="When the email was processed by AI"
    )
    
    status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS_CHOICES,
        default='pending',
        help_text="Current processing status"
    )
    
    # Link to created event (if verified and converted)
    event = models.ForeignKey(
        'event_management.Event',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_emails',
        help_text="Event created from this email (if applicable)"
    )

    # The immutable reception record this processing row was derived from.
    # Nullable for legacy rows created before the ingestion pipeline existed;
    # the new pipeline always writes RawMessage first, then creates this row
    # only for messages that reach extraction/escalation.
    raw_message = models.OneToOneField(
        'RawMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_processing',
        help_text="Immutable reception record this processing row came from"
    )

    # Conversation/thread grouping (Outlook conversationId -> EmailThread).
    # Populated automatically on save from complete_email_data['thread_id'].
    thread = models.ForeignKey(
        'EmailThread',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='emails',
        help_text="Conversation thread this email belongs to (from Outlook conversationId)"
    )
    
    # Error handling
    error_message = models.TextField(
        blank=True,
        help_text="Error message if processing failed"
    )
    
    # Security and audit fields
    data_classification = models.CharField(
        max_length=20,
        choices=settings.DATA_CLASSIFICATION_LEVELS,
        default='internal',
        help_text="Data classification level for security compliance"
    )
    
    processed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='processed_emails',
        help_text="User who processed/verified this email"
    )
    
    # Raw email content (encrypted)
    raw_content = models.TextField(
        blank=True,
        help_text="Raw email content for reference (encrypted)"
    )
    
    class Meta:
        db_table = 'email_processing'
        verbose_name = 'Email Processing'
        verbose_name_plural = 'Email Processing Records'
        ordering = ['-received']
        indexes = [
            models.Index(fields=['email_id']),
            models.Index(fields=['received']),
            models.Index(fields=['status']),
            models.Index(fields=['is_scheduling_request']),
            models.Index(fields=['sender']),
            models.Index(fields=['data_classification']),
        ]
    
    def __str__(self):
        return f"Email from {self.sender}: {self.subject[:50]}..."
    
    def clean(self):
        """Validate model data."""
        from django.core.exceptions import ValidationError
        
        # Validate complete_email_data is a dictionary
        if not isinstance(self.complete_email_data, dict):
            raise ValidationError("Complete email data must be a dictionary.")
        
        # Validate extracted_data is a dictionary
        if not isinstance(self.extracted_data, dict):
            raise ValidationError("Extracted data must be a dictionary.")
        
        # Validate confidence score
        if not (0.0 <= self.confidence <= 1.0):
            raise ValidationError("Confidence must be between 0.0 and 1.0.")
    
    def save(self, *args, **kwargs):
        """Override save to ensure data validation."""
        self.full_clean()
        # Auto-link to a conversation thread from the Outlook conversationId
        # captured in complete_email_data, so threading is maintained at ingest.
        if self.thread_id is None:
            self._link_thread_from_conversation()
        super().save(*args, **kwargs)

    def _link_thread_from_conversation(self):
        """Attach this email to the EmailThread for its conversationId.

        Idempotent and safe to call before the email row exists. Does nothing
        when no conversationId is present (a one-off with no thread context).
        """
        conversation_id = self.get_email_thread_id()
        if not conversation_id:
            return
        thread, _ = EmailThread.objects.get_or_create(
            conversation_id=conversation_id,
            defaults={'subject': self.subject or ''},
        )
        self.thread = thread

    @property
    def is_verified(self):
        """Check if email processing has been verified by a user."""
        return self.status == 'verified'
    
    @property
    def needs_review(self):
        """Check if email needs human review."""
        return self.status in ['pending', 'processed'] and self.is_scheduling_request
    
    def get_extracted_field(self, field_name, default=None):
        """Safely get a field from extracted_data."""
        return self.extracted_data.get(field_name, default)
    
    def set_extracted_field(self, field_name, value):
        """Safely set a field in extracted_data."""
        if not isinstance(self.extracted_data, dict):
            self.extracted_data = {}
        self.extracted_data[field_name] = value
    
    def get_complete_email_field(self, field_name, default=None):
        """Safely get a field from complete_email_data."""
        return self.complete_email_data.get(field_name, default)
    
    def set_complete_email_field(self, field_name, value):
        """Safely set a field in complete_email_data."""
        if not isinstance(self.complete_email_data, dict):
            self.complete_email_data = {}
        self.complete_email_data[field_name] = value
    
    def get_email_type(self):
        """Get the email type from complete_email_data."""
        return self.get_complete_email_field('email_type', 'unknown')
    
    def get_email_thread_id(self):
        """Get the thread ID from complete_email_data."""
        return self.get_complete_email_field('thread_id', '')
    
    def get_email_body(self):
        """Get the email body from complete_email_data."""
        return self.get_complete_email_field('body', {})
    
    def get_email_attachments(self):
        """Get email attachments from complete_email_data."""
        return self.get_complete_email_field('attachments', [])
    
    def has_complete_email_data(self):
        """Check if this record has complete email data."""
        return bool(self.complete_email_data and 
                   self.complete_email_data.get('email_id'))
    
    @property
    def email_preview(self):
        """Get email preview text."""
        body = self.get_email_body()
        return body.get('preview', '') or body.get('text', '')[:200]


class EmailResponse(models.Model):
    """
    Model for tracking email responses sent through the system.
    """
    
    RESPONSE_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('scheduled', 'Scheduled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Link to original email processing record
    original_email = models.ForeignKey(
        EmailProcessing,
        on_delete=models.CASCADE,
        related_name='responses',
        help_text="Original email this is responding to"
    )
    
    # Response details
    template_used = models.ForeignKey(
        'event_management.EmailTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Template used for this response"
    )
    
    subject = models.CharField(
        max_length=1000,
        help_text="Response email subject"
    )
    
    body = models.TextField(
        help_text="Response email body"
    )
    
    is_html = models.BooleanField(
        default=False,
        help_text="Whether the body is HTML formatted"
    )
    
    # Email addresses
    sender = models.EmailField(
        help_text="Email address of the sender (staff member)"
    )
    
    recipient = models.EmailField(
        help_text="Primary recipient email address"
    )
    
    cc_recipients = models.JSONField(
        default=list,
        blank=True,
        help_text="List of CC recipient email addresses"
    )

    bcc_recipients = models.JSONField(
        default=list,
        blank=True,
        help_text="List of BCC recipient email addresses"
    )
    
    # Sending metadata
    status = models.CharField(
        max_length=20,
        choices=RESPONSE_STATUS_CHOICES,
        default='pending',
        help_text="Response status"
    )
    
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the response was sent"
    )
    
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the response is scheduled to be sent"
    )
    
    # External system integration
    outlook_message_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="ID of the sent message in Outlook"
    )
    
    # Error handling
    error_message = models.TextField(
        blank=True,
        help_text="Error message if sending failed"
    )
    
    # Audit fields
    created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='email_responses_created',
        help_text="User who created this response"
    )
    
    modified = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='email_responses_modified',
        help_text="User who last modified this response"
    )
    
    class Meta:
        db_table = 'email_responses'
        verbose_name = 'Email Response'
        verbose_name_plural = 'Email Responses'
        ordering = ['-created']
        indexes = [
            models.Index(fields=['original_email', 'created']),
            models.Index(fields=['status']),
            models.Index(fields=['sent_at']),
            models.Index(fields=['scheduled_for']),
            models.Index(fields=['created']),
        ]
    
    def __str__(self):
        return f"Response to {self.original_email.sender}: {self.subject[:50]}..."
    
    def clean(self):
        """Validate model data."""
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email
        
        # Validate CC recipients is a list
        if not isinstance(self.cc_recipients, list):
            raise ValidationError("CC recipients must be a list.")
        
        # Validate BCC recipients is a list
        if not isinstance(self.bcc_recipients, list):
            raise ValidationError("BCC recipients must be a list.")
        
        # Validate email addresses in CC recipients
        for email in self.cc_recipients:
            try:
                validate_email(email)
            except ValidationError:
                raise ValidationError(f"Invalid CC email address: {email}")
        
        # Validate email addresses in BCC recipients
        for email in self.bcc_recipients:
            try:
                validate_email(email)
            except ValidationError:
                raise ValidationError(f"Invalid BCC email address: {email}")
    
    def save(self, *args, **kwargs):
        """Override save to ensure data validation."""
        self.full_clean()
        super().save(*args, **kwargs)
    
    @property
    def is_sent(self):
        """Check if response has been sent."""
        return self.status == 'sent' and self.sent_at is not None


class EmailThread(models.Model):
    """
    A conversation thread grouping EmailProcessing records that share an
    Outlook conversationId. Membership is the source of truth (EmailThread.emails);
    the denormalized fields below are refreshed via recalc_metadata() for display.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    conversation_id = models.CharField(
        max_length=512,
        unique=True,
        help_text="Outlook conversationId (or message-id for imported mail) that defines the thread"
    )

    subject = models.CharField(
        max_length=1000,
        blank=True,
        help_text="Representative subject for the thread (usually the first message)"
    )

    # Denormalized for fast display; refreshed by recalc_metadata().
    participants = models.JSONField(
        default=list,
        blank=True,
        help_text="Distinct participants: list of {email, name}"
    )

    message_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of emails in the thread (denormalized)"
    )

    first_message_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the earliest message in the thread"
    )

    last_message_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the most recent message in the thread"
    )

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'email_threads'
        verbose_name = 'Email Thread'
        verbose_name_plural = 'Email Threads'
        ordering = ['-last_message_at']
        indexes = [
            models.Index(fields=['conversation_id']),
            models.Index(fields=['last_message_at']),
        ]

    def __str__(self):
        return f"Thread '{self.subject[:50]}' ({self.message_count} messages)"

    def recalc_metadata(self, save=True):
        """Refresh denormalized fields from the current set of member emails."""
        from django.db.models import Count, Max, Min

        agg = self.emails.aggregate(
            n=Count('id'), last=Max('received'), first=Min('received')
        )
        self.message_count = agg['n'] or 0
        self.last_message_at = agg['last']
        self.first_message_at = agg['first']

        participants = {}
        for sender, sender_name in self.emails.values_list('sender', 'sender_name'):
            if sender and sender not in participants:
                participants[sender] = sender_name or ''
        self.participants = [
            {'email': email, 'name': name} for email, name in participants.items()
        ]

        if save:
            self.save(update_fields=[
                'message_count', 'last_message_at', 'first_message_at',
                'participants', 'modified',
            ])

    @property
    def latest_email(self):
        """The most recent email in the thread (for reply targeting)."""
        return self.emails.order_by('-received').first()


class RawMessage(models.Model):
    """The audit floor of the ingestion pipeline.

    Every message the office receives is persisted here — verbatim — *before*
    anything (funnel, extraction, materialization) touches it. This is the
    single source of truth for "what did we actually receive", the divert-store
    that guarantees the office can always find a message it got, and the raw
    input every downstream stage re-reads.

    Immutable by contract: once a row is written it is never updated. Reprocessing
    creates new FilterLog / ExtractionCandidate rows that *reference* this one;
    the reception record itself never changes. Immutability is enforced in
    ``save()`` (see below).
    """

    SOURCE_CHOICES = [
        ('webhook', 'Webhook'),
        ('sweep', 'Sweep'),
        ('manual', 'Manual'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # --- Identity (used by dedup + reconciliation) ---
    graph_message_id = models.CharField(
        max_length=512,
        unique=True,
        db_index=True,
        help_text="Microsoft Graph message id (unique per mailbox copy)"
    )
    internet_message_id = models.CharField(
        max_length=998,
        blank=True,
        db_index=True,
        help_text="RFC-5322 Message-ID header; stable across mailboxes, used by dedup"
    )
    conversation_id = models.CharField(
        max_length=512,
        blank=True,
        db_index=True,
        help_text="Outlook conversationId grouping the thread"
    )

    # --- Provenance ---
    mailbox = models.CharField(
        max_length=254,
        db_index=True,
        help_text="Subscribed mailbox this copy was received in"
    )
    received_at = models.DateTimeField(
        help_text="receivedDateTime from Graph (when the mail server got it)"
    )
    fetched_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When HillDesk fetched and persisted this message"
    )
    source = models.CharField(
        max_length=10,
        choices=SOURCE_CHOICES,
        default='sweep',
        help_text="How this message reached us: reconciliation sweep, webhook, or manual"
    )

    # --- Sender (encrypted PII + blind index for reputation/rate-gate lookups) ---
    sender = EncryptedCharField(
        max_length=254,
        blank=True,
        help_text="Sender email address (encrypted)"
    )
    sender_key = models.CharField(
        max_length=64,
        db_index=True,
        editable=False,
        blank=True,
        default='',
        help_text="Blind index (HMAC) of the sender email for exact-match lookup"
    )
    sender_name = EncryptedCharField(
        max_length=254,
        blank=True,
        help_text="Sender display name (encrypted)"
    )

    # --- Content ---
    subject = models.CharField(
        max_length=1000,
        blank=True,
        help_text="Subject line (kept plaintext for divert-store search/triage)"
    )
    headers = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full header map incl. Authentication-Results, List-*, Auto-Submitted"
    )
    body_text = EncryptedTextField(
        blank=True,
        help_text="Plain-text body (encrypted)"
    )
    body_html = EncryptedTextField(
        blank=True,
        help_text="HTML body (encrypted)"
    )

    # --- Attachments ---
    attachments = models.JSONField(
        default=list,
        blank=True,
        help_text="Attachment metadata: [{name, content_type, size, is_inline, content_id}]"
    )
    has_calendar_part = models.BooleanField(
        default=False,
        help_text="Set at reception from MIME inspection (text/calendar part or .ics attachment)"
    )

    # Security / audit
    data_classification = models.CharField(
        max_length=20,
        choices=settings.DATA_CLASSIFICATION_LEVELS,
        default='sensitive',
        help_text="Data classification level for security compliance"
    )

    class Meta:
        db_table = 'email_raw_message'
        verbose_name = 'Raw Message'
        verbose_name_plural = 'Raw Messages'
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['mailbox', 'received_at']),
            models.Index(fields=['sender_key', 'received_at']),
            models.Index(fields=['conversation_id']),
        ]

    def __str__(self):
        return f"RawMessage {self.graph_message_id} <{self.mailbox}>"

    def save(self, *args, **kwargs):
        """Persist the reception record.

        Enforces immutability: a RawMessage may be INSERTed once and never
        updated. Any attempt to save an already-persisted row raises, so no
        code path can silently mutate the audit floor. The sender blind index
        is (re)derived on insert from the encrypted sender value.
        """
        if self.pk and RawMessage.objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "RawMessage is immutable and cannot be updated once persisted."
            )
        self.sender_key = email_blind_index(self.sender) if self.sender else ''
        super().save(*args, **kwargs)


class FilterLog(models.Model):
    """One row per message per funnel stage per pipeline run.

    This is the funnel's ledger: every decision the pipeline makes about a
    message is recorded here with the actual signals that drove it (header
    hits, token counts, score components). It doubles as the future local
    classifier's training dataset and the false-negative forensics tool —
    never pruned.
    """

    STAGE_CHOICES = [
        ('0_scope', 'Stage 0: Scope'),
        ('1_headers', 'Stage 1: Headers'),
        ('2_reputation', 'Stage 2: Reputation'),
        ('3_dedup', 'Stage 3: Dedup'),
        ('4_content', 'Stage 4: Content heuristics'),
        ('rate_gate', 'Rate gate'),
        ('extraction', 'Extraction'),
        ('postprocess', 'Post-processing'),
    ]

    OUTCOME_CHOICES = [
        ('pass', 'Pass'),
        ('divert', 'Divert'),
        ('escalate', 'Escalate'),
        ('extract', 'Extract'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_message = models.ForeignKey(
        RawMessage,
        on_delete=models.CASCADE,
        related_name='filter_logs',
        help_text="Message this decision applies to"
    )
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES)
    signals = models.JSONField(
        default=dict,
        blank=True,
        help_text="Actual signal values behind the decision (header hits, token "
                  "counts, score components) — shaped as the future classifier's "
                  "feature vector"
    )
    score = models.FloatField(default=0.0)
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES)
    # Written only on 3_dedup rows: the normalized content hash used for
    # near-duplicate detection. A dedicated indexed column (rather than a key in
    # signals) because dedup must query it within a time window.
    dedup_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'email_filter_log'
        verbose_name = 'Filter Log'
        verbose_name_plural = 'Filter Logs'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['raw_message', 'created_at']),
            models.Index(fields=['stage', 'outcome']),
            models.Index(fields=['outcome', 'created_at']),
        ]

    def __str__(self):
        return f"FilterLog {self.stage}:{self.outcome} for {self.raw_message_id}"


class SenderReputation(models.Model):
    """Allow/block/unknown standing for a sender or a whole domain.

    A row is one or the other: ``sender_key`` (blind index of the address, same
    HMAC key space as apps.contacts) for per-sender rows, or plaintext
    ``domain`` for domain rows (a domain is not PII). ``sender_email`` keeps an
    encrypted copy of per-sender addresses for display, since the blind index
    is one-way.

    Written by reviewer actions (accept → approve_count++, junk-dismiss →
    offered blocklist), staff list management, and the seed migration
    (internal domains + existing Contacts).
    """

    LIST_CHOICES = [
        ('allow', 'Allow'),
        ('block', 'Block'),
        ('unknown', 'Unknown'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender_email = EncryptedCharField(
        max_length=254, blank=True, default='',
        help_text="Sender address (encrypted; blank for domain rows)"
    )
    sender_key = models.CharField(
        max_length=64, blank=True, default='', db_index=True, editable=False,
        help_text="Blind index of sender_email (blank for domain rows)"
    )
    domain = models.CharField(
        max_length=254, blank=True, default='', db_index=True,
        help_text="Domain this row covers (blank for per-sender rows)"
    )
    list = models.CharField(max_length=10, choices=LIST_CHOICES, default='unknown')
    approve_count = models.PositiveIntegerField(default=0)
    reject_count = models.PositiveIntegerField(default=0)
    last_seen = models.DateTimeField(null=True, blank=True)
    added_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sender_reputations_added'
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'email_sender_reputation'
        verbose_name = 'Sender Reputation'
        verbose_name_plural = 'Sender Reputations'
        constraints = [
            models.UniqueConstraint(
                fields=['sender_key'], name='uniq_reputation_sender_key',
                condition=~models.Q(sender_key=''),
            ),
            models.UniqueConstraint(
                fields=['domain'], name='uniq_reputation_domain',
                condition=~models.Q(domain=''),
            ),
            # A row targets exactly one of (sender, domain).
            models.CheckConstraint(
                name='reputation_sender_xor_domain',
                check=(
                    (models.Q(sender_key='') & ~models.Q(domain='')) |
                    (~models.Q(sender_key='') & models.Q(domain=''))
                ),
            ),
        ]

    def __str__(self):
        target = self.domain or f"sender:{self.sender_key[:12]}…"
        return f"SenderReputation {target} ({self.list})"

    def save(self, *args, **kwargs):
        if self.sender_email:
            self.sender_key = email_blind_index(self.sender_email)
        self.domain = (self.domain or '').strip().lower()
        super().save(*args, **kwargs)


class ExtractionCandidate(models.Model):
    """One extracted scheduling candidate — the unit handed downstream.

    One email → N candidate rows (multi-event fan-out, or ICS + body extraction
    on the same message). A candidate is never shown raw to reviewers; Phase 5
    post-processing materializes it into the review surfaces (draft Event or
    EventChangeSuggestion). The payload is schema-validated model output — data,
    never instructions.
    """

    INTENT_CHOICES = [
        ('NEW_EVENT', 'New event'),
        ('RECURRING_EVENT', 'Recurring event'),
        ('RESCHEDULE', 'Reschedule'),
        ('CANCELLATION', 'Cancellation'),
        ('UNCERTAIN', 'Uncertain'),
    ]

    STATUS_CHOICES = [
        ('pending_review', 'Pending review'),
        ('materialized', 'Materialized'),
        ('escalated', 'Escalated'),
        ('rejected', 'Rejected'),
        ('superseded', 'Superseded'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_message = models.ForeignKey(
        RawMessage, on_delete=models.CASCADE, related_name='candidates',
    )
    email_processing = models.ForeignKey(
        EmailProcessing, on_delete=models.CASCADE, related_name='candidates',
        null=True, blank=True,
        help_text="The pipeline-visible message record",
    )
    thread = models.ForeignKey(
        EmailThread, on_delete=models.SET_NULL, related_name='candidates',
        null=True, blank=True,
    )

    intent = models.CharField(max_length=20, choices=INTENT_CHOICES)
    payload = models.JSONField(
        default=dict,
        help_text="Schema-validated candidate (event fields, contacts[], "
                  "organizations[], verbatim, timezone)",
    )
    provenance = models.JSONField(
        default=dict, blank=True,
        help_text="Source channel (body|ics|attachment:<name>|forward-quoted), "
                  "spans, verbatim strings, timezone basis, ICS UID/method",
    )
    confidence = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    recurrence_rule = models.CharField(
        max_length=500, null=True, blank=True,
        help_text="RFC-5545 RRULE string (never expanded instances)",
    )
    recurrence_needs_end = models.BooleanField(
        default=False,
        help_text="RRULE lacks UNTIL/COUNT; series cannot activate until a "
                  "reviewer sets a bound",
    )

    # Filled by Phase-5 post-processing.
    matched_event = models.ForeignKey(
        'event_management.Event', on_delete=models.SET_NULL,
        related_name='matched_candidates', null=True, blank=True,
    )
    match_basis = models.JSONField(default=dict, blank=True,
                                   help_text="How the match was made")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='pending_review')
    created_event = models.ForeignKey(
        'event_management.Event', on_delete=models.SET_NULL,
        related_name='source_candidates', null=True, blank=True,
    )
    change_suggestion = models.ForeignKey(
        'event_management.EventChangeSuggestion', on_delete=models.SET_NULL,
        related_name='source_candidates', null=True, blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'email_extraction_candidate'
        verbose_name = 'Extraction Candidate'
        verbose_name_plural = 'Extraction Candidates'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['intent']),
        ]

    def __str__(self):
        return f"Candidate {self.intent} ({self.status}) from {self.raw_message_id}"


class AttachmentBlob(models.Model):
    """Stored payload of an attachment on a RawMessage.

    Small attachments (<= ATTACHMENT_STORE_MAX_BYTES) are persisted here so the
    pipeline can harvest/parse them without a second Graph round-trip. Larger
    attachments are recorded as metadata only on ``RawMessage.attachments`` and
    re-fetched from Graph on demand.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_message = models.ForeignKey(
        RawMessage,
        on_delete=models.CASCADE,
        related_name='attachment_blobs',
        help_text="Message this attachment belongs to"
    )
    graph_attachment_id = models.CharField(
        max_length=512,
        blank=True,
        help_text="Graph attachment id (for re-fetch)"
    )
    name = models.CharField(max_length=512, blank=True)
    content_type = models.CharField(max_length=255, blank=True)
    content_id = models.CharField(
        max_length=512, blank=True,
        help_text="Content-ID for inline attachments"
    )
    size = models.PositiveIntegerField(default=0, help_text="Size in bytes")
    is_inline = models.BooleanField(default=False)
    payload = models.BinaryField(
        help_text="Raw attachment bytes (<= ATTACHMENT_STORE_MAX_BYTES)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'email_attachment_blob'
        verbose_name = 'Attachment Blob'
        verbose_name_plural = 'Attachment Blobs'
        indexes = [
            models.Index(fields=['raw_message']),
        ]

    def __str__(self):
        return f"AttachmentBlob {self.name} ({self.size} bytes)"


class SubscriptionState(models.Model):
    """Per-mailbox reception bookkeeping.

    One row per subscribed mailbox. Carries both the Graph webhook subscription
    lifecycle (subscription_id, expiry, renewal health) AND the sweep state
    (delta token, last sweep) — so reconciliation sweeps work even when webhooks
    are disabled, and both mechanisms key off the same row.
    """

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('lapsed', 'Lapsed'),
        ('disabled', 'Disabled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    mailbox = models.CharField(
        max_length=254,
        unique=True,
        help_text="Mailbox address this subscription/sweep state tracks"
    )
    resource = models.CharField(
        max_length=512,
        blank=True,
        help_text="Graph resource path the subscription targets (mail folder)"
    )

    # Webhook subscription lifecycle
    subscription_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        db_index=True,
        help_text="Graph subscription id (blank when webhooks are off / not yet created)"
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    last_renewed_at = models.DateTimeField(null=True, blank=True)
    last_renewal_error = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='disabled',
        help_text="Subscription health; sweep keeps mail flowing regardless"
    )

    # Sweep / reconciliation state (used even when webhooks are off)
    delta_token = models.TextField(
        blank=True,
        default='',
        help_text="Graph delta query token for incremental sweeps"
    )
    last_sweep_at = models.DateTimeField(null=True, blank=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'email_subscription_state'
        verbose_name = 'Subscription State'
        verbose_name_plural = 'Subscription States'
        ordering = ['mailbox']

    def __str__(self):
        return f"SubscriptionState {self.mailbox} ({self.status})"

    @property
    def needs_renewal(self):
        """True when an active subscription expires within the renewal window (24h)."""
        if not self.subscription_id or not self.expires_at:
            return False
        return self.expires_at <= timezone.now() + timedelta(hours=24)