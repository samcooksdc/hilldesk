# SPDX-License-Identifier: Apache-2.0
"""
Server-rendered event pages (detail, create, edit, delete).

Every view applies the same permission rules as the events API:
visibility via ``Permissions.scope_events_queryset`` (role scope), edits via
``Permissions.can_edit_event``, status changes via ``can_change_status``,
creation via ``create_events`` and deletion via ``archive_delete_events``.
Deleting is a soft delete (archive), like the rest of the app.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView

from apps.authentication.permissions import Permissions

from ..forms import EventForm
from ..models import Event, EventChangeHistory


def visible_events(user):
    """Active events ``user`` may see (same scope as the events API)."""
    return Permissions.scope_events_queryset(user, Event.get_active_events())


class _ScopedEventMixin(LoginRequiredMixin):
    model = Event

    def get_queryset(self):
        return visible_events(self.request.user)


class EventDetailView(_ScopedEventMixin, DetailView):
    """Detail view for events."""
    template_name = 'event_management/event_detail.html'
    context_object_name = 'event'


class EventCreateView(LoginRequiredMixin, CreateView):
    """Create view for events."""
    model = Event
    form_class = EventForm
    template_name = 'event_management/event_form.html'
    success_url = reverse_lazy('event_management:events')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not Permissions.has_permission(
            request.user, Permissions.CREATE_EVENTS
        ):
            raise PermissionDenied('You do not have permission to create events.')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = 'Create New Event'
        context['submit_text'] = 'Create Event'
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.modified_by = self.request.user
        response = super().form_valid(form)
        EventChangeHistory.objects.create(
            event=self.object,
            user=self.request.user,
            field='created',
            old_value='',
            new_value='Event created',
            ip_address=self.request.META.get('REMOTE_ADDR'),
        )
        messages.success(self.request, f'Event "{self.object}" created successfully.')
        return response


class EventUpdateView(_ScopedEventMixin, UpdateView):
    """Update view for events."""
    form_class = EventForm
    template_name = 'event_management/event_form.html'

    def get_object(self, queryset=None):
        event = super().get_object(queryset)
        if not Permissions.can_edit_event(self.request.user, event):
            raise PermissionDenied('You do not have permission to edit this event.')
        return event

    def get_success_url(self):
        return reverse_lazy('event_management:event_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = f'Edit Event: {self.object}'
        context['submit_text'] = 'Update Event'
        return context

    def form_valid(self, form):
        if 'status' in form.changed_data and not Permissions.can_change_status(self.request.user):
            raise PermissionDenied('You do not have permission to change event status.')
        for field in form.changed_data:
            EventChangeHistory.objects.create(
                event=self.object,
                user=self.request.user,
                field=field,
                old_value=str(form.initial.get(field, '')),
                new_value=str(form.cleaned_data.get(field, '')),
                ip_address=self.request.META.get('REMOTE_ADDR'),
            )
        form.instance.modified_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f'Event "{self.object}" updated successfully.')
        return response


class EventDeleteView(_ScopedEventMixin, DeleteView):
    """Soft-delete (archive) an event; it moves to Settings -> Deleted events."""
    template_name = 'event_management/event_confirm_delete.html'
    success_url = reverse_lazy('event_management:events')

    def get_object(self, queryset=None):
        event = super().get_object(queryset)
        if not Permissions.has_permission(self.request.user, Permissions.ARCHIVE_DELETE_EVENTS):
            raise PermissionDenied('You do not have permission to delete events.')
        return event

    def form_valid(self, form):
        self.object.archive(user=self.request.user)
        messages.success(self.request, f'Event "{self.object}" moved to Deleted events.')
        return HttpResponseRedirect(self.get_success_url())
