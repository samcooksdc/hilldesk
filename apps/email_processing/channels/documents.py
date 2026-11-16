# SPDX-License-Identifier: Apache-2.0
"""Document-attachment channel: pre-extraction text harvest.

PDFs (pypdf) and Word documents (python-docx) are read locally — pure Python,
no egress. Images and scan-only PDFs can't be read here; they're collected for
the single Bedrock call's vision content blocks so OCR stays inside the one
model call. Unreadable or metadata-only (oversized) attachments are reported
as failures — the pipeline escalates those rather than silently dropping an
invitation nobody parsed.
"""

import base64
import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, List

logger = logging.getLogger('apps.email_processing')

# Minimum extractable characters for a PDF to count as text-bearing; below
# this it is treated as scan-only and routed to vision.
_PDF_TEXT_MINIMUM = 40

_IMAGE_TYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/tiff')
_DOCX_TYPES = (
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
)


@dataclass
class HarvestResult:
    """What the document channel got out of a message's attachments."""
    texts: List[Dict] = field(default_factory=list)     # {name, text}
    images: List[Dict] = field(default_factory=list)    # {name, content_type, data_b64}
    failures: List[Dict] = field(default_factory=list)  # {name, reason}

    @property
    def has_content(self) -> bool:
        return bool(self.texts or self.images)


def _harvest_pdf(name: str, payload: bytes, result: HarvestResult) -> None:
    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(payload))
        text = '\n'.join((page.extract_text() or '') for page in reader.pages).strip()
    except Exception as exc:
        result.failures.append({'name': name, 'reason': f'pdf_unreadable: {exc}'})
        return
    if len(text) >= _PDF_TEXT_MINIMUM:
        result.texts.append({'name': name, 'text': text})
    else:
        # Scan-only: hand the bytes to the model as a vision/document block.
        result.images.append({
            'name': name,
            'content_type': 'application/pdf',
            'data_b64': base64.b64encode(payload).decode('ascii'),
        })


def _harvest_docx(name: str, payload: bytes, result: HarvestResult) -> None:
    from docx import Document
    try:
        doc = Document(BytesIO(payload))
    except Exception as exc:
        result.failures.append({'name': name, 'reason': f'docx_unreadable: {exc}'})
        return
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(' | '.join(cells))
    text = '\n'.join(parts).strip()
    if text:
        result.texts.append({'name': name, 'text': text})
    else:
        result.failures.append({'name': name, 'reason': 'docx_empty'})


def harvest(raw_message) -> HarvestResult:
    """Harvest text/images from a message's stored attachment payloads.

    Attachments recorded in metadata but not stored (over the size cap) are
    reported as failures with reason ``not_stored`` — the pipeline decides
    whether to re-fetch or escalate.
    """
    result = HarvestResult()
    stored = {blob.name: blob for blob in raw_message.attachment_blobs.all()}

    for meta in raw_message.attachments or []:
        name = meta.get('name', '') or 'attachment'
        if meta.get('is_inline'):
            continue
        ctype = (meta.get('content_type') or '').lower()
        lname = name.lower()

        is_pdf = ctype == 'application/pdf' or lname.endswith('.pdf')
        is_docx = ctype in _DOCX_TYPES or lname.endswith('.docx')
        is_image = ctype.startswith('image/')
        if not (is_pdf or is_docx or is_image):
            continue  # not a document-channel type (.ics handled by ics.py, etc.)

        blob = stored.get(name)
        if blob is None:
            result.failures.append({'name': name, 'reason': 'not_stored'})
            continue
        payload = bytes(blob.payload)

        if is_pdf:
            _harvest_pdf(name, payload, result)
        elif is_docx:
            _harvest_docx(name, payload, result)
        elif is_image:
            if ctype in _IMAGE_TYPES:
                result.images.append({
                    'name': name,
                    'content_type': ctype,
                    'data_b64': base64.b64encode(payload).decode('ascii'),
                })
            else:
                result.failures.append({'name': name, 'reason': f'unsupported_image: {ctype}'})

    return result
