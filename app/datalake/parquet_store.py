"""Parquet storage for the lake: year-partitioned files, de-duplicated on a key.

Writes are *merges*: the existing year file (if any) is read, the new rows are
appended, duplicates on the key column are dropped (last write wins — a
re-fetched confirmed bar is identical anyway), rows are sorted by key, and the
file is replaced atomically (temp file + ``os.replace``). Files are small
(one instrument × timeframe × year), so a merge is cheap even for 1m bars.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.datalake.layout import LakeLayout
from app.okx.client import Candle

TS_TYPE = pa.timestamp("ms", tz="UTC")

CANDLE_SCHEMA = pa.schema(
    [
        ("open_time", TS_TYPE),
        ("instrument", pa.string()),
        ("timeframe", pa.string()),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
        ("confirmed", pa.bool_()),
    ]
)


@dataclass
class MergeResult:
    path: Path
    rows_before: int
    rows_after: int
    duplicates_dropped: int

    @property
    def added(self) -> int:
        return self.rows_after - self.rows_before


@dataclass
class WriteResult:
    rows_in: int = 0
    added: int = 0
    duplicates_dropped: int = 0
    files: List[Path] = field(default_factory=list)


REPLACE_RETRIES = 8
REPLACE_RETRY_DELAY = 0.25  # seconds; grows linearly per attempt


def atomic_replace(tmp: Path, path: Path, *, retries: int = REPLACE_RETRIES) -> None:
    """``os.replace`` with retries.

    On Windows a concurrent reader (a research run, a DuckDB query, a shell
    ``cat``) can hold the target open for a moment, and ``os.replace`` then
    raises ``PermissionError`` (WinError 5/32). The write stays atomic: the
    temp file is complete before the first attempt and the target is never
    partially written.
    """
    for attempt in range(1, max(1, retries) + 1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt >= retries:
                raise
            time.sleep(REPLACE_RETRY_DELAY * attempt)


def to_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return int(value.astimezone(timezone.utc).timestamp() * 1000)


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def merge_into_parquet(path: Path, table: pa.Table, *, key: str, schema: pa.Schema) -> MergeResult:
    """Merge ``table`` into the Parquet file at ``path`` (create if missing)."""
    table = table.select(schema.names).cast(schema)
    if path.exists():
        existing = pq.read_table(path).select(schema.names).cast(schema)
        rows_before = existing.num_rows
        combined = pa.concat_tables([existing, table])
    else:
        rows_before = 0
        combined = table
    df = combined.to_pandas()
    total = len(df)
    df = (
        df.drop_duplicates(subset=[key], keep="last")
        .sort_values(key, kind="mergesort")
        .reset_index(drop=True)
    )
    out = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(out, tmp, compression="zstd")
    atomic_replace(tmp, path)
    return MergeResult(
        path=path,
        rows_before=rows_before,
        rows_after=out.num_rows,
        duplicates_dropped=total - out.num_rows,
    )


def _years(column: pa.ChunkedArray) -> List[int]:
    years = pc.unique(pc.year(column)).to_pylist()
    return sorted(int(y) for y in years if y is not None)


def write_partitioned(
    table: pa.Table,
    *,
    key: str,
    schema: pa.Schema,
    file_for_year,
) -> WriteResult:
    """Split ``table`` by UTC year of ``key`` and merge each part into its file."""
    result = WriteResult(rows_in=table.num_rows)
    if table.num_rows == 0:
        return result
    table = table.select(schema.names).cast(schema)
    year_col = pc.year(table[key])
    for year in _years(table[key]):
        part = table.filter(pc.equal(year_col, year))
        merged = merge_into_parquet(file_for_year(year), part, key=key, schema=schema)
        result.added += merged.added
        result.duplicates_dropped += merged.duplicates_dropped
        result.files.append(merged.path)
    return result


# -- candles ------------------------------------------------------------------

def candles_to_table(candles: Iterable[Candle]) -> pa.Table:
    rows = list(candles)
    return pa.table(
        {
            "open_time": pa.array([c.timestamp for c in rows], type=TS_TYPE),
            "instrument": pa.array([c.instrument for c in rows], type=pa.string()),
            "timeframe": pa.array([c.timeframe for c in rows], type=pa.string()),
            "open": pa.array([c.open for c in rows], type=pa.float64()),
            "high": pa.array([c.high for c in rows], type=pa.float64()),
            "low": pa.array([c.low for c in rows], type=pa.float64()),
            "close": pa.array([c.close for c in rows], type=pa.float64()),
            "volume": pa.array([c.volume for c in rows], type=pa.float64()),
            "confirmed": pa.array([c.confirmed for c in rows], type=pa.bool_()),
        },
        schema=CANDLE_SCHEMA,
    )


def write_candles(layout: LakeLayout, candles: Sequence[Candle]) -> WriteResult:
    """Merge candles into ``candles/<instrument>/<timeframe>/<year>.parquet`` files."""
    total = WriteResult(rows_in=len(candles))
    if not candles:
        return total
    groups = {}
    for c in candles:
        groups.setdefault((c.instrument, c.timeframe), []).append(c)
    for (instrument, timeframe), rows in groups.items():
        res = write_partitioned(
            candles_to_table(rows),
            key="open_time",
            schema=CANDLE_SCHEMA,
            file_for_year=lambda y, i=instrument, t=timeframe: layout.candles_file(i, t, y),
        )
        total.added += res.added
        total.duplicates_dropped += res.duplicates_dropped
        total.files.extend(res.files)
    return total


def _year_files(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("*.parquet") if p.stem.isdigit())


def read_candles(
    layout: LakeLayout,
    instrument: str,
    timeframe: str,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> pa.Table:
    """Read stored candles (oldest first), optionally restricted to ``[start, end)``."""
    files = _year_files(layout.candles_dir(instrument, timeframe))
    if start is not None:
        files = [f for f in files if int(f.stem) >= start.astimezone(timezone.utc).year]
    if end is not None:
        files = [f for f in files if int(f.stem) <= end.astimezone(timezone.utc).year]
    if not files:
        return CANDLE_SCHEMA.empty_table()
    table = pa.concat_tables([pq.read_table(f).cast(CANDLE_SCHEMA) for f in files])
    if start is not None:
        table = table.filter(pc.greater_equal(table["open_time"], pa.scalar(start, type=TS_TYPE)))
    if end is not None:
        table = table.filter(pc.less(table["open_time"], pa.scalar(end, type=TS_TYPE)))
    return table


@dataclass(frozen=True)
class Coverage:
    rows: int
    min_ms: Optional[int]
    max_ms: Optional[int]
    files: int


def coverage(directory: Path, key: str) -> Coverage:
    """Cheap coverage summary (reads only the key column of each year file)."""
    files = _year_files(directory)
    rows, lo, hi = 0, None, None
    for f in files:
        col = pq.read_table(f, columns=[key])[key]
        if col.length() == 0:
            continue
        rows += col.length()
        mn = to_ms(pc.min(col).as_py())
        mx = to_ms(pc.max(col).as_py())
        lo = mn if lo is None else min(lo, mn)
        hi = mx if hi is None else max(hi, mx)
    return Coverage(rows=rows, min_ms=lo, max_ms=hi, files=len(files))


def candle_coverage(layout: LakeLayout, instrument: str, timeframe: str) -> Coverage:
    return coverage(layout.candles_dir(instrument, timeframe), "open_time")


def table_to_frame(table: pa.Table) -> pd.DataFrame:
    """pandas view with ``open_time`` (or ``ts``) as tz-aware UTC datetimes."""
    return table.to_pandas()
