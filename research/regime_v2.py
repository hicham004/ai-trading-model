"""Regime v2: a Gaussian HMM on returns + realized vol, used as an ENTRY gate only.

Sprint 2c, item 1 (SIMULATION ONLY). Per walk-forward window the model is
fitted on the TRAIN slice only (:func:`fit_regime`); the filtered state
probabilities (:func:`bear_probability`) are then computed forward through the
train and test slices with those fixed parameters, so the probability at bar
``t`` depends only on bars ``<= t``. Two ways to act on it, both on entries
only — exits, stops and brackets never see the regime:

- ``mode="gate"``  — no NEW entry while ``P(bear) >= bear_prob_max``;
- ``mode="scale"`` — entries while ``P(bear) >= bear_prob_max`` are sized at
  ``bear_scale`` x the policy fraction (the "policy minimum").

States are ordered by their mean standardized return: the lowest-mean state
is *bear*, the highest *bull*, the rest *chop*. ``mode="none"`` reproduces the
Sprint 2b behaviour exactly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from research import features
from research.hmm import GaussianHMM
from research.strategies.base import days_to_bars

REGIME_MODES = ("none", "gate", "scale")
FEATURE_NAMES = ("log_return", "log_realized_vol")


@dataclass(frozen=True)
class RegimeV2Config:
    mode: str = "gate"
    n_states: int = 3
    vol_window_days: float = 7.0
    bear_prob_max: float = 0.5
    bear_scale: float = 0.25
    n_iter: int = 200
    tol: float = 1e-5
    min_train_bars: int = 200

    def __post_init__(self) -> None:
        if self.mode not in REGIME_MODES:
            raise ValueError(f"mode must be one of {REGIME_MODES}")
        if int(self.n_states) < 2:
            raise ValueError("n_states must be at least 2")
        if self.vol_window_days <= 0:
            raise ValueError("vol_window_days must be positive")
        if not (0.0 < self.bear_prob_max <= 1.0):
            raise ValueError("bear_prob_max must be in (0, 1]")
        if not (0.0 <= self.bear_scale <= 1.0):
            raise ValueError("bear_scale must be in [0, 1]")
        if int(self.min_train_bars) < 10:
            raise ValueError("min_train_bars must be at least 10")

    @property
    def active(self) -> bool:
        return self.mode != "none"

    @property
    def label(self) -> str:
        if self.mode == "none":
            return "no regime gate"
        base = f"hmm{self.n_states} bear>={self.bear_prob_max:g}"
        return f"{base} gate" if self.mode == "gate" else f"{base} scale{self.bear_scale:g}"

    def to_dict(self) -> Dict[str, object]:
        out = asdict(self)
        out["label"] = self.label
        return out


@dataclass
class FittedRegime:
    model: GaussianHMM
    mean: np.ndarray  # feature standardisation (train only)
    std: np.ndarray
    bear_state: int
    bull_state: int
    vol_window_bars: int
    train_bars: int
    train_bear_share: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "bear_state": int(self.bear_state),
            "bull_state": int(self.bull_state),
            "train_bars": int(self.train_bars),
            "train_bear_share": float(self.train_bear_share),
            "feature_mean": self.mean.tolist(),
            "feature_std": self.std.tolist(),
            "model": self.model.to_dict(),
        }


def regime_features(df: pd.DataFrame, timeframe: str, periods_per_year: float, cfg: RegimeV2Config) -> pd.DataFrame:
    """Per-bar (log return, log realized vol) using only bars up to and including each bar; NaN while warming up."""
    close = df["close"].astype(float)
    window = max(2, days_to_bars(cfg.vol_window_days, timeframe))
    ret = features.log_returns(close)
    vol = features.realized_vol(close, window, periods_per_year)
    out = pd.DataFrame({FEATURE_NAMES[0]: ret, FEATURE_NAMES[1]: np.log(vol.replace(0.0, np.nan))}, index=df.index)
    return out.replace([np.inf, -np.inf], np.nan)


def fit_regime(df_train: pd.DataFrame, timeframe: str, periods_per_year: float, cfg: RegimeV2Config) -> FittedRegime:
    """Fit the HMM on ``df_train`` only (standardisation statistics come from the same slice)."""
    feats = regime_features(df_train, timeframe, periods_per_year, cfg).dropna()
    if len(feats) < cfg.min_train_bars:
        raise ValueError(f"regime fit needs at least {cfg.min_train_bars} finite bars, got {len(feats)}")
    mean = feats.mean(axis=0).to_numpy(dtype=float)
    std = feats.std(axis=0, ddof=0).replace(0.0, 1.0).to_numpy(dtype=float)
    std = np.where(np.isfinite(std) & (std > 0), std, 1.0)
    X = (feats.to_numpy(dtype=float) - mean) / std
    model = GaussianHMM(n_states=cfg.n_states, n_iter=cfg.n_iter, tol=cfg.tol).fit(X)
    order = model.state_order(feature=0)
    bear, bull = int(order[0]), int(order[-1])
    alpha = model.filter(X)
    return FittedRegime(
        model=model, mean=mean, std=std, bear_state=bear, bull_state=bull,
        vol_window_bars=max(2, days_to_bars(cfg.vol_window_days, timeframe)), train_bars=int(len(feats)),
        train_bear_share=float((alpha.argmax(axis=1) == bear).mean()),
    )


def filtered_probabilities(fitted: FittedRegime, df: pd.DataFrame, timeframe: str, periods_per_year: float, cfg: RegimeV2Config) -> pd.DataFrame:
    """Forward-filtered state probabilities for every bar of ``df`` (NaN before the feature warm-up).

    The filter starts at the first finite feature row of ``df`` with the
    model's start distribution and only ever moves forward, so the row for
    bar ``t`` is a function of bars ``<= t`` and the (train-only) parameters.
    """
    feats = regime_features(df, timeframe, periods_per_year, cfg)
    finite = feats.notna().all(axis=1).to_numpy()
    out = pd.DataFrame(np.nan, index=df.index, columns=[f"state_{k}" for k in range(cfg.n_states)])
    if not finite.any():
        return out
    first = int(np.argmax(finite))
    sub = feats.iloc[first:]
    # Rows after the first finite row are finite as long as the series has no
    # internal gaps; a NaN inside is carried forward (no information bar).
    X = sub.to_numpy(dtype=float)
    X = np.where(np.isfinite(X), X, np.nan)
    if np.isnan(X).any():
        X = pd.DataFrame(X).ffill().to_numpy(dtype=float)
    X = (X - fitted.mean) / fitted.std
    alpha = fitted.model.filter(X)
    out.iloc[first:, :] = alpha
    return out


def bear_probability(fitted: FittedRegime, df: pd.DataFrame, timeframe: str, periods_per_year: float, cfg: RegimeV2Config) -> pd.Series:
    probs = filtered_probabilities(fitted, df, timeframe, periods_per_year, cfg)
    return probs.iloc[:, fitted.bear_state].rename("bear_prob")


def entry_gate_mask(bear_prob: pd.Series, cfg: RegimeV2Config) -> pd.Series:
    """True where NEW entries are allowed (``gate`` mode). Warm-up bars block entries."""
    if cfg.mode != "gate":
        return pd.Series(True, index=bear_prob.index)
    return (bear_prob.notna() & (bear_prob < cfg.bear_prob_max)).astype(bool)


def size_multiplier(bear_prob: pd.Series, cfg: RegimeV2Config) -> pd.Series:
    """Entry-fraction multiplier (``scale`` mode): ``bear_scale`` in the bear state, 1 elsewhere (and while warming up)."""
    if cfg.mode != "scale":
        return pd.Series(1.0, index=bear_prob.index)
    bear = bear_prob.notna() & (bear_prob >= cfg.bear_prob_max)
    return pd.Series(np.where(bear, float(cfg.bear_scale), 1.0), index=bear_prob.index)


def regime_summary(bear_prob: pd.Series, cfg: RegimeV2Config) -> Dict[str, float]:
    finite = bear_prob.dropna()
    if finite.empty:
        return {"bars": 0, "bear_share": 0.0, "mean_bear_prob": 0.0}
    return {
        "bars": int(len(finite)),
        "bear_share": float((finite >= cfg.bear_prob_max).mean()),
        "mean_bear_prob": float(finite.mean()),
    }
