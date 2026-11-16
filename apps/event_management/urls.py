# SPDX-License-Identifier: Apache-2.0
"""
Event Management URL configuration for HillDesk.
"""
from django.urls import path
from . import views
from .views import email_template_views
from .views import search_views
from .views import settings_views
from .views import calendar_views
from .views import event_views_simple as event_views

app_name = 'event_management'

urlpatterns = [
    # Main views
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('events/', views.ScheduleView.as_view(), name='events'),
    path('inbox/', views.InboxView.as_view(), name='inbox'),
    path('calendar/', calendar_views.CalendarView.as_view(), name='calendar'),
    path('calendar/<str:view_type>/', calendar_views.CalendarView.as_view(), name='calendar_view'),
    path('calendar/<str:view_type>/<int:year>/<int:month>/', calendar_views.CalendarView.as_view(), name='calendar_date'),
    path('calendar/<str:view_type>/<int:year>/<int:month>/<int:day>/', calendar_views.CalendarView.as_view(), name='calendar_date'),
    path('calendar/today/', calendar_views.CalendarTodayRedirectView.as_view(), name='calendar_today'),
    path('calendar/today/<str:view_type>/', calendar_views.CalendarTodayRedirectView.as_view(), name='calendar_today_view'),
    path('api/calendar/events/', calendar_views.CalendarEventAPIView.as_view(), name='calendar_events_api'),
    path('api/calendar/upcoming-events/', calendar_views.CalendarUpcomingEventsAPIView.as_view(), name='calendar_upcoming_events_api'),
    path('api/calendar/navigation/', calendar_views.CalendarNavigationAPIView.as_view(), name='calendar_navigation_api'),
    path('api/calendar/metadata/', calendar_views.CalendarMetadataAPIView.as_view(), name='calendar_metadata_api'),
    
    # Event CRUD operations
    path('events/create/', views.EventCreateView.as_view(), name='event_create'),
    path('events/<uuid:pk>/', views.EventDetailView.as_view(), name='event_detail'),
    path('events/<uuid:pk>/edit/', views.EventUpdateView.as_view(), name='event_update'),
    path('events/<uuid:pk>/delete/', views.EventDeleteView.as_view(), name='event_delete'),
    
    # Event bulk actions and utilities
    path('events/calendar/', views.ScheduleView.as_view(), name='event_calendar'),
    
    # Event Metadata Management - temporarily commented out
    
    # Search and Filtering
    path('api/search/suggestions/', search_views.search_suggestions, name='search_suggestions'),
    path('api/search/stats/', search_views.filter_stats, name='filter_stats'),
    path('api/search/advanced/', search_views.advanced_search, name='advanced_search'),
    path('export/events/', search_views.export_filtered_events, name='export_events'),
    
    # Event Archiving
    
    # Email Template Management
    path('email-templates/', email_template_views.EmailTemplateListView.as_view(), name='email_template_list'),
    path('email-templates/create/', email_template_views.EmailTemplateCreateView.as_view(), name='email_template_create'),
    path('email-templates/<uuid:pk>/', email_template_views.EmailTemplateDetailView.as_view(), name='email_template_detail'),
    path('email-templates/<uuid:pk>/edit/', email_template_views.EmailTemplateUpdateView.as_view(), name='email_template_update'),
    path('email-templates/<uuid:pk>/delete/', email_template_views.EmailTemplateDeleteView.as_view(), name='email_template_delete'),
    path('email-templates/<uuid:pk>/preview/', email_template_views.preview_template, name='email_template_preview'),
    
    # Event Editing Interface
    path('event-editing/<uuid:event_id>/', event_views.event_editing_interface, name='event_editing_interface'),
    
    # Simple schedule test
    
    # Test URL for event editing interface
    
    # Settings
    path('settings/', views.SettingsView.as_view(), name='settings'),
    path('settings/preferences/', settings_views.update_preferences, name='update_preferences'),
    path('settings/profile/', settings_views.update_profile, name='update_profile'),
    path('settings/notifications/', settings_views.update_notifications, name='update_notifications'),
    path('settings/password/', settings_views.change_password, name='change_password'),
    path('settings/clear-data/', settings_views.clear_user_data, name='clear_user_data'),
    path('settings/export/', settings_views.export_user_data, name='export_user_data'),
    path('settings/stats/', settings_views.get_user_stats, name='user_stats'),

    # Office
    path('office/', views.OfficeView.as_view(), name='office'),

    path('templates/', views.TemplateManagementView.as_view(), name='templates'),
]