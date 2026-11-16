# SPDX-License-Identifier: Apache-2.0
"""
Calendar views for HillDesk.
"""
from django.views.generic import TemplateView, RedirectView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.http import JsonResponse
from django.urls import reverse
from django.core.cache import cache
from django.db.models import Q
from django.core.exceptions import ValidationError, PermissionDenied
from datetime import datetime, date, time, timedelta
import calendar
from apps.event_management.utils.json_embed import script_safe_json
import logging

from apps.authentication.permissions import Permissions

from ..models import Event
from ..utils import CalendarColorManager

logger = logging.getLogger(__name__)


class CalendarView(LoginRequiredMixin, TemplateView):
    """Main calendar view supporting multiple display modes (month, week, day)."""
    
    def get_template_names(self):
        """Return modern calendar template."""
        return ['event_management/calendar_modern.html']
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get view parameters with validation
        view_type = self.kwargs.get('view_type', 'month')
        year = self.kwargs.get('year', timezone.now().year)
        month = self.kwargs.get('month', timezone.now().month)
        day = self.kwargs.get('day', timezone.now().day)
        
        # Get timezone from session or default to EST
        selected_timezone = self.request.session.get('calendar_timezone', 'America/New_York')
        
        # Validate view type
        if view_type not in ['month', 'week', 'day']:
            view_type = 'month'
        
        # Validate and create current date with comprehensive error handling
        current_date = None
        date_error = None
        
        try:
            # Validate year range (reasonable bounds)
            if not (1900 <= year <= 2100):
                raise ValueError(f"Year {year} is out of valid range")
            
            # Validate month
            if not (1 <= month <= 12):
                raise ValueError(f"Month {month} is not valid")
            
            # For day view, validate the specific day
            if view_type == 'day':
                # Validate day exists in the given month/year
                if not (1 <= day <= 31):
                    raise ValueError(f"Day {day} is not valid")
                current_date = date(year, month, day)
            else:
                # For month and week views, use the first day of the month
                current_date = date(year, month, 1)
                # For week view, adjust to the specific day if provided
                if view_type == 'week' and day:
                    try:
                        current_date = date(year, month, day)
                    except ValueError:
                        # If specific day is invalid, use first day of month
                        current_date = date(year, month, 1)
                        
        except ValueError as e:
            # Invalid date parameters, default to today
            today = timezone.localdate()  # office-local, like the dashboard
            current_date = today
            year = today.year
            month = today.month
            day = today.day
            date_error = str(e)
            
            # Log the error for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Invalid calendar date parameters: {e}. Defaulting to today: {today}")
        
        # Ensure we have a valid date
        if current_date is None:
            current_date = timezone.now().date()
            year = current_date.year
            month = current_date.month
            day = current_date.day
        
        # Get events for the current period
        events = self.get_events_for_period(view_type, current_date)
        
        # Build calendar data based on view type
        if view_type == 'month':
            calendar_data = self.build_monthly_calendar(current_date, events)
        elif view_type == 'week':
            calendar_data = self.build_weekly_calendar(current_date, events)
        else:  # day
            calendar_data = self.build_daily_calendar(current_date, events)
        
        # Navigation URLs
        navigation = self.build_navigation_urls(view_type, current_date)
        
        # Get filter choices for the UI (office-specific if available)
        from django.conf import settings
        user = self.request.user
        office = getattr(user, 'office', None) if user.is_authenticated else None

        if office:
            # Office-specific choices
            status_choices_list = office.get_active_statuses()
            type_choices_list = office.get_active_types()
            format_choices_list = office.get_active_formats()
            # Convert to tuple format for template compatibility
            status_choices = [(s['value'], s['label']) for s in status_choices_list]
            type_choices = [(t['value'], t['label']) for t in type_choices_list]
        else:
            # Fallback to global defaults
            status_choices_list = getattr(settings, 'DEFAULT_EVENT_STATUS_CHOICES', [])
            type_choices_list = getattr(settings, 'DEFAULT_EVENT_TYPE_CHOICES', [])
            format_choices_list = getattr(settings, 'DEFAULT_EVENT_FORMAT_CHOICES', [])
            status_choices = settings.EVENT_STATUS_CHOICES
            type_choices = settings.EVENT_TYPE_CHOICES

        filter_choices = {
            'status_choices': status_choices,
            'type_choices': type_choices,
        }

        # Serialize filter choices for JavaScript (with keys matching JS expectations)
        filter_choices_json = {
            'event_statuses': status_choices_list,
            'event_types': type_choices_list,
            'event_formats': format_choices_list,
            'staff': [],
        }
        
        # Add additional context for enhanced navigation and color coding
        context.update({
            'view_type': view_type,
            'current_date': current_date,
            'events': events,
            'calendar_data': calendar_data,
            'navigation': navigation,
            'year': year,
            'month': month,
            'day': day,
            'date_error': date_error,
            'month_name': current_date.strftime('%B'),
            'year_display': current_date.year,
            'today': timezone.now().date(),
            'color_legend': CalendarColorManager.get_legend_data(),
            'filter_choices': filter_choices,
            'filter_choices_json': script_safe_json(filter_choices_json),
            # Office-specific status choices for CSS variable generation
            'office_status_choices': status_choices_list,
        })
        
        # Add timezone information to context
        context.update({
            'selected_timezone': selected_timezone,
            'timezone_choices': [
                ('America/New_York', 'Eastern Time (EST)'),
                ('America/Chicago', 'Central Time (CST)'),
                ('America/Denver', 'Mountain Time (MST)'),
                ('America/Los_Angeles', 'Pacific Time (PST)'),
                ('America/Anchorage', 'Alaska Time (AKST)'),
                ('Pacific/Honolulu', 'Hawaii Time (HST)'),
                ('UTC', 'UTC'),
            ],
            'events_json': script_safe_json([
                {
                    'id': str(event.id),
                    'title': event.title or event.group or 'Untitled Event',
                    'group': event.group or '',
                    'start_date': event.start_date.isoformat() if event.start_date else None,
                    'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
                    'end_date': event.end_date.isoformat() if event.end_date else None,
                    'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
                    'location': event.location or '',
                    'status': event.status,
                    'status_display': event.get_status_display_from_office(),
                    'type': event.type or '',
                    'type_display': event.get_type_display_from_office() if event.type else '',
                    'is_longer_than_day': event.is_longer_than_day,
                    'is_date_range': event.is_date_range,
                    'time_notes': event.time_notes or '',
                    'requires_human_review': event.requires_human_review,
                } for event in events
            ])
        })
        
        return context
    
    def convert_event_time_to_timezone(self, event, target_timezone_str):
        """Convert event times to target timezone (simplified version for now)."""
        # For now, just return the event as-is to avoid timezone conversion issues
        # TODO: Implement proper timezone conversion when pytz is available
        return event
    
    def get_period_display(self, view_type, current_date):
        """Get detailed period display information."""
        today = timezone.localdate()  # office-local, like the dashboard
        
        if view_type == 'month':
            period_display = current_date.strftime('%B %Y')
            period_short = current_date.strftime('%b %Y')
        elif view_type == 'week':
            # Calculate week boundaries
            days_since_sunday = (current_date.weekday() + 1) % 7
            start_of_week = current_date - timedelta(days=days_since_sunday)
            end_of_week = start_of_week + timedelta(days=6)
            
            if start_of_week.year == end_of_week.year:
                if start_of_week.month == end_of_week.month:
                    period_display = f"{start_of_week.strftime('%B %d')} - {end_of_week.strftime('%d, %Y')}"
                    period_short = f"{start_of_week.strftime('%b %d')} - {end_of_week.strftime('%d')}"
                else:
                    period_display = f"{start_of_week.strftime('%B %d')} - {end_of_week.strftime('%B %d, %Y')}"
                    period_short = f"{start_of_week.strftime('%b %d')} - {end_of_week.strftime('%b %d')}"
            else:
                period_display = f"{start_of_week.strftime('%B %d, %Y')} - {end_of_week.strftime('%B %d, %Y')}"
                period_short = f"{start_of_week.strftime('%b %d, %Y')} - {end_of_week.strftime('%b %d, %Y')}"
        else:  # day
            period_display = current_date.strftime('%A, %B %d, %Y')
            period_short = current_date.strftime('%a, %b %d')
            
        return {
            'display': period_display,
            'short': period_short,
            'is_today': current_date == today,
            'is_current_month': current_date.month == today.month and current_date.year == today.year,
            'is_current_week': self._is_same_week(current_date, today),
        }
    
    def _is_same_week(self, date1, date2):
        """Check if two dates are in the same week (Sunday-based)."""
        # Calculate start of week for both dates
        days_since_sunday1 = (date1.weekday() + 1) % 7
        start_of_week1 = date1 - timedelta(days=days_since_sunday1)
        
        days_since_sunday2 = (date2.weekday() + 1) % 7
        start_of_week2 = date2 - timedelta(days=days_since_sunday2)
        
        return start_of_week1 == start_of_week2


    def get_events_for_period(self, view_type, current_date):
        """Get events for the specified time period using new event model structure.

        Fetches events that OVERLAP with the period, not just those that start within it.
        This ensures multi-day events spanning across weeks/months are shown.
        """
        from django.db.models import Q

        if view_type == 'month':
            # Get events for the entire calendar view (including prev/next month days)
            cal = calendar.Calendar(firstweekday=6)  # Start week on Sunday
            month_calendar = cal.monthdatescalendar(current_date.year, current_date.month)

            # Get the first and last dates from the calendar grid
            start_date = month_calendar[0][0]  # First date in calendar
            end_date = month_calendar[-1][-1]  # Last date in calendar

        elif view_type == 'week':
            # Get events for the week containing current_date (Sunday-based week)
            days_since_sunday = (current_date.weekday() + 1) % 7
            start_date = current_date - timedelta(days=days_since_sunday)
            end_date = start_date + timedelta(days=6)
        else:  # day
            start_date = current_date
            end_date = current_date

        # Query for overlapping events:
        # An event overlaps if it starts before/on period end AND ends on/after period start
        from apps.authentication.permissions import Permissions
        queryset = Event.objects.filter(
            Q(start_date__lte=end_date) &  # Event starts before or on period end
            (Q(end_date__gte=start_date) | Q(end_date__isnull=True) | Q(end_date=None)),  # Event ends on/after period start
            is_archived=False,  # Only show non-archived events
            requires_human_review=False  # Hide events pending human review
        ).select_related('created_by', 'modified_by').order_by('start_date', 'start_time')
        # Restrict to events this user is allowed to view.
        return Permissions.scope_events_queryset(self.request.user, queryset)
    
    def build_monthly_calendar(self, current_date, events):
        """Build monthly calendar grid data with proper 7x6 grid layout."""
        cal = calendar.Calendar(firstweekday=6)  # Start week on Sunday
        
        # Get all dates for the calendar view (including prev/next month)
        month_calendar = cal.monthdatescalendar(current_date.year, current_date.month)
        
        # Ensure we always have 6 weeks (42 days) for consistent grid layout
        while len(month_calendar) < 6:
            # Add empty week if needed
            last_date = month_calendar[-1][-1]
            new_week = []
            for i in range(7):
                last_date = last_date + timedelta(days=1)
                new_week.append(last_date)
            month_calendar.append(new_week)
        
        # Create events lookup by date
        events_by_date = {}
        for event in events:
            # Use start_date for calendar positioning (already a DateField)
            event_date = event.start_date
            if event_date not in events_by_date:
                events_by_date[event_date] = []
            events_by_date[event_date].append(event)
            
            # Handle multi-day events (is_longer_than_day=True)
            if event.is_longer_than_day and event.end_date:
                current_date = event.start_date + timedelta(days=1)
                while current_date <= event.end_date:
                    if current_date not in events_by_date:
                        events_by_date[current_date] = []
                    events_by_date[current_date].append(event)
                    current_date += timedelta(days=1)
        
        # Build calendar grid
        calendar_weeks = []
        today = timezone.localdate()  # office-local, like the dashboard
        
        for week_dates in month_calendar:
            calendar_week = []
            for day_date in week_dates:
                is_current_month = (day_date.month == current_date.month and 
                                  day_date.year == current_date.year)
                
                calendar_week.append({
                    'day': day_date.day,
                    'date': day_date,
                    'events': events_by_date.get(day_date, []),
                    'is_today': day_date == today,
                    'is_current_month': is_current_month
                })
            calendar_weeks.append(calendar_week)
        
        return {
            'weeks': calendar_weeks,
            'month_name': current_date.strftime('%B'),
            'year': current_date.year,
            'total_weeks': len(calendar_weeks),
            'total_days': len(calendar_weeks) * 7
        }
    
    def build_weekly_calendar(self, current_date, events):
        """Build weekly calendar data with 7-day layout and hourly time slots."""
        # Get start of week (Sunday) - weekday() returns 0=Monday, 6=Sunday
        # We want Sunday=0, so we adjust the calculation
        days_since_sunday = (current_date.weekday() + 1) % 7
        start_of_week = current_date - timedelta(days=days_since_sunday)
        
        # Create events lookup by date
        events_by_date = {}
        for event in events:
            # Use start_date for calendar positioning (already a DateField)
            event_date = event.start_date
            if event_date not in events_by_date:
                events_by_date[event_date] = []
            events_by_date[event_date].append(event)
            
            # Handle multi-day events (is_longer_than_day=True)
            if event.is_longer_than_day and event.end_date:
                current_date = event.start_date + timedelta(days=1)
                while current_date <= event.end_date:
                    if current_date not in events_by_date:
                        events_by_date[current_date] = []
                    events_by_date[current_date].append(event)
                    current_date += timedelta(days=1)
        
        # Build 7 days with hourly time slots
        week_days = []
        today = timezone.localdate()  # office-local, like the dashboard
        
        for i in range(7):
            day_date = start_of_week + timedelta(days=i)
            day_events = events_by_date.get(day_date, [])
            
            # Create hourly time slots (8 AM to 6 PM - business hours)
            time_slots = []
            for hour in range(8, 19):  # 8 AM to 6 PM
                slot_events = []
                
                # Find events that fall in this hour slot
                for event in day_events:
                    if event.start_time:
                        # Use the new start_time field (TimeField)
                        event_hour = event.start_time.hour
                        if event_hour == hour:
                            slot_events.append(event)
                    else:
                        # Events without specific time go in the 8 AM slot
                        if hour == 8:
                            slot_events.append(event)
                
                time_slots.append({
                    'hour': hour,
                    'time_display': f"{hour:02d}:00",
                    'time_12h': f"{hour if hour <= 12 else hour-12}:00 {'AM' if hour < 12 else 'PM'}",
                    'events': slot_events
                })
            
            week_days.append({
                'date': day_date,
                'events': day_events,
                'time_slots': time_slots,
                'is_today': day_date == today,
                'day_name': day_date.strftime('%A'),
                'day_short': day_date.strftime('%a')
            })
        
        return {
            'days': week_days,
            'week_start': start_of_week,
            'week_end': start_of_week + timedelta(days=6),
            'week_display': f"{start_of_week.strftime('%b %d')} - {(start_of_week + timedelta(days=6)).strftime('%b %d, %Y')}"
        }
    
    def build_daily_calendar(self, current_date, events):
        """Build daily calendar data with single-day hourly breakdown using new event model."""
        # Filter events for the specific date
        day_events = []
        for event in events:
            # Use start_date for calendar positioning (already a DateField)
            if event.start_date == current_date:
                day_events.append(event)
            # Also include multi-day events that span this date
            elif event.is_longer_than_day and event.end_date and event.start_date <= current_date <= event.end_date:
                day_events.append(event)
        
        # Create detailed hourly time slots (5 AM to 11 PM)
        time_slots = []
        for hour in range(5, 24):  # 5 AM to 11 PM
            slot_events = []
            
            # Find events that fall in this hour slot
            for event in day_events:
                if event.start_time:
                    # Use the new start_time field (TimeField)
                    event_hour = event.start_time.hour
                    if event_hour == hour:
                        slot_events.append(event)
                else:
                    # Events without specific time go in the 9 AM slot
                    if hour == 9:
                        slot_events.append(event)
            
            time_slots.append({
                'hour': hour,
                'time_display': f"{hour:02d}:00",
                'time_12h': f"{hour if hour <= 12 else hour-12}:00 {'AM' if hour < 12 else 'PM'}",
                'events': slot_events,
                'has_events': len(slot_events) > 0
            })
        
        return {
            'date': current_date,
            'events': day_events,
            'time_slots': time_slots,
            'is_today': current_date == timezone.now().date(),
            'day_name': current_date.strftime('%A'),
            'date_display': current_date.strftime('%B %d, %Y')
        }
    
    def build_navigation_urls(self, view_type, current_date):
        """Build previous/next navigation URLs."""
        from django.urls import reverse
        
        if view_type == 'month':
            # Previous/next month
            if current_date.month == 1:
                prev_date = date(current_date.year - 1, 12, 1)
            else:
                prev_date = date(current_date.year, current_date.month - 1, 1)
            
            if current_date.month == 12:
                next_date = date(current_date.year + 1, 1, 1)
            else:
                next_date = date(current_date.year, current_date.month + 1, 1)
            
            prev_url = reverse('event_management:calendar_date', kwargs={
                'view_type': 'month',
                'year': prev_date.year,
                'month': prev_date.month
            })
            next_url = reverse('event_management:calendar_date', kwargs={
                'view_type': 'month',
                'year': next_date.year,
                'month': next_date.month
            })
            current_period = current_date.strftime('%B %Y')
            
        elif view_type == 'week':
            # Previous/next week
            prev_date = current_date - timedelta(days=7)
            next_date = current_date + timedelta(days=7)
            
            prev_url = reverse('event_management:calendar_date', kwargs={
                'view_type': 'week',
                'year': prev_date.year,
                'month': prev_date.month,
                'day': prev_date.day
            })
            next_url = reverse('event_management:calendar_date', kwargs={
                'view_type': 'week',
                'year': next_date.year,
                'month': next_date.month,
                'day': next_date.day
            })
            
            # Week range display - use same logic as build_weekly_calendar
            days_since_sunday = (current_date.weekday() + 1) % 7
            start_of_week = current_date - timedelta(days=days_since_sunday)
            end_of_week = start_of_week + timedelta(days=6)
            current_period = f"{start_of_week.strftime('%b %d')} - {end_of_week.strftime('%b %d, %Y')}"
            
        else:  # day
            # Previous/next day
            prev_date = current_date - timedelta(days=1)
            next_date = current_date + timedelta(days=1)
            
            prev_url = reverse('event_management:calendar_date', kwargs={
                'view_type': 'day',
                'year': prev_date.year,
                'month': prev_date.month,
                'day': prev_date.day
            })
            next_url = reverse('event_management:calendar_date', kwargs={
                'view_type': 'day',
                'year': next_date.year,
                'month': next_date.month,
                'day': next_date.day
            })
            current_period = current_date.strftime('%A, %B %d, %Y')
        
        # Add "Today" navigation URL
        today = timezone.localdate()  # office-local, like the dashboard
        today_url = reverse('event_management:calendar_date', kwargs={
            'view_type': view_type,
            'year': today.year,
            'month': today.month,
            'day': today.day if view_type in ['week', 'day'] else 1
        })
        
        return {
            'prev_url': prev_url,
            'next_url': next_url,
            'today_url': today_url,
            'current_period': current_period,
            'is_today': current_date == today,
            'view_type': view_type
        }


class CalendarTodayRedirectView(LoginRequiredMixin, RedirectView):
    """Redirect to today's date in the specified view type."""
    
    permanent = False
    
    def get_redirect_url(self, *args, **kwargs):
        view_type = kwargs.get('view_type', 'month')
        today = timezone.localdate()  # office-local, like the dashboard
        
        # Validate view type
        if view_type not in ['month', 'week', 'day']:
            view_type = 'month'
        
        # Build URL for today's date
        if view_type == 'month':
            return reverse('event_management:calendar_date', kwargs={
                'view_type': 'month',
                'year': today.year,
                'month': today.month
            })
        else:
            return reverse('event_management:calendar_date', kwargs={
                'view_type': view_type,
                'year': today.year,
                'month': today.month,
                'day': today.day
            })


class CalendarEventAPIView(LoginRequiredMixin, View):
    """
    Enhanced API endpoint for loading calendar event data with filtering support.
    Provides optimized responses with proper error handling and security checks.
    """
    
    def dispatch(self, request, *args, **kwargs):
        """Add security checks and logging."""
        # Log API access for security auditing
        logger.info(f"Calendar API accessed by user {request.user.id} from IP {self.get_client_ip(request)}")
        
        # Check if user has permission to view events
        if not request.user.is_authenticated:
            logger.warning(f"Unauthenticated calendar API access attempt from IP {self.get_client_ip(request)}")
            return JsonResponse({
                'success': False,
                'error': 'Authentication required'
            }, status=401)
        
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request, *args, **kwargs):
        """Return filtered calendar events as JSON with enhanced error handling."""
        try:
            # Validate and sanitize input parameters
            view_type, current_date, status_filters, type_filters, timezone_param, extra_filters = self.validate_and_parse_parameters(request)

            # Generate cache key for this request
            cache_key = self.generate_cache_key(request.user.id, view_type, current_date, status_filters, type_filters, timezone_param, extra_filters)

            # Try to get cached response
            cached_response = cache.get(cache_key)
            if cached_response:
                logger.debug(f"Returning cached calendar data for user {request.user.id}")
                return JsonResponse(cached_response)

            # Get events for the period with user-specific filtering
            events = self.get_filtered_events_for_period(
                request.user, view_type, current_date, status_filters, type_filters, extra_filters
            )
            
            # Build optimized calendar data based on view type
            calendar_data = self.build_calendar_data(view_type, current_date, events)
            
            # Build response
            response_data = {
                'success': True,
                'calendar_data': calendar_data,
                'filters_applied': {
                    'status': status_filters,
                    'type': type_filters
                },
                'total_events': len(events),
                'view_type': view_type,
                'current_date': current_date.isoformat(),
                'cache_timestamp': timezone.now().isoformat()
            }
            
            # Cache the response for 5 minutes
            cache.set(cache_key, response_data, 300)
            
            logger.info(f"Calendar API returned {len(events)} events for user {request.user.id}")
            return JsonResponse(response_data)
            
        except ValidationError as e:
            logger.warning(f"Calendar API validation error for user {request.user.id}: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Invalid parameters provided',
                'details': str(e)
            }, status=400)
            
        except PermissionDenied as e:
            logger.warning(f"Calendar API permission denied for user {request.user.id}: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
            
        except Exception as e:
            logger.error(f"Calendar API error for user {request.user.id}: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'An unexpected error occurred'
            }, status=500)
    
    def validate_and_parse_parameters(self, request):
        """Validate and parse request parameters with proper error handling."""
        # Get and validate view type
        view_type = request.GET.get('view_type', 'month')
        if view_type not in ['month', 'week', 'day']:
            raise ValidationError(f"Invalid view_type: {view_type}. Must be 'month', 'week', or 'day'")
        
        # Get timezone parameter (validation simplified for now)
        timezone_param = request.GET.get('timezone', 'America/New_York')
        # TODO: Add proper timezone validation when timezone library is available
        
        # Store timezone in session (if session exists)
        if hasattr(request, 'session'):
            request.session['calendar_timezone'] = timezone_param
        
        # Get and validate date parameters
        try:
            year = int(request.GET.get('year', timezone.now().year))
            month = int(request.GET.get('month', timezone.now().month))
            day = int(request.GET.get('day', timezone.now().day))
            
            # Validate year range (reasonable bounds)
            if not (1900 <= year <= 2100):
                raise ValidationError(f"Year {year} is out of valid range (1900-2100)")
            
            # Validate month
            if not (1 <= month <= 12):
                raise ValidationError(f"Month {month} is not valid (1-12)")
            
            # Create current date based on view type
            if view_type == 'day':
                if not (1 <= day <= 31):
                    raise ValidationError(f"Day {day} is not valid (1-31)")
                current_date = date(year, month, day)
            else:
                current_date = date(year, month, 1)
                if view_type == 'week' and day:
                    try:
                        current_date = date(year, month, day)
                    except ValueError:
                        # If specific day is invalid, use first day of month
                        current_date = date(year, month, 1)
                        
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid date parameters: {str(e)}")
        
        # Get and validate filter parameters
        status_filters = request.GET.getlist('status')
        type_filters = request.GET.getlist('type')
        
        # Validate status filters against allowed choices (office-specific or global)
        from django.conf import settings
        user = request.user
        office = getattr(user, 'office', None) if user.is_authenticated else None

        if office:
            # Get valid values from office choices (include inactive for existing events)
            valid_statuses = [s['value'] for s in office.event_status_choices]
            valid_types = [t['value'] for t in office.event_type_choices]
        else:
            # Fallback to global defaults
            valid_statuses = [choice[0] for choice in settings.EVENT_STATUS_CHOICES]
            valid_types = [choice[0] for choice in settings.EVENT_TYPE_CHOICES]

        invalid_statuses = [s for s in status_filters if s not in valid_statuses]
        if invalid_statuses:
            raise ValidationError(f"Invalid status filters: {invalid_statuses}")

        invalid_types = [t for t in type_filters if t not in valid_types]
        if invalid_types:
            raise ValidationError(f"Invalid type filters: {invalid_types}")

        # Extract additional filter parameters (no validation needed for these)
        staff_filters = request.GET.getlist('staff')
        source_filters = request.GET.getlist('source')
        my_events = request.GET.get('my_events') == 'true'
        overlapping_only = request.GET.get('overlapping_only') == 'true'

        extra_filters = {
            'staff': staff_filters,
            'source': source_filters,
            'my_events': my_events,
            'overlapping_only': overlapping_only,
        }

        return view_type, current_date, status_filters, type_filters, timezone_param, extra_filters
    
    def generate_cache_key(self, user_id, view_type, current_date, status_filters, type_filters, timezone_param, extra_filters=None):
        """Generate a cache key for the request."""
        extra = extra_filters or {}
        filters_str = (
            f"status:{','.join(sorted(status_filters))}"
            f"_type:{','.join(sorted(type_filters))}"
            f"_staff:{','.join(sorted(extra.get('staff', [])))}"
            f"_source:{','.join(sorted(extra.get('source', [])))}"
            f"_my:{extra.get('my_events', False)}"
            f"_overlap:{extra.get('overlapping_only', False)}"
            f"_tz:{timezone_param}"
        )
        return f"calendar_api:{user_id}:{view_type}:{current_date.isoformat()}:{hash(filters_str)}"
    
    def get_client_ip(self, request):
        """Get the client IP address from the request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_filtered_events_for_period(self, user, view_type, current_date, status_filters, type_filters, extra_filters=None):
        """
        Get events for the specified time period with filters applied.
        Includes user permission checks and query optimization.

        Uses overlap query to find events that OVERLAP with the period,
        not just those that start within it. This ensures multi-day events
        spanning across weeks/months are shown on all relevant periods.
        """
        extra = extra_filters or {}

        # Calculate date range based on view type
        start_date, end_date = self.calculate_date_range(view_type, current_date)

        # Base queryset with optimizations
        # Query for overlapping events: event.start_date <= period_end AND event.end_date >= period_start
        from apps.authentication.permissions import Permissions
        queryset = Event.objects.filter(
            Q(start_date__lte=end_date) &
            (Q(end_date__gte=start_date) | Q(end_date__isnull=True)),
            is_archived=False,
            requires_human_review=False
        ).select_related(
            'created_by', 'modified_by'
        ).order_by('start_date', 'start_time')
        # Restrict to events this user is allowed to view.
        queryset = Permissions.scope_events_queryset(user, queryset)

        # Apply status filters
        if status_filters:
            queryset = queryset.filter(status__in=status_filters)

        # Apply type filters
        if type_filters:
            queryset = queryset.filter(type__in=type_filters)

        # "My events" filter — events where user is assigned staff or an approver
        if extra.get('my_events'):
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

            staff_q = Q()
            for name in names:
                staff_q |= Q(staff__icontains=name)
            for email in emails:
                staff_q |= Q(staff__icontains=email)

            approval_q = Q()
            for name in names:
                approval_q |= Q(approval_routing__icontains=name)
            for email in emails:
                approval_q |= Q(approval_routing__icontains=email)

            queryset = queryset.filter(staff_q | approval_q)

        # "Overlapping events" filter — only events that overlap with at least one other.
        # Check against ALL non-archived events in the date range so that
        # status/type filters don't exclude the counterpart of a genuine overlap.
        if extra.get('overlapping_only'):
            all_dated = list(
                Event.objects.filter(
                    is_archived=False,
                    requires_human_review=False,
                ).exclude(start_date__isnull=True)
                .filter(
                    Q(start_date__lte=end_date) &
                    (Q(end_date__gte=start_date) | Q(end_date__isnull=True))
                )
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

        # Filter by staff name (supports multiple values)
        staff_filters = extra.get('staff', [])
        if staff_filters:
            staff_q = Q()
            for name in staff_filters:
                staff_q |= Q(staff__icontains=name)
            queryset = queryset.filter(staff_q)

        # Filter by source (email vs manual)
        source_filters = extra.get('source', [])
        if source_filters and set(source_filters) != {'email', 'manual'}:
            if 'email' in source_filters and 'manual' not in source_filters:
                queryset = queryset.filter(source_emails__isnull=False).distinct()
            elif 'manual' in source_filters and 'email' not in source_filters:
                queryset = queryset.exclude(
                    id__in=Event.objects.filter(source_emails__isnull=False).values_list('id', flat=True)
                )

        logger.debug(f"Calendar query for user {user.id}: {len(status_filters)} status filters, {len(type_filters)} type filters, date range {start_date} to {end_date}")

        return queryset
    
    def calculate_date_range(self, view_type, current_date):
        """Calculate the start and end dates for the given view type and date."""
        if view_type == 'month':
            # Get events for the entire calendar view (including prev/next month days)
            cal = calendar.Calendar(firstweekday=6)  # Start week on Sunday
            month_calendar = cal.monthdatescalendar(current_date.year, current_date.month)
            
            # Get the first and last dates from the calendar grid
            start_date = month_calendar[0][0]  # First date in calendar
            end_date = month_calendar[-1][-1]  # Last date in calendar
                    
        elif view_type == 'week':
            # Get events for the week containing current_date
            days_since_sunday = (current_date.weekday() + 1) % 7
            start_date = current_date - timedelta(days=days_since_sunday)
            end_date = start_date + timedelta(days=6)
        else:  # day
            start_date = current_date
            end_date = current_date
        
        return start_date, end_date
    
    def build_calendar_data(self, view_type, current_date, events):
        """Build calendar data based on view type with optimized structure."""
        if view_type == 'month':
            return self.build_monthly_calendar_data(current_date, events)
        elif view_type == 'week':
            return self.build_weekly_calendar_data(current_date, events)
        else:  # day
            return self.build_daily_calendar_data(current_date, events)
    
    def build_monthly_calendar_data(self, current_date, events):
        """Build monthly calendar grid data for API response using new event model."""
        cal = calendar.Calendar(firstweekday=6)  # Start week on Sunday
        month_calendar = cal.monthdatescalendar(current_date.year, current_date.month)

        # Ensure we always have 6 weeks (42 days) for consistent grid layout
        while len(month_calendar) < 6:
            last_date = month_calendar[-1][-1]
            new_week = []
            for i in range(7):
                last_date = last_date + timedelta(days=1)
                new_week.append(last_date)
            month_calendar.append(new_week)

        # Create events lookup by date using new event model
        events_by_date = {}
        for event in events:
            # Use start_date for calendar positioning (already a DateField)
            event_date = event.start_date
            if event_date not in events_by_date:
                events_by_date[event_date] = []

            # Format time display using new start_time field
            time_display = 'TBD'
            if event.start_time:
                time_display = event.start_time.strftime('%I:%M %p')
                if event.end_time:
                    time_display += f" - {event.end_time.strftime('%I:%M %p')}"

            events_by_date[event_date].append({
                'id': str(event.id),
                'title': event.title or event.group or 'Untitled Event',
                'group': event.group or '',
                'time': time_display,
                'start_date': event.start_date.isoformat() if event.start_date else None,
                'end_date': event.end_date.isoformat() if event.end_date else None,
                'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
                'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
                'location': event.location or 'TBD',
                'status': event.status,
                'status_display': event.get_status_display_from_office(),
                'type': event.type,
                'type_display': event.get_type_display_from_office() if event.type else '',
                'is_longer_than_day': event.is_longer_than_day,
                'is_date_range': event.is_date_range,
                'time_notes': event.time_notes or '',
            })

            # Handle multi-day events (is_longer_than_day=True)
            if event.is_longer_than_day and event.end_date:
                current_date_iter = event.start_date + timedelta(days=1)
                while current_date_iter <= event.end_date:
                    if current_date_iter not in events_by_date:
                        events_by_date[current_date_iter] = []
                    events_by_date[current_date_iter].append({
                        'id': str(event.id),
                        'title': f"{event.title or event.group or 'Untitled Event'} (cont.)",
                        'group': event.group or '',
                        'time': 'Multi-day event',
                        'start_date': current_date_iter.isoformat(),
                        'end_date': event.end_date.isoformat() if event.end_date else None,
                        'original_start_date': event.start_date.isoformat() if event.start_date else None,
                        'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
                        'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
                        'location': event.location or 'TBD',
                        'status': event.status,
                        'status_display': event.get_status_display_from_office(),
                        'type': event.type,
                        'type_display': event.get_type_display_from_office() if event.type else '',
                        'is_longer_than_day': True,
                        'is_date_range': event.is_date_range,
                        'time_notes': event.time_notes or '',
                        'is_continuation': True,
                    })
                    current_date_iter += timedelta(days=1)

        # Build calendar grid
        calendar_weeks = []
        today = timezone.localdate()  # office-local, like the dashboard
        
        for week_dates in month_calendar:
            calendar_week = []
            for day_date in week_dates:
                is_current_month = (day_date.month == current_date.month and 
                                  day_date.year == current_date.year)
                
                calendar_week.append({
                    'day': day_date.day,
                    'date': day_date.isoformat(),
                    'events': events_by_date.get(day_date, []),
                    'is_today': day_date == today,
                    'is_current_month': is_current_month
                })
            calendar_weeks.append(calendar_week)
        
        return {
            'weeks': calendar_weeks,
            'view_type': 'month'
        }
    
    def build_weekly_calendar_data(self, current_date, events):
        """Build weekly calendar data for API response."""
        # Get start of week (Sunday)
        days_since_sunday = (current_date.weekday() + 1) % 7
        start_of_week = current_date - timedelta(days=days_since_sunday)

        # Create events lookup by date using new event model
        events_by_date = {}
        for event in events:
            # Use start_date for calendar positioning (already a DateField)
            event_date = event.start_date
            if event_date not in events_by_date:
                events_by_date[event_date] = []

            # Format time display using new start_time field
            time_display = 'TBD'
            if event.start_time:
                time_display = event.start_time.strftime('%I:%M %p')
                if event.end_time:
                    time_display += f" - {event.end_time.strftime('%I:%M %p')}"

            events_by_date[event_date].append({
                'id': str(event.id),
                'title': event.title or event.group or 'Untitled Event',
                'group': event.group or '',
                'time': time_display,
                'start_date': event.start_date.isoformat() if event.start_date else None,
                'end_date': event.end_date.isoformat() if event.end_date else None,
                'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
                'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
                'location': event.location or 'TBD',
                'status': event.status,
                'status_display': event.get_status_display_from_office(),
                'type': event.type,
                'type_display': event.get_type_display_from_office() if event.type else '',
                'is_longer_than_day': event.is_longer_than_day,
                'is_date_range': event.is_date_range,
                'time_notes': event.time_notes or '',
            })

            # Handle multi-day events (is_longer_than_day=True)
            if event.is_longer_than_day and event.end_date:
                current_date_iter = event.start_date + timedelta(days=1)
                while current_date_iter <= event.end_date:
                    if current_date_iter not in events_by_date:
                        events_by_date[current_date_iter] = []
                    events_by_date[current_date_iter].append({
                        'id': str(event.id),
                        'title': f"{event.title or event.group or 'Untitled Event'} (cont.)",
                        'group': event.group or '',
                        'time': 'Multi-day event',
                        'start_date': current_date_iter.isoformat(),
                        'end_date': event.end_date.isoformat() if event.end_date else None,
                        'original_start_date': event.start_date.isoformat() if event.start_date else None,
                        'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
                        'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
                        'location': event.location or 'TBD',
                        'status': event.status,
                        'status_display': event.get_status_display_from_office(),
                        'type': event.type,
                        'type_display': event.get_type_display_from_office() if event.type else '',
                        'is_longer_than_day': True,
                        'is_date_range': event.is_date_range,
                        'time_notes': event.time_notes or '',
                        'is_continuation': True,
                    })
                    current_date_iter += timedelta(days=1)

        # Build 7 days
        week_days = []
        today = timezone.localdate()  # office-local, like the dashboard
        
        for i in range(7):
            day_date = start_of_week + timedelta(days=i)
            week_days.append({
                'date': day_date.isoformat(),
                'events': events_by_date.get(day_date, []),
                'is_today': day_date == today,
                'day_name': day_date.strftime('%A'),
                'day_short': day_date.strftime('%a')
            })
        
        return {
            'days': week_days,
            'view_type': 'week'
        }
    
    def build_daily_calendar_data(self, current_date, events):
        """Build daily calendar data for API response using new event model."""
        # Filter events for the specific date
        day_events = []
        for event in events:
            # Use start_date for calendar positioning (already a DateField)
            if event.start_date == current_date:
                # Format time display using new start_time field
                time_display = 'TBD'
                if event.start_time:
                    time_display = event.start_time.strftime('%I:%M %p')
                    if event.end_time:
                        time_display += f" - {event.end_time.strftime('%I:%M %p')}"

                day_events.append({
                    'id': str(event.id),
                    'title': event.title or event.group or 'Untitled Event',
                    'group': event.group or '',
                    'time': time_display,
                    'start_date': event.start_date.isoformat() if event.start_date else None,
                    'end_date': event.end_date.isoformat() if event.end_date else None,
                    'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
                    'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
                    'location': event.location or 'TBD',
                    'status': event.status,
                    'status_display': event.get_status_display_from_office(),
                    'type': event.type,
                    'type_display': event.get_type_display_from_office() if event.type else '',
                    'is_longer_than_day': event.is_longer_than_day,
                    'is_date_range': event.is_date_range,
                    'time_notes': event.time_notes or '',
                })
            # Also include multi-day events that span this date
            elif event.is_longer_than_day and event.end_date and event.start_date <= current_date <= event.end_date:
                day_events.append({
                    'id': str(event.id),
                    'title': f"{event.title or event.group or 'Untitled Event'} (cont.)",
                    'group': event.group or '',
                    'time': 'Multi-day event',
                    'start_date': event.start_date.isoformat() if event.start_date else None,
                    'end_date': event.end_date.isoformat() if event.end_date else None,
                    'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
                    'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
                    'location': event.location or 'TBD',
                    'status': event.status,
                    'status_display': event.get_status_display_from_office(),
                    'type': event.type,
                    'type_display': event.get_type_display_from_office() if event.type else '',
                    'is_longer_than_day': True,
                    'is_date_range': event.is_date_range,
                    'time_notes': event.time_notes or '',
                    'is_continuation': True,
                })
        
        return {
            'date': current_date.isoformat(),
            'events': day_events,
            'is_today': current_date == timezone.now().date(),
            'view_type': 'day'
        }


class CalendarUpcomingEventsAPIView(LoginRequiredMixin, View):
    """
    API endpoint for loading upcoming events for sidebar display.
    """
    
    def get(self, request, *args, **kwargs):
        """Return upcoming events as JSON."""
        try:
            # Get parameters
            status_filter = request.GET.get('status_filter', '')
            type_filter = request.GET.get('type_filter', '')
            limit = int(request.GET.get('limit', 10))
            
            # Store timezone parameter (validation simplified for now)
            # TODO: Add proper timezone validation when timezone library is available
            
            # Get upcoming events (next 30 days)
            from datetime import timedelta
            today = timezone.localdate()  # office-local, like the dashboard
            end_date = today + timedelta(days=30)
            
            # Build query
            query = Permissions.scope_events_queryset(request.user, Event.objects.filter(
                start_date__gte=today,
                start_date__lte=end_date,
                is_archived=False
            ))
            
            # Apply filters
            if status_filter:
                query = query.filter(status=status_filter)
            if type_filter:
                query = query.filter(type=type_filter)
            
            # Get events ordered by date
            events = query.order_by('start_date', 'start_time')[:limit]
            
            # Format events for response with timezone conversion
            events_data = []
            for event in events:
                # Convert event times to target timezone if needed
                display_date = event.start_date
                display_start_time = event.start_time
                display_end_time = event.end_time
                
                # TODO: Add timezone conversion when timezone library is available
                # For now, use event times as-is
                
                # Format date display
                date_display = display_date.strftime('%b %d')
                if display_date.year != today.year:
                    date_display = display_date.strftime('%b %d, %Y')
                
                # Format time display
                time_display = 'TBD'
                if display_start_time:
                    time_display = display_start_time.strftime('%I:%M %p')
                    if display_end_time:
                        time_display += f" - {display_end_time.strftime('%I:%M %p')}"
                
                events_data.append({
                    'id': str(event.id),
                    'title': event.title or event.group or 'Untitled Event',
                    'group': event.group or '',
                    'date_display': date_display,
                    'time': time_display,
                    'location': event.location or 'TBD',
                    'status': event.status,
                    'status_display': event.get_status_display_from_office(),
                    'type': event.type,
                    'type_display': event.get_type_display_from_office() if event.type else '',
                    'is_date_range': event.is_date_range,
                    'time_notes': event.time_notes or '',
                })
            
            return JsonResponse({
                'success': True,
                'events': events_data,
                'total_count': len(events_data)
            })
            
        except Exception as e:
            logger.error(f"Upcoming events API error: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'An error occurred while loading upcoming events'
            }, status=500)


class CalendarNavigationAPIView(LoginRequiredMixin, View):
    """
    API endpoint for calendar navigation data.
    Provides navigation URLs, period information, and metadata.
    """
    
    def get(self, request, *args, **kwargs):
        """Return calendar navigation data as JSON."""
        try:
            # Validate parameters
            view_type = request.GET.get('view_type', 'month')
            if view_type not in ['month', 'week', 'day']:
                raise ValidationError(f"Invalid view_type: {view_type}")
            
            year = int(request.GET.get('year', timezone.now().year))
            month = int(request.GET.get('month', timezone.now().month))
            day = int(request.GET.get('day', timezone.now().day))
            
            # Create current date
            if view_type == 'day':
                current_date = date(year, month, day)
            else:
                current_date = date(year, month, 1)
                if view_type == 'week' and day:
                    try:
                        current_date = date(year, month, day)
                    except ValueError:
                        current_date = date(year, month, 1)
            
            # Build navigation data
            navigation_data = self.build_navigation_data(view_type, current_date)
            
            return JsonResponse({
                'success': True,
                'navigation': navigation_data,
                'current_date': current_date.isoformat(),
                'view_type': view_type
            })
            
        except (ValueError, ValidationError) as e:
            logger.warning(f"Calendar navigation API validation error: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Invalid parameters provided'
            }, status=400)
            
        except Exception as e:
            logger.error(f"Calendar navigation API error: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'An unexpected error occurred'
            }, status=500)
    
    def build_navigation_data(self, view_type, current_date):
        """Build navigation data for the calendar."""
        today = timezone.localdate()  # office-local, like the dashboard
        
        if view_type == 'month':
            # Previous/next month
            if current_date.month == 1:
                prev_date = date(current_date.year - 1, 12, 1)
            else:
                prev_date = date(current_date.year, current_date.month - 1, 1)
            
            if current_date.month == 12:
                next_date = date(current_date.year + 1, 1, 1)
            else:
                next_date = date(current_date.year, current_date.month + 1, 1)
            
            current_period = current_date.strftime('%B %Y')
            
        elif view_type == 'week':
            # Previous/next week
            days_since_sunday = (current_date.weekday() + 1) % 7
            start_of_week = current_date - timedelta(days=days_since_sunday)
            end_of_week = start_of_week + timedelta(days=6)
            
            prev_date = current_date - timedelta(days=7)
            next_date = current_date + timedelta(days=7)
            
            current_period = f"{start_of_week.strftime('%b %d')} - {end_of_week.strftime('%b %d, %Y')}"
            
        else:  # day
            # Previous/next day
            prev_date = current_date - timedelta(days=1)
            next_date = current_date + timedelta(days=1)
            
            current_period = current_date.strftime('%A, %B %d, %Y')
        
        return {
            'prev_date': prev_date.isoformat(),
            'next_date': next_date.isoformat(),
            'current_period': current_period,
            'is_today': current_date == today,
            'today_date': today.isoformat(),
            'view_type': view_type
        }


class CalendarMetadataAPIView(LoginRequiredMixin, View):
    """
    API endpoint for calendar metadata and configuration.
    Provides filter choices, color mappings, and other configuration data.
    """
    
    def get(self, request, *args, **kwargs):
        """Return calendar metadata as JSON."""
        try:
            from django.conf import settings

            # Get office-specific choices if available
            user = request.user
            office = getattr(user, 'office', None) if user.is_authenticated else None

            if office:
                status_choices = office.get_active_statuses()
                type_choices = office.get_active_types()
                format_choices = office.get_active_formats()
            else:
                status_choices = getattr(settings, 'DEFAULT_EVENT_STATUS_CHOICES', [])
                type_choices = getattr(settings, 'DEFAULT_EVENT_TYPE_CHOICES', [])
                format_choices = getattr(settings, 'DEFAULT_EVENT_FORMAT_CHOICES', [])

            # Get color mappings
            color_legend = CalendarColorManager.get_legend_data()

            # Build metadata
            metadata = {
                'success': True,
                'filter_choices': {
                    'status': status_choices,
                    'type': type_choices,
                    'format': format_choices
                },
                'color_legend': color_legend,
                'view_types': [
                    {'value': 'month', 'label': 'Month'},
                    {'value': 'week', 'label': 'Week'},
                    {'value': 'day', 'label': 'Day'}
                ],
                'date_formats': {
                    'month': '%B %Y',
                    'week': '%b %d - %b %d, %Y',
                    'day': '%A, %B %d, %Y'
                },
                'cache_timestamp': timezone.now().isoformat()
            }
            
            return JsonResponse(metadata)
            
        except Exception as e:
            logger.error(f"Calendar metadata API error: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'Failed to load calendar metadata'
            }, status=500)