# SPDX-License-Identifier: Apache-2.0
"""
API URL configuration for HillDesk.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    EventViewSet, EmailFetchAPIView, EmailProcessingViewSet,
    SmartExtractAPIView, event_choices, validate_event_data, office_choices,
    check_option_usage, enable_smartextract_mode, disable_smartextract_mode,
    smartextract_status, review_field, accept_all_fields, review_status, dismiss_review,
    review_contact, review_organization,
    create_staff_member, update_staff_member, delete_staff_member,
    link_staff_account, unlink_staff_account,
    # Role management endpoints
    create_role, update_role, delete_role,
    # Change suggestion endpoints
    check_edit_permission, create_suggestion, get_event_suggestions,
    review_suggestion, get_inbox_suggestions, bulk_approve_suggestions,
    # Approval routing endpoints
    approval_routing, submit_approval, events_needing_approval, cancel_review, remove_routing,
    # Email template & response endpoints
    email_templates_list, email_template_create, email_template_update, email_template_delete,
    send_email_response, email_response_history, generate_email_draft,
    # Filter preset endpoints
    filter_presets, filter_preset_detail,
    routing_presets, routing_preset_detail,
    # Export endpoints
    export_templates_list, export_template_upload, export_template_delete,
    export_template_download,
    export_events_docx, export_status, export_events_csv,
    # Event attachment endpoints
    event_attachments, event_attachment_replace, event_attachment_download,
    event_attachment_delete,
    # Email ingestion review surfaces
    change_suggestions_feed, activate_event_series, event_series, block_sender,
)

from apps.contacts.api import ContactViewSet, OrganizationViewSet
from apps.email_processing.webhook_views import graph_webhook

app_name = 'api'

# Create a router for API endpoints
router = DefaultRouter()
router.register(r'events', EventViewSet, basename='event')
router.register(r'email-processing', EmailProcessingViewSet, basename='emailprocessing')
router.register(r'contacts', ContactViewSet, basename='contact')
router.register(r'organizations', OrganizationViewSet, basename='organization')

urlpatterns = [
    # Human Review endpoints (must be before router to avoid conflict)
    path('events/<uuid:event_id>/review-field/', review_field, name='review-field'),
    path('events/<uuid:event_id>/review-contact/', review_contact, name='review-contact'),
    path('events/<uuid:event_id>/review-organization/', review_organization, name='review-organization'),
    path('events/<uuid:event_id>/accept-all/', accept_all_fields, name='accept-all'),
    path('events/<uuid:event_id>/dismiss/', dismiss_review, name='dismiss-review'),
    path('events/<uuid:event_id>/review-status/', review_status, name='review-status'),

    # SmartExtract AI endpoints (must be before router)
    path('events/<uuid:event_id>/smartextract/', SmartExtractAPIView.as_view(), name='smartextract'),
    path('events/<uuid:event_id>/smartextract/enable/', enable_smartextract_mode, name='enable-smartextract'),
    path('events/<uuid:event_id>/smartextract/disable/', disable_smartextract_mode, name='disable-smartextract'),
    path('events/<uuid:event_id>/smartextract/status/', smartextract_status, name='smartextract-status'),

    # Staff Change Suggestion endpoints (must be before router)
    path('events/<uuid:event_id>/edit-permission/', check_edit_permission, name='check-edit-permission'),
    path('events/<uuid:event_id>/suggest/', create_suggestion, name='create-suggestion'),
    path('events/<uuid:event_id>/suggestions/', get_event_suggestions, name='get-event-suggestions'),
    path('events/<uuid:event_id>/suggestions/bulk-approve/', bulk_approve_suggestions, name='bulk-approve-suggestions'),
    path('suggestions/<uuid:suggestion_id>/review/', review_suggestion, name='review-suggestion'),
    path('inbox/suggestions/', get_inbox_suggestions, name='inbox-suggestions'),

    # Approval Routing endpoints (must be before router)
    path('events/<uuid:event_id>/approval-routing/', approval_routing, name='approval-routing'),
    path('events/<uuid:event_id>/approval-routing/approve/', submit_approval, name='submit-approval'),
    path('events/<uuid:event_id>/approval-routing/cancel/', cancel_review, name='cancel-review'),
    path('events/<uuid:event_id>/approval-routing/remove/', remove_routing, name='remove-routing'),
    path('events/needs-my-approval/', events_needing_approval, name='events-needing-approval'),

    # Event attachment endpoints (must be before router to avoid events/ prefix conflict)
    path('events/<uuid:event_id>/attachments/', event_attachments, name='event-attachments'),
    path('events/<uuid:event_id>/attachments/<uuid:attachment_id>/replace/', event_attachment_replace, name='event-attachment-replace'),
    path('events/<uuid:event_id>/attachments/<uuid:attachment_id>/versions/<uuid:version_id>/download/', event_attachment_download, name='event-attachment-download'),
    path('events/<uuid:event_id>/attachments/<uuid:attachment_id>/', event_attachment_delete, name='event-attachment-delete'),

    # Export endpoints (must be before router to avoid events/ prefix conflict)
    path('events/export/', export_events_docx, name='export-events-docx'),
    path('events/export/status/<str:task_id>/', export_status, name='export-status'),
    path('events/export/csv/', export_events_csv, name='export-events-csv'),

    # Router URLs (events/, email-processing/)
    path('', include(router.urls)),

    # Email integration endpoints
    path('emails/', EmailFetchAPIView.as_view(), name='email-fetch'),

    # Microsoft Graph change-notification webhook (ingestion pipeline)
    path('webhooks/graph/', graph_webhook, name='graph-webhook'),

    # Email ingestion review surfaces (third inbox feed, series confirm, reputation)
    path('change-suggestions/', change_suggestions_feed, name='change-suggestions-feed'),
    path('series/<uuid:series_id>/activate/', activate_event_series, name='activate-series'),
    path('events/<uuid:event_id>/series/', event_series, name='event-series'),
    path('reputation/block/', block_sender, name='block-sender'),

    # Utility endpoints
    path('event-choices/', event_choices, name='event-choices'),
    path('office/choices/', office_choices, name='office-choices'),
    path('office/check-option-usage/', check_option_usage, name='check-option-usage'),
    path('validate-event/', validate_event_data, name='validate-event'),

    # Staff management endpoints
    path('office/staff/', create_staff_member, name='create-staff'),
    path('office/staff/<uuid:staff_id>/', update_staff_member, name='update-staff'),
    path('office/staff/<uuid:staff_id>/delete/', delete_staff_member, name='delete-staff'),
    path('office/staff/<uuid:staff_id>/link/', link_staff_account, name='link-staff-account'),
    path('office/staff/<uuid:staff_id>/unlink/', unlink_staff_account, name='unlink-staff-account'),

    # Role management endpoints
    path('office/roles/', create_role, name='create-role'),
    path('office/roles/<uuid:role_id>/', update_role, name='update-role'),
    path('office/roles/<uuid:role_id>/delete/', delete_role, name='delete-role'),

    # Email template endpoints
    path('email/templates/', email_templates_list, name='email-templates-list'),
    path('email/templates/create/', email_template_create, name='email-template-create'),
    path('email/templates/<uuid:template_id>/', email_template_update, name='email-template-update'),
    path('email/templates/<uuid:template_id>/delete/', email_template_delete, name='email-template-delete'),

    # Email response endpoints
    path('email/send-response/', send_email_response, name='send-email-response'),
    path('email/<uuid:email_id>/responses/', email_response_history, name='email-response-history'),
    path('email/generate-draft/', generate_email_draft, name='generate-email-draft'),

    # Filter preset endpoints (named, user-level, multiple)
    path('user/filter-presets/', filter_presets, name='filter-presets'),
    path('user/filter-presets/<int:preset_id>/', filter_preset_detail, name='filter-preset-detail'),

    # Routing preset endpoints (named, user-level, multiple)
    path('user/routing-presets/', routing_presets, name='routing-presets'),
    path('user/routing-presets/<int:preset_id>/', routing_preset_detail, name='routing-preset-detail'),

    # Export template management endpoints
    path('export/templates/', export_templates_list, name='export-templates-list'),
    path('export/templates/upload/', export_template_upload, name='export-template-upload'),
    path('export/templates/<uuid:template_id>/delete/', export_template_delete, name='export-template-delete'),
    path('export/templates/<uuid:template_id>/download/', export_template_download, name='export-template-download'),
]

# TEMPORARY: Demo reset endpoint — wired to the DEMO tab Reset button. Remove
# this block (and the matching view + button) once the DEMO tab is gone.
from .views import reset_demo
urlpatterns += [
    path('demo/reset/', reset_demo, name='demo-reset'),
]