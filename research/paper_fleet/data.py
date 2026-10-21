"""Live PUBLIC market data for the paper fleet: OKX 1H candles and OKX positioning series.

Network: only :class:`app.datalake.okx_public_rest.OKXPublicRest` — GET, an
allowlist of public path prefixes, no authentication headers, no credentials
of any kind — on four paths:

- ``/api/v5/market/candles`` (the newest confirmed 1H candles),
- ``/api/v5/market/history-candles`` (older 1H candles, to bootstrap and to fill gaps),
- ``/api/v5/public/funding-rate-history`` and
  ``/api/v5/rubik/stat/contracts/open-interest-history`` (the S5 positioning
  filter's funding rate and open interest of the BTC/ETH USDT swaps — research
  FEATURES only; the fleet never trades swaps).

Storage: the fleet's OWN small lake (``<fleet dir>/lake``, the research lake
layout), seeded once by copying the research lake's files when they exist and
topped up from OKX afterwards. The research lake is only ever read.

Bars: 4H and 6H bars are rebuilt from confirmed 1H candles on the UTC clock
(:func:`research.resample.resample_ohlcv`, complete bars only) — the research
lab's 6H construction; for 4H it matches OKX's stored 4H bars on 99.97 % of
the history. A bar exists only once all of its 1H candles are confirmed, so
the fleet never sees a forming bar.
"""

from __future__ import annotations

import math
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa

from app.datalake.derivatives import (
    FUNDING_PERIOD,
    fetch_funding_rate_history,
    fetch_open_interest_history,
    write_series,
)
from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest, PublicRestError
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE, read_candles, write_partitioned
from research.data import bars_per_year, load_okx_series
from research.resample import OHLCV, resample_ohlcv
from research.strategies.base import FeatureContext

CANDLES_PATH = "/api/v5/market/candles"
HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
SOURCE_BAR = "1H"
HOUR_MS = 3_600_000
NEWEST_LIMIT = 300
HISTORY_LIMIT = 100
SWAP_FOR = {"BTC-USDT": "BTC-USDT-SWAP", "ETH-USDT": "ETH-USDT-SWAP"}
OI_PERIOD = "1H"
POSITIONING_SOURCES = ("okx", "none")


class MarketDataError(RuntimeError):
    """The public data needed for a decision is missing or malformed."""


def _utc(ts: Any) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    return out.tz_localize("UTC") if out.tzinfo is None else out.tz_convert("UTC")


def _ms(ts: Any) -> int:
    return int(_utc(ts).value // 1_000_000)


def parse_candle_rows(rows: Sequence[Any], instrument: str) -> pd.DataFrame:
    """Confirmed, well-formed 1H candles from an OKX ``candles`` reply (any order), oldest first.

    Rows are ``[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]``; the
    forming candle (``confirm != "1"``), malformed rows, non-finite or
    non-positive prices, incoherent highs/lows and timestamps off the hour grid
    are dropped.
    """
    out: Dict[int, Tuple[float, float, float, float, float]] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 9 or str(row[8]) != "1":
            continue
        try:
            ts = int(row[0])
            o, h, low, c, vol = (float(row[i]) for i in range(1, 6))
        except (TypeError, ValueError):
            continue
        if ts <= 0 or ts % HOUR_MS != 0:
            continue
        if not all(math.isfinite(v) for v in (o, h, low, c, vol)) or min(o, h, low, c) <= 0 or vol < 0:
            continue
        if h < max(o, c, low) or low > min(o, c, h):
            continue
        out[ts] = (o, h, low, c, vol)
    if not out:
        return _empty_frame()
    keys = sorted(out)
    idx = pd.DatetimeIndex(pd.to_datetime(keys, unit="ms", utc=True), name="open_time")
    return pd.DataFrame([out[k] for k in keys], index=idx, columns=list(OHLCV)).astype(float)


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=list(OHLCV), index=pd.DatetimeIndex([], tz="UTC", name="open_time"), dtype=float)


class OkxPublicFeed:
    """The fleet's only network access: OKX PUBLIC GET endpoints through the allowlisted client."""

    def __init__(self, rest: Optional[OKXPublicRest] = None, *, sleep_seconds: float = 0.12, sleep: Callable[[float], None] = time.sleep) -> None:
        self.rest = rest or OKXPublicRest()
        self.sleep_seconds = float(sleep_seconds)
        self._sleep = sleep
        self.requests = 0

    def _get(self, path: str, params: Mapping[str, Any]) -> List[Any]:
        self.requests += 1
        data = self.rest.get(path, {k: v for k, v in params.items() if v is not None})
        if self.sleep_seconds > 0:
            self._sleep(self.sleep_seconds)
        return data

    def newest_candles(self, instrument: str) -> pd.DataFrame:
        return parse_candle_rows(self._get(CANDLES_PATH, {"instId": instrument, "bar": SOURCE_BAR, "limit": NEWEST_LIMIT}), instrument)

    def candles_before(self, instrument: str, before_ms: int) -> pd.DataFrame:
        """Up to 100 confirmed candles strictly older than ``before_ms`` (OKX ``after`` cursor)."""
        return parse_candle_rows(
            self._get(HISTORY_CANDLES_PATH, {"instId": instrument, "bar": SOURCE_BAR, "after": int(before_ms), "limit": HISTORY_LIMIT}),
            instrument,
        )

    def funding_history(self, swap: str, *, before_ms: Optional[int] = None) -> List[dict]:
        self.requests += 1
        rows = fetch_funding_rate_history(self.rest, swap, after_ms=before_ms)
        if self.sleep_seconds > 0:
            self._sleep(self.sleep_seconds)
        return rows

    def open_interest_history(self, swap: str, *, end_ms: Optional[int] = None) -> List[dict]:
        self.requests += 1
        rows = fetch_open_interest_history(self.rest, swap, OI_PERIOD, end_ms=end_ms)
        if self.sleep_seconds > 0:
            self._sleep(self.sleep_seconds)
        return rows


# -- the fleet's own lake ------------------------------------------------------


class FleetLake:
    """1H candles and OKX positioning series under ``root`` (the research lake layout)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.layout = LakeLayout(self.root)

    def seed_from(self, seed: LakeLayout, instruments: Sequence[str], since: pd.Timestamp) -> Dict[str, int]:
        """Copy the research lake's year files the fleet lake lacks (candles 1H, OKX funding/OI). Read-only on ``seed``."""
        copied: Dict[str, int] = {}
        pairs: List[Tuple[Path, Path, str]] = []
        for inst in instruments:
            pairs.append((seed.candles_dir(inst, SOURCE_BAR), self.layout.candles_dir(inst, SOURCE_BAR), f"candles {inst}"))
            swap = SWAP_FOR[inst]
            pairs.append((seed.series_dir("funding_rate", swap, FUNDING_PERIOD), self.layout.series_dir("funding_rate", swap, FUNDING_PERIOD), f"funding {swap}"))
            pairs.append((seed.series_dir("open_interest", swap, OI_PERIOD), self.layout.series_dir("open_interest", swap, OI_PERIOD), f"open interest {swap}"))
        for src, dst, label in pairs:
            if not src.exists() or (dst.exists() and any(dst.glob("*.parquet"))):
                continue
            files = [f for f in sorted(src.glob("*.parquet")) if f.stem.isdigit() and int(f.stem) >= since.year]
            if not files:
                continue
            dst.mkdir(parents=True, exist_ok=True)
            for f in files:
                shutil.copy2(f, dst / f.name)
            copied[label] = len(files)
        return copied

    def write_candles(self, instrument: str, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        table = pa.table(
            {
                "open_time": pa.array(list(frame.index.to_pydatetime()), type=TS_TYPE),
                "instrument": pa.array([instrument] * len(frame), type=pa.string()),
                "timeframe": pa.array([SOURCE_BAR] * len(frame), type=pa.string()),
                **{col: pa.array(frame[col].to_numpy(dtype=float), type=pa.float64()) for col in OHLCV},
                "confirmed": pa.array([True] * len(frame), type=pa.bool_()),
            },
            schema=CANDLE_SCHEMA,
        )
        res = write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA,
                                file_for_year=lambda y: self.layout.candles_file(instrument, SOURCE_BAR, y))
        return int(res.added)

    def read_candles(self, instrument: str, since: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        table = read_candles(self.layout, instrument, SOURCE_BAR, start=None if since is None else since.to_pydatetime())
        df = table.to_pandas()
        if df.empty:
            return _empty_frame()
        df = df[df["confirmed"]] if "confirmed" in df else df
        df = df.set_index("open_time").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df.index = pd.DatetimeIndex(df.index).tz_convert("UTC") if df.index.tz is not None else pd.DatetimeIndex(df.index, tz="UTC")
        df.index.name = "open_time"
        return df[list(OHLCV)].astype(float)

    def write_positioning(self, kind: str, swap: str, records: Sequence[dict]) -> int:
        if not records:
            return 0
        period = FUNDING_PERIOD if kind == "funding_rate" else OI_PERIOD
        return int(write_series(self.layout, kind, swap, period, records).added)

    def read_funding(self, swap: str) -> Optional[pd.DataFrame]:
        return load_okx_series(self.layout, "funding_rate", swap, FUNDING_PERIOD, ["funding_rate"])

    def read_open_interest(self, swap: str) -> Optional[pd.DataFrame]:
        return load_okx_series(self.layout, "open_interest", swap, OI_PERIOD, ["oi_usd"])


# -- in-memory view --------------------------------------------------------------


@dataclass
class RefreshReport:
    candles_added: Dict[str, int] = field(default_factory=dict)
    positioning_added: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    requests: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"candles_added": dict(self.candles_added), "positioning_added": dict(self.positioning_added),
                "errors": list(self.errors), "requests": self.requests}


class MarketData:
    """1H candles per instrument (memory + fleet lake), resampled bars and the S5 feature context."""

    def __init__(
        self,
        lake: FleetLake,
        feed: Optional[OkxPublicFeed],
        *,
        instruments: Sequence[str],
        history_days: float,
        positioning: str = "okx",
        positioning_days: float = 100.0,
        oi_days: float = 10.0,
        positioning_refresh_minutes: float = 30.0,
        max_gap_pages: int = 400,
    ) -> None:
        if positioning not in POSITIONING_SOURCES:
            raise ValueError(f"positioning source must be one of {POSITIONING_SOURCES}")
        self.lake = lake
        self.feed = feed
        self.instruments = tuple(instruments)
        self.history_days = float(history_days)
        self.positioning = positioning
        self.positioning_days = float(positioning_days)
        self.oi_days = float(oi_days)
        self.positioning_refresh = timedelta(minutes=float(positioning_refresh_minutes))
        self.max_gap_pages = int(max_gap_pages)
        self._candles: Dict[str, pd.DataFrame] = {i: _empty_frame() for i in self.instruments}
        self._funding: Dict[str, Optional[pd.DataFrame]] = {}
        self._oi: Dict[str, Optional[pd.DataFrame]] = {}
        self._positioning_at: Optional[datetime] = None
        self._bars_cache: Dict[Tuple[str, str], Tuple[int, pd.DataFrame]] = {}

    # -- loading -------------------------------------------------------------

    def load(self, now: datetime) -> None:
        since = _utc(now) - pd.Timedelta(days=self.history_days)
        for inst in self.instruments:
            self._candles[inst] = self.lake.read_candles(inst, since)
        self._load_positioning()

    def _load_positioning(self) -> None:
        for inst in self.instruments:
            swap = SWAP_FOR[inst]
            self._funding[inst] = self.lake.read_funding(swap) if self.positioning == "okx" else None
            self._oi[inst] = self.lake.read_open_interest(swap) if self.positioning == "okx" else None

    def bootstrap(self, now: datetime, seed: Optional[LakeLayout] = None) -> RefreshReport:
        """Seed from the research lake (copy), load, then top up from OKX (gaps filled backwards)."""
        report = RefreshReport()
        since = _utc(now) - pd.Timedelta(days=self.history_days)
        if seed is not None and seed.root.exists() and seed.root.resolve() != self.lake.root.resolve():
            copied = self.lake.seed_from(seed, self.instruments, since)
            for label, n in copied.items():
                report.candles_added[f"seeded {label} (files)"] = n
        self.load(now)
        if self.feed is not None:
            for inst in self.instruments:
                try:
                    report.candles_added[inst] = self._top_up_candles(inst, since)
                except (PublicRestError, MarketDataError) as exc:
                    report.errors.append(f"candles {inst}: {exc}")
            if self.positioning == "okx":
                self._refresh_positioning(now, report, bootstrap=True)
        report.requests = 0 if self.feed is None else self.feed.requests
        return report

    def refresh(self, now: datetime) -> RefreshReport:
        """Fetch the newest candles (filling any gap since the last stored one) and, when due, positioning data."""
        report = RefreshReport()
        if self.feed is None:
            return report
        before = self.feed.requests
        since = _utc(now) - pd.Timedelta(days=self.history_days)
        for inst in self.instruments:
            try:
                report.candles_added[inst] = self._top_up_candles(inst, since)
            except (PublicRestError, MarketDataError) as exc:
                report.errors.append(f"candles {inst}: {exc}")
        if self.positioning == "okx" and (self._positioning_at is None or _utc(now) - _utc(self._positioning_at) >= self.positioning_refresh):
            self._refresh_positioning(now, report, bootstrap=False)
        report.requests = self.feed.requests - before
        return report

    def _top_up_candles(self, instrument: str, since: pd.Timestamp) -> int:
        newest = self.feed.newest_candles(instrument)
        frames = [newest]
        have = self._candles[instrument]
        stop_at = have.index[-1] if len(have) else since
        cursor = newest.index[0] if len(newest) else None
        pages = 0
        # Walk backwards until the stored history (or the history window start) is reached.
        while cursor is not None and cursor > stop_at and pages < self.max_gap_pages:
            older = self.feed.candles_before(instrument, _ms(cursor))
            pages += 1
            if older.empty:
                break
            frames.append(older)
            if older.index[0] >= cursor:
                raise MarketDataError("history-candles did not move backwards")
            cursor = older.index[0]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return 0
        fetched = pd.concat(frames).sort_index()
        fetched = fetched[~fetched.index.duplicated(keep="last")]
        fresh = fetched[~fetched.index.isin(have.index)] if len(have) else fetched
        fresh = fresh[fresh.index >= since]
        if fresh.empty:
            return 0
        self.lake.write_candles(instrument, fresh)
        merged = pd.concat([have, fresh]).sort_index() if len(have) else fresh.sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        self._candles[instrument] = merged[merged.index >= since - pd.Timedelta(days=1)]
        self._bars_cache = {k: v for k, v in self._bars_cache.items() if k[0] != instrument}
        return int(len(fresh))

    def _refresh_positioning(self, now: datetime, report: RefreshReport, *, bootstrap: bool) -> None:
        now_ts = _utc(now)
        changed = False
        for inst in self.instruments:
            swap = SWAP_FOR[inst]
            try:
                n_f = self._walk_series("funding_rate", swap, self._funding.get(inst), now_ts - pd.Timedelta(days=self.positioning_days), bootstrap)
                n_o = self._walk_series("open_interest", swap, self._oi.get(inst), now_ts - pd.Timedelta(days=self.oi_days), bootstrap)
                report.positioning_added[f"funding {swap}"] = n_f
                report.positioning_added[f"open interest {swap}"] = n_o
                changed = changed or bool(n_f or n_o)
            except (PublicRestError, ValueError) as exc:
                report.errors.append(f"positioning {swap}: {exc}")
        self._positioning_at = now_ts.to_pydatetime()
        if changed:
            self._load_positioning()

    def _walk_series(self, kind: str, swap: str, have: Optional[pd.DataFrame], since: pd.Timestamp, bootstrap: bool) -> int:
        """Fetch pages newest-first until the stored history is reached; store only rows newer than it."""
        fetch = (lambda c: self.feed.funding_history(swap, before_ms=c)) if kind == "funding_rate" else (
            lambda c: self.feed.open_interest_history(swap, end_ms=None if c is None else c - 1))
        newest_ms = _ms(have.index[-1]) if have is not None and len(have) else None
        stop_at = _utc(have.index[-1]) if newest_ms is not None else since
        added = 0
        cursor: Optional[int] = None
        for _ in range(12 if bootstrap else 3):
            rows = fetch(cursor)
            if not rows:
                break
            fresh = [r for r in rows if newest_ms is None or int(r["ts"]) > newest_ms]
            if fresh:
                added += self.lake.write_positioning(kind, swap, fresh)
            oldest = min(int(r["ts"]) for r in rows)
            if pd.Timestamp(oldest, unit="ms", tz="UTC") <= stop_at or (cursor is not None and oldest >= cursor):
                break
            cursor = oldest
        return added

    # -- views ----------------------------------------------------------------

    def candles(self, instrument: str) -> pd.DataFrame:
        return self._candles[instrument]

    def last_candle_open(self, instrument: str) -> Optional[pd.Timestamp]:
        df = self._candles.get(instrument)
        return None if df is None or df.empty else df.index[-1]

    def bars(self, instrument: str, timeframe: str) -> pd.DataFrame:
        """Complete UTC-aligned ``timeframe`` bars built from the stored 1H candles."""
        src = self._candles[instrument]
        key = (instrument, timeframe)
        cached = self._bars_cache.get(key)
        if cached is not None and cached[0] == len(src):
            return cached[1]
        out = resample_ohlcv(src, timeframe, source_timeframe=SOURCE_BAR) if len(src) else _empty_frame()
        self._bars_cache[key] = (len(src), out)
        return out

    def context(self, instrument: str, timeframe: str) -> FeatureContext:
        ctx = FeatureContext(timeframe=timeframe, periods_per_year=bars_per_year(timeframe))
        if self.positioning == "okx":
            ctx.funding = self._funding.get(instrument)
            ctx.open_interest = self._oi.get(instrument)
        return ctx

    def positioning_age(self, instrument: str, at: pd.Timestamp) -> Dict[str, Optional[float]]:
        """Hours between ``at`` and the newest funding / open-interest value known at ``at``."""
        out: Dict[str, Optional[float]] = {}
        for label, frame in (("funding", self._funding.get(instrument)), ("open_interest", self._oi.get(instrument))):
            if frame is None or frame.empty:
                out[label] = None
                continue
            known = frame.index[frame.index <= at]
            out[label] = None if len(known) == 0 else float((at - known[-1]).total_seconds() / 3600.0)
        return out


def frame_until(df: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    """Rows with open time <= ``end`` (a decision may only see bars up to and including its own)."""
    if df.empty:
        return df
    pos = int(np.searchsorted(df.index.values, _utc(end).to_datetime64(), side="right"))
    return df.iloc[:pos]
