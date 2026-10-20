"""Sizing and risk overlays for the research engine (SIMULATION ONLY).

Three deterministic, strictly backward-looking overlays scale a candidate's
exposure without touching its entry/exit rule:

- **Volatility targeting** — ``fraction = clamp(target_vol / realized_vol, 0, cap)``.
  Long-only spot, no leverage, so the cap is 1.0 (100 % of equity). While the
  realized-vol window is still warming up the fraction is NaN, which the
  engine treats as "no entry".
- **Crash-state de-risking** (Howden & Andreev, SSRN 2026) — when the close is
  more than ``crash_dd`` below its rolling ``crash_window`` peak the fraction
  is halved (``mode="half"``) or zeroed (``mode="zero"``).
- **Drawdown ladder** on the strategy's own equity — a state machine applied
  inside the engine loop: drawdown >= ``half_dd`` -> half size, >= ``flat_dd``
  -> flat. Half is released once the drawdown is back under ``release_dd``
  (default half of ``half_dd``, a hysteresis band) or on a new equity high.
  Flat is released on a new equity high or after ``recovery_bars`` bars, when
  the reference peak is reset to the current equity (cooling-off, then
  re-arm).

Every series produced here uses only bars up to and including the current
one; the engine applies the value computed at bar ``i-1`` to the execution at
bar ``i`` (next open), exactly like the strategy signals.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research import features
from research.strategies.base import days_to_bars

LADDER_MULTIPLIERS = np.array([1.0, 0.5, 0.0])  # level 0 = full, 1 = half, 2 = flat


# -- drawdown ladder ----------------------------------------------------------

@dataclass(frozen=True)
class LadderConfig:
    half_dd: float = 0.05
    flat_dd: float = 0.10
    recovery_bars: int = 120
    release_dd: Optional[float] = None  # default: half_dd / 2

    def __post_init__(self) -> None:
        if not (0.0 < self.half_dd < self.flat_dd < 1.0):
            raise ValueError("need 0 < half_dd < flat_dd < 1")
        if int(self.recovery_bars) <= 0:
            raise ValueError("recovery_bars must be positive")
        if self.release_dd is not None and not (0.0 <= self.release_dd < self.half_dd):
            raise ValueError("release_dd must be in [0, half_dd)")

    @property
    def release(self) -> float:
        return self.half_dd / 2.0 if self.release_dd is None else float(self.release_dd)

    def to_dict(self) -> Dict[str, float]:
        return {"half_dd": self.half_dd, "flat_dd": self.flat_dd, "recovery_bars": int(self.recovery_bars),
                "release_dd": self.release}


def ladder_step(
    level: np.ndarray, bars_flat: np.ndarray, peak: np.ndarray, equity: np.ndarray, cfg: LadderConfig
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Advance the ladder state by one bar, after that bar's equity is known.

    Vectorized over columns. Returns ``(level, bars_flat, peak)``. The
    multiplier to apply to the *next* bar is ``LADDER_MULTIPLIERS[level]``.
    """
    level = np.asarray(level, dtype=np.int64)
    bars_flat = np.asarray(bars_flat, dtype=np.int64)
    equity = np.asarray(equity, dtype=float)
    peak = np.maximum(np.asarray(peak, dtype=float), equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, 1.0 - equity / peak, 0.0)
    # Escalate.
    level = np.where(dd >= cfg.flat_dd, 2, level)
    level = np.where((dd >= cfg.half_dd) & (level < 1), 1, level)
    # Release: half -> full once the drawdown is back under the release band;
    # flat -> full on a new equity high (drawdown zero).
    level = np.where((level == 1) & (dd < cfg.release), 0, level)
    level = np.where((level == 2) & (dd <= 0.0), 0, level)
    # Flat cooling-off: after ``recovery_bars`` bars flat, reset the reference peak and re-arm.
    bars_flat = np.where(level == 2, bars_flat + 1, 0)
    reset = bars_flat >= int(cfg.recovery_bars)
    peak = np.where(reset, equity, peak)
    level = np.where(reset, 0, level)
    bars_flat = np.where(reset, 0, bars_flat)
    return level, bars_flat, peak


def ladder_multiplier_path(equity: Sequence[float], cfg: LadderConfig) -> np.ndarray:
    """Multiplier applicable to the bar AFTER each bar of ``equity`` (scalar path)."""
    eq = np.asarray(equity, dtype=float)
    out = np.ones(eq.size)
    if eq.size == 0:
        return out
    level, flat, peak = np.zeros(1, dtype=np.int64), np.zeros(1, dtype=np.int64), np.array([eq[0]])
    for i, value in enumerate(eq):
        level, flat, peak = ladder_step(level, flat, peak, np.array([value]), cfg)
        out[i] = LADDER_MULTIPLIERS[int(level[0])]
    return out


def apply_ladder_to_returns(returns: pd.Series, cfg: LadderConfig, *, start_equity: float = 1.0) -> Tuple[pd.Series, pd.Series]:
    """Scale a bar-return stream by the ladder multiplier of the PREVIOUS bar.

    Used at the portfolio level, where the sleeves' returns are already known:
    equity is rebuilt bar by bar from the scaled returns so the ladder reacts to
    its own path. Returns ``(scaled_returns, multiplier_used)``.
    """
    r = returns.astype(float).fillna(0.0).to_numpy()
    scaled = np.zeros(r.size)
    used = np.ones(r.size)
    level, flat, peak = np.zeros(1, dtype=np.int64), np.zeros(1, dtype=np.int64), np.array([float(start_equity)])
    equity = float(start_equity)
    mult = 1.0
    for i in range(r.size):
        used[i] = mult
        scaled[i] = mult * r[i]
        equity *= 1.0 + scaled[i]
        level, flat, peak = ladder_step(level, flat, peak, np.array([equity]), cfg)
        mult = float(LADDER_MULTIPLIERS[int(level[0])])
    return pd.Series(scaled, index=returns.index), pd.Series(used, index=returns.index)


# -- fraction overlays --------------------------------------------------------

def vol_target_fraction(close: pd.Series, target_vol: float, lookback: int, periods_per_year: float, *, cap: float = 1.0) -> pd.Series:
    """``clamp(target_vol / realized_vol, 0, cap)`` using only past closes (NaN while warming up)."""
    if target_vol <= 0:
        raise ValueError("target_vol must be positive")
    if int(lookback) < 2:
        raise ValueError("lookback must be at least 2 bars")
    if not (0.0 < cap <= 1.0):
        raise ValueError("cap must be in (0, 1] for long-only spot")
    vol = features.realized_vol(close.astype(float), int(lookback), periods_per_year)
    frac = target_vol / vol.replace(0.0, np.nan)
    return frac.clip(lower=0.0, upper=cap).astype(float)


def crash_multiplier(close: pd.Series, drawdown: float, window_bars: int, *, mode: str = "half") -> pd.Series:
    """1.0 normally; 0.5 (``half``) or 0.0 (``zero``) while the close is more than ``drawdown`` below its rolling peak."""
    if not (0.0 < drawdown < 1.0):
        raise ValueError("drawdown must be in (0, 1)")
    if int(window_bars) < 1:
        raise ValueError("window_bars must be positive")
    if mode not in ("half", "zero"):
        raise ValueError("mode must be 'half' or 'zero'")
    c = close.astype(float)
    peak = c.rolling(int(window_bars), min_periods=1).max()
    in_crash = ((c / peak) - 1.0) < -float(drawdown)
    return pd.Series(np.where(in_crash.fillna(False), 0.5 if mode == "half" else 0.0, 1.0), index=close.index)


@dataclass(frozen=True)
class SizingSpec:
    """One sizing configuration: fixed fraction or vol target, optional crash filter and ladder."""

    kind: str = "vol_target"  # "vol_target" | "fixed"
    fraction: float = 1.0  # fixed kind only
    target_vol: float = 0.15  # annualized
    vol_lookback: int = 30  # bars
    crash_dd: Optional[float] = None
    crash_window_days: Optional[float] = None
    crash_mode: str = "half"
    ladder: bool = False
    cap: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in ("vol_target", "fixed"):
            raise ValueError("kind must be 'vol_target' or 'fixed'")
        if self.kind == "fixed" and not (0.0 < self.fraction <= 1.0):
            raise ValueError("fixed fraction must be in (0, 1]")
        if self.kind == "vol_target" and (self.target_vol <= 0 or int(self.vol_lookback) < 2):
            raise ValueError("vol target needs target_vol > 0 and lookback >= 2")
        if (self.crash_dd is None) != (self.crash_window_days is None):
            raise ValueError("crash_dd and crash_window_days go together")
        if self.crash_dd is not None and not (0.0 < self.crash_dd < 1.0 and self.crash_window_days > 0):
            raise ValueError("crash_dd in (0, 1) and crash_window_days > 0")
        if self.crash_mode not in ("half", "zero"):
            raise ValueError("crash_mode must be 'half' or 'zero'")
        if not (0.0 < self.cap <= 1.0):
            raise ValueError("cap must be in (0, 1]")

    @property
    def label(self) -> str:
        if self.kind == "fixed":
            base = f"fixed{self.fraction * 100:.0f}"
        else:
            base = f"vt{self.target_vol * 100:.0f}/{int(self.vol_lookback)}"
        if self.crash_dd is not None:
            mode = "h" if self.crash_mode == "half" else "z"
            base += f" crash{self.crash_dd * 100:.0f}/{self.crash_window_days:g}d{mode}"
        if self.ladder:
            base += " ladder"
        return base

    def to_dict(self) -> Dict[str, object]:
        out = asdict(self)
        out["label"] = self.label
        return out


def fraction_series(df: pd.DataFrame, spec: SizingSpec, timeframe: str, periods_per_year: float) -> pd.Series:
    """Entry fraction of equity for every bar (NaN while the vol window warms up)."""
    close = df["close"].astype(float)
    if spec.kind == "fixed":
        frac = pd.Series(float(spec.fraction), index=close.index, dtype=float)
    else:
        frac = vol_target_fraction(close, spec.target_vol, spec.vol_lookback, periods_per_year, cap=spec.cap)
    if spec.crash_dd is not None:
        window = days_to_bars(float(spec.crash_window_days), timeframe)
        frac = frac * crash_multiplier(close, spec.crash_dd, window, mode=spec.crash_mode)
    return frac.clip(lower=0.0, upper=spec.cap)


def fraction_matrix(df: pd.DataFrame, specs: Sequence[SizingSpec], timeframe: str, periods_per_year: float) -> np.ndarray:
    """(n, S) matrix of entry fractions, one column per spec (the ladder is applied in the engine)."""
    n = len(df)
    out = np.full((n, len(specs)), np.nan)
    cache: Dict[Tuple, np.ndarray] = {}
    for j, spec in enumerate(specs):
        key = (spec.kind, spec.fraction, spec.target_vol, spec.vol_lookback, spec.crash_dd,
               spec.crash_window_days, spec.crash_mode, spec.cap)
        if key not in cache:
            cache[key] = fraction_series(df, spec, timeframe, periods_per_year).to_numpy(dtype=float)
        out[:, j] = cache[key]
    return out


def ladder_mask(specs: Sequence[SizingSpec]) -> np.ndarray:
    return np.array([bool(s.ladder) for s in specs], dtype=bool)


def sizing_grid(
    *,
    targets: Sequence[float] = (0.10, 0.15, 0.20, 0.25),
    lookbacks: Sequence[int] = (20, 30, 60),
    fixed: Sequence[float] = (0.25, 0.50),
    crash: Sequence[Tuple[float, float]] = ((0.10, 90.0), (0.10, 180.0), (0.15, 90.0), (0.15, 180.0), (0.20, 90.0), (0.20, 180.0)),
    crash_modes: Sequence[str] = ("half", "zero"),
    ladders: Sequence[bool] = (False, True),
) -> List[SizingSpec]:
    """The Sprint 2b sizing grid: (vol targets x lookbacks + fixed) x (no crash filter + crash x modes) x ladder."""
    bases: List[Dict] = [{"kind": "vol_target", "target_vol": t, "vol_lookback": lb} for t, lb in itertools.product(targets, lookbacks)]
    bases += [{"kind": "fixed", "fraction": f} for f in fixed]
    crash_variants: List[Dict] = [{}]
    for (dd, days), mode in itertools.product(crash, crash_modes):
        crash_variants.append({"crash_dd": dd, "crash_window_days": days, "crash_mode": mode})
    specs: List[SizingSpec] = []
    for base, cv, lad in itertools.product(bases, crash_variants, ladders):
        specs.append(SizingSpec(**base, **cv, ladder=lad))
    return specs


def find_spec(specs: Sequence[SizingSpec], label: str) -> Optional[int]:
    for j, spec in enumerate(specs):
        if spec.label == label:
            return j
    return None
