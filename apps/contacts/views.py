# SPDX-License-Identifier: Apache-2.0
"""Read-only Contacts / Organizations directory.

A lookup surface over the normalized Contact / Organization data. Because the
sortable/searchable fields (name, email, organization) are encrypted at rest
and therefore not queryable/orderable in SQL, the views decrypt into memory and
sort/filter in Python. This is fine at a House office's scale (hundreds of
records, not millions).

The directory is presented as an inbox-style list-detail layout: the list page
renders every row up front and a small amount of client-side JS handles search,
sort, and selection; clicking a row fetches that record's detail panel HTML from
the ``*_panel`` fragment endpoints below.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.email_processing.models import EmailProcessing

from .models import Contact, EventContact, EventOrganization, Organization


def _primary(addresses, attr):
    """Pick the primary (or first) value from a prefetched child collection."""
    items = list(addresses)
    if not items:
        return ''
    chosen = next((i for i in items if i.is_primary), items[0])
    return getattr(chosen, attr)


def _group_related(emails):
    """Collapse a (-received-ordered) email list into one row per thread.

    The most recent email represents each thread; ``count`` is the full thread
    size (every message in the conversation, which the popup shows together).
    Threadless emails are their own group of one.
    """
    groups, seen = [], set()
    for e in emails:
        tid = e.thread_id
        if tid and tid in seen:
            continue
        if tid:
            seen.add(tid)
        groups.append({'rep': e, 'thread_id': tid})
    for grp in groups:
        grp['count'] = grp['rep'].thread.emails.count() if grp['thread_id'] else 1
    return groups


def _email_thread_context(pk):
    """Emails + their attached events for the related-email popup.

    If the clicked email belongs to a thread, the whole thread is returned
    (oldest first); otherwise just the one email.
    """
    email = get_object_or_404(EmailProcessing.objects.select_related('thread'), pk=pk)
    if email.thread_id:
        emails = list(email.thread.emails.all().order_by('received'))
    else:
        emails = [email]
    items = []
    for e in emails:
        events, seen = [], set()
        for link in e.event_links.filter(mode='include').select_related('event'):
            ev = link.event
            if ev and ev.id not in seen:
                seen.add(ev.id)
                events.append(ev)
        items.append({'email': e, 'events': events})
    return {'items': items, 'thread_count': len(emails)}


def _initials(name):
    """First + last initial for an avatar (e.g. 'Jane Smith' -> 'JS')."""
    parts = [p for p in (name or '').split() if p]
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _attached_email_counts(through_model, owner_field):
    """Distinct emails attached to each owner's events, in one query.

    ``through_model`` is EventContact / EventOrganization; ``owner_field`` is
    'contact' / 'organization'. Counts emails directly attached to the owner's
    events (include-mode EventEmailLinks) — a cheap indicator for the list badge.
    """
    rows = (through_model.objects
            .filter(event__email_links__mode='include')
            .values(owner_field)
            .annotate(n=Count('event__email_links__email', distinct=True)))
    return {row[owner_field]: row['n'] for row in rows}


def _contact_rows():
    """Build the decrypted, name-sorted list of contact rows for the directory."""
    email_counts = _attached_email_counts(EventContact, 'contact')
    contacts = Contact.objects.prefetch_related(
        'email_addresses', 'phone_numbers', 'organizations', 'event_links',
    )
    rows = []
    for c in contacts:
        org_names = ', '.join(sorted(o.name for o in c.organizations.all()))
        rows.append({
            'id': c.id,
            'name': c.name,
            'initials': _initials(c.name),
            'email': _primary(c.email_addresses.all(), 'email'),
            'phone': _primary(c.phone_numbers.all(), 'phone'),
            'organization': org_names,
            'event_count': len(c.event_links.all()),
            'email_count': email_counts.get(c.id, 0),
        })
    rows.sort(key=lambda r: (r.get('name') or '').lower())
    return rows


def _organization_rows():
    """Build the decrypted, name-sorted list of organization rows."""
    email_counts = _attached_email_counts(EventOrganization, 'organization')
    orgs = Organization.objects.prefetch_related(
        'email_addresses', 'phone_numbers', 'contacts', 'event_links',
    )
    rows = []
    for o in orgs:
        rows.append({
            'id': o.id,
            'name': o.name,
            'location': o.location or '',
            'email': _primary(o.email_addresses.all(), 'email'),
            'contact_count': len(o.contacts.all()),
            'event_count': len(o.event_links.all()),
            'email_count': email_counts.get(o.id, 0),
        })
    rows.sort(key=lambda r: (r.get('name') or '').lower())
    return rows


def _render_directory(request, active_tab):
    """Render the combined People + Organizations directory.

    Both datasets are rendered into a single page so the People/Organizations
    toggle can switch client-side without a navigation. ``active_tab`` decides
    which one is shown first.
    """
    return render(request, 'contacts/directory.html', {
        'contact_rows': _contact_rows(),
        'organization_rows': _organization_rows(),
        'active_tab': active_tab,
    })


@login_required
def contact_list(request):
    return _render_directory(request, 'people')


@login_required
def organization_list(request):
    return _render_directory(request, 'organizations')


def _emails_attached_to_events(event_links):
    """All emails attached to the given events (deduped, most-recent-first).

    "Related emails" for a contact/org is exactly the set of emails attached to
    its linked events (each event's thread ∪ direct − excluded union).
    """
    email_ids = set()
    for el in event_links:
        if el.event_id:
            email_ids.update(el.event.get_attached_emails().values_list('id', flat=True))
    if not email_ids:
        return []
    related = (EmailProcessing.objects
               .filter(id__in=email_ids)
               .select_related('thread')
               .order_by('-received'))
    return list(related)


def _split_events(event_links):
    """Split linked events into (upcoming, past).

    Upcoming = future-dated OR undated events, shown first (undated lead, then
    soonest first). Past = past-dated, most-recent first.
    """
    today = timezone.localdate()
    upcoming, past = [], []
    for el in event_links:
        d = getattr(el.event, 'start_date', None)
        if d is None or d >= today:
            upcoming.append(el)
        else:
            past.append(el)
    upcoming.sort(key=lambda el: (el.event.start_date is not None,
                                  el.event.start_date or today))
    past.sort(key=lambda el: el.event.start_date, reverse=True)
    return upcoming, past


def _contact_context(pk):
    contact = get_object_or_404(
        Contact.objects.prefetch_related(
            'email_addresses', 'phone_numbers', 'organizations',
        ),
        pk=pk,
    )
    event_links = list(contact.event_links
                       .select_related('event')
                       .order_by('-linked_at'))
    upcoming, past = _split_events(event_links)
    return {
        'contact': contact,
        'emails': list(contact.email_addresses.all()),
        'phones': list(contact.phone_numbers.all()),
        'organizations': list(contact.organizations.all()),
        'event_links': event_links,
        'upcoming_links': upcoming,
        'past_links': past,
        'related_groups': _group_related(_emails_attached_to_events(event_links)),
    }


def _organization_context(pk):
    org = get_object_or_404(
        Organization.objects.prefetch_related(
            'email_addresses', 'phone_numbers', 'contacts',
        ),
        pk=pk,
    )
    event_links = list(org.event_links
                       .select_related('event')
                       .order_by('-linked_at'))
    upcoming, past = _split_events(event_links)
    return {
        'organization': org,
        'emails': list(org.email_addresses.all()),
        'phones': list(org.phone_numbers.all()),
        'contacts': list(org.contacts.all()),
        'event_links': event_links,
        'upcoming_links': upcoming,
        'past_links': past,
        'related_groups': _group_related(_emails_attached_to_events(event_links)),
    }


@login_required
def contact_panel(request, pk):
    """Detail-panel HTML fragment for a single contact (fetched on row click)."""
    return render(request, 'contacts/_contact_panel.html', _contact_context(pk))


@login_required
def organization_panel(request, pk):
    """Detail-panel HTML fragment for a single organization."""
    return render(request, 'contacts/_organization_panel.html', _organization_context(pk))


@login_required
def email_popup(request, pk):
    """The email's full thread (with attached events) for the popup overlay."""
    return render(request, 'contacts/_email_popup.html', _email_thread_context(pk))
