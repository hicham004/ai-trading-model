"""Resumable backward pagination shared by the candle and derivatives backfills.

OKX history endpoints page *backwards in time*: a request with a cursor
returns up to ``limit`` records older than it, newest first. A backfill
therefore walks from the newest record down to a target start date. This
module makes that walk resumable and idempotent:

- A small JSON state file records the contiguous covered range
  ``[oldest_ms, newest_ms]`` plus an in-progress "top fill" (new data that
  appeared since the last run and is being joined to the covered range).
- Every page is handed to ``on_page`` *before* the state is advanced, and the
  Parquet writer de-duplicates on the timestamp key, so an interruption at any
  point leaves consistent files and a state that simply resumes.
- ``max_pages`` bounds a run (tests, cron slots); ``sleep_seconds`` keeps the
  request rate under OKX's public limits.

Row = ``(timestamp_ms, payload)``. Sources implement ``fetch_newest()`` (the
latest page, no cursor) and ``fetch_older(cursor_ms)`` (records strictly older
than the cursor, or at least making progress below it).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence, Tuple

Row = Tuple[int, Any]


class PageSource(Protocol):
    def fetch_newest(self) -> Sequence[Row]: ...

    def fetch_older(self, cursor_ms: int) -> Sequence[Row]: ...


@dataclass
class WalkState:
    """Persistent cursor state. ``complete`` is derived, never stored blindly."""

    start_ms: int
    oldest_ms: Optional[int] = None
    newest_ms: Optional[int] = None
    exhausted: bool = False  # the source returned no data older than oldest_ms
    fill_top_ms: Optional[int] = None  # unfinished top fill: highest ts fetched
    fill_cursor_ms: Optional[int] = None  # unfinished top fill: lowest ts fetched
    pages: int = 0
    updated_at: str = ""

    @property
    def complete(self) -> bool:
        return self.exhausted or (self.oldest_ms is not None and self.oldest_ms <= self.start_ms)


_STATE_FIELDS = tuple(WalkState.__dataclass_fields__)


def load_state(path: Path, start_ms: int) -> WalkState:
    """Load a state file; a new (earlier) ``start_ms`` re-opens a finished walk."""
    if not path.exists():
        return WalkState(start_ms=start_ms)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"corrupt backfill state file: {path}")
    kwargs = {k: data.get(k) for k in _STATE_FIELDS if k in data}
    kwargs["start_ms"] = start_ms
    kwargs.setdefault("pages", 0)
    kwargs.setdefault("updated_at", "")
    kwargs.setdefault("exhausted", False)
    return WalkState(**kwargs)


def save_state(path: Path, state: WalkState) -> None:
    """Atomically persist the state (temp file + ``os.replace``)."""
    state.updated_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class WalkReport:
    pages: int = 0
    rows: int = 0
    reason: str = ""
    oldest_ms: Optional[int] = None
    newest_ms: Optional[int] = None
    complete: bool = False
    exhausted: bool = False


class _Budget(Exception):
    """Internal: page budget used up."""


class BackwardWalker:
    """Run one resumable backfill session against a ``PageSource``."""

    def __init__(
        self,
        source: PageSource,
        *,
        state_path: Path,
        start_ms: int,
        on_page: Callable[[Sequence[Row]], None],
        max_pages: Optional[int] = None,
        sleep_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if start_ms <= 0:
            raise ValueError("start_ms must be after the Unix epoch")
        if max_pages is not None and max_pages <= 0:
            raise ValueError("max_pages must be positive when given")
        self._source = source
        self._state_path = state_path
        self._start_ms = int(start_ms)
        self._on_page = on_page
        self._max_pages = max_pages
        self._sleep_seconds = max(0.0, float(sleep_seconds))
        self._sleep = sleep
        self._report = WalkReport()
        self._state: Optional[WalkState] = None

    # -- helpers -------------------------------------------------------------
    def _fetch(self, cursor_ms: Optional[int]) -> list:
        if self._max_pages is not None and self._report.pages >= self._max_pages:
            raise _Budget()
        rows = self._source.fetch_newest() if cursor_ms is None else self._source.fetch_older(cursor_ms)
        self._report.pages += 1
        assert self._state is not None
        self._state.pages += 1
        if self._sleep_seconds:
            self._sleep(self._sleep_seconds)
        rows = sorted(rows, key=lambda r: int(r[0]))
        for ts, _ in rows:
            if int(ts) <= 0:
                raise ValueError("source returned a non-positive timestamp")
        return rows

    def _write(self, rows: Sequence[Row]) -> None:
        if rows:
            self._on_page(rows)
            self._report.rows += len(rows)

    def _save(self) -> None:
        assert self._state is not None
        save_state(self._state_path, self._state)

    # -- phases --------------------------------------------------------------
    def _walk_top_fill(self) -> Optional[str]:
        """Join an unfinished top fill to the covered range. Returns a stop reason or None."""
        st = self._state
        assert st is not None and st.fill_cursor_ms is not None and st.newest_ms is not None
        cursor = st.fill_cursor_ms
        while True:
            rows = self._fetch(cursor)
            if not rows:
                # Nothing between the covered range and the new top: close it.
                st.newest_ms = st.fill_top_ms
                st.fill_top_ms = None
                st.fill_cursor_ms = None
                self._save()
                return None
            page_min = int(rows[0][0])
            if page_min >= cursor:
                return "no_progress"
            self._write(rows)
            st.fill_cursor_ms = page_min
            if page_min <= st.newest_ms:
                st.newest_ms = st.fill_top_ms
                st.fill_top_ms = None
                st.fill_cursor_ms = None
                self._save()
                return None
            self._save()
            cursor = page_min

    def _extend_bottom(self) -> str:
        st = self._state
        assert st is not None and st.oldest_ms is not None
        cursor = st.oldest_ms
        while True:
            if st.complete:
                return "reached_start"
            rows = self._fetch(cursor)
            if not rows:
                st.exhausted = True
                self._save()
                return "exhausted"
            page_min = int(rows[0][0])
            if page_min >= cursor:
                return "no_progress"
            self._write(rows)
            st.oldest_ms = page_min
            self._save()
            cursor = page_min

    def run(self) -> WalkReport:
        st = load_state(self._state_path, self._start_ms)
        self._state = st
        reason = "complete"
        try:
            # Phase 1: resume an interrupted top fill.
            if st.fill_cursor_ms is not None and st.newest_ms is not None:
                stop = self._walk_top_fill()
                if stop:
                    reason = stop
                    raise _Budget()
            # Phase 2: fetch the newest page; start a top fill if there is new data.
            rows = self._fetch(None)
            if not rows:
                if st.newest_ms is None:
                    reason = "no_data"
                    raise _Budget()
            else:
                page_min, page_max = int(rows[0][0]), int(rows[-1][0])
                if st.newest_ms is None:
                    self._write(rows)
                    st.oldest_ms, st.newest_ms = page_min, page_max
                    self._save()
                elif page_max > st.newest_ms:
                    self._write(rows)
                    if page_min <= st.newest_ms:
                        st.newest_ms = page_max
                        self._save()
                    else:
                        st.fill_top_ms, st.fill_cursor_ms = page_max, page_min
                        self._save()
                        stop = self._walk_top_fill()
                        if stop:
                            reason = stop
                            raise _Budget()
            # Phase 3: extend the covered range down to the start.
            if not st.complete:
                reason = self._extend_bottom()
        except _Budget:
            if reason == "complete":
                reason = "max_pages"
        self._report.reason = reason
        self._report.oldest_ms = st.oldest_ms
        self._report.newest_ms = st.newest_ms
        self._report.complete = st.complete
        self._report.exhausted = st.exhausted
        return self._report
