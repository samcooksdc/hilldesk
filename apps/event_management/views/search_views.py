# SPDX-License-Identifier: Apache-2.0
"""Search and filtering views for event management."""

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.views.decorators.http import require_GET
from django.core.paginator import Paginator

from apps.authentication.permissions import Permissions

from ..models import Event


def _visible_events(request):
    """Active events this user may see: the same role scope as the events API.

    HillDesk is one deployment per office; within it, roles decide whether a
    user sees every event or only those assigned to / routed through them.
    """
    queryset = Event.objects.select_related('created_by', 'modified_by').filter(is_archived=False)
    return Permissions.scope_events_queryset(request.user, queryset)


def _text_search_q(text):
    """Free-text match over plain (unencrypted) event fields.

    Organization and contact names are encrypted and can't be substring-searched.
    """
    return (
        Q(title__icontains=text) |
        Q(location__icontains=text) |
        Q(description__icontains=text) |
        Q(notes__icontains=text) |
        Q(time_notes__icontains=text) |
        Q(legislative_topics__icontains=text) |
        Q(participants__icontains=text)
    )


@login_required
@require_GET
def search_suggestions(request):
    """
    Provide search suggestions for autocomplete functionality.
    """
    query = request.GET.get('q', '').strip()
    field = request.GET.get('field', 'all')
    
    if len(query) < 2:
        return JsonResponse({'suggestions': []})
    
    suggestions = set()

    # NOTE: group (organization) and contact-name suggestions are no longer
    # available here — that data is normalized into the encrypted
    # Contact/Organization models, which cannot be substring-queried in SQL.

    if field == 'all' or field == 'location':
        # Get location suggestions
        locations = _visible_events(request).filter(
            location__icontains=query
        ).values_list('location', flat=True).distinct()[:10]
        suggestions.update(filter(None, locations))

    if field == 'all' or field == 'topic':
        # Get legislative topic suggestions
        events_with_topics = _visible_events(request).exclude(
            legislative_topics__isnull=True
        ).exclude(legislative_topics__exact=[])
        
        matching_topics = set()
        for event in events_with_topics:
            if event.legislative_topics:
                for topic in event.legislative_topics:
                    if query.lower() in topic.lower():
                        matching_topics.add(topic)
                        if len(matching_topics) >= 10:
                            break
        suggestions.update(matching_topics)
    
    # Convert to sorted list
    suggestions_list = sorted(list(suggestions))[:10]
    
    return JsonResponse({
        'suggestions': suggestions_list,
        'query': query
    })


@login_required
@require_GET
def filter_stats(request):
    """
    Get statistics for current filter parameters.
    """
    queryset = _visible_events(request)

    search_query = request.GET.get('search')
    if search_query:
        queryset = queryset.filter(_text_search_q(search_query))
    
    status_filter = request.GET.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    
    type_filter = request.GET.get('type')
    if type_filter:
        queryset = queryset.filter(type=type_filter)
    
    # Add other filters as needed...
    
    # Calculate statistics
    total_filtered = queryset.count()
    status_breakdown = {}
    type_breakdown = {}
    
    # Statuses and types are configured per office, so count the values present.
    for row in queryset.values('status').annotate(n=Count('id')).order_by():
        status_breakdown[row['status']] = row['n']
    for row in queryset.values('type').annotate(n=Count('id')).order_by():
        type_breakdown[row['type']] = row['n']
    
    return JsonResponse({
        'total_filtered': total_filtered,
        'status_breakdown': status_breakdown,
        'type_breakdown': type_breakdown
    })


@login_required
@require_GET
def export_filtered_events(request):
    """
    Export filtered events to CSV.
    """
    from django.http import HttpResponse
    import csv
    from datetime import datetime
    
    queryset = _visible_events(request)

    search_query = request.GET.get('search')
    if search_query:
        queryset = queryset.filter(_text_search_q(search_query))
    
    # Apply other filters
    filters = {
        'status': request.GET.get('status'),
        'type': request.GET.get('type'),
        'data_classification': request.GET.get('classification')
    }
    
    for field, value in filters.items():
        if value:
            queryset = queryset.filter(**{field: value})
    
    # Date filters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date:
        try:
            start_date = datetime.fromisoformat(start_date)
            queryset = queryset.filter(start_date__gte=start_date)
        except ValueError:
            pass
    
    if end_date:
        try:
            end_date = datetime.fromisoformat(end_date)
            queryset = queryset.filter(start_date__lte=end_date)
        except ValueError:
            pass
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="events_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    
    # Write header
    writer.writerow([
        'ID', 'Group', 'Type', 'Status', 'Start Date', 'End Date', 'Time',
        'Location', 'Details', 'Point of Contact', 'Contact Email', 'Contact Phone',
        'Legislative Topics', 'Participants',
        'Data Classification', 'Created', 'Created By',
        'Modified', 'Modified By'
    ])
    
    # Write data
    for event in queryset:
        writer.writerow([
            str(event.id),
            event.group,
            event.get_type_display_from_office(),
            event.get_status_display_from_office(),
            event.start_date.strftime('%Y-%m-%d %H:%M') if event.start_date else '',
            event.end_date.strftime('%Y-%m-%d %H:%M') if event.end_date else '',
            event.time_display,
            event.location or '',
            event.description or '',
            event.point_of_contact_name or '',
            event.point_of_contact_email or '',
            event.point_of_contact_phone or '',
            ', '.join(event.legislative_topics) if event.legislative_topics else '',
            ', '.join(event.participants) if event.participants else '',
            event.get_data_classification_display(),
            event.created.strftime('%Y-%m-%d %H:%M'),
            event.created_by.get_full_name() or event.created_by.username,
            event.modified.strftime('%Y-%m-%d %H:%M'),
            event.modified_by.get_full_name() or event.modified_by.username,
        ])
    
    return response


@login_required
@require_GET
def advanced_search(request):
    """
    Advanced search with faceted filtering.
    """
    query = request.GET.get('q', '').strip()
    page = request.GET.get('page', 1)
    
    queryset = _visible_events(request)
    
    # Apply search if provided
    if query:
        queryset = queryset.filter(_text_search_q(query))
    
    # Apply filters
    filters = {
        'status': request.GET.get('status'),
        'type': request.GET.get('type'),
        'data_classification': request.GET.get('classification')
    }
    
    for field, value in filters.items():
        if value:
            queryset = queryset.filter(**{field: value})
    
    # Pagination
    paginator = Paginator(queryset, 25)
    events_page = paginator.get_page(page)
    
    # Prepare response data
    events_data = []
    for event in events_page:
        events_data.append({
            'id': str(event.id),
            'group': event.group,
            'type': event.get_type_display_from_office(),
            'status': event.get_status_display_from_office(),
            'start_date': event.start_date.isoformat(),
            'location': event.location or '',
            'contact': event.point_of_contact_name,
            'url': f'/events/{event.pk}/'
        })
    
    return JsonResponse({
        'events': events_data,
        'pagination': {
            'current_page': events_page.number,
            'total_pages': paginator.num_pages,
            'total_count': paginator.count,
            'has_next': events_page.has_next(),
            'has_previous': events_page.has_previous()
        },
        'query': query,
        'filters': filters
    })