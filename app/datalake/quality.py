"""Data-quality assessment for stored candles (continuity, duplicates, alignment, outliers).

Pure functions over a pandas frame / pyarrow table with the lake's candle
columns. Used by ``scripts/data_quality_report.py`` and by the backfill
summary. Nothing here touches the network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa

from app.strategy.timeframes import parse_timeframe


@dataclass(frozen=True)
class Gap:
    after_ms: int  # last stored bar before the hole
    before_ms: int  # first stored bar after the hole
    missing_bars: int


@dataclass
class QualityReport:
    instrument: str
    timeframe: str
    rows: int
    unique_rows: int
    first_ms: Optional[int]
    last_ms: Optional[int]
    expected_rows: int
    missing_rows: int
    gap_count: int
    gaps: List[Gap]
    duplicate_rows: int
    misaligned_rows: int
    phase_ms: Optional[int]
    unconfirmed_rows: int
    incoherent_ohlc_rows: int
    nonpositive_price_rows: int
    zero_volume_rows: int
    extreme_move_rows: int
    max_abs_log_return: float
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.missing_rows == 0
            and self.duplicate_rows == 0
            and self.misaligned_rows == 0
            and self.incoherent_ohlc_rows == 0
            and self.nonpositive_price_rows == 0
            and self.unconfirmed_rows == 0
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        d["first"] = _iso(self.first_ms)
        d["last"] = _iso(self.last_ms)
        return d


def _iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="minutes")


def _frame(data) -> pd.DataFrame:
    if isinstance(data, pa.Table):
        data = data.to_pandas()
    if not isinstance(data, pd.DataFrame):
        raise TypeError("expected a pyarrow Table or pandas DataFrame")
    return data


def assess_candles(
    data,
    *,
    instrument: str,
    timeframe: str,
    extreme_move_threshold: float = 0.25,
    max_gaps_listed: int = 25,
) -> QualityReport:
    """Assess continuity/duplicates/alignment/outliers of one candle series."""
    bar_ms = int(parse_timeframe(timeframe).total_seconds() * 1000)
    df = _frame(data)
    if len(df) == 0:
        return QualityReport(
            instrument, timeframe, 0, 0, None, None, 0, 0, 0, [], 0, 0, None, 0, 0, 0, 0, 0, 0.0,
            notes=["no rows stored"],
        )
    ts = pd.to_datetime(df["open_time"], utc=True)
    ts_ms = ((ts - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(dtype="int64")
    order = np.argsort(ts_ms, kind="mergesort")
    ts_ms = ts_ms[order]
    df = df.iloc[order].reset_index(drop=True)

    unique_ms, first_idx = np.unique(ts_ms, return_index=True)
    duplicate_rows = int(len(ts_ms) - len(unique_ms))
    first_ms, last_ms = int(unique_ms[0]), int(unique_ms[-1])

    # Alignment: every open time must share the same phase modulo the bar.
    phases = unique_ms % bar_ms
    phase_values, phase_counts = np.unique(phases, return_counts=True)
    phase_ms = int(phase_values[int(np.argmax(phase_counts))])
    misaligned_rows = int((phases != phase_ms).sum())

    # Continuity is judged on the aligned grid only (an off-grid bar never
    # "fills" a hole).
    aligned = unique_ms[phases == phase_ms]
    expected_rows = int((int(aligned[-1]) - int(aligned[0])) // bar_ms) + 1
    missing_rows = max(0, expected_rows - len(aligned))

    gaps: List[Gap] = []
    diffs = np.diff(aligned)
    for i in np.nonzero(diffs > bar_ms)[0]:
        missing = int(diffs[i] // bar_ms) - 1
        if missing > 0 and len(gaps) < max_gaps_listed:
            gaps.append(Gap(int(aligned[i]), int(aligned[i + 1]), missing))
    gap_count = int((diffs > bar_ms).sum())

    uniq = df.iloc[first_idx]
    o, h, l, c = (uniq[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    vol = uniq["volume"].to_numpy(dtype=float)
    incoherent = int(((h < np.maximum.reduce([o, c, l])) | (l > np.minimum.reduce([o, c, h]))).sum())
    nonpositive = int((np.minimum.reduce([o, h, l, c]) <= 0).sum())
    zero_volume = int((vol <= 0).sum())
    unconfirmed = int((~uniq["confirmed"].to_numpy(dtype=bool)).sum()) if "confirmed" in uniq else 0

    with np.errstate(divide="ignore", invalid="ignore"):
        log_ret = np.diff(np.log(np.where(c > 0, c, np.nan)))
    log_ret = log_ret[np.isfinite(log_ret)]
    extreme = int((np.abs(log_ret) > extreme_move_threshold).sum()) if log_ret.size else 0
    max_abs = float(np.max(np.abs(log_ret))) if log_ret.size else 0.0

    notes: List[str] = []
    if timeframe.endswith("D") and phase_ms != 0:
        notes.append(
            f"daily bars open at {phase_ms // 3_600_000:02d}:00 UTC (OKX 1D is UTC+8 aligned)"
        )
    if missing_rows:
        notes.append(f"{missing_rows} missing bar(s) across {gap_count} gap(s)")
    if extreme:
        notes.append(f"{extreme} bar(s) with |log return| > {extreme_move_threshold}")

    return QualityReport(
        instrument=instrument,
        timeframe=timeframe,
        rows=int(len(ts_ms)),
        unique_rows=int(len(unique_ms)),
        first_ms=first_ms,
        last_ms=last_ms,
        expected_rows=expected_rows,
        missing_rows=missing_rows,
        gap_count=gap_count,
        gaps=gaps,
        duplicate_rows=duplicate_rows,
        misaligned_rows=misaligned_rows,
        phase_ms=phase_ms,
        unconfirmed_rows=unconfirmed,
        incoherent_ohlc_rows=incoherent,
        nonpositive_price_rows=nonpositive,
        zero_volume_rows=zero_volume,
        extreme_move_rows=extreme,
        max_abs_log_return=max_abs,
        notes=notes,
    )


def render_markdown(reports: Sequence[QualityReport], *, generated_at: Optional[datetime] = None) -> str:
    """Human-readable report (one table row per series + gap details)."""
    generated_at = generated_at or datetime.now(tz=timezone.utc)
    lines = [
        "# Data-quality report — candles",
        "",
        f"Generated {generated_at:%Y-%m-%d %H:%M} UTC. PUBLIC market data; research only.",
        "",
        "| Series | Rows | First (UTC) | Last (UTC) | Missing | Gaps | Dupes | Misaligned | Incoherent | Zero-vol | Extreme | OK |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in reports:
        lines.append(
            f"| {r.instrument} {r.timeframe} | {r.unique_rows} | {_iso(r.first_ms) or '-'} | "
            f"{_iso(r.last_ms) or '-'} | {r.missing_rows} | {r.gap_count} | {r.duplicate_rows} | "
            f"{r.misaligned_rows} | {r.incoherent_ohlc_rows} | {r.zero_volume_rows} | "
            f"{r.extreme_move_rows} | {'yes' if r.ok else 'NO'} |"
        )
    for r in reports:
        if r.gaps or r.notes:
            lines += ["", f"## {r.instrument} {r.timeframe}", ""]
            for note in r.notes:
                lines.append(f"- {note}")
            if r.gaps:
                lines += ["", "| Gap after (UTC) | resumes at (UTC) | missing bars |", "|---|---|---:|"]
                for g in r.gaps:
                    lines.append(f"| {_iso(g.after_ms)} | {_iso(g.before_ms)} | {g.missing_bars} |")
                if r.gap_count > len(r.gaps):
                    lines.append(f"| … | {r.gap_count - len(r.gaps)} more gap(s) not listed | |")
    return "\n".join(lines) + "\n"
