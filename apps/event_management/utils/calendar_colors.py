# SPDX-License-Identifier: Apache-2.0
"""
Calendar color utilities for event status and type display.
"""

class CalendarColorManager:
    """Manages color coding for calendar events based on status and type."""
    
    # Status color mapping based on requirements and existing implementation
    STATUS_COLORS = {
        'scheduled': {
            'background': '#d4edda',
            'color': '#155724',
            'border': '#28a745',
            'name': 'Scheduled',
            'description': 'Confirmed and scheduled events'
        },
        'hold': {
            'background': '#fff3cd',
            'color': '#856404',
            'border': '#ffc107',
            'name': 'Hold',
            'description': 'Events on hold pending decision'
        },
        'canceled': {
            'background': '#f8d7da',
            'color': '#721c24',
            'border': '#dc3545',
            'name': 'Canceled',
            'description': 'Canceled or withdrawn events',
            'strikethrough': True
        },
        'received': {
            'background': '#d1ecf1',
            'color': '#0c5460',
            'border': '#17a2b8',
            'name': 'Received',
            'description': 'Newly received requests'
        },
        'rsvped': {
            'background': '#d1ecf1',
            'color': '#0c5460',
            'border': '#17a2b8',
            'name': 'RSVP\'ed',
            'description': 'RSVP confirmed'
        },
        'passed': {
            'background': '#e2e3e5',
            'color': '#6c757d',
            'border': '#6c757d',
            'name': 'Passed',
            'description': 'Declined or passed events'
        },
        'referred': {
            'background': '#e7e3ff',
            'color': '#5a4fcf',
            'border': '#6f42c1',
            'name': 'Referred',
            'description': 'Referred to other parties'
        },
        'fyied': {
            'background': '#fff0e6',
            'color': '#cc5500',
            'border': '#fd7e14',
            'name': 'FYI\'ed',
            'description': 'For information only'
        },
        'scheduling_in_progress': {
            'background': '#e6f3ff',
            'color': '#0066cc',
            'border': '#007bff',
            'name': 'Scheduling in Progress',
            'description': 'Currently being scheduled'
        },
        'regrets_sent': {
            'background': '#ffe6e6',
            'color': '#cc0000',
            'border': '#dc3545',
            'name': 'Regrets Sent',
            'description': 'Regrets have been sent'
        },
        'requires_hms_review': {
            'background': '#fff5e6',
            'color': '#b8860b',
            'border': '#ffc107',
            'name': 'Requires HMS Review',
            'description': 'Pending HMS review'
        }
    }
    
    # Type color mapping (secondary color coding)
    TYPE_COLORS = {
        'event': {
            'accent': '#007bff',
            'name': 'Event',
            'icon': '📅'
        },
        'meeting': {
            'accent': '#28a745',
            'name': 'Meeting',
            'icon': '🤝'
        },
        'speaking': {
            'accent': '#dc3545',
            'name': 'Speaking',
            'icon': '🎤'
        }
    }
    
    @classmethod
    def get_status_color(cls, status):
        """Get color information for a given status."""
        return cls.STATUS_COLORS.get(status, cls.STATUS_COLORS['received'])
    
    @classmethod
    def get_type_color(cls, event_type):
        """Get color information for a given event type."""
        return cls.TYPE_COLORS.get(event_type, cls.TYPE_COLORS['event'])
    
    @classmethod
    def get_css_class(cls, status, event_type=None):
        """Get CSS class name for an event."""
        classes = [f'status-{status}']
        if event_type:
            classes.append(f'type-{event_type}')
        return ' '.join(classes)
    
    @classmethod
    def get_legend_data(cls):
        """Get legend data for display in calendar."""
        return {
            'statuses': [
                {
                    'key': key,
                    'name': info['name'],
                    'description': info['description'],
                    'color': info['background'],
                    'border': info['border'],
                    'strikethrough': info.get('strikethrough', False)
                }
                for key, info in cls.STATUS_COLORS.items()
            ],
            'types': [
                {
                    'key': key,
                    'name': info['name'],
                    'icon': info['icon'],
                    'accent': info['accent']
                }
                for key, info in cls.TYPE_COLORS.items()
            ]
        }
    
    @classmethod
    def generate_css(cls):
        """Generate CSS for all status and type combinations."""
        css_rules = []
        
        # Status-based CSS
        for status, colors in cls.STATUS_COLORS.items():
            rule = f"""
.event-item.status-{status} {{
    background: {colors['background']};
    color: {colors['color']};
    border-left-color: {colors['border']};
    {"text-decoration: line-through;" if colors.get('strikethrough') else ""}
}}"""
            css_rules.append(rule)
        
        # Type-based accent CSS
        for event_type, colors in cls.TYPE_COLORS.items():
            rule = f"""
.event-item.type-{event_type}::before {{
    content: "{colors['icon']}";
    margin-right: 4px;
    font-size: 0.8em;
}}"""
            css_rules.append(rule)
        
        return '\n'.join(css_rules)