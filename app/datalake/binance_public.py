"""Binance PUBLIC USDT-margined futures statistics as long-history research FEATURES.

This project trades OKX SPOT only (demo), long-only; it never trades on
Binance and never sends credentials anywhere. These series exist because OKX
keeps only months of public funding-rate / open-interest history (checked
2026-10-20: funding since 2026-07, open interest since 2026-08) while Binance
serves, without any API key:

- **funding-rate history** since 2019-09-10 (BTCUSDT) / 2019-11-27 (ETHUSDT)
  through ``GET https://fapi.binance.com/fapi/v1/fundingRate`` (public,
  request weight 1, up to 1000 rows per page, ascending from ``startTime``);
- **5-minute open interest and long/short ratios** since 2020-09-01 (BTCUSDT)
  / 2021-12-01 (ETHUSDT) as one zipped CSV per UTC day on the public bulk
  bucket ``https://data.binance.vision/data/futures/um/daily/metrics/<SYMBOL>/``
  with a ``.CHECKSUM`` (sha256) file next to each zip. The REST endpoint
  ``/futures/data/openInterestHist`` only serves the latest ~30 days, which is
  why the bulk files are used. Here the 5-minute rows are reduced to the last
  snapshot of every UTC hour (``period = 1H``); each stored row keeps its own
  snapshot time so as-of alignment onto candles can never see a value before
  it existed.

Terms: public market data published by Binance for its users (Binance API
Terms of Use; "Binance Public Data" on data.binance.vision). Used for internal
research only, not redistributed; files are cached in the git-ignored lake.
Row formats were confirmed against the live endpoints on 2026-10-20.

Safety: GET only; hostname + path allowlists; no headers beyond a User-Agent;
bounded downloads; one-member, size-capped zip extraction; sha256
verification of every bulk file; timestamps and numbers validated.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import pyarrow as pa
import requests

from app.datalake.layout import EXTERNAL_KINDS, LakeLayout
from app.datalake.parquet_store import TS_TYPE, WriteResult, atomic_replace, coverage, from_ms, to_ms, write_partitioned
from app.logging_config import get_logger

logger = get_logger(__name__)

FAPI_BASE = "https://fapi.binance.com"
VISION_BASE = "https://data.binance.vision"
VENUE = "binance"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SYMBOL_FOR_INSTRUMENT = {"BTC-USDT": "BTCUSDT", "ETH-USDT": "ETHUSDT"}
FUNDING_PATH = "/fapi/v1/fundingRate"
ALLOWED_FAPI_PATHS = (FUNDING_PATH,)
METRICS_PREFIX = "/data/futures/um/daily/metrics/"
FUNDING_PERIOD = "8H"
METRICS_PERIOD = "1H"
FUNDING_PAGE_LIMIT = 1000
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
MAX_CSV_BYTES = 16 * 1024 * 1024
USER_AGENT = "ai-trading-model-research/0.1 (public market data; research features only)"
FUNDING_START = {
    "BTCUSDT": datetime(2019, 9, 1, tzinfo=timezone.utc),
    "ETHUSDT": datetime(2019, 11, 1, tzinfo=timezone.utc),
}
METRICS_START = {"BTCUSDT": date(2020, 9, 1), "ETHUSDT": date(2021, 12, 1)}
METRICS_COLUMNS = (
    "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
    "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
)

_F64 = pa.float64()
_STR = pa.string()
EXTERNAL_SCHEMAS: Dict[str, pa.Schema] = {
    "funding_rate": pa.schema(
        [("ts", TS_TYPE), ("venue", _STR), ("symbol", _STR), ("period", _STR), ("funding_rate", _F64), ("mark_price", _F64)]
    ),
    "metrics": pa.schema(
        [
            ("ts", TS_TYPE), ("venue", _STR), ("symbol", _STR), ("period", _STR),
            ("oi", _F64), ("oi_usd", _F64),
            ("top_ls_ratio_count", _F64), ("top_ls_ratio_pos", _F64), ("ls_ratio_count", _F64), ("taker_ls_vol_ratio", _F64),
        ]
    ),
}
assert tuple(EXTERNAL_SCHEMAS) == EXTERNAL_KINDS


class BinancePublicError(RuntimeError):
    """Network failure, HTTP error, malformed response, or integrity failure."""


# -- allowlists ---------------------------------------------------------------

def assert_fapi_path(path: str) -> str:
    """Only the public funding-rate history endpoint is reachable."""
    if path not in ALLOWED_FAPI_PATHS:
        raise ValueError(f"path {path!r} is not an allowed Binance public endpoint")
    return path


def assert_vision_path(path: str) -> str:
    """Only daily metrics zips (and their checksum files) under the public bulk prefix."""
    if not path.startswith(METRICS_PREFIX) or any(t in path for t in ("..", "?", "#", "//", "\\")):
        raise ValueError(f"path {path!r} is not an allowed Binance bulk-data path")
    if not (path.endswith(".zip") or path.endswith(".zip.CHECKSUM")):
        raise ValueError(f"path {path!r} must point at a .zip or .zip.CHECKSUM file")
    parts = path[len(METRICS_PREFIX):].split("/")
    if len(parts) != 2 or parts[0] not in SYMBOLS or not parts[1].startswith(f"{parts[0]}-metrics-"):
        raise ValueError(f"path {path!r} is not a metrics file of an allowed symbol")
    return path


def metrics_file_path(symbol: str, day: date) -> str:
    _check_symbol(symbol)
    return f"{METRICS_PREFIX}{symbol}/{symbol}-metrics-{day.isoformat()}.zip"


def _check_symbol(symbol: str) -> None:
    if symbol not in SYMBOLS:
        raise ValueError(f"symbol {symbol!r} not allowed; allowed: {SYMBOLS}")


# -- client -------------------------------------------------------------------

class BinancePublicClient:
    """GET-only client for the two public Binance data sources above."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeout = float(timeout)
        self._max_retries = max(1, int(max_retries))
        self._session = session or requests.Session()
        self._sleep = sleep
        self._headers = {"User-Agent": USER_AGENT}

    def _get(self, url: str, params: Optional[Dict[str, str]] = None) -> requests.Response:
        last_error: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._session.get(url, params=params, timeout=self._timeout, headers=self._headers)
                if response.status_code in (418, 429):
                    raise BinancePublicError(f"rate limited (HTTP {response.status_code})")
                if response.status_code == 404:
                    return response
                response.raise_for_status()
                return response
            except (requests.RequestException, BinancePublicError) as exc:
                last_error = exc
                logger.warning("Binance public request failed", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt < self._max_retries:
                    self._sleep(2.0 * attempt)
        raise BinancePublicError(f"failed after {self._max_retries} attempts: {last_error}")

    def get_json(self, path: str, params: Optional[Dict[str, object]] = None) -> List:
        assert_fapi_path(path)
        clean = {k: str(v) for k, v in (params or {}).items() if v is not None}
        response = self._get(f"{FAPI_BASE}{path}", clean)
        if response.status_code == 404:
            raise BinancePublicError("endpoint not found (HTTP 404)")
        try:
            payload = response.json()
        except ValueError as exc:
            raise BinancePublicError("response was not JSON") from exc
        if not isinstance(payload, list):
            raise BinancePublicError(f"unexpected response shape: {type(payload).__name__}")
        return payload

    def get_file(self, path: str) -> Optional[bytes]:
        """Download one bulk file; ``None`` when the day does not exist (HTTP 404)."""
        assert_vision_path(path)
        response = self._get(f"{VISION_BASE}{path}")
        if response.status_code == 404:
            return None
        content = response.content
        if len(content) > MAX_DOWNLOAD_BYTES:
            raise BinancePublicError(f"file too large ({len(content)} bytes): {path}")
        return content


# -- parsing ------------------------------------------------------------------

def _num(value, label: str, *, allow_blank: bool = False) -> float:
    if value in (None, "") and allow_blank:
        return math.nan
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise BinancePublicError(f"malformed {label}: {value!r}") from exc
    if not math.isfinite(out):
        raise BinancePublicError(f"non-finite {label}: {value!r}")
    return out


def _ts(value, label: str = "ts") -> int:
    try:
        ms = int(value)
    except (TypeError, ValueError) as exc:
        raise BinancePublicError(f"malformed {label}: {value!r}") from exc
    if ms <= 0:
        raise BinancePublicError(f"{label} must be after the Unix epoch")
    return ms


def parse_funding_rows(data: Sequence, symbol: str) -> List[dict]:
    """``/fapi/v1/fundingRate`` rows -> records (other symbols are skipped, never mixed)."""
    _check_symbol(symbol)
    out = []
    for item in data:
        if not isinstance(item, dict):
            raise BinancePublicError(f"malformed funding row: {item!r}")
        if item.get("symbol") not in (None, symbol):
            continue
        out.append(
            {
                "ts": _ts(item.get("fundingTime"), "fundingTime"),
                "venue": VENUE,
                "symbol": symbol,
                "period": FUNDING_PERIOD,
                "funding_rate": _num(item.get("fundingRate"), "fundingRate"),
                "mark_price": _num(item.get("markPrice"), "markPrice", allow_blank=True),
            }
        )
    return out


def _parse_create_time(value: str) -> int:
    try:
        dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (AttributeError, ValueError) as exc:
        raise BinancePublicError(f"malformed create_time: {value!r}") from exc
    return to_ms(dt)


def parse_metrics_csv(text: str, symbol: str) -> List[dict]:
    """Daily metrics CSV (5-minute snapshots) -> records sorted by time, exact-duplicate times collapsed."""
    _check_symbol(symbol)
    reader = csv.DictReader(io.StringIO(text))
    header = tuple(reader.fieldnames or ())
    if header != METRICS_COLUMNS:
        raise BinancePublicError(f"unexpected metrics header: {header!r}")
    rows: Dict[int, dict] = {}
    for row in reader:
        if row.get("symbol") != symbol:
            continue
        ts = _parse_create_time(row.get("create_time") or "")
        rows[ts] = {
            "ts": ts,
            "venue": VENUE,
            "symbol": symbol,
            "period": METRICS_PERIOD,
            "oi": _num(row.get("sum_open_interest"), "sum_open_interest"),
            "oi_usd": _num(row.get("sum_open_interest_value"), "sum_open_interest_value"),
            "top_ls_ratio_count": _num(row.get("count_toptrader_long_short_ratio"), "count_toptrader_long_short_ratio", allow_blank=True),
            "top_ls_ratio_pos": _num(row.get("sum_toptrader_long_short_ratio"), "sum_toptrader_long_short_ratio", allow_blank=True),
            "ls_ratio_count": _num(row.get("count_long_short_ratio"), "count_long_short_ratio", allow_blank=True),
            "taker_ls_vol_ratio": _num(row.get("sum_taker_long_short_vol_ratio"), "sum_taker_long_short_vol_ratio", allow_blank=True),
        }
    return [rows[k] for k in sorted(rows)]


def hourly_last(records: Sequence[dict]) -> List[dict]:
    """Keep the last snapshot of every UTC hour (the row keeps its own snapshot time)."""
    by_hour: Dict[int, dict] = {}
    for rec in records:
        hour = int(rec["ts"]) // 3_600_000
        current = by_hour.get(hour)
        if current is None or int(rec["ts"]) > int(current["ts"]):
            by_hour[hour] = rec
    return [by_hour[k] for k in sorted(by_hour)]


def unzip_single_csv(content: bytes, *, max_bytes: int = MAX_CSV_BYTES) -> str:
    """Extract the single CSV member of a bulk zip with a hard size cap (untrusted input)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        members = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise BinancePublicError("bulk file is not a valid zip") from exc
    if len(members) != 1:
        raise BinancePublicError(f"expected exactly one zip member, got {len(members)}")
    info = members[0]
    if info.file_size > max_bytes or not info.filename.lower().endswith(".csv"):
        raise BinancePublicError(f"refusing zip member {info.filename!r} ({info.file_size} bytes)")
    with archive.open(info) as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise BinancePublicError("zip member larger than declared")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BinancePublicError("zip member is not UTF-8 text") from exc


def verify_checksum(content: bytes, checksum_text: str, filename: str) -> None:
    """``<sha256>  <filename>`` as published next to each bulk file."""
    tokens = checksum_text.strip().split()
    if len(tokens) < 1:
        raise BinancePublicError("empty checksum file")
    expected = tokens[0].lower()
    if len(tokens) >= 2 and tokens[1] != filename:
        raise BinancePublicError(f"checksum file names {tokens[1]!r}, expected {filename!r}")
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise BinancePublicError(f"sha256 mismatch for {filename}: {actual} != {expected}")


def records_to_table(kind: str, records: Sequence[dict]) -> pa.Table:
    schema = EXTERNAL_SCHEMAS[kind]
    columns = {}
    for field_ in schema:
        columns[field_.name] = pa.array([r.get(field_.name) for r in records], type=field_.type)
    return pa.table(columns, schema=schema)


# -- storage ------------------------------------------------------------------

def write_external_series(layout: LakeLayout, kind: str, symbol: str, period: str, records: Sequence[dict]) -> WriteResult:
    if kind not in EXTERNAL_SCHEMAS:
        raise ValueError(f"unknown external series kind {kind!r}")
    return write_partitioned(
        records_to_table(kind, records),
        key="ts",
        schema=EXTERNAL_SCHEMAS[kind],
        file_for_year=lambda y: layout.external_series_file(VENUE, kind, symbol, period, y),
    )


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"corrupt state file: {path}")
    return data


def _save_state(path: Path, state: dict) -> None:
    state = dict(state, updated_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    atomic_replace(tmp, path)


# -- funding-rate backfill (forward, resumable) ---------------------------------

@dataclass
class FundingBackfillReport:
    symbol: str
    pages: int = 0
    rows_fetched: int = 0
    added: int = 0
    duplicates_dropped: int = 0
    stored_rows: int = 0
    stored_min: Optional[datetime] = None
    stored_max: Optional[datetime] = None
    reason: str = ""

    @property
    def complete(self) -> bool:
        return self.reason in ("complete", "up_to_date")

    def summary(self) -> str:
        span = (
            f"{self.stored_min:%Y-%m-%d %H:%M} -> {self.stored_max:%Y-%m-%d %H:%M} UTC"
            if self.stored_min and self.stored_max else "(empty)"
        )
        return (
            f"binance funding_rate {self.symbol}: pages={self.pages} fetched={self.rows_fetched} added={self.added} "
            f"dupes={self.duplicates_dropped} stored={self.stored_rows} span={span} reason={self.reason}"
        )


def backfill_funding(
    client: BinancePublicClient,
    layout: LakeLayout,
    symbol: str,
    *,
    start: Optional[datetime] = None,
    max_pages: Optional[int] = None,
    sleep_seconds: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
) -> FundingBackfillReport:
    """Walk forward from the stored cursor (or ``start``) in pages of 1000 settlements."""
    _check_symbol(symbol)
    if start is not None and start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    if max_pages is not None and max_pages <= 0:
        raise ValueError("max_pages must be positive when given")
    state_path = layout.state_file("external", VENUE, "funding_rate", symbol)
    state = _load_state(state_path)
    cursor = int(state.get("cursor_ms") or to_ms(start or FUNDING_START[symbol]))
    if start is not None and to_ms(start) < cursor and not state.get("cursor_ms"):
        cursor = to_ms(start)
    report = FundingBackfillReport(symbol=symbol)
    while True:
        if max_pages is not None and report.pages >= max_pages:
            report.reason = "max_pages"
            break
        data = client.get_json(FUNDING_PATH, {"symbol": symbol, "startTime": cursor, "limit": FUNDING_PAGE_LIMIT})
        report.pages += 1
        rows = parse_funding_rows(data, symbol)
        if not rows:
            report.reason = "up_to_date"
            break
        rows.sort(key=lambda r: r["ts"])
        if rows[0]["ts"] < cursor:
            raise BinancePublicError("endpoint returned rows before the requested startTime")
        res = write_external_series(layout, "funding_rate", symbol, FUNDING_PERIOD, rows)
        report.rows_fetched += len(rows)
        report.added += res.added
        report.duplicates_dropped += res.duplicates_dropped
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
    logger.info("Binance funding backfill finished", extra={"summary": report.summary()})
    return report


# -- metrics (open interest) backfill: one bulk file per UTC day, resumable ------

@dataclass
class MetricsBackfillReport:
    symbol: str
    days_requested: int = 0
    days_fetched: int = 0
    days_missing: List[str] = field(default_factory=list)
    rows_added: int = 0
    duplicates_dropped: int = 0
    stored_rows: int = 0
    stored_min: Optional[datetime] = None
    stored_max: Optional[datetime] = None
    done_through: Optional[str] = None
    reason: str = ""

    def summary(self) -> str:
        span = (
            f"{self.stored_min:%Y-%m-%d %H:%M} -> {self.stored_max:%Y-%m-%d %H:%M} UTC"
            if self.stored_min and self.stored_max else "(empty)"
        )
        return (
            f"binance metrics {self.symbol}: days_requested={self.days_requested} fetched={self.days_fetched} "
            f"missing={len(self.days_missing)} added={self.rows_added} dupes={self.duplicates_dropped} "
            f"stored={self.stored_rows} span={span} done_through={self.done_through} reason={self.reason}"
        )


def backfill_metrics(
    client: BinancePublicClient,
    layout: LakeLayout,
    symbol: str,
    *,
    start_day: Optional[date] = None,
    end_day: Optional[date] = None,
    max_days: Optional[int] = None,
    sleep_seconds: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
    verify: bool = True,
    today: Optional[date] = None,
) -> MetricsBackfillReport:
    """Download, verify, parse and store one day at a time from the stored cursor (or ``start_day``)."""
    _check_symbol(symbol)
    if max_days is not None and max_days <= 0:
        raise ValueError("max_days must be positive when given")
    today = today or datetime.now(tz=timezone.utc).date()
    end = end_day or (today - timedelta(days=1))  # yesterday: today's file does not exist yet
    state_path = layout.state_file("external", VENUE, "metrics", symbol)
    state = _load_state(state_path)
    missing: List[str] = list(state.get("missing_days") or [])
    day = start_day or METRICS_START[symbol]
    done_through = state.get("done_through")
    if done_through:
        day = max(day, date.fromisoformat(done_through) + timedelta(days=1))
    report = MetricsBackfillReport(symbol=symbol, done_through=done_through)
    report.reason = "up_to_date" if day > end else "complete"
    while day <= end:
        if max_days is not None and report.days_fetched + len(report.days_missing) >= max_days:
            report.reason = "max_days"
            break
        report.days_requested += 1
        path = metrics_file_path(symbol, day)
        content = client.get_file(path)
        if content is None:
            report.days_missing.append(day.isoformat())
            if day.isoformat() not in missing:
                missing.append(day.isoformat())
        else:
            if verify:
                checksum = client.get_file(path + ".CHECKSUM")
                if checksum is None:
                    raise BinancePublicError(f"checksum file missing for {path}")
                verify_checksum(content, checksum.decode("utf-8", errors="replace"), path.rsplit("/", 1)[-1])
            rows = hourly_last(parse_metrics_csv(unzip_single_csv(content), symbol))
            res = write_external_series(layout, "metrics", symbol, METRICS_PERIOD, rows)
            report.days_fetched += 1
            report.rows_added += res.added
            report.duplicates_dropped += res.duplicates_dropped
        state["done_through"] = day.isoformat()
        state["missing_days"] = missing
        _save_state(state_path, state)
        report.done_through = day.isoformat()
        day += timedelta(days=1)
        if sleep_seconds:
            sleep(sleep_seconds)
    cov = coverage(layout.external_series_dir(VENUE, "metrics", symbol, METRICS_PERIOD), "ts")
    report.stored_rows = cov.rows
    report.stored_min = from_ms(cov.min_ms) if cov.min_ms is not None else None
    report.stored_max = from_ms(cov.max_ms) if cov.max_ms is not None else None
    logger.info("Binance metrics backfill finished", extra={"summary": report.summary()})
    return report
