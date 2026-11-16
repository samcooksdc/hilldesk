# SPDX-License-Identifier: Apache-2.0
"""Celery tasks for the email ingestion pipeline.

Split by concern:
- ``reception``: sweep, webhook fan-in, subscription lifecycle (Phase 1).
- ``pipeline``: funnel + extraction orchestration per message (Phase 2+).
"""
