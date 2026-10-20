"""Performance metrics, multiple-testing corrections — all over SIMULATED results."""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

EULER_GAMMA = 0.5772156649015329


# -- normal distribution helpers (no scipy dependency) --------------------------

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Acklam's rational approximation of the inverse normal CDF (|err| < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


# -- equity-curve metrics -------------------------------------------------------

def max_drawdown(equity: np.ndarray) -> float:
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(eq)
    dd = eq / peaks - 1.0
    return float(-dd.min())


def bar_returns(equity: np.ndarray) -> np.ndarray:
    eq = np.asarray(equity, dtype=float)
    if eq.size < 2:
        return np.zeros(0)
    return eq[1:] / eq[:-1] - 1.0


def sharpe(returns: np.ndarray, periods_per_year: float) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(periods_per_year)) if sd > 0 else 0.0


def sortino(returns: np.ndarray, periods_per_year: float) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    downside = np.minimum(r, 0.0)
    dd = math.sqrt(float((downside ** 2).mean()))
    return float(r.mean() / dd * math.sqrt(periods_per_year)) if dd > 0 else 0.0


def cagr(equity: np.ndarray, periods_per_year: float) -> float:
    eq = np.asarray(equity, dtype=float)
    if eq.size < 2 or eq[0] <= 0:
        return 0.0
    years = (eq.size - 1) / periods_per_year
    if years <= 0:
        return 0.0
    ratio = eq[-1] / eq[0]
    return float(ratio ** (1.0 / years) - 1.0) if ratio > 0 else -1.0


def equity_metrics(equity: np.ndarray, periods_per_year: float) -> Dict[str, float]:
    eq = np.asarray(equity, dtype=float)
    r = bar_returns(eq)
    total = float(eq[-1] / eq[0] - 1.0) if eq.size and eq[0] > 0 else 0.0
    mdd = max_drawdown(eq)
    growth = cagr(eq, periods_per_year)
    return {
        "total_return": total,
        "cagr": growth,
        "ann_vol": float(r.std(ddof=1) * math.sqrt(periods_per_year)) if r.size > 1 else 0.0,
        "sharpe": sharpe(r, periods_per_year),
        "sortino": sortino(r, periods_per_year),
        "max_drawdown": mdd,
        "calmar": float(growth / mdd) if mdd > 0 else 0.0,
        "bars": int(eq.size),
    }


# -- trade metrics ------------------------------------------------------------

def trade_metrics(trades: pd.DataFrame, *, init_cash: float, n_bars: int, periods_per_year: float) -> Dict[str, float]:
    n = int(len(trades))
    if n == 0:
        return {"n_trades": 0, "trades_per_year": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "avg_win": 0.0,
                "avg_loss": 0.0, "expectancy": 0.0, "avg_bars_held": 0.0, "fees_total": 0.0, "fees_pct_of_start": 0.0,
                "fees_pct_per_year": 0.0, "turnover_notional": 0.0}
    pnl = trades["pnl"].to_numpy(dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    gross_profit, gross_loss = float(wins.sum()), float(-losses.sum())
    years = n_bars / periods_per_year if periods_per_year > 0 else 0.0
    notional = float((trades["entry_price"] * trades["quantity"]).sum() + (trades["exit_price"] * trades["quantity"]).sum())
    return {
        "n_trades": n,
        "trades_per_year": float(n / years) if years > 0 else 0.0,
        "win_rate": float(len(wins) / n),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
        "avg_win": float(wins.mean()) if wins.size else 0.0,
        "avg_loss": float(losses.mean()) if losses.size else 0.0,
        "expectancy": float(pnl.mean()),
        "avg_bars_held": float(trades["bars_held"].mean()),
        "fees_total": float(trades["fees"].sum()),
        "fees_pct_of_start": float(trades["fees"].sum() / init_cash),
        "fees_pct_per_year": float(trades["fees"].sum() / init_cash / years) if years > 0 else 0.0,
        "turnover_notional": notional / init_cash,
    }


def summarize_combo(equity: np.ndarray, trades: pd.DataFrame, exposure: float, *, init_cash: float, periods_per_year: float) -> Dict[str, float]:
    out = equity_metrics(equity, periods_per_year)
    out.update(trade_metrics(trades, init_cash=init_cash, n_bars=len(equity), periods_per_year=periods_per_year))
    out["exposure"] = float(exposure)
    return out


# -- multiple testing ----------------------------------------------------------

def probabilistic_sharpe_ratio(sr: float, sr_benchmark: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """PSR = P[true SR > benchmark] (Bailey & López de Prado); SR per observation period."""
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return 0.0
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return norm_cdf(z)


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum SR among ``n_trials`` independent zero-skill trials (False Strategy Theorem)."""
    if n_trials <= 1 or sr_variance <= 0:
        return 0.0
    sd = math.sqrt(sr_variance)
    return sd * ((1 - EULER_GAMMA) * norm_ppf(1 - 1.0 / n_trials) + EULER_GAMMA * norm_ppf(1 - 1.0 / (n_trials * math.e)))


def deflated_sharpe_ratio(
    observed_sr: float,
    trial_sharpes: Sequence[float],
    n_obs: int,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> Dict[str, float]:
    """Deflated Sharpe Ratio: PSR against the SR expected from the best of N trials.

    ``observed_sr`` and ``trial_sharpes`` are per-period (non-annualized) Sharpe
    ratios of the selected configuration and of every configuration tried.
    """
    trials = np.asarray([s for s in trial_sharpes if np.isfinite(s)], dtype=float)
    n_trials = int(trials.size)
    sr_var = float(trials.var(ddof=1)) if n_trials > 1 else 0.0
    sr0 = expected_max_sharpe(n_trials, sr_var)
    return {
        "n_trials": n_trials,
        "sr_variance": sr_var,
        "expected_max_sr": sr0,
        "dsr": probabilistic_sharpe_ratio(observed_sr, sr0, n_obs, skew, kurt),
    }


def return_moments(returns: np.ndarray) -> Dict[str, float]:
    r = np.asarray(returns, dtype=float)
    if r.size < 3 or r.std() == 0:
        return {"skew": 0.0, "kurt": 3.0}
    z = (r - r.mean()) / r.std()
    return {"skew": float((z ** 3).mean()), "kurt": float((z ** 4).mean())}


def yearly_returns(equity: pd.Series) -> pd.Series:
    """Calendar-year returns of an equity series indexed by UTC timestamps."""
    if equity.empty:
        return pd.Series(dtype=float)
    yearly_last = equity.groupby(equity.index.year).last()
    prev = yearly_last.shift(1)
    prev.iloc[0] = equity.iloc[0]
    return yearly_last / prev - 1.0
