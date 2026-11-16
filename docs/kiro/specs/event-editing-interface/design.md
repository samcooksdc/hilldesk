# Design Document

## Overview

The event editing interface is a sophisticated split-panel component that provides a comprehensive view for editing congressional events. The interface consists of an email viewer pane on the left (60% width) and an event editing panel on the right (33% width). The system supports both standard editing mode and an AI-assisted "SmartExtract" review mode where users can review and approve AI-generated suggestions.

The design leverages the existing Django backend with Event models and integrates seamlessly with the current theme system, responsive design patterns, and accessibility standards established in the application.

## Architecture

### Component Structure

```
EventEditingInterface/
├── EmailViewerPane/
│   ├── EmailToolbar/
│   │   ├── RespondButton
│   │   ├── OutlookButton
│   │   └── SearchField
│   └── EmailList/
│       ├── EmailCard[]
│       └── ScrollContainer
├── EventEditingPanel/
│   ├── PanelHeader/
│   │   ├── EventIcon
│   │   ├── TitleSection
│   │   └── CloseButton
│   ├── TimeRangeSection/
│   │   ├── DatePickers
│   │   ├── TimePickers
│   │   ├── LongerThanDayCheckbox
│   │   └── TimezoneSelector
│   ├── TabNavigation/
│   │   ├── EventDetailsTab
│   │   ├── InvolvedPartiesTab
│   │   └── StaffReviewTab
│   ├── ScrollableContent/
│   │   ├── EventDetailsForm
│   │   ├── InvolvedPartiesForm
│   │   └── StaffReviewForm
│   └── ActionBar/
│       ├── HideEmailButton
│       ├── RespondButton
│       ├── RequireReviewButton
│       └── EventStatusButton
└── SmartExtractOverlay/
    ├── AIFieldHighlights
    ├── EmailSourceHighlights
    ├── ReviewProgressBar
    └── ReviewControls
```

### Data Flow

1. **Event Selection**: User clicks on schedule card → triggers panel open
2. **Data Loading**: System fetches event data and related emails via AJAX
3. **Panel Rendering**: Interface renders with current event data
4. **User Interactions**: Form changes trigger validation and auto-save
5. **SmartExtract Mode**: AI suggestions are highlighted and require user approval
6. **Data Persistence**: Changes are saved to Django Event model via API endpoints

### State Management

The interface maintains several state layers:
- **Panel State**: Open/closed, active tab, scroll position
- **Form State**: Field values, validation errors, dirty flags
- **Review State**: AI suggestions, approval status, progress tracking
- **Email State**: Selected emails, search filters, scroll position

## Components and Interfaces

### EmailViewerPane Component

**Purpose**: Display related emails in a scrollable list with search and action capabilities, including full HTML email content display.

**Props**:
- `eventId`: UUID of the current event
- `emails`: Array of email objects
- `onEmailSelect`: Callback for email selection
- `searchQuery`: Current search filter

**State**:
- `selectedEmail`: Currently selected email
- `expandedEmail`: ID of currently expanded email showing HTML content
- `scrollPosition`: Current scroll position
- `searchQuery`: Search filter text
- `loadedImages`: Set of email IDs with loaded external images

**Methods**:
- `loadEmails()`: Fetch emails related to event
- `handleSearch()`: Filter emails by search query
- `handleEmailClick()`: Select email and highlight in panel
- `handleEmailExpand()`: Expand email to show full HTML content
- `handleEmailCollapse()`: Collapse expanded email back to card view
- `handleLoadImages()`: Load external images for HTML email content
- `handleRespond()`: Open email response modal
- `handleOutlookOpen()`: Open email in Outlook
- `sanitizeEmailHTML()`: Sanitize HTML content for safe display

### EventEditingPanel Component

**Purpose**: Main editing interface with tabbed content and form controls.

**Props**:
- `event`: Event object with all data
- `mode`: 'edit' | 'smartextract'
- `aiSuggestions`: Object with AI-generated field values
- `onSave`: Callback for saving changes
- `onClose`: Callback for closing panel

**State**:
- `activeTab`: Currently active tab ('details' | 'parties' | 'staff')
- `formData`: Current form values
- `validationErrors`: Field validation errors
- `isDirty`: Whether form has unsaved changes
- `reviewProgress`: Progress tracking for SmartExtract mode

**Methods**:
- `handleTabChange()`: Switch between tabs
- `handleFieldChange()`: Update form field values
- `handleSave()`: Save form data to backend
- `handleValidation()`: Validate form fields
- `handleAIApproval()`: Approve AI suggestions

### EmailHTMLViewer Component

**Purpose**: Display full HTML email content with proper sanitization and security controls.

**Props**:
- `email`: Email object with HTML content
- `isExpanded`: Whether the email is currently expanded
- `imagesLoaded`: Whether external images should be displayed
- `onCollapse`: Callback to collapse the email view
- `onLoadImages`: Callback to load external images

**State**:
- `sanitizedHTML`: Sanitized HTML content ready for display
- `attachments`: List of email attachments
- `hasExternalImages`: Whether the email contains external images

**Methods**:
- `sanitizeHTML()`: Clean HTML content and remove dangerous elements
- `extractAttachments()`: Extract attachment information from email data
- `detectExternalImages()`: Check if HTML contains external image references
- `processImageLoading()`: Handle external image loading when requested

**Security Features**:
- HTML sanitization using DOMPurify or similar library
- External image blocking by default
- Attachment handling with proper MIME type validation
- Script tag removal and event handler stripping

### Form Components

#### EventDetailsForm
- Location input with geocoding
- Event type, format, duration dropdowns
- Event tags with add/remove functionality
- Description and notes textareas

#### InvolvedPartiesForm
- Organization/group input
- Point of contact fields (name, expected attendees)
- Contact information textarea
- Assigned staff management
- Reminder scheduling

#### StaffReviewForm
- Staff assignment with pill tags
- Review table with avatars and status badges
- Notes textarea for review comments

### SmartExtract Components

#### AIFieldHighlight
**Purpose**: Highlight fields with AI suggestions and provide approval controls.

**Props**:
- `fieldName`: Name of the form field
- `suggestion`: AI-generated value
- `sourceText`: Original email text
- `onApprove`: Callback for approving suggestion
- `onReject`: Callback for rejecting suggestion

#### EmailSourceHighlight
**Purpose**: Highlight source text in email when hovering over AI suggestions.

**Props**:
- `emailId`: ID of source email
- `textRange`: Character range to highlight
- `isActive`: Whether highlight is currently active

#### ReviewProgressBar
**Purpose**: Show progress through AI suggestion review process.

**Props**:
- `totalFields`: Total number of fields with suggestions
- `reviewedFields`: Number of fields reviewed
- `onJumpToNext`: Callback to navigate to next unreviewed field

## Data Models

### Event Model Extensions

The existing Django Event model supports all required fields. Additional computed properties needed:

```python
@property
def ai_suggestions(self):
    """Get AI suggestions for this event if available"""
    return getattr(self, '_ai_suggestions', {})

@property
def review_progress(self):
    """Get review progress for SmartExtract mode"""
    return getattr(self, '_review_progress', {'reviewed': 0, 'total': 0})
```

### Frontend Data Structures

```typescript
interface EventData {
  id: string;
  type: string;
  start_date: string;
  end_date?: string;
  time: string;
  location: string;
  group: string;
  details: string;
  legislative_topics: string[];
  participants: string[];
  point_of_contact_name: string;
  point_of_contact_email: string;
  point_of_contact_phone: string;
  staff: string[];
  status: string;
  // ... other fields
}

interface AIsuggestion {
  field: string;
  value: any;
  confidence: number;
  sourceEmail: string;
  sourceRange: [number, number];
}

interface EmailData {
  id: string;
  subject: string;
  sender: string;
  senderName: string;
  date: string;
  body: {
    text: string;
    html: string;
    preview: string;
  };
  attachments: EmailAttachment[];
  isSelected: boolean;
  isExpanded: boolean;
  hasExternalImages: boolean;
  imagesLoaded: boolean;
}

interface EmailAttachment {
  id: string;
  name: string;
  contentType: string;
  size: number;
  downloadUrl: string;
}

interface EmailHTMLContent {
  sanitizedHTML: string;
  originalHTML: string;
  externalImages: string[];
  hasBlockedContent: boolean;
}
```

## Error Handling

### Validation Strategy

1. **Client-side Validation**: Real-time validation using existing form validation patterns
2. **Server-side Validation**: Django model validation with detailed error messages
3. **Network Error Handling**: Retry logic and user-friendly error messages
4. **Data Consistency**: Optimistic updates with rollback on failure

### Error States

- **Field Validation Errors**: Red border, error message below field
- **Network Errors**: Toast notifications with retry options
- **Save Conflicts**: Modal dialog with conflict resolution options
- **AI Service Errors**: Graceful degradation to manual editing mode

### Error Recovery

```javascript
// Example error handling pattern
async function saveEventData(eventData) {
  try {
    showLoading('Saving event...');
    const response = await api.updateEvent(eventData);
    showToast('Event saved successfully', 'success');
    return response;
  } catch (error) {
    if (error.status === 409) {
      // Handle conflict
      showConflictResolutionModal(error.data);
    } else if (error.status >= 500) {
      // Server error
      showToast('Server error. Please try again.', 'error');
    } else {
      // Validation error
      displayValidationErrors(error.data.errors);
    }
    throw error;
  } finally {
    hideLoading();
  }
}
```

## Testing Strategy

### Unit Tests

1. **Component Tests**: Test individual components in isolation
2. **Form Validation Tests**: Test all validation rules and error states
3. **State Management Tests**: Test state transitions and data flow
4. **API Integration Tests**: Test backend communication

### Integration Tests

1. **Panel Interaction Tests**: Test opening/closing and tab navigation
2. **SmartExtract Flow Tests**: Test AI suggestion review process
3. **Email Integration Tests**: Test email viewer and highlighting
4. **Responsive Behavior Tests**: Test across different screen sizes

### End-to-End Tests

1. **Complete Edit Flow**: Test full event editing workflow
2. **SmartExtract Review**: Test AI suggestion approval process
3. **Cross-browser Compatibility**: Test in major browsers
4. **Accessibility Tests**: Test keyboard navigation and screen readers

### Test Data

```javascript
// Example test data structures
const mockEvent = {
  id: 'test-event-123',
  type: 'meeting',
  start_date: '2025-02-15T14:00:00Z',
  location: 'Capitol Building Room 123',
  group: 'Healthcare Coalition',
  // ... other fields
};

const mockAISuggestions = {
  location: {
    value: 'Capitol Building Room 123',
    confidence: 0.95,
    sourceEmail: 'email-456',
    sourceRange: [245, 270]
  },
  // ... other suggestions
};
```

## Performance Considerations

### Optimization Strategies

1. **Lazy Loading**: Load email content on demand
2. **Virtual Scrolling**: Handle large email lists efficiently
3. **Debounced Search**: Prevent excessive API calls during search
4. **Memoization**: Cache computed values and API responses
5. **Code Splitting**: Load SmartExtract components only when needed

### Bundle Size Management

- Use dynamic imports for SmartExtract features
- Implement tree shaking for unused components
- Optimize CSS with purging unused styles
- Compress images and icons

### Memory Management

- Clean up event listeners on component unmount
- Implement proper cleanup for timers and intervals
- Use weak references for large data structures
- Monitor for memory leaks in development

## Accessibility

### WCAG 2.1 AA Compliance

1. **Keyboard Navigation**: Full keyboard support for all interactions
2. **Screen Reader Support**: Proper ARIA labels and live regions
3. **Color Contrast**: Meet minimum contrast ratios in all themes
4. **Focus Management**: Logical focus order and visible focus indicators

### Implementation Details

```html
<!-- Example accessible form field -->
<div class="form-field">
  <label for="event-location" class="form-label">
    Event Location
    <span class="required" aria-label="required">*</span>
  </label>
  <input
    id="event-location"
    type="text"
    class="form-input"
    aria-describedby="location-help location-error"
    aria-invalid="false"
    required
  />
  <div id="location-help" class="form-help">
    Enter the full address or venue name
  </div>
  <div id="location-error" class="form-error" aria-live="polite">
    <!-- Error message appears here -->
  </div>
</div>
```

### Screen Reader Announcements

- Panel open/close state changes
- Tab navigation changes
- Form validation errors
- Save success/failure messages
- SmartExtract review progress

## Security Considerations

### Data Protection

1. **Input Sanitization**: Sanitize all user inputs before processing
2. **XSS Prevention**: Use proper escaping for dynamic content
3. **CSRF Protection**: Include CSRF tokens in all API requests
4. **Data Classification**: Respect event data classification levels

### API Security

```javascript
// Example secure API call
async function updateEvent(eventId, data) {
  const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
  
  return fetch(`/api/events/${eventId}/`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: JSON.stringify(sanitizeEventData(data))
  });
}
```

### Audit Trail

- Log all event modifications with user and timestamp
- Track AI suggestion approvals/rejections
- Maintain change history for compliance
- Implement proper session management

## Integration Points

### Django Backend Integration

1. **Event API Endpoints**: CRUD operations for events
2. **Email Integration**: Fetch related emails via Graph API
3. **User Authentication**: Leverage existing auth system
4. **Permissions**: Respect user roles and permissions

### Microsoft Graph Integration

1. **Email Fetching**: Retrieve emails related to events
2. **Calendar Sync**: Update Outlook calendar events
3. **Response Handling**: Send email responses through Graph API

### AI Service Integration

1. **Information Extraction**: Extract event details from emails
2. **Suggestion Confidence**: Provide confidence scores for suggestions
3. **Source Mapping**: Map suggestions back to source text
4. **Error Handling**: Graceful degradation when AI services are unavailable

## Deployment Considerations

### Static Asset Management

- Use Django's static file handling for CSS/JS
- Implement proper cache headers for performance
- Use CDN for static assets in production
- Minify and compress assets for production builds

### Browser Support

- Support modern browsers (Chrome 90+, Firefox 88+, Safari 14+, Edge 90+)
- Provide graceful degradation for older browsers
- Test across different operating systems
- Ensure mobile browser compatibility

### Performance Monitoring

- Implement client-side error tracking
- Monitor API response times
- Track user interaction metrics
- Set up alerts for performance degradation