"""Research round 3 (plan row R19): the asymmetric setups of the Trader Plan, section 5, SIMULATION ONLY.

Two new rule families, written as FIXED rules: every parameter is one pre-registered
number (the grid holds a single value per parameter, so the walk-forward has nothing
to select), the protocol's robustness replay still perturbs them by +-30 %, and the
fixed-rule protocol variant of the round skips the 20-train-trade qualification that
left the round-2 slow rules flat (``research/round3.py``).

- **S7 — trend-pullback continuation** (:class:`TrendPullback`). In an uptrend (the
  close above its 100-day simple moving average and the 50-day average above the
  100-day), after a pullback (a close below the 20-day average; variant ``S7e``:
  below the 10-day exponential average), enter when a close exceeds the previous
  bar's high while the uptrend still holds; the stop sits under the pullback low
  (the lowest low from the first close below the pullback average to the entry
  bar), floored at 2 x ATR(14) (variant ``S7w``: 3 x); the exit is a close below
  the 50-day average, or the stop. Variant ``S7t``: the same rule under the
  protocol's ``trail3`` exit bracket (a trailing stop that activates at +1 R and
  follows the running high at 3 R), applied by the research runner and by the
  paper fleet alike through the ``bracket`` parameter, never by this frame.
  The only version of dip buying the evidence supports (plan section 2.6).
- **S8 — slow breakout with wide stops** (:class:`SlowBreakout`). A slow Turtle
  System 2 breakout: enter on a close above the prior 55-day high, exit on a close
  below the prior 20-day low, Garner's 5 x ATR(14) stop, no adds, no volume or
  volatility filter (unlike S2). Variant ``S8g``: Garner's own 90-day / 45-day
  channels. The fewer-trades, wider-stop direction that kept working in futures
  after 1990 (plan section 2.1).

Every lookback is in calendar days and converted to bars of the timeframe
(:func:`research.strategies.base.days_to_bars`), as every other rule's. The state
machines are causal: a bar's state depends only on bars up to and including it.
Nothing here can reach an order or an account; every number produced with these
rules is a simulation.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

import numpy as np
import pandas as pd

from research import features
from research.strategies.base import FeatureContext, ResearchStrategy, SignalFrame, days_to_bars, finite_or_nan, state_from_events

#: S7's fixed numbers (plan section 5, item 1): the trend averages, the pullback average, the ATR window and the stop floor.
TREND_FAST_DAYS = 50
TREND_SLOW_DAYS = 100
PULLBACK_SMA_DAYS = 20
PULLBACK_EMA_DAYS = 10
ATR_WINDOW = 14
STOP_FLOOR_ATR = 2.0
STOP_FLOOR_ATR_WIDE = 3.0
TRAIL_BRACKET = "trail3"  # research.bracket.BRACKETS: activates at +1 R, follows the running high at 3 R
#: S8's fixed numbers (plan section 5, item 2): the Turtle System 2 channels, Garner's stop, Garner's channels.
BREAKOUT_ENTRY_DAYS = 55
BREAKOUT_EXIT_DAYS = 20
BREAKOUT_STOP_ATR = 5.0
GARNER_ENTRY_DAYS = 90
GARNER_EXIT_DAYS = 45


def pullback_state(uptrend: np.ndarray, pullback: np.ndarray, breakout: np.ndarray, exit_: np.ndarray, low: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The S7 state machine, bar by bar (causal).

    Flat and unarmed -> a close below the pullback average while the uptrend holds arms the rule and starts the pullback low;
    armed -> every bar's low (the entry bar's included) lowers the pullback low; a close above the previous bar's high while
    the uptrend holds enters; the uptrend failing disarms; long -> the pullback low is frozen; a close below the fast average
    exits, and the exit bar may arm a new pullback at once (a fresh episode). Returns ``(desired, pullback_low)``; the pullback
    low is NaN while flat and unarmed, the current episode's low while armed, and the entry's low while long.
    """
    n = len(low)
    desired = np.zeros(n, dtype=bool)
    pb_low = np.full(n, np.nan)
    state = 0  # 0 flat and unarmed, 1 armed (flat, a pullback seen), 2 long
    current = np.nan
    for i in range(n):
        if state == 2:
            if exit_[i]:
                state, current = 0, np.nan
            else:
                desired[i] = True
                pb_low[i] = current
                continue
        if not uptrend[i]:
            state, current = 0, np.nan
            continue
        if state == 1:
            current = min(current, low[i])
            if breakout[i]:
                state = 2
                desired[i] = True
                pb_low[i] = current
                continue
        if pullback[i]:
            if state == 0:
                state, current = 1, low[i]
        pb_low[i] = current
    return desired, pb_low


class TrendPullback(ResearchStrategy):
    """S7: trend-pullback continuation with the pullback-low stop (plan section 5, item 1); a fixed rule."""

    warmup_days = float(TREND_SLOW_DAYS)

    def __init__(self, *, key: str = "S7", pullback: str = "sma", pullback_days: int = PULLBACK_SMA_DAYS,
                 stop_floor_atr: float = STOP_FLOOR_ATR, fixed_bracket: str = "none", variant_label: str = "") -> None:
        if pullback not in ("sma", "ema"):
            raise ValueError("pullback must be 'sma' or 'ema'")
        self.key = key
        self.pullback_kind = pullback
        #: The exit bracket this fixed rule is pre-registered with (``none`` = the rule's own exit and stop only; ``trail3`` = the
        #: protocol's wide trailing stop). Informational: the runner and the fleet apply it through the ``bracket`` parameter.
        self.fixed_bracket = fixed_bracket
        avg = "simple" if pullback == "sma" else "exponential"
        self.label = (f"trend-pullback continuation: uptrend (close above its {TREND_SLOW_DAYS}-day average, {TREND_FAST_DAYS}-day above "
                      f"{TREND_SLOW_DAYS}-day), pullback below the {pullback_days}-day {avg} average, entry on a close above the previous bar's "
                      f"high, stop under the pullback low floored at {stop_floor_atr:g} x ATR({ATR_WINDOW}), exit on a close below the "
                      f"{TREND_FAST_DAYS}-day average" + (f" ({variant_label})" if variant_label else ""))
        self.default_params = {"trend_fast_days": TREND_FAST_DAYS, "trend_slow_days": TREND_SLOW_DAYS, "pullback_days": int(pullback_days),
                               "atr_window": ATR_WINDOW, "atr_floor_mult": float(stop_floor_atr)}
        # One value per parameter: nothing to select; the robustness replay perturbs each by +-30 % (the ATR window is a default, as for S1/S2).
        self.grid = {"trend_fast_days": [TREND_FAST_DAYS], "trend_slow_days": [TREND_SLOW_DAYS], "pullback_days": [int(pullback_days)],
                     "atr_floor_mult": [float(stop_floor_atr)]}

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        tf = context.timeframe
        close, high, low = df["close"].astype(float), df["high"].astype(float), df["low"].astype(float)
        fast_w = max(2, days_to_bars(float(p["trend_fast_days"]), tf))
        slow_w = max(2, days_to_bars(float(p["trend_slow_days"]), tf))
        pb_w = max(2, days_to_bars(float(p["pullback_days"]), tf))
        sma_fast = features.sma(close, fast_w)
        sma_slow = features.sma(close, slow_w)
        pb_line = features.sma(close, pb_w) if self.pullback_kind == "sma" else features.ema(close, pb_w)
        atr = features.atr(high, low, close, int(p["atr_window"]))
        uptrend = ((close > sma_slow) & (sma_fast > sma_slow)).fillna(False).to_numpy(dtype=bool)
        pullback = (close < pb_line).fillna(False).to_numpy(dtype=bool)
        breakout = (close > high.shift(1)).fillna(False).to_numpy(dtype=bool)
        exit_ = (close < sma_fast).fillna(False).to_numpy(dtype=bool)
        desired, pb_low = pullback_state(uptrend, pullback, breakout, exit_, low.to_numpy(dtype=float))
        floor = atr.to_numpy(dtype=float) * float(p["atr_floor_mult"])
        under_low = close.to_numpy(dtype=float) - pb_low
        stop = np.where(np.isfinite(pb_low), np.fmax(under_low, floor), floor)
        desired_s = pd.Series(desired, index=df.index)
        strength = finite_or_nan((close - sma_fast) / atr.replace(0.0, np.nan)).where(desired_s)
        return SignalFrame(desired=desired_s, stop_distance=finite_or_nan(pd.Series(stop, index=df.index)), strength=strength)


class SlowBreakout(ResearchStrategy):
    """S8: a slow Turtle System 2 breakout with Garner's wide stop (plan section 5, item 2); a fixed rule."""

    def __init__(self, *, key: str = "S8", entry_days: int = BREAKOUT_ENTRY_DAYS, exit_days: int = BREAKOUT_EXIT_DAYS,
                 atr_mult: float = BREAKOUT_STOP_ATR, variant_label: str = "") -> None:
        self.key = key
        self.fixed_bracket = "none"
        self.label = (f"slow breakout (Turtle System 2): entry on a close above the prior {entry_days}-day high, exit on a close below the prior "
                      f"{exit_days}-day low, {atr_mult:g} x ATR({ATR_WINDOW}) stop, no adds, no filters" + (f" ({variant_label})" if variant_label else ""))
        self.default_params = {"entry_days": int(entry_days), "exit_days": int(exit_days), "atr_window": ATR_WINDOW, "atr_mult": float(atr_mult)}
        self.grid = {"entry_days": [int(entry_days)], "exit_days": [int(exit_days)], "atr_mult": [float(atr_mult)]}
        self.warmup_days = float(max(entry_days, exit_days))

    def build(self, df: pd.DataFrame, params: Mapping[str, Any], context: FeatureContext) -> SignalFrame:
        p = self.params_with_defaults(params)
        tf = context.timeframe
        close, high, low = df["close"].astype(float), df["high"].astype(float), df["low"].astype(float)
        dh = features.donchian_high(high, max(1, days_to_bars(float(p["entry_days"]), tf)))
        dl = features.donchian_low(low, max(1, days_to_bars(float(p["exit_days"]), tf)))
        atr = features.atr(high, low, close, int(p["atr_window"]))
        entries = (close > dh).fillna(False)
        exits = (close < dl).fillna(False)
        desired = state_from_events(entries, exits)
        strength = finite_or_nan((close - dh) / atr.replace(0.0, np.nan)).where(entries)
        return SignalFrame(desired=desired, stop_distance=finite_or_nan(atr * float(p["atr_mult"])), strength=strength)


__all__ = ["ATR_WINDOW", "BREAKOUT_ENTRY_DAYS", "BREAKOUT_EXIT_DAYS", "BREAKOUT_STOP_ATR", "GARNER_ENTRY_DAYS", "GARNER_EXIT_DAYS", "PULLBACK_EMA_DAYS",
           "PULLBACK_SMA_DAYS", "STOP_FLOOR_ATR", "STOP_FLOOR_ATR_WIDE", "SlowBreakout", "TRAIL_BRACKET", "TREND_FAST_DAYS", "TREND_SLOW_DAYS",
           "TrendPullback", "pullback_state"]
