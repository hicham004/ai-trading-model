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

Research round 1 (plan row R13) adds three pre-registered entry conditions
on top of the unchanged S1 / S2 rules (``research.strategies.round1``):
``S1+BT`` / ``S2+BT`` (entries only while BTC's S1 trend is up), ``S1+VC``
(entries only on a 30-day volume z-score above 1) and the two dual-momentum
legs ``DM-BTC`` / ``DM-ETH`` (one position in the stronger 90-day performer
while both trends are up). The cross-asset ones need a
:class:`research.strategies.round1.CrossAssetContext`.

Research round 2 (plan row R16) adds the slow own-market trend filter
(``research.strategies.round2``): ``S2+TF`` (the breakout rule, entries only
while the close is above its 200-day moving average) and ``TF`` (that filter as
the exposure rule itself, no stop). ``TF`` is a fixed rule: its one parameter
sits in the grid with a single value, so the walk-forward selects only the
exit bracket (``FIXED_RULES``).

Research round 3 (plan row R19) adds the asymmetric setups of the Trader Plan,
section 5 (``research.strategies.round3``), all fixed rules: ``S7`` (trend-pullback
continuation) with its three pre-registered variants ``S7e`` (10-day EMA
pullback), ``S7w`` (3 x ATR stop floor) and ``S7t`` (the ``trail3`` exit
bracket), and ``S8`` (slow Turtle System 2 breakout, 55/20, 5 x ATR stop) with
``S8g`` (Garner's 90/45 channels). ``VARIANT_OF`` names each variant's base
rule; ``ROUND3_BASES`` the comparison line of each round-3 rule.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from research.strategies.base import ResearchStrategy
from research.strategies.baseline import MovingAverageCrossoverRef
from research.strategies.hold import AlwaysLong
from research.strategies.round1 import DualMomentumLeg, ReferenceTrendGated, VolumeConfirmed
from research.strategies.round2 import SlowTrendExposure, SlowTrendGated
from research.strategies.round3 import GARNER_ENTRY_DAYS, GARNER_EXIT_DAYS, PULLBACK_EMA_DAYS, STOP_FLOOR_ATR_WIDE, TRAIL_BRACKET, SlowBreakout, TrendPullback
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
    # Research round 1 (plan row R13): pre-registered entry conditions on the unchanged S1 / S2 rules.
    "S1+BT": ReferenceTrendGated(TimeSeriesMomentum(), reference="BTC-USDT"),
    "S2+BT": ReferenceTrendGated(DonchianBreakout(), reference="BTC-USDT"),
    "S1+VC": VolumeConfirmed(TimeSeriesMomentum()),
    "DM-BTC": DualMomentumLeg("BTC-USDT", "ETH-USDT", tie_wins=True),
    "DM-ETH": DualMomentumLeg("ETH-USDT", "BTC-USDT", tie_wins=False),
    # Research round 2 (plan row R16): the slow own-market trend filter on the unchanged S2 rule, and as the exposure rule itself.
    "S2+TF": SlowTrendGated(DonchianBreakout()),
    "TF": SlowTrendExposure(),
    # Research round 3 (plan row R19): the asymmetric setups of the Trader Plan, section 5, each a fixed rule with one parameter set.
    "S7": TrendPullback(),
    "S7e": TrendPullback(key="S7e", pullback="ema", pullback_days=PULLBACK_EMA_DAYS, variant_label="variant: 10-day EMA pullback"),
    "S7w": TrendPullback(key="S7w", stop_floor_atr=STOP_FLOOR_ATR_WIDE, variant_label="variant: 3 x ATR stop floor"),
    "S7t": TrendPullback(key="S7t", fixed_bracket=TRAIL_BRACKET, variant_label="variant: the trail3 exit bracket, +1 R activation, 3 R trail"),
    "S8": SlowBreakout(),
    "S8g": SlowBreakout(key="S8g", entry_days=GARNER_ENTRY_DAYS, exit_days=GARNER_EXIT_DAYS, variant_label="variant: Garner's 90/45-day channels"),
}

REFERENCES: Dict[str, ResearchStrategy] = {
    "hold": AlwaysLong(),
}

ALL_KEYS: List[str] = [*REFERENCES, *CANDIDATES]
TURNOVER_VARIANTS: Dict[str, str] = {"S1w": "S1", "S1d": "S1", "S2d": "S2", "S4d": "S4", "S1h": "S1"}
S5_RETEST_VARIANTS: Dict[str, str] = {"S1+S5s": "S1", "S2+S5s": "S2"}
#: Research round 1 (plan row R13): each new candidate and the Sprint 2c rule it wraps (the comparison line in its report).
ROUND1_BASES: Dict[str, str] = {"S1+BT": "S1", "S2+BT": "S2", "S1+VC": "S1", "DM-BTC": "S1", "DM-ETH": "S1"}
#: Research round 2 (plan row R16): each candidate and its comparison line (``TF`` is compared with the hold + policy control).
ROUND2_BASES: Dict[str, str] = {"S1+VC": "S1", "S2+TF": "S2", "TF": "hold"}
#: Pre-registered rules with one fixed parameter set: the grid holds a single value per parameter, so the walk-forward selects
#: only the exit bracket; the protocol's robustness replay still perturbs the parameters by +-30 %.
FIXED_RULES: Tuple[str, ...] = ("TF", "S7", "S7e", "S7w", "S7t", "S8", "S8g")
#: Research round 3 (plan row R19): each round-3 rule and its comparison line (hold + policy sizing at the same cell), and each
#: variant's base rule (the variant is compared with it on the same series, mode and cell).
ROUND3_BASES: Dict[str, str] = {"S7": "hold", "S7e": "hold", "S7w": "hold", "S7t": "hold", "S8": "hold", "S8g": "hold"}
VARIANT_OF: Dict[str, str] = {"S7e": "S7", "S7w": "S7", "S7t": "S7", "S8g": "S8"}


def get_candidate(key: str) -> ResearchStrategy:
    if key in CANDIDATES:
        return CANDIDATES[key]
    if key in REFERENCES:
        return REFERENCES[key]
    raise ValueError(f"unknown candidate {key!r}; available: {sorted(ALL_KEYS)}")
