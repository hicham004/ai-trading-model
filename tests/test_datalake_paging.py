"""Resumable backward pagination: completion, interruption/resume, top fills, guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.datalake.paging import BackwardWalker, WalkState, load_state, save_state

HOUR = 3_600_000


class TimelineSource:
    """A synthetic exchange: bars every hour in ``[first, last]`` (ms)."""

    def __init__(self, first_ms: int, last_ms: int, *, newest_limit=300, page_limit=100, stuck=False):
        self.first, self.last = first_ms, last_ms
        self.newest_limit, self.page_limit = newest_limit, page_limit
        self.calls = []
        self.stuck = stuck

    def _rows(self, upper_ms, limit):
        rows = []
        ts = upper_ms
        while ts >= self.first and len(rows) < limit:
            rows.append((ts, {"ts": ts}))
            ts -= HOUR
        return rows  # newest first, like OKX

    def fetch_newest(self):
        self.calls.append(("newest", None))
        return self._rows(self.last, self.newest_limit)

    def fetch_older(self, cursor_ms):
        self.calls.append(("older", cursor_ms))
        if self.stuck:
            return [(cursor_ms, {"ts": cursor_ms})]  # only the cursor row: no progress
        return self._rows(cursor_ms - HOUR, self.page_limit)


def run_walk(source, state_path, *, start_ms, sink, max_pages=None):
    def on_page(rows):
        for ts, _ in rows:
            sink.setdefault(ts, 0)
            sink[ts] += 1

    return BackwardWalker(
        source, state_path=state_path, start_ms=start_ms, on_page=on_page, max_pages=max_pages
    ).run()


def test_full_walk_reaches_start_without_gaps(tmp_path: Path):
    first, last = 1_000 * HOUR, 1_000 * HOUR + 999 * HOUR  # 1000 bars
    src = TimelineSource(first, last)
    sink = {}
    report = run_walk(src, tmp_path / "s.json", start_ms=first, sink=sink)
    assert report.reason == "reached_start" and report.complete
    assert set(sink) == {first + i * HOUR for i in range(1000)}
    assert report.oldest_ms == first and report.newest_ms == last
    # 1 newest page (300) + 7 history pages (700)
    assert report.pages == 8


def test_interrupted_run_resumes_and_completes(tmp_path: Path):
    first, last = 1_000 * HOUR, 1_000 * HOUR + 999 * HOUR
    src = TimelineSource(first, last)
    sink = {}
    r1 = run_walk(src, tmp_path / "s.json", start_ms=first, sink=sink, max_pages=3)
    assert r1.reason == "max_pages" and not r1.complete and r1.pages == 3
    state = json.loads((tmp_path / "s.json").read_text())
    assert state["newest_ms"] == last and state["oldest_ms"] == last - 499 * HOUR

    r2 = run_walk(src, tmp_path / "s.json", start_ms=first, sink=sink)
    assert r2.reason == "reached_start" and r2.complete
    assert set(sink) == {first + i * HOUR for i in range(1000)}
    # Resume re-checks the newest page but, with nothing new, writes no row twice.
    assert sum(sink.values()) == 1000


def test_new_data_after_completion_fills_the_top(tmp_path: Path):
    first, last = 1_000 * HOUR, 1_000 * HOUR + 399 * HOUR
    src = TimelineSource(first, last)
    sink = {}
    assert run_walk(src, tmp_path / "s.json", start_ms=first, sink=sink).complete
    # 450 new bars appear (more than one newest page).
    src.last = last + 450 * HOUR
    r = run_walk(src, tmp_path / "s.json", start_ms=first, sink=sink)
    assert r.complete and r.newest_ms == src.last and r.oldest_ms == first
    assert set(sink) == {first + i * HOUR for i in range(850)}
    # newest page (300) + two history pages to bridge the remaining 150 bars
    assert r.pages == 3


def test_interrupted_top_fill_is_resumed_without_holes(tmp_path: Path):
    first, last = 1_000 * HOUR, 1_000 * HOUR + 199 * HOUR
    src = TimelineSource(first, last)
    sink = {}
    assert run_walk(src, tmp_path / "s.json", start_ms=first, sink=sink).complete
    src.last = last + 600 * HOUR  # a big top gap: 300 newest + 3 history pages
    r1 = run_walk(src, tmp_path / "s.json", start_ms=first, sink=sink, max_pages=2)
    assert r1.reason == "max_pages"
    state = json.loads((tmp_path / "s.json").read_text())
    assert state["fill_cursor_ms"] is not None and state["newest_ms"] == last
    r2 = run_walk(src, tmp_path / "s.json", start_ms=first, sink=sink)
    assert r2.complete and r2.newest_ms == src.last
    assert set(sink) == {first + i * HOUR for i in range(800)}
    state = json.loads((tmp_path / "s.json").read_text())
    assert state["fill_cursor_ms"] is None and state["fill_top_ms"] is None


def test_exchange_history_shorter_than_requested_start_is_exhausted(tmp_path: Path):
    first, last = 1_000 * HOUR, 1_000 * HOUR + 149 * HOUR
    src = TimelineSource(first, last)
    sink = {}
    r = run_walk(src, tmp_path / "s.json", start_ms=first - 500 * HOUR, sink=sink)
    assert r.reason == "exhausted" and r.exhausted and r.complete
    assert set(sink) == {first + i * HOUR for i in range(150)}


def test_no_progress_guard_stops_the_walk(tmp_path: Path):
    src = TimelineSource(1_000 * HOUR, 1_000 * HOUR + 500 * HOUR, stuck=True)
    sink = {}
    r = run_walk(src, tmp_path / "s.json", start_ms=1_000 * HOUR, sink=sink, max_pages=50)
    assert r.reason == "no_progress" and not r.complete and r.pages < 50


def test_empty_source_reports_no_data(tmp_path: Path):
    src = TimelineSource(10 * HOUR, 5 * HOUR)  # last < first: nothing to return
    r = run_walk(src, tmp_path / "s.json", start_ms=HOUR, sink={})
    assert r.reason == "no_data" and r.pages == 1 and not r.complete


def test_state_roundtrip_and_earlier_start_reopens(tmp_path: Path):
    path = tmp_path / "s.json"
    st = WalkState(start_ms=100, oldest_ms=100, newest_ms=500)
    assert st.complete
    save_state(path, st)
    loaded = load_state(path, 100)
    assert loaded.complete and loaded.updated_at
    reopened = load_state(path, 50)
    assert not reopened.complete and reopened.oldest_ms == 100
    assert not (path.with_suffix(".json.tmp")).exists()


def test_walker_argument_validation(tmp_path: Path):
    src = TimelineSource(HOUR, 2 * HOUR)
    with pytest.raises(ValueError):
        BackwardWalker(src, state_path=tmp_path / "s.json", start_ms=0, on_page=lambda r: None)
    with pytest.raises(ValueError):
        BackwardWalker(src, state_path=tmp_path / "s.json", start_ms=1, on_page=lambda r: None, max_pages=0)
