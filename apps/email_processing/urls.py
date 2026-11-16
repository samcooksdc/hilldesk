# SPDX-License-Identifier: Apache-2.0
from django.urls import path
from . import views

app_name = 'email_processing'

# NOTE (email ingestion migration): this app's URLs were disabled at the root
# URLconf for some time; only the new ingestion-pipeline surfaces are routed.
# The legacy inbox/verification views remain dark (their code is deleted in
# Phase 5 of the ingestion build, replaced by the triage list — see
# docs/EMAIL_INGESTION_BUILD_PLAN.md).
urlpatterns = [
    # Divert-store browse (ingestion pipeline)
    path('diverted/', views.divert_store, name='divert_store'),
    path('diverted/<uuid:raw_message_id>/promote/', views.promote_diverted, name='promote_diverted'),

    # Triage list (ingestion pipeline — replaces the legacy verification views)
    path('triage/', views.triage_list, name='triage_list'),
    path('api/triage/', views.triage_items_api, name='triage_items_api'),
    path('api/diverted/', views.diverted_items_api, name='diverted_items_api'),
    path('triage/<uuid:raw_message_id>/extract/', views.triage_extract_anyway, name='triage_extract_anyway'),
    path('triage/<uuid:raw_message_id>/divert/', views.triage_divert, name='triage_divert'),
]
