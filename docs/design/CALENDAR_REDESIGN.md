# HillDesk Calendar View Redesign

## Overview

Redesign the calendar view UI to improve usability and make event status the primary visual element. This is a **frontend-only change** that must integrate with the existing event management system and use existing event data.

---

## Critical Constraint

**This redesign MUST integrate with the existing event management system.**

- Use existing Event model and queryset methods
- Use existing event data fields (status, category, location, assigned_staff, etc.)
- Use existing API endpoints for fetching events
- When an event is clicked on the calendar, launch the **existing event editing modal** — do not create a new modal

---

## Requirements

### Layout

1. Two-panel layout: scrollable filter sidebar on left, calendar view on right
2. Filter sidebar fixed width (~220px), scrolls independently
3. Calendar area fills remaining width
4. Header bar with navigation controls and view mode toggle

### Header Bar

1. Navigation: `< Today >` arrows to move between periods
2. Current period label (e.g., "January 2026")
3. View mode toggle: Day | Week | Month | Agenda
4. Views switch without page reload

### Filter Sidebar (Left Panel)

1. Scrollable container
2. Collapsible accordion sections
3. Filters apply immediately on check/uncheck (no "Apply" button)
4. `[Clear All]` button at bottom
5. Filter sections in this order (top to bottom):
   - **Status** (Confirmed, Tentative, Pending, Cancelled)
   - **Review State** (All, Needs Review, Approved)
   - **Category** (populated from existing event categories)
   - **Location** (DC, District, Virtual)
   - **Staff** (populated from existing staff/users)
   - **Source** (All, From Email, Manual)

### Calendar Views

#### Week View (Default)
1. 7-day horizontal grid with time slots on vertical axis
2. Overlapping events display **side by side** (like Outlook), not stacked
3. Events show: status badge, title, time, location (if space)
4. Scrollable time range

#### Day View
1. Single day with hourly time slots
2. Overlapping events display side by side
3. More detail visible per event than week view

#### Month View
1. Traditional calendar grid
2. Compact event chips showing status badge and truncated title
3. `+N more` indicator when events exceed visible space
4. Click on date switches to day view for that date

#### Agenda View
1. Chronological list grouped by day
2. Each row shows: status badge, time, title, location
3. Scrollable list of upcoming events

### Event Display

1. **Status is the primary visual element**
   - Status badge at top of event card
   - Left border color indicates status
   - No hardcoded colors for categories
2. Status visual treatments:
   - Confirmed: solid border
   - Tentative: dashed border
   - Pending: dotted border
   - Cancelled: solid border + strikethrough text
3. Review state indicator:
   - Events needing review show `⚠ Needs Review` badge
4. Event card content (space permitting):
   - Status badge
   - Title
   - Time
   - Location
   - Review warning (if applicable)
5. Email source indicator: `✉` icon for events created from email

### Event Interaction

1. Hover: subtle highlight effect
2. Click: **launch existing event editing modal**
3. Do not create a new modal — use the existing one from event_management

### Overlapping Events

1. Display side by side in the same time slot
2. Each event takes equal width
3. No conflict warnings, suggestions, or notifications — just display them

### Responsive Behavior

1. Filter sidebar collapsible on smaller screens
2. Calendar adjusts to available width

---

## Tasks

### Layout & Structure
- [ ] Create two-panel layout with filter sidebar and calendar area
- [ ] Implement fixed-width scrollable filter sidebar
- [ ] Add header bar with navigation and view toggle

### Filter Sidebar
- [ ] Create collapsible accordion component for filter sections
- [ ] Implement Status filter (checkboxes)
- [ ] Implement Review State filter (checkboxes)
- [ ] Implement Category filter (populate from existing categories)
- [ ] Implement Location filter (checkboxes)
- [ ] Implement Staff filter (populate from existing users)
- [ ] Implement Source filter (checkboxes)
- [ ] Add Clear All button
- [ ] Wire filters to calendar query/display

### Week View
- [ ] Create 7-day grid layout with time axis
- [ ] Render events in correct time slots
- [ ] Implement side-by-side display for overlapping events
- [ ] Style event cards with status as primary element

### Day View
- [ ] Create single-day layout with hourly slots
- [ ] Render events with side-by-side overlap handling
- [ ] Show expanded event details

### Month View
- [ ] Create calendar grid layout
- [ ] Render compact event chips with status badge
- [ ] Implement `+N more` overflow indicator
- [ ] Add click-to-day-view functionality

### Agenda View
- [ ] Create chronological list layout grouped by day
- [ ] Render event rows with status badge, time, title, location

### Event Cards
- [ ] Design status-first event card component
- [ ] Implement status-based border styling (solid/dashed/dotted)
- [ ] Add review state warning badge
- [ ] Add email source indicator

### Event Interaction
- [ ] Add hover effects
- [ ] Wire click handler to launch existing event editing modal

### Navigation
- [ ] Implement previous/next period navigation
- [ ] Implement "Today" button
- [ ] Implement view mode switching (Day/Week/Month/Agenda)
- [ ] Preserve filter state across navigation

### Integration
- [ ] Connect to existing event management API/queryset
- [ ] Ensure existing event editing modal works when launched from calendar
- [ ] Verify all existing event fields display correctly

---

## Out of Scope

- Backend changes
- New event creation flow
- New event editing modal
- Conflict resolution or suggestions
- Notifications for overlaps
- Alternative time suggestions
- Outlook sync UI
- Mobile-specific views

---

## Notes

- All event data comes from the existing Event model
- All filtering should use existing querysets or API endpoints
- The event editing modal already exists — reuse it exactly as-is
- Status values and categories should be pulled from existing model choices, not hardcoded
