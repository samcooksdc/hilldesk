# SPDX-License-Identifier: Apache-2.0
"""
Email Integration Service for connecting email processing with event email attachments.
"""

from typing import Dict, Any
from django.contrib.auth import get_user_model
from django.utils import timezone

from ..models import EmailProcessing, EmailResponse
from apps.event_management.models import Event

User = get_user_model()


class EmailIntegrationService:
    """Service for integrating email processing with event email attachments."""
    
    @staticmethod
    def attach_processed_email_to_event(email_processing: EmailProcessing, event: Event, user: User) -> bool:
        """
        Attach a processed email to an event using the streamlined approach.
        
        Args:
            email_processing: EmailProcessing instance
            event: Event to attach email to
            user: User performing the attachment
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Attach the EmailProcessing record to the event
            success = event.attach_email(email_processing.id)
            
            if success:
                # Update the EmailProcessing record to link to the event
                email_processing.event = event
                email_processing.status = 'verified'
                email_processing.processed_by = user
                
                # Update processing metadata in complete_email_data
                if email_processing.complete_email_data:
                    processing_metadata = email_processing.complete_email_data.get('processing_metadata', {})
                    processing_metadata.update({
                        'attached_to_event': timezone.now().isoformat(),
                        'attached_by_user_id': str(user.id),
                        'event_id': str(event.id)
                    })
                    email_processing.complete_email_data['processing_metadata'] = processing_metadata
                
                email_processing.save()
                event.save()
            
            return success
        except Exception as e:
            print(f"Error attaching processed email to event: {e}")
            return False
    
    @staticmethod
    def attach_response_email_to_event(email_response: EmailResponse, event: Event, user: User) -> bool:
        """
        Attach a sent response email to an event by creating an EmailProcessing record.
        
        Args:
            email_response: EmailResponse instance
            event: Event to attach response to
            user: User performing the attachment
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create an EmailProcessing record for the response
            email_processing = EmailProcessing.objects.create(
                email_id=f"response_{email_response.id}",
                subject=email_response.subject,
                sender=email_response.sender,
                sender_name=f"{user.first_name} {user.last_name}".strip() or user.username,
                received=email_response.sent_at or email_response.created,
                is_scheduling_request=False,
                confidence=1.0,
                status='verified',
                event=event,
                processed_by=user,
                complete_email_data=EmailIntegrationService._create_email_data_from_response(email_response, user),
                extracted_data={'response_type': 'manual_response'}
            )
            
            # Attach to event
            success = event.attach_email(email_processing.id)
            if success:
                event.save()
            
            return success
        except Exception as e:
            print(f"Error attaching response email to event: {e}")
            return False
    
    @staticmethod
    def _create_email_data_from_processing(email_processing: EmailProcessing, email_type: str) -> Dict[str, Any]:
        """
        Create standardized email data from an EmailProcessing record.
        
        Args:
            email_processing: EmailProcessing instance
            email_type: Type of email
            
        Returns:
            Standardized email data dictionary
        """
        # Create sender info
        from_data = {
            'name': email_processing.sender_name or '',
            'email': email_processing.sender,
            'display_name': f"{email_processing.sender_name} <{email_processing.sender}>" if email_processing.sender_name else email_processing.sender
        }
        
        # Extract recipient info from extracted_data if available
        to_recipients = []
        extracted_data = email_processing.extracted_data or {}
        if 'recipients' in extracted_data:
            for recipient in extracted_data['recipients']:
                if isinstance(recipient, dict):
                    to_recipients.append(recipient)
                else:
                    to_recipients.append({
                        'name': '',
                        'email': str(recipient),
                        'display_name': str(recipient)
                    })
        
        # Create email body from extracted data or raw content
        body_content = extracted_data.get('body', '') or email_processing.raw_content or ''
        body = {
            'text': body_content,
            'html': body_content if '<' in body_content and '>' in body_content else '',
            'preview': body_content[:200]
        }
        
        email_data = {
            'email_id': email_processing.email_id,
            'email_type': email_type,
            'source': 'outlook',
            'thread_id': extracted_data.get('conversation_id', ''),
            'message_id': extracted_data.get('message_id', ''),
            'in_reply_to': extracted_data.get('in_reply_to', ''),
            'references': extracted_data.get('references', []),
            'subject': email_processing.subject,
            'from': from_data,
            'to': to_recipients,
            'cc': extracted_data.get('cc_recipients', []),
            'bcc': extracted_data.get('bcc_recipients', []),
            'date_sent': email_processing.received.isoformat(),
            'date_received': email_processing.received.isoformat(),
            'body': body,
            'attachments': extracted_data.get('attachments', []),
            'headers': {
                'importance': extracted_data.get('importance', 'normal'),
                'priority': extracted_data.get('priority', 'normal'),
                'sensitivity': extracted_data.get('sensitivity', 'normal'),
                'delivery_receipt_requested': False,
                'read_receipt_requested': False
            },
            'outlook_metadata': {
                'conversation_id': extracted_data.get('conversation_id', ''),
                'internet_message_id': extracted_data.get('message_id', ''),
                'web_link': extracted_data.get('web_link', ''),
                'categories': extracted_data.get('categories', []),
                'flag_status': 'notFlagged',
                'is_read': True,
                'has_attachments': len(extracted_data.get('attachments', [])) > 0
            },
            'processing_metadata': {
                'added_to_event': timezone.now().isoformat(),
                'added_by_user_id': str(email_processing.processed_by.id) if email_processing.processed_by else None,
                'relationship_type': email_type,
                'confidence_score': email_processing.confidence,
                'extraction_source': 'ai_processing',
                'is_primary_email': email_type == 'original_request'
            },
            'content_analysis': {
                'language': 'en',
                'sentiment': 'neutral',
                'key_phrases': extracted_data.get('key_phrases', []),
                'entities': extracted_data.get('entities', []),
                'topics': extracted_data.get('topics', [])
            }
        }
        
        return email_data
    
    @staticmethod
    def _create_email_data_from_response(email_response: EmailResponse, user: User) -> Dict[str, Any]:
        """
        Create standardized email data from an EmailResponse record.
        
        Args:
            email_response: EmailResponse instance
            user: User who sent the response
            
        Returns:
            Standardized email data dictionary
        """
        # Create sender info
        from_data = {
            'name': f"{user.first_name} {user.last_name}".strip() or user.username,
            'email': email_response.sender,
            'display_name': f"{user.first_name} {user.last_name} <{email_response.sender}>".strip()
        }
        
        # Create recipient info
        to_recipients = [{
            'name': '',
            'email': email_response.recipient,
            'display_name': email_response.recipient
        }]
        
        # Create CC recipients
        cc_recipients = []
        for cc_email in email_response.cc_recipients:
            cc_recipients.append({
                'name': '',
                'email': cc_email,
                'display_name': cc_email
            })
        
        # Create BCC recipients
        bcc_recipients = []
        for bcc_email in email_response.bcc_recipients:
            bcc_recipients.append({
                'name': '',
                'email': bcc_email,
                'display_name': bcc_email
            })
        
        # Create body
        body = {
            'text': email_response.body if not email_response.is_html else '',
            'html': email_response.body if email_response.is_html else '',
            'preview': email_response.body[:200]
        }
        
        email_data = {
            'email_id': str(email_response.id),
            'email_type': 'response_sent',
            'source': 'manual',
            'thread_id': email_response.original_email.extracted_data.get('conversation_id', ''),
            'message_id': email_response.outlook_message_id or f"<{email_response.id}@congressional-scheduling>",
            'in_reply_to': email_response.original_email.extracted_data.get('message_id', ''),
            'references': [email_response.original_email.extracted_data.get('message_id', '')],
            'subject': email_response.subject,
            'from': from_data,
            'to': to_recipients,
            'cc': cc_recipients,
            'bcc': bcc_recipients,
            'date_sent': email_response.sent_at.isoformat() if email_response.sent_at else email_response.created.isoformat(),
            'date_received': email_response.sent_at.isoformat() if email_response.sent_at else email_response.created.isoformat(),
            'body': body,
            'attachments': [],
            'headers': {
                'importance': 'normal',
                'priority': 'normal',
                'sensitivity': 'normal',
                'delivery_receipt_requested': False,
                'read_receipt_requested': False
            },
            'outlook_metadata': {
                'conversation_id': email_response.original_email.extracted_data.get('conversation_id', ''),
                'internet_message_id': email_response.outlook_message_id or '',
                'web_link': '',
                'categories': [],
                'flag_status': 'notFlagged',
                'is_read': True,
                'has_attachments': False
            },
            'processing_metadata': {
                'added_to_event': timezone.now().isoformat(),
                'added_by_user_id': str(user.id),
                'relationship_type': 'response_sent',
                'confidence_score': 1.0,
                'extraction_source': 'manual_response',
                'is_primary_email': False
            },
            'content_analysis': {
                'language': 'en',
                'sentiment': 'neutral',
                'key_phrases': [],
                'entities': [],
                'topics': []
            }
        }
        
        return email_data
    
    @staticmethod
    def sync_existing_emails_to_events():
        """
        Sync existing EmailProcessing records to their associated events using streamlined approach.
        This is a utility method for migrating existing data.
        """
        processed_count = 0
        error_count = 0
        
        # Get all EmailProcessing records that have associated events
        email_processings = EmailProcessing.objects.filter(
            event__isnull=False,
            status='verified'
        ).select_related('event', 'processed_by')
        
        for email_processing in email_processings:
            try:
                event = email_processing.event
                email_id = str(email_processing.id)
                
                # Check if this email is already attached to the event
                if email_id not in event.attached_email_ids:
                    # Attach the EmailProcessing record to the event
                    success = event.attach_email(email_processing.id)
                    
                    if success:
                        # Migrate existing data to complete_email_data if needed
                        if not email_processing.has_complete_email_data():
                            email_data = EmailIntegrationService._create_email_data_from_processing(
                                email_processing, 'original_request'
                            )
                            email_processing.complete_email_data = email_data
                            email_processing.save()
                        
                        event.save()
                        processed_count += 1
                        print(f"Synced email {email_processing.email_id} to event {event.id}")
                    else:
                        error_count += 1
                        print(f"Failed to sync email {email_processing.email_id}")
                
            except Exception as e:
                error_count += 1
                print(f"Error syncing email {email_processing.email_id}: {e}")
        
        print(f"Sync complete: {processed_count} emails synced, {error_count} errors")
        return processed_count, error_count