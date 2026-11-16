# SPDX-License-Identifier: Apache-2.0
"""
Email processing services for HillDesk.
Provides high-level email processing functionality using Microsoft Graph API.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model

from .graph_client import MicrosoftGraphClient, GraphAPIError
from .models import EmailProcessing

User = get_user_model()
logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')


class EmailProcessingService:
    """
    Service for processing emails from Microsoft Graph API.
    Handles email retrieval, filtering, and processing workflows.
    """
    
    def __init__(self, user_email: str = None):
        """
        Initialize the email processing service.
        
        Args:
            user_email: Email address of the user to process emails for
        """
        self.user_email = user_email
        self.graph_client = MicrosoftGraphClient()
        
        # Configuration from settings
        self.batch_size = getattr(settings, 'GRAPH_API_SETTINGS', {}).get(
            'DEFAULT_EMAIL_BATCH_SIZE', 50
        )
        self.max_batch_size = getattr(settings, 'GRAPH_API_SETTINGS', {}).get(
            'MAX_EMAIL_BATCH_SIZE', 1000
        )
    
    def test_connection(self) -> bool:
        """
        Test connection to Microsoft Graph API.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            return self.graph_client.test_connection()
        except Exception as e:
            logger.error(f"Graph API connection test failed: {e}")
            return False
    
    def get_new_emails(self, user_email: str = None, 
                      hours_back: int = 24) -> List[Dict[str, Any]]:
        """
        Get new emails from the last specified hours.
        
        Args:
            user_email: User's email address (uses instance default if not provided)
            hours_back: Number of hours to look back for new emails
            
        Returns:
            List of email dictionaries
            
        Raises:
            GraphAPIError: If API request fails
        """
        user_email = user_email or self.user_email
        if not user_email:
            raise ValueError("User email is required")
        
        # Calculate time filter
        cutoff_time = timezone.now() - timedelta(hours=hours_back)
        filter_query = f"receivedDateTime ge {cutoff_time.isoformat()}"
        
        try:
            response = self.graph_client.get_user_emails(
                user_id=user_email,
                folder='inbox',
                top=self.batch_size,
                filter_query=filter_query
            )
            
            emails = response.get('value', [])
            
            security_logger.info(
                'New emails retrieved',
                extra={
                    'user_email': user_email,
                    'count': len(emails),
                    'hours_back': hours_back,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return emails
            
        except GraphAPIError as e:
            logger.error(f"Failed to get new emails for {user_email}: {e}")
            raise
    
    def get_unread_emails(self, user_email: str = None) -> List[Dict[str, Any]]:
        """
        Get unread emails from user's inbox.
        
        Args:
            user_email: User's email address (uses instance default if not provided)
            
        Returns:
            List of unread email dictionaries
        """
        user_email = user_email or self.user_email
        if not user_email:
            raise ValueError("User email is required")
        
        filter_query = "isRead eq false"
        
        try:
            response = self.graph_client.get_user_emails(
                user_id=user_email,
                folder='inbox',
                top=self.batch_size,
                filter_query=filter_query
            )
            
            emails = response.get('value', [])
            
            security_logger.info(
                'Unread emails retrieved',
                extra={
                    'user_email': user_email,
                    'count': len(emails),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return emails
            
        except GraphAPIError as e:
            logger.error(f"Failed to get unread emails for {user_email}: {e}")
            raise
    
    def get_email_details(self, user_email: str, email_id: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific email.
        
        Args:
            user_email: User's email address
            email_id: Email message ID
            
        Returns:
            Detailed email dictionary
        """
        try:
            email = self.graph_client.get_email_by_id(user_email, email_id)
            
            security_logger.info(
                'Email details retrieved',
                extra={
                    'user_email': user_email,
                    'email_id': email_id,
                    'subject': email.get('subject', '')[:100],  # Truncate for logging
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return email
            
        except GraphAPIError as e:
            logger.error(f"Failed to get email details for {email_id}: {e}")
            raise
    
    def search_emails(self, user_email: str, search_query: str, 
                     folder: str = 'inbox', max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Search emails using a query string.
        
        Args:
            user_email: User's email address
            search_query: Search query string
            folder: Mail folder to search in
            max_results: Maximum number of results to return
            
        Returns:
            List of matching email dictionaries
        """
        try:
            # Use OData filter for basic search
            filter_query = f"contains(subject,'{search_query}') or contains(bodyPreview,'{search_query}')"
            
            response = self.graph_client.get_user_emails(
                user_id=user_email,
                folder=folder,
                top=min(max_results, self.max_batch_size),
                filter_query=filter_query
            )
            
            emails = response.get('value', [])
            
            security_logger.info(
                'Email search performed',
                extra={
                    'user_email': user_email,
                    'search_query': search_query[:100],  # Truncate for logging
                    'folder': folder,
                    'results_count': len(emails),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return emails
            
        except GraphAPIError as e:
            logger.error(f"Failed to search emails for {user_email}: {e}")
            raise
    
    def send_email_response(self, user_email: str, to_recipients: List[str],
                          subject: str, body: str, cc_recipients: List[str] = None,
                          bcc_recipients: List[str] = None, is_html: bool = True) -> bool:
        """
        Send an email response on behalf of the user.
        
        Args:
            user_email: User's email address
            to_recipients: List of recipient email addresses
            subject: Email subject
            body: Email body content
            cc_recipients: List of CC recipient email addresses
            bcc_recipients: List of BCC recipient email addresses
            is_html: Whether body is HTML content
            
        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            self.graph_client.send_email(
                user_id=user_email,
                to_recipients=to_recipients,
                subject=subject,
                body=body,
                cc_recipients=cc_recipients,
                bcc_recipients=bcc_recipients,
                is_html=is_html
            )
            
            security_logger.info(
                'Email response sent',
                extra={
                    'user_email': user_email,
                    'to_count': len(to_recipients),
                    'cc_count': len(cc_recipients or []),
                    'bcc_count': len(bcc_recipients or []),
                    'subject': subject[:100],  # Truncate for logging
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return True
            
        except GraphAPIError as e:
            logger.error(f"Failed to send email response for {user_email}: {e}")
            return False
    
    def reply_to_email(self, user_email: str, email_id: str, 
                      reply_body: str, is_html: bool = True) -> bool:
        """
        Reply to a specific email.
        
        Args:
            user_email: User's email address
            email_id: Original email message ID
            reply_body: Reply body content
            is_html: Whether body is HTML content
            
        Returns:
            True if reply was sent successfully, False otherwise
        """
        try:
            self.graph_client.reply_to_email(
                user_id=user_email,
                email_id=email_id,
                body=reply_body,
                is_html=is_html
            )
            
            security_logger.info(
                'Email reply sent',
                extra={
                    'user_email': user_email,
                    'original_email_id': email_id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return True
            
        except GraphAPIError as e:
            logger.error(f"Failed to reply to email {email_id} for {user_email}: {e}")
            return False
    
    def process_email_for_scheduling(self, user_email: str, email_id: str) -> Optional[str]:
        """
        Process an email to determine if it's a scheduling request.
        Creates an EmailProcessing record for tracking.
        
        Args:
            user_email: User's email address
            email_id: Email message ID
            
        Returns:
            EmailProcessing record ID if created, None if processing failed
        """
        try:
            # Get email details
            email = self.get_email_details(user_email, email_id)
            
            # Check if already processed
            existing = EmailProcessing.objects.filter(email_id=email_id).first()
            if existing:
                logger.info(f"Email {email_id} already processed")
                return str(existing.id)
            
            # Create processing record
            processing_record = EmailProcessing.objects.create(
                email_id=email_id,
                subject=email.get('subject', ''),
                sender=self._extract_sender_email(email),
                received=self._parse_datetime(email.get('receivedDateTime')),
                status='pending'
            )
            
            security_logger.info(
                'Email processing record created',
                extra={
                    'user_email': user_email,
                    'email_id': email_id,
                    'processing_id': str(processing_record.id),
                    'subject': email.get('subject', '')[:100],
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return str(processing_record.id)
            
        except Exception as e:
            logger.error(f"Failed to process email {email_id} for scheduling: {e}")
            return None
    
    def get_user_profile(self, user_email: str) -> Optional[Dict[str, Any]]:
        """
        Get user profile information from Microsoft Graph.
        
        Args:
            user_email: User's email address
            
        Returns:
            User profile dictionary or None if failed
        """
        try:
            profile = self.graph_client.get_user_profile(user_email)
            
            security_logger.info(
                'User profile retrieved',
                extra={
                    'user_email': user_email,
                    'display_name': profile.get('displayName', ''),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return profile
            
        except GraphAPIError as e:
            logger.error(f"Failed to get user profile for {user_email}: {e}")
            return None
    
    def _extract_sender_email(self, email: Dict[str, Any]) -> str:
        """
        Extract sender email address from email data.
        
        Args:
            email: Email dictionary from Graph API
            
        Returns:
            Sender email address
        """
        sender = email.get('sender', {})
        email_address = sender.get('emailAddress', {})
        return email_address.get('address', '')
    
    def _parse_datetime(self, datetime_str: str) -> Optional[datetime]:
        """
        Parse datetime string from Graph API.
        
        Args:
            datetime_str: ISO datetime string
            
        Returns:
            Parsed datetime object or None if parsing fails
        """
        if not datetime_str:
            return None
        
        try:
            # Parse ISO format datetime
            dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse datetime '{datetime_str}': {e}")
            return None


class CalendarService:
    """
    Service for managing calendar operations via Microsoft Graph API.
    """
    
    def __init__(self, user_email: str = None):
        """
        Initialize the calendar service.
        
        Args:
            user_email: Email address of the user
        """
        self.user_email = user_email
        self.graph_client = MicrosoftGraphClient()
    
    def get_calendars(self, user_email: str = None) -> List[Dict[str, Any]]:
        """
        Get user's calendars.
        
        Args:
            user_email: User's email address (uses instance default if not provided)
            
        Returns:
            List of calendar dictionaries
        """
        user_email = user_email or self.user_email
        if not user_email:
            raise ValueError("User email is required")
        
        try:
            response = self.graph_client.get_user_calendars(user_email)
            calendars = response.get('value', [])
            
            security_logger.info(
                'User calendars retrieved',
                extra={
                    'user_email': user_email,
                    'count': len(calendars),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return calendars
            
        except GraphAPIError as e:
            logger.error(f"Failed to get calendars for {user_email}: {e}")
            raise
    
    def create_event(self, user_email: str, subject: str, 
                    start_time: datetime, end_time: datetime,
                    location: str = None, description: str = None,
                    attendees: List[str] = None) -> Optional[str]:
        """
        Create a calendar event.
        
        Args:
            user_email: User's email address
            subject: Event subject/title
            start_time: Event start time
            end_time: Event end time
            location: Event location
            description: Event description
            attendees: List of attendee email addresses
            
        Returns:
            Created event ID or None if creation failed
        """
        try:
            event = self.graph_client.create_calendar_event(
                user_id=user_email,
                subject=subject,
                start_time=start_time,
                end_time=end_time,
                location=location,
                body=description,
                attendees=attendees
            )
            
            event_id = event.get('id')
            
            security_logger.info(
                'Calendar event created',
                extra={
                    'user_email': user_email,
                    'event_id': event_id,
                    'subject': subject,
                    'start_time': start_time.isoformat(),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return event_id
            
        except GraphAPIError as e:
            logger.error(f"Failed to create calendar event for {user_email}: {e}")
            return None
    
    def update_event(self, user_email: str, event_id: str, 
                    updates: Dict[str, Any]) -> bool:
        """
        Update an existing calendar event.
        
        Args:
            user_email: User's email address
            event_id: Calendar event ID
            updates: Dictionary of fields to update
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            self.graph_client.update_calendar_event(user_email, event_id, updates)
            
            security_logger.info(
                'Calendar event updated',
                extra={
                    'user_email': user_email,
                    'event_id': event_id,
                    'updated_fields': list(updates.keys()),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return True
            
        except GraphAPIError as e:
            logger.error(f"Failed to update calendar event {event_id} for {user_email}: {e}")
            return False
    
    def delete_event(self, user_email: str, event_id: str) -> bool:
        """
        Delete a calendar event.
        
        Args:
            user_email: User's email address
            event_id: Calendar event ID
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            self.graph_client.delete_calendar_event(user_email, event_id)
            
            security_logger.info(
                'Calendar event deleted',
                extra={
                    'user_email': user_email,
                    'event_id': event_id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return True
            
        except GraphAPIError as e:
            logger.error(f"Failed to delete calendar event {event_id} for {user_email}: {e}")
            return False


class ContactService:
    """
    Service for managing contacts via Microsoft Graph API.
    """
    
    def __init__(self, user_email: str = None):
        """
        Initialize the contact service.
        
        Args:
            user_email: Email address of the user
        """
        self.user_email = user_email
        self.graph_client = MicrosoftGraphClient()
    
    def get_contacts(self, user_email: str = None, 
                    max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Get user's contacts.
        
        Args:
            user_email: User's email address (uses instance default if not provided)
            max_results: Maximum number of contacts to return
            
        Returns:
            List of contact dictionaries
        """
        user_email = user_email or self.user_email
        if not user_email:
            raise ValueError("User email is required")
        
        try:
            response = self.graph_client.get_user_contacts(
                user_id=user_email,
                top=max_results
            )
            
            contacts = response.get('value', [])
            
            security_logger.info(
                'User contacts retrieved',
                extra={
                    'user_email': user_email,
                    'count': len(contacts),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return contacts
            
        except GraphAPIError as e:
            logger.error(f"Failed to get contacts for {user_email}: {e}")
            raise
    
    def search_contacts(self, user_email: str, search_term: str) -> List[Dict[str, Any]]:
        """
        Search contacts by name or email.
        
        Args:
            user_email: User's email address
            search_term: Search term for name or email
            
        Returns:
            List of matching contact dictionaries
        """
        # Get all contacts and filter locally (Graph API has limited search capabilities)
        try:
            all_contacts = self.get_contacts(user_email, max_results=1000)
            
            # Filter contacts based on search term
            matching_contacts = []
            search_lower = search_term.lower()
            
            for contact in all_contacts:
                display_name = contact.get('displayName', '').lower()
                email_addresses = contact.get('emailAddresses', [])
                
                # Check display name
                if search_lower in display_name:
                    matching_contacts.append(contact)
                    continue
                
                # Check email addresses
                for email_addr in email_addresses:
                    if search_lower in email_addr.get('address', '').lower():
                        matching_contacts.append(contact)
                        break
            
            security_logger.info(
                'Contact search performed',
                extra={
                    'user_email': user_email,
                    'search_term': search_term[:50],  # Truncate for logging
                    'results_count': len(matching_contacts),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return matching_contacts
            
        except Exception as e:
            logger.error(f"Failed to search contacts for {user_email}: {e}")
            return []