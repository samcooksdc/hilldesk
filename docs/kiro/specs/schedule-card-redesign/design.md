# Schedule Card Redesign Design Document

## Overview

This document outlines the design for redesigning the schedule view event cards to match a compact, professional layout that maximizes information density while maintaining excellent usability.

## Architecture

### Component Structure

```
ScheduleView
├── SearchAndFilters
├── EventCardList
│   └── EventCard (repeated)
│       ├── EventIcon
│       ├── EventContent
│       │   ├── EventTitle
│       │   ├── EventDateTime  
│       │   └── EventLocation
│       ├── StatusBadge
│       └── ParticipantTags
└── Pagination
```

### Event Card Layout

The event card will use CSS Grid for precise layout control:

```css
.event-card {
  display: grid;
  grid-template-columns: 40px 1fr auto auto;
  grid-template-areas: 
    "icon content status participants";
  gap: 12px;
  padding: 16px;
  height: 88px;
}
```

## Components and Interfaces

### EventCard Component

**Props:**
- `event`: Event object with all event data
- `onStatusChange`: Function to handle status updates
- `onCardClick`: Function to handle card clicks
- `className`: Optional additional CSS classes

**State:**
- `isHovered`: Boolean for hover effects
- `showStatusDropdown`: Boolean for status dropdown visibility

### EventIcon Component

**Props:**
- `eventType`: String ('meeting', 'event', 'speaking')
- `size`: Number (default: 24)

**Icon Mapping:**
- Meeting: Users/conference icon
- Event: Calendar icon  
- Speaking: Microphone icon

### StatusBadge Component

**Props:**
- `status`: Current event status
- `onStatusChange`: Callback for status changes
- `editable`: Boolean to enable/disable editing

**Status Color Mapping:**
- Scheduled: Green (#10b981)
- Received: Gray (#6b7280)
- Hold: Orange (#f59e0b)
- Requires HMS Review: Blue (#3b82f6)

### ParticipantTags Component

**Props:**
- `participants`: Array of participant objects
- `pointOfContact`: Primary contact object
- `maxVisible`: Number of tags to show (default: 3)

## Data Models

### Event Card Data Structure

```typescript
interface EventCardData {
  id: string;
  type: 'meeting' | 'event' | 'speaking';
  title: string;
  startDate: Date;
  endDate?: Date;
  time: string;
  location: string;
  status: EventStatus;
  participants: Participant[];
  pointOfContact: Contact;
  group: string;
}

interface Participant {
  name: string;
  role?: string;
  type: 'staff' | 'external' | 'contact';
}

interface Contact {
  name: string;
  email: string;
  phone?: string;
}
```

## Error Handling

### Missing Data Handling
- Missing location: Show "TBD" in muted text
- Missing time: Show "TBD" in muted text
- Missing participants: Hide participant section
- Missing contact: Show generic "Contact TBD"

### Status Update Errors
- Show inline error message below status badge
- Revert to previous status on failure
- Provide retry mechanism

## Testing Strategy

### Unit Tests
- EventCard component rendering with various props
- StatusBadge dropdown functionality
- ParticipantTags overflow handling
- EventIcon type mapping

### Integration Tests
- Event card click navigation
- Status update workflow
- Responsive behavior at different breakpoints
- Accessibility compliance (keyboard navigation, screen readers)

### Visual Regression Tests
- Card layout consistency across different event types
- Status badge color accuracy
- Hover and focus states
- Mobile responsive layout

## Implementation Plan

### Phase 1: Core Card Structure
1. Create new EventCard component
2. Implement basic grid layout
3. Add EventIcon component
4. Style basic card appearance

### Phase 2: Status and Interactions
1. Implement StatusBadge with dropdown
2. Add hover and click interactions
3. Integrate with existing event update APIs
4. Add loading and error states

### Phase 3: Participants and Polish
1. Create ParticipantTags component
2. Implement overflow handling
3. Add tooltips and accessibility features
4. Responsive design refinements

### Phase 4: Integration and Testing
1. Replace existing schedule list with new cards
2. Comprehensive testing across devices
3. Performance optimization
4. User acceptance testing

## CSS Architecture

### Card Base Styles
```css
.event-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  transition: all var(--transition-fast);
  cursor: pointer;
}

.event-card:hover {
  border-color: var(--accent-color);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
```

### Responsive Breakpoints
- Desktop: Full horizontal layout
- Tablet (768px): Maintain horizontal, allow tag wrapping
- Mobile (480px): Stack content vertically

### Dark Mode Support
All components will respect the existing theme system with proper color variables for both light and dark modes.

## Performance Considerations

### Virtualization
For large event lists (>100 items), implement virtual scrolling to maintain performance.

### Lazy Loading
Load participant details and additional metadata only when needed.

### Memoization
Use React.memo for EventCard components to prevent unnecessary re-renders.

## Accessibility

### Keyboard Navigation
- Tab through cards in logical order
- Enter/Space to open event details
- Arrow keys for status dropdown navigation

### Screen Reader Support
- Proper ARIA labels for all interactive elements
- Semantic HTML structure
- Status announcements for dynamic updates

### Color Contrast
All status colors and text combinations meet WCAG AA standards for contrast ratios.