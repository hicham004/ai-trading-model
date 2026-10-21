"""Read-only Phase 6a journal snapshots for the news shadow (PHASE6B_DESIGN sections 7.7, 11, 14).

The Phase 6a shadow supervisor appends ``journal-YYYY-MM-DD.jsonl`` under
``logs/shadow``. The news shadow only READS those files — it never writes, locks
or truncates them and never opens the demo database — and turns each journaled
candidate NEW long entry into a ``Phase6aCandidate`` carrying the decision the
existing runtime made about it (the baseline):

- ``signal`` lines (the supervisor's shadow evaluation, ``action == "long"``):
  the candidate, its confidence and whether it cleared the confidence floor;
- ``ledger_event`` lines with ``event_type == "risk_decision"`` and intent
  ``entry``: the runtime's authoritative allowed/blocked decision and its reason
  (an entry decision with no matching signal line is still a candidate);
  ``equity_unavailable`` lines: an entry the driver refused before the risk check;
- ``ledger_intent`` lines with intent ``entry``: the size and price submitted;
- ``candle`` lines: the timeframe and, for the daily report, the later price path.

FLAT and HOLD signals, stop evaluations and exits never become candidates: the
news layer has no input that represents them. A candidate whose runtime decision
has not appeared after a settle window is reported as "not observed" — never as
allowed — so it can never count as a prevented trade.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app.news.corroborate import PublicCandle

DEFAULT_JOURNAL_DIR = "logs/shadow"
JOURNAL_DIR_ENV = "PHASE6A_JOURNAL_DIR"
DEFAULT_TIMEFRAME = "1H"
DEFAULT_SETTLE = timedelta(minutes=15)
# A runtime decision may be stamped a moment before the candle's nominal close.
DECISION_EARLY_SLACK = timedelta(seconds=60)

_TIMEFRAME_RE = re.compile(r"^(\d{1,3})([mHD])(?:utc)?$")
_UNIT_MINUTES = {"m": 1, "H": 60, "D": 1440}
_MESSAGE_RE = re.compile(r"^\s*(entry|exit)\s+(allowed|blocked):\s*(.*?)\s*$")
_REASON_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


def journal_dir_from_env(env: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get(JOURNAL_DIR_ENV) or DEFAULT_JOURNAL_DIR)


def timeframe_interval(timeframe: Optional[str]) -> timedelta:
    """``"1H"`` -> 1 hour, ``"5m"`` -> 5 minutes; anything unknown is 1 hour (the Phase 6a timeframe)."""
    match = _TIMEFRAME_RE.match(str(timeframe or "").strip())
    if not match:
        return timedelta(hours=1)
    return timedelta(minutes=int(match.group(1)) * _UNIT_MINUTES[match.group(2)])


def parse_time(value: Any) -> Optional[datetime]:
    """A journal timestamp (ISO or ``str(datetime)``); naive values are taken as UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _float(value: Any) -> Optional[float]:
    number = _decimal(value)
    return None if number is None else float(number)


def _payload(value: Any) -> Dict[str, Any]:
    """The mirrored ledger payload: a JSON string in the journal, or already a dict."""
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _reason(value: Any) -> str:
    """A short audit token for a block reason (journal text is not trusted as-is)."""
    text = _REASON_RE.sub("_", str(value or "").strip())[:80].strip("_")
    return text or "unknown"


def candidate_key(instrument: str, candle_ts: datetime) -> str:
    return f"{instrument}|{candle_ts.astimezone(timezone.utc).isoformat()}"


def _floor(when: datetime, step: timedelta) -> datetime:
    seconds = int(step.total_seconds())
    return datetime.fromtimestamp(int(when.timestamp()) // seconds * seconds, tz=timezone.utc)


@dataclass(frozen=True)
class RuntimeDecision:
    """One authoritative runtime decision on a NEW long entry (mirrored ledger event)."""

    instrument: str
    at: datetime
    allowed: bool
    reason: str
    kind: str  # "risk_decision" | "equity_unavailable"


@dataclass(frozen=True)
class Baseline:
    """What the existing system decided about a candidate (the news layer never changes it)."""

    allowed: bool
    reason: str
    source: str  # "runtime" | "shadow_eval" | "not_observed"
    decided_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "source": self.source,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }


@dataclass(frozen=True)
class Phase6aCandidate:
    """One candidate NEW long entry from the Phase 6a journal, with its baseline once settled."""

    key: str
    instrument: str
    timeframe: str
    candle_ts: datetime
    close_time: datetime
    signal_source: str  # "shadow_eval" (a journaled LONG signal) | "runtime_only" (a decision without one)
    confidence: Optional[float]
    cleared: Optional[bool]
    veto_reason: Optional[str]
    signal_reason: str
    baseline: Optional[Baseline]
    intent_size: Optional[Decimal] = None
    intent_price: Optional[Decimal] = None
    # As read from the journal, for the report's independent checks: the action of
    # the candle's signal line (if any) and "entry" when a runtime entry decision exists.
    journal_action: Optional[str] = None
    decision_intent: Optional[str] = None

    @property
    def settled(self) -> bool:
        return self.baseline is not None

    @property
    def signal_id(self) -> str:
        """The runtime's own signal id format: ``<instrument>|<timeframe>|<candle open ISO>``."""
        return f"{self.instrument}|{self.timeframe}|{self.candle_ts.isoformat()}"

    @property
    def decision_time(self) -> datetime:
        """When the runtime decided (its decision time when observed, else the candle close)."""
        if self.baseline is not None and self.baseline.decided_at is not None:
            return self.baseline.decided_at
        return self.close_time

    @property
    def baseline_notional(self) -> Optional[Decimal]:
        if self.intent_size is None or self.intent_price is None:
            return None
        return self.intent_size * self.intent_price

    def to_dict(self) -> dict:
        notional = self.baseline_notional
        return {
            "candidate_key": self.key,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "candle_ts": self.candle_ts.isoformat(),
            "candle_close": self.close_time.isoformat(),
            "signal_id": self.signal_id,
            "signal_action": "long",
            "signal_source": self.signal_source,
            "signal_confidence": self.confidence,
            "signal_cleared": self.cleared,
            "signal_veto_reason": self.veto_reason,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "baseline_intent_size": None if self.intent_size is None else str(self.intent_size),
            "baseline_intent_price": None if self.intent_price is None else str(self.intent_price),
            "baseline_notional": None if notional is None else str(notional),
            "journal_signal_action": self.journal_action,
            "journal_decision_intent": self.decision_intent,
        }


class Phase6aJournal:
    """Incremental, read-only reader of the Phase 6a journal files.

    ``refresh`` reads only complete lines appended since the last call (a line
    still being written is picked up next time); unparseable lines are counted
    and skipped. The first journaled LONG signal for a candle wins.
    """

    def __init__(self, journal_dir: Path, *, settle: timedelta = DEFAULT_SETTLE) -> None:
        if settle <= timedelta(0):
            raise ValueError("settle must be positive")
        self.journal_dir = Path(journal_dir)
        self._settle = settle
        self._offsets: Dict[str, int] = {}
        self._signals: Dict[str, Dict[str, Any]] = {}
        self._signal_actions: Dict[str, str] = {}
        self._timeframes: Dict[Tuple[str, datetime], str] = {}
        self._candles: Dict[str, Dict[datetime, PublicCandle]] = {}
        self._decisions: Dict[Tuple[str, str, str, str], RuntimeDecision] = {}
        self._intents: Dict[Tuple[str, datetime], Tuple[Optional[Decimal], Optional[Decimal]]] = {}
        self.lines_read = 0
        self.unparseable = 0
        self.files_found: set = set()

    def file_for(self, day: date) -> Path:
        return self.journal_dir / f"journal-{day.isoformat()}.jsonl"

    @property
    def exists(self) -> bool:
        return self.journal_dir.is_dir()

    def refresh(self, days: Iterable[date]) -> int:
        """Read new complete lines of each day's file; returns how many records were read."""
        return sum(self._read_new(self.file_for(day)) for day in sorted(set(days)))

    def _read_new(self, path: Path) -> int:
        try:
            size = path.stat().st_size
        except OSError:
            return 0
        self.files_found.add(path.name)
        key = str(path)
        offset = self._offsets.get(key, 0)
        if size < offset:  # replaced or truncated: read it again (records are de-duplicated)
            offset = 0
        if size == offset:
            return 0
        with path.open("rb") as fh:  # read-only
            fh.seek(offset)
            data = fh.read(size - offset)
        end = data.rfind(b"\n")
        if end < 0:
            return 0
        self._offsets[key] = offset + end + 1
        count = 0
        for raw in data[: end + 1].splitlines():
            if not raw.strip():
                continue
            self.lines_read += 1
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self.unparseable += 1
                continue
            if isinstance(record, dict):
                self._ingest(record)
                count += 1
        return count

    # -- one journal record ------------------------------------------------------------

    def _ingest(self, record: Mapping[str, Any]) -> None:
        kind = record.get("kind")
        if kind == "signal":
            self._ingest_signal(record)
        elif kind == "candle":
            self._ingest_candle(record)
        elif kind == "ledger_event":
            self._ingest_event(record)
        elif kind == "ledger_intent":
            self._ingest_intent(record)

    def _ingest_signal(self, record: Mapping[str, Any]) -> None:
        if record.get("source") not in (None, "shadow_eval"):
            return
        instrument = str(record.get("instrument") or "")
        candle_ts = parse_time(record.get("candle_ts"))
        if not instrument or candle_ts is None:
            return
        key = candidate_key(instrument, candle_ts)
        action = str(record.get("action") or "").strip().lower()
        self._signal_actions.setdefault(key, action)
        if action != "long" or key in self._signals:
            return
        cleared = record.get("cleared")
        veto = record.get("veto_reason")
        self._signals[key] = {
            "instrument": instrument,
            "candle_ts": candle_ts,
            "confidence": _float(record.get("confidence")),
            "cleared": cleared if isinstance(cleared, bool) else None,
            "veto_reason": _reason(veto) if veto else None,
            "reason": str(record.get("reason") or "")[:200],
        }

    def _ingest_candle(self, record: Mapping[str, Any]) -> None:
        instrument = str(record.get("instrument") or "")
        opened = parse_time(record.get("candle_ts"))
        if not instrument or opened is None:
            return
        timeframe = str(record.get("timeframe") or DEFAULT_TIMEFRAME)
        self._timeframes.setdefault((instrument, opened), timeframe)
        values = [_float(record.get(k)) for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in values):
            return
        o, h, low, c, vol = values  # type: ignore[misc]
        try:
            candle = PublicCandle(opened, timeframe_interval(timeframe), o, h, low, c, vol)
        except ValueError:
            return
        self._candles.setdefault(instrument, {}).setdefault(opened, candle)

    def _ingest_event(self, record: Mapping[str, Any]) -> None:
        event_type = record.get("event_type")
        if event_type not in ("risk_decision", "equity_unavailable"):
            return
        payload = _payload(record.get("payload"))
        at = parse_time(record.get("event_time")) or parse_time(record.get("ts"))
        instrument = str(payload.get("instrument") or "")
        if at is None or not instrument:
            return
        if event_type == "equity_unavailable":
            decision = RuntimeDecision(instrument, at, False, "equity_unavailable", event_type)
        else:
            message = _MESSAGE_RE.match(str(record.get("message") or ""))
            intent = payload.get("intent") or (message.group(1) if message else None)
            if intent != "entry":
                return
            allowed = payload.get("allowed")
            if not isinstance(allowed, bool):
                if message is None:
                    return
                allowed = message.group(2) == "allowed"
            reason = payload.get("reason") or (message.group(3) if message else "")
            decision = RuntimeDecision(instrument, at, allowed, _reason(reason), event_type)
        self._decisions.setdefault((instrument, at.isoformat(), event_type, decision.reason), decision)

    def _ingest_intent(self, record: Mapping[str, Any]) -> None:
        if record.get("intent") != "entry":
            return
        parts = str(record.get("signal_id") or "").split("|")
        if len(parts) != 3:
            return
        candle_ts = parse_time(parts[2])
        if candle_ts is None:
            return
        self._intents.setdefault((parts[0], candle_ts), (_decimal(record.get("size")), _decimal(record.get("price"))))

    # -- candidates --------------------------------------------------------------------

    def _timeframe_for(self, instrument: str, candle_ts: Optional[datetime]) -> str:
        known = self._timeframes.get((instrument, candle_ts)) if candle_ts is not None else None
        if known:
            return known
        seen = Counter(tf for (inst, _), tf in self._timeframes.items() if inst == instrument)
        return seen.most_common(1)[0][0] if seen else DEFAULT_TIMEFRAME

    def _decisions_by_candle(self) -> Dict[Tuple[str, datetime], RuntimeDecision]:
        """Each runtime decision belongs to exactly one candle: the one that closed last
        at or before the decision (allowing a small early stamp); the earliest wins."""
        out: Dict[Tuple[str, datetime], RuntimeDecision] = {}
        for decision in sorted(self._decisions.values(), key=lambda d: (d.at, d.kind, d.reason)):
            interval = timeframe_interval(self._timeframe_for(decision.instrument, None))
            candle_ts = _floor(decision.at + DECISION_EARLY_SLACK, interval) - interval
            out.setdefault((decision.instrument, candle_ts), decision)
        return out

    def candidates(self, now: datetime) -> List[Phase6aCandidate]:
        """Every candidate known so far; ``baseline`` is None while it is still settling."""
        now = now.astimezone(timezone.utc)
        rows: Dict[str, Phase6aCandidate] = {}
        by_candle = self._decisions_by_candle()
        claimed: set = set()
        for key, sig in self._signals.items():
            instrument, candle_ts = sig["instrument"], sig["candle_ts"]
            timeframe = self._timeframe_for(instrument, candle_ts)
            interval = timeframe_interval(timeframe)
            close = candle_ts + interval
            decision = by_candle.get((instrument, candle_ts))
            baseline: Optional[Baseline] = None
            if decision is not None:
                claimed.add((instrument, candle_ts))
                baseline = Baseline(decision.allowed, decision.reason, "runtime", decision.at)
            elif now >= close + self._settle:
                if sig["cleared"] is False:
                    baseline = Baseline(False, sig["veto_reason"] or "confidence_too_low", "shadow_eval")
                else:
                    baseline = Baseline(False, "not_observed", "not_observed")
            size, price = self._intents.get((instrument, candle_ts), (None, None))
            rows[key] = Phase6aCandidate(
                key=key,
                instrument=instrument,
                timeframe=timeframe,
                candle_ts=candle_ts,
                close_time=close,
                signal_source="shadow_eval",
                confidence=sig["confidence"],
                cleared=sig["cleared"],
                veto_reason=sig["veto_reason"],
                signal_reason=sig["reason"],
                baseline=baseline,
                intent_size=size,
                intent_price=price,
                journal_action=self._signal_actions.get(key),
                decision_intent="entry" if decision is not None else None,
            )
        # A runtime entry decision with no journaled LONG signal is still a candidate.
        for (instrument, candle_ts), decision in sorted(by_candle.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            key = candidate_key(instrument, candle_ts)
            if (instrument, candle_ts) in claimed or key in rows:
                continue
            timeframe = self._timeframe_for(instrument, candle_ts)
            interval = timeframe_interval(timeframe)
            size, price = self._intents.get((instrument, candle_ts), (None, None))
            rows[key] = Phase6aCandidate(
                key=key,
                instrument=instrument,
                timeframe=timeframe,
                candle_ts=candle_ts,
                close_time=candle_ts + interval,
                signal_source="runtime_only",
                confidence=None,
                cleared=None,
                veto_reason=None,
                signal_reason="",
                baseline=Baseline(decision.allowed, decision.reason, "runtime", decision.at),
                intent_size=size,
                intent_price=price,
                journal_action=self._signal_actions.get(key),
                decision_intent="entry",
            )
        return sorted(rows.values(), key=lambda c: (c.candle_ts, c.instrument))

    def signal_actions(self, day: Optional[date] = None) -> Counter:
        """Journaled signal actions (long / flat / hold) by count, optionally for one candle day."""
        counts: Counter = Counter()
        for key, action in self._signal_actions.items():
            if day is not None:
                when = parse_time(key.split("|", 1)[1])
                if when is None or when.date() != day:
                    continue
            counts[action or "unknown"] += 1
        return counts

    def candles(self, instrument: str) -> Tuple[PublicCandle, ...]:
        series = self._candles.get(instrument, {})
        return tuple(series[t] for t in sorted(series))

    def prune(self, before: datetime) -> None:
        """Forget records about candles that opened before ``before`` (bounded memory)."""
        self._signals = {k: v for k, v in self._signals.items() if v["candle_ts"] >= before}
        self._signal_actions = {
            k: v for k, v in self._signal_actions.items() if (parse_time(k.split("|", 1)[1]) or before) >= before
        }
        self._timeframes = {k: v for k, v in self._timeframes.items() if k[1] >= before}
        self._candles = {i: {t: c for t, c in s.items() if t >= before} for i, s in self._candles.items()}
        self._decisions = {k: d for k, d in self._decisions.items() if d.at >= before}
        self._intents = {k: v for k, v in self._intents.items() if k[1] >= before}
