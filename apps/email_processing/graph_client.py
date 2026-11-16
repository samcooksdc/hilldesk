# SPDX-License-Identifier: Apache-2.0
"""
Microsoft Graph API client for HillDesk.
Handles authentication and API operations for Outlook integration.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Any
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger('apps.email_processing')
security_logger = logging.getLogger('security_audit')


class GraphAPIError(Exception):
    """Base exception for Graph API errors."""
    pass


class GraphAPIAuthenticationError(GraphAPIError):
    """Exception raised for authentication errors."""
    pass


class GraphAPIRateLimitError(GraphAPIError):
    """Exception raised when rate limit is exceeded."""
    pass


class GraphAPIPermissionError(GraphAPIError):
    """Exception raised for permission errors."""
    pass


class MicrosoftGraphClient:
    """
    Microsoft Graph API client for accessing Outlook emails, calendar, and contacts.
    Implements OAuth 2.0 client credentials flow with error handling and retry mechanisms.
    """
    
    BASE_URL = "https://graph.microsoft.com/v1.0"
    AUTH_URL = "https://login.microsoftonline.com"
    
    def __init__(self, tenant_id: str = None, client_id: str = None, client_secret: str = None):
        """
        Initialize the Graph API client.
        
        Args:
            tenant_id: Azure AD tenant ID
            client_id: Application (client) ID
            client_secret: Client secret
        """
        self.tenant_id = tenant_id or getattr(settings, 'MICROSOFT_TENANT_ID', None)
        self.client_id = client_id or getattr(settings, 'MICROSOFT_CLIENT_ID', None)
        self.client_secret = client_secret or getattr(settings, 'MICROSOFT_CLIENT_SECRET', None)
        
        if not all([self.tenant_id, self.client_id, self.client_secret]):
            raise GraphAPIError("Microsoft Graph API credentials not configured")
        
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        # Rate limiting configuration
        self.max_retries = 3
        self.retry_delay = 1  # seconds
        self.rate_limit_delay = 60  # seconds
        # (connect, read) seconds. Without a timeout a stalled Graph endpoint
        # blocks the calling request/worker indefinitely.
        self.timeout = (5, 30)
    
    def _get_access_token(self) -> str:
        """
        Get access token using OAuth 2.0 client credentials flow.
        Implements caching to avoid unnecessary token requests.
        
        Returns:
            Access token string
            
        Raises:
            GraphAPIAuthenticationError: If authentication fails
        """
        # Check cache first
        cache_key = f"graph_token_{self.client_id}"
        token = cache.get(cache_key)
        
        if token:
            return token
        
        # Request new token
        token_url = f"{self.AUTH_URL}/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials'
        }
        
        try:
            response = requests.post(token_url, data=data, timeout=self.timeout)
            response.raise_for_status()
            
            token_data = response.json()
            access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 3600)
            
            # Cache token with 5 minute buffer before expiration
            # Ensure expires_in is an integer for calculation
            try:
                expires_in = int(expires_in)
                cache_timeout = max(expires_in - 300, 300)
            except (ValueError, TypeError):
                cache_timeout = 3300  # Default to 55 minutes
            
            cache.set(cache_key, access_token, cache_timeout)
            
            security_logger.info(
                'Microsoft Graph API token obtained',
                extra={
                    'client_id': self.client_id,
                    'expires_in': expires_in,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to obtain Graph API token: {e}")
            raise GraphAPIAuthenticationError(f"Authentication failed: {e}")
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Make authenticated request to Graph API with retry logic.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for requests
            
        Returns:
            JSON response data
            
        Raises:
            GraphAPIError: For various API errors
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        
        for attempt in range(self.max_retries + 1):
            try:
                # Get fresh token for each request
                token = self._get_access_token()
                headers = kwargs.get('headers', {})
                headers['Authorization'] = f'Bearer {token}'
                kwargs['headers'] = headers
                
                kwargs.setdefault('timeout', self.timeout)
                response = self.session.request(method, url, **kwargs)
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', self.rate_limit_delay))
                    logger.warning(f"Rate limit exceeded, waiting {retry_after} seconds")
                    
                    if attempt < self.max_retries:
                        time.sleep(retry_after)
                        continue
                    else:
                        raise GraphAPIRateLimitError("Rate limit exceeded after retries")
                
                # Handle authentication errors
                if response.status_code == 401:
                    # Clear cached token and retry once
                    cache_key = f"graph_token_{self.client_id}"
                    cache.delete(cache_key)
                    
                    if attempt < self.max_retries:
                        continue
                    else:
                        raise GraphAPIAuthenticationError("Authentication failed")
                
                # Handle permission errors
                if response.status_code == 403:
                    raise GraphAPIPermissionError("Insufficient permissions")
                
                # Handle other client errors
                if 400 <= response.status_code < 500:
                    error_data = response.json() if response.content else {}
                    error_message = error_data.get('error', {}).get('message', 'Unknown error')
                    raise GraphAPIError(f"Client error {response.status_code}: {error_message}")
                
                # Handle server errors with retry
                if response.status_code >= 500:
                    if attempt < self.max_retries:
                        wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Server error {response.status_code}, retrying in {wait_time} seconds")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise GraphAPIError(f"Server error {response.status_code} after retries")
                
                # Success
                response.raise_for_status()
                return response.json() if response.content else {}
                
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"Request failed: {e}, retrying in {wait_time} seconds")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Request failed after retries: {e}")
                    raise GraphAPIError(f"Request failed: {e}")
        
        raise GraphAPIError("Max retries exceeded")
    
    # Email Operations
    
    def get_user_emails(self, user_id: str, folder: str = 'inbox', 
                       top: int = 50, skip: int = 0, 
                       filter_query: str = None) -> Dict[str, Any]:
        """
        Get emails from user's mailbox.
        
        Args:
            user_id: User's email address or ID
            folder: Mail folder (inbox, sent, drafts, etc.)
            top: Number of emails to retrieve (max 1000)
            skip: Number of emails to skip
            filter_query: OData filter query
            
        Returns:
            Dictionary containing emails and metadata
        """
        endpoint = f"users/{user_id}/mailFolders/{folder}/messages"
        
        params = {
            '$top': min(top, 1000),
            '$skip': skip,
            '$orderby': 'receivedDateTime desc',
            '$select': 'id,subject,sender,toRecipients,receivedDateTime,bodyPreview,body,hasAttachments,importance,isRead'
        }
        
        if filter_query:
            params['$filter'] = filter_query
        
        try:
            response = self._make_request('GET', endpoint, params=params)
            
            security_logger.info(
                'User emails retrieved',
                extra={
                    'user_id': user_id,
                    'folder': folder,
                    'count': len(response.get('value', [])),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to get emails for user {user_id}: {e}")
            raise
    
    def get_email_by_id(self, user_id: str, email_id: str) -> Dict[str, Any]:
        """
        Get specific email by ID.
        
        Args:
            user_id: User's email address or ID
            email_id: Email message ID
            
        Returns:
            Email data dictionary
        """
        endpoint = f"users/{user_id}/messages/{email_id}"
        
        params = {
            '$select': 'id,subject,sender,toRecipients,ccRecipients,bccRecipients,receivedDateTime,sentDateTime,body,bodyPreview,hasAttachments,importance,isRead,conversationId'
        }
        
        try:
            response = self._make_request('GET', endpoint, params=params)
            
            security_logger.info(
                'Email retrieved by ID',
                extra={
                    'user_id': user_id,
                    'email_id': email_id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to get email {email_id} for user {user_id}: {e}")
            raise
    
    # Full message + delta id (message-level headers needed for the funnel)
    _FULL_MESSAGE_SELECT = (
        'id,internetMessageId,subject,sender,from,toRecipients,ccRecipients,'
        'bccRecipients,receivedDateTime,sentDateTime,body,bodyPreview,'
        'hasAttachments,importance,isRead,conversationId,internetMessageHeaders'
    )
    _DELTA_SELECT = (
        'id,internetMessageId,subject,sender,from,receivedDateTime,'
        'conversationId,hasAttachments,isRead'
    )

    def _relativize(self, url: str) -> str:
        """Strip the Graph base URL from an absolute @odata link so it can be
        passed back through ``_make_request`` as an endpoint (with its embedded
        query string preserved)."""
        prefix = self.BASE_URL + '/'
        if url.startswith(prefix):
            return url[len(prefix):]
        if url.startswith(self.BASE_URL):
            return url[len(self.BASE_URL):].lstrip('/')
        return url

    def get_message_full(self, user_id: str, message_id: str) -> Dict[str, Any]:
        """Fetch a single message with the full field set the funnel needs,
        including ``internetMessageHeaders`` (auth results, List-*, Auto-Submitted)
        and ``internetMessageId``."""
        endpoint = f"users/{user_id}/messages/{message_id}"
        params = {'$select': self._FULL_MESSAGE_SELECT}
        return self._make_request('GET', endpoint, params=params)

    def get_message_attachments(self, user_id: str, message_id: str) -> List[Dict[str, Any]]:
        """Return the attachments of a message (fileAttachment items carry
        base64 ``contentBytes``; itemAttachment/reference items carry metadata)."""
        endpoint = f"users/{user_id}/messages/{message_id}/attachments"
        response = self._make_request('GET', endpoint)
        return response.get('value', [])

    def delta_messages(self, user_id: str, folder: str = 'inbox',
                       delta_link: str = None, max_pages: int = 50) -> Dict[str, Any]:
        """Incrementally list messages in a folder using Graph delta queries.

        Args:
            user_id: Mailbox address/id.
            folder: Mail folder (default inbox).
            delta_link: The ``@odata.deltaLink`` (full URL, contains the delta
                token) returned by a previous call. None → full initial sync.
            max_pages: Safety cap on pagination.

        Returns:
            ``{'messages': [...], 'delta_link': <str or None>}``. ``delta_link``
            is the resume point to persist for the next sweep. On an invalidated
            token Graph returns an error; the caller falls back to window listing.
        """
        if delta_link:
            endpoint = self._relativize(delta_link)
            params = None
        else:
            endpoint = f"users/{user_id}/mailFolders/{folder}/messages/delta"
            params = {'$select': self._DELTA_SELECT}

        messages: List[Dict[str, Any]] = []
        new_delta_link = None
        pages = 0
        while True:
            if params is not None:
                response = self._make_request('GET', endpoint, params=params)
            else:
                response = self._make_request('GET', endpoint)
            messages.extend(response.get('value', []))
            pages += 1

            next_link = response.get('@odata.nextLink')
            final_link = response.get('@odata.deltaLink')
            if final_link:
                new_delta_link = final_link
                break
            if not next_link or pages >= max_pages:
                # Truncated at the page cap: nextLink is the resume point.
                new_delta_link = next_link
                break
            endpoint = self._relativize(next_link)
            params = None

        return {'messages': messages, 'delta_link': new_delta_link}

    def list_recent_messages(self, user_id: str, folder: str = 'inbox',
                             since=None, top: int = 200) -> List[Dict[str, Any]]:
        """Window-listing fallback for when a delta token is invalidated.

        Lists messages received since ``since`` (a datetime), newest first,
        using the same id-level select as delta so the sweep can diff against
        RawMessage.graph_message_id."""
        endpoint = f"users/{user_id}/mailFolders/{folder}/messages"
        params = {
            '$top': min(top, 1000),
            '$orderby': 'receivedDateTime desc',
            '$select': self._DELTA_SELECT,
        }
        if since is not None:
            iso = since.isoformat() if hasattr(since, 'isoformat') else since
            params['$filter'] = f"receivedDateTime ge {iso}"
        response = self._make_request('GET', endpoint, params=params)
        return response.get('value', [])

    # Subscription (webhook) lifecycle

    def create_subscription(self, resource: str, notification_url: str,
                            client_state: str, expiration,
                            change_type: str = 'created') -> Dict[str, Any]:
        """Create a Graph change-notification subscription."""
        exp = expiration.isoformat() if hasattr(expiration, 'isoformat') else expiration
        data = {
            'changeType': change_type,
            'notificationUrl': notification_url,
            'resource': resource,
            'expirationDateTime': exp,
            'clientState': client_state,
        }
        response = self._make_request('POST', 'subscriptions', json=data)
        security_logger.info(
            'Graph subscription created',
            extra={'resource': resource, 'subscription_id': response.get('id'),
                   'timestamp': timezone.now().isoformat()}
        )
        return response

    def renew_subscription(self, subscription_id: str, expiration) -> Dict[str, Any]:
        """Extend the expiration of an existing subscription."""
        exp = expiration.isoformat() if hasattr(expiration, 'isoformat') else expiration
        endpoint = f"subscriptions/{subscription_id}"
        return self._make_request('PATCH', endpoint, json={'expirationDateTime': exp})

    def delete_subscription(self, subscription_id: str) -> None:
        """Delete a subscription."""
        self._make_request('DELETE', f"subscriptions/{subscription_id}")

    def list_subscriptions(self) -> List[Dict[str, Any]]:
        """List all subscriptions owned by this application."""
        return self._make_request('GET', 'subscriptions').get('value', [])

    def send_email(self, user_id: str, to_recipients: List[str],
                   subject: str, body: str, cc_recipients: List[str] = None,
                   bcc_recipients: List[str] = None, is_html: bool = True) -> Dict[str, Any]:
        """
        Send email on behalf of user.
        
        Args:
            user_id: User's email address or ID
            to_recipients: List of recipient email addresses
            subject: Email subject
            body: Email body content
            cc_recipients: List of CC recipient email addresses
            bcc_recipients: List of BCC recipient email addresses
            is_html: Whether body is HTML content
            
        Returns:
            Response data from send operation
        """
        endpoint = f"users/{user_id}/sendMail"
        
        # Build recipient lists
        to_list = [{'emailAddress': {'address': addr}} for addr in to_recipients]
        cc_list = [{'emailAddress': {'address': addr}} for addr in (cc_recipients or [])]
        bcc_list = [{'emailAddress': {'address': addr}} for addr in (bcc_recipients or [])]
        
        message_data = {
            'message': {
                'subject': subject,
                'body': {
                    'contentType': 'HTML' if is_html else 'Text',
                    'content': body
                },
                'toRecipients': to_list
            }
        }
        
        if cc_list:
            message_data['message']['ccRecipients'] = cc_list
        
        if bcc_list:
            message_data['message']['bccRecipients'] = bcc_list
        
        try:
            response = self._make_request('POST', endpoint, json=message_data)
            
            security_logger.info(
                'Email sent',
                extra={
                    'user_id': user_id,
                    'to_count': len(to_recipients),
                    'cc_count': len(cc_recipients or []),
                    'bcc_count': len(bcc_recipients or []),
                    'subject': subject[:100],  # Truncate for logging
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to send email for user {user_id}: {e}")
            raise
    
    def reply_to_email(self, user_id: str, email_id: str, 
                      body: str, is_html: bool = True) -> Dict[str, Any]:
        """
        Reply to an email.
        
        Args:
            user_id: User's email address or ID
            email_id: Original email message ID
            body: Reply body content
            is_html: Whether body is HTML content
            
        Returns:
            Response data from reply operation
        """
        endpoint = f"users/{user_id}/messages/{email_id}/reply"
        
        reply_data = {
            'comment': body,
            'message': {
                'body': {
                    'contentType': 'HTML' if is_html else 'Text',
                    'content': body
                }
            }
        }
        
        try:
            response = self._make_request('POST', endpoint, json=reply_data)
            
            security_logger.info(
                'Email reply sent',
                extra={
                    'user_id': user_id,
                    'original_email_id': email_id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to reply to email {email_id} for user {user_id}: {e}")
            raise
    
    # Calendar Operations
    
    def get_user_calendars(self, user_id: str) -> Dict[str, Any]:
        """
        Get user's calendars.
        
        Args:
            user_id: User's email address or ID
            
        Returns:
            Dictionary containing calendars data
        """
        endpoint = f"users/{user_id}/calendars"
        
        try:
            response = self._make_request('GET', endpoint)
            
            security_logger.info(
                'User calendars retrieved',
                extra={
                    'user_id': user_id,
                    'count': len(response.get('value', [])),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to get calendars for user {user_id}: {e}")
            raise
    
    def create_calendar_event(self, user_id: str, subject: str, 
                            start_time: datetime, end_time: datetime,
                            location: str = None, body: str = None,
                            attendees: List[str] = None) -> Dict[str, Any]:
        """
        Create calendar event for user.
        
        Args:
            user_id: User's email address or ID
            subject: Event subject/title
            start_time: Event start time
            end_time: Event end time
            location: Event location
            body: Event description
            attendees: List of attendee email addresses
            
        Returns:
            Created event data
        """
        endpoint = f"users/{user_id}/events"
        
        # Format datetime for Graph API
        start_dt = start_time.isoformat()
        end_dt = end_time.isoformat()
        
        event_data = {
            'subject': subject,
            'start': {
                'dateTime': start_dt,
                'timeZone': 'UTC'
            },
            'end': {
                'dateTime': end_dt,
                'timeZone': 'UTC'
            }
        }
        
        if location:
            event_data['location'] = {'displayName': location}
        
        if body:
            event_data['body'] = {
                'contentType': 'HTML',
                'content': body
            }
        
        if attendees:
            event_data['attendees'] = [
                {
                    'emailAddress': {'address': email},
                    'type': 'required'
                }
                for email in attendees
            ]
        
        try:
            response = self._make_request('POST', endpoint, json=event_data)
            
            security_logger.info(
                'Calendar event created',
                extra={
                    'user_id': user_id,
                    'event_id': response.get('id'),
                    'subject': subject,
                    'start_time': start_dt,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to create calendar event for user {user_id}: {e}")
            raise
    
    def update_calendar_event(self, user_id: str, event_id: str, 
                            updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update existing calendar event.
        
        Args:
            user_id: User's email address or ID
            event_id: Calendar event ID
            updates: Dictionary of fields to update
            
        Returns:
            Updated event data
        """
        endpoint = f"users/{user_id}/events/{event_id}"
        
        try:
            response = self._make_request('PATCH', endpoint, json=updates)
            
            security_logger.info(
                'Calendar event updated',
                extra={
                    'user_id': user_id,
                    'event_id': event_id,
                    'updated_fields': list(updates.keys()),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to update calendar event {event_id} for user {user_id}: {e}")
            raise
    
    def delete_calendar_event(self, user_id: str, event_id: str) -> None:
        """
        Delete calendar event.
        
        Args:
            user_id: User's email address or ID
            event_id: Calendar event ID
        """
        endpoint = f"users/{user_id}/events/{event_id}"
        
        try:
            self._make_request('DELETE', endpoint)
            
            security_logger.info(
                'Calendar event deleted',
                extra={
                    'user_id': user_id,
                    'event_id': event_id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to delete calendar event {event_id} for user {user_id}: {e}")
            raise
    
    # Contact Operations
    
    def get_user_contacts(self, user_id: str, top: int = 50, 
                         skip: int = 0) -> Dict[str, Any]:
        """
        Get user's contacts.
        
        Args:
            user_id: User's email address or ID
            top: Number of contacts to retrieve
            skip: Number of contacts to skip
            
        Returns:
            Dictionary containing contacts data
        """
        endpoint = f"users/{user_id}/contacts"
        
        params = {
            '$top': min(top, 1000),
            '$skip': skip,
            '$orderby': 'displayName',
            '$select': 'id,displayName,emailAddresses,businessPhones,mobilePhone,jobTitle,companyName'
        }
        
        try:
            response = self._make_request('GET', endpoint, params=params)
            
            security_logger.info(
                'User contacts retrieved',
                extra={
                    'user_id': user_id,
                    'count': len(response.get('value', [])),
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to get contacts for user {user_id}: {e}")
            raise
    
    # Utility Methods
    
    def test_connection(self) -> bool:
        """
        Test connection to Microsoft Graph API.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            # Simple test request to get service root
            self._make_request('GET', '')
            return True
        except Exception as e:
            logger.error(f"Graph API connection test failed: {e}")
            return False
    
    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """
        Get user profile information.
        
        Args:
            user_id: User's email address or ID
            
        Returns:
            User profile data
        """
        endpoint = f"users/{user_id}"
        
        params = {
            '$select': 'id,displayName,mail,userPrincipalName,jobTitle,department,officeLocation'
        }
        
        try:
            response = self._make_request('GET', endpoint, params=params)
            
            security_logger.info(
                'User profile retrieved',
                extra={
                    'user_id': user_id,
                    'timestamp': timezone.now().isoformat(),
                }
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to get user profile for {user_id}: {e}")
            raise