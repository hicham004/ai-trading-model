"""Daily news-shadow report (PHASE6B_DESIGN sections 11 and 14) — offline, from logs only.

``logs/news_shadow/report-YYYY-MM-DD.md`` is rebuilt from that day's shadow logs
(``events-*.jsonl``, ``decisions-*.jsonl``; the day before for events still live
at midnight) and the Phase 6a journal snapshots (``journal-*.jsonl``, read-only,
for the price path after each decision). Nothing else is read — no network, no
database, no clock — so the same files always give the same report.

The report describes counterfactual RISK effects only ("would have blocked",
"would have reduced") and never claims profitability. It also re-checks, from the
logs, the design's pass criteria that must hold every day (section 11): no
single-source or expired event with an effect, nothing evaluated that is not a
new-long decision in the Phase 6a journal (exits never are), no size increase,
no double counting or compounding, no effect while the news state was unhealthy,
no baseline-blocked entry counted as a prevented trade, and no baseline taken as
allowed unless the journal holds the runtime's own "entry allowed".
"""

from __future__ import annotations

import bisect
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.news.decay import DEFAULT_POLICY, effective_signal
from app.news.evaluation import _INVALID, _NO_CALL  # the eval's own call classes (same package)
from app.news.phase6a import Phase6aJournal
from app.news.schema import ACTIVE_STATUSES, CorroborationStatus, NewsEvent

REPORT_VERSION = "news-shadow-report-v1"
PRICE_PATH_HOURS = 6
LARGE_MOVE_PCT = -2.0  # an hourly close-to-close drop at least this large is listed for review
DEFAULT_STALE_AFTER_SECONDS = 900.0
TOP_N = 5


# -- reading --------------------------------------------------------------------------------


def _read_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    """Every JSON object line of ``path``; a broken line (also one cut inside a
    multi-byte character, e.g. after a crash or a full disk) is counted and skipped."""
    records: List[Dict[str, Any]] = []
    bad = 0
    if not path.exists():
        return records, bad
    for raw in path.read_bytes().splitlines():
        if not raw.strip():
            continue
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            bad += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            bad += 1
    return records, bad


def _ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dec(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _day_bounds(day: date) -> Tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _call_class(record: Mapping[str, Any]) -> str:
    """valid | invalid | refusal | truncated | no_call | infra (the eval's classes, for log records)."""
    if record.get("ok"):
        return "valid"
    failure = str(record.get("failure") or "")
    if failure in _NO_CALL:
        return "no_call"
    if failure == "refusal":
        return "refusal"
    if failure == "max_tokens":
        return "truncated"
    if failure in _INVALID:
        return "invalid"
    return "infra"


# -- events reconstructed from the logs -------------------------------------------------------


class LoggedEvents:
    """Every event version found in the logs, with the time it became known (as the runner saw it)."""

    def __init__(self) -> None:
        self._versions: Dict[str, List[Tuple[datetime, NewsEvent]]] = defaultdict(list)
        self.invalid = 0

    def add(self, record: Mapping[str, Any]) -> None:
        raw = record.get("event")
        known = _ts(record.get("known_at")) or _ts(record.get("ts"))
        if not isinstance(raw, Mapping) or known is None:
            return
        try:
            event = NewsEvent.model_validate(raw)
        except ValueError:
            self.invalid += 1
            return
        self._versions[event.event_id].append((known, event))

    def ids(self) -> List[str]:
        return sorted(self._versions)

    def latest(self, event_id: str) -> Optional[NewsEvent]:
        versions = self._versions.get(event_id)
        return max(versions, key=lambda v: v[0])[1] if versions else None

    def as_of(self, when: datetime) -> List[NewsEvent]:
        out = []
        for versions in self._versions.values():
            known = [v for v in versions if v[0] <= when]
            if known:
                out.append(max(known, key=lambda v: v[0])[1])
        return out

    def first_known(self, event_id: str) -> Optional[datetime]:
        versions = self._versions.get(event_id)
        return min(v[0] for v in versions) if versions else None

    def strongest_effect(self, event_id: str, start: datetime, end: datetime) -> Tuple[str, float]:
        """The strongest effect the event had between ``start`` and ``end``, from its versions.

        Within one version the effect only fades, so its strongest moment is when the
        version became known (or ``start``, if it was already known then). This also
        covers an event that was live at midnight without a new signal record that day.
        """
        rank = {"NO_EFFECT": 0, "REDUCE_SIZE": 1, "BLOCK_NEW_LONGS": 2}
        best = ("NO_EFFECT", 0.0)
        ordered = sorted(self._versions.get(event_id, []), key=lambda v: v[0])
        for i, (known, event) in enumerate(ordered):
            until = ordered[i + 1][0] if i + 1 < len(ordered) else end
            at = max(known, start)
            if at >= min(until, end):
                continue
            signal = effective_signal(event, at, DEFAULT_POLICY)
            candidate = (signal.action.value, float(signal.effective_severity))
            if (rank[candidate[0]], candidate[1]) > (rank[best[0]], best[1]):
                best = candidate
        return best


# -- the report data ------------------------------------------------------------------------------


def _price_path(candles: Sequence[Any], after: datetime, hours: int) -> Optional[Dict[str, Any]]:
    """Path of the hours after ``after`` (a candle close): reference close, return, max drop and max rise."""
    before = [c for c in candles if c.close_time <= after]
    later = [c for c in candles if c.open_time >= after and c.open_time < after + timedelta(hours=hours)]
    if not before or not later or before[-1].close <= 0:
        return None
    ref = before[-1].close
    return {
        "reference_close": ref,
        "hours_available": len(later),
        "return_pct": round((later[-1].close / ref - 1) * 100, 3),
        "max_drop_pct": round((min(c.low for c in later) / ref - 1) * 100, 3),
        "max_rise_pct": round((max(c.high for c in later) / ref - 1) * 100, 3),
    }


def _unhealthy_minutes(
    cycles: Sequence[Mapping[str, Any]], start: datetime, end: datetime, stale_after: float
) -> Tuple[float, float]:
    """(minutes observed, minutes without a healthy cycle in the previous ``stale_after`` seconds)."""
    healthy = sorted(t for t in (_ts(c.get("finished_at")) for c in cycles if c.get("healthy")) if t is not None)
    finished = sorted(t for t in (_ts(c.get("finished_at")) for c in cycles) if t is not None)
    if not finished:
        return 0.0, 0.0
    first, last = max(start, finished[0]), min(end, finished[-1])
    if last <= first:
        return 0.0, 0.0
    window = timedelta(seconds=stale_after)
    total = bad = 0
    t = first
    while t < last:
        i = bisect.bisect_right(healthy, t)
        if i == 0 or t - healthy[i - 1] > window:
            bad += 1
        total += 1
        t += timedelta(minutes=1)
    return float(total), float(bad)


def build_report_data(log_dir: Path, journal_dir: Optional[Path], day: date) -> Dict[str, Any]:
    """Every number of one day's report, from the logs (and journal) alone."""
    log_dir = Path(log_dir)
    start, end = _day_bounds(day)
    prev = day - timedelta(days=1)
    events_today, bad_e = _read_jsonl(log_dir / f"events-{day.isoformat()}.jsonl")
    events_prev, bad_p = _read_jsonl(log_dir / f"events-{prev.isoformat()}.jsonl")
    decisions, bad_d = _read_jsonl(log_dir / f"decisions-{day.isoformat()}.jsonl")
    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in events_today:
        by_kind[str(record.get("kind"))].append(record)

    logged = LoggedEvents()
    for record in events_prev + events_today:
        if record.get("kind") in ("event_candidate_created", "event_deduplicated"):
            logged.add(record)

    # -- runner, versions and health
    cycles = sorted(by_kind["cycle_summary"], key=lambda c: str(c.get("finished_at") or c.get("ts")))
    runner_events = by_kind["runner_event"]
    starts = [r for r in runner_events if r.get("event") == "start"]
    stale_after = DEFAULT_STALE_AFTER_SECONDS
    for r in starts:
        settings = r.get("settings") or {}
        if isinstance(settings, Mapping) and settings.get("stale_after_seconds"):
            stale_after = float(settings["stale_after_seconds"])
    observed_min, unhealthy_min = _unhealthy_minutes(cycles, start, end, stale_after)
    fingerprints = sorted({str(c.get("config_fingerprint")) for c in cycles if c.get("config_fingerprint")})
    as_of = max((r.get("ts") for r in events_today + decisions if r.get("ts")), default=None)
    errors = Counter(e.split(":", 1)[0] for c in cycles for e in (c.get("errors") or []))
    skews = [abs(float(c["clock_skew_seconds"])) for c in cycles if isinstance(c.get("clock_skew_seconds"), (int, float))]
    runner = {
        "starts": len(starts),
        "stops": sum(1 for r in runner_events if r.get("event") == "stop"),
        "cycles": len(cycles),
        "healthy_cycles": sum(1 for c in cycles if c.get("healthy")),
        "observed_minutes": observed_min,
        "unhealthy_minutes": unhealthy_min,
        "unhealthy_reasons": dict(Counter(r for c in cycles for r in (c.get("unhealthy_reasons") or []))),
        "stage_errors": dict(errors),
        "state_resets": sum(1 for r in runner_events if r.get("event") == "state_reset"),
        "clock_skew_events": sum(1 for r in runner_events if r.get("event") == "clock_skew"),
        "max_abs_clock_skew_seconds": max(skews) if skews else None,
        "spend_cap_reached": sum(1 for r in runner_events if r.get("event") == "spend_cap_reached"),
        "model_enabled": any(c.get("model_enabled") for c in cycles) if cycles else None,
        "fingerprints": fingerprints,
        "unparseable_lines": bad_e + bad_p + bad_d,
    }
    versions = {}
    if starts:
        last = starts[-1]
        versions = {
            "runner_version": last.get("runner_version"),
            "prompt_version": last.get("prompt_version"),
            "classifier_prompt_sha256": last.get("classifier_prompt_sha256"),
            "triage_prompt_sha256": last.get("triage_prompt_sha256"),
            "models": last.get("models"),
            "decay_policy": last.get("decay_policy"),
            "schema_version": last.get("schema_version"),
            "overlay_version": last.get("overlay_version"),
            "sources": last.get("sources"),
        }

    # -- sources and items
    fetches = sorted(by_kind["source_fetch"], key=lambda f: (str(f.get("source_id")), str(f.get("fetched_at"))))
    sources: Dict[str, Dict[str, Any]] = {}
    by_source_fetches: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in fetches:
        by_source_fetches[str(f.get("source_id"))].append(f)
    for source_id, rows in sorted(by_source_fetches.items()):
        times = [_ts(r.get("fetched_at")) for r in rows]
        gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:]) if a and b]
        typical = statistics.median(gaps) if gaps else 5.0
        outage = 0.0
        for i, r in enumerate(rows):
            if r.get("status") in ("ok", "skipped"):
                continue
            gap = gaps[i] if i < len(gaps) else typical
            outage += min(gap, 30.0)
        sources[source_id] = {
            "attempts": len(rows),
            "ok": sum(1 for r in rows if r.get("status") == "ok"),
            "failed": sum(1 for r in rows if r.get("status") not in ("ok", "skipped")),
            "skipped": sum(1 for r in rows if r.get("status") == "skipped"),
            "items": sum(int(r.get("items") or 0) for r in rows),
            "outage_minutes": round(outage, 1),
            "last_error": next((str(r.get("error"))[:120] for r in reversed(rows) if r.get("error")), ""),
        }
    observed = by_kind["source_item_observed"]
    triage_status = Counter(str((o.get("triage") or {}).get("status")) for o in observed)
    by_category: Counter = Counter()
    for o in observed:
        t = o.get("triage") or {}
        if t.get("relevant") and t.get("category"):
            by_category[str(t["category"])] += 1
        elif t.get("status") in ("called", "reused"):
            by_category["not a watchlist item"] += 1
        else:
            by_category[f"not triaged ({t.get('status')})"] += 1
    flags = Counter(f for s in by_kind["source_item_sanitized"] for f in (s.get("sanitization_flags") or []))
    items = {
        "observed": len(observed),
        "quarantined": sum(1 for o in observed if o.get("quarantined")),
        "by_source": dict(Counter(str(o.get("source_id")) for o in observed)),
        "by_category": dict(by_category),
        "triage_status": dict(triage_status),
    }

    # -- classifier calls and spend
    calls = by_kind["classifier_output"] + by_kind["classifier_rejected"] + by_kind["classifier_unavailable"]
    stages: Dict[str, Dict[str, Any]] = {}
    for stage in ("triage", "classify"):
        rows = [c for c in calls if c.get("stage") == stage]
        classes = Counter(_call_class(c) for c in rows)
        answered = classes["valid"] + classes["invalid"]
        tokens: Counter = Counter()
        for c in rows:
            for k, v in (c.get("usage") or {}).items():
                if isinstance(v, int):
                    tokens[k] += v
        stages[stage] = {
            "calls": len(rows),
            "classes": dict(classes),
            "schema_validity": (classes["valid"] / answered) if answered else None,
            "failures": dict(Counter(str(c.get("failure")) for c in rows if not c.get("ok"))),
            "prohibited_actions": sum(1 for c in rows if c.get("failure") == "prohibited_action"),
            "cost_usd": round(sum(float(c.get("cost_usd") or 0.0) for c in rows), 6),
            "tokens": dict(tokens),
            "latency_ms_median": statistics.median([c["latency_ms"] for c in rows if isinstance(c.get("latency_ms"), int)])
            if any(isinstance(c.get("latency_ms"), int) for c in rows)
            else None,
        }
    spend = next((c.get("spend") for c in reversed(cycles) if c.get("spend")), None)

    # -- events, corroboration and effective signals
    created = [r for r in by_kind["event_candidate_created"] if r.get("event")]
    merged = [r for r in by_kind["event_deduplicated"] if r.get("event")]
    copies = [r for r in by_kind["event_deduplicated"] if not r.get("event")]
    skipped = Counter(
        str(reason).split(":", 1)[0]
        for r in by_kind["event_candidate_created"]
        if not r.get("event")
        for reason in (r.get("reasons") or [])
    )
    corroboration_status = Counter(str((r.get("corroboration") or {}).get("status")) for r in by_kind["corroboration_update"])
    touched = sorted({str(r.get("event_id") or (r.get("event") or {}).get("event_id")) for r in created + merged})
    event_rows = []
    signals = [s for s in by_kind["effective_signal"] if s.get("scope") == "event"]
    window_end = min(end, _ts(as_of)) if _ts(as_of) is not None else end
    live_ids = set(touched)
    for event_id in logged.ids():
        event = logged.latest(event_id)
        if event is not None and event.first_seen_at < end and event.expires_at > start:
            live_ids.add(event_id)
    for event_id in sorted(live_ids):
        event = logged.latest(event_id)
        if event is None:
            continue
        strongest = logged.strongest_effect(event_id, start, window_end)
        event_rows.append(
            {
                "event_id": event_id,
                "category": event.category.value,
                "status": event.corroboration_status.value,
                "classified_action": event.action.value,
                "strongest_effect": strongest[0],
                "max_severity": round(strongest[1], 3),
                "sources": event.source_quality.independent_source_count,
                "tier": event.source_quality.tier.value,
                "first_seen_at": event.first_seen_at.isoformat(),
                "expires_at": event.expires_at.isoformat(),
                "summary": event.raw_summary,
            }
        )
    by_cat: Dict[str, Counter] = defaultdict(Counter)
    for row in event_rows:
        c = by_cat[row["category"]]
        c["events"] += 1
        c["corroborated"] += row["status"] in {s.value for s in ACTIVE_STATUSES}
        c["single_source"] += row["status"] == CorroborationStatus.SINGLE_SOURCE.value
        c["with_effect"] += row["strongest_effect"] != "NO_EFFECT"
    single_source_vetoes = sum(
        1
        for r in created + merged
        if r.get("proposed_action") not in (None, "NO_EFFECT")
        and (r.get("event") or {}).get("corroboration_status") == CorroborationStatus.SINGLE_SOURCE.value
    )
    expired_today = sum(1 for row in event_rows if start <= datetime.fromisoformat(row["expires_at"]) <= window_end)
    # Dedup compression (design 11): articles folded into each event today.
    article_ids = {str(i) for r in created + merged + copies for i in (r.get("story_item_ids") or [])}
    event_ids_today = {str(r.get("event_id")) for r in created + merged + copies if r.get("event_id")}
    # Latencies (design 11): first publication -> first article seen; first article seen -> event known.
    observed_by_id = {str(o.get("item_id")): o for o in events_prev + events_today if o.get("kind") == "source_item_observed"}
    detection, signal_lag = [], []
    for r in created:
        event = r.get("event") or {}
        seen = _ts(event.get("first_seen_at"))
        known = _ts(r.get("known_at"))
        published = [
            _ts(observed_by_id[i].get("published_at")) for i in (r.get("story_item_ids") or []) if i in observed_by_id
        ]
        published = [p for p in published if p is not None and seen is not None and p <= seen]
        if seen is not None and published:
            detection.append((seen - min(published)).total_seconds() / 60)
        if seen is not None and known is not None:
            signal_lag.append((known - seen).total_seconds() / 60)

    # -- the shadow overlay on Phase 6a candidates, with the later price path
    journal = None
    if journal_dir is not None and Path(journal_dir).is_dir():
        journal = Phase6aJournal(Path(journal_dir))
        journal.refresh([prev, day, day + timedelta(days=1)])
    overlay_rows = []
    baseline_counts: Counter = Counter()
    for d in sorted(decisions, key=lambda r: str(r.get("decision_time"))):
        if d.get("kind") != "shadow_entry_overlay":
            continue
        baseline = d.get("baseline") or {}
        baseline_counts[f"{baseline.get('source', '?')}:{d.get('baseline_reason')}"] += 1
        path = None
        if journal is not None:
            close = _ts(d.get("candle_close"))
            if close is not None:
                path = _price_path(journal.candles(str(d.get("instrument"))), close, PRICE_PATH_HOURS)
        overlay_rows.append({**d, "price_path": path})
    would_block = [r for r in overlay_rows if r.get("would_have_blocked_here")]
    would_reduce = [r for r in overlay_rows if r.get("would_have_reduced_here")]
    acted = would_block + would_reduce

    def mean(values: Iterable[Optional[float]]) -> Optional[float]:
        vals = [v for v in values if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    overlay = {
        "decisions": len(overlay_rows),
        "baseline_allowed": sum(1 for r in overlay_rows if r.get("baseline_allowed")),
        "would_block": len(would_block),
        "would_reduce": len(would_reduce),
        "no_effect": len(overlay_rows) - len(acted),
        "news_also_active_on_blocked_baseline": sum(
            1 for r in overlay_rows if not r.get("baseline_allowed") and r.get("action") != "NO_EFFECT"
        ),
        "baseline": dict(baseline_counts),
        "after_acted": {
            "with_path": sum(1 for r in acted if r.get("price_path")),
            "adverse_6h": sum(1 for r in acted if r.get("price_path") and r["price_path"]["return_pct"] < 0),
            "favorable_6h": sum(1 for r in acted if r.get("price_path") and r["price_path"]["return_pct"] > 0),
            "mean_max_drop_pct": mean(r["price_path"]["max_drop_pct"] for r in acted if r.get("price_path")),
            "mean_max_rise_pct": mean(r["price_path"]["max_rise_pct"] for r in acted if r.get("price_path")),
        },
    }

    # -- review lists (manual review, not metrics)
    missed = sorted(
        (
            {
                "event_id": (r.get("event") or {}).get("event_id"),
                "category": (r.get("event") or {}).get("category"),
                "status": (r.get("event") or {}).get("corroboration_status"),
                "proposed": r.get("proposed_action"),
                "base_score": float(r.get("base_score") or 0.0),
                "reasons": r.get("reasons") or [],
                "summary": (r.get("event") or {}).get("raw_summary"),
            }
            for r in created + merged
            if r.get("proposed_action") not in (None, "NO_EFFECT") and (r.get("event") or {}).get("action") == "NO_EFFECT"
        ),
        key=lambda m: (-m["base_score"], str(m["event_id"])),
    )[:TOP_N]
    large_moves = []
    if journal is not None:
        for inst in sorted({str(r.get("instrument")) for r in overlay_rows} | {"BTC-USDT"}):
            series = journal.candles(inst)
            for prev_c, cur in zip(series, series[1:]):
                if not start <= cur.close_time <= end or prev_c.close <= 0:
                    continue
                move = (cur.close / prev_c.close - 1) * 100
                if move > LARGE_MOVE_PCT:
                    continue
                active = [
                    e for e in logged.as_of(cur.close_time)
                    if inst in e.asset_impact.instruments and effective_signal(e, cur.close_time, DEFAULT_POLICY).action.value != "NO_EFFECT"
                ]
                if not active:
                    large_moves.append({"instrument": inst, "candle_close": cur.close_time.isoformat(), "move_pct": round(move, 3)})
    false_blocks = sorted(
        (
            {
                "decision_time": r.get("decision_time"),
                "instrument": r.get("instrument"),
                "action": r.get("action"),
                "event_id": r.get("event_id"),
                "return_pct": r["price_path"]["return_pct"],
                "max_drop_pct": r["price_path"]["max_drop_pct"],
            }
            for r in acted
            if r.get("price_path") and r["price_path"]["return_pct"] > 0
        ),
        key=lambda f: -f["return_pct"],
    )[:TOP_N]

    # -- the daily invariants (design 11 pass criteria that must hold every day)
    def bad_signal_status(s: Mapping[str, Any]) -> bool:
        return s.get("action") != "NO_EFFECT" and s.get("status") not in {x.value for x in ACTIVE_STATUSES}

    def expired_effect(s: Mapping[str, Any]) -> bool:
        at, expires = _ts(s.get("at")), _ts(s.get("expires_at"))
        return s.get("action") != "NO_EFFECT" and at is not None and expires is not None and at >= expires

    def over_one(value: Any) -> bool:
        number = _dec(value)
        return number is not None and number > 1

    def double_counted(r: Mapping[str, Any]) -> bool:
        """The decision must be exactly its deciding event's own effect: never a sum of
        severities, never a product of reductions (design 7.6)."""
        if r.get("action") == "NO_EFFECT":
            return False
        deciding = [e for e in (r.get("events_at_decision") or []) if e.get("event_id") == r.get("event_id")]
        if len(deciding) != 1:
            return True
        e = deciding[0]
        return not (
            e.get("action") == r.get("action")
            and math.isclose(float(r.get("effective_severity") or 0.0), float(e.get("effective_severity") or 0.0), abs_tol=1e-6)
            and _dec(e.get("size_multiplier")) == _dec(r.get("size_multiplier"))
        )

    decision_expired = 0
    for r in overlay_rows:
        if r.get("action") == "NO_EFFECT" or not r.get("event_id"):
            continue
        event = logged.latest(str(r["event_id"]))
        at = _ts(r.get("decision_time"))
        if event is not None and at is not None and at >= event.expires_at:
            decision_expired += 1

    # Checked against the Phase 6a journal itself, not against fields the shadow derived:
    # every evaluated decision must be a journaled LONG signal or runtime entry decision,
    # and every baseline taken as allowed must be a runtime "entry allowed" in the journal.
    not_long: Optional[int]
    unconfirmed_allowed: Optional[int]
    if journal is not None:
        journal_candidates = {c.key: c for c in journal.candidates(datetime.max.replace(tzinfo=timezone.utc))}
        not_long = sum(1 for r in overlay_rows if str(r.get("candidate_key")) not in journal_candidates)
        unconfirmed_allowed = 0
        for r in overlay_rows:
            if not r.get("baseline_allowed"):
                continue
            c = journal_candidates.get(str(r.get("candidate_key")))
            if c is None or c.baseline is None or c.baseline.source != "runtime" or not c.baseline.allowed:
                unconfirmed_allowed += 1
    else:
        not_long = sum(
            1 for r in overlay_rows if not (r.get("journal_decision_intent") == "entry" or r.get("journal_signal_action") == "long")
        )
        unconfirmed_allowed = None  # cannot be checked without the journal
    invariants = [
        ("single-source or unconfirmed event with an effect", sum(1 for s in signals if bad_signal_status(s))),
        ("expired event with an effect", sum(1 for s in signals if expired_effect(s)) + decision_expired),
        ("decision without a journaled LONG signal or entry decision (exits are never evaluated)", not_long),
        ("size multiplier above 1", sum(1 for x in signals + overlay_rows if over_one(x.get("size_multiplier")))),
        ("severity double counted or reductions compounded", sum(1 for r in overlay_rows if double_counted(r))),
        ("effect while the news state was unhealthy", sum(1 for r in overlay_rows if not r.get("news_healthy") and r.get("action") != "NO_EFFECT")),
        (
            "baseline-blocked entry counted as prevented",
            sum(1 for r in overlay_rows if not r.get("baseline_allowed") and (r.get("would_have_blocked_here") or r.get("would_have_reduced_here"))),
        ),
        ("allowed baseline without a runtime 'entry allowed' in the journal", unconfirmed_allowed),
    ]

    anomalies = []
    if len(fingerprints) > 1:
        anomalies.append(f"the frozen configuration changed during the day ({', '.join(fingerprints)})")
    if runner["state_resets"]:
        anomalies.append(f"state reset {runner['state_resets']} time(s): events were forgotten")
    if runner["clock_skew_events"]:
        anomalies.append(f"clock skew above the limit in {runner['clock_skew_events']} cycle(s)")
    budget_skips = sum(
        int((c.get("triage") or {}).get("skipped_budget", 0)) + int((c.get("stories") or {}).get("skipped_budget", 0))
        for c in cycles
    )
    if runner["spend_cap_reached"] or budget_skips:
        anomalies.append(f"the spend cap held back {budget_skips} AI call(s) (headlines and stories)")
    if runner["unhealthy_minutes"]:
        anomalies.append(f"news state unhealthy for {runner['unhealthy_minutes']:.0f} of {runner['observed_minutes']:.0f} minutes")
    if runner["stage_errors"]:
        anomalies.append("stage errors: " + ", ".join(f"{k}={v}" for k, v in sorted(runner["stage_errors"].items())))
    for source_id, s in sources.items():
        if s["outage_minutes"] >= 60:
            anomalies.append(f"source {source_id} unavailable for about {s['outage_minutes']:.0f} minutes")
    if journal is None:
        anomalies.append("Phase 6a journal directory not found: no candidate entries could be evaluated")
    if runner["unparseable_lines"]:
        anomalies.append(f"{runner['unparseable_lines']} unparseable log line(s) skipped")
    if logged.invalid:
        anomalies.append(f"{logged.invalid} logged event(s) failed validation when re-read")

    headline = {
        "cycles": runner["cycles"],
        "healthy_pct": round(100 * (1 - runner["unhealthy_minutes"] / runner["observed_minutes"]), 1)
        if runner["observed_minutes"]
        else None,
        "items": items["observed"],
        "quarantined": items["quarantined"],
        "triage_calls": stages["triage"]["calls"],
        "classify_calls": stages["classify"]["calls"],
        "cost_usd": round(stages["triage"]["cost_usd"] + stages["classify"]["cost_usd"], 6),
        "events": len(event_rows),
        "corroborated_events": sum(1 for r in event_rows if r["status"] in {s.value for s in ACTIVE_STATUSES}),
        "events_with_effect": sum(1 for r in event_rows if r["strongest_effect"] != "NO_EFFECT"),
        "decisions": overlay["decisions"],
        "would_block": overlay["would_block"],
        "would_reduce": overlay["would_reduce"],
        "invariants_ok": all(v == 0 for _, v in invariants if v is not None),
    }
    return {
        "report_version": REPORT_VERSION,
        "day": day.isoformat(),
        "as_of": as_of,
        "versions": versions,
        "runner": runner,
        "sources": sources,
        "items": items,
        "sanitizer_flags": dict(flags),
        "classifier": stages,
        "spend": spend,
        "events": {
            "created": len(created),
            "merged": len(merged),
            "articles_in_events": len(article_ids),
            "events_touched": len(event_ids_today),
            "articles_per_event": round(len(article_ids) / len(event_ids_today), 2) if event_ids_today else None,
            "median_publish_to_seen_minutes": round(statistics.median(detection), 1) if detection else None,
            "median_seen_to_known_minutes": round(statistics.median(signal_lag), 1) if signal_lag else None,
            "copies_attached": sum(len(r.get("story_item_ids") or []) for r in copies),
            "stories_not_classified": dict(skipped),
            "corroboration_updates": dict(corroboration_status),
            "single_source_vetoes": single_source_vetoes,
            "expired_today": expired_today,
            "by_category": {k: dict(v) for k, v in sorted(by_cat.items())},
            "rows": event_rows,
        },
        "overlay": overlay,
        "overlay_rows": overlay_rows,
        "phase6a_signals": dict(journal.signal_actions(day)) if journal is not None else None,
        "review": {"missed_events": missed, "large_moves_without_event": large_moves, "false_block_candidates": false_blocks},
        "invariants": [{"check": name, "count": count, "pass": None if count is None else count == 0} for name, count in invariants],
        "anomalies": anomalies,
        "headline": headline,
    }


# -- rendering ------------------------------------------------------------------------------------


def _money(value: Optional[float]) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _cell(value: Any) -> str:
    return str(value if value is not None else "—").replace("|", "/").replace("\n", " ")


def render_report(data: Mapping[str, Any]) -> str:
    h = data["headline"]
    r = data["runner"]
    o = data["overlay"]
    spend = data.get("spend") or {}
    out: List[str] = [
        f"# News shadow daily report — {data['day']} (UTC)",
        "",
        "LOG-ONLY. This report shows what the news layer WOULD have done to new long",
        "entries. Nothing in it changed a trade, an exit, a stop or the demo account, and it",
        "makes no claim about profit. Rebuilt from the news logs and the Phase 6a journal",
        f"alone (as of {data.get('as_of') or 'no records'}; {data['report_version']}).",
        "",
        "## In short",
        "",
    ]
    if not r["cycles"]:
        out.append("- The news shadow did not run on this day.")
    else:
        health = (
            "too short to measure how often the news state was healthy"
            if h["healthy_pct"] is None
            else f"the news state was healthy {h['healthy_pct']}% of the time it was observed"
        )
        out += [
            f"- It ran {r['cycles']} cycle{'' if r['cycles'] == 1 else 's'}; {health}.",
            f"- It saw {h['items']} new articles ({h['quarantined']} put aside as suspicious) and asked the AI about "
            f"{h['triage_calls']} headlines and {h['classify_calls']} stories, for an estimated {_money(h['cost_usd'])}"
            + (f" (this month {_money(spend.get('spent_usd'))} of the {_money(spend.get('cap_usd'))} cap)." if spend else "."),
            f"- It tracked {h['events']} events: {h['corroborated_events']} confirmed by two sources or by the market, "
            f"{h['events_with_effect']} with an effect at some point.",
        ]
        if o["decisions"]:
            out.append(
                f"- Phase 6a made {o['decisions']} new-long decisions ({o['baseline_allowed']} allowed by the existing rules): "
                f"the news layer would have blocked {o['would_block']} and reduced {o['would_reduce']} of the allowed ones."
            )
        else:
            out.append("- Phase 6a made no new-long decision while the news shadow was watching.")
        if r.get("model_enabled") is False:
            out.append("- The AI was switched off (--no-model): news was collected but not classified.")
    out.append(
        "- Safety checks: " + ("all passed." if h["invariants_ok"] else "**FAILED** — see Safety checks below and stop the shadow for review.")
    )
    out += ["", "## Safety checks (design section 11; every count must be 0)", "", "| Check | Count | Result |", "|---|---|---|"]
    for inv in data["invariants"]:
        if inv["pass"] is None:
            out.append(f"| {inv['check']} | — | not checked (no Phase 6a journal) |")
        else:
            out.append(f"| {inv['check']} | {inv['count']} | {'pass' if inv['pass'] else '**FAIL**'} |")

    out += ["", "## Shadow entry overlays", ""]
    if o["decisions"]:
        out += [
            f"- decisions: {o['decisions']} — would block {o['would_block']}, would reduce {o['would_reduce']}, no effect {o['no_effect']}",
            f"- news also active on a baseline that was already blocked (not counted): {o['news_also_active_on_blocked_baseline']}",
            "- baseline: " + ", ".join(f"{k} = {v}" for k, v in sorted(o["baseline"].items())),
            f"- after a would-block or would-reduce ({PRICE_PATH_HOURS} h, from the journal's candles; descriptive, not a trade result): "
            f"{o['after_acted']['with_path']} with a price path, {o['after_acted']['adverse_6h']} lower and "
            f"{o['after_acted']['favorable_6h']} higher {PRICE_PATH_HOURS} h later; mean max drop "
            f"{_cell(o['after_acted']['mean_max_drop_pct'])} %, mean max rise {_cell(o['after_acted']['mean_max_rise_pct'])} %",
            "",
            "| Decision (UTC) | Instrument | Baseline | News | Size × | Event | Why nothing | 6 h later |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in data["overlay_rows"]:
            path = row.get("price_path")
            later = "—" if not path else f"{path['return_pct']:+.2f} % ({path['hours_available']} h)"
            baseline = f"{'allowed' if row.get('baseline_allowed') else 'blocked'}: {row.get('baseline_reason')}"
            out.append(
                f"| {_cell(row.get('decision_time'))} | {_cell(row.get('instrument'))} | {_cell(baseline)} | "
                f"{_cell(row.get('action'))} | {_cell(row.get('size_multiplier'))} | {_cell(row.get('event_id'))} | "
                f"{_cell(row.get('why_no_effect'))} | {later} |"
            )
    else:
        out.append("- no Phase 6a candidate entry was evaluated on this day")
    if data.get("phase6a_signals") is not None:
        out.append(
            "- Phase 6a signals journaled for this day's candles (only LONG ones are ever evaluated): "
            + (", ".join(f"{k} = {v}" for k, v in sorted(data["phase6a_signals"].items())) or "none")
        )

    ev = data["events"]
    out += [
        "",
        "## Events",
        "",
        f"- created {ev['created']}, updated by a linked story {ev['merged']}, same-headline copies attached {ev['copies_attached']}",
        f"- de-duplication: {ev['articles_in_events']} articles folded into {ev['events_touched']} events"
        + (f" ({ev['articles_per_event']} per event)" if ev["articles_per_event"] is not None else ""),
        f"- median time from first publication to the first article seen: {_cell(ev['median_publish_to_seen_minutes'])} min; "
        f"from the first article seen to the event being known: {_cell(ev['median_seen_to_known_minutes'])} min",
        f"- restriction proposed by the AI but kept at no effect by the single-source rule: {ev['single_source_vetoes']}",
        f"- expired during the day: {ev['expired_today']}",
        "- stories not classified: " + (", ".join(f"{k} = {v}" for k, v in sorted(ev["stories_not_classified"].items())) or "none"),
        "- corroboration results: " + (", ".join(f"{k} = {v}" for k, v in sorted(ev["corroboration_updates"].items())) or "none"),
        "",
    ]
    if ev["by_category"]:
        out += ["| Category | Events | Confirmed | Single source | With effect |", "|---|---|---|---|---|"]
        for cat, c in ev["by_category"].items():
            out.append(f"| {cat} | {c.get('events', 0)} | {c.get('corroborated', 0)} | {c.get('single_source', 0)} | {c.get('with_effect', 0)} |")
        out += ["", "| Event | Category | Status | Strongest effect | Sources | Tier | First seen | Expires | Summary |", "|---|---|---|---|---|---|---|---|---|"]
        for row in ev["rows"]:
            out.append(
                f"| {row['event_id']} | {row['category']} | {row['status']} | {row['strongest_effect']} ({row['max_severity']}) | "
                f"{row['sources']} | {row['tier']} | {row['first_seen_at']} | {row['expires_at']} | {_cell(row['summary'])} |"
            )
    else:
        out.append("- no event was live on this day")

    items = data["items"]
    out += [
        "",
        "## Sources and articles",
        "",
        f"- new articles: {items['observed']} (quarantined: {items['quarantined']})",
        "- by source: " + (", ".join(f"{k} = {v}" for k, v in sorted(items["by_source"].items())) or "none"),
        "- by category (from triage): " + (", ".join(f"{k} = {v}" for k, v in sorted(items["by_category"].items())) or "none"),
        "- triage handling: " + (", ".join(f"{k} = {v}" for k, v in sorted(items["triage_status"].items())) or "none"),
        "- sanitizer flags: " + (", ".join(f"{k} = {v}" for k, v in sorted(data["sanitizer_flags"].items())) or "none"),
        "",
    ]
    if data["sources"]:
        out += ["| Source | Fetches | OK | Failed | Items in replies (with repeats) | Outage (min) | Last error |", "|---|---|---|---|---|---|---|"]
        for source_id, s in data["sources"].items():
            out.append(
                f"| {source_id} | {s['attempts']} | {s['ok']} | {s['failed']} | {s['items']} | {s['outage_minutes']} | {_cell(s['last_error'] or None)} |"
            )

    out += ["", "## AI calls", "", "| Stage | Calls | Valid | Schema validity | Refusals | Failures | Prohibited | Est. cost |", "|---|---|---|---|---|---|---|---|"]
    for stage, s in data["classifier"].items():
        failures = ", ".join(f"{k} = {v}" for k, v in sorted(s["failures"].items())) or "none"
        out.append(
            f"| {stage} | {s['calls']} | {s['classes'].get('valid', 0)} | {_pct(s['schema_validity'])} | "
            f"{s['classes'].get('refusal', 0)} | {_cell(failures)} | {s['prohibited_actions']} | {_money(s['cost_usd'])} |"
        )
    if spend:
        out += [
            "",
            f"- spend this month (estimate from list prices): {_money(spend.get('spent_usd'))} of {_money(spend.get('cap_usd'))}; "
            f"today {_money(spend.get('today_usd'))}"
            + (f" of a {_money(spend.get('day_limit_usd'))} pace limit" if spend.get("day_limit_usd") is not None else "")
            + (f"; refused calls: {spend.get('refused')}" if spend.get("refused") else ""),
        ]
        if spend.get("state_error"):
            out.append(f"- **spend record problem:** {spend['state_error']}")

    review = data["review"]
    out += ["", "## For manual review", "", "Restrictions the AI proposed that the rules kept at no effect (possible missed events):", ""]
    if review["missed_events"]:
        for m in review["missed_events"]:
            out.append(
                f"- {m['event_id']} ({m['category']}, {m['status']}, AI proposed {m['proposed']}, score {m['base_score']:.2f}): "
                f"{_cell(m['summary'])} — {', '.join(m['reasons']) or 'below threshold'}"
            )
    else:
        out.append("- none")
    out += ["", f"Hourly drops of {abs(LARGE_MOVE_PCT):.0f} % or more with no active news event (journal candles):", ""]
    out += [f"- {m['instrument']} candle closing {m['candle_close']}: {m['move_pct']:+.2f} %" for m in review["large_moves_without_event"]] or ["- none"]
    out += ["", f"Would-block or would-reduce decisions followed by a higher price {PRICE_PATH_HOURS} h later (possible false blocks):", ""]
    out += [
        f"- {f['decision_time']} {f['instrument']} {f['action']} ({f['event_id']}): {f['return_pct']:+.2f} % later, max drop {f['max_drop_pct']:+.2f} %"
        for f in review["false_block_candidates"]
    ] or ["- none"]

    out += [
        "",
        "## Runner",
        "",
        f"- starts {r['starts']}, stops {r['stops']}, cycles {r['cycles']} (healthy {r['healthy_cycles']})",
        f"- news state unhealthy {r['unhealthy_minutes']:.0f} of {r['observed_minutes']:.0f} observed minutes"
        + (f" ({', '.join(f'{k} = {v}' for k, v in sorted(r['unhealthy_reasons'].items()))})" if r["unhealthy_reasons"] else ""),
        f"- largest clock skew: {_cell(r['max_abs_clock_skew_seconds'])} s",
        "- configuration fingerprint: " + (", ".join(r["fingerprints"]) or "n/a"),
    ]
    versions = data.get("versions") or {}
    if versions:
        out += [
            f"- versions: runner {versions.get('runner_version')}, prompt {versions.get('prompt_version')} "
            f"(classifier {str(versions.get('classifier_prompt_sha256'))[:12]}, triage {str(versions.get('triage_prompt_sha256'))[:12]}), "
            f"models {versions.get('models')}, event schema {versions.get('schema_version')}, decay {versions.get('decay_policy')}, "
            f"overlay {versions.get('overlay_version')}",
            "- sources: " + ", ".join(versions.get("sources") or []),
        ]
    out += ["", "## Open anomalies", ""]
    out += [f"- {a}" for a in data["anomalies"]] or ["- none"]
    out.append("")
    return "\n".join(out)


def generate_daily_report(log_dir: Path, journal_dir: Optional[Path], day: date) -> str:
    return render_report(build_report_data(log_dir, journal_dir, day))


def write_daily_report(log_dir: Path, journal_dir: Optional[Path], day: date) -> Path:
    """Write ``report-YYYY-MM-DD.md`` atomically next to the logs; returns its path.

    Refuses a directory that holds Phase 6a journal files: the Phase 6a reports use
    the same file names there, and a news report must never replace one.
    """
    if any(Path(log_dir).glob("journal-*.jsonl")):
        raise ValueError(f"refusing to write a news report into the Phase 6a journal directory {log_dir}")
    text = generate_daily_report(log_dir, journal_dir, day)
    path = Path(log_dir) / f"report-{day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path
