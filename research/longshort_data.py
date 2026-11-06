"""Public data for the Phase 9 long/short design study (plan row R9, SIMULATION ONLY).

Three inputs, all public and all research features only — nothing here can
authenticate, place an order or reach a derivatives account:

- **Perpetual-swap funding.** OKX keeps only months of public funding history
  (``data/lake/derivatives/funding_rate``, since 2026-07), so the study uses
  Binance's PUBLIC USDT-margined funding history (BTCUSDT since 2019-09,
  ETHUSDT since 2019-11; collected in Sprint 2b) as the proxy for OKX's
  BTC-/ETH-USDT-SWAP funding, and measures the two against each other where
  both exist (:func:`funding_overlap`). Settlement timestamps are rounded to
  the hour (Binance stamps them a few milliseconds after the hour).
- **Funding per bar.** Every settlement is assigned to the bar during which it
  happens, a settlement exactly on a bar boundary to the bar that ENDS there
  (:func:`funding_per_bar`): the engine charges it on the position open at that
  bar's close, which is the position held at the settlement instant for a
  boundary settlement (an order "at the next open" executes after it).
- **OKX perpetual candles.** ``BTC-USDT-SWAP`` / ``ETH-USDT-SWAP`` 1H candles
  from OKX's public ``market/candles`` and ``market/history-candles``
  endpoints through the GET-only, path-allowlisted
  :class:`app.datalake.okx_public_rest.OKXPublicRest` (no headers, no keys),
  stored in the lake next to the spot candles (``candles/<SWAP>/1H``) with the
  resumable :class:`app.datalake.paging.BackwardWalker`. They are used for the
  spot-perp basis and for a replay of the short leg on the perp's own prices;
  the study's signals always come from spot candles.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa

from app.datalake.binance_public import FUNDING_PERIOD as BINANCE_FUNDING_PERIOD
from app.datalake.binance_public import SYMBOL_FOR_INSTRUMENT
from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest
from app.datalake.paging import BackwardWalker, Row, WalkReport
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE, to_ms, write_partitioned
from research.data import load_candles, load_external_series, load_okx_series
from research.paper_fleet.data import parse_candle_rows
from research.resample import resample_ohlcv

SWAP_FOR: Dict[str, str] = {"BTC-USDT": "BTC-USDT-SWAP", "ETH-USDT": "ETH-USDT-SWAP"}
PERP_SOURCE_BAR = "1H"
CANDLES_PATH = "/api/v5/market/candles"
HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
NEWEST_LIMIT = 300
HISTORY_LIMIT = 100
DEFAULT_PERP_START = datetime(2019, 12, 1, tzinfo=timezone.utc)
FUNDING_SOURCES = ("binance", "okx")


# -- funding -------------------------------------------------------------------------

def _utc_ns(index) -> pd.DatetimeIndex:
    """A tz-aware UTC index in nanoseconds, whatever the resolution it was stored with."""
    idx = pd.DatetimeIndex(index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return idx.as_unit("ns")


def _round_to_hour(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return _utc_ns(index).round("h")


def load_funding(layout: LakeLayout, instrument: str, *, source: str = "binance") -> pd.Series:
    """Funding rate per settlement (index: settlement time rounded to the hour, UTC). Empty when unavailable."""
    if source not in FUNDING_SOURCES:
        raise ValueError(f"funding source must be one of {FUNDING_SOURCES}")
    if source == "binance":
        symbol = SYMBOL_FOR_INSTRUMENT.get(instrument)
        frame = None if symbol is None else load_external_series(layout, "binance", "funding_rate", symbol, BINANCE_FUNDING_PERIOD, ["funding_rate"])
    else:
        swap = SWAP_FOR.get(instrument)
        frame = None if swap is None else load_okx_series(layout, "funding_rate", swap, "8H", ["funding_rate"])
    if frame is None or frame.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC", name="ts"), name="funding_rate")
    series = frame["funding_rate"].astype(float)
    series.index = _round_to_hour(series.index)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    if not np.all(np.isfinite(series.to_numpy())):
        raise ValueError(f"non-finite funding rates for {instrument} ({source})")
    series.index.name = "ts"
    series.name = "funding_rate"
    return series


def funding_per_bar(index: pd.DatetimeIndex, settlements: pd.Series) -> np.ndarray:
    """Sum of the funding rates settled during each bar of ``index`` (bar open times, sorted).

    A settlement at time ``s`` belongs to bar ``i`` when ``open[i] < s <= open[i+1]``
    (a boundary settlement to the bar that ends there); settlements at or before the
    first open, or after the last bar's open, are dropped. Returns an (n,) array.
    """
    idx = _utc_ns(index)
    n = len(idx)
    out = np.zeros(n)
    if n == 0 or settlements is None or len(settlements) == 0:
        return out
    if not idx.is_monotonic_increasing:
        raise ValueError("bar index must be sorted")
    # Both sides in UTC nanoseconds: the lake stores milliseconds, pandas defaults to nanoseconds.
    opens = idx.asi8
    times = _utc_ns(settlements.index).asi8
    rates = settlements.to_numpy(dtype=float)
    pos = np.searchsorted(opens, times, side="left") - 1
    last_end = opens[-1] + (opens[-1] - opens[-2] if n > 1 else 0)
    keep = (pos >= 0) & (times <= last_end)
    np.add.at(out, pos[keep], rates[keep])
    return out


def funding_coverage(index: pd.DatetimeIndex, settlements: pd.Series) -> float:
    """Share of bars after the first settlement that are covered by the funding series (reporting aid)."""
    if len(index) == 0 or settlements is None or len(settlements) == 0:
        return 0.0
    idx = pd.DatetimeIndex(index)
    first, last = settlements.index.min(), settlements.index.max()
    inside = (idx >= first) & (idx <= last)
    return float(inside.mean())


def funding_by_year(settlements: pd.Series, *, start: Optional[pd.Timestamp] = None, end: Optional[pd.Timestamp] = None) -> Dict[int, Dict[str, float]]:
    """Per calendar year: settlements, annualized mean (mean x settlements per year), share negative, extremes,
    and the year's summed rate (what a 1x long held through every settlement paid, in % of notional)."""
    s = settlements
    if start is not None:
        s = s[s.index >= start]
    if end is not None:
        s = s[s.index < end]
    out: Dict[int, Dict[str, float]] = {}
    for year, g in s.groupby(s.index.year):
        days = max(1.0, (g.index[-1] - g.index[0]).total_seconds() / 86_400.0)
        per_year = len(g) / days * 365.25
        out[int(year)] = {
            "settlements": int(len(g)),
            "annualized_mean": float(g.mean() * per_year),
            "summed": float(g.sum()),
            "share_negative": float((g < 0).mean()),
            "min": float(g.min()),
            "max": float(g.max()),
            "p01": float(g.quantile(0.01)),
            "p99": float(g.quantile(0.99)),
        }
    return out


def funding_overlap(layout: LakeLayout, instrument: str) -> Dict[str, float]:
    """OKX's own funding against the Binance proxy over the months both exist (settlements matched by hour)."""
    okx = load_funding(layout, instrument, source="okx")
    binance = load_funding(layout, instrument, source="binance")
    joined = pd.concat([binance.rename("binance"), okx.rename("okx")], axis=1, join="inner").dropna()
    if joined.empty:
        return {"n": 0}
    diff = joined["okx"] - joined["binance"]
    return {
        "n": int(len(joined)),
        "start": joined.index[0].isoformat(),
        "end": joined.index[-1].isoformat(),
        "correlation": float(joined.corr().iloc[0, 1]) if len(joined) > 2 else float("nan"),
        "mean_okx": float(joined["okx"].mean()),
        "mean_binance": float(joined["binance"].mean()),
        "annualized_mean_okx": float(joined["okx"].mean() * 3 * 365.25),
        "annualized_mean_binance": float(joined["binance"].mean() * 3 * 365.25),
        "annualized_mean_difference": float(diff.mean() * 3 * 365.25),
        "mean_abs_difference": float(diff.abs().mean()),
        "same_sign_share": float((np.sign(joined["okx"]) == np.sign(joined["binance"])).mean()),
    }


# -- OKX perpetual candles (public) ----------------------------------------------------

class _PerpCandleSource:
    """``PageSource`` over the public candle endpoints for one allowlisted perpetual swap (1H)."""

    def __init__(self, rest: OKXPublicRest, swap: str) -> None:
        if swap not in SWAP_FOR.values():
            raise ValueError(f"only {sorted(SWAP_FOR.values())} are collected; got {swap!r}")
        self._rest = rest
        self._swap = swap

    def _rows(self, data) -> Sequence[Row]:
        frame = parse_candle_rows(data, self._swap)
        return [(int(ts.value // 1_000_000), (ts, row)) for ts, row in zip(frame.index, frame.itertuples(index=False))]

    def fetch_newest(self) -> Sequence[Row]:
        return self._rows(self._rest.get(CANDLES_PATH, {"instId": self._swap, "bar": PERP_SOURCE_BAR, "limit": NEWEST_LIMIT}))

    def fetch_older(self, cursor_ms: int) -> Sequence[Row]:
        return self._rows(self._rest.get(HISTORY_CANDLES_PATH, {"instId": self._swap, "bar": PERP_SOURCE_BAR, "after": int(cursor_ms),
                                                                "limit": HISTORY_LIMIT}))


def _write_perp_rows(layout: LakeLayout, swap: str, rows: Sequence[Row]) -> int:
    if not rows:
        return 0
    stamps = [payload[0].to_pydatetime() for _, payload in rows]
    values = [payload[1] for _, payload in rows]
    table = pa.table(
        {
            "open_time": pa.array(stamps, type=TS_TYPE),
            "instrument": pa.array([swap] * len(rows), type=pa.string()),
            "timeframe": pa.array([PERP_SOURCE_BAR] * len(rows), type=pa.string()),
            "open": pa.array([float(v.open) for v in values], type=pa.float64()),
            "high": pa.array([float(v.high) for v in values], type=pa.float64()),
            "low": pa.array([float(v.low) for v in values], type=pa.float64()),
            "close": pa.array([float(v.close) for v in values], type=pa.float64()),
            "volume": pa.array([float(v.volume) for v in values], type=pa.float64()),
            "confirmed": pa.array([True] * len(rows), type=pa.bool_()),
        },
        schema=CANDLE_SCHEMA,
    )
    res = write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA,
                            file_for_year=lambda y: layout.candles_file(swap, PERP_SOURCE_BAR, y))
    return int(res.added)


@dataclass
class PerpCollectReport:
    swap: str
    walk: WalkReport
    added: int


def collect_perp_candles(
    layout: LakeLayout,
    instrument: str,
    *,
    rest: Optional[OKXPublicRest] = None,
    start: datetime = DEFAULT_PERP_START,
    max_pages: Optional[int] = None,
    sleep_seconds: float = 0.15,
    sleep: Callable[[float], None] = time.sleep,
) -> PerpCollectReport:
    """One resumable session collecting the perpetual swap's public 1H candles for ``instrument`` (BTC-USDT / ETH-USDT)."""
    swap = SWAP_FOR.get(instrument)
    if swap is None:
        raise ValueError(f"no perpetual swap mapped for {instrument!r}; allowed: {sorted(SWAP_FOR)}")
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    added = 0

    def on_page(rows: Sequence[Row]) -> None:
        nonlocal added
        added += _write_perp_rows(layout, swap, rows)

    walker = BackwardWalker(_PerpCandleSource(rest or OKXPublicRest(), swap), state_path=layout.state_file("candles", swap, PERP_SOURCE_BAR),
                            start_ms=to_ms(start), on_page=on_page, max_pages=max_pages, sleep_seconds=sleep_seconds, sleep=sleep)
    return PerpCollectReport(swap=swap, walk=walker.run(), added=added)


def load_perp_candles(layout: LakeLayout, instrument: str, timeframe: str) -> pd.DataFrame:
    """The perpetual swap's candles for ``instrument`` at ``timeframe``, rebuilt from its 1H candles on the UTC clock."""
    swap = SWAP_FOR.get(instrument)
    if swap is None:
        raise ValueError(f"no perpetual swap mapped for {instrument!r}")
    base = load_candles(layout, swap, PERP_SOURCE_BAR)
    if base.empty or timeframe == PERP_SOURCE_BAR:
        return base
    return resample_ohlcv(base, timeframe, source_timeframe=PERP_SOURCE_BAR)


def align_perp(spot: pd.DataFrame, perp: pd.DataFrame) -> Dict[str, object]:
    """Perp OHLC aligned onto the spot index. Returns arrays plus the share of spot bars the perp covers.

    Bars the perp lacks are filled from spot (and counted), so a replay never invents a price."""
    joined = perp.reindex(spot.index)
    missing = joined["close"].isna().to_numpy() if len(joined) else np.zeros(0, dtype=bool)
    filled = joined.copy()
    for col in ("open", "high", "low", "close"):
        filled[col] = filled[col].where(~missing, spot[col])
    return {
        "open": filled["open"].to_numpy(dtype=float), "high": filled["high"].to_numpy(dtype=float),
        "low": filled["low"].to_numpy(dtype=float), "close": filled["close"].to_numpy(dtype=float),
        "coverage": float((~missing).mean()) if len(missing) else 0.0, "missing": int(missing.sum()),
    }


def basis_stats(spot: pd.DataFrame, perp: pd.DataFrame, *, start: Optional[pd.Timestamp] = None, end: Optional[pd.Timestamp] = None) -> Dict[str, float]:
    """Perp close / spot close - 1 at matching bar closes (positive = the perp trades above spot)."""
    joined = pd.concat([spot["close"].rename("spot"), perp["close"].rename("perp")], axis=1, join="inner").dropna()
    if start is not None:
        joined = joined[joined.index >= start]
    if end is not None:
        joined = joined[joined.index < end]
    if joined.empty:
        return {"n": 0}
    basis = joined["perp"] / joined["spot"] - 1.0
    return {
        "n": int(len(basis)), "start": joined.index[0].isoformat(), "end": joined.index[-1].isoformat(),
        "mean": float(basis.mean()), "median": float(basis.median()), "std": float(basis.std(ddof=0)),
        "p01": float(basis.quantile(0.01)), "p99": float(basis.quantile(0.99)), "min": float(basis.min()), "max": float(basis.max()),
        "share_abs_over_0_5pct": float((basis.abs() > 0.005).mean()),
    }
