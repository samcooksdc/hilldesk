# SPDX-License-Identifier: Apache-2.0
"""
Fetch and parse the Clerk's live House floor proceedings feed.

The Clerk publishes one XML file per legislative day at:
    https://clerk.house.gov/floor/{YYYYMMDD}.xml

This is the same "Activity" feed live.house.gov displays — a reverse-chronological
list of timestamped floor actions (prayer, pledge, votes, messages, adjournment…).

Production note: external HTTP egress is restricted in production; this module is
intended to be invoked from a Celery task running in the approved egress path
(clerk.house.gov is reachable from House infrastructure).
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from django.db import transaction

from ..models import HouseFloorAction, HouseFloorProceedings

logger = logging.getLogger('apps.event_management')

# The Clerk publishes naive timestamps in Eastern Time (Capitol local time).
HOUSE_TZ = ZoneInfo('America/New_York')

CLERK_FLOOR_URL_TEMPLATE = 'https://clerk.house.gov/floor/{yyyymmdd}.xml'
DEFAULT_USER_AGENT = 'HillDesk/1.0 (congressional scheduling; +https://hilldesk)'
REQUEST_TIMEOUT_SECONDS = 20
# How many days back to walk looking for the most recent published day when the
# target date has no file (weekends / recess).
DEFAULT_LOOKBACK_DAYS = 10

_WHITESPACE_RE = re.compile(r'\s+')


def build_url(d: date) -> str:
    return CLERK_FLOOR_URL_TEMPLATE.format(yyyymmdd=d.strftime('%Y%m%d'))


def _parse_compact_dt(raw: str) -> Optional[datetime]:
    """Parse the Clerk's compact timestamps (e.g. '20260615T10:33:15' or
    '20260615T10:39'), attaching Eastern time."""
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y%m%dT%H:%M:%S', '%Y%m%dT%H:%M', '%Y%m%d'):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=HOUSE_TZ)
        except ValueError:
            continue
    return None


def _parse_pub_date(raw: str) -> Optional[datetime]:
    """Parse an RFC 2822 pubDate like 'Mon, 15 Jun 2026 15:45:01 EDT'."""
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def _element_text(el: Optional[ET.Element]) -> str:
    """Flatten an element's mixed content (including inline <a> links) to plain
    text with normalized whitespace."""
    if el is None:
        return ''
    text = ''.join(el.itertext())
    return _WHITESPACE_RE.sub(' ', text).strip()


def fetch_xml(d: date, user_agent: str = DEFAULT_USER_AGENT) -> Optional[str]:
    """Fetch the day's XML. Returns the body, or None if no file is published."""
    url = build_url(d)
    resp = requests.get(
        url,
        headers={'User-Agent': user_agent, 'Accept': 'application/xml,text/xml'},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code == 404:
        logger.info('No floor proceedings published for %s (%s)', d, url)
        return None
    resp.raise_for_status()
    return resp.text


def parse_and_store(xml_text: str, source_url: str) -> HouseFloorProceedings:
    """Parse the proceedings XML and upsert a HouseFloorProceedings + actions."""
    # Fixed House feed URL; stdlib ElementTree does not resolve external entities.
    root = ET.fromstring(xml_text)  # nosec B314

    day_el = root.find('legislative_day')
    leg_day = None
    if day_el is not None:
        leg_day = _parse_compact_dt(day_el.attrib.get('date') or '')
    legislative_day = leg_day.date() if leg_day else date.today()

    congress_el = root.find('legislative_congress')
    congress_num = session_num = None
    if congress_el is not None:
        c = congress_el.attrib.get('congress') or ''
        s = congress_el.attrib.get('session') or ''
        congress_num = int(c) if c.isdigit() else None
        session_num = int(s) if s.isdigit() else None

    header = (root.findtext('legislative_header') or '').strip()
    pub_date = _parse_pub_date(root.findtext('pubDate') or '')

    actions_el = root.find('floor_actions')
    day_finished = False
    next_convenes = None
    if actions_el is not None:
        finished_el = actions_el.find('legislative_day_finished')
        if finished_el is not None:
            day_finished = (finished_el.text or '').strip().lower() == 'yes'
            next_convenes = _parse_compact_dt(
                finished_el.attrib.get('next-legislative-day-convenes') or ''
            )

    actions: list[HouseFloorAction] = []
    for fa in (actions_el.findall('floor_action') if actions_el is not None else []):
        time_el = fa.find('action_time')
        action_time = None
        time_display = ''
        if time_el is not None:
            action_time = _parse_compact_dt(time_el.attrib.get('for-search') or '')
            # Display text is like "10:33:15 A.M. -"; drop the trailing dash.
            time_display = (time_el.text or '').strip().rstrip('-').strip()

        actions.append(HouseFloorAction(
            unique_id=(fa.attrib.get('unique-id') or '').strip(),
            act_id=(fa.attrib.get('act-id') or '').strip(),
            action_time=action_time,
            action_time_display=time_display,
            description=_element_text(fa.find('action_description')),
            update_date_time=_parse_compact_dt(fa.attrib.get('update-date-time') or ''),
        ))

    with transaction.atomic():
        proceedings, _ = HouseFloorProceedings.objects.update_or_create(
            legislative_day=legislative_day,
            defaults={
                'legislative_header': header,
                'congress_num': congress_num,
                'session_num': session_num,
                'pub_date': pub_date,
                'day_finished': day_finished,
                'next_convenes': next_convenes,
                'source_url': source_url,
                'raw_xml': xml_text,
            },
        )
        proceedings.actions.all().delete()
        for action in actions:
            action.proceedings = proceedings
        HouseFloorAction.objects.bulk_create(actions)

    logger.info(
        'Stored floor proceedings for %s — %d action(s)',
        legislative_day, len(actions)
    )
    return proceedings


def fetch_and_store(
    target_date: Optional[date] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> Optional[HouseFloorProceedings]:
    """Top-level entry point used by the Celery task and management command.

    Tries `target_date` (default today), walking back day-by-day up to
    `lookback_days` to find the most recent published proceedings (the House
    doesn't convene every calendar day).
    """
    if target_date is None:
        from django.utils import timezone
        target_date = timezone.localdate()

    for offset in range(lookback_days + 1):
        day = target_date - timedelta(days=offset)
        xml_text = fetch_xml(day)
        if xml_text is not None:
            return parse_and_store(xml_text, build_url(day))

    logger.info('No floor proceedings found within %d days of %s', lookback_days, target_date)
    return None
