# SPDX-License-Identifier: Apache-2.0
"""Channel parsers (spec §6): non-prose routes into the pipeline.

- ``ics``: calendar objects parse deterministically into candidates — no model
  call, confidence 1.0.
- ``documents``: PDF/DOCX text harvest + image collection for the single
  extraction call's vision blocks.
- ``forwards``: forward detection and original-sender extraction (reputation
  evaluates the original sender, not the forwarding staffer).

Channels produce plain dicts/dataclasses; persistence of candidates arrives
with the ExtractionCandidate model in Phase 4.
"""
