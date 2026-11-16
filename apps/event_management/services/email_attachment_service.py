# SPDX-License-Identifier: Apache-2.0
"""
Email Attachment Service for Event Management (Streamlined Approach).
Handles creating EmailProcessing records with complete email data and attaching them to events.
"""

import uuid
from datetime import datetime
from typing import Dict, List, Any
from django.utils import timezone
from django.contrib.auth import get_user_model
from ..models import Event

User = get_user_model()


class EmailAttachmentService:
    """Service for managing email attachments to events using streamlined approach."""
    
    @staticmethod
    def create_email_data_from_outlook(outlook_email: Dict[str, Any], email_type: str = 'original_request') -> Dict[str, Any]:
        """
        Convert Outlook Graph API email data to our standardized email format.
        
        Args:
            outlook_email: Raw email data from Microsoft Graph API
            email_type: Type of email (original_request, response_sent, follow_up, etc.)
            
        Returns:
            Standardized email data dictionary
        """
        # Generate unique email ID if not present
        email_id = outlook_email.get('id', str(uuid.uuid4()))
        
        # Extract sender information
        sender_info = outlook_email.get('sender', {}).get('emailAddress', {})
        from_data = {
            'name': sender_info.get('name', ''),
            'email': sender_info.get('address', ''),
            'display_name': f"{sender_info.get('name', '')} <{sender_info.get('address', '')}>"
        }
        
        # Extract recipients
        to_recipients = []
        for recipient in outlook_email.get('toRecipients', []):
            email_addr = recipient.get('emailAddress', {})
            to_recipients.append({
                'name': email_addr.get('name', ''),
                'email': email_addr.get('address', ''),
                'display_name': f"{email_addr.get('name', '')} <{email_addr.get('address', '')}>"
            })
        
        cc_recipients = []
        for recipient in outlook_email.get('ccRecipients', []):
            email_addr = recipient.get('emailAddress', {})
            cc_recipients.append({
                'name': email_addr.get('name', ''),
                'email': email_addr.get('address', ''),
                'display_name': f"{email_addr.get('name', '')} <{email_addr.get('address', '')}>"
            })
        
        bcc_recipients = []
        for recipient in outlook_email.get('bccRecipients', []):
            email_addr = recipient.get('emailAddress', {})
            bcc_recipients.append({
                'name': email_addr.get('name', ''),
                'email': email_addr.get('address', ''),
                'display_name': f"{email_addr.get('name', '')} <{email_addr.get('address', '')}>"
            })
        
        # Extract body content
        body_data = outlook_email.get('body', {})
        body = {
            'html': body_data.get('content', '') if body_data.get('contentType') == 'html' else '',
            'text': body_data.get('content', '') if body_data.get('contentType') == 'text' else '',
            'preview': outlook_email.get('bodyPreview', '')[:200]  # First 200 chars
        }
        
        # If we only have HTML, try to extract text (simplified)
        if body['html'] and not body['text']:
            import re
            # Simple HTML to text conversion (remove tags)
            body['text'] = re.sub(r'<[^>]+>', '', body['html'])
        
        # Parse dates
        date_sent = outlook_email.get('sentDateTime')
        date_received = outlook_email.get('receivedDateTime')
        
        if isinstance(date_sent, str):
            try:
                date_sent = datetime.fromisoformat(date_sent.replace('Z', '+00:00')).isoformat()
            except ValueError:
                date_sent = date_sent
        elif date_sent:
            date_sent = date_sent.isoformat()
        
        if isinstance(date_received, str):
            try:
                date_received = datetime.fromisoformat(date_received.replace('Z', '+00:00')).isoformat()
            except ValueError:
                date_received = date_received
        elif date_received:
            date_received = date_received.isoformat()
        
        # Create standardized email data
        email_data = {
            'email_id': email_id,
            'email_type': email_type,
            'source': 'outlook',
            'thread_id': outlook_email.get('conversationId', ''),
            'message_id': outlook_email.get('internetMessageId', ''),
            'in_reply_to': outlook_email.get('inReplyTo', ''),
            'references': outlook_email.get('references', []),
            'subject': outlook_email.get('subject', ''),
            'from': from_data,
            'to': to_recipients,
            'cc': cc_recipients,
            'bcc': bcc_recipients,
            'date_sent': date_sent,
            'date_received': date_received,
            'body': body,
            'attachments': [],  # Will be populated separately if needed
            'headers': {
                'importance': outlook_email.get('importance', 'normal'),
                'priority': outlook_email.get('importance', 'normal'),
                'sensitivity': outlook_email.get('sensitivity', 'normal'),
                'delivery_receipt_requested': outlook_email.get('isDeliveryReceiptRequested', False),
                'read_receipt_requested': outlook_email.get('isReadReceiptRequested', False)
            },
            'outlook_metadata': {
                'conversation_id': outlook_email.get('conversationId', ''),
                'internet_message_id': outlook_email.get('internetMessageId', ''),
                'web_link': outlook_email.get('webLink', ''),
                'categories': outlook_email.get('categories', []),
                'flag_status': outlook_email.get('flag', {}).get('flagStatus', 'notFlagged'),
                'is_read': outlook_email.get('isRead', False),
                'has_attachments': outlook_email.get('hasAttachments', False)
            },
            'processing_metadata': {
                'added_to_event': timezone.now().isoformat(),
                'added_by_user_id': None,  # Will be set when attached to event
                'relationship_type': email_type,
                'confidence_score': 1.0,
                'extraction_source': 'outlook_integration',
                'is_primary_email': email_type == 'original_request'
            },
            'content_analysis': {
                'language': 'en',  # Default, could be detected
                'sentiment': 'neutral',  # Could be analyzed
                'key_phrases': [],  # Could be extracted
                'entities': [],  # Could be extracted
                'topics': []  # Could be extracted
            }
        }
        
        return email_data
    
    @staticmethod
    def create_email_data_from_eml(eml_data: Dict[str, Any], email_type: str = 'imported') -> Dict[str, Any]:
        """
        Convert eml_parser output to our standardized email format.
        
        Args:
            eml_data: Parsed email data from eml_parser
            email_type: Type of email
            
        Returns:
            Standardized email data dictionary
        """
        # Generate unique email ID
        email_id = str(uuid.uuid4())
        
        # Extract header information
        header = eml_data.get('header', {})
        
        # Extract sender
        from_data = {
            'name': header.get('from', ''),
            'email': header.get('from', ''),
            'display_name': header.get('from', '')
        }
        
        # Extract recipients
        to_recipients = []
        if 'to' in header:
            to_list = header['to'] if isinstance(header['to'], list) else [header['to']]
            for recipient in to_list:
                to_recipients.append({
                    'name': recipient,
                    'email': recipient,
                    'display_name': recipient
                })
        
        # Extract body
        body = {
            'text': eml_data.get('body', [{}])[0].get('content', '') if eml_data.get('body') else '',
            'html': '',  # Would need to be extracted from multipart if available
            'preview': (eml_data.get('body', [{}])[0].get('content', '') if eml_data.get('body') else '')[:200]
        }
        
        # Create standardized email data
        email_data = {
            'email_id': email_id,
            'email_type': email_type,
            'source': 'imported',
            'thread_id': header.get('message-id', ''),
            'message_id': header.get('message-id', ''),
            'in_reply_to': header.get('in-reply-to', ''),
            'references': header.get('references', '').split() if header.get('references') else [],
            'subject': header.get('subject', ''),
            'from': from_data,
            'to': to_recipients,
            'cc': [],  # Would need to be extracted
            'bcc': [],  # Would need to be extracted
            'date_sent': header.get('date', ''),
            'date_received': timezone.now().isoformat(),
            'body': body,
            'attachments': eml_data.get('attachment', []),
            'headers': {
                'importance': 'normal',
                'priority': 'normal',
                'sensitivity': 'normal',
                'delivery_receipt_requested': False,
                'read_receipt_requested': False
            },
            'outlook_metadata': {},
            'processing_metadata': {
                'added_to_event': timezone.now().isoformat(),
                'added_by_user_id': None,
                'relationship_type': email_type,
                'confidence_score': 0.8,
                'extraction_source': 'eml_import',
                'is_primary_email': email_type == 'original_request'
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
    def attach_email_to_event(event: Event, email_data: Dict[str, Any], user: User) -> bool:
        """
        Attach an email to an event by creating an EmailProcessing record.
        
        Args:
            event: Event instance to attach email to
            email_data: Standardized email data
            user: User performing the attachment
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from apps.email_processing.models import EmailProcessing
            
            # Extract basic email information
            email_id = email_data.get('email_id', str(uuid.uuid4()))
            subject = email_data.get('subject', '')
            sender_info = email_data.get('from', {})
            sender_email = sender_info.get('email', '')
            sender_name = sender_info.get('name', '')
            date_sent = email_data.get('date_sent')
            
            # Parse date
            if isinstance(date_sent, str):
                try:
                    date_sent = datetime.fromisoformat(date_sent.replace('Z', '+00:00'))
                    if timezone.is_naive(date_sent):
                        date_sent = timezone.make_aware(date_sent)
                except (ValueError, TypeError):
                    date_sent = timezone.now()
            elif not date_sent:
                date_sent = timezone.now()
            
            # Set processing metadata
            if 'processing_metadata' in email_data:
                email_data['processing_metadata']['attached_to_event'] = timezone.now().isoformat()
                email_data['processing_metadata']['attached_by_user_id'] = str(user.id)
                email_data['processing_metadata']['event_id'] = str(event.id)
            
            # Create or update EmailProcessing record
            email_processing, created = EmailProcessing.objects.get_or_create(
                email_id=email_id,
                defaults={
                    'subject': subject,
                    'sender': sender_email,
                    'sender_name': sender_name,
                    'received': date_sent,
                    'is_scheduling_request': email_data.get('email_type') == 'original_request',
                    'confidence': email_data.get('processing_metadata', {}).get('confidence_score', 1.0),
                    'status': 'verified',
                    'event': event,
                    'processed_by': user,
                    'complete_email_data': email_data,
                    'extracted_data': email_data.get('content_analysis', {})
                }
            )
            
            if not created:
                # Update existing record
                email_processing.complete_email_data = email_data
                email_processing.event = event
                email_processing.processed_by = user
                email_processing.status = 'verified'
                email_processing.save()

            # EmailProcessing.save() auto-links the email to its conversation
            # thread (from the Outlook conversationId in complete_email_data).
            # Record the explicit Event<->Email link as the source of truth.
            is_primary = email_data.get('email_type') == 'original_request'
            event.attach_email(
                email_processing,
                origin='ai_auto',
                user=user,
                is_primary=is_primary,
            )

            # For an original request, attach the whole conversation so later
            # replies on the same thread surface on the event automatically.
            if is_primary and email_processing.thread_id:
                event.attach_thread(email_processing.thread, user=user)

            event.modified_by = user
            event.save()

            return True
        except Exception as e:
            print(f"Error attaching email to event: {e}")
            return False
    
    @staticmethod
    def create_response_email_data(original_email: Dict[str, Any], response_content: str, 
                                 sender: User, recipient_email: str) -> Dict[str, Any]:
        """
        Create email data for a response email.
        
        Args:
            original_email: The original email being responded to
            response_content: Content of the response
            sender: User sending the response
            recipient_email: Email address of the recipient
            
        Returns:
            Standardized email data for the response
        """
        email_id = str(uuid.uuid4())
        
        # Create response subject
        original_subject = original_email.get('subject', '')
        response_subject = f"Re: {original_subject}" if not original_subject.startswith('Re:') else original_subject
        
        # Create sender info
        from_data = {
            'name': f"{sender.first_name} {sender.last_name}".strip() or sender.username,
            'email': sender.email,
            'display_name': f"{sender.first_name} {sender.last_name} <{sender.email}>".strip()
        }
        
        # Create recipient info
        original_sender = original_email.get('from', {})
        to_recipients = [{
            'name': original_sender.get('name', ''),
            'email': recipient_email,
            'display_name': f"{original_sender.get('name', '')} <{recipient_email}>"
        }]
        
        email_data = {
            'email_id': email_id,
            'email_type': 'response_sent',
            'source': 'manual',
            'thread_id': original_email.get('thread_id', ''),
            'message_id': f"<{email_id}@congressional-scheduling>",
            'in_reply_to': original_email.get('message_id', ''),
            'references': [original_email.get('message_id', '')],
            'subject': response_subject,
            'from': from_data,
            'to': to_recipients,
            'cc': [],
            'bcc': [],
            'date_sent': timezone.now().isoformat(),
            'date_received': timezone.now().isoformat(),
            'body': {
                'text': response_content,
                'html': f"<p>{response_content.replace(chr(10), '</p><p>')}</p>",
                'preview': response_content[:200]
            },
            'attachments': [],
            'headers': {
                'importance': 'normal',
                'priority': 'normal',
                'sensitivity': 'normal',
                'delivery_receipt_requested': False,
                'read_receipt_requested': False
            },
            'outlook_metadata': {},
            'processing_metadata': {
                'added_to_event': timezone.now().isoformat(),
                'added_by_user_id': str(sender.id),
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
    def get_email_thread(event: Event, thread_id: str) -> List[Dict[str, Any]]:
        """
        Get all emails in a thread for an event.
        
        Args:
            event: Event instance
            thread_id: Thread ID to search for
            
        Returns:
            List of emails in the thread, sorted by date
        """
        thread_emails = []
        
        for email in event.attached_emails:
            if email.get('thread_id') == thread_id:
                thread_emails.append(email)
        
        # Sort by date sent
        thread_emails.sort(key=lambda x: x.get('date_sent', ''))
        
        return thread_emails
    
    @staticmethod
    def update_email_in_event(event: Event, email_id: str, updated_data: Dict[str, Any], user: User) -> bool:
        """
        Update an email within an event's attached emails.
        
        Args:
            event: Event instance
            email_id: ID of the email to update
            updated_data: Updated email data
            user: User performing the update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            for i, email in enumerate(event.attached_emails):
                if email.get('email_id') == email_id:
                    # Update the email data
                    event.attached_emails[i] = {**email, **updated_data}
                    
                    # Update processing metadata
                    event.attached_emails[i]['processing_metadata']['modified_at'] = timezone.now().isoformat()
                    event.attached_emails[i]['processing_metadata']['modified_by_user_id'] = str(user.id)
                    
                    event.modified_by = user
                    event.save()
                    return True
            
            return False  # Email not found
        except Exception as e:
            print(f"Error updating email in event: {e}")
            return False