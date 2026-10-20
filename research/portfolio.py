"""Portfolio combination of sleeve return streams (SIMULATION ONLY).

A *sleeve* is one (strategy, asset, timeframe, sizing) configuration's
out-of-sample bar-return stream. Sleeves can live on different bar clocks
(4H vs 6H), so everything is compounded into UTC calendar-day returns first.
Two combination rules:

- ``buckets`` (default) — every sleeve compounds its own share of the
  starting capital and the portfolio is the sum of the buckets. That is what a
  per-strategy capital allocation without rebalancing does, and it needs no
  cross-sleeve trading.
- ``daily`` — constant weights rebalanced every day (a reference, not a plan).

"Equal risk" weights are proportional to the inverse of each sleeve's realized
daily volatility over the SAME out-of-sample sample, which is a mild
in-sample choice; the report labels it as such. The portfolio-level drawdown
ladder scales the next day's portfolio return by the multiplier of the
previous day (``research.sizing.apply_ladder_to_returns``) — an estimate of
what cutting every sleeve's size together would have done.

Sprint 2c adds **portfolio-level sizing** (:func:`combine_sized`): sleeves are
fed in at FULL size and the portfolio layer does all the sizing — trailing
inverse-vol weights (past days only), one portfolio vol target applied to the
next day, and one portfolio drawdown ladder with a 15 % budget — so the
BTC+ETH × S1/S2/S4 sleeves are sized jointly against one drawdown budget
instead of one each.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

import numpy as np
import pandas as pd

from research.metrics import equity_metrics, yearly_returns
from research.sizing import LadderConfig, apply_ladder_to_returns

DAYS_PER_YEAR = 365.25


def to_daily_returns(bar_returns: pd.Series) -> pd.Series:
    """Compound bar returns into UTC calendar-day returns."""
    r = bar_returns.astype(float).fillna(0.0)
    if r.empty:
        return pd.Series(dtype=float)
    days = r.index.tz_convert("UTC").floor("D")
    growth = (1.0 + r).groupby(days).prod()
    out = growth - 1.0
    out.index.name = "day"
    return out


def align_sleeves(sleeves: Mapping[str, pd.Series]) -> pd.DataFrame:
    """Daily returns of every sleeve on the union of days; days a sleeve has no data are 0 (cash)."""
    daily = {name: to_daily_returns(series) for name, series in sleeves.items()}
    frame = pd.DataFrame(daily).sort_index()
    return frame.fillna(0.0)


def equal_weights(columns) -> pd.Series:
    cols = list(columns)
    return pd.Series(1.0 / len(cols), index=cols) if cols else pd.Series(dtype=float)


def equal_risk_weights(daily: pd.DataFrame) -> pd.Series:
    """Weights proportional to 1 / realized daily vol (full-sample; flagged as in-sample in the report)."""
    vol = daily.std(ddof=1)
    inv = (1.0 / vol.replace(0.0, np.nan)).fillna(0.0)
    if inv.sum() <= 0:
        return equal_weights(daily.columns)
    return inv / inv.sum()


@dataclass
class PortfolioResult:
    name: str
    weights: Dict[str, float]
    rebalance: str
    daily_returns: pd.Series
    equity: pd.Series
    metrics: Dict[str, float]
    correlation: pd.DataFrame
    sleeve_metrics: Dict[str, Dict[str, float]]
    diversification_ratio: float
    ladder: Optional[Dict[str, float]] = None
    ladder_used: Optional[pd.Series] = None
    yearly: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    scale_used: Optional[pd.Series] = None  # portfolio vol-target scale actually applied (Sprint 2c)
    sizing: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "weights": {k: float(v) for k, v in self.weights.items()},
            "rebalance": self.rebalance,
            "metrics": {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in self.metrics.items()},
            "correlation": {a: {b: (None if not np.isfinite(v) else float(v)) for b, v in row.items()} for a, row in self.correlation.to_dict().items()},
            "sleeve_metrics": self.sleeve_metrics,
            "diversification_ratio": None if not np.isfinite(self.diversification_ratio) else float(self.diversification_ratio),
            "ladder": self.ladder,
            "ladder_share_reduced": None if self.ladder_used is None else float((self.ladder_used < 1.0).mean()),
            "yearly": {int(k): float(v) for k, v in self.yearly.items()},
            "days": int(len(self.daily_returns)),
            "sizing": self.sizing,
            "avg_scale": None if self.scale_used is None else float(self.scale_used.mean()),
        }


def combine(
    daily: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    name: str,
    rebalance: str = "buckets",
    ladder: Optional[LadderConfig] = None,
) -> PortfolioResult:
    """Combine aligned daily sleeve returns under ``weights`` (sum to 1, non-negative)."""
    if daily.empty or len(daily.columns) == 0:
        raise ValueError("no sleeves to combine")
    w = pd.Series({k: float(weights[k]) for k in daily.columns})
    if abs(float(w.sum()) - 1.0) > 1e-9 or bool((w < 0).any()):
        raise ValueError("weights must be non-negative and sum to 1")
    if rebalance == "buckets":
        buckets = (1.0 + daily).cumprod() * w
        equity = buckets.sum(axis=1)
        port_r = equity / equity.shift(1).fillna(1.0) - 1.0
    elif rebalance == "daily":
        port_r = (daily * w).sum(axis=1)
        equity = (1.0 + port_r).cumprod()
    else:
        raise ValueError("rebalance must be 'buckets' or 'daily'")
    ladder_used = None
    if ladder is not None:
        port_r, ladder_used = apply_ladder_to_returns(port_r, ladder)
        equity = (1.0 + port_r).cumprod()
    return _finish(name, w, rebalance, daily, port_r, equity, ladder, ladder_used)


def _finish(name, w, rebalance, daily, port_r, equity, ladder, ladder_used, scale_used=None, sizing=None) -> PortfolioResult:
    metrics = equity_metrics(np.concatenate([[1.0], equity.to_numpy(dtype=float)]), DAYS_PER_YEAR)
    metrics["positive_days_share"] = float((port_r > 0).mean()) if len(port_r) else 0.0
    sleeve_metrics = {
        k: equity_metrics(np.concatenate([[1.0], (1.0 + daily[k]).cumprod().to_numpy(dtype=float)]), DAYS_PER_YEAR)
        for k in daily.columns
    }
    corr = daily.corr()
    sleeve_vol = daily.std(ddof=1)
    port_vol = float(port_r.std(ddof=1)) if len(port_r) > 1 else 0.0
    dr = float((w * sleeve_vol).sum() / port_vol) if port_vol > 0 else float("nan")
    return PortfolioResult(
        name=name, weights=w.to_dict(), rebalance=rebalance, daily_returns=port_r, equity=equity, metrics=metrics,
        correlation=corr, sleeve_metrics=sleeve_metrics, diversification_ratio=dr,
        ladder=None if ladder is None else ladder.to_dict(), ladder_used=ladder_used, yearly=yearly_returns(equity),
        scale_used=scale_used, sizing=sizing,
    )


# -- Sprint 2c: portfolio-level sizing ----------------------------------------

def rolling_inverse_vol_weights(daily: pd.DataFrame, lookback_days: int = 60, *, min_days: int = 20) -> pd.DataFrame:
    """Per-day weights ∝ 1 / trailing realized vol, using only PAST days (shifted by one day).

    Days without enough history (or with zero vol everywhere) fall back to
    equal weights. Rows sum to 1.
    """
    if int(lookback_days) < 2:
        raise ValueError("lookback_days must be at least 2")
    vol = daily.rolling(int(lookback_days), min_periods=int(min_days)).std(ddof=1).shift(1)
    inv = 1.0 / vol.replace(0.0, np.nan)
    inv = inv.where(np.isfinite(inv))
    weights = inv.div(inv.sum(axis=1), axis=0)
    fallback = pd.DataFrame(1.0 / len(daily.columns), index=daily.index, columns=daily.columns)
    weights = weights.where(weights.notna().all(axis=1) & (inv.sum(axis=1) > 0), fallback)
    return weights.fillna(0.0)


def vol_target_scale(returns: pd.Series, target_vol: float, lookback_days: int = 30, *, cap: float = 1.0, min_days: int = 10) -> pd.Series:
    """``clamp(target / trailing realized vol, 0, cap)`` applied to the NEXT day (shifted); 1 while warming up."""
    if target_vol <= 0:
        raise ValueError("target_vol must be positive")
    if not (0.0 < cap <= 1.0):
        raise ValueError("cap must be in (0, 1] for long-only spot")
    vol = returns.rolling(int(lookback_days), min_periods=int(min_days)).std(ddof=1) * np.sqrt(DAYS_PER_YEAR)
    scale = (target_vol / vol.replace(0.0, np.nan)).clip(lower=0.0, upper=cap).shift(1)
    return scale.fillna(1.0)


def combine_sized(
    daily: pd.DataFrame,
    *,
    name: str,
    target_vol: float = 0.10,
    vol_lookback_days: int = 30,
    weight_lookback_days: int = 60,
    ladder: Optional[LadderConfig] = LadderConfig(half_dd=0.075, flat_dd=0.15, recovery_bars=30),
    cap: float = 1.0,
) -> PortfolioResult:
    """Size FULL-SIZE sleeves jointly: trailing inverse-vol weights → portfolio vol target → portfolio ladder.

    Every quantity used on day ``t`` is computed from days ``< t``; the result
    is a daily-rebalanced, long-only (scale ≤ 1) portfolio. ``daily`` holds the
    sleeves' full-size daily returns (all-in when in position).
    """
    if daily.empty or len(daily.columns) == 0:
        raise ValueError("no sleeves to combine")
    weights = rolling_inverse_vol_weights(daily, weight_lookback_days)
    raw = (daily * weights).sum(axis=1)
    scale = vol_target_scale(raw, target_vol, vol_lookback_days, cap=cap)
    port_r = raw * scale
    ladder_used = None
    if ladder is not None:
        port_r, ladder_used = apply_ladder_to_returns(port_r, ladder)
    equity = (1.0 + port_r).cumprod()
    avg_w = weights.mean(axis=0)
    sizing = {"target_vol": float(target_vol), "vol_lookback_days": int(vol_lookback_days), "weight_lookback_days": int(weight_lookback_days),
              "cap": float(cap), "ladder": None if ladder is None else ladder.to_dict()}
    return _finish(name, avg_w, "daily (trailing inverse-vol weights)", daily, port_r, equity, ladder, ladder_used, scale_used=scale, sizing=sizing)
