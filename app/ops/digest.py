"""Daily ops digest (plan row R6; master plan section 5.4) — plain English, from files only.

Once a day (07:00 Beirut by the systemd timer) the owner gets one Telegram message
that says what needs attention and how each running part did the day before. It is
built from the files those parts already write, never from their databases, the
exchange or the network:

- the Phase 6a shadow (``logs/shadow``): ``heartbeat.json`` (now), ``state.json`` and
  ``ALERT`` (a halt waiting for the operator), and one UTC day's
  ``journal-YYYY-MM-DD.jsonl`` — the supervisor's own lines (candles, signals,
  health, restarts) plus its read-only mirror of the demo ledger (risk decisions,
  fills, reconciliations);
- the news shadow (``logs/news_shadow``): its saved state (last cycle, live events),
  its spend record and the day's numbers through ``app.news.report.build_report_data``
  (the same numbers as its own daily report);
- the paper fleet: a facts dict the caller reads with the fleet's own status view
  (``research``; ``scripts/ops_digest.py`` passes it in);
- the OKX changelog watcher (``logs/ops/okx_changelog``): its state.

The digest itself is a deterministic template: fixed rules decide what "needs
attention", and the same files always give the same text. ``app.ops.digest_ai`` can
add a short Claude-written summary on top; the template is sent either way.

Read-only and observability only. A file that is missing, half-written or
unreadable is reported as such; it never stops the digest. Nothing here can place,
size, approve, modify or cancel an order, and nothing in the trading runtime reads it.
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
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from app.news.sanitize import sanitize_text

DIGEST_VERSION = "ops-digest-v1"
# The Phase 6a supervisor's file names (app/shadow/supervisor.py; a test keeps them equal).
HEARTBEAT_FILENAME = "heartbeat.json"
STATE_FILENAME = "state.json"
ALERT_FILENAME = "ALERT"
JOURNAL_PREFIX = "journal"
NEWS_STATE_FILE = "shadow_state.json"  # app/news/shadow.py STATE_FILE (a test keeps them equal)

# Thresholds of the attention rules (fixed here, documented in docs/runbooks/OPS_DIGEST.md).
HEARTBEAT_LATE_MINUTES = 10.0  # the supervisor writes its heartbeat every 20 s
CANDLE_LATE_BARS = 2.5  # no candle CLOSED for 2.5 bars (2.5 h on the 1H strategy) is a feed problem
DOWN_CANDLES_MISSING = 2  # a day's journal with 2+ fewer closed candles than a full day: down or blind for hours
NEWS_LATE_MINUTES = 30.0  # the news shadow saves its state every 5-minute cycle
FLEET_LATE_MINUTES = 15.0  # the fleet runs a cycle every minute
CHANGELOG_LATE_HOURS = 50.0  # the watcher runs daily; two missed days
UPTIME_WATCH_PCT = 95.0  # of the health samples written while the shadow ran
NEWS_HEALTHY_WATCH_PCT = 90.0
SPEND_WATCH_SHARE = 0.8
TELEGRAM_LIMIT = 3800  # Telegram's limit is 4096 characters per message; keep a margin
REASON_MAX_CHARS = 200
# Demo-runtime events worth a look whatever their severity (app/execution; error-level ones are listed anyway).
NOTABLE_EVENTS = {
    "exit_deferred": "a protective exit was deferred",
    "exit_precision_rejected": "an exit was rejected for lot precision",
    "kill_switch_release_refused": "a kill-switch release was refused",
    "arm_refused": "arming was refused",
    "private_foreign": "an order this system did not place was seen",
    "equity_unavailable": "the account equity could not be read",
    "startup_gate_blocked": "a startup gate refused to start",
}

# Supervisor journal events that open a new supervision attempt; the heartbeat's last candle starts empty after one.
ATTEMPT_START_EVENTS = ("eval_window_reset", "start")

BEIRUT = "Asia/Beirut"
# A number, with its sign only when the sign stands alone ("-12.0%", not the hyphens of "2026-10-21").
_NUMBER = re.compile(r"(?<![\w.])([-+−]?)(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)")


# -- small helpers -------------------------------------------------------------------------


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    try:
        out = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _minutes_between(earlier: Optional[datetime], later: datetime) -> Optional[float]:
    if earlier is None:
        return None
    return max(0.0, (later - earlier).total_seconds() / 60.0)


def _dec(value: Any) -> Optional[Decimal]:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return out if out.is_finite() else None


def _clean(text: Any, limit: int = REASON_MAX_CHARS) -> str:
    """Text from a file, fit for one line of a message: control/zero-width/bidi characters removed, capped."""
    return sanitize_text(str(text or ""), max_chars=limit).text


def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """(data, None), (None, None) when missing, or (None, error) when unreadable."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"unreadable ({type(exc).__name__})"
    try:
        return json.loads(raw), None
    except ValueError:
        return None, "unreadable (not JSON)"


def _jsonl(path: Path) -> Iterator[Tuple[Optional[dict], bool]]:
    """(record, ok) per non-empty line; a broken or half-written last line is (None, False)."""
    with open(path, "rb") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                yield None, False
                continue
            yield (value, True) if isinstance(value, dict) else (None, False)


def _payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            out = json.loads(value)
        except ValueError:
            return {}
        return out if isinstance(out, dict) else {}
    return {}


def _timeframe_hours(timeframe: Optional[str]) -> float:
    m = re.fullmatch(r"(\d+)([mHDW])", str(timeframe or "1H"))
    if not m:
        return 1.0
    n = int(m.group(1))
    return {"m": n / 60.0, "H": float(n), "D": 24.0 * n, "W": 168.0 * n}[m.group(2)]


def _int(value: Any) -> int:
    """A count from a file; anything that is not a number counts as 0 (never an exception)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        number = _dec(value)
        return int(number) if number is not None else 0


def _guarded(fn: Callable[[], Dict[str, Any]], fallback: Dict[str, Any]) -> Dict[str, Any]:
    """One part of a source; an unexpected failure becomes an ``error`` field, never a lost digest."""
    try:
        return fn()
    except Exception as exc:
        return {**fallback, "error": f"could not be read ({type(exc).__name__})"}


# -- Phase 6a shadow -----------------------------------------------------------------------


class _DayTally:
    """Counts of one UTC day of the Phase 6a journal: the supervisor's own lines and its ledger mirror."""

    def __init__(self) -> None:
        self.lines = self.bad = self.candles = 0
        self.signals: Counter = Counter()
        self.decisions: Counter = Counter()
        self.blocked: Counter = Counter()
        self.supervisor: Counter = Counter()
        self.errors: Counter = Counter()
        self.notable: Counter = Counter()
        self.warnings: Counter = Counter()
        self.health = {"samples": 0, "ws_auth": 0, "feed_usable": 0, "continuity": 0}
        self.recs = {"count": 0, "consistent": 0, "inconsistent": 0, "foreign_orders": 0, "unexplained": 0}
        self.stops = {"evaluations": 0, "breaches": 0}
        self.fills = {"count": 0, "buys": 0, "sells": 0}
        self.buy_notional = self.sell_notional = Decimal(0)
        self.fees: Dict[str, Decimal] = {}
        self.quotes: set = set()
        self.instrument: Optional[str] = None
        self.timeframe: Optional[str] = None
        self.last_attempt_at: Optional[datetime] = None  # the latest (re)start of the supervision loop

    def add(self, rec: Mapping[str, Any]) -> None:
        kind = rec.get("kind")
        if kind == "candle":
            self.candles += 1
            self.instrument = self.instrument or _clean(rec.get("instrument"), 20) or None
            self.timeframe = self.timeframe or _clean(rec.get("timeframe"), 8) or None
        elif kind == "signal":
            action = _clean(rec.get("action"), 20)
            self.signals[action] += 1
            if action == "long":
                self.signals["cleared" if rec.get("cleared") else "below_floor"] += 1
        elif kind == "stop_eval":
            self.stops["evaluations"] += 1
            self.stops["breaches"] += 1 if rec.get("breached") else 0
        elif kind == "health":
            self.health["samples"] += 1
            self.health["ws_auth"] += 1 if rec.get("ws_auth") else 0
            self.health["feed_usable"] += 1 if rec.get("feed_usable") else 0
            self.health["continuity"] += 1 if rec.get("market_continuity_ok", True) else 0
        elif kind == "supervisor":
            event = _clean(rec.get("event"), 60)
            if event == "rearm" and not rec.get("renewed"):
                event = "rearm_refused"
            self.supervisor[event] += 1
            if event in ATTEMPT_START_EVENTS:
                at = _parse_ts(rec.get("ts"))
                if at is not None and (self.last_attempt_at is None or at > self.last_attempt_at):
                    self.last_attempt_at = at
        elif kind == "ledger_event":
            self._ledger_event(rec)
        elif kind == "ledger_fill":
            self._fill(rec)
        elif kind == "ledger_reconciliation":
            self.recs["count"] += 1
            if rec.get("consistent") is True:
                self.recs["consistent"] += 1
            else:
                self.recs["inconsistent"] += 1
            self.recs["foreign_orders"] += _int(rec.get("foreign_orders"))
            self.recs["unexplained"] += _int(rec.get("unexplained_balances"))

    def _ledger_event(self, rec: Mapping[str, Any]) -> None:
        event_type = _clean(rec.get("event_type") or "unknown", 60)
        severity = str(rec.get("severity") or "")
        if event_type == "risk_decision":
            payload = _payload(rec.get("payload"))
            message = str(rec.get("message") or "")
            intent = _clean(payload.get("intent") or message.split(" ", 1)[0] or "unknown", 20)
            allowed = payload.get("allowed")
            if allowed is None:
                allowed = " allowed" in message
            self.decisions[f"{intent}_{'allowed' if allowed else 'blocked'}"] += 1
            if not allowed:
                reason = payload.get("reason") or (message.split(":", 1)[1].strip() if ":" in message else "unknown")
                self.blocked[_clean(reason, 60)] += 1
            return
        if event_type in NOTABLE_EVENTS:
            self.notable[event_type] += 1
        if severity in ("error", "critical"):
            self.errors[event_type] += 1
        elif severity == "warning":
            self.warnings[event_type] += 1

    def _fill(self, rec: Mapping[str, Any]) -> None:
        size, price = _dec(rec.get("fill_size")), _dec(rec.get("fill_price"))
        notional = (size or Decimal(0)) * (price or Decimal(0))
        self.fills["count"] += 1
        if str(rec.get("side")) == "buy":
            self.fills["buys"] += 1
            self.buy_notional += notional
        else:
            self.fills["sells"] += 1
            self.sell_notional += notional
        inst = str(rec.get("instrument") or "")
        if "-" in inst:
            self.quotes.add(_clean(inst.split("-")[1], 10))
        fee, ccy = _dec(rec.get("fee")), rec.get("fee_ccy")
        if fee is not None and ccy:
            key = _clean(ccy, 10)
            self.fees[key] = self.fees.get(key, Decimal(0)) + fee


def _shadow_day(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"journal": str(path), "found": path.exists()}
    if not out["found"]:
        return out
    t = _DayTally()
    try:
        for rec, ok in _jsonl(path):
            if not ok or rec is None:
                t.bad += 1
                continue
            try:
                t.add(rec)
                t.lines += 1
            except Exception:  # one odd record is skipped and counted; it never hides the rest
                t.bad += 1
    except OSError as exc:  # the counts below are partial (or empty), and the digest says so
        out["error"] = f"could not be read completely ({type(exc).__name__})"
    quote = sorted(t.quotes)[0] if len(t.quotes) == 1 else ("USDT" if not t.quotes else None)
    cash = None if quote is None else t.sell_notional - t.buy_notional + t.fees.get(quote, Decimal(0))
    tf_hours = _timeframe_hours(t.timeframe)

    def pct(key: str) -> Optional[float]:
        return round(100.0 * t.health[key] / t.health["samples"], 1) if t.health["samples"] else None

    out.update({
        "lines": t.lines, "unparseable": t.bad, "candles": t.candles, "instrument": t.instrument, "timeframe": t.timeframe,
        "expected_candles": int(round(24.0 / tf_hours)) if tf_hours <= 24.0 else None,
        "signals": {"long": t.signals["long"], "cleared": t.signals["cleared"], "below_floor": t.signals["below_floor"],
                    "flat": t.signals["flat"], "hold": t.signals["hold"]},
        "decisions": dict(sorted(t.decisions.items())), "blocked_reasons": dict(t.blocked.most_common()),
        "fills": {**t.fills, "quote": quote, "buy_notional": str(t.buy_notional), "sell_notional": str(t.sell_notional),
                  "fees": {k: str(v) for k, v in sorted(t.fees.items())}, "cash_result": None if cash is None else str(cash)},
        "reconciliations": t.recs, "stops": t.stops,
        "health": {"samples": t.health["samples"], "ws_auth_pct": pct("ws_auth"), "feed_usable_pct": pct("feed_usable"),
                   "continuity_pct": pct("continuity")},
        "supervisor": dict(sorted(t.supervisor.items())), "runtime_errors": dict(t.errors.most_common()),
        "runtime_warnings": dict(t.warnings.most_common()), "notable_events": dict(t.notable.most_common()),
        "last_attempt_at": None if t.last_attempt_at is None else t.last_attempt_at.isoformat(),
    })
    return out


def _last_attempt_in(path: Path) -> Optional[datetime]:
    """The latest supervision (re)start written in one journal file (None when there is none or no file)."""
    if not path.exists():
        return None
    latest: Optional[datetime] = None
    for rec, ok in _jsonl(path):
        if ok and rec is not None and rec.get("kind") == "supervisor" and rec.get("event") in ATTEMPT_START_EVENTS:
            at = _parse_ts(rec.get("ts"))
            if at is not None and (latest is None or at > latest):
                latest = at
    return latest


def _heartbeat(shadow_dir: Path, now: datetime, timeframe: Optional[str]) -> Dict[str, Any]:
    hb, err = _read_json(shadow_dir / HEARTBEAT_FILENAME)
    heartbeat: Dict[str, Any] = {"found": isinstance(hb, dict), "error": err}
    if not isinstance(hb, dict):
        return heartbeat
    ts = _parse_ts(hb.get("ts"))
    last_open = _parse_ts(hb.get("last_candle"))
    last_close = None if last_open is None else last_open + timedelta(hours=_timeframe_hours(timeframe))
    flat = hb.get("flat_at_lot")
    continuity = hb.get("market_continuity_ok")
    heartbeat.update({
        "ts": hb.get("ts"), "age_minutes": _minutes_between(ts, now), "state": _clean(hb.get("state") or "unknown", 40),
        "reason": _clean(hb.get("reason"), REASON_MAX_CHARS) or None, "position": _clean(hb.get("position"), 40) or None,
        "flat_at_lot": flat if isinstance(flat, bool) else None, "kill": bool(hb.get("kill")),
        "kill_owner": _clean(hb.get("kill_owner"), 80) or None, "armed_until": hb.get("armed_until"),
        "restarts_in_window": hb.get("restarts_in_window"), "entries_today": hb.get("entries_today"),
        "day_pnl": _clean(hb.get("day_pnl"), 40) or None, "last_candle": hb.get("last_candle"),
        "last_candle_close": None if last_close is None else last_close.isoformat(),
        "last_candle_closed_hours_ago": None if last_close is None else max(0.0, (now - last_close).total_seconds() / 3600.0),
        "market_continuity_ok": continuity if isinstance(continuity, bool) else None,
    })
    return heartbeat


def _alert(shadow_dir: Path) -> Dict[str, Any]:
    state, state_err = _read_json(shadow_dir / STATE_FILENAME)
    alert_path = shadow_dir / ALERT_FILENAME
    present = alert_path.exists()
    first_line = None
    if present:
        try:
            with open(alert_path, encoding="utf-8", errors="replace") as fh:
                first_line = _clean(fh.readline(), REASON_MAX_CHARS) or "(empty)"
        except OSError as exc:
            first_line = f"(the ALERT file could not be read: {type(exc).__name__})"
    state_alert = (_clean(state.get("alert"), REASON_MAX_CHARS) or None) if isinstance(state, dict) else None
    return {"present": present, "first_line": first_line, "state_alert": state_alert, "state_error": state_err}


def collect_shadow(shadow_dir: Path, day: date, now: datetime) -> Dict[str, Any]:
    """The Phase 6a shadow now (heartbeat, ALERT, state) and on ``day`` (its journal).

    The three parts are read independently: a broken journal never hides an ALERT."""
    shadow_dir = Path(shadow_dir)
    out: Dict[str, Any] = {"dir": str(shadow_dir), "present": shadow_dir.is_dir()}
    if not out["present"]:
        return out
    journal = shadow_dir / f"{JOURNAL_PREFIX}-{day.isoformat()}.jsonl"
    out["day"] = _guarded(lambda: _shadow_day(journal), {"journal": str(journal), "found": True})
    timeframe = out["day"].get("timeframe")
    if day == now.date() and out["day"].get("expected_candles"):
        # A day that is not over yet: only the hours that have passed can have candles.
        elapsed = (now - datetime(day.year, day.month, day.day, tzinfo=timezone.utc)).total_seconds() / 3600.0
        out["day"]["expected_candles"] = min(out["day"]["expected_candles"], int(elapsed // _timeframe_hours(timeframe)))
        out["day"]["partial_day"] = True
    out["heartbeat"] = _guarded(lambda: _heartbeat(shadow_dir, now, timeframe), {"found": False})
    hb = out["heartbeat"]
    if hb.get("found") and hb.get("last_candle") is None:
        # No candle since the last restart: time it from that restart (today's journal, else the day's).
        def since_restart() -> Dict[str, Any]:
            today = shadow_dir / f"{JOURNAL_PREFIX}-{now.date().isoformat()}.jsonl"
            at = _last_attempt_in(today) or _parse_ts(out["day"].get("last_attempt_at"))
            if at is not None:
                return {"restart_at": at.isoformat(), "hours": max(0.0, (now - at).total_seconds() / 3600.0)}
            if today.exists() and out["day"].get("found") and not out["day"].get("error"):
                # No restart in either journal: the last one was before the digested day began.
                start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
                return {"restart_at": None, "hours": None, "at_least_hours": max(0.0, (now - start).total_seconds() / 3600.0)}
            return {"restart_at": None, "hours": None}

        hb["no_candle_since_restart"] = _guarded(since_restart, {"restart_at": None, "hours": None})
    out["alert"] = _guarded(lambda: _alert(shadow_dir), {"present": None, "first_line": None, "state_alert": None, "state_error": None})
    report = shadow_dir / f"report-{day.isoformat()}.md"
    out["report"] = str(report) if report.exists() else None
    return out



# -- news shadow ---------------------------------------------------------------------------


def _spend_month(state_dir: Path, month: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    data, err = _read_json(state_dir / f"spend-{month}.json")
    if data is not None and not isinstance(data, dict):
        return None, "unreadable (not a spend record)"
    return data, err


def _news_spend(state_dir: Path, day: date, now: datetime, cap: Optional[float]) -> Dict[str, Any]:
    """This month's AI spend (what the cap applies to), and the day's spend from the day's own month
    (on the 1st, yesterday belongs to last month's record)."""
    month = f"{now:%Y-%m}"
    current, err = _spend_month(state_dir, month)
    sp: Dict[str, Any] = {"month": month, "cap_usd": cap, "error": err}
    if current is not None:
        refused = current.get("refused")
        sp.update({"spent_usd": float(_dec(current.get("spent_usd")) or 0), "calls": _int(current.get("calls")),
                   "refused": {str(k): _int(v) for k, v in refused.items()} if isinstance(refused, dict) else {}})
    day_month = f"{day:%Y-%m}"
    record = current
    if day_month != month:
        record, prev_err = _spend_month(state_dir, day_month)
        if record is not None:
            sp["previous_month"] = {"month": day_month, "spent_usd": float(_dec(record.get("spent_usd")) or 0)}
        elif prev_err:
            sp["previous_month"] = {"month": day_month, "error": prev_err}
    by_day = record.get("by_day") if isinstance(record, dict) else None
    sp["yesterday_usd"] = float(_dec(by_day.get(day.isoformat())) or 0) if isinstance(by_day, dict) else 0.0
    return sp


def collect_news(
    log_dir: Path,
    journal_dir: Optional[Path],
    day: date,
    now: datetime,
    *,
    monthly_cap_usd: Optional[float] = None,
    report_data: Optional[Callable[[Path, Optional[Path], date], Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """The news shadow now (state, spend) and on ``day`` (its report numbers)."""
    log_dir = Path(log_dir)
    out: Dict[str, Any] = {"dir": str(log_dir), "installed": log_dir.is_dir()}
    if not out["installed"]:
        return out
    state_dir = log_dir / "_state"
    state, err = _read_json(state_dir / NEWS_STATE_FILE)
    st: Dict[str, Any] = {"found": isinstance(state, dict), "error": err}
    if isinstance(state, dict):
        saved = _parse_ts(state.get("saved_at"))
        health = state.get("health") or []
        live = []
        for entry in state.get("book") or []:
            versions = entry.get("versions") if isinstance(entry, dict) else None
            last = versions[-1] if isinstance(versions, list) and versions else {}
            event = last.get("event") if isinstance(last, dict) else None
            event = event if isinstance(event, dict) else {}
            expires = _parse_ts(event.get("expires_at"))
            if expires is not None and expires > now:
                live.append({"category": _clean(event.get("category"), 60), "action": _clean(event.get("action"), 40),
                             "status": _clean(event.get("corroboration_status"), 60), "expires_at": expires.isoformat()})
        st.update({"saved_at": state.get("saved_at"), "age_minutes": _minutes_between(saved, now), "cycles": state.get("cycle"),
                   "last_cycle_healthy": bool(health[-1][1]) if health and isinstance(health[-1], (list, tuple)) else None,
                   "live_events": live})
    out["state"] = st
    out["spend"] = _news_spend(state_dir, day, now, monthly_cap_usd)
    if report_data is None:
        from app.news.report import build_report_data as report_data  # the news shadow's own numbers
    try:
        data = report_data(log_dir, journal_dir if journal_dir is not None and Path(journal_dir).is_dir() else None, day)
        out["day"] = {"headline": dict(data.get("headline") or {}), "anomalies": [_clean(a) for a in (data.get("anomalies") or [])[:3]],
                      "model_enabled": (data.get("runner") or {}).get("model_enabled")}
    except Exception as exc:  # the digest reports a broken log, it never fails on one
        out["day"] = {"error": f"the day's news logs could not be read ({type(exc).__name__})"}
    report = log_dir / f"report-{day.isoformat()}.md"
    out["report"] = str(report) if report.exists() else None
    return out


# -- OKX changelog watcher -----------------------------------------------------------------


def collect_changelog(state_dir: Path, now: datetime) -> Dict[str, Any]:
    from app.ops.okx_changelog import STATE_FILE, status_summary

    state_dir = Path(state_dir)
    out: Dict[str, Any] = {"dir": str(state_dir), "installed": (state_dir / STATE_FILE).exists()}
    if not out["installed"]:
        return out
    state, err = _read_json(state_dir / STATE_FILE)
    if not isinstance(state, dict):
        out["error"] = err or "unreadable state"
        return out
    out.update(status_summary(state, now))
    last_ok = _parse_ts(out.get("last_ok_at"))
    out["last_ok_age_hours"] = None if last_ok is None else (now - last_ok).total_seconds() / 3600.0
    return out


# -- attention rules -----------------------------------------------------------------------


@dataclass(frozen=True)
class Attention:
    level: str  # "ACTION": something is wrong now; "CHECK": worth a look
    text: str

    def to_dict(self) -> Dict[str, str]:
        return {"level": self.level, "text": self.text}


def _fmt_minutes(minutes: Optional[float]) -> str:
    if minutes is None:
        return "an unknown time"
    if minutes < 1:
        return "less than a minute"
    if minutes < 90:
        return f"{minutes:.0f} min"
    if minutes < 48 * 60:
        return f"{minutes / 60:.1f} h"
    return f"{minutes / 1440:.1f} days"


def attention_items(facts: Mapping[str, Any]) -> List[Attention]:
    """The fixed rules that decide what the owner should look at (ACTION first)."""
    items: List[Attention] = []
    now = _parse_ts(facts.get("generated_at")) or datetime.now(tz=timezone.utc)
    sh = facts.get("shadow") or {}
    if sh.get("present") and sh.get("error"):
        items.append(Attention("ACTION", f"The digest could not read the Phase 6a shadow's files ({sh['error']}): check "
                                         "logs/shadow by hand."))
    elif sh.get("present"):
        items += _shadow_attention(sh)
    elif facts.get("expect_shadow"):
        items.append(Attention("CHECK", f"There is no Phase 6a shadow folder at {sh.get('dir')}: if the shadow writes "
                                        "elsewhere, set PHASE6A_JOURNAL_DIR in /etc/ai-trading/ops.env."))

    news = facts.get("news") or {}
    if news.get("installed") and news.get("error"):
        items.append(Attention("CHECK", f"The news shadow's files {news['error']}."))
    elif news.get("installed"):
        items += _news_attention(news)

    fleet = facts.get("fleet") or {}
    if fleet.get("installed"):
        items += _fleet_attention(fleet)

    cl = facts.get("changelog") or {}
    if cl.get("installed"):
        items += _changelog_attention(cl, now)
    elif sh.get("present"):
        items.append(Attention("CHECK", "The OKX changelog watcher has not run next to the shadow yet (install "
                                        "okx-changelog-watch.timer, docs/runbooks/OPS_DIGEST.md)."))
    order = {"ACTION": 0, "CHECK": 1}
    return sorted(items, key=lambda a: order.get(a.level, 2))


def _shadow_attention(sh: Mapping[str, Any]) -> List[Attention]:
    items: List[Attention] = []
    alert = sh.get("alert") or {}
    hb = sh.get("heartbeat") or {}
    day = sh.get("day") or {}
    tf = day.get("timeframe") or "1H"
    halted = bool(alert.get("present") or alert.get("state_alert"))
    if alert.get("error"):
        items.append(Attention("ACTION", f"The digest could not tell whether the Phase 6a shadow is halted (its ALERT and "
                                         f"state files {alert['error']}): look at logs/shadow by hand."))
    if halted:
        why = alert.get("first_line") or alert.get("state_alert") or "see the ALERT file"
        items.append(Attention("ACTION", f"The Phase 6a shadow is halted and waits for you: {why}. It stays halted "
                                         "(no new entries) until you review the journal and acknowledge the alert."))
    if alert.get("state_error"):
        damaged = "not JSON" in str(alert["state_error"])
        items.append(Attention("ACTION" if damaged else "CHECK",
                               f"The digest could not read the shadow's state.json ({alert['state_error']}). A damaged "
                               "state file makes the supervisor refuse to restart until it is fixed."))
    if hb.get("error") and not hb.get("found"):
        items.append(Attention("ACTION", f"The digest could not read the shadow's heartbeat ({hb['error']}), so it cannot "
                                         "tell whether the shadow runs."))
    elif not hb.get("found"):
        items.append(Attention("ACTION", "The Phase 6a shadow has no heartbeat file: it is not running, or it writes "
                                         f"somewhere else than {sh.get('dir')}."))
    else:
        age = hb.get("age_minutes")
        if age is None or age > HEARTBEAT_LATE_MINUTES:
            items.append(Attention("ACTION", f"The Phase 6a shadow's heartbeat is {_fmt_minutes(age)} old: the "
                                             "supervisor may have stopped (check shadow.service)."))
        elif hb.get("state") != "running" and not halted:
            items.append(Attention("ACTION", f"The Phase 6a shadow reports state '{hb.get('state')}'"
                                             + (f": {hb.get('reason')}" if hb.get("reason") else ".")))
        hours = hb.get("last_candle_closed_hours_ago")
        limit = CANDLE_LATE_BARS * _timeframe_hours(tf)
        if hb.get("state") == "running" and hours is not None and hours > limit:
            items.append(Attention("ACTION", f"No new {tf} candle has closed for the Phase 6a shadow for {hours:.1f} h (the "
                                             f"last one closed at {_dm(hb.get('last_candle_close'))}): the market feed may be "
                                             "down, and strategy and stop checks wait for candles."))
        since = hb.get("no_candle_since_restart") or {}
        if hb.get("state") == "running" and hb.get("last_candle") is None and (since.get("hours") or 0.0) > limit:
            items.append(Attention("ACTION", f"No candle has reached the Phase 6a shadow since it restarted "
                                             f"{since['hours']:.1f} h ago ({_dm(since.get('restart_at'))}): the market feed may "
                                             "be down, and strategy and stop checks wait for candles."))
        elif hb.get("state") == "running" and hb.get("last_candle") is None and (since.get("at_least_hours") or 0.0) > limit:
            items.append(Attention("ACTION", f"No candle has reached the Phase 6a shadow for at least "
                                             f"{since['at_least_hours']:.0f} h (since a restart before the digested day): the "
                                             "market feed may be down, and strategy and stop checks wait for candles."))
        if hb.get("market_continuity_ok") is False:
            items.append(Attention("CHECK", "The shadow's market-continuity check is not satisfied (a candle gap): new "
                                            "entries are paused until live candles confirm the feed; exits and stops still work."))
        if hb.get("kill"):
            owner = hb.get("kill_owner")
            if owner and not str(owner).startswith("halt:"):
                items.append(Attention("CHECK", f"New entries are paused for the rest of the UTC day by the shadow's own "
                                                f"cap ({owner}); exits and stops still work."))
            elif not owner:
                items.append(Attention("CHECK", "The kill switch is engaged and the shadow did not engage it itself "
                                                "(you, or a halt): no new entries until it is released."))
    if day.get("error"):
        items.append(Attention("CHECK", f"Yesterday's shadow journal {day['error']}: the counts below are missing or "
                                        "incomplete (the halt and heartbeat checks above do not depend on it)."))
    if day.get("found") and day.get("lines") is not None:
        recs = day.get("reconciliations") or {}
        if recs.get("inconsistent"):
            items.append(Attention("ACTION", f"{recs['inconsistent']} reconciliation(s) with the exchange were "
                                             "inconsistent yesterday: the shadow halts on these; review before anything else."))
        expected, candles = day.get("expected_candles"), day.get("candles") or 0
        complete = not day.get("error")  # counts from a journal read only in part prove nothing about downtime
        if complete and expected and candles <= expected - DOWN_CANDLES_MISSING:
            missing = (expected - candles) * _timeframe_hours(tf)
            when = "so far today" if day.get("partial_day") else "yesterday"
            items.append(Attention("CHECK", f"Only {candles} of {expected} {tf} candles reached the shadow {when}: it "
                                            f"was down or without market data for about {missing:.0f} h."))
        sup = day.get("supervisor") or {}
        if sup.get("start"):
            items.append(Attention("CHECK", f"The shadow process started {sup['start']} time(s) yesterday (a service "
                                            "restart, a reboot, or the whole process crashing)."))
        if sup.get("restart"):
            items.append(Attention("CHECK", f"The Phase 6a shadow restarted {sup['restart']} time(s) yesterday after a "
                                            "crash or a refused gate."))
        if sup.get("supervise_tick_error"):
            items.append(Attention("CHECK", f"The shadow supervisor logged {sup['supervise_tick_error']} tick error(s) yesterday."))
        notable = day.get("notable_events") or {}
        if notable:
            items.append(Attention("CHECK", "The demo runtime reported: " + "; ".join(
                f"{NOTABLE_EVENTS.get(k, k)} ({k} x{v})" for k, v in list(notable.items())[:4]) + "."))
        errors = {k: v for k, v in (day.get("runtime_errors") or {}).items() if k not in notable}
        if errors:
            items.append(Attention("CHECK", "The demo runtime logged errors yesterday: "
                                            + ", ".join(f"{k} x{v}" for k, v in list(errors.items())[:4]) + "."))
        health = (day.get("health") or {}) if complete else {}
        ws, feed = health.get("ws_auth_pct"), health.get("feed_usable_pct")
        if ws is not None and ws < UPTIME_WATCH_PCT:
            items.append(Attention("CHECK", f"While it ran yesterday, the shadow's private connection was authenticated "
                                            f"only {ws:.1f}% of the time."))
        if feed is not None and feed < UPTIME_WATCH_PCT:
            items.append(Attention("CHECK", f"While it ran yesterday, the shadow's market feed was usable only {feed:.1f}% "
                                            "of the time."))
    elif not day.get("found") and hb.get("found"):
        items.append(Attention("CHECK", "The Phase 6a shadow wrote no journal for yesterday."))
    return items


def _news_attention(news: Mapping[str, Any]) -> List[Attention]:
    items: List[Attention] = []
    st = news.get("state") or {}
    h = (news.get("day") or {}).get("headline") or {}
    if (news.get("day") or {}).get("error"):
        items.append(Attention("CHECK", f"News shadow: {news['day']['error']}."))
    if h and h.get("invariants_ok") is False:
        items.append(Attention("ACTION", "A news-shadow safety check FAILED yesterday: stop news-shadow.service and "
                                         "ask for a review (docs/runbooks/NEWS_SHADOW.md)."))
    if not st.get("found"):
        items.append(Attention("CHECK", "The news shadow's folder exists but it has not saved a cycle yet"
                                        + (f" ({st['error']})." if st.get("error") else ".")))
    else:
        age = st.get("age_minutes")
        if age is None or age > NEWS_LATE_MINUTES:
            items.append(Attention("ACTION", f"The news shadow has not saved a cycle for {_fmt_minutes(age)}: it is "
                                             "probably not running (check news-shadow.service)."))
        elif st.get("last_cycle_healthy") is False:
            items.append(Attention("CHECK", "The news shadow's last cycle was unhealthy (its effects are off until it recovers)."))
    if h.get("healthy_pct") is not None and h["healthy_pct"] < NEWS_HEALTHY_WATCH_PCT:
        items.append(Attention("CHECK", f"The news state was healthy only {h['healthy_pct']}% of yesterday."))
    sp = news.get("spend") or {}
    if sp.get("error"):
        items.append(Attention("CHECK", "The news shadow's spend record is unreadable; it treats the month as spent "
                                        "until you check it (docs/runbooks/NEWS_SHADOW.md)."))
    elif sp.get("cap_usd") and (sp.get("spent_usd") or 0.0) >= SPEND_WATCH_SHARE * sp["cap_usd"]:
        items.append(Attention("CHECK", f"AI spend of the news shadow is ${sp['spent_usd']:.2f} of the "
                                        f"${sp['cap_usd']:.2f} monthly cap."))
    return items


def _fleet_attention(fleet: Mapping[str, Any]) -> List[Attention]:
    if fleet.get("error"):
        return [Attention("CHECK", f"Paper fleet: {fleet['error']}.")]
    if not fleet.get("found"):
        return [Attention("CHECK", "The paper fleet's folder exists but it holds no fleet yet.")]
    items: List[Attention] = []
    age = fleet.get("last_cycle_age_minutes")
    if age is None or age > FLEET_LATE_MINUTES:
        items.append(Attention("ACTION", f"The paper fleet's last cycle was {_fmt_minutes(age)} ago: it is "
                                         "probably not running (check paper-fleet.service)."))
    elif fleet.get("data_stale"):
        items.append(Attention("CHECK", "The paper fleet's public prices are stale (no new hourly candle for over 2.5 h)."))
    if fleet.get("last_errors"):
        items.append(Attention("CHECK", f"The paper fleet reported errors in its last cycle: {fleet['last_errors'][-1]}"))
    alarms = fleet.get("drawdown_alarms") or []
    if alarms:
        items.append(Attention("CHECK", f"Paper fleet drawdown ALARM on {', '.join(alarms[:5])}: it fell 1.5 times further "
                                        "than the worst drop of its backtest, which counts against that configuration "
                                        "(weekly report)."))
    return items


def _changelog_attention(cl: Mapping[str, Any], now: datetime) -> List[Attention]:
    if cl.get("error"):
        return [Attention("CHECK", "The OKX changelog watcher's state is unreadable.")]
    items: List[Attention] = []
    since = now - timedelta(hours=24)
    fresh = [r for r in cl.get("flagged_recent") or [] if (_parse_ts(r.get("at")) or since - timedelta(seconds=1)) >= since]
    if fresh:
        titles = "; ".join(f"\"{_clean(r.get('title'), 90)}\"" for r in fresh[:3])
        items.append(Attention("CHECK", f"OKX's API changelog has {len(fresh)} new or edited "
                                        f"{'entry' if len(fresh) == 1 else 'entries'} mentioning what this system uses: "
                                        f"{titles}. Read them (links in the changelog section)."))
    pending = [r for r in cl.get("pending") or [] if r not in fresh]
    if pending:
        titles = "; ".join(f"\"{_clean(r.get('title'), 90)}\"" for r in pending[:3])
        items.append(Attention("CHECK", f"The changelog watcher could not deliver {len(pending)} alert(s) yet (it retries "
                                        f"daily): {titles}."))
    age = cl.get("last_ok_age_hours")
    if age is None or age > CHANGELOG_LATE_HOURS or (cl.get("consecutive_failures") or 0) >= 2:
        items.append(Attention("CHECK", f"The OKX changelog watcher has not read the changelog since "
                                        f"{cl.get('last_ok_at') or 'it was installed'} (last error: {cl.get('last_error') or 'none'})."))
    return items



# -- the whole digest ----------------------------------------------------------------------


def build_facts(
    *,
    now: datetime,
    day: date,
    shadow_dir: Path,
    news_dir: Path,
    changelog_dir: Path,
    fleet: Mapping[str, Any],
    news_cap_usd: Optional[float] = None,
    report_data: Optional[Callable[[Path, Optional[Path], date], Mapping[str, Any]]] = None,
    expect_shadow: bool = False,
) -> Dict[str, Any]:
    """Every fact of one digest (JSON-ready). ``day`` is the UTC day the "yesterday" lines describe.

    ``expect_shadow``: this machine runs the Phase 6a shadow (the timer's ``--send`` run on the
    server), so a missing shadow folder is worth a line in NEEDS ATTENTION."""
    facts: Dict[str, Any] = {"version": DIGEST_VERSION, "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
                             "day": day.isoformat(), "expect_shadow": bool(expect_shadow)}

    def guarded(fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        try:
            return fn()
        except Exception as exc:  # one broken source never stops the digest
            return {"present": True, "installed": True, "error": f"could not be read ({type(exc).__name__})"}

    facts["shadow"] = guarded(lambda: collect_shadow(shadow_dir, day, now))
    facts["news"] = guarded(lambda: collect_news(news_dir, shadow_dir, day, now, monthly_cap_usd=news_cap_usd,
                                                 report_data=report_data))
    facts["fleet"] = dict(fleet)
    facts["changelog"] = guarded(lambda: collect_changelog(changelog_dir, now))
    facts["attention"] = [a.to_dict() for a in attention_items(facts)]
    return facts


# -- rendering -----------------------------------------------------------------------------


def _n(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "?"


def _pct(value: Optional[float], signed: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%" if signed else f"{value:.1f}%"


def _ret(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100.0 * value:+.1f}%"


def _hhmm(value: Any) -> str:
    ts = _parse_ts(value)
    return "?" if ts is None else ts.astimezone(timezone.utc).strftime("%H:%M UTC")


def _dm(value: Any) -> str:
    ts = _parse_ts(value)
    return "?" if ts is None else ts.astimezone(timezone.utc).strftime("%d %b %H:%M UTC")


def _header(facts: Mapping[str, Any]) -> str:
    now = _parse_ts(facts.get("generated_at")) or datetime.now(tz=timezone.utc)
    local = ""
    try:
        from zoneinfo import ZoneInfo

        local = f", {now.astimezone(ZoneInfo(BEIRUT)).strftime('%H:%M')} Beirut"
    except Exception:  # no time-zone database on this machine: UTC only
        local = ""
    day = date.fromisoformat(str(facts.get("day")))
    return (f"AI trading system - daily digest, {now:%a %d %b %Y} ({now:%H:%M} UTC{local}). "
            f"\"Yesterday\" below is {day:%d %b} (UTC).")


def _shadow_lines(sh: Mapping[str, Any]) -> List[str]:
    if not sh.get("present"):
        return [f"Not found here ({sh.get('dir')}): the shadow runs on the VPS."]
    if sh.get("error"):
        return [f"The shadow's files {sh['error']}."]
    out: List[str] = []
    hb = sh.get("heartbeat") or {}
    day = sh.get("day") or {}
    if hb.get("found"):
        if hb.get("flat_at_lot") is True:
            pos = "flat"
        elif hb.get("flat_at_lot") is False:
            pos = f"OPEN, {hb.get('position')}"
        else:
            pos = hb.get("position") or "unknown"
        kill = "off" if not hb.get("kill") else f"ON ({hb.get('kill_owner') or 'not engaged by the shadow'})"
        candle = (f"last {day.get('timeframe') or ''} candle closed {_hhmm(hb.get('last_candle_close'))}".replace("  ", " ")
                  if hb.get("last_candle_close") else "no candle since the last restart yet")
        continuity = " Entries paused by the market-continuity check." if hb.get("market_continuity_ok") is False else ""
        out.append(f"Now: {hb.get('state')} (heartbeat {_fmt_minutes(hb.get('age_minutes'))} ago). Position: {pos}. "
                   f"Kill switch {kill}. {candle[0].upper() + candle[1:]}.{continuity} Restarts in the last hour: "
                   f"{hb.get('restarts_in_window') if hb.get('restarts_in_window') is not None else '?'}. "
                   f"Today so far: entries {hb.get('entries_today') if hb.get('entries_today') is not None else '?'}, "
                   f"result {hb.get('day_pnl') or 'n/a'} USDT (marked to market).")
    elif hb.get("error"):
        out.append(f"Now: the heartbeat file is {hb['error']}.")
    else:
        out.append("Now: no heartbeat file.")
    if not day.get("found"):
        out.append("Yesterday: no journal.")
        return out
    if day.get("lines") is None:
        out.append(f"Yesterday: the journal {day.get('error') or 'could not be read'}.")
        return out
    s = day.get("signals") or {}
    d = day.get("decisions") or {}
    f = day.get("fills") or {}
    r = day.get("reconciliations") or {}
    h = day.get("health") or {}
    blocked = day.get("blocked_reasons") or {}
    of = f" of {day['expected_candles']}" if day.get("expected_candles") is not None else ""
    so_far = " so far (the day is not over)" if day.get("partial_day") else ""
    parts = [f"{_n(day.get('candles'))}{of} candles{so_far}",
             f"LONG signals {_n(s.get('long'))} ({_n(s.get('cleared'))} cleared the confidence floor, "
             f"{_n(s.get('below_floor'))} below it), FLAT {_n(s.get('flat'))}, HOLD {_n(s.get('hold'))}"]
    entries = f"entries allowed {_n(d.get('entry_allowed', 0))}, blocked {_n(d.get('entry_blocked', 0))}"
    if blocked:
        entries += " (" + ", ".join(f"{k} {v}" for k, v in list(blocked.items())[:3]) + ")"
    parts.append(entries)
    if d.get("exit_allowed") or d.get("exit_blocked"):
        parts.append(f"exits allowed {_n(d.get('exit_allowed', 0))}, blocked {_n(d.get('exit_blocked', 0))}")
    if f.get("count"):
        fees = ", ".join(f"{v} {k}" for k, v in (f.get("fees") or {}).items()) or "none"
        parts.append(f"fills {_n(f['count'])} ({_n(f.get('buys'))} buy, {_n(f.get('sells'))} sell), fees {fees}, "
                     f"cash result {f.get('cash_result') if f.get('cash_result') is not None else 'n/a'} {f.get('quote') or ''}".rstrip())
    else:
        parts.append("no fills")
    if r.get("count"):
        parts.append(f"reconciliations {_n(r['count'])}"
                     + (", all consistent" if not r.get("inconsistent") else f", {_n(r['inconsistent'])} INCONSISTENT"))
    else:
        parts.append("no reconciliation recorded")
    if h.get("samples"):
        parts.append(f"while it ran, the private connection was authenticated {_pct(h.get('ws_auth_pct'))} and the market "
                     f"feed usable {_pct(h.get('feed_usable_pct'))} of the time")
    if (day.get("stops") or {}).get("evaluations"):
        parts.append(f"stop checks {_n(day['stops']['evaluations'])} (breaches {_n(day['stops'].get('breaches'))})")
    sup = {k: v for k, v in (day.get("supervisor") or {}).items()
           if k in ("start", "restart", "halt", "alert", "readiness_alert", "cap_breach", "operator_stop", "rearm_refused",
                    "kill_switch_release_attempt", "meta_fetch_failed", "supervise_tick_error")}
    if sup:
        parts.append("supervisor events: " + ", ".join(f"{k} {v}" for k, v in sup.items()))
    warnings = day.get("runtime_warnings") or {}
    if warnings:
        parts.append("runtime warnings: " + ", ".join(f"{k} {v}" for k, v in list(warnings.items())[:5]))
    if day.get("unparseable"):
        parts.append(f"{_n(day['unparseable'])} unreadable journal line(s) skipped")
    prefix = f"Yesterday (INCOMPLETE: the journal {day['error']})" if day.get("error") else "Yesterday"
    out.append(f"{prefix}: " + "; ".join(parts) + ".")
    return out


def _news_lines(news: Mapping[str, Any]) -> List[str]:
    if not news.get("installed"):
        return ["Not installed here yet (plan row G5: it starts with a capped AI key, docs/runbooks/NEWS_SHADOW.md)."]
    if news.get("error"):
        return [f"The news shadow's files {news['error']}."]
    out: List[str] = []
    st = news.get("state") or {}
    sp = news.get("spend") or {}
    if st.get("found"):
        healthy = {True: "healthy", False: "UNHEALTHY", None: "health unknown"}[st.get("last_cycle_healthy")]
        live = st.get("live_events") or []
        live_text = "no live events" if not live else f"{len(live)} live event(s): " + "; ".join(
            f"{e['category']} {e['action']} until {_dm(e['expires_at'])}" for e in live[:3])
        out.append(f"Now: last cycle {_fmt_minutes(st.get('age_minutes'))} ago, {healthy}; {live_text}.")
    else:
        out.append(f"Now: no saved state{' (' + st['error'] + ')' if st.get('error') else ''}.")
    if sp.get("spent_usd") is not None or sp.get("previous_month"):
        cap = f" of the ${sp['cap_usd']:.2f} cap" if sp.get("cap_usd") else ""
        spent = f"${sp['spent_usd']:.2f}{cap}" if sp.get("spent_usd") is not None else "nothing yet"
        prev = sp.get("previous_month") or {}
        closed = (f"; {prev['month']} closed at ${prev['spent_usd']:.2f}" if prev.get("spent_usd") is not None else "")
        out.append(f"AI spend {sp['month']}: {spent}{closed} (yesterday ${float(sp.get('yesterday_usd') or 0.0):.2f}).")
    day = news.get("day") or {}
    h = day.get("headline") or {}
    if day.get("error"):
        out.append(f"Yesterday: {day['error']}.")
    elif not h.get("cycles"):
        out.append("Yesterday: it did not run.")
    else:
        healthy = "n/a" if h.get("healthy_pct") is None else f"{h['healthy_pct']}%"
        text = (f"Yesterday: {_n(h.get('cycles'))} cycles, news state healthy {healthy} of the time; "
                f"{_n(h.get('items'))} new articles ({_n(h.get('quarantined'))} set aside as suspicious); "
                f"AI looked at {_n(h.get('triage_calls'))} headlines and {_n(h.get('classify_calls'))} stories "
                f"(about ${float(h.get('cost_usd') or 0.0):.2f}); events {_n(h.get('events'))} "
                f"({_n(h.get('corroborated_events'))} confirmed, {_n(h.get('events_with_effect'))} with an effect)")
        if h.get("decisions"):
            text += (f"; Phase 6a new-long decisions {_n(h['decisions'])}: the news layer would have blocked "
                     f"{_n(h.get('would_block'))} and reduced {_n(h.get('would_reduce'))}")
        text += "; safety checks " + ("all passed." if h.get("invariants_ok") else "FAILED.")
        out.append(text)
        if day.get("model_enabled") is False:
            out.append("The AI was switched off (--no-model): news was collected but not classified.")
        for a in day.get("anomalies") or []:
            out.append(f"Note: {a}.")
    return out


def _fleet_lines(fleet: Mapping[str, Any]) -> List[str]:
    if not fleet.get("installed"):
        return ["Not running here (plan row G6, docs/runbooks/PAPER_FLEET.md)."]
    if fleet.get("error"):
        return [f"{fleet['error']}."]
    if not fleet.get("found"):
        return ["No fleet in its folder yet."]
    days = fleet.get("days_running")
    early = (f" (too early to judge: verdicts start at day {fleet.get('min_days_for_verdict', 30):.0f})"
             if fleet.get("too_early") else "")
    prices = "STALE" if fleet.get("data_stale") else "fresh"
    out = [f"Now: last cycle {_fmt_minutes(fleet.get('last_cycle_age_minutes'))} ago, public prices {prices}. "
           f"Day {0 if days is None else int(days) + 1} of the forward record{early}. {_n(fleet.get('accounts'))} accounts, "
           f"{_n(fleet.get('in_position'))} holding a position."]
    parts = []
    if fleet.get("best") and fleet.get("worst"):
        b, w = fleet["best"], fleet["worst"]
        if b["id"] == w["id"]:
            parts.append(f"{b['id']} {_ret(b.get('return'))}")
        else:
            parts.append(f"best {b['id']} {_ret(b.get('return'))}, worst {w['id']} {_ret(w.get('return'))}")
    for item in fleet.get("confirmed") or []:
        a, c = item.get("account") or {}, item.get("control")
        text = f"holdout-confirmed {a.get('id')} {_ret(a.get('return'))}"
        if c:
            text += f" (its always-long control {c.get('id')} {_ret(c.get('return'))})"
        parts.append(text)
    alloc = fleet.get("allocator")
    if alloc:
        state = (f"in cash for {alloc['cooldown_days_left']} more day(s) after a weekly loss-limit trip"
                 if alloc.get("cooldown_days_left") else "armed")
        parts.append(f"allocator v2 {alloc['id']} {_ret(alloc.get('return'))}, {state}, {alloc.get('loss_limit_trips', 0)} trip(s)")
    if parts:
        out.append("Since start: " + "; ".join(parts) + ".")
    verdicts = fleet.get("verdicts") or {}
    if verdicts and not fleet.get("too_early"):
        out.append("Against the backtest (weekly report): " + ", ".join(f"{v} {k}" for k, v in sorted(verdicts.items())) + ".")
    if fleet.get("verdicts_error"):
        out.append(f"Note: {fleet['verdicts_error']}.")
    for w in fleet.get("warnings") or []:
        out.append(f"Note: {w}")
    return out


def _changelog_lines(cl: Mapping[str, Any]) -> List[str]:
    if not cl.get("installed"):
        return ["The watcher has not run here yet (docs/runbooks/OPS_DIGEST.md)."]
    if cl.get("error"):
        return [f"Its state {cl['error']}."]
    status = "ok" if not cl.get("last_error") else f"FAILED ({cl['last_error']}, {cl.get('consecutive_failures', 0)} in a row)"
    out = [f"Last check {_dm(cl.get('last_check_at'))}: {status}; {_n(cl.get('entries_known'))} entries known."]
    recent = cl.get("flagged_recent") or []
    if not recent:
        out.append(f"No new or edited entry in the last {cl.get('days', 7)} days mentions what this system uses.")
    else:
        out.append(f"Flagged in the last {cl.get('days', 7)} days:")
        for r in recent[-5:]:
            when = r.get("date") or "undated"
            out.append(f"- [{when}, {r.get('change')}] {_clean(r.get('title'), 120)}: "
                       + "; ".join(str(m) for m in (r.get("matches") or [])[:4]) + f" {r.get('url') or ''}".rstrip())
    if cl.get("pending"):
        out.append(f"Not delivered yet (retried with the next checks): {len(cl['pending'])} alert(s).")
    return out


def render(facts: Mapping[str, Any], *, ai_summary: Optional[str] = None, ai_note: Optional[str] = None) -> str:
    """The digest text (plain text: Telegram shows it exactly as written).

    The fixed NEEDS ATTENTION list always comes first; an AI summary, when there is one, follows it."""
    lines = [_header(facts), "Demo and simulation only. This digest only reads files; it changed nothing.", ""]
    attention = facts.get("attention") or []
    lines.append("NEEDS ATTENTION")
    if attention:
        lines += [f"- {a['level']}: {a['text']}" for a in attention]
    else:
        lines.append("Nothing needs your attention.")
    if ai_summary:
        lines += ["", "AI SUMMARY (Claude; it can be wrong, the facts decide)", ai_summary]
    sh = facts.get("shadow") or {}
    inst = (sh.get("day") or {}).get("instrument")
    tf = (sh.get("day") or {}).get("timeframe")
    lines += ["", "PHASE 6A SHADOW (demo money" + (f", {inst} {tf}" if inst and tf else "") + ")"]
    lines += _shadow_lines(sh)
    lines += ["", "NEWS SHADOW (log-only: it never changes a trade)"]
    lines += _news_lines(facts.get("news") or {})
    lines += ["", "PAPER FLEET (simulation: virtual money on public prices)"]
    lines += _fleet_lines(facts.get("fleet") or {})
    lines += ["", "OKX API CHANGELOG"]
    lines += _changelog_lines(facts.get("changelog") or {})
    reports = [p for p in ((facts.get("shadow") or {}).get("report"), (facts.get("news") or {}).get("report"),
                           (facts.get("fleet") or {}).get("latest_report")) if p]
    if reports:
        lines += ["", "Full reports: " + " | ".join(str(p) for p in reports)]
    if ai_note:
        lines += ["", f"({ai_note})"]
    return "\n".join(lines).strip() + "\n"


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> List[str]:
    """Pieces of at most ``limit`` characters, cut at line ends (a single over-long line is cut hard)."""
    if limit < 100:
        raise ValueError("limit too small")
    pieces: List[str] = []
    current = ""
    for line in text.splitlines():
        while len(line) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            pieces.append(current)
            current = line
        else:
            current = candidate
    if current.strip():
        pieces.append(current)
    pieces = [p for p in pieces if p.strip()]
    if len(pieces) > 1:  # a "(1/2) " prefix: TELEGRAM_LIMIT leaves room for it under Telegram's 4096
        pieces = [f"({i}/{len(pieces)}) {p}" for i, p in enumerate(pieces, 1)]
    return pieces


def numbers_in(text: str) -> List[str]:
    """Every number written in ``text`` with its sign, normalized: "2,880" -> "2880", "0.60" -> "0.6",
    "03" -> "3", "-12.0%" -> "-12", "+1.2%" -> "1.2". A hyphen inside a date or a name ("2026-10-21",
    "S1+S5") is not a sign. The AI check compares these exactly, so "12" does not vouch for "-12.0"."""
    out = []
    for m in _NUMBER.finditer(text or ""):
        sign, raw = (m.group(1), m.group(2)) if m.group(2) is not None else ("", m.group(3))
        value = _dec(raw.replace(",", ""))
        if value is None:
            continue
        norm = format(value.normalize(), "f")
        if "." in norm:
            norm = norm.rstrip("0").rstrip(".")
        norm = norm or "0"
        out.append(f"-{norm}" if sign in ("-", "−") and norm != "0" else norm)
    return out


# -- output files --------------------------------------------------------------------------


def write_outputs(out_dir: Path, facts: Mapping[str, Any], text: str) -> Tuple[Path, Path]:
    """``digest-YYYY-MM-DD.md`` and ``.json`` next to each other (atomic replace)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"digest-{facts['day']}"
    md, js = out_dir / f"{stem}.md", out_dir / f"{stem}.json"
    for path, body in ((md, text), (js, json.dumps(facts, indent=1, sort_keys=True, default=str) + "\n")):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
    return md, js


def append_run_log(out_dir: Path, record: Mapping[str, Any]) -> None:
    path = Path(out_dir) / "digest.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")


@dataclass(frozen=True)
class SendResult:
    status: str  # "sent" | "dry-run" | "missing-credentials" | "failed"
    parts: int
    error: Optional[str] = None


def send_text(text: str, notifier: Any, *, limit: int = TELEGRAM_LIMIT) -> SendResult:
    """Send ``text`` in pieces through the existing Telegram notifier (it honours TELEGRAM_DRY_RUN)."""
    pieces = split_message(text, limit)
    statuses = []
    for piece in pieces:
        result = notifier.send(piece)
        if result.skipped == "missing-credentials":
            return SendResult("missing-credentials", len(pieces))
        if not result.ok:
            return SendResult("failed", len(pieces), result.error or f"HTTP {result.status_code}")
        statuses.append(result.skipped or "sent")
    return SendResult("dry-run" if "dry-run" in statuses else "sent", len(pieces))
