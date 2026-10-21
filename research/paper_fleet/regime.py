"""Regime-v2 entry gate run forward (SIMULATION ONLY), with the walk-forward's geometry.

In the walk-forward every 180-day test window used a 3-state HMM fitted on the
540 days of bars that ended 7 days (the purge) before the window, and the
filtered bear probability was run forward from the start of that train slice.
The fleet does the same on the forward clock: a fit becomes active at the
fleet's start and is replaced every 180 days by a fit on the then-latest 540
days (ending 7 days before the switch). The fitted parameters are stored in the
fleet state, so a restart reuses the same model instead of refitting.

The gate acts on ENTRIES only, exactly like the research
(:func:`research.gated_walkforward.gate_desired_matrix`): within a run of
desired bars the position may start only on a bar where ``P(bear) < 0.5``;
while the model stays the same, an open position is never closed by the gate.
A fit that fails (too few bars) blocks every entry until the next fit (fail
closed), as in the research. A refit happens when the sleeves restart their
180-day test window, flat (as every research window started); the gate state is
then recomputed under the new model from its own train start. An account whose
windows do not line up with the refits (one added to the fleet later) can hold
a position at a refit: if the new model would not have let that run start, the
position is closed at the next open, journaled with ``blocked_by: regime gate``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from research.data import bars_per_year
from research.hmm import GaussianHMM
from research.regime_v2 import FittedRegime, RegimeV2Config, bear_probability, entry_gate_mask, fit_regime, size_multiplier

from research.paper_fleet.config import PURGE_DAYS, REFIT_DAYS, TRAIN_DAYS


def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text).tz_convert("UTC") if pd.Timestamp(text).tzinfo else pd.Timestamp(text, tz="UTC")


def fitted_to_dict(fitted: FittedRegime) -> Dict[str, Any]:
    m = fitted.model
    return {
        "n_states": int(m.n_states), "n_iter": int(m.n_iter), "tol": float(m.tol), "min_var": float(m.min_var), "sticky": float(m.sticky),
        "startprob": m.startprob_.tolist(), "transmat": m.transmat_.tolist(), "means": m.means_.tolist(), "vars": m.vars_.tolist(),
        "converged": bool(m.converged_), "iterations": len(m.loglik_history_),
        "loglik": float(m.loglik_history_[-1]) if m.loglik_history_ else None,
        "feature_mean": fitted.mean.tolist(), "feature_std": fitted.std.tolist(), "bear_state": int(fitted.bear_state),
        "bull_state": int(fitted.bull_state), "vol_window_bars": int(fitted.vol_window_bars), "train_bars": int(fitted.train_bars),
        "train_bear_share": float(fitted.train_bear_share),
    }


def fitted_from_dict(data: Dict[str, Any]) -> FittedRegime:
    model = GaussianHMM(n_states=int(data["n_states"]), n_iter=int(data["n_iter"]), tol=float(data["tol"]), min_var=float(data["min_var"]),
                        sticky=float(data["sticky"]))
    model.startprob_ = np.asarray(data["startprob"], dtype=float)
    model.transmat_ = np.asarray(data["transmat"], dtype=float)
    model.means_ = np.asarray(data["means"], dtype=float)
    model.vars_ = np.asarray(data["vars"], dtype=float)
    model.converged_ = bool(data.get("converged", False))
    return FittedRegime(model=model, mean=np.asarray(data["feature_mean"], dtype=float), std=np.asarray(data["feature_std"], dtype=float),
                        bear_state=int(data["bear_state"]), bull_state=int(data["bull_state"]), vol_window_bars=int(data["vol_window_bars"]),
                        train_bars=int(data["train_bars"]), train_bear_share=float(data["train_bear_share"]))


@dataclass
class RegimeFit:
    """One fitted (or failed) regime model for one series, active over [active_from, active_until)."""

    instrument: str
    timeframe: str
    active_from: pd.Timestamp
    active_until: pd.Timestamp
    train_start: pd.Timestamp
    train_end: pd.Timestamp  # exclusive
    fitted: Optional[FittedRegime]
    error: Optional[str] = None

    @property
    def fit_id(self) -> str:
        return f"{self.instrument} {self.timeframe} {_iso(self.active_from)}"

    def to_dict(self) -> Dict[str, Any]:
        return {"instrument": self.instrument, "timeframe": self.timeframe, "active_from": _iso(self.active_from),
                "active_until": _iso(self.active_until), "train_start": _iso(self.train_start), "train_end": _iso(self.train_end),
                "fitted": None if self.fitted is None else fitted_to_dict(self.fitted), "error": self.error}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegimeFit":
        return cls(instrument=data["instrument"], timeframe=data["timeframe"], active_from=_ts(data["active_from"]),
                   active_until=_ts(data["active_until"]), train_start=_ts(data["train_start"]), train_end=_ts(data["train_end"]),
                   fitted=None if data.get("fitted") is None else fitted_from_dict(data["fitted"]), error=data.get("error"))

    def summary(self) -> Dict[str, Any]:
        out = {"fit_id": self.fit_id, "train": f"{_iso(self.train_start)} -> {_iso(self.train_end)}", "active_until": _iso(self.active_until),
               "error": self.error}
        if self.fitted is not None:
            out.update({"train_bars": self.fitted.train_bars, "train_bear_share": round(self.fitted.train_bear_share, 4),
                        "bear_state": self.fitted.bear_state, "converged": bool(self.fitted.model.converged_)})
        return out


def fit_series(bars: pd.DataFrame, instrument: str, timeframe: str, active_from: pd.Timestamp, cfg: RegimeV2Config) -> RegimeFit:
    """Fit on the bars of [active_from - purge - train, active_from - purge) only (fail closed on a failed fit)."""
    active_from = pd.Timestamp(active_from)
    train_end = active_from - pd.Timedelta(days=PURGE_DAYS)
    train_start = train_end - pd.Timedelta(days=TRAIN_DAYS)
    train = bars[(bars.index >= train_start) & (bars.index < train_end)]
    until = active_from + pd.Timedelta(days=REFIT_DAYS)
    try:
        fitted = fit_regime(train, timeframe, bars_per_year(timeframe), cfg)
    except Exception as exc:  # any failed fit fails closed: no entries until the next fit
        return RegimeFit(instrument, timeframe, active_from, until, train_start, train_end, None, error=f"{type(exc).__name__}: {exc}")
    return RegimeFit(instrument, timeframe, active_from, until, train_start, train_end, fitted)


def regime_window(bars: pd.DataFrame, fit: RegimeFit) -> pd.DataFrame:
    """The bars the filter runs over: from the fit's train start to the latest bar given."""
    return bars[bars.index >= fit.train_start]


def gate_inputs(bars: pd.DataFrame, fit: RegimeFit, cfg: RegimeV2Config) -> Dict[str, pd.Series]:
    """Bear probability, entry-allowed mask and size multiplier over the fit's window (research semantics)."""
    sub = regime_window(bars, fit)
    if fit.fitted is None:
        n = len(sub)
        ok = pd.Series(np.zeros(n, dtype=bool) if cfg.mode == "gate" else np.ones(n, dtype=bool), index=sub.index)
        mult = pd.Series(np.full(n, cfg.bear_scale) if cfg.mode == "scale" else np.ones(n), index=sub.index)
        return {"bear_prob": pd.Series(np.nan, index=sub.index), "ok": ok, "mult": mult}
    bear = bear_probability(fit.fitted, sub, fit.timeframe, bars_per_year(fit.timeframe), cfg)
    return {"bear_prob": bear, "ok": entry_gate_mask(bear, cfg), "mult": size_multiplier(bear, cfg)}


def gate_desired(desired: pd.Series, ok: pd.Series) -> pd.Series:
    """``out[i] = desired[i] & (ok[i] | out[i-1])`` from the first bar of ``ok`` (the research entries-only gate)."""
    d = desired.reindex(ok.index).fillna(False).astype(bool).to_numpy()
    allowed = ok.astype(bool).to_numpy()
    out = np.zeros(len(d), dtype=bool)
    prev = False
    for i in range(len(d)):
        prev = bool(d[i] and (allowed[i] or prev))
        out[i] = prev
    return pd.Series(out, index=ok.index)


def needs_refit(fit: Optional[RegimeFit], bar_open: pd.Timestamp) -> bool:
    return fit is None or pd.Timestamp(bar_open) >= fit.active_until
