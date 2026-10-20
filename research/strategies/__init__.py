"""Candidate strategies S0–S5 for the research lab (SIMULATION ONLY).

Each candidate is a :class:`research.strategies.base.ResearchStrategy` that
builds a vectorized :class:`SignalFrame` (desired-long mask, fixed stop
distance, raw strength) for the sweep engine, and can be wrapped by
:class:`research.strategies.adapters.ResearchStrategyAdapter` into the
reviewed ``app.strategy.base.Strategy`` contract for the event-driven check.
None of them is registered in the live registry.

``REFERENCES`` holds passive references (always long) that the Sprint 2b
runner reports next to the candidates but never shortlists.

Sprint 2c adds the lower-turnover variants (``S1w`` weekly clock, ``S1d`` /
``S2d`` / ``S4d`` 1D entry clock, ``S1h`` hysteresis bands) and the S5
re-test variants (``S1+S5s`` / ``S2+S5s``, 7–14-day funding window and an
open-interest change window). The entry rules themselves are unchanged.
"""

from __future__ import annotations

from typing import Dict, List

from research.strategies.base import ResearchStrategy
from research.strategies.baseline import MovingAverageCrossoverRef
from research.strategies.hold import AlwaysLong
from research.strategies.s1_tsmom import TimeSeriesMomentum, TimeSeriesMomentumHysteresis
from research.strategies.s2_breakout import DonchianBreakout
from research.strategies.s3_meanrev import RangeMeanReversion
from research.strategies.s4_volcompression import VolCompressionBreakout
from research.strategies.s5_positioning import PositioningFiltered
from research.strategies.turnover import DailyEntryClock, WeeklyClock

CANDIDATES: Dict[str, ResearchStrategy] = {
    "baseline": MovingAverageCrossoverRef(),
    "S1": TimeSeriesMomentum(),
    "S2": DonchianBreakout(),
    "S3": RangeMeanReversion(),
    "S4": VolCompressionBreakout(),
    "S1+S5": PositioningFiltered(TimeSeriesMomentum()),
    "S2+S5": PositioningFiltered(DonchianBreakout()),
    # Sprint 2c lower-turnover variants (same entry rules, different clocks / bands).
    "S1w": WeeklyClock(TimeSeriesMomentum()),
    "S1d": DailyEntryClock(TimeSeriesMomentum()),
    "S2d": DailyEntryClock(DonchianBreakout()),
    "S4d": DailyEntryClock(VolCompressionBreakout()),
    "S1h": TimeSeriesMomentumHysteresis(),
    # Sprint 2c S5 re-test (shorter funding window, open-interest change window).
    "S1+S5s": PositioningFiltered(TimeSeriesMomentum(), variant="short"),
    "S2+S5s": PositioningFiltered(DonchianBreakout(), variant="short"),
}

REFERENCES: Dict[str, ResearchStrategy] = {
    "hold": AlwaysLong(),
}

ALL_KEYS: List[str] = [*REFERENCES, *CANDIDATES]
TURNOVER_VARIANTS: Dict[str, str] = {"S1w": "S1", "S1d": "S1", "S2d": "S2", "S4d": "S4", "S1h": "S1"}
S5_RETEST_VARIANTS: Dict[str, str] = {"S1+S5s": "S1", "S2+S5s": "S2"}


def get_candidate(key: str) -> ResearchStrategy:
    if key in CANDIDATES:
        return CANDIDATES[key]
    if key in REFERENCES:
        return REFERENCES[key]
    raise ValueError(f"unknown candidate {key!r}; available: {sorted(ALL_KEYS)}")
