"""JSON-lines storage for the news agent (all paths git-ignored).

Ingested items (``NewsStore``, ``data/news``)::

    <root>/raw/<YYYY-MM-DD>.jsonl          sanitized items (one per line)
    <root>/quarantine/<YYYY-MM-DD>.jsonl   items with severe sanitization flags
    <root>/_fetch_log/<YYYY-MM-DD>.jsonl   one line per source fetch (status, counts)
    <root>/_state/seen.json                dedup seen-set

Shadow logs (``NewsShadowLog``, ``logs/news_shadow``, PHASE6B_DESIGN section 11)::

    <root>/events-<YYYY-MM-DD>.jsonl       observations, classifier outputs, events, signals
    <root>/decisions-<YYYY-MM-DD>.jsonl    one shadow overlay record per candidate entry

Both are append-only: a record, once written, is never rewritten. Nothing here
is read by the trading runtime.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

DEFAULT_NEWS_DIR = "data/news"
NEWS_DIR_ENV = "NEWS_DATA_DIR"
DEFAULT_SHADOW_LOG_DIR = "logs/news_shadow"
SHADOW_LOG_DIR_ENV = "NEWS_SHADOW_LOG_DIR"
SHADOW_LOG_VERSION = "news-shadow-log-v1"

# PHASE6B_DESIGN section 11 record kinds (+ classifier_unavailable for the
# section 13 "LLM unavailable" case, and three operational kinds the shadow
# runner writes: source_fetch for source health and outage minutes,
# cycle_summary once per cycle, runner_event for start/stop, state, spend-cap and
# health changes). ``shadow_entry_overlay`` records go to the decisions file;
# every other kind goes to the events file.
EVENT_RECORD_KINDS = frozenset(
    {
        "source_item_observed",
        "source_item_sanitized",
        "event_candidate_created",
        "event_deduplicated",
        "classifier_output",
        "classifier_rejected",
        "classifier_unavailable",
        "corroboration_update",
        "effective_signal",
        "daily_summary",
        "source_fetch",
        "cycle_summary",
        "runner_event",
    }
)
DECISION_RECORD_KINDS = frozenset({"shadow_entry_overlay"})

_SECRET_KEYS = frozenset(
    {"api_key", "apikey", "x-api-key", "authorization", "secret", "password", "passphrase", "token", "cookie"}
)
# Suffix match covers e.g. telegram_bot_token, newsapi_ai_api_key, client_secret.
# Token *counts* ("input_tokens", "output_tokens") are plural and stay visible.
_SECRET_SUFFIXES = ("_api_key", "_apikey", "_secret", "_password", "_passphrase", "_token")
_SECRET_VALUE = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")
REDACTED = "[REDACTED]"


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


def _is_secret_key(key: str) -> bool:
    lowered = key.strip().lower()
    return lowered in _SECRET_KEYS or lowered.endswith(_SECRET_SUFFIXES)


def redact(value: Any) -> Any:
    """Copy of ``value`` with secret-looking keys and API-key-looking strings replaced."""
    if isinstance(value, Mapping):
        return {str(k): (REDACTED if _is_secret_key(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [redact(v) for v in items]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"not JSON-serializable: {type(value).__name__}")


def _normalize(value: Any) -> Any:
    """Round-trip through JSON so redaction sees plain dicts, lists and strings."""
    return json.loads(json.dumps(value, default=_json_default, ensure_ascii=False))


class NewsShadowLog:
    """Append-only daily JSONL logs for the Phase 6b log-only shadow (design 11)."""

    def __init__(self, root: Path, *, clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc)) -> None:
        self.root = Path(root)
        self._clock = clock

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, **kw) -> "NewsShadowLog":
        env = os.environ if env is None else env
        return cls(Path(env.get(SHADOW_LOG_DIR_ENV, DEFAULT_SHADOW_LOG_DIR)), **kw)

    def events_file(self, day: date) -> Path:
        return self.root / f"events-{day.isoformat()}.jsonl"

    def decisions_file(self, day: date) -> Path:
        return self.root / f"decisions-{day.isoformat()}.jsonl"

    def _write(self, path_for: Callable[[date], Path], kind: str, fields: Mapping[str, Any]) -> Dict[str, Any]:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("the shadow log clock must be timezone-aware")
        now = now.astimezone(timezone.utc)
        body = {k: v for k, v in _normalize(dict(fields)).items() if k not in ("ts", "kind", "log_version")}
        record = {"ts": now.isoformat(), "kind": kind, "log_version": SHADOW_LOG_VERSION, **redact(body)}
        path = path_for(now.date())
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as fh:  # append-only
            fh.write(line + "\n")
            fh.flush()
        return record

    def write_event(self, kind: str, fields: Optional[Mapping[str, Any]] = None, **extra: Any) -> Dict[str, Any]:
        if kind not in EVENT_RECORD_KINDS:
            raise ValueError(f"unknown event record kind {kind!r}")
        return self._write(self.events_file, kind, {**(fields or {}), **extra})

    def write_decision(self, fields: Mapping[str, Any], **extra: Any) -> Dict[str, Any]:
        body = {**fields, **extra}
        kind = str(body.get("kind") or "shadow_entry_overlay")
        if kind not in DECISION_RECORD_KINDS:
            raise ValueError(f"unknown decision record kind {kind!r}")
        return self._write(self.decisions_file, kind, body)

    def read(self, stream: str, day: date) -> List[Dict[str, Any]]:
        """Every record of one day's ``events`` or ``decisions`` file, in write order."""
        if stream not in ("events", "decisions"):
            raise ValueError("stream must be 'events' or 'decisions'")
        path = self.events_file(day) if stream == "events" else self.decisions_file(day)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
