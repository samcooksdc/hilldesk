# Design Document

## Overview

The Calendar View feature provides a modern, sleek calendar interface for HillDesk that displays events using the new event model structure. The calendar features a left sidebar panel for filters and upcoming events, timezone support with EST default, and integration with the existing event editing modal. Date range events are excluded from the calendar view to maintain clarity and focus on specific scheduled events.

## Architecture

### URL Structure
- `/calendar/` - Main calendar page (defaults to month view)
- `/calendar/month/` - Monthly calendar view
- `/calendar/week/` - Weekly calendar view  
- `/calendar/day/` - Daily calendar view
- `/calendar/month/2025/01/` - Specific month view
- `/calendar/week/2025/01/15/` - Specific week view
- `/calendar/day/2025/01/15/` - Specific day view

### Navigation Integration
The Calendar page will be added as a new navigation item in the main sidebar, positioned between "Schedule" and "Archive" to maintain logical flow.

### View Architecture
The calendar will use a single Django view class with multiple rendering modes:
- `CalendarView` - Main view class that handles all calendar display modes
- Template switching based on view type (month/week/day)
- AJAX endpoints for event data loading and quick actions

## Components and Interfaces

### Backend Components

#### Views
```python
class CalendarView(LoginRequiredMixin, TemplateView):
    """Main calendar view supporting multiple display modes with new event model"""
    
class CalendarEventAPIView(LoginRequiredMixin, View):
    """API endpoint for loading calendar event data with timezone support"""
    
class CalendarUpcomingEventsAPIView(LoginRequiredMixin, View):
    """API endpoint for loading upcoming events for sidebar"""
```

#### URL Patterns
```python
# New URLs to be added to event_management/urls.py
path('calendar/', CalendarView.as_view(), name='calendar'),
path('calendar/<str:view_type>/', CalendarView.as_view(), name='calendar_view'),
path('calendar/<str:view_type>/<int:year>/<int:month>/', CalendarView.as_view(), name='calendar_date'),
path('api/calendar/events/', CalendarEventAPIView.as_view(), name='calendar_events_api'),
path('api/calendar/quick-create/', QuickEventCreateView.as_view(), name='calendar_quick_create'),
```

### Frontend Components

#### Layout Components
- **Left Sidebar Panel**: Split into filters/options (top 1/3) and upcoming events (bottom 2/3)
- **Main Calendar Area**: Modern, sleek calendar display without shape outlines
- **Timezone Selector**: Dropdown with EST default for timezone selection

#### Calendar Grid Component
- **Monthly View**: 7x6 grid showing full month with modern styling
- **Weekly View**: 7-column layout with hourly time slots and timezone-aware display
- **Daily View**: Single column with detailed hourly breakdown and timezone support

#### Event Display Components
- **Event Block**: Modern styled blocks using new event model fields (title, start_date, start_time, etc.)
- **Event Tooltip**: Hover overlay with event details from new model structure
- **Event Editing Modal**: Reuses existing event editing modal from schedule page

#### Sidebar Components
- **Filter Panel**: Status, type, and other filtering controls in top section
- **Upcoming Events List**: Scrollable list of upcoming events in bottom section
- **Timezone Controls**: Timezone selector and related options

#### Navigation Components
- **View Toggle**: Modern buttons for Month/Week/Day switching
- **Date Navigation**: Clean Previous/Next buttons and date picker

## Data Models

### Updated Event Model Integration
The calendar will use the updated `Event` model with new field structure. Key fields used:
- `title` - Event name displayed on calendar
- `start_date` - Event start date for calendar positioning
- `start_time` - Event start time for scheduling
- `end_date` - Event end date for multi-day events
- `end_time` - Event end time
- `timezone` - Event timezone for proper display
- `is_date_range` - Boolean to exclude date range events from calendar
- `is_longer_than_day` - Boolean for multi-day event handling
- `status` - For color coding
- `type` - For filtering and categorization
- `description` - For tooltips and details
- `group` - Organization/group name for display

### Calendar-Specific Data Structures
```python
# Calendar context data structure with timezone support
calendar_data = {
    'view_type': 'month',  # month, week, day
    'current_date': date.today(),
    'selected_timezone': 'America/New_York',  # EST default
    'events': queryset.exclude(is_date_range=True),  # Exclude date range events
    'calendar_grid': [],  # Processed calendar layout with timezone conversion
    'navigation': {
        'prev_url': '/calendar/month/2024/12/',
        'next_url': '/calendar/month/2025/02/',
        'current_period': 'January 2025'
    },
    'filters': {
        'status': [],
        'event_type': [],
        'active_filters': {}
    },
    'upcoming_events': [],  # For sidebar display
    'timezone_choices': settings.TIMEZONE_CHOICES
}
```

## Security and Encryption Requirements

### Data Encryption
- **In Transit**: All calendar API calls use HTTPS/TLS encryption
- **At Rest**: Sensitive event data encrypted in database using Django's encryption utilities
- **Caching**: Calendar data cached with encryption and proper expiration policies
- **Session Data**: User timezone preferences and filter states encrypted in session storage

### Authentication and Authorization
- **API Security**: All calendar endpoints require authentication and proper user permissions
- **Data Classification**: Respect event data classification levels (internal, confidential, etc.)
- **Audit Logging**: Log all calendar access attempts and data modifications
- **Rate Limiting**: Implement API throttling to prevent abuse

### Congressional Security Compliance
- **Field-Level Encryption**: Encrypt sensitive fields like participant information, legislative topics
- **Access Controls**: Ensure users only see events they have permission to view
- **Data Retention**: Follow congressional data retention policies for calendar data
- **Security Headers**: Implement proper security headers for calendar pages

## Error Handling

### Client-Side Error Handling
- **Network Errors**: Graceful degradation when API calls fail with encrypted error messages
- **Invalid Dates**: Redirect to current date if invalid date parameters
- **Empty States**: Show appropriate messages when no events exist
- **Loading States**: Show spinners during data fetching with secure loading indicators

### Server-Side Error Handling
- **Invalid Date Parameters**: Return 404 or redirect to valid date with security logging
- **Permission Errors**: Ensure users only see their own events with audit trail
- **Database Errors**: Log errors securely and show user-friendly messages
- **API Rate Limiting**: Implement throttling for AJAX requests with security monitoring

## Testing Strategy

### Unit Tests
```python
# Test calendar view rendering
class CalendarViewTests(TestCase):
    def test_monthly_view_renders_correctly(self)
    def test_weekly_view_shows_proper_time_slots(self)
    def test_daily_view_displays_hourly_breakdown(self)
    def test_event_filtering_works(self)
    def test_date_navigation_functions(self)

# Test API endpoints
class CalendarAPITests(TestCase):
    def test_events_api_returns_correct_data(self)
    def test_quick_create_api_works(self)
    def test_api_respects_user_permissions(self)
```

### Integration Tests
```python
class CalendarIntegrationTests(TestCase):
    def test_calendar_navigation_integration(self)
    def test_event_creation_from_calendar(self)
    def test_calendar_filters_with_real_data(self)
    def test_responsive_behavior(self)
```

### Frontend Tests
- **JavaScript Unit Tests**: Test calendar rendering logic
- **UI Tests**: Test user interactions and responsive behavior
- **Accessibility Tests**: Ensure calendar is keyboard navigable
- **Cross-Browser Tests**: Verify compatibility across browsers

## Modern Design Requirements

### Visual Design Principles
- **No Shape Outlines**: All calendar elements use clean, borderless design
- **Sleek Modern Styling**: Flat design with subtle shadows and gradients
- **Consistent Color Scheme**: Uses existing HillDesk color palette
- **Clean Typography**: Modern font choices with proper hierarchy
- **Responsive Layout**: Adapts seamlessly to different screen sizes

### Layout Structure
```
┌─────────────────────────────────────────────────────────┐
│                    Header/Navigation                     │
├──────────────┬──────────────────────────────────────────┤
│   Sidebar    │                                          │
│   ┌────────┐ │                                          │
│   │Filters │ │            Calendar Grid                 │
│   │Options │ │                                          │
│   │Timezone│ │                                          │
│   └────────┘ │                                          │
│   ┌────────┐ │                                          │
│   │Upcoming│ │                                          │
│   │Events  │ │                                          │
│   │List    │ │                                          │
│   │        │ │                                          │
│   └────────┘ │                                          │
└──────────────┴──────────────────────────────────────────┘
```

## Implementation Details

### Calendar Rendering Logic
The calendar will use a combination of server-side date calculation and client-side rendering with timezone support:

1. **Server-side**: Calculate date ranges, fetch relevant events (excluding date ranges), organize by date with timezone conversion
2. **Client-side**: Render modern calendar grid, handle interactions, manage view switching, timezone updates

### Event Color Coding and Timezone Handling
```python
# Modern color scheme without harsh borders
STATUS_COLORS = {
    'received': '#ffc107',           # Amber
    'scheduled': '#28a745',          # Green
    'hold': '#6c757d',              # Gray
    'referred': '#17a2b8',          # Teal
    'fyied': '#fd7e14',             # Orange
    'scheduling_in_progress': '#20c997',  # Mint
    'rsvped': '#6f42c1',            # Purple
    'regrets_sent': '#dc3545',      # Red
    'passed': '#e83e8c',            # Pink
    'canceled': '#6c757d',          # Gray
}

# Timezone conversion utility
def convert_event_time_to_timezone(event, target_timezone):
    """Convert event start/end times to target timezone"""
    if event.start_date and event.start_time:
        # Combine date and time, convert timezone
        pass
```

### Responsive Design Strategy
- **Desktop (>1200px)**: Full calendar grid with all features
- **Tablet (768-1199px)**: Condensed calendar with collapsible sidebar
- **Mobile (<768px)**: Agenda-style list view with date picker

### Performance Considerations
- **Event Loading**: Load only events for visible date range
- **Lazy Loading**: Load additional months/weeks as user navigates
- **Caching**: Cache calendar data for frequently accessed periods
- **Pagination**: Limit number of events loaded per request

### Accessibility Features
- **Keyboard Navigation**: Arrow keys for date navigation
- **Screen Reader Support**: Proper ARIA labels and descriptions
- **High Contrast**: Support for high contrast mode
- **Focus Management**: Clear focus indicators and logical tab order

### Browser Compatibility
- **Modern Browsers**: Full feature support (Chrome, Firefox, Safari, Edge)
- **Older Browsers**: Graceful degradation with basic functionality
- **Mobile Browsers**: Touch-optimized interactions

This design provides a comprehensive calendar solution that integrates seamlessly with the existing HillDesk while offering users an intuitive way to visualize and manage their events.