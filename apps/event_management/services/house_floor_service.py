# SPDX-License-Identifier: Apache-2.0
"""
Fetch and parse the docs.house.gov 'Bills This Week' floor schedule XML.

The feed is published per week (Monday-dated) at:
    https://docs.house.gov/billsthisweek/{YYYYMMDD}/{YYYYMMDD}.xml

Production note: external HTTP egress is restricted in production; this module is
intended to be invoked from a Celery task running in the approved egress path.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from django.db import transaction
from django.utils.dateparse import parse_datetime

from ..models import HouseFloorItem, HouseFloorSchedule

logger = logging.getLogger('apps.event_management')

# docs.house.gov publishes naive timestamps in Eastern Time (Capitol local time).
HOUSE_TZ = ZoneInfo('America/New_York')


def _parse_dt_eastern(raw: str) -> Optional[datetime]:
    """Parse an ISO timestamp; if naive, attach America/New_York."""
    dt = parse_datetime(raw or '')
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=HOUSE_TZ)
    return dt

DOCS_HOUSE_URL_TEMPLATE = 'https://docs.house.gov/billsthisweek/{yyyymmdd}/{yyyymmdd}.xml'
DEFAULT_USER_AGENT = 'HillDesk/1.0 (congressional scheduling; +https://hilldesk)'
REQUEST_TIMEOUT_SECONDS = 20


def monday_of(d: date) -> date:
    """Return the Monday on/before the given date."""
    return d - timedelta(days=d.weekday())


def build_url(week_monday: date) -> str:
    return DOCS_HOUSE_URL_TEMPLATE.format(yyyymmdd=week_monday.strftime('%Y%m%d'))


def fetch_xml(week_monday: date, user_agent: str = DEFAULT_USER_AGENT) -> Optional[str]:
    """Fetch the week's XML. Returns the body, or None if the feed isn't published yet."""
    url = build_url(week_monday)
    resp = requests.get(
        url,
        headers={'User-Agent': user_agent, 'Accept': 'application/xml,text/xml'},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code == 404:
        logger.info('No floor schedule published for week of %s (%s)', week_monday, url)
        return None
    resp.raise_for_status()
    return resp.text


def parse_and_store(xml_text: str, fallback_week_monday: date, source_url: str) -> HouseFloorSchedule:
    """Parse XML and upsert into HouseFloorSchedule + HouseFloorItem rows."""
    # Fixed House feed URL; stdlib ElementTree does not resolve external entities.
    root = ET.fromstring(xml_text)  # nosec B314

    week_date_attr = root.attrib.get('week-date') or ''
    try:
        week_date = date.fromisoformat(week_date_attr)
    except ValueError:
        week_date = fallback_week_monday

    congress_num_raw = root.attrib.get('congress-num') or ''
    congress_num = int(congress_num_raw) if congress_num_raw.isdigit() else None

    update_date = _parse_dt_eastern(
        root.attrib.get('update-date') or root.attrib.get('orig-publish-date') or ''
    )

    items: list[HouseFloorItem] = []
    for category in root.findall('category'):
        cat_type = (category.attrib.get('type') or '').strip()
        try:
            cat_order = int(category.attrib.get('sort-order') or 0)
        except ValueError:
            cat_order = 0

        for floor_item in category.findall('.//floor-item'):
            legis = (floor_item.findtext('legis-num') or '').strip()
            text = (floor_item.findtext('floor-text') or '').strip()
            external_id = (floor_item.attrib.get('id') or '').strip()
            try:
                item_order = int(floor_item.attrib.get('sort-order') or 0)
            except ValueError:
                item_order = 0
            pub = _parse_dt_eastern(floor_item.attrib.get('publish-date') or '')

            pdf_url = ''
            pdf_el = floor_item.find('.//file[@doc-type="PDF"]')
            if pdf_el is not None:
                pdf_url = (pdf_el.attrib.get('doc-url') or '').strip()

            items.append(HouseFloorItem(
                category=cat_type,
                category_sort_order=cat_order,
                item_sort_order=item_order,
                external_id=external_id,
                legis_num=legis,
                floor_text=text,
                publish_date=pub,
                pdf_url=pdf_url,
            ))

    with transaction.atomic():
        schedule, _ = HouseFloorSchedule.objects.update_or_create(
            week_date=week_date,
            defaults={
                'congress_num': congress_num,
                'source_url': source_url,
                'source_update_date': update_date,
                'raw_xml': xml_text,
            },
        )
        schedule.items.all().delete()
        for item in items:
            item.schedule = schedule
        HouseFloorItem.objects.bulk_create(items)

    logger.info(
        'Stored floor schedule for week of %s — %d items across categories',
        week_date, len(items)
    )
    return schedule


def fetch_and_store(week_monday: Optional[date] = None) -> Optional[HouseFloorSchedule]:
    """Top-level entry point used by the Celery task and management command."""
    if week_monday is None:
        from django.utils import timezone
        week_monday = monday_of(timezone.localdate())

    xml_text = fetch_xml(week_monday)
    if xml_text is None:
        return None
    return parse_and_store(xml_text, week_monday, build_url(week_monday))
