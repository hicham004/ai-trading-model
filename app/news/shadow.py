"""Phase 6b news shadow runner (PHASE6B_DESIGN sections 7, 11, 13 and 14) — LOG-ONLY.

One cycle (``NewsShadowRunner.run_cycle``), every few minutes:

1. public market data: recent OKX candles for BTC-USDT and ETH-USDT and the
   exchange clock (``market``);
2. ingestion of the due sources: fetch, sanitize, de-duplicate (``pipeline``);
3. triage (Claude Haiku 5.5) of each new item, once per headline: copies with
   the same headline reuse the first answer; quarantined items, and items
   published longer ago than any event may live (24 h), are never sent;
4. stories: the relevant items grouped by category and shared headline words;
5. classification (Claude Opus 5.5) of each story, with the recent events offered
   as candidates to link to; then the deterministic rules: price/volume checks on
   public candles closed before the call, ``corroborate.assess`` and
   ``decay.build_event``;
6. the event book: every version of every event with the time it became known,
   so a Phase 6a decision is judged only on what the news layer knew then;
7. effective signals, logged when they change;
8. the shadow overlay: each settled Phase 6a candidate NEW long entry (read from
   the journal files) evaluated as of its decision time;
9. health, state, the cycle summary and the daily report.

A story's evidence is judged over all of its articles (design 2 rule 5, 4 and
7.5): when a later article is linked to an event, the corroboration counts the
event's earlier independent sources together with the new ones, while a repeat
never re-fires the TTL (``decay.merge_event``). Every failure is NO_EFFECT: a
source outage, an unavailable model or an exhausted budget only means no new
events, and a stale or skewed news state makes the overlay NO_EFFECT (design 13).

The runner has no order authority and no path to one. It imports nothing from
execution, risk, exchange or strategy code, reads the Phase 6a journal files
read-only, never opens the demo database, and writes only the news logs, the news
data store and its own state. Using its output to gate entries is NOT authorized.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.logging_config import get_logger
from app.news.budget import SpendGuard, usage_cost, worst_case_cost
from app.news.classifier import (
    CLASSIFIER_MODEL,
    CLASSIFIER_PROMPT_SHA256,
    CLASSIFIER_SYSTEM_PROMPT,
    MAX_ITEMS_PER_REQUEST,
    PROMPT_VERSION,
    TRIAGE_MODEL,
    TRIAGE_PROMPT_SHA256,
    TRIAGE_SYSTEM_PROMPT,
    ClassificationRequest,
    ClassifierOutcome,
    EventCandidateView,
    NewsClassifier,
)
from app.news.corroborate import CorroborationResult, PriceVolumeCheck, assess, confirm_price_volume, market_context
from app.news.decay import (
    DEFAULT_POLICY,
    POLICY_VERSION,
    DecayPolicy,
    EventBuild,
    build_event,
    effective_signal,
    signal_for_instrument,
)
from app.news.dedup import SeenStore, normalize_title_key, story_key as make_story_key
from app.news.fetch import NewsFetcher
from app.news.market import PublicMarketData
from app.news.overlay import OVERLAY_VERSION, NewLongEntryCandidate, evaluate_new_long_entry
from app.news.phase6a import Phase6aCandidate, Phase6aJournal
from app.news.pipeline import IngestSummary, run_once
from app.news.schema import (
    SCHEMA_VERSION,
    ASSET_ORDER,
    INSTRUMENT_FOR_ASSET,
    Action,
    ClassifiedCategory,
    ClassifierVerdict,
    NewsEvent,
    SourceItemRef,
    SourceTier,
)
from app.news.sources import Source
from app.news.store import NewsShadowLog, NewsStore, redact

logger = get_logger(__name__)

RUNNER_VERSION = "phase6b-news-shadow-v1"
STATE_VERSION = "news-shadow-state-v1"
STATE_FILE = "shadow_state.json"
INSTRUMENTS: Tuple[str, ...] = tuple(INSTRUMENT_FOR_ASSET[a] for a in ASSET_ORDER)

# The classifier's own request limits are the single source of truth for the budget checks.
_CLASSIFIER_DEFAULTS = inspect.signature(NewsClassifier.__init__).parameters
TRIAGE_MAX_TOKENS: int = _CLASSIFIER_DEFAULTS["triage_max_tokens"].default
CLASSIFY_MAX_TOKENS: int = _CLASSIFIER_DEFAULTS["classify_max_tokens"].default
# Generous bounds on one request's user message (sanitized fields are length-capped).
_TRIAGE_PAYLOAD_CHARS = 4_000
_CLASSIFY_PAYLOAD_CHARS = 40_000
TRIAGE_WORST_USD = worst_case_cost(TRIAGE_MODEL, input_chars=len(TRIAGE_SYSTEM_PROMPT) + _TRIAGE_PAYLOAD_CHARS, max_tokens=TRIAGE_MAX_TOKENS)
CLASSIFY_WORST_USD = worst_case_cost(
    CLASSIFIER_MODEL, input_chars=len(CLASSIFIER_SYSTEM_PROMPT) + _CLASSIFY_PAYLOAD_CHARS, max_tokens=CLASSIFY_MAX_TOKENS
)

_TIER_RANK = {SourceTier.OFFICIAL: 4, SourceTier.HIGH: 3, SourceTier.MEDIUM: 2, SourceTier.LOW: 1, SourceTier.UNKNOWN: 0}
_STOPWORDS = frozenset(
    "the a an and or of to in on for with at by from as is are was were be been its it this that after over "
    "into amid says said report reports new news update live latest".split()
)
STORY_SIMILARITY = 0.5  # headline-word Jaccard at which two items are grouped as one story


def _iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_time(item: SourceItemRef) -> datetime:
    if item.published_at is not None and item.published_at <= item.observed_at:
        return item.published_at
    return item.observed_at


def max_event_lifetime(policy: DecayPolicy = DEFAULT_POLICY) -> timedelta:
    """The longest any event can have an effect: the largest category TTL (24 h in v1)."""
    return timedelta(minutes=max(cp.max_ttl_minutes for cp in policy.categories.values()))


def headline_tokens(title: str) -> FrozenSet[str]:
    words = normalize_title_key(title).split()
    return frozenset(w for w in words if w not in _STOPWORDS and (len(w) > 2 or w.isdigit()))


def same_story(a: FrozenSet[str], b: FrozenSet[str]) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= STORY_SIMILARITY


class RunnerLock:
    """One news shadow per state directory: an OS file lock, released when the process ends."""

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


# -- settings -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ShadowSettings:
    """Operational settings of the news shadow (frozen for a run; logged with every start)."""

    interval_seconds: float = 300.0
    model_enabled: bool = True
    max_triage_per_cycle: int = 80
    max_stories_per_cycle: int = 12
    triage_workers: int = 4
    link_candidates: int = 8
    story_item_cap: int = 50
    stale_after_seconds: float = 900.0
    max_clock_skew_seconds: float = 30.0
    clock_unverified_after_seconds: float = 1800.0
    settle_minutes: float = 15.0
    candidate_lookback_hours: float = 36.0
    report_every_seconds: float = 900.0
    report_horizon_hours: float = 6.0
    instruments: Tuple[str, ...] = INSTRUMENTS

    def __post_init__(self) -> None:
        positive = (
            "interval_seconds",
            "max_triage_per_cycle",
            "max_stories_per_cycle",
            "triage_workers",
            "story_item_cap",
            "stale_after_seconds",
            "max_clock_skew_seconds",
            "clock_unverified_after_seconds",
            "settle_minutes",
            "candidate_lookback_hours",
            "report_every_seconds",
            "report_horizon_hours",
        )
        for name in positive:
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be positive")
        if self.link_candidates < 0:
            raise ValueError("link_candidates must not be negative")
        for inst in self.instruments:
            if inst not in INSTRUMENTS:
                raise ValueError(f"unknown instrument {inst!r}")

    def to_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}


# -- the event book -----------------------------------------------------------------------


def _pv_from_dict(data: Mapping[str, Any]) -> PriceVolumeCheck:
    def ts(key: str) -> datetime:
        parsed = _parse(data.get(key))
        if parsed is None:
            raise ValueError(f"price/volume check without {key}")
        return parsed

    return PriceVolumeCheck(
        instrument=str(data["instrument"]),
        confirmed=bool(data["confirmed"]),
        reason=str(data.get("reason") or ""),
        decision_time=ts("decision_time"),
        event_time=ts("event_time"),
        reference_close=data.get("reference_close"),
        last_close=data.get("last_close"),
        move=data.get("move"),
        atr=data.get("atr"),
        volume_ratio=data.get("volume_ratio"),
        baseline_candles=int(data.get("baseline_candles") or 0),
        reaction_candles=int(data.get("reaction_candles") or 0),
        ignored_unclosed_candles=int(data.get("ignored_unclosed_candles") or 0),
    )


@dataclass
class StoryEntry:
    """One event, every version of it with the time it became known, its articles,
    and every price/volume confirmation it has had (evidence is never forgotten)."""

    event_id: str
    story_key: str
    created_at: datetime
    versions: List[Tuple[datetime, NewsEvent]] = field(default_factory=list)
    records: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    price_volume: List[Dict[str, Any]] = field(default_factory=list)

    def confirmed_checks(self) -> List[PriceVolumeCheck]:
        out = []
        for raw in self.price_volume:
            try:
                check = _pv_from_dict(raw)
            except (KeyError, TypeError, ValueError):
                continue
            if check.confirmed:
                out.append(check)
        return out

    @property
    def event(self) -> NewsEvent:
        return self.versions[-1][1]

    @property
    def known_at(self) -> datetime:
        return self.versions[-1][0]

    def as_of(self, when: datetime) -> Optional[NewsEvent]:
        found = None
        for known_at, event in self.versions:
            if known_at > when:
                break
            found = event
        return found

    def refs(self) -> List[SourceItemRef]:
        out = []
        for record in self.records.values():
            try:
                out.append(SourceItemRef.from_record(record))
            except (TypeError, ValueError):
                continue
        return out

    def to_state(self) -> dict:
        return {
            "event_id": self.event_id,
            "story_key": self.story_key,
            "created_at": _iso(self.created_at),
            "versions": [{"known_at": _iso(t), "event": e.model_dump(mode="json")} for t, e in self.versions],
            "records": self.records,
            "price_volume": self.price_volume,
        }

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> "StoryEntry":
        versions = [(_parse(v["known_at"]), NewsEvent.model_validate(v["event"])) for v in data["versions"]]
        if not versions or any(t is None for t, _ in versions):
            raise ValueError("an event entry needs timestamped versions")
        created = _parse(data.get("created_at")) or versions[0][0]
        return cls(
            event_id=str(data["event_id"]),
            story_key=str(data.get("story_key") or ""),
            created_at=created,  # type: ignore[arg-type]
            versions=versions,  # type: ignore[arg-type]
            records={str(k): dict(v) for k, v in dict(data.get("records") or {}).items()},
            price_volume=[dict(p) for p in data.get("price_volume") or []],
        )


class EventBook:
    """All events the shadow currently tracks (kept for a while after they expire)."""

    MAX_VERSIONS = 500

    def __init__(self, *, item_cap: int = 50) -> None:
        self._entries: Dict[str, StoryEntry] = {}
        self._item_cap = int(item_cap)

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> List[StoryEntry]:
        return sorted(self._entries.values(), key=lambda e: (e.created_at, e.event_id))

    def get(self, event_id: Optional[str]) -> Optional[StoryEntry]:
        return self._entries.get(event_id) if event_id else None

    def record(
        self,
        event: NewsEvent,
        *,
        known_at: datetime,
        story_key: str,
        records: Mapping[str, Mapping[str, Any]],
        price_volume: Iterable[PriceVolumeCheck] = (),
    ) -> StoryEntry:
        entry = self._entries.get(event.event_id)
        if entry is None:
            entry = StoryEntry(event.event_id, story_key, known_at)
            self._entries[event.event_id] = entry
        if entry.versions and known_at < entry.known_at:
            known_at = entry.known_at  # versions never go back in time
        entry.versions.append((known_at, event))
        del entry.versions[: max(0, len(entry.versions) - self.MAX_VERSIONS)]
        counted = set(event.source_quality.source_ids)
        for item_id, record in records.items():
            # The articles that count as sources are always kept; the cap only limits the rest.
            if item_id not in entry.records and (item_id in counted or len(entry.records) < self._item_cap):
                entry.records[item_id] = dict(record)
        have = {str(p.get("instrument")) for p in entry.price_volume}
        for check in price_volume:
            if check.confirmed and check.instrument not in have:
                entry.price_volume.append(check.to_dict())
                have.add(check.instrument)
        return entry

    def entry_for_headline(self, story_key: str, now: datetime) -> Optional[StoryEntry]:
        """The unexpired event that already has an article with this exact headline (story key)."""
        for entry in self.entries():
            if now < entry.event.expires_at and any(r.get("story_key") == story_key for r in entry.records.values()):
                return entry
        return None

    def attach(self, event_id: str, records: Mapping[str, Mapping[str, Any]]) -> List[str]:
        """Add same-headline copies to an event's articles (no new version: copies add no source)."""
        entry = self._entries[event_id]
        added = []
        for item_id, record in records.items():
            if item_id not in entry.records and len(entry.records) < self._item_cap:
                entry.records[item_id] = dict(record)
                added.append(item_id)
        return added

    def linkable(self, now: datetime, category: str, limit: int) -> List[NewsEvent]:
        """Unexpired events offered to the classifier for linking: same category first, newest first."""
        live = [e for e in self._entries.values() if now < e.event.expires_at]
        live.sort(key=lambda e: (e.event.category.value != category, -e.known_at.timestamp(), e.event_id))
        return [e.event for e in live[:limit]]

    def current(self) -> List[NewsEvent]:
        return [e.event for e in self.entries()]

    def as_of(self, when: datetime) -> List[NewsEvent]:
        out = []
        for entry in self.entries():
            event = entry.as_of(when)
            if event is not None:
                out.append(event)
        return out

    def prune(self, now: datetime, retain_after_expiry: timedelta) -> List[str]:
        gone = [k for k, e in self._entries.items() if now >= e.event.expires_at + retain_after_expiry]
        for key in gone:
            del self._entries[key]
        return sorted(gone)

    def to_state(self) -> List[dict]:
        return [e.to_state() for e in self.entries()]

    @classmethod
    def from_state(cls, data: Iterable[Mapping[str, Any]], *, item_cap: int = 50) -> "EventBook":
        book = cls(item_cap=item_cap)
        for raw in data:
            entry = StoryEntry.from_state(raw)
            book._entries[entry.event_id] = entry
        return book


# -- stories ------------------------------------------------------------------------------


@dataclass
class Story:
    category: str
    items: List[SourceItemRef]
    tokens: List[FrozenSet[str]]

    @property
    def priority(self) -> Tuple[int, int, datetime]:
        best_tier = max((_TIER_RANK[i.tier] for i in self.items), default=0)
        return (-best_tier, -len(self.items), min(_source_time(i) for i in self.items))


def group_stories(relevant: Sequence[Tuple[SourceItemRef, str]]) -> List[Story]:
    """Group relevant items by triage category and shared headline words (deterministic)."""
    stories: List[Story] = []
    for ref, category in sorted(relevant, key=lambda rc: (_source_time(rc[0]), rc[0].item_id)):
        tokens = headline_tokens(ref.title)
        title_key = normalize_title_key(ref.title)
        home = None
        for story in stories:
            if story.category != category:
                continue
            if any(normalize_title_key(i.title) == title_key for i in story.items) or any(
                same_story(tokens, t) for t in story.tokens
            ):
                home = story
                break
        if home is None:
            stories.append(Story(category, [ref], [tokens]))
        else:
            home.items.append(ref)
            home.tokens.append(tokens)
    return sorted(stories, key=lambda s: s.priority)


def request_items(story: Story, limit: int = MAX_ITEMS_PER_REQUEST) -> Tuple[List[SourceItemRef], List[SourceItemRef]]:
    """At most ``limit`` items for one classification, one per publisher first (most diverse)."""
    ordered = sorted(story.items, key=lambda i: (-_TIER_RANK[i.tier], _source_time(i), i.item_id))
    chosen: List[SourceItemRef] = []
    seen_publishers = set()
    for item in ordered:
        key = (item.publisher or item.canonical_url).strip().lower()
        if key not in seen_publishers and len(chosen) < limit:
            chosen.append(item)
            seen_publishers.add(key)
    for item in ordered:
        if len(chosen) >= limit:
            break
        if item not in chosen:
            chosen.append(item)
    left = [i for i in ordered if i not in chosen]
    return chosen, left


@dataclass(frozen=True)
class StoryBuild:
    """One classified story turned into an event by the deterministic rules."""

    build: EventBuild
    corroboration: CorroborationResult
    records: Mapping[str, Mapping[str, Any]]
    story_key: str
    supporting: FrozenSet[str]
    price_volume: Tuple[Any, ...]


# Words too common in crypto and macro headlines to show that two articles tell the same story.
_GENERIC_WORDS = frozenset(
    "bitcoin btc ethereum ether eth crypto cryptocurrency cryptocurrencies token tokens coin coins exchange "
    "exchanges market markets price prices trading traders investors stock stocks billion million percent "
    "sec fed fomc cpi ppi etf etfs spot rate rates inflation jobs payrolls dollar dollars says report".split()
)


def distinctive_words(text: str) -> FrozenSet[str]:
    return frozenset(w for w in headline_tokens(text) if w not in _GENERIC_WORDS)


def link_problem(verdict: ClassifierVerdict, items: Sequence[SourceItemRef], linked: StoryEntry) -> Optional[str]:
    """Why the classifier's ``same_story_as`` must not be followed (None = it may).

    Following a link pools the two stories' evidence, so one wrong link could turn
    two unrelated single-source items into a "confirmed" event. A link is used only
    when the category is the same, the assets overlap, and the new articles share a
    distinctive headline word with the event's own articles (observed text, not the
    model's summary). Otherwise the story stays on its own: at worst a missed
    corroboration (no effect), never an invented one.
    """
    event = linked.event
    if verdict.category.value != event.category.value:
        return "category_mismatch"
    if not set(verdict.assets) & set(event.asset_impact.assets):
        return "asset_mismatch"
    new_words = set().union(*(distinctive_words(i.title) for i in items)) if items else set()
    old_words = set().union(*(distinctive_words(str(r.get("title") or "")) for r in linked.records.values())) if linked.records else set()
    if not new_words & old_words:
        return "no_shared_headline_words"
    return None


def story_event(
    verdict: ClassifierVerdict,
    sent: Sequence[SourceItemRef],
    sent_records: Mapping[str, Mapping[str, Any]],
    linked: Optional[StoryEntry],
    candles: Mapping[str, Sequence[Any]],
    now: datetime,
    policy: DecayPolicy = DEFAULT_POLICY,
) -> StoryBuild:
    """Corroborate and build one story over ALL of its articles (pure; no I/O).

    For a story linked to an existing event the articles are the event's earlier
    ones plus the new ones, and the sources counted are those counted before plus
    the ones the classifier names now — so a repeat can add independent evidence
    but can never erase the evidence already seen. ``build_event`` keeps the
    linked event's id, first-seen time and expiry (a repeat never re-fires the
    TTL). Unlinked, this is exactly the path the R4b eval scores (``run_story``).
    """
    records: Dict[str, Mapping[str, Any]] = dict(linked.records) if linked else {}
    for item in sent:
        record = sent_records.get(item.item_id)
        if record is not None:
            records.setdefault(item.item_id, record)
    refs = linked.refs() if linked else []
    known = {r.item_id for r in refs}
    refs += [i for i in sent if i.item_id not in known]
    supporting = set(verdict.independent_source_ids)
    if linked is not None:
        supporting |= set(linked.event.source_quality.source_ids)
    usable = [r for r in refs if not r.quarantined] or refs
    event_time = min(_source_time(r) for r in usable) if usable else now
    checks = tuple(
        confirm_price_volume(
            candles.get(INSTRUMENT_FOR_ASSET[asset], ()),
            instrument=INSTRUMENT_FOR_ASSET[asset],
            event_time=event_time,
            decision_time=now,
            reaction=verdict.expected_market_reaction,
        )
        for asset in ASSET_ORDER
        if asset in set(verdict.assets) and INSTRUMENT_FOR_ASSET[asset] in candles
    )
    # A market confirmation the story already had stays part of its evidence: a
    # later repeat after the price has retraced cannot take it back.
    checks += tuple(linked.confirmed_checks()) if linked is not None else ()
    corroboration = assess(refs, llm_assessment=verdict.corroboration_assessment, supporting_ids=supporting, price_volume=checks)
    if linked is not None:
        story_key = linked.story_key
    elif usable:
        first = min(usable, key=lambda i: (_source_time(i), i.item_id))
        first_record = records.get(first.item_id) or {}
        story_key = str(first_record.get("story_key") or make_story_key(first.title, first.published_at, first.observed_at))
    else:
        story_key = ""
    build = build_event(
        verdict=verdict,
        items=refs,
        corroboration=corroboration,
        story_key=story_key,
        existing=linked.event if linked else None,
        policy=policy,
    )
    return StoryBuild(build, corroboration, records, story_key, frozenset(supporting), checks)


# -- the runner ---------------------------------------------------------------------------


def _signature(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


def config_fingerprint(settings: ShadowSettings, sources: Sequence[Source], policy: DecayPolicy) -> str:
    """Hash of everything the forward validation freezes (design 11, step 1)."""
    body = {
        "runner": RUNNER_VERSION,
        "prompt_version": PROMPT_VERSION,
        "classifier_prompt_sha256": CLASSIFIER_PROMPT_SHA256,
        "triage_prompt_sha256": TRIAGE_PROMPT_SHA256,
        "models": [TRIAGE_MODEL, CLASSIFIER_MODEL],
        "decay_policy": policy.version,
        "thresholds": [policy.no_effect_below, policy.block_at, [[t, str(m)] for t, m in policy.reduce_tiers]],
        "ttls": {c.value: [p.min_ttl_minutes, p.max_ttl_minutes, p.allow_block] for c, p in policy.categories.items()},
        "weights": {t.value: w for t, w in policy.source_weights.items()},
        "overlay": OVERLAY_VERSION,
        "sources": sorted(s.source_id for s in sources),
        "settings": settings.to_dict(),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


class NewsShadowRunner:
    """The log-only news shadow; one ``run_cycle`` per interval (see the module doc)."""

    def __init__(
        self,
        *,
        sources: Sequence[Source],
        fetcher: NewsFetcher,
        store: NewsStore,
        seen: SeenStore,
        market: PublicMarketData,
        classifier: Optional[NewsClassifier],
        guard: Optional[SpendGuard],
        log: NewsShadowLog,
        journal: Phase6aJournal,
        state_dir: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
        settings: ShadowSettings = ShadowSettings(),
        policy: DecayPolicy = DEFAULT_POLICY,
        report_writer: Optional[Callable[[date], Any]] = None,
    ) -> None:
        self.settings = settings
        self._sources = list(sources)
        self._fetcher = fetcher
        self._store = store
        self._seen = seen
        self._market = market
        self._classifier = classifier if settings.model_enabled else None
        self._guard = guard
        self._log = log
        self._journal = journal
        self._state_dir = Path(state_dir)
        self._clock = clock
        self._policy = policy
        self._report_writer = report_writer
        self._max_age = max_event_lifetime(policy)
        self.fingerprint = config_fingerprint(settings, self._sources, policy)
        # state (persisted)
        self._book = EventBook(item_cap=settings.story_item_cap)
        self._started_at: Optional[datetime] = None
        self._cycle = 0
        self._processed: Dict[str, str] = {}
        self._health: List[Tuple[datetime, bool]] = []
        self._triage_cache: Dict[str, Dict[str, Any]] = {}
        self._last_event_signal: Dict[str, str] = {}
        self._last_instrument_signal: Dict[str, str] = {}
        self._source_last: Dict[str, str] = {}
        self._last_report_at: Optional[datetime] = None
        self._summary_day: Optional[str] = None
        self._budget_refusing = False
        self._last_healthy: Optional[bool] = None
        self._clock_ok_at: Optional[datetime] = None
        self._cycle_records: Dict[str, Dict[str, Any]] = {}

    # -- lifecycle -----------------------------------------------------------------------

    @property
    def state_file(self) -> Path:
        return self._state_dir / STATE_FILE

    @property
    def book(self) -> EventBook:
        return self._book

    def start(self) -> None:
        now = self._clock()
        restored = self._load_state()
        if self._started_at is None:
            self._started_at = now
        self._log.write_event(
            "runner_event",
            event="start",
            runner_version=RUNNER_VERSION,
            config_fingerprint=self.fingerprint,
            state_restored=restored,
            started_at=_iso(self._started_at),
            events_tracked=len(self._book),
            model_enabled=self._classifier is not None,
            models={"triage": TRIAGE_MODEL, "classify": CLASSIFIER_MODEL},
            prompt_version=PROMPT_VERSION,
            classifier_prompt_sha256=CLASSIFIER_PROMPT_SHA256,
            triage_prompt_sha256=TRIAGE_PROMPT_SHA256,
            decay_policy=POLICY_VERSION,
            schema_version=SCHEMA_VERSION,
            overlay_version=OVERLAY_VERSION,
            sources=[s.source_id for s in self._sources],
            settings=self.settings.to_dict(),
            spend=self._guard.snapshot(now).to_dict() if self._guard else None,
            journal_dir=str(self._journal.journal_dir),
            journal_found=self._journal.exists,
        )

    def stop(self, reason: str = "operator_stop") -> None:
        now = self._clock()
        try:
            self._save_state(now)
        finally:
            self._log.write_event("runner_event", event="stop", reason=reason, cycles=self._cycle)
            self._write_reports(now, force=True)

    # -- one cycle -----------------------------------------------------------------------

    def run_cycle(self) -> Dict[str, Any]:
        started = self._clock()
        self._cycle += 1
        self._cycle_records = {}
        errors: List[str] = []
        unhealthy: List[str] = []

        def guarded(stage: str, fn: Callable[[], Any], default: Any = None, fatal: bool = True) -> Any:
            try:
                return fn()
            except Exception as exc:  # one stage failing never stops the others (and is NO_EFFECT)
                errors.append(f"{stage}:{type(exc).__name__}")
                logger.warning("news shadow stage failed", extra={"stage": stage, "error_type": type(exc).__name__})
                if fatal:
                    unhealthy.append(f"{stage}_failed")
                return default

        market = guarded("market", self._market.refresh, default=[], fatal=False)
        skew = guarded("clock", lambda: self._market.clock_skew_seconds(self._clock), fatal=False)
        if skew is not None and abs(skew) > self.settings.max_clock_skew_seconds:
            unhealthy.append("clock_skew")
            self._log.write_event("runner_event", event="clock_skew", skew_seconds=round(skew, 3))
        elif skew is not None:
            self._clock_ok_at = started
        if self._clock_ok_at is None or (started - self._clock_ok_at).total_seconds() > self.settings.clock_unverified_after_seconds:
            unhealthy.append("clock_unverified")  # design 13: a news clock we cannot check is not trusted
        ingest: Optional[IngestSummary] = guarded("ingest", lambda: self._ingest(started))
        if ingest is not None and ingest.sources_attempted and not ingest.sources_ok:
            unhealthy.append("all_sources_failed")
        triage_counts: Counter = Counter()
        relevant: List[Tuple[SourceItemRef, str]] = []
        if ingest is not None:
            relevant = guarded("triage", lambda: self._observe_and_triage(ingest, started, triage_counts), default=[])
        story_counts: Counter = Counter()
        guarded("stories", lambda: self._process_stories(relevant, story_counts))
        signals = guarded("signals", lambda: self._update_signals(self._clock()), default={})
        overlay_counts: Counter = Counter()
        guarded("overlay", lambda: self._evaluate_candidates(self._clock(), overlay_counts), fatal=False)

        budget_skips = int(triage_counts.get("skipped_budget", 0)) + int(story_counts.get("skipped_budget", 0))
        if self._guard is not None:
            refusal = self._guard.refusal(TRIAGE_WORST_USD) or self._guard.refusal(CLASSIFY_WORST_USD)
            self._note_budget(refusal, skipped=budget_skips)

        finished = self._clock()
        healthy = not unhealthy
        self._health.append((finished, healthy))
        horizon = finished - timedelta(hours=self.settings.candidate_lookback_hours + 12)
        self._health = [(t, h) for t, h in self._health if t >= horizon]
        if self._last_healthy is not None and healthy != self._last_healthy:
            self._log.write_event("runner_event", event="health_changed", healthy=healthy, reasons=sorted(set(unhealthy)))
        self._last_healthy = healthy
        pruned = self._book.prune(finished, timedelta(hours=self.settings.candidate_lookback_hours))
        for event_id in pruned:
            self._last_event_signal.pop(event_id, None)
        guarded("state", lambda: self._save_state(finished), fatal=False)

        spend = self._guard.snapshot(finished).to_dict() if self._guard else None
        summary = {
            "cycle": self._cycle,
            "started_at": _iso(started),
            "finished_at": _iso(finished),
            "duration_ms": int((finished - started).total_seconds() * 1000),
            "healthy": healthy,
            "unhealthy_reasons": sorted(set(unhealthy)),
            "clock_skew_seconds": None if skew is None else round(skew, 3),
            "market": [m.to_dict() for m in market or []],
            "sources": {
                "attempted": ingest.sources_attempted if ingest else 0,
                "ok": ingest.sources_ok if ingest else 0,
                "failed": ingest.sources_failed if ingest else 0,
                "skipped": ingest.sources_skipped if ingest else 0,
            },
            "items": {
                "new": len(ingest.records) if ingest else 0,
                "quarantined": len(ingest.quarantined) if ingest else 0,
                "duplicates": ingest.items_duplicate if ingest else 0,
            },
            "triage": dict(sorted(triage_counts.items())),
            "stories": dict(sorted(story_counts.items())),
            "events": self._event_counts(finished),
            "signals": signals or {},
            "overlay": dict(sorted(overlay_counts.items())),
            "spend": spend,
            "model_enabled": self._classifier is not None,
            "config_fingerprint": self.fingerprint,
            "errors": errors,
        }
        self._log.write_event("cycle_summary", summary)
        self._daily_summary_on_rollover(finished)
        guarded("report", lambda: self._write_reports(finished), fatal=False)
        return summary

    # -- 2. ingestion ---------------------------------------------------------------------

    def _due_sources(self, now: datetime) -> List[Source]:
        due = []
        for source in self._sources:
            last = _parse(self._source_last.get(source.source_id))
            # A small tolerance keeps a 300 s source on a 300 s loop from skipping every other cycle.
            if last is None or (now - last).total_seconds() >= source.min_interval_seconds - 5:
                due.append(source)
        return due

    def _ingest(self, now: datetime) -> IngestSummary:
        sources = self._due_sources(now)
        summary = run_once(sources, self._fetcher, self._store, self._seen, now=now)
        for source in sources:
            self._source_last[source.source_id] = _iso(now)
        for entry in summary.fetches:
            self._log.write_event("source_fetch", redact(entry))
        return summary

    # -- 3. observation and triage ------------------------------------------------------------

    def _observe(self, record: Mapping[str, Any], triage: Mapping[str, Any]) -> None:
        self._log.write_event(
            "source_item_observed",
            item_id=triage.get("item_id"),
            source_id=record.get("source_id"),
            publisher=record.get("publisher"),
            publisher_owner=record.get("publisher_owner"),
            source_tier=record.get("source_tier"),
            canonical_url=record.get("canonical_url"),
            published_at=record.get("published_at"),
            observed_at=record.get("observed_at"),
            title=record.get("title"),
            language=record.get("language"),
            story_key=record.get("story_key"),
            content_key=record.get("content_key"),
            sanitization_flags=list(record.get("sanitization_flags") or ()),
            quarantined=bool(record.get("quarantined")),
            triage={k: v for k, v in triage.items() if k != "item_id"},
        )
        if record.get("sanitization_flags"):
            self._log.write_event(
                "source_item_sanitized",
                item_id=triage.get("item_id"),
                source_id=record.get("source_id"),
                sanitization_flags=list(record.get("sanitization_flags") or ()),
                quarantined=bool(record.get("quarantined")),
                title_sha256_original=record.get("title_sha256_original"),
                title_sha256_sanitized=record.get("title_sha256_sanitized"),
                excerpt_sha256_original=record.get("excerpt_sha256_original"),
                excerpt_sha256_sanitized=record.get("excerpt_sha256_sanitized"),
            )

    def _log_outcome(self, outcome: ClassifierOutcome, **extra: Any) -> None:
        record = outcome.to_log_record()
        served = outcome.served_model or outcome.model
        record["cost_usd"] = round(usage_cost(served, outcome.usage), 8) if outcome.usage else 0.0
        self._log.write_event(outcome.log_kind, record, **extra)

    def _budget_refusal(self, worst: float) -> Optional[str]:
        return None if self._guard is None else self._guard.refusal(worst)

    def _note_budget(self, reason: Optional[str], *, skipped: int = 0) -> None:
        """Log when AI calls start or stop being held back by the spend cap (triage or classification)."""
        refusing = reason is not None or skipped > 0
        if refusing != self._budget_refusing and self._guard is not None:
            self._budget_refusing = refusing
            self._log.write_event(
                "runner_event",
                event="spend_cap_reached" if refusing else "spend_cap_cleared",
                reason=reason or ("calls_skipped" if refusing else None),
                skipped_calls=skipped,
                spend=self._guard.snapshot().to_dict(),
            )

    @staticmethod
    def _spend_failure(outcome: ClassifierOutcome) -> ClassifierOutcome:
        if outcome.failure and "SpendCapReached" in outcome.failure:
            return replace(outcome, failure="spend_cap_reached")
        return outcome

    def _observe_and_triage(self, ingest: IngestSummary, now: datetime, counts: Counter) -> List[Tuple[SourceItemRef, str]]:
        for record in ingest.quarantined:
            counts["quarantined"] += 1
            self._observe(record, {"item_id": self._item_id(record), "status": "quarantined"})
        self._prune_triage_cache(now)
        pending: Dict[str, List[Tuple[Dict[str, Any], SourceItemRef]]] = {}
        observed: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        attachments: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for record in ingest.records:
            try:
                ref = SourceItemRef.from_record(record)
            except (TypeError, ValueError):
                counts["invalid"] += 1
                observed.append((record, {"item_id": None, "status": "invalid_record"}))
                continue
            info: Dict[str, Any] = {"item_id": ref.item_id}
            key = str(record.get("story_key") or ref.item_id)
            entry = self._book.entry_for_headline(key, now) if ref.tier is not SourceTier.OFFICIAL else None
            if ref.quarantined:
                info["status"] = "quarantined"
            elif ref.observed_at - _source_time(ref) >= self._max_age:
                info["status"] = "skipped_stale"  # too old for any event to still have an effect
            elif self._classifier is None:
                info["status"] = "model_disabled"
            elif entry is not None:
                # A copy of an article the event already has (same headline): one more
                # article of the same story, never one more source (design 7.3, 7.5).
                info.update(status="attached", attached_to=entry.event_id)
                attachments.setdefault(entry.event_id, {})[ref.item_id] = dict(record)
            elif key in self._triage_cache:
                cached = self._triage_cache[key]
                info.update(status="reused", reused_from=cached["item_id"], relevant=cached["relevant"], category=cached["category"])
            else:
                pending.setdefault(key, []).append((record, ref))
                continue
            observed.append((record, info))
        # One triage call per headline: the best-tier, earliest item represents its copies.
        groups = sorted(
            pending.items(),
            key=lambda kv: (-max(_TIER_RANK[r.tier] for _, r in kv[1]), -max(_source_time(r) for _, r in kv[1]).timestamp()),
        )
        to_call: List[Tuple[str, Dict[str, Any], SourceItemRef]] = []
        for key, members in groups:
            rep_record, rep = min(members, key=lambda m: (-_TIER_RANK[m[1].tier], _source_time(m[1]), m[1].item_id))
            if len(to_call) >= self.settings.max_triage_per_cycle:
                status = "skipped_cycle_cap"
            elif self._budget_refusal(TRIAGE_WORST_USD * (len(to_call) + 1)) is not None:
                status = "skipped_budget"
            else:
                to_call.append((key, rep_record, rep))
                continue
            counts[status] += len(members)
            for record, ref in members:
                observed.append((record, {"item_id": ref.item_id, "status": status}))
        for event_id, records in sorted(attachments.items()):
            added = self._book.attach(event_id, records)
            counts["attached"] += len(records)
            self._log.write_event(
                "event_deduplicated",
                event=None,
                event_id=event_id,
                reasons=["same_headline_copy"],
                merged=False,
                evidence_upgraded=False,
                story_item_ids=sorted(records),
                added_item_ids=added,
            )
        outcomes: Dict[str, ClassifierOutcome] = {}
        if to_call:
            with ThreadPoolExecutor(max_workers=self.settings.triage_workers) as pool:
                futures = {key: pool.submit(self._safe_triage, ref, now) for key, _, ref in to_call}
                outcomes = {key: self._spend_failure(f.result()) for key, f in futures.items()}
        relevant: List[Tuple[SourceItemRef, str]] = []
        for key, rep_record, rep in to_call:
            outcome = outcomes[key]
            counts["calls"] += 1
            self._log_outcome(outcome, story_key=key)
            category = outcome.verdict.category.value if outcome.ok and outcome.verdict is not None else None
            if outcome.ok:
                self._triage_cache[key] = {
                    "item_id": rep.item_id,
                    "relevant": outcome.relevant,
                    "category": category,
                    "at": _iso(now),
                }
            else:
                counts["failed"] += 1
            for record, ref in pending[key]:
                info: Dict[str, Any] = {"item_id": ref.item_id}
                if outcome.ok:
                    info.update(
                        status="called" if ref.item_id == rep.item_id else "reused",
                        relevant=outcome.relevant,
                        category=category,
                    )
                    if ref.item_id != rep.item_id:
                        info["reused_from"] = rep.item_id
                else:
                    info.update(status="failed", failure=outcome.failure)
                observed.append((record, info))
        for record, info in observed:
            self._observe(record, info)
            if info.get("relevant") and info.get("category") not in (None, ClassifiedCategory.NONE.value):
                counts["relevant"] += 1
                try:
                    relevant.append((SourceItemRef.from_record(record), str(info["category"])))
                except (TypeError, ValueError):
                    counts["invalid"] += 1
            if info.get("status") == "reused":
                counts["reused"] += 1
            elif info.get("status") == "skipped_stale":
                counts["skipped_stale"] += 1
            elif info.get("status") == "model_disabled":
                counts["model_disabled"] += 1
        self._cycle_records = {str(info["item_id"]): dict(r) for r, info in observed if info.get("item_id")}
        return relevant

    def _safe_triage(self, ref: SourceItemRef, now: datetime) -> ClassifierOutcome:
        """One triage call; an unexpected exception is a failed outcome (NO_EFFECT), never a lost cycle."""
        assert self._classifier is not None
        try:
            return self._classifier.triage(ref, now=now)
        except Exception as exc:
            return ClassifierOutcome(
                stage="triage",
                ok=False,
                model=TRIAGE_MODEL,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=TRIAGE_PROMPT_SHA256,
                failure=f"unexpected_error:{type(exc).__name__}",
                item_ids=(ref.item_id,),
            )

    def _forget_headlines(self, items: Sequence[SourceItemRef], now: datetime, note: str) -> None:
        """Headlines the classifier found outside the watchlist are not sent again when copies arrive."""
        for item in items:
            key = str((self._cycle_records.get(item.item_id) or {}).get("story_key") or "")
            if key:
                self._triage_cache[key] = {"item_id": item.item_id, "relevant": False, "category": "NONE", "at": _iso(now), "note": note}

    @staticmethod
    def _item_id(record: Mapping[str, Any]) -> Optional[str]:
        try:
            return SourceItemRef.from_record(record).item_id
        except (TypeError, ValueError):
            return None

    def _prune_triage_cache(self, now: datetime) -> None:
        cutoff = now - self._max_age - timedelta(hours=2)
        self._triage_cache = {k: v for k, v in self._triage_cache.items() if (_parse(v.get("at")) or now) >= cutoff}

    # -- 4-6. stories, classification, corroboration, the event book ------------------------------------

    def _market_context(self, now: datetime) -> Dict[str, Dict[str, str]]:
        out = {}
        for inst in self.settings.instruments:
            ctx = market_context(self._market.candles(inst), decision_time=now)
            if ctx is not None:
                out[inst] = ctx
        return out

    def _process_stories(self, relevant: Sequence[Tuple[SourceItemRef, str]], counts: Counter) -> None:
        if not relevant:
            return
        assert self._classifier is not None
        stories = group_stories(relevant)
        counts["found"] += len(stories)
        for index, story in enumerate(stories):
            items, left = request_items(story)
            ids = [i.item_id for i in items]
            if index >= self.settings.max_stories_per_cycle:
                counts["skipped_cycle_cap"] += 1
                self._log.write_event("event_candidate_created", event=None, reasons=["skipped_cycle_cap"], story_item_ids=ids)
                continue
            refusal = self._budget_refusal(CLASSIFY_WORST_USD)
            if refusal is not None:
                counts["skipped_budget"] += 1
                self._log.write_event("event_candidate_created", event=None, reasons=[f"skipped_budget:{refusal}"], story_item_ids=ids)
                continue
            if left:
                counts["items_not_sent"] += len(left)
            try:
                self._classify_story(story, items, counts)
            except Exception as exc:  # one story failing never stops the others (it is NO_EFFECT)
                counts["errors"] += 1
                logger.warning("news shadow story failed", extra={"error_type": type(exc).__name__})
                self._log.write_event("event_candidate_created", event=None, reasons=[f"story_error:{type(exc).__name__}"], story_item_ids=ids)

    def _classify_story(self, story: Story, items: List[SourceItemRef], counts: Counter) -> None:
        now = self._clock()
        assert self._classifier is not None
        candidates = self._book.linkable(now, story.category, self.settings.link_candidates)
        request = ClassificationRequest(
            now=now,
            items=tuple(items),
            candidates=tuple(EventCandidateView.from_event(e) for e in candidates),
            market_context=self._market_context(now),
        )
        outcome = self._spend_failure(self._classifier.classify(request))
        ids = [i.item_id for i in items]
        counts["classified"] += 1
        self._log_outcome(outcome, story_item_ids=ids, category_hint=story.category, candidate_event_ids=[e.event_id for e in candidates])
        if not outcome.ok or not isinstance(outcome.verdict, ClassifierVerdict):
            counts["failed"] += 1
            return
        verdict = outcome.verdict
        if verdict.category is ClassifiedCategory.NONE:
            counts["not_watchlist"] += 1
            self._forget_headlines(items, now, "classified_not_watchlist")
            return
        sent = [i for i in items if i.item_id in set(outcome.item_ids)]
        linked = None
        link_rejected = None
        if verdict.same_story_as is not None and not verdict.new_development:
            linked = self._book.get(verdict.same_story_as)
            link_rejected = link_problem(verdict, sent, linked) if linked is not None else None
            if link_rejected is not None:
                counts["links_rejected"] += 1
                linked = None  # judged on its own articles: a doubtful link never pools evidence
        candles = {inst: self._market.candles(inst) for inst in INSTRUMENTS}
        story = story_event(verdict, sent, self._cycle_records, linked, candles, now, self._policy)
        if story.build.event is not None and linked is None:
            twin = self._book.get(story.build.event.event_id)
            if twin is not None:
                # The deterministic story id says it is the same story: merge, never double count.
                linked = twin
                story = story_event(verdict, sent, self._cycle_records, linked, candles, now, self._policy)
        build = story.build
        event = build.event
        story_ids = sorted(story.records)
        self._log.write_event(
            "corroboration_update",
            event_id=event.event_id if event else None,
            linked_event_id=linked.event_id if linked else None,
            classifier_link=verdict.same_story_as,
            link_rejected=link_rejected,
            story_item_ids=story_ids,
            supporting_item_ids=sorted(story.supporting),
            corroboration=story.corroboration.to_dict(),
        )
        kind = "event_deduplicated" if build.merged else "event_candidate_created"
        if event is None:
            counts["no_event"] += 1
            self._log.write_event(kind, build.to_dict(), story_item_ids=story_ids, linked_event_id=linked.event_id if linked else None)
            return
        known_at = self._clock()
        self._book.record(
            event, known_at=known_at, story_key=story.story_key, records=story.records, price_volume=story.price_volume
        )
        counts["events_merged" if build.merged else "events_created"] += 1
        self._log.write_event(
            kind,
            build.to_dict(),
            event_id=event.event_id,
            known_at=_iso(known_at),
            story_key=story.story_key,
            story_item_ids=story_ids,
            linked_event_id=linked.event_id if linked else None,
            linked_by="classifier" if (linked and verdict.same_story_as == linked.event_id) else ("event_id" if linked else None),
            classifier_link=verdict.same_story_as,
            link_rejected=link_rejected,
            new_development=verdict.new_development,
            proposed_action=verdict.proposed_action.value,
            base_score=round(event.confidence * self._policy.source_weights[event.source_quality.tier] * event.asset_impact.impact_strength, 6),
        )
        signal = effective_signal(event, known_at, self._policy)
        self._last_event_signal[event.event_id] = _signature(signal.action.value, signal.size_multiplier, signal.reason)
        self._log.write_event(
            "effective_signal",
            signal.to_dict(),
            scope="event",
            status=event.corroboration_status.value,
            expires_at=_iso(event.expires_at),
        )

    # -- 7. effective signals --------------------------------------------------------------------

    def _update_signals(self, now: datetime) -> Dict[str, Dict[str, Any]]:
        events = self._book.current()
        for entry in self._book.entries():
            signal = effective_signal(entry.event, now, self._policy)
            sig = _signature(signal.action.value, signal.size_multiplier, signal.reason)
            if self._last_event_signal.get(entry.event_id) != sig:
                self._last_event_signal[entry.event_id] = sig
                self._log.write_event(
                    "effective_signal",
                    signal.to_dict(),
                    scope="event",
                    status=entry.event.corroboration_status.value,
                    expires_at=_iso(entry.event.expires_at),
                )
        out = {}
        for inst in self.settings.instruments:
            combined, _ = signal_for_instrument(events, inst, now, self._policy)
            sig = _signature(combined.action.value, combined.size_multiplier, combined.deciding_event_id)
            if self._last_instrument_signal.get(inst) != sig:
                self._last_instrument_signal[inst] = sig
                self._log.write_event("effective_signal", combined.to_dict(), scope="instrument")
            out[inst] = {
                "action": combined.action.value,
                "size_multiplier": str(combined.size_multiplier),
                "deciding_event_id": combined.deciding_event_id,
            }
        return out

    def _event_counts(self, now: datetime) -> Dict[str, Any]:
        by_action: Counter = Counter()
        live = 0
        for event in self._book.current():
            if now < event.expires_at:
                live += 1
                by_action[effective_signal(event, now, self._policy).action.value] += 1
        return {"tracked": len(self._book), "unexpired": live, "by_effective_action": dict(sorted(by_action.items()))}

    # -- 8. the shadow overlay against Phase 6a candidates ------------------------------------

    def healthy_at(self, when: datetime) -> bool:
        """Was the news state fresh at ``when``: a healthy cycle finished within ``stale_after`` before it?"""
        window = timedelta(seconds=self.settings.stale_after_seconds)
        return any(h and when - window <= t <= when for t, h in self._health)

    def _evaluate_candidates(self, now: datetime, counts: Counter) -> None:
        if not self._journal.exists:
            counts["journal_missing"] += 1
            return
        self._journal.refresh({now.date() - timedelta(days=1), now.date()})
        lookback = timedelta(hours=self.settings.candidate_lookback_hours)
        for candidate in self._journal.candidates(now):
            if candidate.key in self._processed:
                continue
            if not candidate.settled:
                counts["pending"] += 1
                continue
            if self._started_at is not None and candidate.decision_time < self._started_at:
                counts["skipped_before_start"] += 1
                self._processed[candidate.key] = _iso(now)
                continue
            if now - candidate.decision_time > lookback:
                counts["skipped_too_old"] += 1
                self._processed[candidate.key] = _iso(now)
                continue
            record = self.evaluate_candidate(candidate, now)
            self._log.write_decision(record)
            self._processed[candidate.key] = _iso(now)
            counts["evaluated"] += 1
            if record["would_have_blocked_here"]:
                counts["would_block"] += 1
            if record["would_have_reduced_here"]:
                counts["would_reduce"] += 1
        self._journal.prune(now - lookback - timedelta(days=1))
        cutoff = now - lookback - timedelta(days=2)
        self._processed = {k: v for k, v in self._processed.items() if (_parse(v) or now) >= cutoff}

    def evaluate_candidate(self, candidate: Phase6aCandidate, now: datetime) -> Dict[str, Any]:
        """The shadow overlay on one settled candidate, as of its decision time (no hindsight)."""
        assert candidate.baseline is not None
        at = candidate.decision_time
        events = self._book.as_of(at)
        healthy = self.healthy_at(at)
        decision = evaluate_new_long_entry(
            NewLongEntryCandidate(
                instrument=candidate.instrument,
                decision_time=at,
                baseline_allowed=candidate.baseline.allowed,
                baseline_reason=candidate.baseline.reason,
                signal_ref=candidate.signal_id,
            ),
            events,
            news_healthy=healthy,
            policy=self._policy,
        )
        affecting = [e for e in events if candidate.instrument in e.asset_impact.instruments]
        per_event = [effective_signal(e, at, self._policy) for e in affecting]
        if not healthy:
            why = "news_unhealthy"
        elif decision.action is not Action.NO_EFFECT:
            why = None
        elif not affecting:
            why = "no_event_for_instrument"
        else:
            why = "events_without_effect:" + ",".join(sorted({s.reason for s in per_event}))
        notional = candidate.baseline_notional
        adjusted = None
        if notional is not None and candidate.baseline.allowed:
            adjusted = notional * decision.size_multiplier if decision.allowed else Decimal(0)
        record = decision.to_log_record()
        record.update(candidate.to_dict())
        record.update(
            {
                "decision_time": _iso(at),
                "evaluated_at": _iso(now),
                "evaluation_lag_seconds": round((now - at).total_seconds(), 3),
                "news_healthy": healthy,
                "why_no_effect": why,
                "hypothetical_adjusted_notional": None if adjusted is None else str(adjusted),
                "events_at_decision": [
                    {
                        "event_id": s.event_id,
                        "category": s.category.value,
                        "action": s.action.value,
                        "size_multiplier": str(s.size_multiplier),
                        "effective_severity": round(s.effective_severity, 6),
                        "reason": s.reason,
                    }
                    for s in per_event
                ],
                "config_fingerprint": self.fingerprint,
            }
        )
        return record

    # -- 9. state, daily summary and reports --------------------------------------------------

    def _state(self, now: datetime) -> Dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "runner_version": RUNNER_VERSION,
            "saved_at": _iso(now),
            "started_at": _iso(self._started_at),
            "cycle": self._cycle,
            "book": self._book.to_state(),
            "processed": self._processed,
            "health": [[_iso(t), h] for t, h in self._health],
            "triage_cache": self._triage_cache,
            "last_event_signal": self._last_event_signal,
            "last_instrument_signal": self._last_instrument_signal,
            "source_last": self._source_last,
            "last_report_at": _iso(self._last_report_at),
            "summary_day": self._summary_day,
            "clock_ok_at": _iso(self._clock_ok_at),
        }

    def _save_state(self, now: datetime) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_file
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self._state(now), sort_keys=True, default=str), encoding="utf-8")
        os.replace(tmp, path)

    def _load_state(self) -> bool:
        path = self.state_file
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
                raise ValueError("unknown state version")
            book = EventBook.from_state(data.get("book") or [], item_cap=self.settings.story_item_cap)
            health = [(_parse(t), bool(h)) for t, h in data.get("health") or []]
            if any(t is None for t, _ in health):
                raise ValueError("bad health timestamps")
        except Exception as exc:  # unreadable state: start empty (no events -> no effect), keep the file
            aside = path.with_name(f"{path.name}.unreadable-{datetime.now(tz=timezone.utc):%Y%m%dT%H%M%SZ}")
            try:
                os.replace(path, aside)
            except OSError:
                pass
            self._log.write_event("runner_event", event="state_reset", error_type=type(exc).__name__, moved_to=aside.name)
            return False
        self._book = book
        self._health = health  # type: ignore[assignment]
        self._started_at = _parse(data.get("started_at"))
        self._cycle = int(data.get("cycle") or 0)
        self._processed = {str(k): str(v) for k, v in dict(data.get("processed") or {}).items()}
        self._triage_cache = {str(k): dict(v) for k, v in dict(data.get("triage_cache") or {}).items()}
        self._last_event_signal = {str(k): str(v) for k, v in dict(data.get("last_event_signal") or {}).items()}
        self._last_instrument_signal = {str(k): str(v) for k, v in dict(data.get("last_instrument_signal") or {}).items()}
        self._source_last = {str(k): str(v) for k, v in dict(data.get("source_last") or {}).items()}
        self._last_report_at = _parse(data.get("last_report_at"))
        self._summary_day = data.get("summary_day")
        self._clock_ok_at = _parse(data.get("clock_ok_at"))
        return True

    def _daily_summary_on_rollover(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self._summary_day is None:
            self._summary_day = today
            return
        if self._summary_day == today:
            return
        finished_day = date.fromisoformat(self._summary_day)
        self._summary_day = today
        try:
            from app.news.report import build_report_data

            data = build_report_data(self._log.root, self._journal.journal_dir, finished_day)
            self._log.write_event("daily_summary", for_day=finished_day.isoformat(), summary=data["headline"])
        except Exception as exc:  # the summary is a convenience; the report itself is rebuilt from logs
            self._log.write_event("runner_event", event="daily_summary_failed", error_type=type(exc).__name__)

    def _write_reports(self, now: datetime, force: bool = False) -> None:
        if self._report_writer is None:
            return
        due = (
            force
            or self._last_report_at is None
            or (now - self._last_report_at).total_seconds() >= self.settings.report_every_seconds
            or self._last_report_at.date() != now.date()
        )
        if not due:
            return
        self._report_writer(now.date())
        yesterday = now.date() - timedelta(days=1)
        # Yesterday's late decisions get their later price path once the journal has it.
        if now < datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc) + timedelta(
            hours=self.settings.report_horizon_hours + 1
        ):
            self._report_writer(yesterday)
        self._last_report_at = now
