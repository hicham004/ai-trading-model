"""Scheduled-event calendar for the S0 no-trade filter (research only).

Sprint 2c upgrades the S0 filter with *scheduled* event windows: bars inside a
window around a known macro event block NEW entries (never exits). The only
built-in calendar is the FOMC rate-decision schedule, which is public and
fixed a year ahead; the statement is released at 14:00 US Eastern time
(19:00 UTC in winter, 18:00 UTC in daylight time).

The dates were written from memory in Sprint 2c. Plan row R7 checked them on
2026-10-22 against the Federal Reserve's published calendar
(https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm and, for
2020, fomchistorical2020.htm): all 57 of 2020-2026 were right, and the 2027
dates were added from the same calendar. The Fed calls each date tentative
until the meeting before it confirms it. ``tests/test_fomc_calendar.py``
compares this calendar with the Fed's, recorded in
``tests/fixtures/fomc_calendar/`` (its README says how to add the next year).
Reports and the paper fleet's fingerprints name the filter (``FOMC±6/6h``),
not its dates; the paper fleet reads the dates when it starts, so a running
fleet picks up new ones at its next restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import pandas as pd

# FOMC decision days: the day each meeting's policy statement came out — every
# scheduled meeting plus the two unscheduled meetings of March 2020, both rate
# cuts and tradeable shocks (the March 2 meeting's statement came out on March 3).
# Not meetings, so not counted: the cancelled March 17-18, 2020 meeting and the
# notation votes, none of which set rates; the closest call is the FOMC statement
# of March 23, 2020 (8:00 a.m. EDT, unlimited bond buying, rates unchanged).
FOMC_DECISION_DAYS: Tuple[str, ...] = (
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29", "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
)
FOMC_RELEASE_UTC_HOUR = 18  # 14:00 ET in daylight time; in winter the release is at 19:00 UTC, one hour later, which the window absorbs


@dataclass(frozen=True)
class EventWindow:
    """Half-open window ``[start, end]`` (UTC) during which new entries are blocked."""

    start: pd.Timestamp
    end: pd.Timestamp
    label: str = ""

    def as_tuple(self) -> Tuple[pd.Timestamp, pd.Timestamp]:
        return self.start, self.end


def _utc(ts) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    return out.tz_localize("UTC") if out.tzinfo is None else out.tz_convert("UTC")


def fomc_windows(*, before_hours: float = 6.0, after_hours: float = 6.0, days: Sequence[str] = FOMC_DECISION_DAYS) -> List[EventWindow]:
    """Blocks entries ``before_hours`` before and ``after_hours`` after each FOMC release."""
    if before_hours < 0 or after_hours < 0:
        raise ValueError("hours must be non-negative")
    out: List[EventWindow] = []
    for day in days:
        release = _utc(datetime.fromisoformat(day).replace(hour=FOMC_RELEASE_UTC_HOUR, tzinfo=timezone.utc))
        out.append(EventWindow(release - timedelta(hours=before_hours), release + timedelta(hours=after_hours), f"FOMC {day}"))
    return out


def load_event_windows(path: Path) -> List[EventWindow]:
    """Load ``[{"start": iso, "end": iso, "label": str}, ...]`` from a JSON file."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("event calendar must be a JSON list")
    out: List[EventWindow] = []
    for row in rows:
        if not isinstance(row, dict) or "start" not in row or "end" not in row:
            raise ValueError("every event needs start and end")
        start, end = _utc(row["start"]), _utc(row["end"])
        if end < start:
            raise ValueError(f"event window ends before it starts: {row}")
        out.append(EventWindow(start, end, str(row.get("label", ""))))
    return out


def windows_as_tuples(windows: Iterable[EventWindow]) -> Tuple[Tuple[pd.Timestamp, pd.Timestamp], ...]:
    return tuple(w.as_tuple() for w in windows)


def in_event_window(index: pd.DatetimeIndex, windows: Iterable[EventWindow]) -> pd.Series:
    """True for bars whose open time falls inside any window."""
    mask = pd.Series(False, index=index)
    for w in windows:
        mask |= (index >= w.start) & (index <= w.end)
    return mask
