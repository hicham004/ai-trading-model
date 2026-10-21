"""Decisions for one sleeve at one bar close, through the reviewed ``Strategy`` contract (SIMULATION ONLY).

For every bar that closes, each sleeve account asks its research candidate for
signals over a long window of bars ending at that bar
(:class:`research.strategies.adapters.ResearchStrategyAdapter`: the candidate's
own rule, its S5 positioning filter where it has one, and the S0 no-trade
filter with the FOMC calendar — exactly the research's frame), takes the
contract ``Signal`` of the last bar, and adds what the research layered on top:

- the regime-v2 entry gate (entries only) or entry-size scale;
- the policy sizing fraction (vol target, crash filter) of that bar;
- the exit bracket of the selected rule (take-profit target, trailing stop,
  time stop), sized from the signal's stop distance.

The result is a :class:`research.paper_fleet.engine.Decision` executed on the
next bar, plus diagnostics that explain it in the journal (which filter
allowed or blocked, the regime probability, the size parts). Only bars up to
and including the decision bar are ever used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.strategy.base import Signal, SignalAction
from research.bracket import get_bracket
from research.data import bars_per_year, to_market_candles
from research.sizing import crash_multiplier, fraction_series, vol_target_fraction
from research.strategies import get_candidate
from research.sweep import build_frames
from research.strategies.adapters import ResearchStrategyAdapter
from research.strategies.base import FeatureContext, days_to_bars
from research.strategies.s0_filters import tradeable_mask
from research.strategies.s5_positioning import positioning_mask

from research.paper_fleet.config import FALLBACK_CONFIDENCE, NO_TRADE, TEST_WINDOW_DAYS, SleeveSpec
from research.paper_fleet.engine import Decision, EngineConfig
from research.paper_fleet.regime import RegimeFit, gate_desired, gate_inputs

DECISION_WINDOW_DAYS = 400.0  # every feature of the candidates looks back <= 100 days; 400 leaves long margins
STRATEGY_WARMUP_DAYS = 150.0  # gated accounts: signals start this long before the regime fit's train start
DIAGNOSTIC_TAIL_DAYS = 40.0  # journal explanations of the S0 / S5 filters are computed on this tail only


def iso(ts: Any) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _f(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def engine_config(spec: SleeveSpec, *, costs, init_cash: float) -> EngineConfig:
    """The static engine rules of a sleeve: sizing mode, ladder, rebalancing, its exit bracket and the 180-day test windows."""
    bracket = get_bracket(spec.bracket)
    time_stop = days_to_bars(float(bracket.time_stop_days), spec.timeframe) if bracket.time_stop_days is not None else None
    return EngineConfig(
        costs=costs, init_cash=init_cash, sized=spec.sizing is not None, ladder=spec.ladder(),
        rebalance_threshold=spec.rebalance_threshold if spec.sizing is not None else None, time_stop_bars=time_stop,
        trail_activate_r=bracket.trail_activate_r if bracket.trail_r is not None else None,
        trail_r=bracket.trail_r, window_bars=days_to_bars(TEST_WINDOW_DAYS, spec.timeframe),
    )


@dataclass
class DecisionInfo:
    decision: Decision
    signal: Dict[str, Any]
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"decision": self.decision.to_dict(), "signal": self.signal, "diagnostics": self.diagnostics}


def signal_dict(signal: Signal) -> Dict[str, Any]:
    return {"action": signal.action.value, "confidence": float(signal.confidence), "stop_loss": _f(signal.stop_loss),
            "reason": signal.reason, "timeframe": signal.timeframe, "timestamp": iso(signal.timestamp)}


def decide_sleeve(
    spec: SleeveSpec,
    bars: pd.DataFrame,
    context: FeatureContext,
    *,
    regime_fit: Optional[RegimeFit] = None,
    window_days: float = DECISION_WINDOW_DAYS,
) -> DecisionInfo:
    """The decision made at the close of ``bars``' last bar (``bars`` must end at the decision bar)."""
    if bars.empty:
        raise ValueError("no bars to decide on")
    t = bars.index[-1]
    start = t - pd.Timedelta(days=window_days)
    if spec.regime.active and regime_fit is not None:
        # The entries-only gate runs from the regime fit's train start (as in the research): signals need that span plus a warm-up.
        start = min(start, regime_fit.train_start - pd.Timedelta(days=STRATEGY_WARMUP_DAYS))
    window = bars[bars.index > start]
    candidate = get_candidate(spec.candidate)
    adapter = ResearchStrategyAdapter(candidate, spec.rule_params, context, no_trade=NO_TRADE,
                                      fallback_confidence=FALLBACK_CONFIDENCE, fallback_stop_pct=None)
    candles = to_market_candles(window, spec.instrument, spec.timeframe)
    signals = adapter.generate_signals(candles)
    last = signals[-1]
    close = float(window["close"].iloc[-1])
    desired = pd.Series([s.action == SignalAction.LONG for s in signals], index=window.index)
    ppy = bars_per_year(spec.timeframe)
    diag: Dict[str, Any] = {"window_bars": int(len(window)), "contract_long": bool(desired.iloc[-1])}

    # S0 / S5 states of the decision bar (explanations only; the adapter already applied them). Their longest
    # look-back is 30 days (+1 day of vol, 90 bars of funding), so a 40-day tail gives the exact last values.
    tail = window[window.index > t - pd.Timedelta(days=DIAGNOSTIC_TAIL_DAYS)]
    s0 = tradeable_mask(tail, spec.timeframe, ppy, NO_TRADE)
    diag["s0_tradeable"] = bool(s0.iloc[-1])
    if spec.uses_positioning:
        params = candidate.params_with_defaults(spec.rule_params)
        pos_ok = positioning_mask(tail, params, context)
        diag["positioning"] = _positioning_diag(tail, params, context, bool(pos_ok.iloc[-1]))

    # Regime-v2 gate (entries only) or entry-size scale.
    gated = bool(desired.iloc[-1])
    mult = 1.0
    if spec.regime.active:
        if regime_fit is None:
            raise ValueError(f"{spec.candidate} {spec.instrument} {spec.timeframe}: a regime fit is required")
        inputs = gate_inputs(window, regime_fit, spec.regime)
        bear = inputs["bear_prob"]
        diag["regime"] = {"mode": spec.regime.mode, "fit_id": regime_fit.fit_id, "fit_error": regime_fit.error,
                          "bear_prob": _f(bear.iloc[-1]) if len(bear) else None,
                          "entry_allowed": bool(inputs["ok"].iloc[-1]) if len(inputs["ok"]) else False}
        if spec.regime.mode == "gate":
            gated = bool(gate_desired(desired, inputs["ok"]).iloc[-1]) if len(inputs["ok"]) else False
        elif spec.regime.mode == "scale":
            mult = float(inputs["mult"].iloc[-1]) if len(inputs["mult"]) else float(spec.regime.bear_scale)
    diag["desired"] = gated
    if bool(desired.iloc[-1]) and not gated:
        # The rule (after S0/S5) wants to be long, the regime gate does not let a new run start (or, right after a
        # refit, did not let the current run start under the new model): no entry, and an open position is closed.
        diag["blocked_by"] = "regime gate"

    # Size: the policy fraction of the decision bar (vol target x crash filter), times the regime scale.
    if spec.sizing is not None:
        frac = float(fraction_series(window, spec.sizing, spec.timeframe, ppy).iloc[-1]) * mult
        parts: Dict[str, Any] = {"fraction": _f(frac), "regime_multiplier": mult}
        if spec.sizing.kind == "vol_target":
            parts["vol_target"] = _f(vol_target_fraction(window["close"], spec.sizing.target_vol, spec.sizing.vol_lookback, ppy,
                                                          cap=spec.sizing.cap).iloc[-1])
        if spec.sizing.crash_dd is not None:
            parts["crash_multiplier"] = _f(crash_multiplier(window["close"], spec.sizing.crash_dd,
                                                            days_to_bars(float(spec.sizing.crash_window_days), spec.timeframe),
                                                            mode=spec.sizing.crash_mode).iloc[-1])
        diag["size"] = parts
    else:
        frac = 1.0

    # Stop distance from the contract signal; the bracket's take-profit is sized from it (R multiples).
    sd = close - float(last.stop_loss) if (last.action == SignalAction.LONG and last.stop_loss is not None) else float("nan")
    bracket = get_bracket(spec.bracket)
    td = float("nan")
    if bracket.take_profit_r is not None and math.isfinite(sd) and sd > 0:
        td = sd * float(bracket.take_profit_r)
    decision = Decision(bar_time=iso(t), close=close, desired=gated, stop_distance=sd, target_distance=td, fraction=frac)
    return DecisionInfo(decision=decision, signal=signal_dict(last), diagnostics=diag)


def _positioning_diag(window: pd.DataFrame, params: Dict[str, Any], context: FeatureContext, ok: bool) -> Dict[str, Any]:
    idx = window.index
    out: Dict[str, Any] = {"entry_allowed": ok}
    funding = context.aligned("funding", idx, "funding_rate")
    if funding is not None:
        w = int(params.get("funding_z_window", 90))
        roll = funding.rolling(w, min_periods=max(10, w // 3))
        z = (funding - roll.mean()) / roll.std(ddof=0).replace(0.0, np.nan)
        out.update({"funding_rate": _f(funding.iloc[-1]), "funding_z": _f(z.iloc[-1]), "funding_z_max": float(params.get("funding_z_max", 2.0))})
    else:
        out["funding_rate"] = None
    oi = context.aligned("open_interest", idx, "oi_usd")
    if oi is not None:
        day = days_to_bars(float(params.get("oi_change_window_days", 1)), context.timeframe)
        change = oi / oi.shift(day) - 1.0
        out.update({"oi_usd": _f(oi.iloc[-1]), "oi_change": _f(change.iloc[-1]), "oi_change_max": float(params.get("oi_change_max", 0.15))})
    else:
        out["oi_usd"] = None
    return out


def frame_decisions(spec: SleeveSpec, bars: pd.DataFrame, context: FeatureContext, *, start: pd.Timestamp) -> List[Decision]:
    """Decisions for every bar of ``bars`` from ``start`` on, from the research frames in one vectorized pass.

    The same rules as :func:`decide_sleeve` (``research.sweep.build_frames``: the
    candidate, its S5 filter, the S0 filter and the exit bracket) for sleeves
    without a regime gate; used to simulate the portfolio's warm-up history
    quickly. ``tests/test_paper_fleet_signals.py`` checks both paths agree.
    """
    if spec.regime.active:
        raise ValueError("frame decisions are only used for sleeves without a regime gate")
    frames = build_frames(get_candidate(spec.candidate), bars, [dict(spec.params)], context, no_trade=NO_TRADE)
    desired = frames.desired[:, 0]
    stop = frames.stop[:, 0]
    target = frames.target[:, 0] if frames.target is not None else np.full(len(bars), np.nan)
    if spec.sizing is not None:
        frac = fraction_series(bars, spec.sizing, spec.timeframe, bars_per_year(spec.timeframe)).to_numpy(dtype=float)
    else:
        frac = np.ones(len(bars))
    closes = bars["close"].to_numpy(dtype=float)
    out: List[Decision] = []
    for i, ts in enumerate(bars.index):
        if ts < start:
            continue
        # Like a contract FLAT signal, a bar that is not desired carries no stop (the engine only uses it to enter).
        sd = float(stop[i]) if (desired[i] and np.isfinite(stop[i]) and stop[i] > 0) else float("nan")
        td = float(target[i]) if (math.isfinite(sd) and np.isfinite(target[i]) and target[i] > 0) else float("nan")
        out.append(Decision(bar_time=iso(ts), close=float(closes[i]), desired=bool(desired[i]), stop_distance=sd, target_distance=td,
                            fraction=float(frac[i])))
    return out


def decide_buy_and_hold(bars: pd.DataFrame) -> DecisionInfo:
    """Plain buy-and-hold: always long, all in, no stop, no filter (research ``buy_and_hold``)."""
    t = bars.index[-1]
    close = float(bars["close"].iloc[-1])
    decision = Decision(bar_time=iso(t), close=close, desired=True, fraction=1.0)
    return DecisionInfo(decision=decision, signal={"action": "long", "reason": "buy-and-hold: always long", "stop_loss": None},
                        diagnostics={"desired": True})
