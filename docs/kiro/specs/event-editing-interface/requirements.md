# Requirements Document

## Introduction

This feature creates a comprehensive event editing interface that opens when a card is selected in the "Schedule" page. The interface consists of a split-panel design with an email viewer on the left and a detailed event editing panel on the right. The system supports both standard editing mode and an AI-assisted "SmartExtract" review mode where users can review and approve AI-generated suggestions before finalizing events.

## Requirements

### Requirement 1

**User Story:** As a congressional scheduler, I want to open an event editing interface when I select a schedule card, so that I can view related emails and edit event details in a unified interface.

#### Acceptance Criteria

1. WHEN a user clicks on a schedule card THEN the system SHALL open a right-sliding panel overlay
2. WHEN the panel opens THEN it SHALL occupy approximately one-third of the viewport width
3. WHEN the panel opens THEN it SHALL extend from below the browser toolbar to 80% of window height
4. WHEN the panel opens THEN it SHALL display with rounded corners, subtle drop-shadow, and light border
5. WHEN the panel opens THEN the left side SHALL show an email viewer pane occupying 60% of viewport width

### Requirement 2

**User Story:** As a congressional scheduler, I want to view related emails in a dedicated pane, so that I can reference email content while editing event details.

#### Acceptance Criteria

1. WHEN the email viewer loads THEN it SHALL display a top toolbar with "Respond" and "Open in Outlook" buttons
2. WHEN the email viewer loads THEN it SHALL include a search field in the toolbar
3. WHEN the email viewer loads THEN it SHALL show a scrollable list of email cards below the toolbar
4. WHEN a user hovers over an email card THEN it SHALL highlight with pale grey background
5. WHEN email content exceeds card height THEN it SHALL be clipped with bottom fade indicator
6. WHEN a user scrolls the email list THEN cards SHALL slide under the fixed toolbar
7. WHEN a user clicks on an email card THEN it SHALL expand to show the full HTML content of the email
8. WHEN displaying HTML email content THEN it SHALL render safely with proper sanitization to prevent XSS attacks
9. WHEN HTML email content is displayed THEN it SHALL maintain responsive layout within the email viewer pane
10. WHEN viewing HTML email content THEN external images SHALL be blocked by default with an option to load them

### Requirement 3

**User Story:** As a congressional scheduler, I want to edit event details in a structured form, so that I can maintain consistent event information.

#### Acceptance Criteria

1. WHEN the event panel opens THEN it SHALL display event title and subtitle in the header
2. WHEN the event panel opens THEN it SHALL include a close button (×) in the top-right corner
3. WHEN the event panel opens THEN it SHALL show time range controls with date and time pickers
4. WHEN the event panel opens THEN it SHALL include a "Longer Than a Day" checkbox option
5. WHEN the event panel opens THEN it SHALL provide timezone selection dropdown
6. WHEN the event panel opens THEN it SHALL display three tabs: Event Details, Involved Parties, Staff & Review

### Requirement 4

**User Story:** As a congressional scheduler, I want to manage event details through the Event Details tab, so that I can specify location, type, format, and other event attributes.

#### Acceptance Criteria

1. WHEN Event Details tab is active THEN it SHALL display a location input field with location pin icon
2. WHEN Event Details tab is active THEN it SHALL show three dropdown fields: Event Type, Format, and Duration
3. WHEN Event Details tab is active THEN it SHALL include an event tags section with add/remove functionality
4. WHEN Event Details tab is active THEN it SHALL provide a multi-line event description textarea
5. WHEN Event Details tab is active THEN it SHALL include a notes section for additional comments

### Requirement 5

**User Story:** As a congressional scheduler, I want to manage involved parties through the Involved Parties tab, so that I can track organizations, contacts, and attendees.

#### Acceptance Criteria

1. WHEN Involved Parties tab is active THEN it SHALL display an organization/group input field
2. WHEN Involved Parties tab is active THEN it SHALL show side-by-side Point of Contact and Expected Attendees fields
3. WHEN Involved Parties tab is active THEN it SHALL include a POC contact information textarea
4. WHEN Involved Parties tab is active THEN it SHALL provide assigned staff management with add/remove functionality
5. WHEN Involved Parties tab is active THEN it SHALL include a reminder icon for scheduling alerts
6. WHEN Involved Parties tab is active THEN it SHALL display a notes section

### Requirement 6

**User Story:** As a congressional scheduler, I want to manage staff assignments and reviews through the Staff & Review tab, so that I can track who is involved and approval status.

#### Acceptance Criteria

1. WHEN Staff & Review tab is active THEN it SHALL display assigned staff with pill-shaped tags and add/remove functionality
2. WHEN Staff & Review tab is active THEN it SHALL show a review table with reviewer avatars and names
3. WHEN Staff & Review tab is active THEN it SHALL display review status badges (Approved, Pending, etc.) with timestamps
4. WHEN Staff & Review tab is active THEN it SHALL include a notes section for review comments
5. WHEN Staff & Review tab is active THEN it SHALL maintain proper spacing and grid alignment

### Requirement 7

**User Story:** As a congressional scheduler, I want access to action buttons at the bottom of the panel, so that I can perform common operations without scrolling.

#### Acceptance Criteria

1. WHEN the event panel is open THEN it SHALL display four fixed bottom buttons: Hide Email, Respond, Require Review, Event Status
2. WHEN the event panel is open THEN each button SHALL combine an icon above text label
3. WHEN the event panel is open THEN all buttons SHALL share consistent padding and rounded-corner styling
4. WHEN the event panel is open THEN the action bar SHALL remain fixed during content scrolling
5. WHEN the event panel is open THEN buttons SHALL be equally spaced across the panel width

### Requirement 8

**User Story:** As a congressional scheduler, I want the interface to support both light and dark themes, so that I can work comfortably in different lighting conditions.

#### Acceptance Criteria

1. WHEN the user switches themes THEN all interface elements SHALL adapt to the selected theme colors
2. WHEN the user switches themes THEN text contrast SHALL remain accessible in both modes
3. WHEN the user switches themes THEN borders and shadows SHALL adjust appropriately
4. WHEN the user switches themes THEN form elements SHALL maintain visual consistency
5. WHEN the user switches themes THEN the transition SHALL be smooth and immediate

### Requirement 9

**User Story:** As a congressional scheduler, I want to use AI-assisted event creation with SmartExtract mode, so that I can efficiently review and approve automatically extracted event details.

#### Acceptance Criteria

1. WHEN SmartExtract mode is active THEN AI-suggested fields SHALL display with glowing amber outline
2. WHEN SmartExtract mode is active THEN suggested text SHALL appear in italicized deep maroon font
3. WHEN a user hovers over AI-suggested fields THEN the corresponding email text SHALL highlight with pale yellow
4. WHEN a user hovers over AI-suggested fields THEN a tooltip SHALL show "Suggested from here"
5. WHEN SmartExtract mode is active THEN outbound buttons SHALL show tooltips requiring human review completion

### Requirement 10

**User Story:** As a congressional scheduler, I want to track my review progress in SmartExtract mode, so that I can see how many AI suggestions I've reviewed.

#### Acceptance Criteria

1. WHEN SmartExtract mode is active THEN the event status SHALL show "Human Review Required" in amber
2. WHEN SmartExtract mode is active THEN a "Jump to next →" button SHALL navigate to unreviewed fields
3. WHEN SmartExtract mode is active THEN a progress bar SHALL show reviewed vs total fields (e.g., "1 / 14 fields reviewed")
4. WHEN SmartExtract mode is active THEN outbound actions SHALL be disabled until review completion
5. WHEN SmartExtract mode is active THEN review progress SHALL update as fields are approved

### Requirement 11

**User Story:** As a congressional scheduler, I want responsive behavior across different screen sizes, so that I can use the interface on various devices.

#### Acceptance Criteria

1. WHEN the viewport is smaller THEN the panel SHALL adjust its width proportionally
2. WHEN the viewport is smaller THEN the email viewer SHALL maintain readability
3. WHEN the viewport is smaller THEN form elements SHALL stack appropriately
4. WHEN the viewport is smaller THEN touch targets SHALL remain accessible
5. WHEN the viewport is smaller THEN scrolling SHALL work smoothly on touch devices

### Requirement 12

**User Story:** As a congressional scheduler, I want proper form validation and error handling, so that I can avoid submitting incomplete or invalid event data.

#### Acceptance Criteria

1. WHEN required fields are empty THEN the system SHALL display validation messages
2. WHEN invalid data is entered THEN the system SHALL highlight problematic fields
3. WHEN validation fails THEN the system SHALL prevent form submission
4. WHEN network errors occur THEN the system SHALL display appropriate error messages
5. WHEN validation passes THEN the system SHALL allow normal form submission

### Requirement 13

**User Story:** As a congressional scheduler, I want automatic form saving when I update fields, so that my changes are preserved without manual saving.

#### Acceptance Criteria

1. WHEN a user modifies any form field THEN the system SHALL automatically save changes after 1 second of inactivity
2. WHEN auto-save is triggered THEN the system SHALL display a "Saving..." indicator in the top-right corner
3. WHEN auto-save completes successfully THEN the system SHALL show a "Saved" confirmation message
4. WHEN auto-save fails THEN the system SHALL display an error message with retry option
5. WHEN no changes are detected THEN the system SHALL skip unnecessary save operations
6. WHEN editing a new event THEN auto-save SHALL be disabled until the event is initially created

### Requirement 14

**User Story:** As a congressional scheduler, I want proper scrolling functionality in the event editing panel, so that I can access all form fields regardless of content length.

#### Acceptance Criteria

1. WHEN the form content exceeds the panel height THEN a scrollbar SHALL appear in the content area
2. WHEN scrolling through form content THEN the header and tab navigation SHALL remain fixed
3. WHEN scrolling THEN the scrollbar SHALL be styled consistently with the interface theme
4. WHEN using touch devices THEN scrolling SHALL work smoothly with touch gestures
5. WHEN the content fits within the panel THEN no scrollbar SHALL be displayed

### Requirement 15

**User Story:** As a congressional scheduler, I want to view full HTML email content in an expanded view, so that I can see the complete email formatting and content while editing events.

#### Acceptance Criteria

1. WHEN a user clicks on an email card THEN the email SHALL expand to show full HTML content below the card
2. WHEN HTML email content is displayed THEN it SHALL be properly sanitized to prevent security vulnerabilities
3. WHEN HTML email content is displayed THEN it SHALL maintain proper styling within the email viewer constraints
4. WHEN viewing HTML email content THEN external images SHALL be blocked by default with a "Load Images" button
5. WHEN HTML email content contains attachments THEN they SHALL be listed with download links
6. WHEN a user clicks "Load Images" THEN external images SHALL be displayed in the HTML content
7. WHEN HTML email content is expanded THEN a "Collapse" button SHALL be available to return to card view
8. WHEN multiple emails are expanded THEN only one email SHALL show full content at a time
9. WHEN HTML email content is too wide THEN it SHALL wrap appropriately within the email pane
10. WHEN HTML email content contains complex formatting THEN it SHALL render as closely as possible to the original