"""Tokenized US stocks on OKX: a LOG-ONLY research-side data collector (plan row R21, SIMULATION ONLY).

OKX lists tokenized US stocks (Backed's xStocks: ``XNVDA-USDT``, ``XQQQ-USDT``, ...) as SPOT
pairs whose instrument row carries ``instCategory`` 3. Nothing in this project trades them:
the app's ``ALLOWED_INSTRUMENTS`` stays BTC-USDT / ETH-USDT, this module never imports the
trading, exchange, risk or supervisor code, and its only network access is the GET-only,
path-allowlisted public client of the data lake
(:class:`app.datalake.okx_public_rest.OKXPublicRest`: no headers, no keys) on six public
endpoints: instruments, tickers, candles, history-candles, books and price-limit. It cannot
authenticate, place an order or reach an account; it can only read public pages and write
files under the lake.

What it collects, in the lake layout under ``<lake>/xstocks/`` (the R12 precedent
``research/replication_data.py`` applied to a new instrument class):

- **the universe** — the 15 most liquid X-prefixed USDT stock pairs by 24-hour quote volume
  (``/api/v5/market/tickers``, ``volCcy24h``) among the instruments with ``instCategory`` 3
  that are ``live``; chosen ONCE (``select_universe``) and written to a file kept in the
  repository (``docs/research/xstocks_universe.json``) so every later run, on any machine,
  collects the same list; crypto names that also start with X (XRP, XLM, XAUT, ...) are
  excluded by the category;
- **the instrument parameters** (``lotSz``, ``minSz``, ``tickSz``, ``maxMktAmt``, the
  price-band percentages, the fee ``groupId``, ``listTime``, ``state``, ...), once a day,
  exactly as OKX returns them;
- **1H and 1Dutc candles** back to each pair's ``listTime``, resumable through the lake's
  :class:`app.datalake.paging.BackwardWalker` (OKX's own ``1D`` bar opens at 16:00 UTC and
  would cut the US session in two; ``1Dutc`` opens at 00:00 UTC and holds one whole US
  session). The quote volume (USDT) of every candle is kept beside the base volume;
- **order-book snapshots** on the New York schedule the plan fixes: the US regular-session
  open and close (09:30 and 16:00 America/New_York, converted at run time: 14:30 / 21:00 UTC
  in winter, 13:30 / 20:00 UTC in summer) on weekdays, 03:00 UTC every day and 12:00 UTC on
  Saturdays. The plan names 50 levels; 50 levels reach only 0.2-0.45 % from mid on the
  tightest books (XQQQ, XSPY, XGOOGL on 2026-11-05), which would cut the "depth within
  0.5 % of mid" measure short, so the endpoint's maximum of 400 levels is requested (one
  request either way) and the levels within 2 % of mid are stored, with the spread, the
  depth within 0.5 % and whether that band was fully covered computed at write time.

Everything is resumable and idempotent: candle walks keep their cursor state, snapshots are
recorded per slot so a restart never takes one twice, and the daily parameter record is
one file per UTC day. Public rate limits are respected with a pause between requests.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Collection, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.datalake.layout import LakeLayout, safe_segment
from app.datalake.okx_public_rest import OKXPublicRest, PublicRestError
from app.datalake.paging import BackwardWalker, Row, WalkReport
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE, atomic_replace, coverage, from_ms, write_partitioned

XSTOCKS_SUBDIR = "xstocks"
STOCK_CATEGORY = "3"  # OKX ``instCategory`` of the tokenized-stock pairs (the "Stocks" category)
XSTOCK_ID_RE = re.compile(r"^X[A-Z0-9]+-USDT$")
UNIVERSE_SIZE = 15
UNIVERSE_VERSION = 1
DEFAULT_UNIVERSE_PATH = Path("docs/research/xstocks_universe.json")
UNIVERSE_RULE = ("the top 15 by 24-hour quote volume (tickers volCcy24h) among SPOT instruments with instCategory 3, "
                 "an id matching ^X[A-Z0-9]+-USDT$ and state live, ties by id; chosen once and kept")

INSTRUMENTS_PATH = "/api/v5/public/instruments"
TICKERS_PATH = "/api/v5/market/tickers"
CANDLES_PATH = "/api/v5/market/candles"
HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
BOOKS_PATH = "/api/v5/market/books"
PRICE_LIMIT_PATH = "/api/v5/public/price-limit"

COLLECTED_BARS: Tuple[str, ...] = ("1H", "1Dutc")
BAR_MS = {"1H": 3_600_000, "1Dutc": 86_400_000}
NEWEST_LIMIT = 300
HISTORY_LIMIT = 100
DEFAULT_SLEEP_SECONDS = 0.15  # OKX public limits: 20-40 requests per 2 s per endpoint; this keeps us under 7 a second

BOOK_LEVELS = 400  # the books endpoint's maximum per side
BOOK_KEEP_PCT = 0.02  # levels stored: within 2 % of mid (the instruments' 2 % opening price band)
DEPTH_BAND_PCT = 0.005  # the plan's measure: depth within 0.5 % of mid

NEW_YORK = ZoneInfo("America/New_York")
US_OPEN = dtime(9, 30)
US_CLOSE = dtime(16, 0)
SLOT_US_OPEN = "us_open"
SLOT_US_CLOSE = "us_close"
SLOT_UTC_03 = "utc_03"
SLOT_SAT_12 = "sat_12"
SLOT_ADHOC = "adhoc"
SCHEDULED_SLOTS = (SLOT_US_OPEN, SLOT_US_CLOSE, SLOT_UTC_03, SLOT_SAT_12)
SNAPSHOT_GRACE_MINUTES = 30  # a slot missed by less than this (a restart, a sleep) is still taken
BOOKS_STATE_KEEP_DAYS = 45
TOPUP_DELAY_SECONDS = 90  # the loop tops the 1H candles up this long after the hour (OKX publishes the closed candle within seconds)

#: NYSE full-day closures, written 2026-11-05 from the published NYSE holiday calendar (2026 and 2027). A snapshot on
#: one of these days is still taken and labelled: the token trades while the stock does not. Verify against
#: https://www.nyse.com/markets/hours-calendars before relying on a date, and add 2028 before 2027 ends.
US_MARKET_HOLIDAYS = frozenset({
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
})
#: NYSE early closes (13:00 New York): labelled only; the 16:00 snapshot is still taken.
US_EARLY_CLOSES = frozenset({"2026-11-27", "2026-12-24", "2027-11-26"})
US_HOLIDAYS_KNOWN_THROUGH = "2027-12-31"

#: The instrument-row fields recorded once a day (strings exactly as OKX returns them).
INSTRUMENT_FIELDS = ("instId", "instType", "instCategory", "baseCcy", "quoteCcy", "state", "listTime", "contTdSwTime", "openType",
                     "ruleType", "lotSz", "minSz", "tickSz", "maxMktAmt", "maxLmtAmt", "maxMktSz", "maxLmtSz", "initPxLmtPct",
                     "floatPxLmtPct", "maxPxLmtPct", "groupId", "lever", "upcChg")

XSTOCK_CANDLE_SCHEMA = pa.schema(list(CANDLE_SCHEMA) + [pa.field("quote_volume", pa.float64())])


class XStocksDataError(RuntimeError):
    """The collector was asked for something outside its bounds, a file is malformed, or the data it got is."""


# -- layout ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class XStocksLayout:
    """Every file the collector writes, under ``<lake>/xstocks/`` in the lake's own layout.

    ``candles/<inst>/<bar>/<year>.parquet`` and ``_state/<job>.json`` come from :class:`LakeLayout`
    rooted at the subdirectory; ``instruments/<YYYY-MM-DD>.json`` (plus ``latest.json``) and
    ``books/<inst>/<YYYY-MM-DD>.jsonl`` are this collector's own.
    """

    root: Path

    @classmethod
    def from_lake(cls, lake: LakeLayout) -> "XStocksLayout":
        return cls(Path(lake.root) / XSTOCKS_SUBDIR)

    @property
    def lake(self) -> LakeLayout:
        return LakeLayout(self.root)

    def candles_dir(self, instrument: str, bar: str) -> Path:
        return self.lake.candles_dir(instrument, bar)

    def candles_file(self, instrument: str, bar: str, year: int) -> Path:
        return self.lake.candles_file(instrument, bar, year)

    def candle_state_file(self, instrument: str, bar: str) -> Path:
        return self.lake.state_file("candles", instrument, bar)

    @property
    def instruments_dir(self) -> Path:
        return self.root / "instruments"

    def instruments_file(self, day: date) -> Path:
        return self.instruments_dir / f"{day.isoformat()}.json"

    @property
    def instruments_latest(self) -> Path:
        return self.instruments_dir / "latest.json"

    def books_dir(self, instrument: str) -> Path:
        return self.root / "books" / safe_segment(instrument, "instrument")

    def books_file(self, instrument: str, day: date) -> Path:
        return self.books_dir(instrument) / f"{day.isoformat()}.jsonl"

    @property
    def books_state_file(self) -> Path:
        return self.lake.state_file("books")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms_iso(ms: int) -> str:
    return _iso(from_ms(ms))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    atomic_replace(tmp, path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise XStocksDataError(f"cannot read {path}: {exc}") from exc


def _float(value: Any, label: str, *, allow_blank: bool = False) -> float:
    if value in (None, "") and allow_blank:
        return math.nan
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise XStocksDataError(f"malformed {label}: {value!r}") from exc
    if not math.isfinite(out):
        raise XStocksDataError(f"non-finite {label}: {value!r}")
    return out


def _opt_float(value: Any, label: str) -> Optional[float]:
    out = _float(value, label, allow_blank=True)
    return None if math.isnan(out) else out


# -- universe ----------------------------------------------------------------------------------------------------

def is_xstock_row(row: Mapping[str, Any]) -> bool:
    """A live SPOT instrument in the Stocks category whose id is X-prefixed and USDT-quoted (XRP, XLM, XAUT fail the category)."""
    return (isinstance(row, Mapping) and str(row.get("instType", "")) == "SPOT" and str(row.get("instCategory", "")) == STOCK_CATEGORY
            and bool(XSTOCK_ID_RE.match(str(row.get("instId", "")))) and str(row.get("state", "")) == "live")


def rank_xstocks(instruments: Sequence[Mapping[str, Any]], tickers: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Every eligible pair with its 24-hour quote volume, ranked (volume descending, then id); a pair without a ticker ranks last."""
    by_id = {str(t.get("instId", "")): t for t in tickers if isinstance(t, Mapping)}
    rows: List[Dict[str, Any]] = []
    for inst in instruments:
        if not is_xstock_row(inst):
            continue
        iid = str(inst["instId"])
        ticker = by_id.get(iid)
        quote_vol = _float(ticker.get("volCcy24h"), f"{iid} volCcy24h", allow_blank=True) if ticker else math.nan
        rows.append({
            "instId": iid,
            "quote_volume_24h": None if math.isnan(quote_vol) else quote_vol,
            "base_volume_24h": _opt_float(ticker.get("vol24h"), "vol24h") if ticker else None,
            "last": _opt_float(ticker.get("last"), "last") if ticker else None,
            "list_time_ms": int(inst.get("listTime") or 0) or None,
            "lotSz": str(inst.get("lotSz", "")),
            "minSz": str(inst.get("minSz", "")),
        })
    rows.sort(key=lambda r: (-(r["quote_volume_24h"] if r["quote_volume_24h"] is not None else -1.0), r["instId"]))
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
        row["list_time"] = _ms_iso(row["list_time_ms"]) if row["list_time_ms"] else None
    return rows


def _universe_summary(instruments: Sequence[Mapping[str, Any]], ranking: Sequence[Mapping[str, Any]], tickers: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    stock_rows = [r for r in instruments if isinstance(r, Mapping) and str(r.get("instCategory", "")) == STOCK_CATEGORY and str(r.get("instType", "")) == "SPOT"]
    volumes = [r["quote_volume_24h"] for r in ranking if r["quote_volume_24h"] is not None]
    total = float(sum(volumes))
    top10 = float(sum(sorted(volumes, reverse=True)[:10]))
    ts = max((int(t.get("ts") or 0) for t in tickers if isinstance(t, Mapping)), default=0)
    return {
        "stock_instruments_spot": len(stock_rows),
        "stock_pairs_usdt_x_live": len(ranking),
        "stock_pairs_usdc_quoted": sum(1 for r in stock_rows if str(r.get("quoteCcy", "")) == "USDC"),
        "total_quote_volume_24h": total,
        "top10_share": (top10 / total) if total > 0 else None,
        "pairs_above_1m": sum(1 for v in volumes if v >= 1_000_000),
        "pairs_below_10k": sum(1 for v in volumes if v < 10_000),
        "tickers_ts": _ms_iso(ts) if ts else None,
    }


def select_universe(rest: OKXPublicRest, *, now: Optional[datetime] = None, size: int = UNIVERSE_SIZE) -> Dict[str, Any]:
    """Two public GETs (instruments, tickers) and the fixed rule: the top ``size`` live X-USDT stock pairs by 24-hour quote volume."""
    if size <= 0:
        raise ValueError("size must be positive")
    now = _utc(now or datetime.now(tz=timezone.utc))
    instruments = rest.get(INSTRUMENTS_PATH, {"instType": "SPOT"})
    tickers = rest.get(TICKERS_PATH, {"instType": "SPOT"})
    ranking = rank_xstocks(instruments, tickers)
    if len(ranking) < size:
        raise XStocksDataError(f"only {len(ranking)} eligible stock pairs, fewer than the {size} wanted")
    chosen = [r["instId"] for r in ranking[:size]]
    for r in ranking:
        r["chosen"] = r["instId"] in chosen
    return {
        "version": UNIVERSE_VERSION,
        "selected_at": _iso(now),
        "rule": UNIVERSE_RULE,
        "size": size,
        "pairs": chosen,
        "ranking": ranking,
        "summary": _universe_summary(instruments, ranking, tickers),
    }


def write_universe(path: Path, payload: Mapping[str, Any], *, force: bool = False) -> Path:
    path = Path(path)
    if path.exists() and not force:
        raise XStocksDataError(f"{path} exists; the universe is chosen once (use force to replace it, which starts a new record)")
    _write_json(path, dict(payload))
    return path


def load_universe(path: Path) -> Dict[str, Any]:
    """The committed universe, checked: version, size, ids, no duplicates, the ranking's chosen flags."""
    path = Path(path)
    if not path.exists():
        raise XStocksDataError(f"no universe file at {path}: run the selection once (collect_xstocks.py --select-universe)")
    data = _read_json(path)
    if not isinstance(data, dict) or data.get("version") != UNIVERSE_VERSION:
        raise XStocksDataError(f"{path}: not a version {UNIVERSE_VERSION} universe file")
    pairs = data.get("pairs")
    size = data.get("size")
    if not isinstance(pairs, list) or not isinstance(size, int) or size <= 0 or len(pairs) != size:
        raise XStocksDataError(f"{path}: 'pairs' must hold exactly 'size' ids")
    if len(set(pairs)) != len(pairs) or not all(isinstance(p, str) and XSTOCK_ID_RE.match(p) for p in pairs):
        raise XStocksDataError(f"{path}: 'pairs' must be distinct X-prefixed USDT ids")
    ranking = data.get("ranking")
    if isinstance(ranking, list) and ranking:
        flagged = [r.get("instId") for r in ranking if isinstance(r, Mapping) and r.get("chosen")]
        if flagged != pairs:
            raise XStocksDataError(f"{path}: the ranking's chosen pairs differ from 'pairs'")
    if not isinstance(data.get("selected_at"), str):
        raise XStocksDataError(f"{path}: 'selected_at' missing")
    return data


def universe_pairs(universe: Mapping[str, Any]) -> List[str]:
    return [str(p) for p in universe["pairs"]]


# -- instrument parameters ---------------------------------------------------------------------------------------

def instrument_record(row: Mapping[str, Any]) -> Dict[str, Any]:
    """The recorded subset of one instrument row, values exactly as OKX returns them, plus ISO times."""
    rec: Dict[str, Any] = {k: row.get(k) for k in INSTRUMENT_FIELDS}
    for key in ("listTime", "contTdSwTime"):
        raw = row.get(key)
        rec[f"{key}_iso"] = _ms_iso(int(raw)) if raw not in (None, "") else None
    return rec


def record_instruments(layout: XStocksLayout, rest: OKXPublicRest, pairs: Sequence[str], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """One GET of the SPOT instruments; the universe's rows written to ``instruments/<day>.json`` and ``latest.json``."""
    now = _utc(now or datetime.now(tz=timezone.utc))
    rows = rest.get(INSTRUMENTS_PATH, {"instType": "SPOT"})
    by_id = {str(r.get("instId", "")): r for r in rows if isinstance(r, Mapping)}
    recorded: Dict[str, Any] = {}
    missing: List[str] = []
    not_live: List[str] = []
    for pair in pairs:
        row = by_id.get(pair)
        if row is None:
            missing.append(pair)
            continue
        recorded[pair] = instrument_record(row)
        if str(row.get("state", "")) != "live":
            not_live.append(pair)
    payload = {"recorded_at": _iso(now), "day": now.date().isoformat(), "pairs": recorded, "missing": missing, "not_live": not_live}
    _write_json(layout.instruments_file(now.date()), payload)
    _write_json(layout.instruments_latest, payload)
    return payload


def instruments_recorded_on(layout: XStocksLayout, day: date) -> bool:
    return layout.instruments_file(day).exists()


def latest_instruments(layout: XStocksLayout) -> Optional[Dict[str, Any]]:
    path = layout.instruments_latest
    if not path.exists():
        return None
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), dict):
        raise XStocksDataError(f"{path}: malformed instruments record")
    return data


def list_times(layout: XStocksLayout) -> Dict[str, int]:
    """``listTime`` in ms per recorded pair (the candle walks start there)."""
    latest = latest_instruments(layout)
    if latest is None:
        return {}
    out: Dict[str, int] = {}
    for pair, rec in latest["pairs"].items():
        raw = rec.get("listTime")
        if raw not in (None, ""):
            out[pair] = int(raw)
    return out


# -- candles -----------------------------------------------------------------------------------------------------

def _check_bar(bar: str) -> str:
    if bar not in COLLECTED_BARS:
        raise XStocksDataError(f"bar {bar!r} is not collected; collected bars: {COLLECTED_BARS}")
    return bar


def _check_pair(instrument: str) -> str:
    if not isinstance(instrument, str) or not XSTOCK_ID_RE.match(instrument):
        raise XStocksDataError(f"{instrument!r} is not an X-prefixed USDT stock pair")
    return instrument


def parse_xstock_candle_rows(data: Sequence[Any], bar: str) -> List[Row]:
    """Confirmed, well-formed candles of one bar from an OKX reply, as ``(open_ms, record)`` rows (any order).

    Rows are ``[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]``; for SPOT ``vol`` is the base quantity
    and ``volCcy`` the quote (USDT) quantity. The forming candle, malformed rows, non-finite or non-positive
    prices, incoherent highs/lows and timestamps off the bar's own grid are dropped.
    """
    step = BAR_MS[_check_bar(bar)]
    out: Dict[int, Dict[str, float]] = {}
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 9 or str(row[8]) != "1":
            continue
        try:
            ts = int(row[0])
            o, h, low, c, vol, quote_vol = (float(row[i]) for i in (1, 2, 3, 4, 5, 6))
        except (TypeError, ValueError):
            continue
        if ts <= 0 or ts % step != 0:
            continue
        if not all(math.isfinite(v) for v in (o, h, low, c, vol, quote_vol)) or min(o, h, low, c) <= 0 or vol < 0 or quote_vol < 0:
            continue
        if h < max(o, c, low) or low > min(o, c, h):
            continue
        out[ts] = {"open": o, "high": h, "low": low, "close": c, "volume": vol, "quote_volume": quote_vol}
    return [(ts, out[ts]) for ts in sorted(out)]


class _CandleSource:
    """``PageSource`` over the two public candle endpoints for one pair and bar."""

    def __init__(self, rest: OKXPublicRest, instrument: str, bar: str) -> None:
        self._rest = rest
        self._instrument = _check_pair(instrument)
        self._bar = _check_bar(bar)

    def fetch_newest(self) -> Sequence[Row]:
        return parse_xstock_candle_rows(self._rest.get(CANDLES_PATH, {"instId": self._instrument, "bar": self._bar, "limit": NEWEST_LIMIT}), self._bar)

    def fetch_older(self, cursor_ms: int) -> Sequence[Row]:
        return parse_xstock_candle_rows(
            self._rest.get(HISTORY_CANDLES_PATH, {"instId": self._instrument, "bar": self._bar, "after": int(cursor_ms), "limit": HISTORY_LIMIT}), self._bar)


def _write_candle_rows(layout: XStocksLayout, instrument: str, bar: str, rows: Sequence[Row]) -> int:
    if not rows:
        return 0
    stamps = [from_ms(int(ms)) for ms, _ in rows]
    recs = [payload for _, payload in rows]
    table = pa.table(
        {
            "open_time": pa.array(stamps, type=TS_TYPE),
            "instrument": pa.array([instrument] * len(rows), type=pa.string()),
            "timeframe": pa.array([bar] * len(rows), type=pa.string()),
            "open": pa.array([r["open"] for r in recs], type=pa.float64()),
            "high": pa.array([r["high"] for r in recs], type=pa.float64()),
            "low": pa.array([r["low"] for r in recs], type=pa.float64()),
            "close": pa.array([r["close"] for r in recs], type=pa.float64()),
            "volume": pa.array([r["volume"] for r in recs], type=pa.float64()),
            "confirmed": pa.array([True] * len(rows), type=pa.bool_()),
            "quote_volume": pa.array([r["quote_volume"] for r in recs], type=pa.float64()),
        },
        schema=XSTOCK_CANDLE_SCHEMA,
    )
    res = write_partitioned(table, key="open_time", schema=XSTOCK_CANDLE_SCHEMA, file_for_year=lambda y: layout.candles_file(instrument, bar, y))
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


def collect_candles(
    layout: XStocksLayout,
    instrument: str,
    bar: str,
    *,
    rest: Optional[OKXPublicRest] = None,
    start_ms: int,
    max_pages: Optional[int] = None,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> CandleCollectReport:
    """One resumable session collecting a pair's public candles for ``bar`` back to ``start_ms`` (its ``listTime``)."""
    _check_pair(instrument)
    _check_bar(bar)
    if int(start_ms) <= 0:
        raise ValueError("start_ms must be after the Unix epoch")
    added = 0

    def on_page(rows: Sequence[Row]) -> None:
        nonlocal added
        added += _write_candle_rows(layout, instrument, bar, rows)

    walker = BackwardWalker(_CandleSource(rest or OKXPublicRest(), instrument, bar), state_path=layout.candle_state_file(instrument, bar),
                            start_ms=int(start_ms), on_page=on_page, max_pages=max_pages, sleep_seconds=sleep_seconds, sleep=sleep)
    report = CandleCollectReport(instrument=instrument, bar=bar, walk=walker.run(), added=added)
    cov = coverage(layout.candles_dir(instrument, bar), "open_time")
    report.stored_rows = cov.rows
    report.stored_min = from_ms(cov.min_ms) if cov.min_ms is not None else None
    report.stored_max = from_ms(cov.max_ms) if cov.max_ms is not None else None
    return report


_CANDLE_COLUMNS = ("open", "high", "low", "close", "volume", "quote_volume")


def read_xstock_candles(layout: XStocksLayout, instrument: str, bar: str) -> pd.DataFrame:
    """The stored candles of one pair and bar, oldest first, ``open_time`` (UTC) as the index; empty when nothing is stored."""
    directory = layout.candles_dir(instrument, _check_bar(bar))
    files = sorted(p for p in directory.glob("*.parquet") if p.stem.isdigit()) if directory.exists() else []
    if not files:
        return pd.DataFrame(columns=list(_CANDLE_COLUMNS), index=pd.DatetimeIndex([], tz="UTC", name="open_time"), dtype=float)
    table = pa.concat_tables([pq.read_table(f).cast(XSTOCK_CANDLE_SCHEMA) for f in files])
    frame = table.to_pandas()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    return frame[list(_CANDLE_COLUMNS)].astype(float)


# -- the snapshot schedule ----------------------------------------------------------------------------------------

def is_us_market_holiday(day: date) -> bool:
    return day.isoformat() in US_MARKET_HOLIDAYS


def is_us_trading_day(day: date) -> bool:
    return day.weekday() < 5 and not is_us_market_holiday(day)


def us_session_open_at(moment: datetime) -> bool:
    """Whether the US regular session (09:30-16:00 New York, trading days) is open at ``moment``."""
    ny = _utc(moment).astimezone(NEW_YORK)
    if not is_us_trading_day(ny.date()):
        return False
    close = dtime(13, 0) if ny.date().isoformat() in US_EARLY_CLOSES else US_CLOSE
    return US_OPEN <= ny.time() < close


@dataclass(frozen=True)
class Slot:
    name: str
    scheduled: datetime  # UTC
    ny_date: date

    @property
    def key(self) -> str:
        return f"{self.name}@{self.scheduled:%Y-%m-%dT%H:%MZ}"

    @property
    def us_holiday(self) -> bool:
        return is_us_market_holiday(self.ny_date)


def _ny_slot(day: date, at: dtime, name: str) -> Slot:
    scheduled = datetime.combine(day, at, tzinfo=NEW_YORK).astimezone(timezone.utc)
    return Slot(name, scheduled, day)


def slots_between(start: datetime, end: datetime) -> List[Slot]:
    """Every scheduled snapshot with ``start <= scheduled < end`` (UTC), in time order."""
    start, end = _utc(start), _utc(end)
    out: List[Slot] = []
    day = start.astimezone(NEW_YORK).date() - timedelta(days=1)
    last = end.astimezone(NEW_YORK).date() + timedelta(days=1)
    while day <= last:
        if day.weekday() < 5:
            out.append(_ny_slot(day, US_OPEN, SLOT_US_OPEN))
            out.append(_ny_slot(day, US_CLOSE, SLOT_US_CLOSE))
        day += timedelta(days=1)
    uday = start.date() - timedelta(days=1)
    ulast = end.date() + timedelta(days=1)
    while uday <= ulast:
        at3 = datetime(uday.year, uday.month, uday.day, 3, tzinfo=timezone.utc)
        out.append(Slot(SLOT_UTC_03, at3, at3.astimezone(NEW_YORK).date()))
        if uday.weekday() == 5:
            at12 = datetime(uday.year, uday.month, uday.day, 12, tzinfo=timezone.utc)
            out.append(Slot(SLOT_SAT_12, at12, at12.astimezone(NEW_YORK).date()))
        uday += timedelta(days=1)
    out = [s for s in out if start <= s.scheduled < end]
    out.sort(key=lambda s: (s.scheduled, s.name))
    return out


def due_slots(now: datetime, taken: Collection[str], *, grace_minutes: float = SNAPSHOT_GRACE_MINUTES) -> List[Slot]:
    """Scheduled slots whose time has come within the last ``grace_minutes`` and that were not taken yet."""
    now = _utc(now)
    window = slots_between(now - timedelta(minutes=grace_minutes), now + timedelta(microseconds=1))
    return [s for s in window if s.key not in taken]


def next_slot(now: datetime) -> Slot:
    now = _utc(now)
    upcoming = slots_between(now + timedelta(microseconds=1), now + timedelta(days=8))
    if not upcoming:  # pragma: no cover - there is always one within a day
        raise XStocksDataError("no scheduled slot within 8 days")
    return upcoming[0]


def adhoc_slot(now: datetime) -> Slot:
    now = _utc(now)
    return Slot(SLOT_ADHOC, now.replace(microsecond=0), now.astimezone(NEW_YORK).date())


# -- order books ------------------------------------------------------------------------------------------------

def parse_book(data: Sequence[Any], instrument: str) -> Dict[str, Any]:
    """The one book of a ``/market/books`` reply: asks ascending, bids descending, ``[price, size, orders]`` floats."""
    if not isinstance(data, (list, tuple)) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise XStocksDataError(f"{instrument}: malformed books reply")
    book = data[0]

    def levels(side: str) -> List[List[float]]:
        out: List[List[float]] = []
        for level in book.get(side) or []:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                raise XStocksDataError(f"{instrument}: malformed {side} level {level!r}")
            px = _float(level[0], f"{side} price")
            sz = _float(level[1], f"{side} size")
            orders = _float(level[3], f"{side} orders", allow_blank=True) if len(level) > 3 else math.nan
            if px <= 0 or sz < 0:
                raise XStocksDataError(f"{instrument}: bad {side} level {level!r}")
            out.append([px, sz, 0 if math.isnan(orders) else int(orders)])
        return out

    asks = sorted(levels("asks"), key=lambda l: l[0])
    bids = sorted(levels("bids"), key=lambda l: -l[0])
    ts = int(book.get("ts") or 0)
    if ts <= 0:
        raise XStocksDataError(f"{instrument}: books reply without ts")
    return {"instrument": instrument, "ts": ts, "seq_id": book.get("seqId"), "asks": asks, "bids": bids}


def book_metrics(book: Mapping[str, Any], *, band: float = DEPTH_BAND_PCT) -> Dict[str, Any]:
    """Spread, depth within ``band`` of mid (quote currency, each side), how far the levels reach and whether the band was covered."""
    asks, bids = book.get("asks") or [], book.get("bids") or []
    if not asks or not bids:
        return {"empty": True, "levels_returned": [len(bids), len(asks)]}
    best_ask, best_bid = float(asks[0][0]), float(bids[0][0])
    mid = (best_ask + best_bid) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 1e4
    ask_depth = sum(px * sz for px, sz, *_ in asks if px <= mid * (1.0 + band))
    bid_depth = sum(px * sz for px, sz, *_ in bids if px >= mid * (1.0 - band))
    ask_levels = sum(1 for px, *_ in asks if px <= mid * (1.0 + band))
    bid_levels = sum(1 for px, *_ in bids if px >= mid * (1.0 - band))
    ask_reach = asks[-1][0] / mid - 1.0
    bid_reach = 1.0 - bids[-1][0] / mid
    return {
        "empty": False,
        "best_bid": best_bid, "best_ask": best_ask, "mid": mid, "spread_bps": spread_bps,
        "best_bid_size": float(bids[0][1]), "best_ask_size": float(asks[0][1]),
        "bid_depth_05": bid_depth, "ask_depth_05": ask_depth, "bid_levels_05": bid_levels, "ask_levels_05": ask_levels,
        "bid_reach_pct": bid_reach * 100.0, "ask_reach_pct": ask_reach * 100.0,
        "band_covered_bid": bid_reach >= band, "band_covered_ask": ask_reach >= band,
        "levels_returned": [len(bids), len(asks)],
    }


def trim_book(book: Mapping[str, Any], *, keep_pct: float = BOOK_KEEP_PCT) -> Dict[str, Any]:
    """The levels within ``keep_pct`` of mid (what is stored), the far tail dropped."""
    asks, bids = book.get("asks") or [], book.get("bids") or []
    if not asks or not bids:
        return {"asks": list(asks), "bids": list(bids), "levels_kept": [len(bids), len(asks)]}
    mid = (float(asks[0][0]) + float(bids[0][0])) / 2.0
    kept_asks = [l for l in asks if l[0] <= mid * (1.0 + keep_pct)]
    kept_bids = [l for l in bids if l[0] >= mid * (1.0 - keep_pct)]
    return {"asks": kept_asks, "bids": kept_bids, "levels_kept": [len(kept_bids), len(kept_asks)]}


def fetch_book(rest: OKXPublicRest, instrument: str, *, levels: int = BOOK_LEVELS) -> Dict[str, Any]:
    _check_pair(instrument)
    return parse_book(rest.get(BOOKS_PATH, {"instId": instrument, "sz": int(levels)}), instrument)


def fetch_price_limit(rest: OKXPublicRest, instrument: str) -> Dict[str, Any]:
    """The venue's current buy/sell price limits for the pair (public GET; the band the instrument parameters describe)."""
    _check_pair(instrument)
    data = rest.get(PRICE_LIMIT_PATH, {"instId": instrument})
    if not isinstance(data, (list, tuple)) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise XStocksDataError(f"{instrument}: malformed price-limit reply")
    row = data[0]
    return {"buy_limit": _float(row.get("buyLmt"), "buyLmt", allow_blank=True), "sell_limit": _float(row.get("sellLmt"), "sellLmt", allow_blank=True),
            "enabled": bool(row.get("enabled")), "ts": int(row.get("ts") or 0) or None}


def load_books_state(layout: XStocksLayout) -> Dict[str, Any]:
    path = layout.books_state_file
    if not path.exists():
        return {"version": 1, "taken": {}}
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("taken"), dict):
        raise XStocksDataError(f"{path}: malformed books state")
    return data


def save_books_state(layout: XStocksLayout, state: Dict[str, Any], *, now: datetime) -> None:
    cutoff = (_utc(now) - timedelta(days=BOOKS_STATE_KEEP_DAYS)).strftime("%Y-%m-%dT%H:%MZ")
    taken = {k: v for k, v in state["taken"].items() if k.split("@", 1)[-1] >= cutoff}
    _write_json(layout.books_state_file, {"version": 1, "taken": taken, "updated_at": _iso(now)})


def taken_slot_keys(layout: XStocksLayout) -> set:
    return set(load_books_state(layout)["taken"])


@dataclass
class SnapshotReport:
    slot: Slot
    taken: int = 0
    errors: List[str] = field(default_factory=list)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return (f"snapshot {self.slot.key}: {self.taken} book(s) stored" + (f", {len(self.errors)} error(s): {self.errors[0]}" if self.errors else "")
                + (" (US market holiday)" if self.slot.us_holiday else ""))


def take_snapshots(
    layout: XStocksLayout,
    rest: OKXPublicRest,
    pairs: Sequence[str],
    slot: Slot,
    *,
    now: Optional[datetime] = None,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    price_limit: bool = True,
    levels: int = BOOK_LEVELS,
) -> SnapshotReport:
    """One order book per pair (and its price limits), appended as one JSON line each to ``books/<pair>/<slot day>.jsonl``.

    A pair that fails is logged in the report and skipped; the slot is marked taken when at least one book was
    stored, so a run that found the network down tries again within the grace window.
    """
    now = _utc(now or datetime.now(tz=timezone.utc))
    report = SnapshotReport(slot=slot)
    day = slot.scheduled.date()
    for pair in pairs:
        try:
            _check_pair(pair)
            book = fetch_book(rest, pair, levels=levels)
            if sleep_seconds:
                sleep(sleep_seconds)
            limits: Optional[Dict[str, Any]] = None
            limit_error: Optional[str] = None
            if price_limit:
                try:
                    limits = fetch_price_limit(rest, pair)
                except (PublicRestError, XStocksDataError, ValueError) as exc:
                    limit_error = f"{type(exc).__name__}: {exc}"
                if sleep_seconds:
                    sleep(sleep_seconds)
            fetched = now
            metrics = book_metrics(book)
            trimmed = trim_book(book)
            record: Dict[str, Any] = {
                "instrument": pair, "slot": slot.name, "slot_key": slot.key, "scheduled_at": _iso(slot.scheduled), "fetched_at": _iso(fetched),
                "ny_time": fetched.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M:%S %Z"), "ny_date": slot.ny_date.isoformat(),
                "us_trading_day": is_us_trading_day(slot.ny_date), "us_holiday": slot.us_holiday, "us_early_close": slot.ny_date.isoformat() in US_EARLY_CLOSES,
                "us_session_open": us_session_open_at(fetched), "ts": book["ts"], "ts_iso": _ms_iso(book["ts"]), "seq_id": book.get("seq_id"),
                **metrics, "levels_kept": trimmed["levels_kept"], "price_limit": limits, "price_limit_error": limit_error,
                "asks": trimmed["asks"], "bids": trimmed["bids"],
            }
            path = layout.books_file(pair, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            report.taken += 1
            report.records.append({k: v for k, v in record.items() if k not in ("asks", "bids")})
        except (PublicRestError, XStocksDataError, ValueError, OSError) as exc:
            report.errors.append(f"{pair}: {type(exc).__name__}: {exc}")
    if report.taken > 0 and slot.name != SLOT_ADHOC:
        state = load_books_state(layout)
        state["taken"][slot.key] = {"at": _iso(now), "stored": report.taken, "errors": report.errors[:5]}
        save_books_state(layout, state, now=now)
    return report


def read_snapshots(layout: XStocksLayout, instrument: str) -> List[Dict[str, Any]]:
    """Every stored snapshot of one pair without its levels (metrics, slot and times), oldest first."""
    directory = layout.books_dir(instrument)
    out: List[Dict[str, Any]] = []
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append({k: v for k, v in rec.items() if k not in ("asks", "bids")})
    out.sort(key=lambda r: (str(r.get("fetched_at", "")), str(r.get("slot", ""))))
    return out


# -- passes ------------------------------------------------------------------------------------------------------

def _log_noop(message: str) -> None:
    return None


def run_once(
    layout: XStocksLayout,
    universe: Mapping[str, Any],
    *,
    rest: Optional[OKXPublicRest] = None,
    now: Optional[datetime] = None,
    max_pages: Optional[int] = None,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    snapshot_now: bool = False,
    bars: Sequence[str] = COLLECTED_BARS,
    log: Callable[[str], None] = _log_noop,
) -> Dict[str, Any]:
    """One pass: today's parameter record if missing, the candle top-up for every pair and bar, the due snapshots.

    ``snapshot_now`` adds an ``adhoc`` snapshot of every pair at ``now`` (the first run, a smoke test).
    """
    rest = rest or OKXPublicRest()
    now = _utc(now or datetime.now(tz=timezone.utc))
    pairs = universe_pairs(universe)
    summary: Dict[str, Any] = {"at": _iso(now), "pairs": len(pairs), "instruments": None, "candles": [], "snapshots": [], "errors": []}
    if not instruments_recorded_on(layout, now.date()) or latest_instruments(layout) is None:
        try:
            rec = record_instruments(layout, rest, pairs, now=now)
            summary["instruments"] = {"day": rec["day"], "recorded": len(rec["pairs"]), "missing": rec["missing"], "not_live": rec["not_live"]}
            log(f"instruments recorded for {rec['day']}: {len(rec['pairs'])} pair(s)" + (f", missing {rec['missing']}" if rec["missing"] else "")
                + (f", not live {rec['not_live']}" if rec["not_live"] else ""))
            if sleep_seconds:
                sleep(sleep_seconds)
        except (PublicRestError, XStocksDataError, ValueError, OSError) as exc:
            summary["errors"].append(f"instruments: {type(exc).__name__}: {exc}")
            log(f"instruments: ERROR {type(exc).__name__}: {exc}")
    starts = list_times(layout)
    for pair in pairs:
        start = starts.get(pair)
        if start is None:
            summary["errors"].append(f"{pair}: no listTime recorded, candles skipped")
            log(f"{pair}: no listTime recorded, candles skipped")
            continue
        for bar in bars:
            try:
                rep = collect_candles(layout, pair, bar, rest=rest, start_ms=start, max_pages=max_pages, sleep_seconds=sleep_seconds, sleep=sleep)
            except (PublicRestError, XStocksDataError, ValueError, OSError) as exc:
                summary["errors"].append(f"{pair} {bar}: {type(exc).__name__}: {exc}")
                log(f"{pair} {bar}: ERROR {type(exc).__name__}: {exc}")
                continue
            summary["candles"].append({"instrument": pair, "bar": bar, "pages": rep.walk.pages, "added": rep.added, "stored": rep.stored_rows,
                                       "complete": rep.walk.complete, "reason": rep.walk.reason,
                                       "min": _iso(rep.stored_min) if rep.stored_min else None, "max": _iso(rep.stored_max) if rep.stored_max else None})
            log(rep.summary())
    slots = due_slots(now, taken_slot_keys(layout))
    if snapshot_now:
        slots.append(adhoc_slot(now))
    for slot in slots:
        rep = take_snapshots(layout, rest, pairs, slot, now=now, sleep_seconds=sleep_seconds, sleep=sleep)
        summary["snapshots"].append({"slot": slot.name, "key": slot.key, "stored": rep.taken, "errors": rep.errors})
        summary["errors"].extend(rep.errors)
        log(rep.summary())
    return summary


def run_loop(
    layout: XStocksLayout,
    universe: Mapping[str, Any],
    *,
    rest: Optional[OKXPublicRest] = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    wait: Callable[[float], bool],
    max_minutes: Optional[float] = None,
    poll_seconds: float = 30.0,
    max_pages: Optional[int] = None,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = _log_noop,
) -> Dict[str, Any]:
    """The service: a full pass at the start, then snapshots at their slots, 1H candles topped up after every hour,
    1Dutc candles and the parameter record once a day. ``wait(seconds)`` returns True when a stop was requested."""
    rest = rest or OKXPublicRest()
    pairs = universe_pairs(universe)
    started = _utc(now_fn())
    stats: Dict[str, Any] = {"started": _iso(started), "passes": 1, "snapshots": 0, "topups": 0, "errors": 0}
    first = run_once(layout, universe, rest=rest, now=started, max_pages=max_pages, sleep_seconds=sleep_seconds, sleep=sleep, log=log)
    stats["errors"] += len(first["errors"])
    stats["snapshots"] += sum(s["stored"] for s in first["snapshots"])
    last_hour = started.replace(minute=0, second=0, microsecond=0)
    last_day = started.date()
    while True:
        now = _utc(now_fn())
        if max_minutes is not None and (now - started) >= timedelta(minutes=max_minutes):
            stats["stopped"] = "max_minutes"
            break
        taken = taken_slot_keys(layout)
        for slot in due_slots(now, taken):
            rep = take_snapshots(layout, rest, pairs, slot, now=now, sleep_seconds=sleep_seconds, sleep=sleep)
            stats["snapshots"] += rep.taken
            stats["errors"] += len(rep.errors)
            log(rep.summary())
        hour = now.replace(minute=0, second=0, microsecond=0)
        if hour > last_hour and (now - hour) >= timedelta(seconds=TOPUP_DELAY_SECONDS):
            bars: List[str] = ["1H"]
            if now.date() != last_day:
                bars.append("1Dutc")
                if not instruments_recorded_on(layout, now.date()):
                    try:
                        rec = record_instruments(layout, rest, pairs, now=now)
                        log(f"instruments recorded for {rec['day']}: {len(rec['pairs'])} pair(s)" + (f", missing {rec['missing']}" if rec["missing"] else ""))
                    except (PublicRestError, XStocksDataError, ValueError, OSError) as exc:
                        stats["errors"] += 1
                        log(f"instruments: ERROR {type(exc).__name__}: {exc}")
                last_day = now.date()
            starts = list_times(layout)
            added = 0
            for pair in pairs:
                start = starts.get(pair)
                if start is None:
                    continue
                for bar in bars:
                    try:
                        rep = collect_candles(layout, pair, bar, rest=rest, start_ms=start, max_pages=max_pages, sleep_seconds=sleep_seconds, sleep=sleep)
                        added += rep.added
                    except (PublicRestError, XStocksDataError, ValueError, OSError) as exc:
                        stats["errors"] += 1
                        log(f"{pair} {bar}: ERROR {type(exc).__name__}: {exc}")
            stats["topups"] += 1
            stats["passes"] += 1
            log(f"top-up {_iso(now)}: bars {bars}, {added} candle(s) added")
            last_hour = hour
        upcoming = next_slot(now).scheduled
        next_topup = hour + timedelta(seconds=TOPUP_DELAY_SECONDS) if hour > last_hour else hour + timedelta(hours=1, seconds=TOPUP_DELAY_SECONDS)
        wake = min(upcoming, next_topup, now + timedelta(seconds=poll_seconds))
        if max_minutes is not None:
            wake = min(wake, started + timedelta(minutes=max_minutes))
        if wait(max(1.0, (wake - now).total_seconds())):
            stats["stopped"] = "signal"
            break
    stats["ended"] = _iso(_utc(now_fn()))
    return stats


# -- what the data says ------------------------------------------------------------------------------------------

def _pct(values: Sequence[float]) -> Dict[str, Optional[float]]:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return {"n": 0, "median_abs": None, "max_abs": None, "mean": None}
    return {"n": len(vals), "median_abs": statistics.median(abs(v) for v in vals), "max_abs": max(abs(v) for v in vals), "mean": statistics.fmean(vals)}


def history_metrics(frame: pd.DataFrame, *, list_time_ms: Optional[int], now: datetime) -> Dict[str, Any]:
    """From a pair's stored 1H candles, on the New York clock: history, weekday/weekend volume, US-hours share,
    weekend gaps (Friday 16:00 to the next trading day's 09:00), open jumps (09:00 to 10:00 on that day) and the
    largest weekend deviation from Friday's close. Percentages are log returns x 100."""
    now = _utc(now)
    out: Dict[str, Any] = {"candles_1h": int(len(frame)), "listed_at": _ms_iso(list_time_ms) if list_time_ms else None,
                           "days_since_listing": ((now - from_ms(list_time_ms)).total_seconds() / 86400.0) if list_time_ms else None}
    if frame.empty:
        out.update({"first_candle": None, "last_candle": None, "coverage_pct": None, "weekday_volume_mean": None, "weekend_volume_mean": None,
                    "weekend_to_weekday_volume": None, "us_hours_volume_share": None, "weekends": 0, "gap": _pct([]), "jump": _pct([]),
                    "weekend_dev": _pct([]), "weekend_fall": _pct([]), "weekend_records": []})
        return out
    idx = frame.index
    ny = idx.tz_convert(NEW_YORK)
    first, last = idx[0], idx[-1]
    expected = int((last - first) / pd.Timedelta(hours=1)) + 1
    out["first_candle"] = _iso(first.to_pydatetime())
    out["last_candle"] = _iso(last.to_pydatetime())
    out["coverage_pct"] = 100.0 * len(frame) / expected if expected > 0 else None
    out["zero_volume_hours_pct"] = 100.0 * float((frame["volume"] <= 0).mean())
    data = pd.DataFrame({"qv": frame["quote_volume"].to_numpy(), "close": frame["close"].to_numpy()}, index=idx)
    data["ny_date"] = [t.date() for t in ny]
    data["ny_hour"] = ny.hour
    per_day = data.groupby("ny_date").agg(qv=("qv", "sum"), hours=("qv", "size"))
    full = per_day[per_day["hours"] >= 20]
    days = [d for d in full.index]
    weekday_days = [d for d in days if is_us_trading_day(d)]
    weekend_days = [d for d in days if d.weekday() >= 5]
    wk_mean = float(full.loc[weekday_days, "qv"].mean()) if weekday_days else None
    we_mean = float(full.loc[weekend_days, "qv"].mean()) if weekend_days else None
    out["full_days"] = len(days)
    out["weekday_days"] = len(weekday_days)
    out["weekend_days"] = len(weekend_days)
    out["weekday_volume_mean"] = wk_mean
    out["weekend_volume_mean"] = we_mean
    out["weekend_to_weekday_volume"] = (we_mean / wk_mean) if wk_mean and we_mean is not None else None
    trading = data[[is_us_trading_day(d) for d in data["ny_date"]]]
    total_trading = float(trading["qv"].sum())
    in_hours = float(trading[(trading["ny_hour"] >= 9) & (trading["ny_hour"] < 16)]["qv"].sum())
    out["us_hours_volume_share"] = (in_hours / total_trading) if total_trading > 0 else None
    closes: Dict[Tuple[date, int], float] = {}
    for d, h, c in zip(data["ny_date"], data["ny_hour"], data["close"]):
        closes[(d, int(h))] = float(c)
    trading_days = sorted({d for d in data["ny_date"] if is_us_trading_day(d)})
    gaps: List[float] = []
    jumps: List[float] = []
    devs: List[float] = []
    falls: List[float] = []
    records: List[Dict[str, Any]] = []
    for i, d in enumerate(trading_days):
        if d.weekday() != 4:
            continue
        nxt = next((t for t in trading_days[i + 1:]), None)
        if nxt is None or (d, 15) not in closes or (nxt, 8) not in closes or (nxt, 9) not in closes:
            continue
        c_fri, c_pre, c_first = closes[(d, 15)], closes[(nxt, 8)], closes[(nxt, 9)]
        gap = math.log(c_pre / c_fri) * 100.0
        jump = math.log(c_first / c_pre) * 100.0
        start_ny = datetime.combine(d, dtime(16, 0), tzinfo=NEW_YORK)
        end_ny = datetime.combine(nxt, dtime(9, 0), tzinfo=NEW_YORK)
        closed = data[(ny > start_ny) & (ny < end_ny)]
        logs = (closed["close"] / c_fri).apply(math.log) * 100.0 if len(closed) else None
        dev = float(logs.abs().max()) if logs is not None else math.nan
        fall = float(max(0.0, -logs.min())) if logs is not None else math.nan
        gaps.append(gap)
        jumps.append(jump)
        devs.append(dev)
        falls.append(fall)
        records.append({"friday": d.isoformat(), "next_trading_day": nxt.isoformat(), "friday_close": c_fri, "pre_open": c_pre, "first_hour_close": c_first,
                        "gap_pct": gap, "jump_pct": jump, "weekend_dev_pct": None if math.isnan(dev) else dev,
                        "weekend_fall_pct": None if math.isnan(fall) else fall, "closed_hours": int(len(closed))})
    out["weekends"] = len(records)
    out["gap"] = _pct(gaps)
    out["jump"] = _pct(jumps)
    out["weekend_dev"] = _pct(devs)
    out["weekend_fall"] = _pct(falls)
    out["weekend_records"] = records
    return out


def snapshot_metrics(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Per slot: how many snapshots, the median spread, the median depth within 0.5 % per side, how often the band was covered."""
    out: Dict[str, Any] = {"snapshots": len(records), "by_slot": {}, "latest": None}
    by_slot: Dict[str, List[Mapping[str, Any]]] = {}
    for rec in records:
        if rec.get("empty"):
            continue
        by_slot.setdefault(str(rec.get("slot")), []).append(rec)
    for slot, recs in sorted(by_slot.items()):
        out["by_slot"][slot] = {
            "n": len(recs),
            "spread_bps_median": statistics.median(float(r["spread_bps"]) for r in recs),
            "bid_depth_05_median": statistics.median(float(r["bid_depth_05"]) for r in recs),
            "ask_depth_05_median": statistics.median(float(r["ask_depth_05"]) for r in recs),
            "mid_median": statistics.median(float(r["mid"]) for r in recs),
            "band_covered_share": statistics.fmean(1.0 if (r.get("band_covered_bid") and r.get("band_covered_ask")) else 0.0 for r in recs),
            "us_session_open_share": statistics.fmean(1.0 if r.get("us_session_open") else 0.0 for r in recs),
        }
    non_empty = [r for r in records if not r.get("empty")]
    if non_empty:
        latest = non_empty[-1]
        out["latest"] = {k: latest.get(k) for k in ("slot", "fetched_at", "ny_time", "us_session_open", "spread_bps", "bid_depth_05", "ask_depth_05", "mid",
                                                   "band_covered_bid", "band_covered_ask", "levels_returned", "price_limit")}
    out["empty_books"] = sum(1 for r in records if r.get("empty"))
    return out


def feasibility_rows(layout: XStocksLayout, universe: Mapping[str, Any], *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One row per pair of the universe: rank and volume, the recorded parameters, the history metrics, the snapshot metrics."""
    now = _utc(now or datetime.now(tz=timezone.utc))
    latest = latest_instruments(layout) or {"pairs": {}}
    ranking = {r["instId"]: r for r in universe.get("ranking", []) if isinstance(r, Mapping)}
    rows: List[Dict[str, Any]] = []
    for pair in universe_pairs(universe):
        params = latest["pairs"].get(pair) or {}
        list_ms = int(params["listTime"]) if params.get("listTime") not in (None, "") else (ranking.get(pair, {}).get("list_time_ms"))
        frame = read_xstock_candles(layout, pair, "1H")
        daily = coverage(layout.candles_dir(pair, "1Dutc"), "open_time")
        rows.append({
            "instrument": pair,
            "rank": ranking.get(pair, {}).get("rank"),
            "quote_volume_24h_at_selection": ranking.get(pair, {}).get("quote_volume_24h"),
            "parameters": {k: params.get(k) for k in ("lotSz", "minSz", "tickSz", "maxMktAmt", "maxLmtAmt", "initPxLmtPct", "floatPxLmtPct", "maxPxLmtPct",
                                                      "groupId", "lever", "state", "openType")},
            "candles_1dutc": daily.rows,
            "history": history_metrics(frame, list_time_ms=list_ms, now=now),
            "snapshots": snapshot_metrics(read_snapshots(layout, pair)),
        })
    return rows


def _fmt(value: Any, digits: int = 1, *, suffix: str = "", none: str = "-") -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return none
    if isinstance(value, float):
        return f"{value:,.{digits}f}{suffix}"
    return f"{value}{suffix}"


def render_feasibility_tables(rows: Sequence[Mapping[str, Any]], *, now: datetime) -> str:
    """The per-pair Markdown tables of the feasibility report, computed from the stored data."""
    lines: List[str] = [f"Generated by `scripts/collect_xstocks.py --report` on {_iso(now)} from the lake under `data/lake/xstocks/`.", ""]
    lines += ["**A. The universe and the venue's parameters** (24-hour quote volume at selection; parameters from the latest daily record)", "",
              "| # | Pair | 24h volume (USDT) | Lot | Min size | Tick | Max market order (USDT) | Band open / floating / max | Fee group | Listed (UTC) |",
              "|---:|---|---:|---|---|---|---:|---|---|---|"]
    for r in rows:
        p = r["parameters"]
        h = r["history"]
        lines.append(f"| {r['rank'] or '-'} | {r['instrument']} | {_fmt(r['quote_volume_24h_at_selection'], 0)} | {p.get('lotSz') or '-'} | {p.get('minSz') or '-'} | "
                     f"{p.get('tickSz') or '-'} | {_fmt(float(p['maxMktAmt']) if p.get('maxMktAmt') else None, 0)} | "
                     f"{p.get('initPxLmtPct') or '-'} / {p.get('floatPxLmtPct') or '-'} / {p.get('maxPxLmtPct') or '-'} | {p.get('groupId') or '-'} | "
                     f"{(h.get('listed_at') or '-')[:10]} |")
    lines += ["", "**B. History and where the volume is** (1H candles on the New York clock; a day counts when at least 20 of its hours are stored; "
              "US hours = the candles opening 09:00-15:59 New York on trading days, so the 09:00 candle's first half hour is pre-open)", "",
              "| Pair | Days since listing | 1H candles | Coverage | Weekday volume / day (USDT) | Weekend volume / day (USDT) | Weekend / weekday | "
              "US-hours share of weekday volume | Hours with no trade |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        h = r["history"]
        lines.append(f"| {r['instrument']} | {_fmt(h.get('days_since_listing'), 0)} | {h.get('candles_1h', 0):,} | {_fmt(h.get('coverage_pct'), 1, suffix=' %')} | "
                     f"{_fmt(h.get('weekday_volume_mean'), 0)} | {_fmt(h.get('weekend_volume_mean'), 0)} | "
                     f"{_fmt(100.0 * h['weekend_to_weekday_volume'] if h.get('weekend_to_weekday_volume') is not None else None, 0, suffix=' %')} | "
                     f"{_fmt(100.0 * h['us_hours_volume_share'] if h.get('us_hours_volume_share') is not None else None, 0, suffix=' %')} | "
                     f"{_fmt(h.get('zero_volume_hours_pct'), 1, suffix=' %')} |")
    lines += ["", "**C. Weekend gaps and the open** (gap = Friday 16:00 New York close to the next trading day's 09:00 price, half an hour before "
              "the open; jump = that day's 09:00 to 10:00 hour, which contains the open; weekend deviation = the farthest hourly close from "
              "Friday's close while the US market was shut, in either direction; weekend fall = the deepest hourly close below Friday's close "
              "in that time, what a long position's stop would have met; log returns)", "",
              "| Pair | Weekends | Gap: median abs | Gap: max abs | Gap: mean | Open jump: median abs | Open jump: max abs | Weekend deviation: median | "
              "Weekend deviation: max | Weekend fall: median | Weekend fall: max |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        h = r["history"]
        g, j, d, f = h.get("gap") or {}, h.get("jump") or {}, h.get("weekend_dev") or {}, h.get("weekend_fall") or {}
        lines.append(f"| {r['instrument']} | {h.get('weekends', 0)} | {_fmt(g.get('median_abs'), 2, suffix=' %')} | {_fmt(g.get('max_abs'), 2, suffix=' %')} | "
                     f"{_fmt(g.get('mean'), 2, suffix=' %')} | {_fmt(j.get('median_abs'), 2, suffix=' %')} | {_fmt(j.get('max_abs'), 2, suffix=' %')} | "
                     f"{_fmt(d.get('median_abs'), 2, suffix=' %')} | {_fmt(d.get('max_abs'), 2, suffix=' %')} | "
                     f"{_fmt(f.get('median_abs'), 2, suffix=' %')} | {_fmt(f.get('max_abs'), 2, suffix=' %')} |")
    lines += ["", "**D. Spread and depth from the order-book snapshots** (per slot: snapshots, median spread, median depth within 0.5 % of mid per "
              "side in USDT, share of snapshots whose stored levels reached 0.5 % on both sides)", "",
              "| Pair | Slot | Snapshots | Spread (bps) | Bid depth 0.5 % | Ask depth 0.5 % | Mid | Band covered | US session open |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        s = r["snapshots"]
        if not s.get("by_slot"):
            lines.append(f"| {r['instrument']} | - | 0 | - | - | - | - | - | - |")
            continue
        for slot, m in s["by_slot"].items():
            lines.append(f"| {r['instrument']} | {slot} | {m['n']} | {_fmt(m['spread_bps_median'], 1)} | {_fmt(m['bid_depth_05_median'], 0)} | "
                         f"{_fmt(m['ask_depth_05_median'], 0)} | {_fmt(m['mid_median'], 2)} | {_fmt(100.0 * m['band_covered_share'], 0, suffix=' %')} | "
                         f"{_fmt(100.0 * m['us_session_open_share'], 0, suffix=' %')} |")
    return "\n".join(lines) + "\n"


def write_feasibility_json(path: Path, rows: Sequence[Mapping[str, Any]], universe: Mapping[str, Any], *, now: datetime) -> Path:
    payload = {"generated_at": _iso(now), "universe_selected_at": universe.get("selected_at"), "pairs": universe_pairs(universe), "rows": list(rows)}
    _write_json(Path(path), payload)
    return Path(path)


def lake_status(layout: XStocksLayout, universe: Mapping[str, Any]) -> Dict[str, Any]:
    """What the lake holds, from files only: candle spans per pair and bar, snapshot counts, the last slots taken."""
    latest = latest_instruments(layout)
    out: Dict[str, Any] = {"root": str(layout.root), "universe_selected_at": universe.get("selected_at"),
                           "instruments_recorded_at": latest.get("recorded_at") if latest else None, "pairs": {}}
    for pair in universe_pairs(universe):
        entry: Dict[str, Any] = {}
        for bar in COLLECTED_BARS:
            cov = coverage(layout.candles_dir(pair, bar), "open_time")
            entry[bar] = {"rows": cov.rows, "min": _ms_iso(cov.min_ms) if cov.min_ms is not None else None, "max": _ms_iso(cov.max_ms) if cov.max_ms is not None else None}
        snaps = read_snapshots(layout, pair)
        entry["snapshots"] = len(snaps)
        entry["last_snapshot"] = {k: snaps[-1].get(k) for k in ("slot", "fetched_at", "spread_bps", "empty")} if snaps else None
        out["pairs"][pair] = entry
    taken = load_books_state(layout)["taken"]
    out["slots_taken"] = sorted(taken)[-12:]
    out["slots_taken_total"] = len(taken)
    return out
