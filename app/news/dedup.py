"""Deduplication keys and the persisted seen-set (PHASE6B_DESIGN section 7.3, skeleton).

Two keys per item:

- ``content_key``: identifies one *article* (canonical URL, else publisher+title).
- ``story_key``:   crude same-story bucket (normalized title + UTC day). The full
  design (entities, category, assets, source family) belongs to the classifier
  stage, which is not built here; this key only lets the log group copies.

The seen-set is a JSON file ``{key: first_seen_iso}`` pruned by age and size.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

_NON_WORD = re.compile(r"[^0-9a-zÀ-ɏЀ-ӿ ]+")
_WS = re.compile(r"\s+")


def normalize_title_key(title: str) -> str:
    text = unicodedata.normalize("NFKC", title or "").lower()
    text = _NON_WORD.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _sha(parts: str) -> str:
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def content_key(canonical_url: str, publisher: str, title: str) -> str:
    if canonical_url:
        return _sha("url|" + canonical_url)
    return _sha("pub|" + (publisher or "").strip().lower() + "|" + normalize_title_key(title))


def story_key(title: str, published_at: Optional[datetime], observed_at: datetime) -> str:
    when = published_at or observed_at
    day = when.astimezone(timezone.utc).date().isoformat()
    return _sha("story|" + normalize_title_key(title) + "|" + day)


class SeenStore:
    """Persisted set of content keys with first-seen timestamps."""

    def __init__(self, path: Path, *, max_age_days: int = 14, max_entries: int = 100_000) -> None:
        self._path = path
        self._max_age = timedelta(days=max_age_days)
        self._max_entries = max_entries
        self._seen: Dict[str, str] = {}
        self._loaded = False
        self.dirty = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8") or "{}")
            if isinstance(data, dict):
                self._seen = {str(k): str(v) for k, v in data.items()}

    def __len__(self) -> int:
        self.load()
        return len(self._seen)

    def is_new(self, key: str) -> bool:
        self.load()
        return key not in self._seen

    def add(self, key: str, when: Optional[datetime] = None) -> None:
        self.load()
        when = when or datetime.now(tz=timezone.utc)
        self._seen[key] = when.astimezone(timezone.utc).isoformat(timespec="seconds")
        self.dirty = True

    def prune(self, now: Optional[datetime] = None) -> int:
        self.load()
        now = now or datetime.now(tz=timezone.utc)
        cutoff = (now - self._max_age).isoformat(timespec="seconds")
        before = len(self._seen)
        self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}
        if len(self._seen) > self._max_entries:
            keep = sorted(self._seen.items(), key=lambda kv: kv[1])[-self._max_entries :]
            self._seen = dict(keep)
        removed = before - len(self._seen)
        if removed:
            self.dirty = True
        return removed

    def save(self) -> None:
        self.load()
        if not self.dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(self._seen, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)
        self.dirty = False
