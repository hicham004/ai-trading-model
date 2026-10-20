"""Candidate strategies S0–S5 for the research lab (SIMULATION ONLY).

Each candidate is a :class:`research.strategies.base.ResearchStrategy` that
builds a vectorized :class:`SignalFrame` (desired-long mask, fixed stop
distance, raw strength) for the sweep engine, and can be wrapped by
:class:`research.strategies.adapters.ResearchStrategyAdapter` into the
reviewed ``app.strategy.base.Strategy`` contract for the event-driven check.
None of them is registered in the live registry.

``REFERENCES`` holds passive references (always long) that the Sprint 2b
runner reports next to the candidates but never shortlists.
"""

from __future__ import annotations

from typing import Dict, List

from research.strategies.base import ResearchStrategy
from research.strategies.baseline import MovingAverageCrossoverRef
from research.strategies.hold import AlwaysLong
from research.strategies.s1_tsmom import TimeSeriesMomentum
from research.strategies.s2_breakout import DonchianBreakout
from research.strategies.s3_meanrev import RangeMeanReversion
from research.strategies.s4_volcompression import VolCompressionBreakout
from research.strategies.s5_positioning import PositioningFiltered

CANDIDATES: Dict[str, ResearchStrategy] = {
    "baseline": MovingAverageCrossoverRef(),
    "S1": TimeSeriesMomentum(),
    "S2": DonchianBreakout(),
    "S3": RangeMeanReversion(),
    "S4": VolCompressionBreakout(),
    "S1+S5": PositioningFiltered(TimeSeriesMomentum()),
    "S2+S5": PositioningFiltered(DonchianBreakout()),
}

REFERENCES: Dict[str, ResearchStrategy] = {
    "hold": AlwaysLong(),
}

ALL_KEYS: List[str] = [*REFERENCES, *CANDIDATES]


def get_candidate(key: str) -> ResearchStrategy:
    if key in CANDIDATES:
        return CANDIDATES[key]
    if key in REFERENCES:
        return REFERENCES[key]
    raise ValueError(f"unknown candidate {key!r}; available: {sorted(ALL_KEYS)}")
