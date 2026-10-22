"""The S0 filter's built-in FOMC calendar against the Federal Reserve's published calendar (plan row R7).

``tests/fixtures/fomc_calendar/federal_reserve_fomc.json`` is the Fed's own meeting calendar for 2020-2027, read
from federalreserve.gov on 2026-10-22 (how: its README). Sprint 2c wrote the 2020-2026 dates from memory; all 57
matched, so nothing was corrected, and R7 added the eight 2027 dates. Research only: the calendar blocks NEW entries
around FOMC statements in the research and the paper fleet; it never touches an exit, demo or live trading.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.events import FOMC_DECISION_DAYS, FOMC_RELEASE_UTC_HOUR, fomc_windows
from research.strategies.s0_filters import NoTradeConfig, tradeable_mask

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fomc_calendar" / "federal_reserve_fomc.json"
DECIDING = ("scheduled", "unscheduled")  # meetings end with a policy statement; a cancelled meeting or a notation vote does not
FOMC_2027 = ("2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08")


@pytest.fixture(scope="module")
def fed():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def decision_days(fed) -> list:
    """Every meeting's statement day; a meeting still ahead has no statement yet and releases it on its last day."""
    return sorted(e["release_day"] or e["last_day"] for e in fed["entries"] if e["kind"] in DECIDING)


def release_utc(day: str, published: str) -> pd.Timestamp:
    """``For release at 2:00 p.m. EST`` on ``day`` -> the UTC instant (EST = UTC-5, EDT = UTC-4)."""
    m = re.fullmatch(r"For release at (\d{1,2}):(\d{2}) ([ap])\.m\. (EST|EDT)", published)
    assert m, published
    hour = int(m.group(1)) % 12 + (12 if m.group(3) == "p" else 0)
    local = pd.Timestamp(f"{day} {hour:02d}:{m.group(2)}")
    assert local.tz_localize("America/New_York").tzname() == m.group(4)  # the zone the Fed printed is New York's on that day
    return local.tz_localize("UTC") + pd.Timedelta(hours=5 if m.group(4) == "EST" else 4)


def test_the_recorded_calendar_is_the_feds_for_2020_to_2027(fed):
    assert fed["retrieved"] == "2026-10-22"
    assert {s["url"] for s in fed["sources"].values()} == {"https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                                                          "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"}
    assert sorted(y for s in fed["sources"].values() for y in s["years"]) == list(range(2020, 2028))
    assert Counter(e["kind"] for e in fed["entries"]) == {"scheduled": 63, "unscheduled": 2, "cancelled": 1, "notation vote": 5}
    for e in fed["entries"]:
        assert e["first_day"] <= e["last_day"] and e["year"] == int(e["first_day"][:4])
        if e["kind"] == "scheduled" and e["release_day"]:
            assert e["release_day"] == e["last_day"], e  # why a meeting still ahead counts on its last day
    unscheduled = [(e["first_day"], e["release_day"]) for e in fed["entries"] if e["kind"] == "unscheduled"]
    assert unscheduled == [("2020-03-02", "2020-03-03"), ("2020-03-15", "2020-03-15")]  # the March 2 meeting's statement came out on March 3
    assert any("tentative until confirmed" in note for note in fed["page_notes"])


def test_the_built_in_calendar_is_exactly_the_feds_decision_days(fed):
    days = decision_days(fed)
    assert len(days) == 65 and len(set(days)) == 65
    assert list(FOMC_DECISION_DAYS) == days  # in order, every one, nothing else
    excluded = {e["last_day"] for e in fed["entries"] if e["kind"] not in DECIDING}
    assert excluded == {"2020-03-18", "2020-03-19", "2020-03-23", "2020-03-31", "2020-08-27", "2025-08-22"}
    assert not excluded & set(FOMC_DECISION_DAYS)  # meetings only: not the cancelled meeting, not the notation votes (none set rates)


def test_the_2027_meetings_are_built_in_and_block_entries(fed):
    assert tuple(d for d in FOMC_DECISION_DAYS if d.startswith("2027")) == FOMC_2027
    assert tuple(e["last_day"] for e in fed["entries"] if e["year"] == 2027 and e["kind"] == "scheduled") == FOMC_2027
    assert max(FOMC_DECISION_DAYS) == "2027-12-08"
    assert all(date.fromisoformat(d).weekday() == 2 for d in FOMC_2027)  # Wednesdays
    # The S0 filter blocks new entries from 12:00 UTC on the decision day to 00:00 UTC the next day (bar open times).
    idx = pd.date_range("2027-01-26", periods=18, freq="4h", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx)
    blocked = ~tradeable_mask(df, "4H", 2191.5, NoTradeConfig(scheduled_events=True, cooldown_bars=0))
    assert list(idx[blocked.to_numpy()]) == [pd.Timestamp(t, tz="UTC") for t in
                                             ("2027-01-27 12:00", "2027-01-27 16:00", "2027-01-27 20:00", "2027-01-28 00:00")]
    assert tradeable_mask(df, "4H", 2191.5, NoTradeConfig(scheduled_events=False, cooldown_bars=0)).all()


def test_every_published_release_time_is_inside_its_window(fed):
    """Statements come out at 2:00 p.m. New York time: 19:00 UTC in winter, 18:00 UTC in daylight time. The windows are
    centred on 18:00 UTC, so in winter a window opens 7 h before and closes 5 h after the statement. The fixture holds
    the time printed on every statement so far; the unscheduled cuts of March 2020 (10:00 a.m. EST on March 3, 5:00 p.m.
    EDT on Sunday March 15) fall inside their windows too, 3 h from an edge."""
    assert FOMC_RELEASE_UTC_HOUR == 18
    windows = {w.label: w for w in fomc_windows(before_hours=6.0, after_hours=6.0)}
    published = {r["day"]: r["as_published"] for r in fed["release_times"]}
    released = {e["release_day"] for e in fed["entries"] if e["kind"] in DECIDING and e["release_day"]}
    assert set(published) == released and len(published) == 55  # every statement from 2020-01-29 to 2026-09-16
    assert {d: t for d, t in published.items() if "2:00 p.m." not in t} == {"2020-03-03": "For release at 10:00 a.m. EST",
                                                                             "2020-03-15": "For release at 5:00 p.m. EDT"}
    utc = {day: release_utc(day, text) for day, text in published.items()}
    assert Counter(at.hour for at in utc.values()) == {18: 38, 19: 15, 15: 1, 21: 1}
    assert utc["2026-01-28"] == pd.Timestamp("2026-01-28 19:00", tz="UTC") and utc["2025-09-17"] == pd.Timestamp("2025-09-17 18:00", tz="UTC")
    for day, at in utc.items():
        w = windows[f"FOMC {day}"]
        assert w.start + pd.Timedelta(hours=3) <= at <= w.end - pd.Timedelta(hours=3), (day, at)
    # The meetings still ahead (late 2026 and 2027): 2:00 p.m. New York time falls inside their windows as well.
    ahead = [d for d in FOMC_DECISION_DAYS if d not in published]
    assert ahead == ["2026-10-28", "2026-12-09", *FOMC_2027]
    for day in ahead:
        at = pd.Timestamp(f"{day} 14:00").tz_localize("America/New_York").tz_convert("UTC")
        w = windows[f"FOMC {day}"]
        assert w.start + pd.Timedelta(hours=6) <= at <= w.end - pd.Timedelta(hours=5), (day, at)
