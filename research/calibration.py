"""Calibrated confidence: map raw signal strength to historical hit-rate buckets.

The current production confidence (``0.55 + 10 × SMA gap``) is not a
probability. Here confidence is the empirical win rate of past entries whose
strength fell in the same quantile bucket, estimated on TRAINING data only.
Buckets with too few samples fall back to the pooled win rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


@dataclass
class StrengthCalibrator:
    n_bins: int = 5
    min_samples: int = 20
    edges: List[float] = field(default_factory=list)
    hit_rates: List[float] = field(default_factory=list)
    counts: List[int] = field(default_factory=list)
    pooled_hit_rate: float = 0.5
    fitted: bool = False

    def fit(self, strengths: Sequence[float], wins: Sequence[bool]) -> "StrengthCalibrator":
        s = np.asarray(strengths, dtype=float)
        w = np.asarray(wins, dtype=bool)
        mask = np.isfinite(s)
        s, w = s[mask], w[mask]
        if s.size == 0:
            self.fitted = False
            return self
        self.pooled_hit_rate = float(w.mean())
        quantiles = np.linspace(0, 1, self.n_bins + 1)[1:-1]
        edges = np.unique(np.quantile(s, quantiles))
        self.edges = [float(e) for e in edges]
        bins = np.searchsorted(edges, s, side="right")
        rates, counts = [], []
        for b in range(len(edges) + 1):
            sel = bins == b
            n = int(sel.sum())
            counts.append(n)
            rates.append(float(w[sel].mean()) if n >= self.min_samples else self.pooled_hit_rate)
        self.hit_rates, self.counts = rates, counts
        self.fitted = True
        return self

    def bucket(self, strength: float) -> int:
        return int(np.searchsorted(np.asarray(self.edges, dtype=float), strength, side="right"))

    def confidence(self, strength: float) -> float:
        if not self.fitted or not np.isfinite(strength):
            return self.pooled_hit_rate
        return self.hit_rates[self.bucket(float(strength))]

    def table(self) -> pd.DataFrame:
        if not self.fitted:
            return pd.DataFrame(columns=["bucket", "upper_edge", "n", "hit_rate"])
        uppers = list(self.edges) + [float("inf")]
        return pd.DataFrame({"bucket": range(len(uppers)), "upper_edge": uppers, "n": self.counts, "hit_rate": self.hit_rates})

    def to_dict(self) -> Dict:
        return {"n_bins": self.n_bins, "min_samples": self.min_samples, "edges": self.edges, "hit_rates": self.hit_rates,
                "counts": self.counts, "pooled_hit_rate": self.pooled_hit_rate, "fitted": self.fitted}

    @classmethod
    def from_dict(cls, data: Dict) -> "StrengthCalibrator":
        return cls(**{k: data[k] for k in ("n_bins", "min_samples", "edges", "hit_rates", "counts", "pooled_hit_rate", "fitted") if k in data})


def entry_outcomes(trades: pd.DataFrame, strength: np.ndarray, combo: int) -> tuple:
    """Strength at the decision bar (entry_i - 1) and win flag for each closed trade of ``combo``."""
    sub = trades[trades["combo"] == combo]
    if sub.empty:
        return np.zeros(0), np.zeros(0, dtype=bool)
    decision_bars = (sub["entry_i"].to_numpy(dtype=int) - 1).clip(min=0)
    col = strength[:, combo] if strength.ndim == 2 else strength
    return col[decision_bars], (sub["pnl"].to_numpy(dtype=float) > 0)
