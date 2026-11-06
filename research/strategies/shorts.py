"""Mirrored short rules for the Phase 9 long/short design study (plan row R9, SIMULATION ONLY).

Each study family keeps its long rule exactly as Sprint 2c ran it and gets the
mirror image as a short rule — same parameters, same features, signs flipped:

- **S1** (time-series momentum): short while at least ``vote`` of the
  lookback returns are NEGATIVE (the long rule: at least ``vote`` positive).
- **S2** (Donchian breakout): short when the close breaks below the prior
  ``entry_days`` low with the same volume and ATR-percentile filters; cover
  when it closes above the prior ``exit_days`` high.
- **S4** (vol-compression breakout): short when the close breaks below the
  lower Bollinger band after a recent squeeze; cover above the mid band.
- **S5** (positioning filter) mirror: no NEW short while the funding-rate
  z-score is below ``-funding_z_max`` (shorts crowded and paying) or open
  interest rose more than ``oi_change_max`` (the same surge rule as for longs).

The stop distance, exit bracket and time stop are the long frame's (ATR x
multiple, the bracket's R multiples): the engine places them on the other side
of the entry. :func:`build_ls_frames` assembles the study's frames:

1. the long side is :func:`research.sweep.build_frames` unchanged (the S0
   no-trade filter gates its entries, as in Sprint 2c);
2. a short may only START on a bar where the long side is flat and the S0
   filter (and, for ``+S5`` families, the S5 mirror) allows a new entry — the
   two gates applied in the long side's order, S5 first, then S0; once open it
   persists until its own exit rule turns it off or the long side wants the bar
   (the engine gives the long side every tie).

S2 and S4 shorts are event states (a breakdown starts one, the cover rule ends
it). When the long side held the bars on which a breakdown happened and no
cover event has come since, the short starts as soon as the long side lets go
— on that bar, with the filters checked there — without waiting for a second
breakdown.

Nothing here is registered anywhere: these rules exist only for the study.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research import features
from research.strategies import get_candidate
from research.strategies.base import FeatureContext, days_to_bars, gate_entries, state_from_events
from research.strategies.s0_filters import NoTradeConfig, tradeable_mask
from research.sweep import Frames, build_frames

MIRRORED_FAMILIES = ("S1", "S2", "S4")
STUDY_KEYS = ("S1", "S2", "S4", "S1+S5", "S2+S5")


@dataclass
class LSFrames(Frames):
    """Sprint 2c frames plus the mirrored short decisions (n, C), exclusive of the long ones."""

    desired_short: Optional[np.ndarray] = None

    def short_matrix(self) -> np.ndarray:
        if self.desired_short is None:
            return np.zeros_like(self.desired)
        return self.desired_short


def _family(key: str) -> Tuple[str, bool]:
    if key not in STUDY_KEYS:
        raise ValueError(f"no mirrored short rule for {key!r}; available: {STUDY_KEYS}")
    base, _, rest = key.partition("+")
    return base, rest == "S5"


def short_desired(key: str, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext,
                  cache: Optional[Dict[Tuple, pd.Series]] = None) -> pd.Series:
    """The mirrored short STATE (before any filter or the long side's priority)."""
    base, _ = _family(key)
    p = get_candidate(key).params_with_defaults(params)
    cache = {} if cache is None else cache
    close, high, low = df["close"], df["high"], df["low"]
    if base == "S1":
        if float(p.get("entry_band", 0.0) or 0.0) > 0.0 or float(p.get("exit_band", 0.0) or 0.0) > 0.0:
            raise ValueError("the hysteresis-band variant (S1h) has no mirrored short rule in this study")
        lookbacks = [days_to_bars(d, context.timeframe) for d in p["lookbacks_days"]]
        vote = int(min(max(1, p["vote"]), len(lookbacks)))
        moms = pd.concat([features.momentum(close, L) for L in lookbacks], axis=1)
        negative = (moms < 0).sum(axis=1)
        ready = moms.notna().all(axis=1)
        return ((negative >= vote) & ready).astype(bool)
    if base == "S2":
        entry_w = days_to_bars(p["entry_days"], context.timeframe)
        exit_w = days_to_bars(p["exit_days"], context.timeframe)
        dl = features.donchian_low(low, entry_w)
        dh = features.donchian_high(high, exit_w)
        vkey = ("S2vol", float(p["vol_mult"]), int(p["volume_window"]))
        if vkey not in cache:
            volume = df["volume"]
            cache[vkey] = (volume > float(p["vol_mult"]) * features.sma(volume, int(p["volume_window"]))).fillna(False)
        akey = ("S2atr", int(p["atr_window"]), float(p["atr_pct_days"]), float(p["atr_pct_max"]))
        if akey not in cache:
            atr = features.atr(high, low, close, int(p["atr_window"]))
            atr_pct = features.percentile_rank(atr, days_to_bars(p["atr_pct_days"], context.timeframe))
            cache[akey] = (atr_pct <= float(p["atr_pct_max"])).fillna(False)
        entries = (close < dl) & cache[vkey] & cache[akey]
        exits = (close > dh).fillna(False)
        return state_from_events(entries, exits)
    # S4
    bkey = ("S4bands", int(p["bb_window"]), float(p["bb_k"]))
    if bkey not in cache:
        cache[bkey] = features.bollinger_bands(close, int(p["bb_window"]), float(p["bb_k"]))
    lower, mid, _upper = cache[bkey]
    wkey = ("S4width", int(p["bb_window"]), float(p["bb_k"]), float(p["pct_days"]))
    if wkey not in cache:
        width = features.bollinger_width(close, int(p["bb_window"]), float(p["bb_k"]))
        cache[wkey] = features.percentile_rank(width, days_to_bars(p["pct_days"], context.timeframe))
    squeezed = (cache[wkey] <= float(p["squeeze_pct"])).fillna(False)
    squeeze_recent = squeezed.shift(1).rolling(int(p["squeeze_lookback"]), min_periods=1).max().fillna(0) > 0
    entries = (close < lower).fillna(False) & squeeze_recent
    exits = (close > mid).fillna(False)
    return state_from_events(entries, exits)


def short_positioning_mask(df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> pd.Series:
    """True where the S5 mirror allows a NEW short (funding z not below -z_max, no open-interest surge)."""
    idx = df.index
    ok = pd.Series(True, index=idx)
    funding = context.aligned("funding", idx, "funding_rate")
    if funding is not None:
        window = int(params.get("funding_z_window", 90))
        roll = funding.rolling(window, min_periods=max(10, window // 3))
        z = (funding - roll.mean()) / roll.std(ddof=0).replace(0.0, np.nan)
        ok &= ~(z < -float(params.get("funding_z_max", 2.0))).fillna(False)
    oi = context.aligned("open_interest", idx, "oi_usd")
    if oi is not None:
        day = days_to_bars(float(params.get("oi_change_window_days", 1)), context.timeframe)
        change = oi / oi.shift(day) - 1.0
        ok &= ~(change > float(params.get("oi_change_max", 0.15))).fillna(False)
    return ok.astype(bool)


def build_ls_frames(
    key: str,
    df: pd.DataFrame,
    combos: Sequence[Mapping[str, Any]],
    context: FeatureContext,
    *,
    no_trade: Optional[NoTradeConfig] = NoTradeConfig(),
    shorts: bool = True,
) -> LSFrames:
    """Long frames exactly as Sprint 2c built them, plus the mirrored short decisions (exclusive of the long ones)."""
    _, with_s5 = _family(key)
    strategy = get_candidate(key)
    base = build_frames(strategy, df, combos, context, no_trade=no_trade)
    n, C = base.desired.shape
    desired_short = np.zeros((n, C), dtype=bool)
    if shorts:
        ok = tradeable_mask(df, context.timeframe, context.periods_per_year, no_trade) if no_trade is not None else pd.Series(True, index=df.index)
        cache: Dict[Tuple, pd.Series] = {}
        s5_cache: Dict[Tuple, pd.Series] = {}
        for j, params in enumerate(combos):
            p = strategy.params_with_defaults(params)
            candidate = short_desired(key, df, p, context, cache) & ~pd.Series(base.desired[:, j], index=df.index)
            if with_s5:
                # Exactly the long side's order: the S5 gate on the rule's state first, then the S0 gate.
                s5_key = (float(p.get("funding_z_max", 2.0)), int(p.get("funding_z_window", 90)), float(p.get("oi_change_max", 0.15)),
                          float(p.get("oi_change_window_days", 1)))
                if s5_key not in s5_cache:
                    s5_cache[s5_key] = short_positioning_mask(df, p, context)
                candidate = gate_entries(candidate, s5_cache[s5_key])
            desired_short[:, j] = gate_entries(candidate, ok).to_numpy(dtype=bool)
    return LSFrames(desired=base.desired, stop=base.stop, strength=base.strength, time_stops=base.time_stops, target=base.target,
                    trail_activate=base.trail_activate, trail_dist=base.trail_dist, desired_short=desired_short)
