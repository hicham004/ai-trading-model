"""OKX PUBLIC derivatives statistics as research *features* (we do not trade swaps).

Series (all for ``BTC-USDT-SWAP`` / ``ETH-USDT-SWAP``, public, unauthenticated):

- ``funding_rate``      GET /api/v5/public/funding-rate-history (8-hourly settlements)
- ``open_interest``     GET /api/v5/rubik/stat/contracts/open-interest-history
- ``long_short_ratio``  GET /api/v5/rubik/stat/contracts/long-short-account-ratio-contract
- ``taker_volume``      GET /api/v5/rubik/stat/taker-volume-contract

Row formats were confirmed against the live public API on 2026-10-20. History
depth on the ``rubik`` endpoints is limited by OKX (months, not years); the
backfill simply records how far back the exchange serves data.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

import pyarrow as pa

from app.datalake.layout import SERIES_KINDS, LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest, PublicRestError
from app.datalake.paging import BackwardWalker, Row, WalkReport
from app.datalake.parquet_store import TS_TYPE, WriteResult, coverage, from_ms, to_ms, write_partitioned
from app.logging_config import get_logger

logger = get_logger(__name__)

SWAP_INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
PERIODS = ("5m", "1H", "1D")
FUNDING_PERIOD = "8H"  # directory label; OKX settles funding every 8 hours
PAGE_LIMIT = 100
DEFAULT_START = datetime(2020, 1, 1, tzinfo=timezone.utc)

FUNDING_PATH = "/api/v5/public/funding-rate-history"
FUNDING_CURRENT_PATH = "/api/v5/public/funding-rate"
OPEN_INTEREST_PATH = "/api/v5/rubik/stat/contracts/open-interest-history"
OPEN_INTEREST_CURRENT_PATH = "/api/v5/public/open-interest"
LONG_SHORT_PATH = "/api/v5/rubik/stat/contracts/long-short-account-ratio-contract"
TAKER_VOLUME_PATH = "/api/v5/rubik/stat/taker-volume-contract"

_F64 = pa.float64()
_STR = pa.string()
SCHEMAS: Dict[str, pa.Schema] = {
    "funding_rate": pa.schema(
        [
            ("ts", TS_TYPE),
            ("instrument", _STR),
            ("period", _STR),
            ("funding_rate", _F64),
            ("realized_rate", _F64),
            ("method", _STR),
            ("formula_type", _STR),
        ]
    ),
    "open_interest": pa.schema(
        [("ts", TS_TYPE), ("instrument", _STR), ("period", _STR), ("oi", _F64), ("oi_ccy", _F64), ("oi_usd", _F64)]
    ),
    "long_short_ratio": pa.schema([("ts", TS_TYPE), ("instrument", _STR), ("period", _STR), ("ratio", _F64)]),
    "taker_volume": pa.schema(
        [("ts", TS_TYPE), ("instrument", _STR), ("period", _STR), ("sell_vol", _F64), ("buy_vol", _F64)]
    ),
}
assert tuple(SCHEMAS) == SERIES_KINDS


# -- parsing ------------------------------------------------------------------

def _num(value, label: str, *, allow_blank: bool = False) -> float:
    if value in (None, "") and allow_blank:
        return math.nan
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PublicRestError(f"malformed {label}: {value!r}") from exc
    if not math.isfinite(out):
        raise PublicRestError(f"non-finite {label}: {value!r}")
    return out


def _ts(value, label: str = "ts") -> int:
    try:
        ms = int(value)
    except (TypeError, ValueError) as exc:
        raise PublicRestError(f"malformed {label}: {value!r}") from exc
    if ms <= 0:
        raise PublicRestError(f"{label} must be after the Unix epoch")
    return ms


def _check_instrument(instrument: str) -> None:
    if instrument not in SWAP_INSTRUMENTS:
        raise ValueError(f"instrument {instrument!r} not allowed; allowed: {SWAP_INSTRUMENTS}")


def _check_period(period: str) -> None:
    if period not in PERIODS:
        raise ValueError(f"period {period!r} not allowed; allowed: {PERIODS}")


def parse_funding_rows(data: Sequence, instrument: str) -> List[dict]:
    out = []
    for item in data:
        if not isinstance(item, dict):
            raise PublicRestError(f"malformed funding row: {item!r}")
        if item.get("instId") not in (None, instrument):
            continue  # defensive: never mix instruments in one series
        out.append(
            {
                "ts": _ts(item.get("fundingTime"), "fundingTime"),
                "instrument": instrument,
                "period": FUNDING_PERIOD,
                "funding_rate": _num(item.get("fundingRate"), "fundingRate"),
                "realized_rate": _num(item.get("realizedRate"), "realizedRate", allow_blank=True),
                "method": str(item.get("method") or ""),
                "formula_type": str(item.get("formulaType") or ""),
            }
        )
    return out


def _parse_array_rows(data: Sequence, instrument: str, period: str, names: Sequence[str], label: str) -> List[dict]:
    out = []
    width = len(names) + 1
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < width:
            raise PublicRestError(f"malformed {label} row: {row!r}")
        record = {"ts": _ts(row[0]), "instrument": instrument, "period": period}
        for i, name in enumerate(names, start=1):
            record[name] = _num(row[i], name)
        out.append(record)
    return out


def parse_open_interest_rows(data: Sequence, instrument: str, period: str) -> List[dict]:
    return _parse_array_rows(data, instrument, period, ("oi", "oi_ccy", "oi_usd"), "open-interest")


def parse_long_short_rows(data: Sequence, instrument: str, period: str) -> List[dict]:
    return _parse_array_rows(data, instrument, period, ("ratio",), "long-short-ratio")


def parse_taker_volume_rows(data: Sequence, instrument: str, period: str) -> List[dict]:
    return _parse_array_rows(data, instrument, period, ("sell_vol", "buy_vol"), "taker-volume")


def records_to_table(kind: str, records: Sequence[dict]) -> pa.Table:
    schema = SCHEMAS[kind]
    columns = {}
    for field_ in schema:
        values = [r.get(field_.name) for r in records]
        columns[field_.name] = pa.array(values, type=field_.type)
    return pa.table(columns, schema=schema)


# -- fetching -----------------------------------------------------------------

def fetch_funding_rate_history(
    rest: OKXPublicRest, instrument: str, *, after_ms: Optional[int] = None, limit: int = PAGE_LIMIT
) -> List[dict]:
    _check_instrument(instrument)
    data = rest.get(FUNDING_PATH, {"instId": instrument, "limit": limit, "after": after_ms})
    return parse_funding_rows(data, instrument)


def fetch_funding_rate_current(rest: OKXPublicRest, instrument: str) -> dict:
    _check_instrument(instrument)
    data = rest.get(FUNDING_CURRENT_PATH, {"instId": instrument})
    rows = parse_funding_rows(data, instrument)
    if not rows:
        raise PublicRestError("empty funding-rate response")
    return rows[0]


def fetch_open_interest_history(
    rest: OKXPublicRest, instrument: str, period: str = "1H", *, end_ms: Optional[int] = None, limit: int = PAGE_LIMIT
) -> List[dict]:
    _check_instrument(instrument)
    _check_period(period)
    data = rest.get(OPEN_INTEREST_PATH, {"instId": instrument, "period": period, "end": end_ms, "limit": limit})
    return parse_open_interest_rows(data, instrument, period)


def fetch_open_interest_current(rest: OKXPublicRest, instrument: str) -> dict:
    _check_instrument(instrument)
    data = rest.get(OPEN_INTEREST_CURRENT_PATH, {"instType": "SWAP", "instId": instrument})
    for item in data:
        if isinstance(item, dict) and item.get("instId") == instrument:
            return {
                "ts": _ts(item.get("ts")),
                "instrument": instrument,
                "period": "now",
                "oi": _num(item.get("oi"), "oi"),
                "oi_ccy": _num(item.get("oiCcy"), "oiCcy"),
                "oi_usd": _num(item.get("oiUsd"), "oiUsd"),
            }
    raise PublicRestError("open-interest response did not include the instrument")


def fetch_long_short_ratio(
    rest: OKXPublicRest, instrument: str, period: str = "1H", *, end_ms: Optional[int] = None, limit: int = PAGE_LIMIT
) -> List[dict]:
    _check_instrument(instrument)
    _check_period(period)
    data = rest.get(LONG_SHORT_PATH, {"instId": instrument, "period": period, "end": end_ms, "limit": limit})
    return parse_long_short_rows(data, instrument, period)


def fetch_taker_volume(
    rest: OKXPublicRest, instrument: str, period: str = "1H", *, end_ms: Optional[int] = None, limit: int = PAGE_LIMIT
) -> List[dict]:
    _check_instrument(instrument)
    _check_period(period)
    data = rest.get(TAKER_VOLUME_PATH, {"instId": instrument, "period": period, "end": end_ms, "limit": limit})
    return parse_taker_volume_rows(data, instrument, period)


# -- storage + resumable backfill ---------------------------------------------

def write_series(layout: LakeLayout, kind: str, instrument: str, period: str, records: Sequence[dict]) -> WriteResult:
    if kind not in SCHEMAS:
        raise ValueError(f"unknown series kind {kind!r}")
    return write_partitioned(
        records_to_table(kind, records),
        key="ts",
        schema=SCHEMAS[kind],
        file_for_year=lambda y: layout.series_file(kind, instrument, period, y),
    )


class _SeriesSource:
    def __init__(self, rest: OKXPublicRest, kind: str, instrument: str, period: str) -> None:
        self._rest, self._kind, self._instrument, self._period = rest, kind, instrument, period

    def _page(self, cursor_ms: Optional[int]) -> Sequence[Row]:
        if self._kind == "funding_rate":
            rows = fetch_funding_rate_history(self._rest, self._instrument, after_ms=cursor_ms)
        else:
            # ``end`` is inclusive on the rubik endpoints: step one millisecond below the cursor.
            end = None if cursor_ms is None else cursor_ms - 1
            fetcher = {
                "open_interest": fetch_open_interest_history,
                "long_short_ratio": fetch_long_short_ratio,
                "taker_volume": fetch_taker_volume,
            }[self._kind]
            rows = fetcher(self._rest, self._instrument, self._period, end_ms=end)
        return [(r["ts"], r) for r in rows]

    def fetch_newest(self) -> Sequence[Row]:
        return self._page(None)

    def fetch_older(self, cursor_ms: int) -> Sequence[Row]:
        return self._page(cursor_ms)


@dataclass
class SeriesBackfillReport:
    kind: str
    instrument: str
    period: str
    walk: WalkReport
    added: int
    duplicates_dropped: int
    stored_rows: int
    stored_min: Optional[datetime]
    stored_max: Optional[datetime]

    def summary(self) -> str:
        span = (
            f"{self.stored_min:%Y-%m-%d %H:%M} -> {self.stored_max:%Y-%m-%d %H:%M} UTC"
            if self.stored_min and self.stored_max
            else "(empty)"
        )
        return (
            f"{self.kind} {self.instrument} {self.period}: pages={self.walk.pages} fetched={self.walk.rows} "
            f"added={self.added} dupes={self.duplicates_dropped} stored={self.stored_rows} span={span} "
            f"complete={self.walk.complete} exhausted={self.walk.exhausted} reason={self.walk.reason}"
        )


def backfill_series(
    rest: OKXPublicRest,
    layout: LakeLayout,
    kind: str,
    instrument: str,
    *,
    period: str = "1H",
    start: datetime = DEFAULT_START,
    max_pages: Optional[int] = None,
    sleep_seconds: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
) -> SeriesBackfillReport:
    """Resumable backward backfill of one derivatives series."""
    if kind not in SCHEMAS:
        raise ValueError(f"unknown series kind {kind!r}")
    _check_instrument(instrument)
    if kind == "funding_rate":
        period = FUNDING_PERIOD
    else:
        _check_period(period)
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")

    added = dupes = 0

    def on_page(rows: Sequence[Row]) -> None:
        nonlocal added, dupes
        res = write_series(layout, kind, instrument, period, [payload for _, payload in rows])
        added += res.added
        dupes += res.duplicates_dropped

    walk = BackwardWalker(
        _SeriesSource(rest, kind, instrument, period),
        state_path=layout.state_file("series", kind, instrument, period),
        start_ms=to_ms(start),
        on_page=on_page,
        max_pages=max_pages,
        sleep_seconds=sleep_seconds,
        sleep=sleep,
    ).run()
    cov = coverage(layout.series_dir(kind, instrument, period), "ts")
    report = SeriesBackfillReport(
        kind=kind,
        instrument=instrument,
        period=period,
        walk=walk,
        added=added,
        duplicates_dropped=dupes,
        stored_rows=cov.rows,
        stored_min=from_ms(cov.min_ms) if cov.min_ms is not None else None,
        stored_max=from_ms(cov.max_ms) if cov.max_ms is not None else None,
    )
    logger.info("Series backfill session finished", extra={"summary": report.summary()})
    return report
