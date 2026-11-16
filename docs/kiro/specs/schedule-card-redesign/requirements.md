# Schedule Card Redesign Requirements

## Introduction

This specification defines the requirements for redesigning the schedule view event cards to match a compact, professional layout with improved visual hierarchy and information density.

## Requirements

### Requirement 1: Compact Event Card Layout

**User Story:** As a congressional scheduler, I want to see events in a compact card format so that I can quickly scan multiple events on one screen.

#### Acceptance Criteria

1. WHEN viewing the schedule page THEN each event SHALL be displayed as a compact horizontal card
2. WHEN an event card is displayed THEN it SHALL show an appropriate icon based on event type (meeting, event, speaking)
3. WHEN an event card is displayed THEN it SHALL show the event title prominently
4. WHEN an event card is displayed THEN it SHALL show the date and time in a consistent format
5. WHEN an event card is displayed THEN it SHALL show the location information
6. WHEN an event card is displayed THEN the card height SHALL be approximately 80-100px for optimal density

### Requirement 2: Status Badge Integration

**User Story:** As a congressional scheduler, I want to see event status at a glance so that I can quickly identify which events need attention.

#### Acceptance Criteria

1. WHEN an event card is displayed THEN it SHALL show a status badge with appropriate color coding
2. WHEN the status is "Scheduled" THEN the badge SHALL be green
3. WHEN the status is "Received" THEN the badge SHALL be gray
4. WHEN the status is "Hold" THEN the badge SHALL be yellow/orange
5. WHEN the status is "Requires HMS Review" THEN the badge SHALL be blue
6. WHEN clicking on a status badge THEN it SHALL show a dropdown to change the status

### Requirement 3: Participant and Contact Tags

**User Story:** As a congressional scheduler, I want to see key participants and contacts for each event so that I can quickly identify stakeholders.

#### Acceptance Criteria

1. WHEN an event card is displayed THEN it SHALL show participant tags on the right side
2. WHEN participant tags are shown THEN they SHALL be displayed as small, rounded badges
3. WHEN there are multiple participants THEN only the first 2-3 SHALL be shown with a "+X more" indicator if needed
4. WHEN a participant tag is clicked THEN it SHALL show more details about that participant
5. WHEN the point of contact is available THEN it SHALL be highlighted differently from other participants

### Requirement 4: Event Type Icons

**User Story:** As a congressional scheduler, I want to quickly identify event types through visual icons so that I can categorize events at a glance.

#### Acceptance Criteria

1. WHEN an event type is "meeting" THEN it SHALL display a meeting/conference icon
2. WHEN an event type is "event" THEN it SHALL display a calendar/event icon  
3. WHEN an event type is "speaking" THEN it SHALL display a microphone/podium icon
4. WHEN an icon is displayed THEN it SHALL be 24x24px and positioned on the left side of the card
5. WHEN an icon is displayed THEN it SHALL use the current theme's accent color

### Requirement 5: Responsive Card Design

**User Story:** As a congressional scheduler, I want the event cards to work well on different screen sizes so that I can use the system on various devices.

#### Acceptance Criteria

1. WHEN viewing on desktop THEN cards SHALL display all information in a single row
2. WHEN viewing on tablet THEN participant tags MAY wrap to a second line if needed
3. WHEN viewing on mobile THEN cards SHALL stack information vertically while maintaining readability
4. WHEN the screen width is reduced THEN less important information SHALL be hidden gracefully
5. WHEN hovering over a card THEN it SHALL show a subtle elevation effect

### Requirement 6: Date and Time Formatting

**User Story:** As a congressional scheduler, I want consistent date and time formatting so that I can quickly understand scheduling information.

#### Acceptance Criteria

1. WHEN displaying dates THEN they SHALL use the format "MM/DD/YYYY"
2. WHEN displaying times THEN they SHALL use 12-hour format with AM/PM
3. WHEN an event spans multiple hours THEN it SHALL show "START_TIME - END_TIME"
4. WHEN an event is all-day THEN it SHALL show "All Day"
5. WHEN time is TBD THEN it SHALL show "TBD" in a muted color

### Requirement 7: Location Display

**User Story:** As a congressional scheduler, I want to see event locations clearly so that I can understand logistical requirements.

#### Acceptance Criteria

1. WHEN a location is specified THEN it SHALL be displayed below the event title
2. WHEN a location is "TBD" THEN it SHALL be shown in a muted color
3. WHEN a location is very long THEN it SHALL be truncated with ellipsis
4. WHEN hovering over a truncated location THEN it SHALL show the full location in a tooltip
5. WHEN a location includes a room number THEN it SHALL be formatted consistently

### Requirement 8: Card Actions and Interactions

**User Story:** As a congressional scheduler, I want to perform quick actions on events so that I can efficiently manage my schedule.

#### Acceptance Criteria

1. WHEN clicking on an event card THEN it SHALL open the event detail modal
2. WHEN right-clicking on an event card THEN it SHALL show a context menu with quick actions
3. WHEN hovering over an event card THEN it SHALL show a subtle highlight effect
4. WHEN an event requires attention THEN the card SHALL have a subtle visual indicator
5. WHEN an event is overdue THEN it SHALL have a distinct visual treatment