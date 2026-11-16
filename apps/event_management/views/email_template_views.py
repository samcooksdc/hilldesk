# SPDX-License-Identifier: Apache-2.0
"""
Views for managing email templates.
"""

import logging
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.http import JsonResponse

from apps.event_management.models import EmailTemplate
from apps.email_processing.email_response_service import EmailResponseService
from apps.email_processing.models import EmailProcessing

logger = logging.getLogger('apps.event_management')


class EmailTemplateListView(LoginRequiredMixin, ListView):
    """View for listing email templates."""
    model = EmailTemplate
    template_name = 'event_management/email_templates/list.html'
    context_object_name = 'templates'
    paginate_by = 10
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by category if provided
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category=category)
        
        # Filter by active status if provided
        active = self.request.GET.get('active')
        if active is not None:
            is_active = active.lower() == 'true'
            queryset = queryset.filter(is_active=is_active)
        
        return queryset.order_by('category', 'name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = EmailTemplate.objects.values_list('category', flat=True).distinct()
        return context


class EmailTemplateDetailView(LoginRequiredMixin, DetailView):
    """View for viewing email template details."""
    model = EmailTemplate
    template_name = 'event_management/email_templates/detail.html'
    context_object_name = 'template'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add sample context data for preview
        context['preview_context'] = {
            'sender_name': 'John Doe',
            'recipient_name': 'Representative Smith',
            'office_name': 'Office of Representative Smith',
            'date': 'January 1, 2023',
            'original_subject': 'Meeting Request',
            'event_type': 'meeting',
            'event_date': 'January 15, 2023',
            'event_time': '2:00 PM - 3:00 PM',
            'event_location': '2411 RHOB',
            'event_details': 'Discussion about healthcare policy',
            'event_status': 'Scheduled',
        }
        
        # Render preview
        template = self.get_object()
        service = EmailResponseService()
        try:
            rendered = service.render_template(template, context['preview_context'])
            context['preview_subject'] = rendered['subject']
            context['preview_body'] = rendered['body']
        except Exception as e:
            logger.error(f"Error rendering template preview: {e}")
            context['preview_error'] = str(e)
        
        return context


class EmailTemplateCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """View for creating a new email template."""
    model = EmailTemplate
    template_name = 'event_management/email_templates/form.html'
    fields = ['name', 'category', 'subject', 'body', 'is_html', 'is_default', 'is_active']
    permission_required = 'event_management.add_emailtemplate'
    
    def get_success_url(self):
        return reverse_lazy('event_management:email_template_detail', kwargs={'pk': self.object.pk})
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.modified_by = self.request.user
        messages.success(self.request, f"Template '{form.instance.name}' created successfully.")
        return super().form_valid(form)


class EmailTemplateUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """View for updating an email template."""
    model = EmailTemplate
    template_name = 'event_management/email_templates/form.html'
    fields = ['name', 'category', 'subject', 'body', 'is_html', 'is_default', 'is_active']
    permission_required = 'event_management.change_emailtemplate'
    
    def get_success_url(self):
        return reverse_lazy('event_management:email_template_detail', kwargs={'pk': self.object.pk})
    
    def form_valid(self, form):
        form.instance.modified_by = self.request.user
        messages.success(self.request, f"Template '{form.instance.name}' updated successfully.")
        return super().form_valid(form)


class EmailTemplateDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """View for deleting an email template."""
    model = EmailTemplate
    template_name = 'event_management/email_templates/confirm_delete.html'
    success_url = reverse_lazy('event_management:email_template_list')
    permission_required = 'event_management.delete_emailtemplate'
    
    def delete(self, request, *args, **kwargs):
        template = self.get_object()
        messages.success(request, f"Template '{template.name}' deleted successfully.")
        return super().delete(request, *args, **kwargs)


def preview_template(request, pk):
    """AJAX view for previewing a template with custom context."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    template = get_object_or_404(EmailTemplate, pk=pk)
    
    # Get context data from request
    context_data = {}
    for key, value in request.POST.items():
        if key != 'csrfmiddlewaretoken':
            context_data[key] = value
    
    # Render template
    service = EmailResponseService()
    try:
        rendered = service.render_template(template, context_data)
        return JsonResponse({
            'subject': rendered['subject'],
            'body': rendered['body'],
            'is_html': rendered['is_html']
        })
    except Exception as e:
        logger.error(f"Error rendering template preview: {e}")
        return JsonResponse({'error': str(e)}, status=400)


def send_email_response(request, email_id):
    """View for sending an email response using a template."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    # Get email processing record
    email_processing = get_object_or_404(EmailProcessing, pk=email_id)
    
    # Get template
    template_id = request.POST.get('template_id')
    if not template_id:
        return JsonResponse({'error': 'Template ID is required'}, status=400)
    
    template = get_object_or_404(EmailTemplate, pk=template_id)
    
    # Get context data from request
    context_data = {}
    for key, value in request.POST.items():
        if key not in ['csrfmiddlewaretoken', 'template_id']:
            context_data[key] = value
    
    # Send response
    service = EmailResponseService(request.user.email)
    try:
        response = service.send_templated_response(
            email_processing=email_processing,
            template=template,
            context_data=context_data
        )
        
        return JsonResponse({
            'success': True,
            'response_id': str(response.id),
            'status': response.status
        })
    except Exception as e:
        logger.error(f"Error sending email response: {e}")
        return JsonResponse({'error': str(e)}, status=500)