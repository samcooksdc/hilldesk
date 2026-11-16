# SPDX-License-Identifier: Apache-2.0
from django.contrib import admin

from .models import (
    AttachmentBlob, ExtractionCandidate, FilterLog, RawMessage,
    SenderReputation, SubscriptionState,
)


@admin.register(ExtractionCandidate)
class ExtractionCandidateAdmin(admin.ModelAdmin):
    """Review surface for pipeline output until Phase-5 materialization lands."""
    list_display = ('intent', 'status', 'confidence', 'recurrence_rule',
                    'raw_message', 'created_at')
    list_filter = ('intent', 'status', 'recurrence_needs_end', 'created_at')
    search_fields = ('raw_message__subject', 'raw_message__graph_message_id')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FilterLog)
class FilterLogAdmin(admin.ModelAdmin):
    """Read-only funnel ledger (never pruned; also the classifier dataset)."""
    list_display = ('raw_message', 'stage', 'outcome', 'score', 'created_at')
    list_filter = ('stage', 'outcome', 'created_at')
    search_fields = ('raw_message__subject', 'raw_message__graph_message_id', 'dedup_hash')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SenderReputation)
class SenderReputationAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'list', 'approve_count', 'reject_count', 'last_seen', 'notes')
    list_filter = ('list',)
    search_fields = ('domain', 'notes')
    readonly_fields = ('sender_key', 'created_at', 'updated_at')


@admin.register(RawMessage)
class RawMessageAdmin(admin.ModelAdmin):
    """Read-only view of the reception audit floor (the divert-store lives here
    until the browse UI lands). RawMessage is immutable, so all fields are
    read-only and adding via admin is disabled."""
    list_display = ('graph_message_id', 'mailbox', 'subject', 'received_at',
                    'source', 'has_calendar_part')
    list_filter = ('mailbox', 'source', 'has_calendar_part', 'received_at')
    search_fields = ('subject', 'graph_message_id', 'internet_message_id', 'conversation_id')
    date_hierarchy = 'received_at'
    ordering = ('-received_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]


@admin.register(SubscriptionState)
class SubscriptionStateAdmin(admin.ModelAdmin):
    list_display = ('mailbox', 'status', 'subscription_id', 'expires_at',
                    'last_sweep_at', 'last_renewed_at')
    list_filter = ('status',)
    search_fields = ('mailbox', 'subscription_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AttachmentBlob)
class AttachmentBlobAdmin(admin.ModelAdmin):
    list_display = ('name', 'content_type', 'size', 'is_inline', 'raw_message')
    search_fields = ('name', 'content_type')

    def has_add_permission(self, request):
        return False
