# SPDX-License-Identifier: Apache-2.0
"""
Forms for Event Management in HillDesk.
"""
from django import forms
from django.conf import settings
from django.utils import timezone
from .models import Event, EmailTemplate


class EventForm(forms.ModelForm):
    """Form for creating and updating events."""
    
    class Meta:
        model = Event
        # NOTE: `group` and `point_of_contact_*` are no longer model fields; they
        # are normalized into Contact/Organization and managed via the contacts
        # API, so they are intentionally absent here.
        fields = [
            'title', 'type', 'format', 'duration', 'start_date', 'start_time',
            'end_date', 'end_time', 'timezone', 'time_notes', 'is_date_range',
            'is_longer_than_day', 'location', 'description', 'tags',
            'legislative_topics', 'participants', 'expected_attendees',
            'staff', 'approval_routing', 'reminder_enabled', 'reminder_time',
            'notes', 'status', 'data_classification'
        ]
        
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Event title'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'timezone': forms.Select(attrs={'class': 'form-select'}),
            'time_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Notes for date range events'}),
            'is_date_range': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_longer_than_day': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'format': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'in-person, virtual, or hybrid'}),
            'duration': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 1hr, 2hr, half-day'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Capitol Building Room 123'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Event description'}),
            'expected_attendees': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'reminder_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'reminder_time': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 15min, 1hr, 1day'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'All notes including schedule, campaign, staff, and general notes'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'data_classification': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set required fields
        self.fields['title'].required = True
        self.fields['type'].required = True
        self.fields['start_date'].required = True
        self.fields['start_time'].required = True
        self.fields['description'].required = True

        # Add help text
        self.fields['tags'].help_text = "Enter tags as JSON array, e.g., [\"Healthcare\", \"Coalition\"]"
        self.fields['legislative_topics'].help_text = "Enter topics as JSON array, e.g., [\"Healthcare\", \"Education\"]"
        self.fields['participants'].help_text = "Enter participants as JSON array, e.g., [\"John Doe\", \"Jane Smith\"]"
        self.fields['staff'].help_text = "Enter staff as JSON array, e.g., [\"Staff Member 1\", \"Staff Member 2\"]"
        self.fields['approval_routing'].help_text = "Enter approval routing as JSON object (advanced users only)"
    
    def clean_start_date(self):
        """Validate start date is not in the past."""
        start_date = self.cleaned_data.get('start_date')
        if start_date and start_date < timezone.now().date():
            raise forms.ValidationError("Start date cannot be in the past.")
        return start_date
    
    def clean(self):
        """Validate the entire form."""
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        start_time = cleaned_data.get('start_time')
        end_date = cleaned_data.get('end_date')
        end_time = cleaned_data.get('end_time')
        
        # Validate end date/time is after start date/time
        if end_date and end_time and start_date and start_time:
            from datetime import datetime
            start_datetime = datetime.combine(start_date, start_time)
            end_datetime = datetime.combine(end_date, end_time)
            if end_datetime <= start_datetime:
                raise forms.ValidationError("End date/time must be after start date/time.")
        elif end_date and start_date and end_date < start_date:
            raise forms.ValidationError("End date must be after start date.")
        
        return cleaned_data
    
    def clean_legislative_topics(self):
        """Validate legislative topics JSON."""
        topics = self.cleaned_data.get('legislative_topics')
        if topics and not isinstance(topics, list):
            try:
                import json
                topics = json.loads(topics) if isinstance(topics, str) else topics
                if not isinstance(topics, list):
                    raise forms.ValidationError("Legislative topics must be a list.")
            except (json.JSONDecodeError, TypeError):
                raise forms.ValidationError("Invalid JSON format for legislative topics.")
        return topics or []
    
    def clean_participants(self):
        """Validate participants JSON."""
        participants = self.cleaned_data.get('participants')
        if participants and not isinstance(participants, list):
            try:
                import json
                participants = json.loads(participants) if isinstance(participants, str) else participants
                if not isinstance(participants, list):
                    raise forms.ValidationError("Participants must be a list.")
            except (json.JSONDecodeError, TypeError):
                raise forms.ValidationError("Invalid JSON format for participants.")
        return participants or []
    
    def clean_staff(self):
        """Validate staff JSON."""
        staff = self.cleaned_data.get('staff')
        if staff and not isinstance(staff, list):
            try:
                import json
                staff = json.loads(staff) if isinstance(staff, str) else staff
                if not isinstance(staff, list):
                    raise forms.ValidationError("Staff must be a list.")
            except (json.JSONDecodeError, TypeError):
                raise forms.ValidationError("Invalid JSON format for staff.")
        return staff or []
    
    def clean_tags(self):
        """Validate tags JSON."""
        tags = self.cleaned_data.get('tags')
        if tags and not isinstance(tags, list):
            try:
                import json
                tags = json.loads(tags) if isinstance(tags, str) else tags
                if not isinstance(tags, list):
                    raise forms.ValidationError("Tags must be a list.")
            except (json.JSONDecodeError, TypeError):
                raise forms.ValidationError("Invalid JSON format for tags.")
        return tags or []
    
    def clean_approval_routing(self):
        """Validate approval routing JSON."""
        approval_routing = self.cleaned_data.get('approval_routing')
        if approval_routing and not isinstance(approval_routing, dict):
            try:
                import json
                approval_routing = json.loads(approval_routing) if isinstance(approval_routing, str) else approval_routing
                if not isinstance(approval_routing, dict):
                    raise forms.ValidationError("Approval routing must be a dictionary.")
            except (json.JSONDecodeError, TypeError):
                raise forms.ValidationError("Invalid JSON format for approval routing.")
        return approval_routing or {}


class EmailTemplateForm(forms.ModelForm):
    """Form for creating and updating email templates."""
    
    class Meta:
        model = EmailTemplate
        fields = ['name', 'subject', 'body', 'variables', 'is_default']
        
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'subject': forms.TextInput(attrs={'class': 'form-control'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 10}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set required fields
        self.fields['name'].required = True
        self.fields['subject'].required = True
        self.fields['body'].required = True
        
        # Add help text
        self.fields['variables'].help_text = "Enter variables as JSON array, e.g., [\"event_name\", \"contact_name\"]"
        self.fields['body'].help_text = "Use {{variable_name}} for template variables"
    
    def clean_variables(self):
        """Validate variables JSON."""
        variables = self.cleaned_data.get('variables')
        if variables and not isinstance(variables, list):
            try:
                import json
                variables = json.loads(variables) if isinstance(variables, str) else variables
                if not isinstance(variables, list):
                    raise forms.ValidationError("Variables must be a list.")
            except (json.JSONDecodeError, TypeError):
                raise forms.ValidationError("Invalid JSON format for variables.")
        return variables or []


class EventSearchForm(forms.Form):
    """Form for searching and filtering events."""
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search events...'
        })
    )
    
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All Statuses')] + settings.EVENT_STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    type = forms.ChoiceField(
        required=False,
        choices=[('', 'All Types')] + settings.EVENT_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    format = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Event format...'
        })
    )
    
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    
    sort_by = forms.ChoiceField(
        required=False,
        choices=[
            ('start_date', 'Date (Ascending)'),
            ('-start_date', 'Date (Descending)'),
            ('title', 'Title (A-Z)'),
            ('-title', 'Title (Z-A)'),
            ('status', 'Status (A-Z)'),
            ('-status', 'Status (Z-A)'),
            ('created', 'Created (Oldest)'),
            ('-created', 'Created (Newest)'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )