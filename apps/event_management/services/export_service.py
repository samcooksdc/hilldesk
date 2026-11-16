# SPDX-License-Identifier: Apache-2.0
"""
Export service for generating .docx and CSV exports of event data.

Uses docxtpl to render Word templates with Jinja2 placeholders.
One code path handles both built-in and office-uploaded templates.
"""

import csv
import io
import logging
import os
from datetime import date, time, datetime, timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone

from docxtpl import DocxTemplate

logger = logging.getLogger('apps.event_management')


class ExportService:
    """
    Core service for rendering event data into .docx and CSV exports.

    Design rules:
    - _serialize_event inspects Event._meta.get_fields() dynamically
    - Date/time fields produce both raw and human-formatted variants
    - FK fields resolve to display strings, not UUIDs
    - Null/empty → "", never None
    """

    # Map of built-in template_type → filename in templates_docx/
    BUILT_IN_FILENAMES = {
        'daily_briefing': 'daily_briefing.docx',
        'weekly_overview': 'weekly_overview.docx',
        'event_detail': 'event_detail.docx',
        'filtered_list': 'filtered_list.docx',
    }

    # ------------------------------------------------------------------
    # Template Resolution
    # ------------------------------------------------------------------

    def resolve_template(
        self,
        template_type: str,
        office: Optional[Any] = None,
        template_id: Optional[str] = None,
    ) -> Any:
        """
        Resolve which ExportTemplate record to use.

        Priority:
        1. Specific template_id if provided
        2. Office-specific template for the given type
        3. Built-in default template for the given type
        """
        from apps.event_management.models import ExportTemplate

        if template_id:
            return ExportTemplate.objects.get(id=template_id)

        # Office-specific first
        if office:
            office_tpl = ExportTemplate.objects.filter(
                office=office,
                template_type=template_type,
            ).first()
            if office_tpl:
                return office_tpl

        # Fall back to built-in
        return ExportTemplate.objects.filter(
            is_default=True,
            template_type=template_type,
        ).first()

    def get_template_path(self, export_template: Any) -> str:
        """
        Get the filesystem path to the .docx file for a given ExportTemplate.

        For uploaded templates, uses the FileField path.
        For built-in defaults, resolves from the static templates_docx/ directory.
        """
        # Uploaded template
        if export_template.docx_file and export_template.docx_file.name:
            return export_template.docx_file.path

        # Built-in template
        filename = self.BUILT_IN_FILENAMES.get(export_template.template_type)
        if not filename:
            raise ValueError(
                f"No built-in template for type '{export_template.template_type}'"
            )

        templates_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'templates_docx',
        )
        path = os.path.join(templates_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Built-in template not found: {path}. "
                f"Run 'python manage.py generate_export_templates' first."
            )
        return path

    # ------------------------------------------------------------------
    # Event Serialization (Dynamic)
    # ------------------------------------------------------------------

    def _serialize_event(self, event: Any) -> Dict[str, Any]:
        """
        Serialize a single Event into a flat dict of template-friendly values.
        Inspects Event._meta.get_fields() dynamically.
        """
        from apps.event_management.models import Event

        data: Dict[str, Any] = {}

        for field in Event._meta.get_fields():
            # Skip reverse relations and many-to-many
            if field.is_relation and (field.one_to_many or field.many_to_many):
                continue

            name = field.name
            value = getattr(event, name, None)

            # FK fields → resolve to display string
            if field.is_relation and field.many_to_one:
                related_obj = value
                if related_obj is not None:
                    if hasattr(related_obj, 'get_full_name'):
                        data[name] = related_obj.get_full_name() or str(related_obj)
                    else:
                        data[name] = str(related_obj)
                else:
                    data[name] = ''
                continue

            # Date fields → raw + formatted variants
            if isinstance(value, date) and not isinstance(value, datetime):
                data[name] = str(value)
                data[f'{name}_formatted'] = value.strftime('%B %d, %Y')
                data[f'{name}_short'] = value.strftime('%m/%d/%Y')
                continue

            # Time fields → raw + formatted variants
            if isinstance(value, time):
                data[name] = str(value)
                data[f'{name}_formatted'] = value.strftime('%I:%M %p').lstrip('0')
                continue

            # Datetime fields → raw + formatted variants
            if isinstance(value, datetime):
                data[name] = value.isoformat()
                data[f'{name}_formatted'] = value.strftime('%B %d, %Y %I:%M %p')
                data[f'{name}_short'] = value.strftime('%m/%d/%Y %I:%M %p')
                continue

            # JSON list fields
            if isinstance(value, list):
                data[name] = value
                continue

            # JSON dict fields
            if isinstance(value, dict):
                data[name] = value
                continue

            # Everything else → string (never None)
            data[name] = str(value) if value is not None else ''

        # ---- Computed display fields ----

        # Time display: "9:00 AM - 10:30 AM" or "TBD"
        data['time_display'] = self._format_time_display(event)

        # Status display via office
        data['status_display'] = event.get_status_display_from_office()

        # Type display via office
        data['type_display'] = event.get_type_display_from_office()

        # Tags → comma-separated string
        data['tags_csv'] = self._format_tags(event.tags)

        # Staff → list of dicts + flat CSV
        data['staff_list'] = self._format_staff_list(event.staff)
        data['staff_csv'] = self._format_staff_csv(event.staff)

        # Short notes (first 200 chars)
        notes = event.notes or ''
        data['notes_short'] = (notes[:200] + '...') if len(notes) > 200 else notes

        return data

    def _resolve_source_email(self, event: Any) -> Dict[str, str]:
        """Get source email data for the event, or empty strings."""
        primary = event.get_primary_email()
        # Fall back to the reverse FK relationship (source_emails)
        if not primary:
            primary = event.source_emails.order_by('received').first()
        if not primary:
            return {
                'sender': '',
                'subject': '',
                'date': '',
                'body_snippet': '',
            }

        email_data = primary.complete_email_data or {}
        body = email_data.get('body', {})
        body_content = body.get('content', '') if isinstance(body, dict) else str(body)
        # Truncate body for snippet
        snippet = body_content[:500] + '...' if len(body_content) > 500 else body_content

        received = primary.received
        date_str = received.strftime('%B %d, %Y %I:%M %p') if received else ''

        return {
            'sender': primary.sender or primary.sender_name or '',
            'subject': primary.subject or '',
            'date': date_str,
            'body_snippet': snippet,
        }

    def _resolve_routing_trail(self, event: Any) -> List[Dict[str, str]]:
        """
        Build a routing trail from EventApproval records + change history.
        Returns a list of {who, action, when} dicts.
        """
        from apps.event_management.models import EventApproval

        trail: List[Dict[str, str]] = []

        # Approval records
        approvals = EventApproval.objects.filter(event=event).select_related('approver')
        for approval in approvals:
            name = approval.approver.get_full_name() or approval.approver.username
            action = approval.get_status_display()
            if approval.comment:
                action += f' — {approval.comment}'
            when = ''
            if approval.decided_at:
                when = approval.decided_at.strftime('%m/%d/%Y %I:%M %p')
            elif approval.status == 'pending':
                when = 'Pending'

            trail.append({'who': name, 'action': action, 'when': when})

        return trail

    # ------------------------------------------------------------------
    # Formatting Helpers
    # ------------------------------------------------------------------

    def _format_time_display(self, event: Any) -> str:
        """Format event time as "9:00 AM - 10:30 AM" or "TBD"."""
        if not event.start_time:
            return 'TBD'

        start = event.start_time.strftime('%I:%M %p').lstrip('0')
        if event.end_time:
            end = event.end_time.strftime('%I:%M %p').lstrip('0')
            return f'{start} - {end}'
        return start

    def _format_tags(self, tags: Any) -> str:
        """Format tags list as comma-separated string."""
        if not tags or not isinstance(tags, list):
            return ''
        return ', '.join(str(t) for t in tags)

    def _format_staff_list(self, staff: Any) -> List[Dict[str, str]]:
        """Format staff JSON into list of dicts with 'name' key."""
        if not staff or not isinstance(staff, list):
            return []
        result = []
        for s in staff:
            if isinstance(s, dict):
                result.append({'name': s.get('name', str(s))})
            else:
                result.append({'name': str(s)})
        return result

    def _format_staff_csv(self, staff: Any) -> str:
        """Format staff JSON into comma-separated name string."""
        staff_list = self._format_staff_list(staff)
        return ', '.join(s['name'] for s in staff_list)

    # ------------------------------------------------------------------
    # Context Builders (one per template type)
    # ------------------------------------------------------------------

    def _get_office_context(self, office: Optional[Any]) -> Dict[str, str]:
        """Common office fields for all contexts."""
        if office:
            return {
                'office_name': office.name or '',
                'member_name': getattr(office, 'member_name', '') or '',
            }
        return {'office_name': '', 'member_name': ''}

    def build_daily_briefing_context(
        self,
        events: Any,
        office: Optional[Any] = None,
        target_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Build context dict for the daily_briefing template."""
        if target_date is None:
            target_date = timezone.now().date()

        serialized = [self._serialize_event(e) for e in events]
        ctx = self._get_office_context(office)
        ctx.update({
            'date_formatted': target_date.strftime('%B %d, %Y'),
            'date_short': target_date.strftime('%m/%d/%Y'),
            'event_count': len(serialized),
            'events': serialized,
            'generated_at': timezone.now().strftime('%B %d, %Y %I:%M %p'),
        })
        return ctx

    def build_weekly_overview_context(
        self,
        events: Any,
        office: Optional[Any] = None,
        start_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Build context dict for the weekly_overview template."""
        if start_date is None:
            today = timezone.now().date()
            start_date = today - timedelta(days=today.weekday())  # Monday

        end_date = start_date + timedelta(days=6)

        # Group events by day
        from collections import OrderedDict
        days_map: Dict[date, list] = OrderedDict()
        for d in range(7):
            day = start_date + timedelta(days=d)
            days_map[day] = []

        for event in events:
            event_date = event.start_date
            if event_date and event_date in days_map:
                days_map[event_date].append(self._serialize_event(event))

        days = []
        for day_date, day_events in days_map.items():
            days.append({
                'label': day_date.strftime('%A, %B %d'),
                'date': day_date.strftime('%m/%d/%Y'),
                'event_count': len(day_events),
                'events': day_events,
            })

        all_events = [self._serialize_event(e) for e in events]
        ctx = self._get_office_context(office)
        ctx.update({
            'date_range': f'{start_date.strftime("%B %d")} - {end_date.strftime("%B %d, %Y")}',
            'event_count': len(all_events),
            'day_count': sum(1 for d in days if d['event_count'] > 0),
            'days': days,
            'events': all_events,
            'generated_at': timezone.now().strftime('%B %d, %Y %I:%M %p'),
        })
        return ctx

    def build_event_detail_context(
        self,
        event: Any,
        office: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Build context dict for the event_detail template."""
        serialized = self._serialize_event(event)

        ctx = self._get_office_context(office)
        ctx.update({
            'event': serialized,
            'source_email': self._resolve_source_email(event),
            'routing_trail': self._resolve_routing_trail(event),
            'generated_at': timezone.now().strftime('%B %d, %Y %I:%M %p'),
        })
        return ctx

    def build_filtered_list_context(
        self,
        events: Any,
        active_filters: Optional[List[str]] = None,
        office: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Build context dict for the filtered_list template."""
        serialized = [self._serialize_event(e) for e in events]
        filters_display = ', '.join(active_filters) if active_filters else 'None'

        ctx = self._get_office_context(office)
        ctx.update({
            'active_filters': active_filters or [],
            'active_filters_display': filters_display,
            'event_count': len(serialized),
            'events': serialized,
            'generated_at': timezone.now().strftime('%B %d, %Y %I:%M %p'),
        })
        return ctx

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_docx(
        self,
        template_type: str,
        queryset: Any,
        office: Optional[Any] = None,
        template_id: Optional[str] = None,
        target_date: Optional[date] = None,
        active_filters: Optional[List[str]] = None,
    ) -> bytes:
        """
        Render a .docx export and return the raw bytes.

        Args:
            template_type: One of daily_briefing, weekly_overview, event_detail, filtered_list
            queryset: QuerySet or list of Event objects (single Event for event_detail)
            office: Office instance for context
            template_id: Optional specific ExportTemplate UUID
            target_date: Target date for daily/weekly exports
            active_filters: Human-readable filter descriptions for filtered_list
        """
        export_template = self.resolve_template(template_type, office, template_id)
        if not export_template:
            raise ValueError(f"No template found for type '{template_type}'")

        template_path = self.get_template_path(export_template)
        doc = DocxTemplate(template_path)

        # Build the appropriate context
        if template_type == 'daily_briefing':
            context = self.build_daily_briefing_context(queryset, office, target_date)
        elif template_type == 'weekly_overview':
            context = self.build_weekly_overview_context(queryset, office, target_date)
        elif template_type == 'event_detail':
            # queryset should be a single event or iterable of one
            event = queryset if not hasattr(queryset, '__iter__') else list(queryset)[0]
            context = self.build_event_detail_context(event, office)
        elif template_type == 'filtered_list':
            context = self.build_filtered_list_context(queryset, active_filters, office)
        else:
            raise ValueError(f"Unknown template type: {template_type}")

        doc.render(context)

        # Write to in-memory buffer
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.read()

    def render_csv(
        self,
        queryset: Any,
        include_notes: bool = True,
        include_description: bool = True,
    ) -> str:
        """
        Render events as CSV text.

        Returns CSV as a string suitable for HttpResponse.
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        headers = [
            'Title', 'Type', 'Format', 'Status', 'Date', 'Start Time', 'End Time',
            'Location', 'Group', 'Staff', 'Tags', 'Point of Contact',
            'Contact Email', 'Contact Phone',
        ]
        if include_description:
            headers.append('Description')
        if include_notes:
            headers.append('Notes')

        writer.writerow(headers)

        for event in queryset:
            row = [
                event.title or '',
                event.get_type_display_from_office(),
                event.format or '',
                event.get_status_display_from_office(),
                event.start_date.strftime('%m/%d/%Y') if event.start_date else '',
                event.start_time.strftime('%I:%M %p').lstrip('0') if event.start_time else '',
                event.end_time.strftime('%I:%M %p').lstrip('0') if event.end_time else '',
                event.location or '',
                event.group or '',
                self._format_staff_csv(event.staff),
                self._format_tags(event.tags),
                event.point_of_contact_name or '',
                event.point_of_contact_email or '',
                event.point_of_contact_phone or '',
            ]
            if include_description:
                row.append(event.description or '')
            if include_notes:
                row.append(event.notes or '')

            writer.writerow(row)

        return output.getvalue()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_template(self, docx_file: Any) -> Dict[str, Any]:
        """
        Validate an uploaded .docx template by doing a dry render with sample data.

        Returns: {'valid': bool, 'errors': list[str]}
        """
        errors: List[str] = []

        try:
            # Save to temp buffer for DocxTemplate
            content = docx_file.read()
            docx_file.seek(0)

            buffer = io.BytesIO(content)
            doc = DocxTemplate(buffer)
        except Exception as e:
            return {'valid': False, 'errors': [f'Invalid .docx file: {e}']}

        # Attempt render with sample context
        try:
            sample_context = self._generate_sample_context()
            doc.render(sample_context)
        except Exception as e:
            error_msg = str(e)
            errors.append(f'Template rendering error: {error_msg}')

        return {'valid': len(errors) == 0, 'errors': errors}

    def _generate_sample_context(self) -> Dict[str, Any]:
        """Generate fake/sample data for template validation dry-run."""
        sample_event = {
            'title': 'Sample Meeting',
            'type': 'meeting',
            'type_display': 'Meeting',
            'format': 'In-Person',
            'duration': '1 hour',
            'start_date': '2026-03-01',
            'start_date_formatted': 'March 01, 2026',
            'start_date_short': '03/01/2026',
            'start_time': '10:00:00',
            'start_time_formatted': '10:00 AM',
            'end_time': '11:00:00',
            'end_time_formatted': '11:00 AM',
            'time_display': '10:00 AM - 11:00 AM',
            'location': '2251 Rayburn HOB',
            'group': 'Sample Organization',
            'description': 'A sample event for template validation.',
            'notes': 'Sample notes for this event.',
            'notes_short': 'Sample notes for this event.',
            'status': 'confirmed',
            'status_display': 'Confirmed',
            'tags': ['healthcare', 'appropriations'],
            'tags_csv': 'healthcare, appropriations',
            'staff_list': [{'name': 'Jane Doe'}, {'name': 'John Smith'}],
            'staff_csv': 'Jane Doe, John Smith',
            'point_of_contact_name': 'Alex Johnson',
            'point_of_contact_email': 'alex@example.com',
            'point_of_contact_phone': '(202) 555-0100',
            'created_by': 'scheduler@example.com',
            'modified_by': 'scheduler@example.com',
        }

        return {
            'office_name': 'Office of Rep. Sample',
            'member_name': 'Rep. Sample',
            'date_formatted': 'March 01, 2026',
            'date_short': '03/01/2026',
            'date_range': 'March 01 - March 07, 2026',
            'event_count': 1,
            'day_count': 1,
            'events': [sample_event],
            'event': sample_event,
            'days': [{
                'label': 'Monday, March 01',
                'date': '03/01/2026',
                'event_count': 1,
                'events': [sample_event],
            }],
            'active_filters': ['Status: Confirmed'],
            'active_filters_display': 'Status: Confirmed',
            'source_email': {
                'sender': 'sender@example.com',
                'subject': 'Meeting Request',
                'date': 'March 01, 2026 09:00 AM',
                'body_snippet': 'We would like to schedule a meeting...',
            },
            'routing_trail': [{
                'who': 'Jane Doe',
                'action': 'Approved',
                'when': '03/01/2026 10:00 AM',
            }],
            'generated_at': 'March 01, 2026 12:00 PM',
        }
