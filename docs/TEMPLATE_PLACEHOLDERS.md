# HillDesk Export Template Placeholders

This document lists every placeholder available in HillDesk Word (.docx) export templates. Use `{{ placeholder_name }}` syntax in your custom templates.

---

## How Templates Work

HillDesk uses **docxtpl** (Jinja2 for Word) to fill in your `.docx` templates at export time. Place placeholders like `{{ event.title }}` anywhere in your document and they will be replaced with real data when you export.

### Loops (repeating rows)

To repeat a table row for each event, use:

```
{%tr for event in events %}
  {{ event.title }}  |  {{ event.time_display }}  |  ...
{%tr endfor %}
```

To repeat a paragraph section:

```
{%p for day in days %}
  {{ day.label }}
{%p endfor %}
```

---

## Common Fields (All Templates)

| Placeholder | Description | Example |
|---|---|---|
| `{{ office_name }}` | Office name | Office of Rep. Smith |
| `{{ member_name }}` | Member's name | Rep. James Smith |
| `{{ generated_at }}` | Timestamp when the export was generated | February 26, 2026 03:45 PM |
| `{{ event_count }}` | Total number of events in this export | 12 |

---

## Single Event Fields

Used inside `{{ event.field_name }}` when iterating over events, or directly as `{{ event.field_name }}` in the Event Detail template.

### Basic Information

| Placeholder | Description | Example |
|---|---|---|
| `{{ event.title }}` | Event title | Budget Committee Hearing |
| `{{ event.type }}` | Event type (raw value) | meeting |
| `{{ event.type_display }}` | Event type (display label) | Meeting |
| `{{ event.format }}` | Event format | In-Person |
| `{{ event.duration }}` | Duration | 1 hour |
| `{{ event.group }}` | Requesting organization | National Education Association |
| `{{ event.status }}` | Status (raw value) | confirmed |
| `{{ event.status_display }}` | Status (display label from office settings) | Confirmed |

### Date & Time

| Placeholder | Description | Example |
|---|---|---|
| `{{ event.start_date }}` | Start date (ISO) | 2026-03-15 |
| `{{ event.start_date_formatted }}` | Start date (long) | March 15, 2026 |
| `{{ event.start_date_short }}` | Start date (short) | 03/15/2026 |
| `{{ event.start_time }}` | Start time (24h) | 14:00:00 |
| `{{ event.start_time_formatted }}` | Start time (12h) | 2:00 PM |
| `{{ event.end_time }}` | End time (24h) | 15:30:00 |
| `{{ event.end_time_formatted }}` | End time (12h) | 3:30 PM |
| `{{ event.time_display }}` | Combined time range | 2:00 PM - 3:30 PM |
| `{{ event.end_date }}` | End date (ISO) | 2026-03-15 |
| `{{ event.end_date_formatted }}` | End date (long) | March 15, 2026 |

### Location & Contact

| Placeholder | Description | Example |
|---|---|---|
| `{{ event.location }}` | Event location | 2251 Rayburn HOB |
| `{{ event.point_of_contact_name }}` | POC name | Jane Smith |
| `{{ event.point_of_contact_email }}` | POC email | jane@example.com |
| `{{ event.point_of_contact_phone }}` | POC phone | (202) 555-0100 |

### Staff & Tags

| Placeholder | Description | Example |
|---|---|---|
| `{{ event.staff_csv }}` | Staff names (comma-separated) | Jane Doe, John Smith |
| `{{ event.tags_csv }}` | Tags (comma-separated) | healthcare, appropriations |
| `{{ event.staff_list }}` | Staff as list of dicts (for loops) | — |

To loop over staff individually:
```
{%p for person in event.staff_list %}
  {{ person.name }}
{%p endfor %}
```

### Content

| Placeholder | Description | Example |
|---|---|---|
| `{{ event.description }}` | Full description | Committee hearing on FY2027 budget... |
| `{{ event.notes }}` | Full notes | Member should review briefing packet... |
| `{{ event.notes_short }}` | Notes (first 200 characters) | Member should review briefing... |

---

## Daily Briefing Template

| Placeholder | Description |
|---|---|
| `{{ date_formatted }}` | The briefing date (e.g., "March 15, 2026") |
| `{{ date_short }}` | Short date (e.g., "03/15/2026") |
| `{{ events }}` | List of events — iterate with `{%tr for event in events %}` |

---

## Weekly Overview Template

| Placeholder | Description |
|---|---|
| `{{ date_range }}` | Week range (e.g., "March 09 - March 15, 2026") |
| `{{ day_count }}` | Number of days with events |
| `{{ days }}` | List of day objects — iterate with `{%p for day in days %}` |

### Day Object Fields

| Placeholder | Description | Example |
|---|---|---|
| `{{ day.label }}` | Day label | Monday, March 09 |
| `{{ day.date }}` | Date (short) | 03/09/2026 |
| `{{ day.event_count }}` | Events on this day | 3 |
| `{{ day.events }}` | Events list for this day | — |

---

## Event Detail Template

Uses `{{ event.field }}` directly (not inside a loop). Also includes:

| Placeholder | Description |
|---|---|
| `{{ source_email.sender }}` | Original email sender |
| `{{ source_email.subject }}` | Original email subject |
| `{{ source_email.date }}` | When the email was received |
| `{{ source_email.body_snippet }}` | First 500 characters of the email body |

### Routing Trail

Iterate with `{%tr for step in routing_trail %}`:

| Placeholder | Description | Example |
|---|---|---|
| `{{ step.who }}` | Approver name | Jane Doe |
| `{{ step.action }}` | What they did | Approved |
| `{{ step.when }}` | When they acted | 03/15/2026 10:30 AM |

---

## Filtered List Template

| Placeholder | Description |
|---|---|
| `{{ active_filters_display }}` | Human-readable filter summary (e.g., "Status: Confirmed, Type: Meeting") |
| `{{ active_filters }}` | List of filter strings (for loops) |
| `{{ events }}` | List of events — iterate with `{%tr for event in events %}` |

---

## Tips for Creating Custom Templates

1. **Start from a built-in template** — Download one from HillDesk and modify it
2. **Use Table Grid style** — Table rows with `{%tr for %}` loops work best with grid borders
3. **Keep placeholders on one line** — Don't split `{{ event.title }}` across multiple text runs in Word
4. **Test before deploying** — Upload validates the template with sample data automatically
5. **Use conditional sections** — `{% if event.notes %}{{ event.notes }}{% endif %}`
