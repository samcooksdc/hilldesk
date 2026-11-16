# Human Review UI Requirements

## Overview

This document specifies the human-in-the-loop review interface for AI-extracted event data. All fields extracted by the LLM from emails must be explicitly reviewed by a staff member before the event can be acted upon. This keeps the AI assistive: a human makes every decision.

---

## Data Model Changes

### Event Model Updates

```python
class Event(models.Model):
    # ... existing fields ...
    
    requires_human_review = models.BooleanField(default=False)
    # True when event was created from email extraction
    # False for manually created events or after review completion
    
    extracted_fields = models.JSONField(default=dict, blank=True)
    # Contains AI-extracted field data with review state and source locations
    # Empty dict for manually created events
```

### extracted_fields JSON Schema

```python
{
    "title": {
        "original_value": "MINECRAFT Act Committee Meeting",
        "status": "unreviewed",  # unreviewed | accepted | rejected | accepted_all
        "reviewed_by": null,     # UUID of reviewing user (null if unreviewed)
        "reviewed_at": null,     # ISO timestamp (null if unreviewed)
        "source_location": {
            "start_index": 1245,
            "end_index": 1278,
            "text_snippet": "MINECRAFT Act Committee Meeting"
        }
    },
    "start_date": {
        "original_value": "2025-06-04",
        "status": "accepted",
        "reviewed_by": "550e8400-e29b-41d4-a716-446655440000",
        "reviewed_at": "2026-01-05T10:30:00Z",
        "source_location": {
            "start_index": 892,
            "end_index": 914,
            "text_snippet": "Tuesday, June 24, 2025"
        }
    },
    "start_time": {
        "original_value": "14:00",
        "status": "accepted_all",
        "reviewed_by": "550e8400-e29b-41d4-a716-446655440000",
        "reviewed_at": "2026-01-05T10:32:00Z",
        "source_location": {
            "start_index": 920,
            "end_index": 927,
            "text_snippet": "2:00 PM"
        }
    },
    "location": {
        "original_value": "H-137",
        "status": "rejected",
        "reviewed_by": "550e8400-e29b-41d4-a716-446655440000",
        "reviewed_at": "2026-01-05T10:31:00Z",
        "source_location": {
            "start_index": 956,
            "end_index": 961,
            "text_snippet": "H-137"
        }
    }
}
```

**Field Status Values:**
- `unreviewed`: AI extracted, awaiting human review
- `accepted`: Human confirmed AI value is correct
- `rejected`: Human rejected AI value, manually entered correction
- `accepted_all`: Human used Accept All function (requires future security approval)

**Source Location:**
- `start_index`: Character position where extracted text begins in email body
- `end_index`: Character position where extracted text ends
- `text_snippet`: Exact text matched (used for verification and fallback search)

### EventReviewAuditLog Model (New)

```python
class EventReviewAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='review_audit_logs')
    field_name = models.CharField(max_length=100)
    action = models.CharField(max_length=50, choices=[
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('accepted_and_edited', 'Accepted and Edited'),
        ('accepted_all', 'Accepted with Accept All'),
    ])
    original_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True, null=True)  # For rejected/edited fields
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['event', 'timestamp']),
        ]
```

---

## UI Specifications

### Modal Appearance

**Review Mode Indicator:**
- When `requires_human_review=True`, the entire modal has an orange glow/border (CSS `box-shadow` or `border`)
- This immediately signals the event needs attention
- Glow removed when review completes

**Email Pane:**
- Email pane is always visible and cannot be hidden during review mode
- "Hide Email" / "Display Email" button is removed from UI during review
- Email body must support scroll-to-position and text highlighting

### Field Visual States

**Unreviewed (needs attention):**
- Orange/yellow glow border around the input field
- Glow implemented via CSS `box-shadow` or `outline`

**Accepted:**
- Glow removed, field returns to normal appearance
- AI-suggested value retained in field

**Rejected:**
- Glow removed, field returns to normal appearance
- Field content cleared
- User can manually enter correct value

**Not Extracted:**
- Fields not in `extracted_fields` have no glow
- Behave as normal form fields

### Accept/Reject Controls

Each unreviewed field displays Accept and Reject controls:

**Option A - Popover (Recommended):**
- Small popover appears on field focus or hover
- Contains "✓ Accept" and "✗ Reject" buttons
- Popover positioned above or beside field

**Option B - Inline Buttons:**
- Small Accept/Reject icons inside the field on the right
- Less intrusive but may conflict with field content

**Click-to-Accept Shortcut:**
- Clicking directly into a glowing field (not on Accept/Reject buttons):
  - Counts as accepting the suggestion
  - Places cursor in the field at click position
  - User can immediately edit if minor corrections needed
  - Audit log records as `accepted_and_edited` if value changes before save

### Bottom Row Replacement

**Normal Mode (requires_human_review=False):**
```
[Display Email] [Show Emails] [Send for Review ▼] [Event Status ▼]
```

**Review Mode (requires_human_review=True):**
```
[Jump to Next →]     [████████░░ 6/8 fields reviewed]     [⚠ Human Review Required]
```

**Jump to Next Button:**
- Scrolls to and focuses the next field with orange glow
- Cycles through unreviewed fields in DOM order
- Disabled when no unreviewed fields remain

**Progress Bar:**
- Shows "X/Y fields reviewed"
- Y = total fields in `extracted_fields`
- X = fields where status != "unreviewed"
- Updates in real-time as user reviews fields
- Visual progress bar (filled portion grows)

**Human Review Required Badge:**
- Orange/warning colored badge
- Text: "Human Review Required" or "⚠ Review Required"
- Serves as persistent reminder

### Email Source Highlighting

**On Field Hover:**
1. User hovers mouse over any field in the right pane (form area)
2. If field exists in `extracted_fields` with `source_location`:
   - Email pane smooth-scrolls to `start_index` position
   - Text from `start_index` to `end_index` is highlighted (yellow/orange background)
3. Highlight remains while hovering the field
4. When mouse leaves field:
   - Highlight fades after 500ms delay, OR
   - Highlight remains until user hovers a different extracted field

**Highlight Implementation:**
```javascript
// Wrap email body text in span with data attributes for character positions
// Or calculate position dynamically from text content

function highlightSource(startIndex, endIndex, textSnippet) {
    // Primary: Use character indices
    // Fallback: Search for textSnippet if indices don't match
    
    const emailBody = document.getElementById('email-body');
    // Scroll to position
    // Apply highlight class to text range
}
```

**Fallback Behavior:**
- If text at `start_index:end_index` doesn't match `text_snippet`:
  - Search email body for `text_snippet`
  - Highlight first occurrence
- If `text_snippet` not found:
  - No highlight, no scroll
  - Log warning for debugging

### Locked Features During Review

**Respond Button (Header):**
- Disabled (grayed out, not clickable)
- Tooltip on hover: "Complete human review before responding"

**Staff & Review Tab (Third Tab):**
- Grayed out, not clickable
- Tooltip on hover: "Complete human review to access staff assignment"

**Event Status Dropdown:**
- Not visible (replaced by review UI)
- Cannot be changed until review complete

### Close Modal Behavior

**If Unreviewed Fields Remain:**
1. User clicks X to close modal
2. Confirmation dialog appears:
   ```
   Review Incomplete
   
   This event has unreviewed fields. What would you like to do?
   
   [Discard Event]    [Finish Review Later]
   ```

**Discard Event:**
- Deletes the event entirely
- No audit log needed (event never existed)
- Modal closes

**Finish Review Later:**
- Saves current state of `extracted_fields` (preserves accepted/rejected states)
- Event remains with `requires_human_review=True`
- Event does not appear on calendar
- Modal closes
- User can reopen event later to continue review

**If All Fields Reviewed:**
- Modal closes normally
- No confirmation needed

### Review Completion

**Trigger:** All fields in `extracted_fields` have status != "unreviewed"

**Automatic Actions:**
1. Set `requires_human_review = False`
2. Set event status to "Received" (or appropriate initial status)
3. Remove orange glow from modal border
4. Restore normal bottom row (Display Email, Show Emails, Send for Review, Event Status)
5. Enable Respond button
6. Enable Staff & Review tab
7. Event becomes visible on calendar

**Transition Animation (Optional):**
- Brief success flash or smooth transition
- Progress bar shows "Complete ✓" momentarily

---

## Accept All Function

### Purpose
Accepts all unreviewed fields in a single action. Heavily requested feature but requires additional security review before exposing to users.

### Implementation Status
- **Backend:** Fully implemented
- **Frontend Button:** NOT implemented (no UI access)
- **Activation:** Future security approval required

### Backend Specification

```python
# event_management/services/review_service.py

def accept_all_fields(event: Event, user: User) -> None:
    """
    Accept all unreviewed fields in extracted_fields.
    
    Creates audit log entries with action='accepted_all' for each field.
    Sets status to 'accepted_all' (distinct from 'accepted') for compliance tracking.
    
    WARNING: This function exists for future use pending security approval.
    Do not expose via UI without authorization.
    """
    if not event.requires_human_review:
        return
    
    extracted = event.extracted_fields.copy()
    now = timezone.now().isoformat()
    
    for field_name, field_data in extracted.items():
        if field_data.get('status') == 'unreviewed':
            # Update field status
            field_data['status'] = 'accepted_all'
            field_data['reviewed_by'] = str(user.id)
            field_data['reviewed_at'] = now
            
            # Create audit log
            EventReviewAuditLog.objects.create(
                event=event,
                field_name=field_name,
                action='accepted_all',
                original_value=field_data.get('original_value', ''),
                new_value=None,
                user=user
            )
    
    event.extracted_fields = extracted
    event.requires_human_review = False
    event.status = 'received'
    event.save()
```

### Audit Trail
- Action recorded as `accepted_all` (not `accepted`)
- Status in JSON is `accepted_all` (not `accepted`)
- Allows compliance auditors to identify bulk-accepted fields
- Distinguishes from individual field review

### Future UI (Post-Approval)
When approved, add button to review mode bottom row:
```
[Accept All]  [Jump to Next →]  [████░░ 3/8 reviewed]  [⚠ Review Required]
```

---

## Extraction Service Updates

### Prompt Modification
Update LLM extraction prompt to return source locations:

```
For each field you extract, provide:
1. The extracted value
2. The exact text from the email that you based this extraction on
3. The character position (start and end index) of that text in the email body

Return in this format for each field:
{
    "value": "extracted value",
    "source_text": "exact text from email",
    "start_index": 1234,
    "end_index": 1256
}
```

### Extraction Service Changes

```python
# email_processing/extraction_service.py

def extract_event_from_email(email_body: str, email_subject: str) -> dict:
    """
    Extract event fields from email with source locations.
    """
    # ... existing extraction logic ...
    
    # Parse LLM response to build extracted_fields dict
    extracted_fields = {}
    
    for field_name, extraction in llm_response.items():
        extracted_fields[field_name] = {
            'original_value': extraction['value'],
            'status': 'unreviewed',
            'reviewed_by': None,
            'reviewed_at': None,
            'source_location': {
                'start_index': extraction['start_index'],
                'end_index': extraction['end_index'],
                'text_snippet': extraction['source_text']
            }
        }
    
    return extracted_fields
```

### Source Location Verification
After extraction, verify that `text_snippet` matches text at indices:

```python
def verify_source_locations(email_body: str, extracted_fields: dict) -> dict:
    """
    Verify and correct source locations if needed.
    """
    for field_name, field_data in extracted_fields.items():
        loc = field_data.get('source_location', {})
        if not loc:
            continue
            
        start = loc.get('start_index', 0)
        end = loc.get('end_index', 0)
        snippet = loc.get('text_snippet', '')
        
        actual_text = email_body[start:end]
        
        if actual_text != snippet:
            # Indices don't match, try to find snippet
            found_index = email_body.find(snippet)
            if found_index != -1:
                loc['start_index'] = found_index
                loc['end_index'] = found_index + len(snippet)
            else:
                # Cannot locate, remove source_location
                field_data['source_location'] = None
    
    return extracted_fields
```

---

## API Endpoints

### Review Field Endpoint

```
POST /api/events/{event_id}/review-field/

Request Body:
{
    "field_name": "title",
    "action": "accepted" | "rejected" | "accepted_and_edited",
    "new_value": "corrected value"  // Required for rejected/edited
}

Response:
{
    "success": true,
    "extracted_fields": { ... updated fields ... },
    "review_complete": false,
    "fields_remaining": 3
}
```

### Accept All Endpoint (Hidden)

```
POST /api/events/{event_id}/accept-all/

Request Body: {}

Response:
{
    "success": true,
    "fields_accepted": 5,
    "review_complete": true
}

Note: Endpoint exists but should not be called from frontend until security approval.
Consider adding feature flag or permission check.
```

### Get Review Status Endpoint

```
GET /api/events/{event_id}/review-status/

Response:
{
    "requires_human_review": true,
    "total_fields": 8,
    "reviewed_fields": 5,
    "unreviewed_fields": ["end_time", "description", "attendees"],
    "extracted_fields": { ... full extracted_fields dict ... }
}
```

---

## Frontend Components

### New Components

1. **ReviewModeModal** - Wrapper that adds orange glow and review state management
2. **ReviewableField** - Input field with Accept/Reject controls and glow state
3. **ReviewProgressBar** - Shows X/Y fields reviewed with visual bar
4. **ReviewBottomRow** - Jump to Next + Progress Bar + Badge
5. **EmailHighlighter** - Manages email pane highlighting on field hover
6. **ReviewConfirmDialog** - "Discard Event" / "Finish Review Later" dialog

### State Management

```javascript
// Review state for an event
const reviewState = {
    eventId: 'uuid',
    requiresReview: true,
    extractedFields: { ... },
    totalFields: 8,
    reviewedCount: 5,
    currentHighlight: null,  // field name currently being highlighted in email
};

// Actions
function acceptField(fieldName) { ... }
function rejectField(fieldName) { ... }
function acceptAndEdit(fieldName) { ... }
function jumpToNext() { ... }
function highlightSource(fieldName) { ... }
function clearHighlight() { ... }
```

---

## Calendar Integration

### Visibility Rules
- Events with `requires_human_review=True` do NOT appear on calendar
- Events appear on calendar only after review completion
- Filter "Needs Review" in sidebar shows count but clicking opens list view, not calendar

### Event List/Queue View
Consider adding a dedicated "Needs Review" queue:
- Lists all events with `requires_human_review=True`
- Sorted by creation date (oldest first)
- Click to open review modal
- Badge count in navigation

---

## Migration

### Database Migration

```python
# event_management/migrations/XXXX_add_human_review_fields.py

from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('event_management', 'previous_migration'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='requires_human_review',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='event',
            name='extracted_fields',
            field=models.JSONField(default=dict, blank=True),
        ),
        migrations.CreateModel(
            name='EventReviewAuditLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ('field_name', models.CharField(max_length=100)),
                ('action', models.CharField(max_length=50)),
                ('original_value', models.TextField(blank=True)),
                ('new_value', models.TextField(blank=True, null=True)),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('event', models.ForeignKey(on_delete=models.CASCADE, related_name='review_audit_logs', to='event_management.event')),
                ('user', models.ForeignKey(null=True, on_delete=models.SET_NULL, to='authentication.user')),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='eventreviewauditlog',
            index=models.Index(fields=['event', 'timestamp'], name='event_review_audit_idx'),
        ),
    ]
```

---

## Testing Requirements

### Unit Tests

1. **Model Tests:**
   - Event with `requires_human_review=True` created correctly
   - `extracted_fields` JSON validates correctly
   - `EventReviewAuditLog` created on field review

2. **Service Tests:**
   - `accept_field()` updates status and creates audit log
   - `reject_field()` clears value and creates audit log
   - `accept_all_fields()` processes all unreviewed fields
   - Review completion triggers status change

3. **API Tests:**
   - Review field endpoint validates input
   - Cannot review non-existent field
   - Cannot review already-reviewed field (or can re-review?)
   - Accept all endpoint functions correctly

### Integration Tests

1. **Email Extraction Flow:**
   - Email received → Event created with `requires_human_review=True`
   - `extracted_fields` populated with source locations

2. **Review Flow:**
   - Open event modal → Review mode active
   - Accept field → Status updates, glow removed
   - Reject field → Value cleared, glow removed
   - All fields reviewed → Event unlocked, appears on calendar

3. **Partial Review:**
   - Review some fields → Close modal → "Finish Review Later"
   - Reopen event → Previous progress preserved

### E2E Tests (Playwright)

1. **Visual Tests:**
   - Modal has orange glow in review mode
   - Fields have orange glow when unreviewed
   - Glow removed after accept/reject
   - Progress bar updates correctly

2. **Interaction Tests:**
   - Click Accept → Field accepted
   - Click Reject → Field cleared
   - Click into field → Accept + cursor placed
   - Hover field → Email highlights correct text
   - Jump to Next → Scrolls to next unreviewed field

3. **Lock Tests:**
   - Respond button disabled during review
   - Staff tab disabled during review
   - Both enabled after review complete

---

## Implementation Order

### Phase 1: Backend Foundation
1. Add `requires_human_review` and `extracted_fields` to Event model
2. Create `EventReviewAuditLog` model
3. Run migrations
4. Create review service with accept/reject/accept_all functions
5. Create API endpoints
6. Update extraction service to return source locations

### Phase 2: Frontend Components
1. Create ReviewableField component with glow states
2. Create Accept/Reject popover controls
3. Create ReviewProgressBar component
4. Create ReviewBottomRow component
5. Create ReviewConfirmDialog component

### Phase 3: Modal Integration
1. Add review mode detection to event modal
2. Add orange glow to modal in review mode
3. Replace bottom row in review mode
4. Implement locked features (disabled buttons, grayed tabs)
5. Implement close confirmation dialog

### Phase 4: Email Highlighting
1. Update email pane to support character-position scrolling
2. Implement text range highlighting
3. Add hover handlers to ReviewableField
4. Implement highlight-on-hover with scroll

### Phase 5: Polish & Testing
1. Add animations/transitions
2. Write unit tests
3. Write integration tests
4. Write E2E tests with Playwright
5. Manual QA testing

---

## Open Questions

1. **Re-review:** Can a user change an accepted field to rejected (or vice versa)? Or is review final?
   - Recommendation: Allow re-review, creates new audit log entry

2. **Partial save:** Should field values save immediately on accept/reject, or only on modal close?
   - Recommendation: Save immediately for data safety

3. **Multiple reviewers:** Can different users review different fields on the same event?
   - Recommendation: Yes, each field tracks its own reviewer

4. **Review queue priority:** How should events needing review be prioritized?
   - Recommendation: FIFO by creation date, with option to sort by meeting date

---

## Appendix: CSS Classes

```css
/* Modal glow in review mode */
.modal--review-mode {
    box-shadow: 0 0 20px 5px rgba(255, 165, 0, 0.5);
}

/* Field states */
.field--unreviewed {
    box-shadow: 0 0 8px 2px rgba(255, 165, 0, 0.6);
    outline: 2px solid orange;
}

.field--normal {
    box-shadow: none;
    outline: none;
}

/* Email highlight */
.email-highlight {
    background-color: rgba(255, 200, 0, 0.4);
    transition: background-color 0.3s ease;
}

/* Progress bar */
.review-progress {
    height: 8px;
    background: #e0e0e0;
    border-radius: 4px;
}

.review-progress__fill {
    height: 100%;
    background: #4caf50;
    border-radius: 4px;
    transition: width 0.3s ease;
}

/* Badge */
.review-badge {
    background: #ff9800;
    color: white;
    padding: 4px 12px;
    border-radius: 4px;
    font-weight: 600;
}

/* Disabled states */
.btn--disabled-review {
    opacity: 0.5;
    cursor: not-allowed;
}

.tab--disabled-review {
    opacity: 0.5;
    pointer-events: none;
}
```
