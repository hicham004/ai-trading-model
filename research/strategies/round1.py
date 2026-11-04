"""Research round 1 (plan row R13): three pre-registered entry conditions, SIMULATION ONLY.

New rules, not retunes of old ones — each wraps a Sprint 2c rule whose
parameters, grid and brackets stay exactly as they were, and adds ONE fixed,
pre-registered condition:

- **H1** ``S1+BT`` / ``S2+BT`` — ETH's S1 / S2 rule, new entries only while
  BTC's S1 trend is up (S1 with its Sprint 2 defaults on BTC's candles:
  lookbacks 7/14/30 days, at least 2 of 3 positive). Entries only: an open
  position is left to the base rule's own exits, as the regime gate and the
  S5 filter do.
- **H2** ``S1+VC`` — S1, new entries only on bars whose volume z-score over
  the trailing 30 days is above 1 (the bar's own volume against the trailing
  mean and standard deviation; Liu & Tsyvinski's attention effect). Entries only.
- **H3** ``DM-BTC`` / ``DM-ETH`` — dual momentum between BTC and ETH as two
  legs that are mutually exclusive by construction: the leg is long its own
  market only while BOTH markets' S1 trends are up (the leg's S1 parameters on
  both) and its own market is the stronger 90-day performer (ties go to BTC).
  The two legs together are one position; the study judges their combined
  curve.

The other market's candles reach a rule through :class:`CrossAssetContext`,
a :class:`research.strategies.base.FeatureContext` with ``references``
(OHLCV frames of other instruments at the same timeframe, indexed by UTC open
time). A rule aligns a reference onto its own bars by exact timestamp — a bar
of one market sees the other market's bar that closed at the same instant,
never a later one — and fails closed (no entry) wherever the reference bar is
missing. A context without the reference a rule needs raises, so a
misconfigured run is a visible failure, not a silently flat account.

Nothing here can reach an order or an account; every number produced with
these rules is a simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

import pandas as pd

from research import features
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, days_to_bars, gate_entries
from research.strategies.s1_tsmom import TimeSeriesMomentum

OHLCV = ("open", "high", "low", "close", "volume")

#: H1: the reference trend is S1 with its Sprint 2 defaults (fixed, never in a grid).
REFERENCE_TREND_PARAMS: Dict[str, Any] = dict(TimeSeriesMomentum.default_params)
#: H2: the volume confirmation (fixed, never in a grid).
VOLUME_Z_DAYS = 30.0
VOLUME_Z_MIN = 1.0
#: H3: the relative-strength lookback (fixed, never in a grid).
DUAL_MOMENTUM_DAYS = 90.0


@dataclass
class CrossAssetContext(FeatureContext):
    """A feature context that also carries other instruments' candles (same timeframe) for cross-asset rules."""

    instrument: Optional[str] = None  # the market the candles handed to ``build`` belong to (checked by the legs)
    references: Dict[str, pd.DataFrame] = field(default_factory=dict)  # instrument -> OHLCV indexed by UTC open_time


def reference_frame(context: FeatureContext, instrument: str, index: pd.Index) -> pd.DataFrame:
    """The reference instrument's OHLCV aligned onto ``index`` by exact timestamp (NaN where its bar is missing).

    Raises ``ValueError`` when the context does not carry that instrument: a cross-asset rule must never run blind."""
    refs = getattr(context, "references", None) or {}
    frame = refs.get(instrument)
    if frame is None or frame.empty:
        raise ValueError(f"the context carries no {instrument} candles; a cross-asset rule cannot run without its reference")
    missing = [c for c in OHLCV if c not in frame.columns]
    if missing:
        raise ValueError(f"the {instrument} reference frame lacks columns {missing}")
    aligned = frame[list(OHLCV)].astype(float).reindex(index)
    aligned.index.name = index.name
    return aligned


def reference_trend_up(context: FeatureContext, instrument: str, index: pd.Index, params: Optional[Mapping[str, Any]] = None) -> pd.Series:
    """S1's trend vote on the reference instrument's candles aligned to ``index`` (False where the reference is missing)."""
    ref = reference_frame(context, instrument, index)
    frame = TimeSeriesMomentum().build(ref, dict(REFERENCE_TREND_PARAMS if params is None else params), context)
    return frame.desired.reindex(index).fillna(False).astype(bool)


def _carry(frame: SignalFrame, desired: pd.Series) -> SignalFrame:
    return SignalFrame(desired=desired, stop_distance=frame.stop_distance, strength=frame.strength.where(desired),
                       target_distance=frame.target_distance, time_stop_bars=frame.time_stop_bars,
                       trail_activate_r=frame.trail_activate_r, trail_r=frame.trail_r)


class ReferenceTrendGated(ResearchStrategy):
    """H1: the base rule's entries are allowed only while the reference market's S1 trend (fixed defaults) is up."""

    def __init__(self, base: ResearchStrategy, *, reference: str = "BTC-USDT") -> None:
        self.base = base
        self.reference = reference
        self.key = f"{base.key}+BT"
        self.label = f"{base.label} + entries only while {reference.split('-')[0]}'s S1 trend is up"
        self.default_params = dict(base.default_params)
        self.grid = dict(base.grid)

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        frame = self.base.build(df, p, context)
        ok = reference_trend_up(context, self.reference, df.index)
        return _carry(frame, gate_entries(frame.desired, ok))


class VolumeConfirmed(ResearchStrategy):
    """H2: the base rule's entries are allowed only on bars whose trailing-window volume z-score is above the threshold."""

    def __init__(self, base: ResearchStrategy, *, z_days: float = VOLUME_Z_DAYS, z_min: float = VOLUME_Z_MIN) -> None:
        self.base = base
        self.z_days = float(z_days)
        self.z_min = float(z_min)
        self.key = f"{base.key}+VC"
        self.label = f"{base.label} + entries only when the {z_days:g}-day volume z-score is above {z_min:g}"
        self.default_params = dict(base.default_params)
        self.grid = dict(base.grid)

    def volume_ok(self, df: pd.DataFrame, context: FeatureContext) -> pd.Series:
        window = max(2, days_to_bars(self.z_days, context.timeframe))
        z = features.zscore(df["volume"].astype(float), window)
        return (z > self.z_min).fillna(False).astype(bool)

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        frame = self.base.build(df, p, context)
        return _carry(frame, gate_entries(frame.desired, self.volume_ok(df, context)))


class DualMomentumLeg(ResearchStrategy):
    """H3: one leg of the BTC/ETH dual-momentum rule (long its own market only while both S1 trends are up and it is the
    stronger performer over the fixed lookback). ``tie_wins`` settles an exact tie (True for the BTC leg), so the two legs can
    never be long at the same bar."""

    def __init__(self, own: str, other: str, *, lookback_days: float = DUAL_MOMENTUM_DAYS, tie_wins: bool = False) -> None:
        self.own = own
        self.other = other
        self.lookback_days = float(lookback_days)
        self.tie_wins = bool(tie_wins)
        self.key = f"DM-{own.split('-')[0]}"
        self.label = (f"dual momentum leg: long {own.split('-')[0]} only while both {own.split('-')[0]} and {other.split('-')[0]} S1 trends are up "
                      f"and {own.split('-')[0]} is the stronger {lookback_days:g}-day performer")
        self.default_params = dict(TimeSeriesMomentum.default_params)
        self.grid = dict(TimeSeriesMomentum.grid)
        self._s1 = TimeSeriesMomentum()

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        bound = getattr(context, "instrument", None)
        if bound is not None and bound != self.own:
            raise ValueError(f"{self.key} must run on {self.own}'s candles, not {bound}'s")
        own_frame = self._s1.build(df, p, context)
        other = reference_frame(context, self.other, df.index)
        other_up = self._s1.build(other, p, context).desired.reindex(df.index).fillna(False).astype(bool)
        lookback = days_to_bars(self.lookback_days, context.timeframe)
        mom_own = features.momentum(df["close"].astype(float), lookback)
        mom_other = features.momentum(other["close"], lookback)
        stronger = (mom_own >= mom_other) if self.tie_wins else (mom_own > mom_other)
        stronger = stronger & mom_own.notna() & mom_other.notna()
        desired = (own_frame.desired & other_up & stronger.fillna(False)).astype(bool)
        return _carry(own_frame, desired)
