# SPDX-License-Identifier: Apache-2.0
"""Deterministic ingestion funnel (spec §5).

One module per stage — pure functions over a FunnelContext — orchestrated by
``engine.run_funnel``, which writes a FilterLog row for every stage evaluated.
"""

from .base import DIVERT, ESCALATE, EXTRACT, PASS, FunnelContext, StageDecision
from .engine import FunnelResult, build_context, run_funnel

__all__ = [
    'DIVERT', 'ESCALATE', 'EXTRACT', 'PASS',
    'FunnelContext', 'StageDecision', 'FunnelResult',
    'build_context', 'run_funnel',
]
