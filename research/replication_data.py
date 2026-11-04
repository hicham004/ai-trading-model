"""Public data for the replication study (plan row R12, SIMULATION ONLY).

Two research-only, resumable collectors for the markets of
:mod:`research.markets`, both bounded to that table and both GET-only:

- **OKX spot candles** (1H, and 4H as Sprint 2c stored them for BTC/ETH)
  through the path-allowlisted :class:`app.datalake.okx_public_rest.OKXPublicRest`
  (no headers, no keys; the R9 precedent ``research/longshort_data.py``), written
  into the lake layout ``data/lake/candles/<inst>/<bar>`` with the resumable
  :class:`app.datalake.paging.BackwardWalker`. 6H bars are resampled from 1H
  by ``research.data.load_or_resample_candles`` exactly as in Sprint 2c. The
  app's own backfill (``app/datalake/backfill.py``) is bounded to BTC/ETH by
  ``ALLOWED_INSTRUMENTS`` in ``app/okx/client.py``, which also bounds demo and
  paper trading and is NOT widened here.
- **Binance public funding history** (``GET /fapi/v1/fundingRate``) for the
  markets' USDT-margined perpetuals, as the S5 positioning feature (the
  research-only feature source Sprint 2b accepted for BTC/ETH). The app's
  ``backfill_funding`` refuses every symbol but BTCUSDT/ETHUSDT, so the page
  loop, the parser and the cursor live here; the rows go into the same lake
  layout (``external/binance/funding_rate/<SYMBOL>/8H``) through the app's
  ``write_external_series`` (schema and de-duplication unchanged), so
  ``research.data.positioning_context`` finds them through the research symbol
  table.

Nothing here can authenticate, place an order or reach an account.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import pandas as pd
import pyarrow as pa

from app.datalake.binance_public import FUNDING_PATH, FUNDING_PERIOD, VENUE, BinancePublicClient, BinancePublicError, write_external_series
from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest
from app.datalake.paging import BackwardWalker, Row, WalkReport
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE, atomic_replace, coverage, from_ms, to_ms, write_partitioned
from research.data import load_external_series
from research.markets import REPLICATION_CANDIDATES, research_symbol_for
from research.paper_fleet.data import parse_candle_rows

CANDLES_PATH = "/api/v5/market/candles"
HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
TICKERS_PATH = "/api/v5/market/tickers"
NEWEST_LIMIT = 300
HISTORY_LIMIT = 100
COLLECTED_BARS = ("1H", "4H")  # Sprint 2c read stored 4H bars and resampled 6H from 1H
DEFAULT_CANDLE_START = datetime(2019, 12, 1, tzinfo=timezone.utc)
DEFAULT_FUNDING_START = datetime(2019, 9, 1, tzinfo=timezone.utc)
FUNDING_PAGE_LIMIT = 1000
BAR_MS = {"1H": 3_600_000, "4H": 4 * 3_600_000}


class ReplicationDataError(RuntimeError):
    """A collector was asked for something outside its bounds, or the data it got is malformed."""


def _check_market(instrument: str) -> str:
    if instrument not in REPLICATION_CANDIDATES:
        raise ReplicationDataError(f"{instrument!r} is not a replication market; known: {sorted(REPLICATION_CANDIDATES)}")
    return instrument


def _check_bar(bar: str) -> str:
    if bar not in COLLECTED_BARS:
        raise ReplicationDataError(f"bar {bar!r} is not collected; collected bars: {COLLECTED_BARS}")
    return bar


# -- OKX spot candles (public) ----------------------------------------------------------

class _SpotCandleSource:
    """``PageSource`` over the public candle endpoints for one replication market and bar."""

    def __init__(self, rest: OKXPublicRest, instrument: str, bar: str) -> None:
        self._rest = rest
        self._instrument = _check_market(instrument)
        self._bar = _check_bar(bar)

    def _rows(self, data) -> Sequence[Row]:
        frame = parse_candle_rows(data, self._instrument)
        step = BAR_MS[self._bar]
        rows: List[Row] = []
        for ts, row in zip(frame.index, frame.itertuples(index=False)):
            ms = int(ts.value // 1_000_000)
            if ms % step != 0:
                continue  # a candle off the bar's own grid is never stored
            rows.append((ms, (ts, row)))
        return rows

    def fetch_newest(self) -> Sequence[Row]:
        return self._rows(self._rest.get(CANDLES_PATH, {"instId": self._instrument, "bar": self._bar, "limit": NEWEST_LIMIT}))

    def fetch_older(self, cursor_ms: int) -> Sequence[Row]:
        return self._rows(self._rest.get(HISTORY_CANDLES_PATH, {"instId": self._instrument, "bar": self._bar, "after": int(cursor_ms),
                                                                "limit": HISTORY_LIMIT}))


def _write_candle_rows(layout: LakeLayout, instrument: str, bar: str, rows: Sequence[Row]) -> int:
    if not rows:
        return 0
    stamps = [payload[0].to_pydatetime() for _, payload in rows]
    values = [payload[1] for _, payload in rows]
    table = pa.table(
        {
            "open_time": pa.array(stamps, type=TS_TYPE),
            "instrument": pa.array([instrument] * len(rows), type=pa.string()),
            "timeframe": pa.array([bar] * len(rows), type=pa.string()),
            "open": pa.array([float(v.open) for v in values], type=pa.float64()),
            "high": pa.array([float(v.high) for v in values], type=pa.float64()),
            "low": pa.array([float(v.low) for v in values], type=pa.float64()),
            "close": pa.array([float(v.close) for v in values], type=pa.float64()),
            "volume": pa.array([float(v.volume) for v in values], type=pa.float64()),
            "confirmed": pa.array([True] * len(rows), type=pa.bool_()),
        },
        schema=CANDLE_SCHEMA,
    )
    res = write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA, file_for_year=lambda y: layout.candles_file(instrument, bar, y))
    return int(res.added)


@dataclass
class CandleCollectReport:
    instrument: str
    bar: str
    walk: WalkReport
    added: int
    stored_rows: int = 0
    stored_min: Optional[datetime] = None
    stored_max: Optional[datetime] = None

    def summary(self) -> str:
        span = f"{self.stored_min:%Y-%m-%d %H:%M} -> {self.stored_max:%Y-%m-%d %H:%M} UTC" if self.stored_min and self.stored_max else "(empty)"
        return (f"{self.instrument} {self.bar}: pages={self.walk.pages} added={self.added} stored={self.stored_rows} span={span} "
                f"complete={self.walk.complete} exhausted={self.walk.exhausted} reason={self.walk.reason}")


def collect_spot_candles(
    layout: LakeLayout,
    instrument: str,
    bar: str = "1H",
    *,
    rest: Optional[OKXPublicRest] = None,
    start: datetime = DEFAULT_CANDLE_START,
    max_pages: Optional[int] = None,
    sleep_seconds: float = 0.15,
    sleep: Callable[[float], None] = time.sleep,
) -> CandleCollectReport:
    """One resumable session collecting a replication market's public candles for ``bar`` back to ``start``."""
    _check_market(instrument)
    _check_bar(bar)
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    added = 0

    def on_page(rows: Sequence[Row]) -> None:
        nonlocal added
        added += _write_candle_rows(layout, instrument, bar, rows)

    walker = BackwardWalker(_SpotCandleSource(rest or OKXPublicRest(), instrument, bar), state_path=layout.state_file("candles", instrument, bar),
                            start_ms=to_ms(start), on_page=on_page, max_pages=max_pages, sleep_seconds=sleep_seconds, sleep=sleep)
    report = CandleCollectReport(instrument=instrument, bar=bar, walk=walker.run(), added=added)
    cov = coverage(layout.candles_dir(instrument, bar), "open_time")
    report.stored_rows = cov.rows
    report.stored_min = from_ms(cov.min_ms) if cov.min_ms is not None else None
    report.stored_max = from_ms(cov.max_ms) if cov.max_ms is not None else None
    return report


def candle_history_start(rest: OKXPublicRest, instrument: str, bar: str = "1H", *, before: str = "2020-01-01") -> Optional[str]:
    """The open time of the newest public candle strictly before ``before`` (None when the history starts later).

    One GET per call; used by the pre-registration step to check the 'history from before 2020-01-01' condition
    without collecting anything."""
    _check_market(instrument)
    cut = int(pd.Timestamp(before, tz="UTC").value // 1_000_000)
    rows = rest.get(HISTORY_CANDLES_PATH, {"instId": instrument, "bar": bar, "after": cut, "limit": 1})
    frame = parse_candle_rows(rows, instrument)
    if frame.empty:
        return None
    return f"{frame.index[-1]:%Y-%m-%d %H:%M}"


# -- Binance public funding (research symbols) ---------------------------------------------

def parse_research_funding_rows(data: Sequence, symbol: str) -> List[dict]:
    """``/fapi/v1/fundingRate`` rows -> records for one research symbol (other symbols skipped, malformed rows refused)."""
    out: List[dict] = []
    for item in data:
        if not isinstance(item, dict):
            raise ReplicationDataError(f"malformed funding row: {item!r}")
        if item.get("symbol") not in (None, symbol):
            continue
        try:
            ts = int(item.get("fundingTime"))
            rate = float(item.get("fundingRate"))
        except (TypeError, ValueError) as exc:
            raise ReplicationDataError(f"malformed funding row: {item!r}") from exc
        if ts <= 0 or not math.isfinite(rate):
            raise ReplicationDataError(f"malformed funding row: {item!r}")
        mark = item.get("markPrice")
        try:
            mark_price = float(mark) if mark not in (None, "") else math.nan
        except (TypeError, ValueError) as exc:
            raise ReplicationDataError(f"malformed markPrice: {mark!r}") from exc
        out.append({"ts": ts, "venue": VENUE, "symbol": symbol, "period": FUNDING_PERIOD, "funding_rate": rate, "mark_price": mark_price})
    return out


def _state_path(layout: LakeLayout, symbol: str) -> Path:
    return layout.state_file("external", VENUE, "funding_rate", symbol)


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ReplicationDataError(f"corrupt state file: {path}")
    return data


def _save_state(path: Path, state: dict) -> None:
    state = dict(state, updated_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    atomic_replace(tmp, path)


@dataclass
class FundingCollectReport:
    instrument: str
    symbol: str
    pages: int = 0
    rows_fetched: int = 0
    added: int = 0
    stored_rows: int = 0
    stored_min: Optional[datetime] = None
    stored_max: Optional[datetime] = None
    reason: str = ""
    errors: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.reason in ("complete", "up_to_date")

    def summary(self) -> str:
        span = f"{self.stored_min:%Y-%m-%d %H:%M} -> {self.stored_max:%Y-%m-%d %H:%M} UTC" if self.stored_min and self.stored_max else "(empty)"
        return (f"binance funding {self.symbol} ({self.instrument}): pages={self.pages} fetched={self.rows_fetched} added={self.added} "
                f"stored={self.stored_rows} span={span} reason={self.reason}")


def collect_research_funding(
    layout: LakeLayout,
    instrument: str,
    *,
    client: Optional[BinancePublicClient] = None,
    start: datetime = DEFAULT_FUNDING_START,
    max_pages: Optional[int] = None,
    sleep_seconds: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
) -> FundingCollectReport:
    """Walk forward from the stored cursor (or ``start``) in pages of 1000 settlements for one replication market."""
    _check_market(instrument)
    symbol = research_symbol_for(instrument)
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    if max_pages is not None and max_pages <= 0:
        raise ValueError("max_pages must be positive when given")
    client = client or BinancePublicClient()
    state_path = _state_path(layout, symbol)
    state = _load_state(state_path)
    cursor = int(state.get("cursor_ms") or to_ms(start))
    report = FundingCollectReport(instrument=instrument, symbol=symbol)
    while True:
        if max_pages is not None and report.pages >= max_pages:
            report.reason = "max_pages"
            break
        try:
            data = client.get_json(FUNDING_PATH, {"symbol": symbol, "startTime": cursor, "limit": FUNDING_PAGE_LIMIT})
        except BinancePublicError as exc:
            report.reason = "error"
            report.errors.append(str(exc))
            break
        report.pages += 1
        rows = parse_research_funding_rows(data, symbol)
        if not rows:
            report.reason = "up_to_date"
            break
        rows.sort(key=lambda r: r["ts"])
        if rows[0]["ts"] < cursor:
            raise ReplicationDataError("endpoint returned rows before the requested startTime")
        res = write_external_series(layout, "funding_rate", symbol, FUNDING_PERIOD, rows)
        report.rows_fetched += len(rows)
        report.added += res.added
        cursor = rows[-1]["ts"] + 1
        state["cursor_ms"] = cursor
        _save_state(state_path, state)
        if len(rows) < FUNDING_PAGE_LIMIT:
            report.reason = "complete"
            break
        if sleep_seconds:
            sleep(sleep_seconds)
    cov = coverage(layout.external_series_dir(VENUE, "funding_rate", symbol, FUNDING_PERIOD), "ts")
    report.stored_rows = cov.rows
    report.stored_min = from_ms(cov.min_ms) if cov.min_ms is not None else None
    report.stored_max = from_ms(cov.max_ms) if cov.max_ms is not None else None
    return report


def research_funding_frame(layout: LakeLayout, instrument: str) -> Optional[pd.DataFrame]:
    """The stored funding frame of a replication market (``None`` when nothing is stored)."""
    return load_external_series(layout, VENUE, "funding_rate", research_symbol_for(instrument), FUNDING_PERIOD, ["funding_rate"])


def funding_bar_coverage(index: pd.DatetimeIndex, funding: Optional[pd.DataFrame]) -> float:
    """Share of candle bars that have a funding value when the series is as-of aligned (Sprint 2b's coverage measure)."""
    if funding is None or funding.empty or len(index) == 0:
        return 0.0
    first = pd.Timestamp(funding.index.min())
    first = first.tz_localize("UTC") if first.tzinfo is None else first.tz_convert("UTC")
    idx = pd.DatetimeIndex(index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return float((idx >= first).mean())


def lake_summary(layout: LakeLayout, instruments: Sequence[str]) -> Dict[str, Dict[str, object]]:
    """What the lake holds for each market: candle spans per collected bar and the funding span (reporting aid)."""
    out: Dict[str, Dict[str, object]] = {}
    for inst in instruments:
        entry: Dict[str, object] = {}
        for bar in COLLECTED_BARS:
            cov = coverage(layout.candles_dir(inst, bar), "open_time")
            entry[f"candles_{bar}"] = {"rows": cov.rows, "min": None if cov.min_ms is None else from_ms(cov.min_ms).isoformat(),
                                       "max": None if cov.max_ms is None else from_ms(cov.max_ms).isoformat()}
        try:
            symbol = research_symbol_for(inst)
        except ValueError:
            symbol = None
        if symbol is not None:
            fcov = coverage(layout.external_series_dir(VENUE, "funding_rate", symbol, FUNDING_PERIOD), "ts")
            entry["funding"] = {"symbol": symbol, "rows": fcov.rows, "min": None if fcov.min_ms is None else from_ms(fcov.min_ms).isoformat(),
                                "max": None if fcov.max_ms is None else from_ms(fcov.max_ms).isoformat()}
        out[inst] = entry
    return out
