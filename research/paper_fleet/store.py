"""Journals, state and the single-instance lock of the paper fleet (local files only).

Layout under the fleet directory (default ``logs/paper_fleet``)::

    journals/<account_id>.jsonl   one append-only journal per paper account
    fleet.jsonl                   fleet-level log: starts, data refreshes, gaps, errors
    reports/weekly-YYYY-Www.md    the weekly ranking report (current week rewritten daily)
    _state/fleet_state.json       everything needed to resume (written atomically)
    _state/fleet.lock             one running fleet per directory
    lake/                         the fleet's own public-data lake

Crash safety: a bar's journal records are appended (and flushed to disk)
before the state that counts them is replaced atomically. Every record carries
a per-account sequence number; after a crash between the two writes the bar is
processed again from the saved state and the records whose sequence number is
already in the journal are not written twice.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

STATE_FILE = "fleet_state.json"
LOCK_FILE = "fleet.lock"
REPLACE_RETRIES = 8


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dumps(record: Dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


class FleetPaths:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.journals = self.root / "journals"
        self.reports = self.root / "reports"
        self.state_dir = self.root / "_state"
        self.lake = self.root / "lake"
        self.fleet_log = self.root / "fleet.jsonl"
        self.state_file = self.state_dir / STATE_FILE
        self.lock_file = self.state_dir / LOCK_FILE

    def journal(self, account_id: str) -> Path:
        return self.journals / f"{account_id}.jsonl"

    def ensure(self) -> None:
        for d in (self.journals, self.reports, self.state_dir, self.lake):
            d.mkdir(parents=True, exist_ok=True)


class Journal:
    """Append-only JSON lines with a per-account sequence number."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def last_seq(self) -> int:
        if not self.path.exists():
            return 0
        last = 0
        with open(self.path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, 65536)
            fh.seek(size - block)
            tail = fh.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(tail):
            line = line.strip()
            if not line:
                continue
            try:
                last = int(json.loads(line).get("seq", 0))
                break
            except (ValueError, AttributeError):
                continue
        return last

    def append(self, records: List[Dict[str, Any]]) -> int:
        """Append records whose ``seq`` is not yet in the file; returns how many were written."""
        if not records:
            return 0
        on_disk = self.last_seq()
        fresh = [r for r in records if int(r["seq"]) > on_disk]
        if not fresh:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        torn = self._ends_without_newline()
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            if torn:  # a line cut by a crash: end it, so it stays one unreadable line and never swallows the next record
                fh.write("\n")
            for r in fresh:
                fh.write(_dumps(r) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return len(fresh)

    def _ends_without_newline(self) -> bool:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return False
        with open(self.path, "rb") as fh:
            fh.seek(-1, os.SEEK_END)
            return fh.read(1) != b"\n"

    def read(self) -> Iterator[Dict[str, Any]]:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue


def append_fleet_log(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(record)
    rec.setdefault("logged_at", utc_now_iso())
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(_dumps(rec) + "\n")


def read_state(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(path: Path, state: Dict[str, Any]) -> None:
    """Atomic replace (temp file + ``os.replace``, retried when Windows holds the target briefly)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(state, sort_keys=True, allow_nan=False, default=str))
        fh.flush()
        os.fsync(fh.fileno())
    for attempt in range(1, REPLACE_RETRIES + 1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt >= REPLACE_RETRIES:
                raise
            time.sleep(0.25 * attempt)


class FleetLock:
    """One fleet per directory: an OS file lock released when the process ends."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fh: Any = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fh.seek(0)
                fh.truncate()
                fh.write(f"{os.getpid()}\n")
                fh.flush()
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._fh.close()
            self._fh = None
