"""JSON-lines storage for ingested news items (``data/news``, git-ignored).

```
<root>/raw/<YYYY-MM-DD>.jsonl          sanitized items (one per line)
<root>/quarantine/<YYYY-MM-DD>.jsonl   items with severe sanitization flags
<root>/_fetch_log/<YYYY-MM-DD>.jsonl   one line per source fetch (status, counts)
<root>/_state/seen.json                dedup seen-set
```
Nothing here is read by the trading runtime.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional

DEFAULT_NEWS_DIR = "data/news"
NEWS_DIR_ENV = "NEWS_DATA_DIR"


class NewsStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "NewsStore":
        env = os.environ if env is None else env
        return cls(Path(env.get(NEWS_DIR_ENV, DEFAULT_NEWS_DIR)))

    @property
    def seen_file(self) -> Path:
        return self.root / "_state" / "seen.json"

    def raw_file(self, day: date) -> Path:
        return self.root / "raw" / f"{day.isoformat()}.jsonl"

    def quarantine_file(self, day: date) -> Path:
        return self.root / "quarantine" / f"{day.isoformat()}.jsonl"

    def fetch_log_file(self, day: date) -> Path:
        return self.root / "_fetch_log" / f"{day.isoformat()}.jsonl"

    @staticmethod
    def _append(path: Path, lines: Iterable[str]) -> int:
        lines = list(lines)
        if not lines:
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return len(lines)

    @staticmethod
    def _day_of(record: Mapping) -> date:
        observed = record.get("observed_at")
        if isinstance(observed, str) and observed:
            return datetime.fromisoformat(observed).astimezone(timezone.utc).date()
        return datetime.now(tz=timezone.utc).date()

    def append_records(self, records: Iterable[Mapping], *, quarantine: bool = False) -> int:
        grouped = {}
        for record in records:
            grouped.setdefault(self._day_of(record), []).append(json.dumps(record, sort_keys=True, ensure_ascii=False))
        written = 0
        for day, lines in grouped.items():
            path = self.quarantine_file(day) if quarantine else self.raw_file(day)
            written += self._append(path, lines)
        return written

    def log_fetch(self, entry: Mapping, *, when: Optional[datetime] = None) -> None:
        when = when or datetime.now(tz=timezone.utc)
        payload = dict(entry)
        payload.setdefault("logged_at", when.isoformat(timespec="seconds"))
        self._append(self.fetch_log_file(when.date()), [json.dumps(payload, sort_keys=True)])
