# SPDX-License-Identifier: Apache-2.0
"""
Views for user settings and preferences management.

This module provides views for managing user preferences, profile settings,
notifications, and other configuration options.
"""

import logging
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import User
from ..models import Event, EmailTemplate

logger = logging.getLogger(__name__)


@login_required
@require_POST
def update_preferences(request):
    """Update user appearance preferences."""
    try:
        user = request.user
        section = request.POST.get('section')
        
        if section == 'appearance':
            # Theme toggle was removed from the UI; theme stays whatever the
            # user already has (forced to 'light' on first login). Ignore any
            # 'theme' POST value to prevent client-side bypass.

            # Update accent color
            accent_color = request.POST.get('accent_color')
            if accent_color in ['blue', 'red']:
                user.accent_color = accent_color
            
            # Update default view
            default_view = request.POST.get('default_view')
            if default_view in ['list', 'calendar']:
                user.default_view = default_view
            
            user.save()
            
            logger.info(f"User {user.id} updated appearance preferences")
            messages.success(request, 'Appearance settings updated successfully.')
        
        else:
            messages.error(request, 'Invalid settings section.')
            
    except Exception as e:
        logger.error(f"Error updating preferences for user {request.user.id}: {e}")
        messages.error(request, 'Error updating preferences. Please try again.')
    
    return redirect('event_management:settings')


@login_required
@require_POST
def update_profile(request):
    """Update user profile information."""
    try:
        user = request.user
        
        # Update basic profile fields
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name = request.POST.get('last_name', '').strip()
        user.email = request.POST.get('email', '').strip()
        user.username = request.POST.get('username', '').strip()
        
        # Validate required fields
        if not all([user.first_name, user.last_name, user.email, user.username]):
            messages.error(request, 'All fields are required.')
            return redirect('event_management:settings')
        
        # Check if username is unique (excluding current user)
        if User.objects.filter(username=user.username).exclude(id=user.id).exists():
            messages.error(request, 'Username already exists. Please choose a different one.')
            return redirect('event_management:settings')
        
        # Check if email is unique (excluding current user)
        if User.objects.filter(email=user.email).exclude(id=user.id).exists():
            messages.error(request, 'Email already exists. Please choose a different one.')
            return redirect('event_management:settings')
        
        user.save()
        
        logger.info(f"User {user.id} updated profile information")
        messages.success(request, 'Profile updated successfully.')
        
    except Exception as e:
        logger.error(f"Error updating profile for user {request.user.id}: {e}")
        messages.error(request, 'Error updating profile. Please try again.')
    
    return redirect('event_management:settings')


@login_required
@require_POST
def update_notifications(request):
    """Update user notification preferences."""
    try:
        user = request.user
        
        # Update notification preferences
        user.notify_email_processing = 'notify_email_processing' in request.POST
        user.notify_event_reminders = 'notify_event_reminders' in request.POST
        user.notify_status_changes = 'notify_status_changes' in request.POST
        user.notify_system_updates = 'notify_system_updates' in request.POST
        
        user.save()
        
        logger.info(f"User {user.id} updated notification preferences")
        messages.success(request, 'Notification settings updated successfully.')
        
    except Exception as e:
        logger.error(f"Error updating notifications for user {request.user.id}: {e}")
        messages.error(request, 'Error updating notification settings. Please try again.')
    
    return redirect('event_management:settings')


@login_required
@require_POST
def change_password(request):
    """Change user password."""
    try:
        form = PasswordChangeForm(request.user, request.POST)
        
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Keep user logged in
            
            logger.info(f"User {user.id} changed password")
            messages.success(request, 'Password changed successfully.')
        else:
            # Extract form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
        
    except Exception as e:
        logger.error(f"Error changing password for user {request.user.id}: {e}")
        messages.error(request, 'Error changing password. Please try again.')
    
    return redirect('event_management:settings')


@login_required
@require_POST
def clear_user_data(request):
    """Clear all user data (dangerous operation)."""
    try:
        user = request.user
        
        with transaction.atomic():
            # Delete user's events
            user_events = Event.objects.filter(created_by=user)
            event_count = user_events.count()
            user_events.delete()
            
            # Delete user's email templates
            user_templates = EmailTemplate.objects.filter(created_by=user)
            template_count = user_templates.count()
            user_templates.delete()
            
            # Reset user preferences to defaults
            user.theme = 'light'
            user.accent_color = 'blue'
            user.default_view = 'list'
            user.save()
            
            logger.warning(f"User {user.id} cleared all data: {event_count} events, {template_count} templates")
            
            return JsonResponse({
                'success': True,
                'message': f'Cleared {event_count} events and {template_count} templates.'
            })
        
    except Exception as e:
        logger.error(f"Error clearing data for user {request.user.id}: {e}")
        return JsonResponse({'error': 'Error clearing data. Please try again.'}, status=500)


@login_required
def export_user_data(request):
    """Export user data for backup or migration."""
    try:
        user = request.user
        
        # Prepare user data for export
        user_data = {
            'profile': {
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'date_joined': user.date_joined.isoformat(),
            },
            'preferences': {
                'theme': user.theme,
                'accent_color': user.accent_color,
                'default_view': user.default_view,
            },
            'events': [],
            'templates': []
        }
        
        # Add user's events
        for event in Event.objects.filter(created_by=user):
            user_data['events'].append({
                'id': str(event.id),
                'type': event.type,
                'start_date': event.start_date.isoformat(),
                'end_date': event.end_date.isoformat() if event.end_date else None,
                'time': event.time_display,
                'location': event.location,
                'group': event.group,
                'details': event.description,
                'status': event.status,
                'created': event.created.isoformat(),
            })
        
        # Add user's templates
        for template in EmailTemplate.objects.filter(created_by=user):
            user_data['templates'].append({
                'id': str(template.id),
                'name': template.name,
                'subject': template.subject,
                'body': template.body,
                'created': template.created.isoformat(),
            })
        
        logger.info(f"User {user.id} exported data")
        
        from django.http import JsonResponse
        
        response = JsonResponse(user_data, json_dumps_params={'indent': 2})
        response['Content-Disposition'] = f'attachment; filename="user_data_{user.username}.json"'
        return response
        
    except Exception as e:
        logger.error(f"Error exporting data for user {request.user.id}: {e}")
        messages.error(request, 'Error exporting data. Please try again.')
        return redirect('event_management:settings')


@login_required
def get_user_stats(request):
    """Get user statistics for settings dashboard."""
    try:
        user = request.user
        
        stats = {
            'total_events': Event.objects.filter(created_by=user).count(),
            'active_events': Event.objects.filter(created_by=user, is_archived=False).count(),
            'archived_events': Event.objects.filter(created_by=user, is_archived=True).count(),
            'email_templates': EmailTemplate.objects.filter(created_by=user).count(),
            'account_age_days': (timezone.now() - user.date_joined).days,
            'last_login': user.last_login.isoformat() if user.last_login else None,
        }
        
        return JsonResponse(stats)
        
    except Exception as e:
        logger.error(f"Error getting stats for user {request.user.id}: {e}")
        return JsonResponse({'error': 'Error loading statistics'}, status=500)


def _get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip