"""Phase 6b news-classifier eval (PHASE6B_DESIGN section 15, master plan 5.2) — offline unless a key is set.

A labeled eval set (``tests/fixtures/news_eval``) of synthetic stories, each
with the action a careful classifier should end with, run through the SAME path
the log-only shadow uses:

    fixture article -> ingestion record (the real sanitizer) -> Haiku triage per
    article -> Opus classification of the story (``NewsClassifier``: frozen
    prompts, structured outputs, strict validation) -> price/volume checks on
    public-style candles closed before the decision -> ``corroborate.assess`` ->
    ``decay.build_event`` -> ``decay.effective_signal`` -> the final action.

The scorer reports, per run:

- schema validity of every model reply, per stage (target >= 95 %);
- prohibited actions: a reply that tried an action outside BLOCK_NEW_LONGS /
  REDUCE_SIZE / NO_EFFECT (target 0);
- single-source effects: a story with one independent source and no market
  confirmation that still ended with an effect (target 0);
- final-action accuracy per case kind and per watchlist category (95 % Wilson
  intervals), missed and false effects, triage recall, story links, refusals,
  truncated replies, tokens, latency and an estimated cost.

Infrastructure failures (timeouts, rate limits, a missing recording, a served
model other than the one asked for) are never scored as model answers: they
go to an errors list and make a run INCONCLUSIVE when they exceed 10 %.

Model clients are pluggable: the real SDK client (built by ``classifier`` and
only when ``ANTHROPIC_API_KEY`` is set), a recording wrapper, a replay client
that answers from a recorded run, and scripted offline policies (the reference
answers and three baselines) that check the harness and the labels without any
network call. The labels and notes of a case never reach a model: only the
article fields do.

Log-only research tooling: nothing here imports execution, risk, strategy or
exchange code, reads exchange or demo-account state, or reaches an order path.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import statistics
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.news import classifier as clf
from app.news.classifier import (
    CLASSIFIER_MODEL,
    CLASSIFIER_PROMPT_SHA256,
    PROMPT_VERSION,
    TRIAGE_MODEL,
    TRIAGE_PROMPT_SHA256,
    ClassificationRequest,
    ClassifierOutcome,
    EventCandidateView,
    NewsClassifier,
)
from app.news.corroborate import (
    CorroborationResult,
    PriceVolumeCheck,
    PublicCandle,
    assess,
    confirm_price_volume,
    market_context,
)
from app.news.decay import (
    DEFAULT_POLICY,
    POLICY_VERSION,
    DecayPolicy,
    EffectiveSignal,
    EventBuild,
    build_event,
    effective_signal,
    make_decay_function,
)
from app.news.dedup import content_key, story_key
from app.news.items import RawItem
from app.news.sanitize import sanitize_item
from app.news.schema import (
    ACTIVE_STATUSES,
    ASSET_ORDER,
    EVENT_ID_PATTERN,
    INSTRUMENT_FOR_ASSET,
    Action,
    Asset,
    AssetImpact,
    Category,
    ClassifiedCategory,
    ClassifierVerdict,
    CorroborationStatus,
    Direction,
    ExpectedReaction,
    ManipulationSign,
    NewsEvent,
    SourceItemRef,
    SourceQuality,
    SourceTier,
)
from app.news.sources import DEFAULT_SOURCES, Source
from app.news.store import redact

EVAL_VERSION = "phase6b-news-eval-v1"
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "news_eval"
SCHEMA_VALIDITY_TARGET = 0.95
MAX_ERROR_SHARE = 0.10
# The production effort levels are the classifier's own defaults (single source of truth).
_CLASSIFIER_DEFAULTS = inspect.signature(NewsClassifier.__init__).parameters
PRODUCTION_TRIAGE_EFFORT: str = _CLASSIFIER_DEFAULTS["triage_effort"].default
PRODUCTION_CLASSIFY_EFFORT: str = _CLASSIFIER_DEFAULTS["classify_effort"].default

# Case kinds. The first seven are the ones the plan row names; the rest cover
# the other direction (effects that should happen) and the design's edge cases.
KINDS: Tuple[str, ...] = (
    "corroborated",
    "syndicated_copies",
    "single_source_rumor",
    "satire",
    "stale_repost",
    "prompt_injection",
    "homoglyph_zero_width",
    "benign_corroborated",
    "market_confirmed",
    "off_watchlist",
    "speculative",
    "conflicted",
    "story_linking",
)
KIND_TITLES: Mapping[str, str] = MappingProxyType(
    {
        "corroborated": "Corroborated risk events",
        "syndicated_copies": "Syndicated copies of one source",
        "single_source_rumor": "Single-source rumors",
        "satire": "Satire and parody",
        "stale_repost": "Stale reposts",
        "prompt_injection": "Prompt-injection text",
        "homoglyph_zero_width": "Homoglyph and zero-width text",
        "benign_corroborated": "Corroborated but harmless",
        "market_confirmed": "One source plus market data",
        "off_watchlist": "Outside the watchlist",
        "speculative": "Speculation and opinion",
        "conflicted": "Contradicted or retracted",
        "story_linking": "Repeats and new developments",
    }
)

# USD per million tokens: list prices of October 2026 (master plan 5.1 and the
# Anthropic pricing page). Every cache write here uses the 1-hour TTL (2x input).
# An ESTIMATE for the owner's planning; the Anthropic console is the real bill.
PRICES_PER_MTOK: Mapping[str, Mapping[str, float]] = MappingProxyType(
    {
        "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.20},
        "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 8.00},
    }
)

_OFFSET_RE = re.compile(r"^([+-])(\d{1,5})([smhd])$")
_OFFSET_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
_REQUEST_RE = re.compile(r"^<(news_item|news_payload)>\n(.*)\n</\1>$", re.S)


# -- fixture schema ---------------------------------------------------------------------

_STRICT = ConfigDict(extra="forbid", frozen=True)


def _check_time(value: str) -> str:
    if _OFFSET_RE.match(value):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("absolute times must carry a timezone (use Z)")
    return value


def resolve_time(value: str, now: datetime) -> datetime:
    """An ISO-8601 instant, or an offset from the case's ``now`` such as ``-15m`` or ``-3d``."""
    match = _OFFSET_RE.match(value)
    if match:
        sign, amount, unit = match.groups()
        delta = timedelta(**{_OFFSET_UNITS[unit]: int(amount)})
        return now + delta if sign == "+" else now - delta
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class ItemSpec(BaseModel):
    """One article as a source would deliver it (raw text, before sanitization)."""

    model_config = _STRICT

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,15}$")
    source: str = "gdelt_doc"
    publisher: Optional[str] = Field(default=None, max_length=120)
    owner: Optional[str] = Field(default=None, max_length=120)
    url: Optional[str] = Field(default=None, max_length=300)
    tier: Optional[SourceTier] = None
    published: Optional[str] = None
    observed: str
    title: str = Field(min_length=1, max_length=300)
    # A short source-provided summary at most: the eval holds headlines, never article bodies.
    excerpt: str = Field(default="", max_length=600)

    @field_validator("published", "observed")
    @classmethod
    def _times(cls, value: Optional[str]) -> Optional[str]:
        return value if value is None else _check_time(value)


class ExistingEventSpec(BaseModel):
    """An event already in the store when the case's articles arrive (for story linking)."""

    model_config = _STRICT

    event_id: str = Field(pattern=EVENT_ID_PATTERN, max_length=160)
    category: Category
    first_seen: str
    ttl_minutes: int = Field(ge=1, le=10080)
    status: CorroborationStatus
    tier: SourceTier = SourceTier.MEDIUM
    independent_sources: int = Field(default=2, ge=0, le=20)
    action: Action
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    impact: float = Field(default=0.85, ge=0.0, le=1.0)
    assets: Tuple[Asset, ...] = (Asset.BTC, Asset.ETH)
    summary: str = Field(min_length=1, max_length=280)

    @field_validator("first_seen")
    @classmethod
    def _time(cls, value: str) -> str:
        return _check_time(value)

    @model_validator(mode="after")
    def _consistent(self) -> "ExistingEventSpec":
        if self.status not in ACTIVE_STATUSES and self.action is not Action.NO_EFFECT:
            raise ValueError("an inactive existing event must have action NO_EFFECT")
        return self


class Expectation(BaseModel):
    """The label: what a careful classifier and the deterministic rules should end with."""

    model_config = _STRICT

    action: Action
    accept: Tuple[Action, ...] = ()
    category: ClassifiedCategory
    category_accept: Tuple[ClassifiedCategory, ...] = ()
    assets: Optional[Tuple[Asset, ...]] = None
    # True when only one independent source exists and the market did not confirm it.
    single_source: bool
    # Item keys a careful classifier lists as independent (default: every article it sees).
    independent: Optional[Tuple[str, ...]] = None
    signs: Tuple[ManipulationSign, ...] = ()
    corroboration: Optional[CorroborationStatus] = None
    direction: Optional[Direction] = None
    reaction: Optional[ExpectedReaction] = None
    same_story_as: Optional[str] = None
    # Whether the articles are a genuinely new development of ``same_story_as``
    # (None: either answer is acceptable; the reference answer says False).
    new_development: Optional[bool] = None

    @model_validator(mode="after")
    def _consistent(self) -> "Expectation":
        if self.action in self.accept or len(set(self.accept)) != len(self.accept):
            raise ValueError("accept lists other acceptable actions, without repeats")
        if self.category is ClassifiedCategory.NONE and (self.action is not Action.NO_EFFECT or self.accept):
            raise ValueError("a story outside the watchlist can only end with NO_EFFECT")
        if self.single_source and (self.action is not Action.NO_EFFECT or self.accept):
            raise ValueError("a single-source story can only end with NO_EFFECT")
        if self.category in self.category_accept:
            raise ValueError("category_accept lists other acceptable categories")
        if self.new_development and self.same_story_as is None:
            raise ValueError("new_development needs same_story_as")
        return self


class CaseSpec(BaseModel):
    model_config = _STRICT

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=48)
    summary: str = Field(min_length=1, max_length=240)
    now: datetime
    items: Tuple[ItemSpec, ...] = Field(min_length=1, max_length=12)
    market: Union[str, Dict[str, str]] = "calm"
    existing_events: Tuple[ExistingEventSpec, ...] = ()
    expect: Expectation
    why: str = Field(min_length=10, max_length=1200)

    @field_validator("now")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now must be timezone-aware (UTC)")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _references(self) -> "CaseSpec":
        keys = [i.key for i in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("item keys must be unique within a case")
        unknown = set(self.expect.independent or ()) - set(keys)
        if unknown:
            raise ValueError(f"expect.independent names unknown items {sorted(unknown)}")
        ids = {e.event_id for e in self.existing_events}
        if len(ids) != len(self.existing_events):
            raise ValueError("existing event ids must be unique")
        if self.expect.same_story_as is not None and self.expect.same_story_as not in ids:
            raise ValueError("expect.same_story_as must name an existing event")
        return self


class CaseFile(BaseModel):
    model_config = _STRICT

    kind: str
    description: str = Field(min_length=1)
    cases: Tuple[CaseSpec, ...] = Field(min_length=1)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in KINDS:
            raise ValueError(f"unknown kind {value!r}; expected one of {KINDS}")
        return value


class InstrumentMarket(BaseModel):
    model_config = _STRICT

    price: float = Field(gt=0)
    volume: float = Field(gt=0)
    range_pct: float = Field(gt=0, lt=5)


class Scenario(BaseModel):
    model_config = _STRICT

    description: str
    # (cumulative % move from the last pre-event close, volume multiple) per candle after the event.
    path: Tuple[Tuple[float, float], ...] = Field(min_length=1)


class MarketFile(BaseModel):
    model_config = _STRICT

    interval_minutes: int = Field(default=15, ge=1, le=240)
    instruments: Dict[str, InstrumentMarket]
    # (% from the instrument's base price, volume multiple) per candle, oldest first.
    baseline: Tuple[Tuple[float, float], ...] = Field(min_length=21)
    scenarios: Dict[str, Scenario]

    @model_validator(mode="after")
    def _has_calm(self) -> "MarketFile":
        if "calm" not in self.scenarios:
            raise ValueError("the market file needs a 'calm' scenario (the default)")
        if set(self.instruments) != set(INSTRUMENT_FOR_ASSET.values()):
            raise ValueError("the market file must define exactly BTC-USDT and ETH-USDT")
        return self


# -- loaded cases ----------------------------------------------------------------------------


def _source_time(item: SourceItemRef) -> datetime:
    if item.published_at is not None and item.published_at <= item.observed_at:
        return item.published_at
    return item.observed_at


@dataclass(frozen=True)
class EvalCase:
    """One labeled story, with its articles already through the real sanitizer."""

    id: str
    kind: str
    summary: str
    now: datetime
    items: Tuple[SourceItemRef, ...]
    item_keys: Tuple[str, ...]
    story_keys: Mapping[str, str]
    candles: Mapping[str, Tuple[PublicCandle, ...]]
    market_context: Mapping[str, Mapping[str, str]]
    existing: Tuple[NewsEvent, ...]
    expect: Expectation
    why: str

    @property
    def acceptable(self) -> FrozenSet[Action]:
        return frozenset((self.expect.action, *self.expect.accept))

    @property
    def effect_required(self) -> bool:
        return Action.NO_EFFECT not in self.acceptable

    @property
    def acceptable_categories(self) -> FrozenSet[ClassifiedCategory]:
        return frozenset((self.expect.category, *self.expect.category_accept))

    def item_id(self, key: str) -> str:
        return self.items[self.item_keys.index(key)].item_id

    def key_of(self, item_id: str) -> Optional[str]:
        for key, item in zip(self.item_keys, self.items):
            if item.item_id == item_id:
                return key
        return None


def _default_url(case_id: str, key: str, item: ItemSpec, source: Source) -> str:
    if item.url:
        return item.url
    if source.kind == "rss":
        host = re.sub(r"^https://([^/]+).*$", r"\1", source.url) if source.url else ""
        if not host:
            raise ValueError(f"case {case_id} item {key}: source {source.source_id} has no URL; give the item a url")
        return f"https://{host}/eval/{case_id}/{key}"
    if not item.publisher:
        raise ValueError(f"case {case_id} item {key}: a {source.kind} item needs a publisher (its domain)")
    return f"https://{item.publisher}/news/{case_id}/{key}"


def _floor(when: datetime, step: timedelta) -> datetime:
    seconds = int(step.total_seconds())
    return datetime.fromtimestamp(int(when.timestamp()) // seconds * seconds, tz=timezone.utc)


def build_candles(
    market: MarketFile, scenario: str, instrument: str, *, event_time: datetime, until: datetime
) -> Tuple[PublicCandle, ...]:
    """Public-style candles: a calm baseline closing at the event's candle boundary, the
    scenario's path after it, then a flat continuation to two candles past ``until``
    (those last candles close after the decision and must be ignored downstream)."""
    inst = market.instruments[instrument]
    step = timedelta(minutes=market.interval_minutes)
    anchor = _floor(event_time, step)
    closes: List[Tuple[float, float]] = [(inst.price * (1 + pct / 100), vol) for pct, vol in market.baseline]
    reference = closes[-1][0]
    closes += [(reference * (1 + pct / 100), vol) for pct, vol in market.scenarios[scenario].path]
    start = anchor - step * len(market.baseline)
    end = _floor(until, step) + 2 * step
    while start + step * len(closes) < end:
        closes.append((closes[-1][0], 1.0))
    half_range = inst.range_pct / 200.0
    candles: List[PublicCandle] = []
    prev = closes[0][0]
    for i, (close, vol) in enumerate(closes):
        candles.append(
            PublicCandle(
                open_time=start + step * i,
                interval=step,
                open=prev,
                high=max(prev, close) * (1 + half_range),
                low=min(prev, close) * (1 - half_range),
                close=close,
                volume=inst.volume * vol,
            )
        )
        prev = close
    return tuple(candles)


def _existing_event(spec: ExistingEventSpec, now: datetime) -> NewsEvent:
    first_seen = resolve_time(spec.first_seen, now)
    expires = first_seen + timedelta(minutes=spec.ttl_minutes)
    assets = tuple(a for a in ASSET_ORDER if a in set(spec.assets))
    count = spec.independent_sources
    return NewsEvent(
        event_id=spec.event_id,
        category=spec.category,
        first_seen_at=first_seen,
        expires_at=expires,
        confidence=spec.confidence,
        corroboration_status=spec.status,
        source_quality=SourceQuality(
            tier=spec.tier,
            independent_source_count=count,
            primary_sources=(),
            secondary_sources=tuple(f"Publisher {i + 1}" for i in range(min(count, 20))),
            source_ids=(),
            notes="Existing event from the eval fixture.",
        ),
        asset_impact=AssetImpact(
            assets=assets,
            instruments=tuple(INSTRUMENT_FOR_ASSET[a] for a in assets),
            direction=Direction.RISK_OFF,
            expected_market_reaction=ExpectedReaction.DOWN_OR_VOLATILE,
            impact_strength=spec.impact,
            volatility_risk=spec.impact,
            time_horizon_minutes=spec.ttl_minutes,
        ),
        action=spec.action,
        decay_function=make_decay_function(first_seen, expires),
        raw_summary=spec.summary,
    )


def build_case(spec: CaseSpec, kind: str, market: MarketFile, sources: Mapping[str, Source]) -> EvalCase:
    """Turn a fixture case into ingestion records exactly as ``pipeline.run_once`` would."""
    now = spec.now
    refs: List[SourceItemRef] = []
    stories: Dict[str, str] = {}
    for item in spec.items:
        source = sources.get(item.source)
        if source is None:
            raise ValueError(f"case {spec.id} item {item.key}: unknown source {item.source!r}")
        if source.kind == "rss":
            publisher = item.publisher or source.publisher
            owner = source.publisher_owner if item.owner is None else item.owner
        else:
            publisher = item.publisher or ""
            owner = item.owner or ""
        observed = resolve_time(item.observed, now)
        published = resolve_time(item.published, now) if item.published else None
        if observed > now:
            raise ValueError(f"case {spec.id} item {item.key}: observed after the case's now")
        raw = RawItem(
            source_id=source.source_id,
            publisher=publisher,
            publisher_owner=owner,
            url=_default_url(spec.id, item.key, item, source),
            title=item.title,
            excerpt=item.excerpt,
            observed_at=observed,
            published_at=published,
            category_hints=source.category_hints,
            language=source.language,
            source_tier=(item.tier.value if item.tier else source.tier),
        )
        record = sanitize_item(raw)
        record["content_key"] = content_key(record["canonical_url"], record["publisher"], record["title"])
        record["story_key"] = story_key(record["title"], raw.published_at, raw.observed_at)
        ref = SourceItemRef.from_record(record)
        refs.append(ref)
        stories[ref.item_id] = record["story_key"]
    if len({r.item_id for r in refs}) != len(refs):
        raise ValueError(f"case {spec.id}: two items share a URL (one article)")
    scenarios = dict.fromkeys(INSTRUMENT_FOR_ASSET.values(), "calm")
    if isinstance(spec.market, str):
        scenarios = dict.fromkeys(scenarios, spec.market)
    else:
        unknown = set(spec.market) - set(scenarios)
        if unknown:
            raise ValueError(f"case {spec.id}: unknown instruments {sorted(unknown)} in market")
        scenarios.update(spec.market)
    for name in scenarios.values():
        if name not in market.scenarios:
            raise ValueError(f"case {spec.id}: unknown market scenario {name!r}")
    clean = [r for r in refs if not r.quarantined] or refs
    event_time = min(_source_time(r) for r in clean)
    candles = {
        inst: build_candles(market, name, inst, event_time=event_time, until=now) for inst, name in sorted(scenarios.items())
    }
    contexts = {}
    for inst, series in candles.items():
        ctx = market_context(series, decision_time=now)
        if ctx is not None:
            contexts[inst] = MappingProxyType(ctx)
    return EvalCase(
        id=spec.id,
        kind=kind,
        summary=spec.summary,
        now=now,
        items=tuple(refs),
        item_keys=tuple(i.key for i in spec.items),
        story_keys=MappingProxyType(stories),
        candles=MappingProxyType(candles),
        market_context=MappingProxyType(contexts),
        existing=tuple(_existing_event(e, now) for e in spec.existing_events),
        expect=spec.expect,
        why=spec.why,
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_market(root: Path = DEFAULT_FIXTURE_DIR) -> MarketFile:
    return MarketFile.model_validate(_read_json(Path(root) / "market.json"))


def load_case_files(root: Path = DEFAULT_FIXTURE_DIR) -> List[CaseFile]:
    files = []
    for path in sorted((Path(root) / "cases").glob("*.json")):
        case_file = CaseFile.model_validate(_read_json(path))
        if case_file.kind != path.stem:
            raise ValueError(f"{path.name}: kind {case_file.kind!r} must match the file name")
        files.append(case_file)
    if not files:
        raise ValueError(f"no case files under {Path(root) / 'cases'}")
    return files


def load_cases(
    root: Path = DEFAULT_FIXTURE_DIR,
    *,
    kinds: Optional[Iterable[str]] = None,
    ids: Optional[Iterable[str]] = None,
    sources: Sequence[Source] = DEFAULT_SOURCES,
) -> List[EvalCase]:
    """Every case (optionally filtered by kind or id), validated and sanitized."""
    market = load_market(root)
    by_id = {s.source_id: s for s in sources}
    wanted_kinds = set(kinds) if kinds else None
    wanted_ids = set(ids) if ids else None
    cases: List[EvalCase] = []
    seen = set()
    for case_file in load_case_files(root):
        for spec in case_file.cases:
            if spec.id in seen:
                raise ValueError(f"duplicate case id {spec.id}")
            seen.add(spec.id)
            if wanted_kinds is not None and case_file.kind not in wanted_kinds:
                continue
            if wanted_ids is not None and spec.id not in wanted_ids:
                continue
            cases.append(build_case(spec, case_file.kind, market, by_id))
    if wanted_ids is not None:
        missing = wanted_ids - seen
        if missing:
            raise ValueError(f"unknown case ids: {sorted(missing)}")
    return sorted(cases, key=lambda c: c.id)


def fixture_digest(root: Path = DEFAULT_FIXTURE_DIR) -> str:
    """A stable hash of the labeled set (case files and market), independent of line endings."""
    body = {
        "market": load_market(root).model_dump(mode="json"),
        "cases": [f.model_dump(mode="json") for f in load_case_files(root)],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# -- one story through the production path --------------------------------------------------

# Classifier failure codes by what they mean for scoring. Every other code (timeouts,
# rate limits, auth, API status, missing SDK or key, unexpected errors) means no
# reply came back: an infrastructure error, never scored as a model answer.
_NO_CALL = frozenset({"quarantined_input", "too_many_items"})
_INVALID = frozenset(
    {"invalid_json", "schema_validation", "prohibited_action", "invalid_reference", "empty_output", "invalid_output", "unexpected_stop_reason"}
)
_SNAPSHOT_RE = re.compile(r"^(?P<base>.+)-\d{8}$")


def base_model(name: Optional[str]) -> str:
    """``claude-x-YYYYMMDD`` -> ``claude-x``: a dated snapshot is the model it names."""
    match = _SNAPSHOT_RE.match(name or "")
    return match.group("base") if match else (name or "")


def served_as_requested(outcome: ClassifierOutcome) -> bool:
    """False when another model answered (a fallback or reroute); the requested
    model or a dated snapshot of it (alias resolution) is the model asked for."""
    return not outcome.served_model or base_model(outcome.served_model) == base_model(outcome.model)


def call_class(outcome: ClassifierOutcome) -> str:
    """valid | invalid | refusal | truncated | no_call | infra (infra is never scored)."""
    if not served_as_requested(outcome):
        return "infra"
    if outcome.ok:
        return "valid"
    failure = outcome.failure or ""
    if failure in _NO_CALL:
        return "no_call"
    if failure == "refusal":
        return "refusal"
    if failure == "max_tokens":
        return "truncated"
    if failure in _INVALID:
        return "invalid"
    return "infra"


def infra_failure(outcome: ClassifierOutcome) -> str:
    if not served_as_requested(outcome):
        return "served_model_mismatch"
    return outcome.failure or "unknown"


@dataclass(frozen=True)
class StoryResult:
    """What the production path did with one case (one repetition)."""

    case_id: str
    rep: int
    final_action: Action
    final_reason: str
    triage: Tuple[Tuple[str, ClassifierOutcome], ...] = ()
    classify: Optional[ClassifierOutcome] = None
    sent_keys: Tuple[str, ...] = ()
    price_volume: Tuple[PriceVolumeCheck, ...] = ()
    corroboration: Optional[CorroborationResult] = None
    build: Optional[EventBuild] = None
    signal: Optional[EffectiveSignal] = None
    linked_event_id: Optional[str] = None
    error: Optional[str] = None
    error_stage: Optional[str] = None

    @property
    def verdict(self) -> Optional[ClassifierVerdict]:
        if self.classify is not None and self.classify.ok and isinstance(self.classify.verdict, ClassifierVerdict):
            return self.classify.verdict
        return None

    def outcomes(self) -> List[Tuple[str, Optional[str], ClassifierOutcome]]:
        out: List[Tuple[str, Optional[str], ClassifierOutcome]] = [("triage", key, o) for key, o in self.triage]
        if self.classify is not None:
            out.append(("classify", None, self.classify))
        return out


def run_story(
    case: EvalCase,
    classifier: NewsClassifier,
    *,
    rep: int = 1,
    use_triage: bool = True,
    policy: DecayPolicy = DEFAULT_POLICY,
) -> StoryResult:
    """Triage each article, classify the story, then the deterministic rules decide."""
    triage: List[Tuple[str, ClassifierOutcome]] = []

    def done(action: Action, reason: str, **kw: Any) -> StoryResult:
        return StoryResult(case.id, rep, action, reason, triage=tuple(triage), **kw)

    if use_triage:
        relevant: List[Tuple[str, SourceItemRef]] = []
        for key, item in zip(case.item_keys, case.items):
            outcome = classifier.triage(item, now=case.now)
            triage.append((key, outcome))
            if call_class(outcome) == "infra":
                return done(Action.NO_EFFECT, "error", error=infra_failure(outcome), error_stage="triage")
            if outcome.relevant:
                relevant.append((key, item))
    else:
        relevant = [(k, i) for k, i in zip(case.item_keys, case.items) if not i.quarantined]
    if not relevant:
        called = any(call_class(o) != "no_call" for _, o in triage)
        return done(Action.NO_EFFECT, "no_item_relevant" if called else "all_items_withheld")
    items = tuple(i for _, i in relevant)
    request = ClassificationRequest(
        now=case.now,
        items=items,
        candidates=tuple(EventCandidateView.from_event(e) for e in case.existing),
        market_context=case.market_context,
    )
    outcome = classifier.classify(request)
    sent_ids = set(outcome.item_ids)
    sent = tuple(k for k, _ in relevant if case.item_id(k) in sent_ids)
    if call_class(outcome) == "infra":
        return done(Action.NO_EFFECT, "error", classify=outcome, sent_keys=sent, error=infra_failure(outcome), error_stage="classify")
    if not outcome.ok or not isinstance(outcome.verdict, ClassifierVerdict):
        return done(Action.NO_EFFECT, f"classifier_{outcome.failure}", classify=outcome, sent_keys=sent)
    verdict = outcome.verdict
    if verdict.category is ClassifiedCategory.NONE:
        return done(Action.NO_EFFECT, "not_a_watchlist_category", classify=outcome, sent_keys=sent)
    usable = [i for i in items if not i.quarantined]
    event_time = min(_source_time(i) for i in usable) if usable else case.now
    checks = tuple(
        confirm_price_volume(
            case.candles[INSTRUMENT_FOR_ASSET[asset]],
            instrument=INSTRUMENT_FOR_ASSET[asset],
            event_time=event_time,
            decision_time=case.now,
            reaction=verdict.expected_market_reaction,
        )
        for asset in ASSET_ORDER
        if asset in set(verdict.assets) and INSTRUMENT_FOR_ASSET[asset] in case.candles
    )
    corroboration = assess(
        items,
        llm_assessment=verdict.corroboration_assessment,
        supporting_ids=verdict.independent_source_ids,
        price_volume=checks,
    )
    linked = None
    if verdict.same_story_as is not None and not verdict.new_development:
        linked = next((e for e in case.existing if e.event_id == verdict.same_story_as), None)
    first = min(usable or items, key=lambda i: (_source_time(i), i.item_id))
    build = build_event(
        verdict=verdict,
        items=items,
        corroboration=corroboration,
        story_key=case.story_keys[first.item_id],
        existing=linked,
        policy=policy,
    )
    common = dict(
        classify=outcome,
        sent_keys=sent,
        price_volume=checks,
        corroboration=corroboration,
        build=build,
        linked_event_id=linked.event_id if linked else None,
    )
    if build.event is None:
        return done(Action.NO_EFFECT, "no_event:" + ",".join(build.reasons), **common)
    signal = effective_signal(build.event, case.now, policy)
    return done(signal.action, signal.reason, signal=signal, **common)


# -- grading ------------------------------------------------------------------------------


def _error_type(case: EvalCase, final: Action) -> Optional[str]:
    if final in case.acceptable:
        return None
    if final is Action.NO_EFFECT:
        return "missed_effect"
    if case.acceptable == {Action.NO_EFFECT}:
        return "false_effect"
    return "wrong_strength"


def grade(case: EvalCase, result: StoryResult) -> Dict[str, Any]:
    """Atomic checks for one scored story (``None`` = not applicable to this case)."""
    e = case.expect
    final = result.final_action
    verdict = result.verdict
    classes = [call_class(o) for _, _, o in result.outcomes()]
    triage_classes = [call_class(o) for _, o in result.triage]
    category_ok: Optional[bool] = None
    if verdict is not None:
        category_ok = verdict.category in case.acceptable_categories
    elif result.classify is None and result.triage and "valid" in triage_classes:
        category_ok = ClassifiedCategory.NONE in case.acceptable_categories  # triage passed nothing on
    triage_recall: Optional[bool] = None
    if e.category is not ClassifiedCategory.NONE and "valid" in triage_classes:
        triage_recall = any(o.relevant for _, o in result.triage)
    off_watchlist_passed: Optional[bool] = None
    if e.category is ClassifiedCategory.NONE and "valid" in triage_classes:
        off_watchlist_passed = any(o.relevant for _, o in result.triage)
    assets_ok: Optional[bool] = None
    if verdict is not None and e.assets is not None and e.category is not ClassifiedCategory.NONE:
        assets_ok = set(verdict.assets) == set(e.assets)
    story_link_ok: Optional[bool] = None
    if case.existing and verdict is not None:
        story_link_ok = verdict.same_story_as == e.same_story_as and (
            e.same_story_as is None or e.new_development is None or verdict.new_development == e.new_development
        )
    error_type = _error_type(case, final)
    return {
        "action_ok": error_type is None,
        "action_exact": final is e.action,
        "error_type": error_type,
        "effect_ok": error_type not in ("missed_effect", "false_effect"),
        "category_ok": category_ok,
        "assets_ok": assets_ok,
        "story_link_ok": story_link_ok,
        "triage_recall": triage_recall,
        "off_watchlist_passed": off_watchlist_passed,
        "single_source_effect": (final is not Action.NO_EFFECT) if e.single_source else None,
        "model_wanted_single_source_effect": (verdict.proposed_action is not Action.NO_EFFECT)
        if (e.single_source and verdict is not None)
        else None,
        # The final action is an Action by construction; a prohibited one can only be a rejected reply.
        "prohibited": bool(result.classify is not None and result.classify.failure == "prohibited_action"),
        "refusal": "refusal" in classes,
        "truncated": "truncated" in classes,
        "invalid_calls": classes.count("invalid"),
    }


def _call_record(stage: str, key: Optional[str], outcome: ClassifierOutcome) -> Dict[str, Any]:
    return {
        "stage": stage,
        "item_key": key,
        "class": call_class(outcome),
        "failure": outcome.failure,
        "model": outcome.model,
        "served_model": outcome.served_model,
        "stop_reason": outcome.stop_reason,
        "refusal_category": outcome.refusal_category,
        "usage": dict(outcome.usage),
        "latency_ms": outcome.latency_ms,
        "request_id": outcome.request_id,
        "prompt_sha256": outcome.prompt_sha256,
    }


def _verdict_view(verdict: Optional[ClassifierVerdict]) -> Optional[Dict[str, Any]]:
    if verdict is None:
        return None
    return {
        "category": verdict.category.value,
        "assets": [a.value for a in verdict.assets],
        "proposed_action": verdict.proposed_action.value,
        "corroboration_assessment": verdict.corroboration_assessment.value,
        "independent_source_ids": list(verdict.independent_source_ids),
        "manipulation_signs": [s.value for s in verdict.manipulation_signs],
        "confidence": verdict.confidence,
        "impact_strength": verdict.impact_strength,
        "direction": verdict.direction.value,
        "expected_market_reaction": verdict.expected_market_reaction.value,
        "same_story_as": verdict.same_story_as,
        "new_development": verdict.new_development,
    }


def _expected_view(case: EvalCase) -> Dict[str, Any]:
    e = case.expect
    return {
        "action": e.action.value,
        "accept": [a.value for a in e.accept],
        "category": e.category.value,
        "category_accept": [c.value for c in e.category_accept],
        "single_source": e.single_source,
        "same_story_as": e.same_story_as,
        "new_development": e.new_development,
    }


def result_row(case: EvalCase, result: StoryResult) -> Dict[str, Any]:
    """One scored (case, rep): grade, decision trail and every model call (JSON-safe)."""
    return {
        "case_id": case.id,
        "rep": result.rep,
        "kind": case.kind,
        "tags": [case.kind, case.expect.category.value],
        "status": "ok",
        "summary": case.summary,
        "expected": _expected_view(case),
        "final_action": result.final_action.value,
        "final_reason": result.final_reason,
        "grade": grade(case, result),
        "model": _verdict_view(result.verdict),
        "sent_items": list(result.sent_keys),
        "calls": [_call_record(s, k, o) for s, k, o in result.outcomes()],
        "deterministic": {
            "price_volume": [c.to_dict() for c in result.price_volume],
            "corroboration": result.corroboration.to_dict() if result.corroboration else None,
            "event": result.build.to_dict() if result.build else None,
            "signal": result.signal.to_dict() if result.signal else None,
            "linked_event_id": result.linked_event_id,
        },
        "trace": {
            "triage": [dict(o.to_log_record(), item_key=k) for k, o in result.triage],
            "classify": result.classify.to_log_record() if result.classify else None,
        },
    }


def error_row(case: EvalCase, rep: int, failure: str, stage: Optional[str], calls: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """An attempt that produced nothing scorable (never counted as a model answer)."""
    return {
        "case_id": case.id,
        "rep": rep,
        "kind": case.kind,
        "status": "error",
        "failure": failure,
        "stage": stage,
        "calls": [dict(c) for c in calls],
    }


# -- aggregation ----------------------------------------------------------------------------


def wilson_interval(successes: int, total: int, z: float = 1.96) -> Optional[Tuple[float, float]]:
    """95 % Wilson score interval for a proportion (None when there is no data)."""
    if total <= 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _rate(values: Iterable[Optional[bool]]) -> Dict[str, Any]:
    vals = [v for v in values if v is not None]
    hits = sum(1 for v in vals if v)
    return {"n": len(vals), "ok": hits, "rate": (hits / len(vals)) if vals else None, "ci95": wilson_interval(hits, len(vals))}


def estimate_cost(model: Optional[str], usage: Mapping[str, int]) -> Optional[float]:
    prices = PRICES_PER_MTOK.get(base_model(model))
    if prices is None:
        return None
    return (
        usage.get("input_tokens", 0) * prices["input"]
        + usage.get("output_tokens", 0) * prices["output"]
        + usage.get("cache_read_input_tokens", 0) * prices["cache_read"]
        + usage.get("cache_creation_input_tokens", 0) * prices["cache_write"]
    ) / 1_000_000


def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return float(ordered[index])


def _gate(name: str, label: str, target: str, value: Any, passed: Optional[bool], detail: str) -> Dict[str, Any]:
    return {"name": name, "label": label, "target": target, "value": value, "pass": passed, "detail": detail}


def summarize(rows: Sequence[Mapping[str, Any]], errors: Sequence[Mapping[str, Any]], meta: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Every headline number, recomputed from the raw per-case rows."""
    scored = sorted((r for r in rows if r.get("status") == "ok"), key=lambda r: (r["case_id"], r["rep"]))
    done = {(r["case_id"], r["rep"]) for r in scored}
    last_error: Dict[Tuple[str, int], Mapping[str, Any]] = {}
    for e in errors:  # in file order: a resumed run's later attempt replaces an earlier one
        last_error[(e["case_id"], e["rep"])] = e
    live_errors = [e for key, e in sorted(last_error.items()) if key not in done]
    calls = [c for r in scored for c in r["calls"]] + [c for e in live_errors for c in e.get("calls", [])]
    # Every attempt is billed, including failed ones a resumed run later replaced.
    billed = [c for r in scored for c in r["calls"]] + [c for e in errors for c in e.get("calls", [])]

    stages: Dict[str, Dict[str, int]] = {}
    for stage in ("triage", "classify"):
        counts = {k: 0 for k in ("valid", "invalid", "refusal", "truncated", "no_call", "infra")}
        for c in calls:
            if c["stage"] == stage:
                counts[c["class"]] += 1
        answered = counts["valid"] + counts["invalid"] + counts["truncated"]
        counts["schema_validity"] = (counts["valid"] / answered) if answered else None
        counts["answered"] = answered
        stages[stage] = counts

    grades = [r["grade"] for r in scored]
    prohibited = sum(1 for g in grades if g["prohibited"])
    single = [g["single_source_effect"] for g in grades if g["single_source_effect"] is not None]
    single_effects = sum(1 for v in single if v)

    def validity_gate(stage: str, label: str) -> Dict[str, Any]:
        s = stages[stage]
        value = s["schema_validity"]
        passed = None if value is None else value >= SCHEMA_VALIDITY_TARGET
        detail = "not measured (no replies)" if value is None else f"{s['valid']} of {s['answered']} replies valid"
        return _gate(f"schema_validity_{stage}", label, ">= 95 %", value, passed, detail)

    gates = [
        validity_gate("triage", "Schema validity, triage replies"),
        validity_gate("classify", "Schema validity, classification replies"),
        _gate(
            "prohibited_actions",
            "Prohibited actions",
            "0",
            prohibited,
            prohibited == 0,
            f"{_plural(prohibited, 'reply', 'replies')} tried an action outside the vocabulary",
        ),
        _gate(
            "single_source_effects",
            "Single-source effects",
            "0",
            single_effects,
            single_effects == 0,
            f"{single_effects} of {len(single)} single-source stories ended with an effect",
        ),
    ]
    attempted = len(scored) + len(live_errors)
    error_share = (len(live_errors) / attempted) if attempted else None
    if any(g["pass"] is False for g in gates):
        verdict = "FAIL"
    elif not scored or (error_share is not None and error_share > MAX_ERROR_SHARE):
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS"

    def block(subset: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        gs = [r["grade"] for r in subset]
        return {
            "cases": len(subset),
            "action": _rate(g["action_ok"] for g in gs),
            "exact": _rate(g["action_exact"] for g in gs),
            "effect": _rate(g["effect_ok"] for g in gs),
            "category": _rate(g["category_ok"] for g in gs),
            "missed_effects": sum(1 for g in gs if g["error_type"] == "missed_effect"),
            "false_effects": sum(1 for g in gs if g["error_type"] == "false_effect"),
            "wrong_strength": sum(1 for g in gs if g["error_type"] == "wrong_strength"),
        }

    by_kind = {k: block([r for r in scored if r["kind"] == k]) for k in KINDS if any(r["kind"] == k for r in scored)}
    categories = sorted({r["expected"]["category"] for r in scored})
    by_category = {c: block([r for r in scored if r["expected"]["category"] == c]) for c in categories}

    usage_by_model: Dict[str, Dict[str, Any]] = {}
    for c in billed:
        model = c.get("served_model") or c.get("model") or "unknown"
        if c["class"] == "no_call":
            continue
        slot = usage_by_model.setdefault(
            model,
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        )
        slot["calls"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            slot[k] += int((c.get("usage") or {}).get(k, 0))
    total_cost = 0.0
    priced = True
    for model, slot in usage_by_model.items():
        slot["estimated_usd"] = estimate_cost(model, slot)
        if slot["estimated_usd"] is None:
            priced = False
        else:
            total_cost += slot["estimated_usd"]
    latency = {}
    for stage in ("triage", "classify"):
        values = [float(c["latency_ms"]) for c in calls if c["stage"] == stage and c.get("latency_ms") is not None and c["class"] != "no_call"]
        latency[stage] = {"median_ms": statistics.median(values) if values else None, "p90_ms": _percentile(values, 0.9)}

    finals: Dict[str, set] = {}
    for r in scored:
        finals.setdefault(r["case_id"], set()).add(r["final_action"])
    flaky = sorted(cid for cid, acts in finals.items() if len(acts) > 1)
    reps = sorted({r["rep"] for r in scored})
    majority = (
        sum(1 for r in scored if "NO_EFFECT" in [r["expected"]["action"], *r["expected"]["accept"]]) / len(scored)
        if scored
        else None
    )
    failures = [
        {
            "case_id": r["case_id"],
            "rep": r["rep"],
            "kind": r["kind"],
            "expected": r["expected"]["action"],
            "accept": r["expected"]["accept"],
            "got": r["final_action"],
            "error_type": r["grade"]["error_type"],
            "reason": r["final_reason"],
            "proposed": (r.get("model") or {}).get("proposed_action"),
            "category": (r.get("model") or {}).get("category"),
        }
        for r in scored
        if not r["grade"]["action_ok"]
    ]
    error_counts: Dict[str, int] = {}
    for e in live_errors:
        error_counts[e["failure"]] = error_counts.get(e["failure"], 0) + 1
    return {
        "eval_version": EVAL_VERSION,
        "meta": dict(meta or {}),
        "verdict": verdict,
        "gates": gates,
        "attempted": attempted,
        "scored": len(scored),
        "cases": len(finals),
        "reps": reps,
        "errors": {
            "count": len(live_errors),
            "share": error_share,
            "by_failure": dict(sorted(error_counts.items())),
            "retried": len(errors) - len(live_errors),
        },
        "calls": stages,
        "overall": block(scored),
        "majority_baseline": majority,
        "by_kind": by_kind,
        "by_category": by_category,
        "triage_recall": _rate(g["triage_recall"] for g in grades),
        "off_watchlist_passed_to_classifier": _rate(g["off_watchlist_passed"] for g in grades),
        "assets": _rate(g["assets_ok"] for g in grades),
        "story_links": _rate(g["story_link_ok"] for g in grades),
        "single_source": {
            "stories": len(single),
            "effects": single_effects,
            "model_wanted_effect": sum(1 for g in grades if g["model_wanted_single_source_effect"]),
            "rules_stopped": sum(1 for g in grades if g["model_wanted_single_source_effect"] and not g["single_source_effect"]),
        },
        "prohibited_actions": prohibited,
        "refusals": sum(1 for g in grades if g["refusal"]),
        "truncated": sum(1 for g in grades if g["truncated"]),
        "flaky_cases": flaky,
        "failures": failures,
        "usage_by_model": usage_by_model,
        "estimated_usd": total_cost if priced else None,
        "latency": latency,
    }


# -- report ---------------------------------------------------------------------------------


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100 * value:.1f} %"


def _ci(rate: Mapping[str, Any]) -> str:
    ci = rate.get("ci95")
    return "n/a" if not ci else f"{100 * ci[0]:.0f}–{100 * ci[1]:.0f} %"


def _frac(rate: Mapping[str, Any]) -> str:
    return "n/a" if not rate.get("n") else f"{_pct(rate['rate'])} ({rate['ok']} of {rate['n']})"


_VERDICT_WORDS = {
    "PASS": "every safety gate was met",
    "FAIL": "at least one safety gate failed: this classifier configuration is not ready for the news shadow",
    "INCONCLUSIVE": "too many cases could not be scored (errors), so the run proves nothing either way",
}

# Plain words for the decision codes in the "Cases to look at" table.
_REASON_WORDS = {
    "active": "the rules let the event take effect",
    "below_threshold": "decayed severity below the threshold",
    "expired": "the event had expired",
    "classified_no_effect": "the event was built with NO_EFFECT",
    "no_item_relevant": "triage passed no article to the classifier",
    "all_items_withheld": "every article was quarantined",
    "not_a_watchlist_category": "the classifier answered NONE (outside the watchlist)",
    "classifier_invalid_json": "the reply was not valid JSON (rejected)",
    "classifier_schema_validation": "the reply broke the schema (rejected)",
    "classifier_prohibited_action": "the reply used an action outside the vocabulary (rejected)",
    "classifier_invalid_reference": "the reply cited a source or event id it was not given (rejected)",
    "classifier_refusal": "the model refused",
    "classifier_max_tokens": "the reply was cut off (truncated)",
    "classifier_quarantined_input": "every article was withheld from the model",
}


def _plural(n: int, word: str, plural: Optional[str] = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _reason(code: str) -> str:
    if code.startswith("status_"):
        return f"corroboration status {code[len('status_'):].upper()}"
    if code.startswith("no_event:"):
        return "no event was built (" + (code[len("no_event:"):] or "no reason") + ")"
    return _REASON_WORDS.get(code, code)


def render_report(summary: Mapping[str, Any]) -> str:
    """The owner-readable markdown report of one run."""
    meta = summary.get("meta", {})
    lines: List[str] = ["# News classifier eval report", ""]
    lines.append(f"**Result: {summary['verdict']}** — {_VERDICT_WORDS[summary['verdict']]}.")
    lines.append("")
    lines.append(
        f"{summary['scored']} of {_plural(summary['attempted'], 'attempt')} scored ({_plural(summary['cases'], 'case')}, "
        f"repetitions {', '.join(str(r) for r in summary['reps']) or 'none'}); "
        f"{_plural(summary['errors']['count'], 'error')} not scored."
    )
    lines.append("")
    details = [
        ("Mode", meta.get("mode")),
        ("Triage model", meta.get("triage_model")),
        ("Classifier model", meta.get("classify_model")),
        ("Prompt", meta.get("prompt_version")),
        ("Decay policy", meta.get("decay_policy")),
        ("Fixture set", (meta.get("fixture_digest") or "")[:16] or None),
        ("Triage stage", None if meta.get("use_triage") is None else ("on" if meta.get("use_triage") else "off (every story goes to the classifier)")),
        ("Started", meta.get("started_at")),
        ("Finished", meta.get("finished_at")),
    ]
    for label, value in details:
        if value:
            lines.append(f"- {label}: `{value}`")
    for warning in meta.get("warnings", []):
        lines.append(f"- Warning: {warning}")
    lines += ["", "## Safety gates", "", "| Gate | Target | Result | |", "|---|---|---|---|"]
    for g in summary["gates"]:
        value = g["value"]
        shown = _pct(value) if g["name"].startswith("schema_validity") else str(value)
        state = "n/a" if g["pass"] is None else ("PASS" if g["pass"] else "**FAIL**")
        lines.append(f"| {g['label']} | {g['target']} | {shown} — {g['detail']} | {state} |")
    overall = summary["overall"]
    lines += [
        "",
        "## How often the final action was right",
        "",
        f"Overall: {_frac(overall['action'])}, 95 % interval {_ci(overall['action'])}. "
        f"A classifier that always answered NO_EFFECT would score {_pct(summary['majority_baseline'])}.",
        "",
        f"Missed effects (no effect where one was due): {overall['missed_effects']} · "
        f"false effects (an effect where none was due): {overall['false_effects']} · "
        f"wrong strength: {overall['wrong_strength']}",
        "",
        "| Case kind | Cases | Action right | 95 % interval | Missed | False |",
        "|---|---|---|---|---|---|",
    ]
    for kind, b in summary["by_kind"].items():
        lines.append(
            f"| {KIND_TITLES.get(kind, kind)} | {b['cases']} | {_pct(b['action']['rate'])} | {_ci(b['action'])} | "
            f"{b['missed_effects']} | {b['false_effects']} |"
        )
    lines += ["", "## Watchlist category", "", "| Expected category | Cases | Category right | Action right |", "|---|---|---|---|"]
    for cat, b in summary["by_category"].items():
        label = "NONE (outside the watchlist)" if cat == "NONE" else cat
        lines.append(f"| {label} | {b['cases']} | {_frac(b['category'])} | {_frac(b['action'])} |")
    ss = summary["single_source"]
    calls = summary["calls"]
    lines += [
        "",
        "## Other measurements",
        "",
        f"- Triage kept watchlist stories (recall): {_frac(summary['triage_recall'])}",
        f"- Off-watchlist stories still passed to the classifier: {_frac(summary['off_watchlist_passed_to_classifier'])}",
        f"- Single-source stories where the model wanted an effect: {ss['model_wanted_effect']} of {ss['stories']}; "
        f"the rules stopped {ss['rules_stopped']} of them",
        f"- Story links (repeat or new development) right: {_frac(summary['story_links'])}",
        f"- Affected assets right: {_frac(summary['assets'])}",
        f"- Refused replies: {summary['refusals']} · truncated replies: {summary['truncated']} · "
        f"replies withheld before any call (quarantined text): {calls['triage']['no_call'] + calls['classify']['no_call']}",
        f"- Cases whose final action changed between repetitions: {', '.join(summary['flaky_cases']) or 'none'}",
    ]
    if summary["errors"]["count"]:
        by = ", ".join(f"{k} × {v}" for k, v in summary["errors"]["by_failure"].items())
        lines.append(f"- Errors (not scored): {by}")
    if summary["errors"].get("retried"):
        lines.append(
            f"- Failed attempts redone by --resume: {summary['errors']['retried']} "
            "(only each case's last attempt counts; every attempt's tokens are in the cost below)"
        )
    lines += ["", "## Tokens and estimated cost", "", "| Model | Calls | Input | Cache read | Cache write | Output | Est. USD |", "|---|---|---|---|---|---|---|"]
    for model, u in sorted(summary["usage_by_model"].items()):
        usd = "n/a" if u["estimated_usd"] is None else f"{u['estimated_usd']:.4f}"
        lines.append(
            f"| {model} | {u['calls']} | {u['input_tokens']} | {u['cache_read_input_tokens']} | "
            f"{u['cache_creation_input_tokens']} | {u['output_tokens']} | {usd} |"
        )
    total = summary["estimated_usd"]
    lines.append("")
    lines.append(f"Estimated total: {'n/a' if total is None else f'${total:.2f}'} (list prices; the Anthropic console shows the real bill).")
    lat = summary["latency"]
    if meta.get("mode") == "live" and lat["classify"]["median_ms"] is not None:
        lines.append(
            f"Median latency: triage {lat['triage']['median_ms'] or 0:.0f} ms, classification {lat['classify']['median_ms']:.0f} ms "
            f"(90th percentile {lat['classify']['p90_ms']:.0f} ms)."
        )
    lines += ["", "## Cases to look at", ""]
    if not summary["failures"]:
        lines.append("None: every scored case ended with an acceptable action.")
    else:
        lines += ["| Case | Rep | Kind | Expected | Got | What decided it | Model proposed |", "|---|---|---|---|---|---|---|"]
        for f in summary["failures"][:60]:
            expected = " or ".join([f["expected"], *f["accept"]])
            lines.append(
                f"| {f['case_id']} | {f['rep']} | {f['kind']} | {expected} | {f['got']} | {_reason(f['reason'])} | {f['proposed'] or '-'} |"
            )
        if len(summary["failures"]) > 60:
            lines.append(f"\n…and {len(summary['failures']) - 60} more in results.jsonl.")
    lines += [
        "",
        "All headlines in the eval set are synthetic. A pass shows the classifier and the rules behave",
        "on these cases; it is not evidence of profit and authorizes nothing (Phase 6b stays log-only).",
        "",
    ]
    return "\n".join(lines)


# -- model clients: scripted policies, recording and replay ----------------------------------


@dataclass
class ReplyBlock:
    type: str
    text: str = ""


@dataclass
class ReplyUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class ReplyStopDetails:
    category: Optional[str] = None


@dataclass
class Reply:
    """Duck-typed stand-in for an SDK ``Message`` (what ``NewsClassifier`` reads)."""

    content: List[ReplyBlock]
    stop_reason: str
    model: str
    usage: ReplyUsage = field(default_factory=ReplyUsage)
    stop_details: Optional[ReplyStopDetails] = None
    _request_id: Optional[str] = None


class _Messages:
    def __init__(self, create: Callable[..., Any]) -> None:
        self.create = create


def parse_request(kwargs: Mapping[str, Any]) -> Tuple[str, Dict[str, Any], str]:
    """(stage, payload, raw user text) of one ``messages.create`` call made by the classifier."""
    text = kwargs["messages"][0]["content"]
    match = _REQUEST_RE.match(text)
    if match is None:
        raise ValueError("not a news-classifier request")
    stage = "triage" if match.group(1) == "news_item" else "classify"
    return stage, json.loads(match.group(2)), text


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_reply(obj: Any, model: str, *, stop_reason: str = "end_turn") -> Reply:
    return Reply(content=[ReplyBlock("thinking"), ReplyBlock("text", json.dumps(obj))], stop_reason=stop_reason, model=model)


Policy = Callable[["EvalCase", str, Mapping[str, Any], str], Union[Reply, BaseException]]


def _sent_ids(payload: Mapping[str, Any]) -> List[str]:
    return [str(s["source_id"]) for s in payload.get("source_items", [])]


def reference_verdict(case: EvalCase, sent_ids: Sequence[str]) -> Dict[str, Any]:
    """What a careful classifier answers for ``case`` (built from its labels)."""
    e = case.expect
    restrictive = e.action is not Action.NO_EFFECT
    if e.independent is not None:
        wanted = {case.item_id(k) for k in e.independent}
        independent = [i for i in sent_ids if i in wanted]
    else:
        independent = list(sent_ids)
    watchlist = e.category is not ClassifiedCategory.NONE
    if e.assets is not None:
        assets = [a.value for a in e.assets]
    else:
        assets = [a.value for a in ASSET_ORDER] if watchlist else []
    if e.corroboration is not None:
        assessment = e.corroboration
    elif e.single_source or not restrictive:
        assessment = CorroborationStatus.SINGLE_SOURCE
    else:
        assessment = CorroborationStatus.INDEPENDENT_SOURCE_CONFIRMED
    horizon = DEFAULT_POLICY.categories[Category(e.category.value)].max_ttl_minutes if watchlist else 60
    return {
        "category": e.category.value,
        "assets": assets,
        "claim_summary": f"Reference answer for eval case {case.id}.",
        "manipulation_signs": [s.value for s in e.signs],
        "corroboration_assessment": assessment.value,
        "independent_source_ids": independent,
        "hedging_uncertainty": 0.15 if restrictive else 0.6,
        "direction": (e.direction or (Direction.RISK_OFF if restrictive else Direction.UNCLEAR)).value,
        "expected_market_reaction": (
            e.reaction or (ExpectedReaction.DOWN_OR_VOLATILE if restrictive else ExpectedReaction.NO_CLEAR_REACTION)
        ).value,
        "impact_strength": 0.85 if restrictive else 0.2,
        "volatility_risk": 0.85 if restrictive else 0.3,
        "time_horizon_minutes": horizon,
        "confidence": 0.9 if restrictive else 0.6,
        "same_story_as": e.same_story_as,
        "new_development": bool(e.new_development),
        "why_not_more_aggressive": "Reference answer used to check the eval harness.",
        "proposed_action": e.action.value,
    }


def _reference_triage(case: EvalCase) -> Dict[str, Any]:
    watchlist = case.expect.category is not ClassifiedCategory.NONE
    return {"relevant": watchlist, "category": case.expect.category.value, "reason": "Reference triage answer."}


def reference_policy(case: EvalCase, stage: str, payload: Mapping[str, Any], model: str) -> Reply:
    """The labels as model answers: must score 100 % and pass every gate (checks the set)."""
    if stage == "triage":
        return json_reply(_reference_triage(case), model)
    return json_reply(reference_verdict(case, _sent_ids(payload)), model)


def always_no_effect_policy(case: EvalCase, stage: str, payload: Mapping[str, Any], model: str) -> Reply:
    """Valid answers that never ask for an effect (the majority-class baseline)."""
    if stage == "triage":
        return json_reply(_reference_triage(case), model)
    verdict = reference_verdict(case, _sent_ids(payload))
    verdict["proposed_action"] = Action.NO_EFFECT.value
    return json_reply(verdict, model)


def always_block_policy(case: EvalCase, stage: str, payload: Mapping[str, Any], model: str) -> Reply:
    """A credulous, trigger-happy classifier: everything is a corroborated block.

    What survives it shows where the deterministic rules alone protect the system,
    and the single-source effects it causes show which cases test the model's
    own skepticism.
    """
    category = case.expect.category.value if case.expect.category is not ClassifiedCategory.NONE else "EXCHANGE_HACK_EXPLOIT"
    if stage == "triage":
        return json_reply({"relevant": True, "category": category, "reason": "Everything matters."}, model)
    return json_reply(
        {
            "category": category,
            "assets": ["BTC", "ETH"],
            "claim_summary": "A dangerous event for crypto markets.",
            "manipulation_signs": [],
            "corroboration_assessment": "INDEPENDENT_SOURCE_CONFIRMED",
            "independent_source_ids": _sent_ids(payload),
            "hedging_uncertainty": 0.0,
            "direction": "RISK_OFF",
            "expected_market_reaction": "DOWN_OR_VOLATILE",
            "impact_strength": 1.0,
            "volatility_risk": 1.0,
            "time_horizon_minutes": 720,
            "confidence": 1.0,
            "same_story_as": None,
            "new_development": False,
            "why_not_more_aggressive": "Already the most restrictive action.",
            "proposed_action": "BLOCK_NEW_LONGS",
        },
        model,
    )


def broken_policy(case: EvalCase, stage: str, payload: Mapping[str, Any], model: str) -> Reply:
    """Mostly unusable classification replies: invalid JSON, out-of-range numbers, a
    BOOST action, truncation, a refusal; one in six is the reference answer."""
    if stage == "triage":
        return json_reply(_reference_triage(case), model)
    verdict = reference_verdict(case, _sent_ids(payload))
    mode = zlib.crc32(case.id.encode("utf-8")) % 6
    if mode == 0:
        return Reply([ReplyBlock("text", '{"category": "EXCHANGE_HA')], "end_turn", model)
    if mode == 1:
        return json_reply({**verdict, "confidence": 2.0}, model)
    if mode == 2:
        return json_reply({**verdict, "proposed_action": "BOOST"}, model)
    if mode == 3:
        return Reply([ReplyBlock("text", json.dumps(verdict)[:80])], "max_tokens", model)
    if mode == 4:
        return Reply([], "refusal", model, stop_details=ReplyStopDetails(category=None))
    return json_reply(verdict, model)


POLICIES: Mapping[str, Policy] = MappingProxyType(
    {
        "reference": reference_policy,
        "always_no_effect": always_no_effect_policy,
        "always_block": always_block_policy,
        "broken": broken_policy,
    }
)


class ScriptedClient:
    """Answers the classifier from a policy function: no network, no key."""

    def __init__(self, case: EvalCase, policy: Policy) -> None:
        self.case = case
        self.policy = policy
        self.calls: List[Dict[str, Any]] = []
        self.messages = _Messages(self._create)

    def _create(self, **kwargs: Any) -> Reply:
        stage, payload, _ = parse_request(kwargs)
        self.calls.append(kwargs)
        reply = self.policy(self.case, stage, payload, str(kwargs.get("model", "")))
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _text_blocks(response: Any) -> List[str]:
    return [str(getattr(b, "text", "")) for b in (getattr(response, "content", None) or ()) if getattr(b, "type", None) == "text"]


def _usage_dict(usage: Any) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for name in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = getattr(usage, name, None)
        if isinstance(value, int):
            out[name] = value
    return out


class RecordingClient:
    """Passes every call to ``inner`` unchanged and records the reply for later replay.

    Failed calls (exceptions) are not recorded: they are infrastructure errors and
    a replay re-reports them as missing recordings.
    """

    def __init__(self, inner: Any, case: EvalCase, rep: int, write: Callable[[Dict[str, Any]], None]) -> None:
        self._inner = inner
        self._case = case
        self._rep = rep
        self._write = write
        self.messages = _Messages(self._create)

    def _create(self, **kwargs: Any) -> Any:
        response = self._inner.messages.create(**kwargs)
        stage, payload, text = parse_request(kwargs)
        item_id = str(payload["item"]["source_id"]) if stage == "triage" else None
        stop_details = getattr(response, "stop_details", None)
        record = {
            "kind": "call",
            "eval_version": EVAL_VERSION,
            "case_id": self._case.id,
            "rep": self._rep,
            "stage": stage,
            "item_key": self._case.key_of(item_id) if item_id else None,
            "item_id": item_id,
            "payload_sha256": _sha256(text),
            "prompt_sha256": _sha256(kwargs["system"][0]["text"]),
            "model": kwargs.get("model"),
            "served_model": getattr(response, "model", None),
            "stop_reason": getattr(response, "stop_reason", None),
            "refusal_category": getattr(stop_details, "category", None) if stop_details is not None else None,
            "text": _text_blocks(response),
            "usage": _usage_dict(getattr(response, "usage", None)),
            "request_id": getattr(response, "_request_id", None),
        }
        self._write(redact(record))
        return response


class ReplayMissing(LookupError):
    """No recorded reply for this call."""


class ReplayStale(LookupError):
    """The recorded reply answered a different request (the fixture changed)."""


@dataclass(frozen=True)
class RecordedCall:
    case_id: str
    rep: int
    stage: str
    item_key: Optional[str]
    text: Tuple[str, ...]
    stop_reason: str
    model: Optional[str]
    served_model: Optional[str]
    usage: Mapping[str, int]
    payload_sha256: Optional[str] = None
    prompt_sha256: Optional[str] = None
    refusal_category: Optional[str] = None
    request_id: Optional[str] = None


# The run settings a recording's header keeps, so a replay asks for the same models.
RUN_SETTINGS: Tuple[str, ...] = ("triage_model", "classify_model", "triage_effort", "classify_effort", "use_triage")


def run_header(case_ids: Iterable[str], reps: int, **extra: Any) -> Dict[str, Any]:
    """First line of a recording: which cases a run attempted (some make no call at all)
    and, in ``extra``, its settings (``RUN_SETTINGS``) and start time."""
    return {"kind": "run", "eval_version": EVAL_VERSION, "case_ids": sorted(case_ids), "reps": int(reps), **extra}


class Recording:
    """Recorded replies of one run, keyed by (case, rep, stage, item key)."""

    def __init__(
        self,
        calls: Iterable[RecordedCall],
        *,
        declared_cases: Iterable[str] = (),
        declared_reps: int = 0,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._calls: Dict[Tuple[str, int, str, Optional[str]], RecordedCall] = {}
        for call in calls:  # a later record for the same key wins (resumed runs)
            self._calls[(call.case_id, call.rep, call.stage, call.item_key)] = call
        self._declared_cases = frozenset(declared_cases)
        self._declared_reps = int(declared_reps)
        self.settings: Mapping[str, Any] = MappingProxyType(dict(settings or {}))
        self.stale_prompts = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._calls)

    @property
    def case_ids(self) -> FrozenSet[str]:
        """Cases the run attempted (from its header), else the cases with recorded calls."""
        return self._declared_cases or frozenset(k[0] for k in self._calls)

    @property
    def reps(self) -> int:
        return max([self._declared_reps, *(k[1] for k in self._calls)], default=1) or 1

    @classmethod
    def load(cls, path: Path) -> "Recording":
        calls = []
        declared: List[str] = []
        declared_reps = 0
        settings: Dict[str, Any] = {}
        with Path(path).open("r", encoding="utf-8") as fh:
            for number, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                raw = json.loads(line)
                if raw.get("kind") == "run":
                    declared.extend(str(c) for c in raw.get("case_ids", []))
                    declared_reps = max(declared_reps, int(raw.get("reps", 1)))
                    settings.update({k: raw[k] for k in RUN_SETTINGS if raw.get(k) is not None})
                    continue
                if raw.get("kind", "call") != "call":
                    continue
                try:
                    calls.append(
                        RecordedCall(
                            case_id=str(raw["case_id"]),
                            rep=int(raw.get("rep", 1)),
                            stage=str(raw["stage"]),
                            item_key=raw.get("item_key"),
                            text=tuple(str(t) for t in raw.get("text", [])),
                            stop_reason=str(raw.get("stop_reason") or "end_turn"),
                            model=raw.get("model"),
                            served_model=raw.get("served_model"),
                            usage=MappingProxyType({k: int(v) for k, v in (raw.get("usage") or {}).items()}),
                            payload_sha256=raw.get("payload_sha256"),
                            prompt_sha256=raw.get("prompt_sha256"),
                            refusal_category=raw.get("refusal_category"),
                            request_id=raw.get("request_id"),
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"{path}:{number}: malformed recording line ({exc})") from exc
        return cls(calls, declared_cases=declared, declared_reps=declared_reps, settings=settings)

    def lookup(self, case_id: str, rep: int, stage: str, item_key: Optional[str]) -> Optional[RecordedCall]:
        return self._calls.get((case_id, rep, stage, item_key))

    def note_stale_prompt(self) -> None:
        with self._lock:
            self.stale_prompts += 1


class ReplayClient:
    """Answers the classifier from a recorded run: no network, no key."""

    def __init__(self, recording: Recording, case: EvalCase, rep: int) -> None:
        self._recording = recording
        self._case = case
        self._rep = rep
        self.messages = _Messages(self._create)

    def _create(self, **kwargs: Any) -> Reply:
        stage, payload, text = parse_request(kwargs)
        key = self._case.key_of(str(payload["item"]["source_id"])) if stage == "triage" else None
        call = self._recording.lookup(self._case.id, self._rep, stage, key)
        if call is None:
            raise ReplayMissing(f"{self._case.id} rep {self._rep} {stage} {key or ''}".strip())
        if call.payload_sha256 and call.payload_sha256 != _sha256(text):
            raise ReplayStale(f"{self._case.id} {stage} {key or ''}".strip())
        if call.prompt_sha256 and call.prompt_sha256 != _sha256(kwargs["system"][0]["text"]):
            self._recording.note_stale_prompt()
        usage = ReplyUsage(**{k: v for k, v in call.usage.items() if k in ReplyUsage.__dataclass_fields__})
        return Reply(
            content=[ReplyBlock("text", t) for t in call.text],
            stop_reason=call.stop_reason,
            model=call.served_model or call.model or str(kwargs.get("model", "")),
            usage=usage,
            stop_details=ReplyStopDetails(call.refusal_category) if call.stop_reason == "refusal" else None,
            _request_id=call.request_id,
        )


def live_client(api_key: str, *, timeout_seconds: float = 300.0, max_retries: int = 5) -> Any:
    """The real SDK client, built the classifier's way (API host pinned). Needs a key.

    More retries than the shadow's client: the SDK backs off on rate limits and
    server errors, and an eval wants an answer for every case (a new key starts
    at low rate limits) where the shadow would simply log NO_EFFECT."""
    if not (api_key or "").strip():
        raise ValueError("an API key is required for a live run")
    return clf._default_client(api_key.strip(), float(timeout_seconds), int(max_retries))


# -- running a set ------------------------------------------------------------------------

ClassifierFor = Callable[[EvalCase, int], NewsClassifier]


def scripted_classifier_for(policy: Policy, **classifier_kw: Any) -> ClassifierFor:
    def factory(case: EvalCase, rep: int) -> NewsClassifier:
        return NewsClassifier(ScriptedClient(case, policy), **classifier_kw)

    return factory


def replay_classifier_for(recording: Recording, **classifier_kw: Any) -> ClassifierFor:
    def factory(case: EvalCase, rep: int) -> NewsClassifier:
        return NewsClassifier(ReplayClient(recording, case, rep), **classifier_kw)

    return factory


def run_cases(
    cases: Sequence[EvalCase],
    classifier_for: ClassifierFor,
    *,
    reps: int = 1,
    workers: int = 1,
    use_triage: bool = True,
    policy: DecayPolicy = DEFAULT_POLICY,
    skip: FrozenSet[Tuple[str, int]] = frozenset(),
    on_done: Optional[Callable[[Optional[Dict[str, Any]], Optional[Dict[str, Any]]], None]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Run every (case, rep) not in ``skip``; returns (scored rows, error rows).

    A bug or an infrastructure failure on one case becomes an error row; it never
    stops the run and is never scored as a model answer.
    """
    if reps < 1 or workers < 1:
        raise ValueError("reps and workers must be at least 1")
    tasks = [(case, rep) for rep in range(1, reps + 1) for case in cases if (case.id, rep) not in skip]
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def one(case: EvalCase, rep: int) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        try:
            result = run_story(case, classifier_for(case, rep), rep=rep, use_triage=use_triage, policy=policy)
        except Exception as exc:  # a harness bug must not look like a model failure
            return None, error_row(case, rep, f"harness_error:{type(exc).__name__}", None)
        if result.error is not None:
            calls = [_call_record(s, k, o) for s, k, o in result.outcomes()]
            return None, error_row(case, rep, result.error, result.error_stage, calls)
        return result_row(case, result), None

    def collect(row: Optional[Dict[str, Any]], err: Optional[Dict[str, Any]]) -> None:
        with lock:
            if row is not None:
                rows.append(row)
            if err is not None:
                errors.append(err)
            if on_done is not None:
                on_done(row, err)

    if workers == 1:
        for case, rep in tasks:
            collect(*one(case, rep))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, case, rep) for case, rep in tasks]
            for future in as_completed(futures):
                collect(*future.result())
    rows.sort(key=lambda r: (r["case_id"], r["rep"]))
    errors.sort(key=lambda e: (e["case_id"], e["rep"]))
    return rows, errors


def run_meta(
    *,
    mode: str,
    root: Path = DEFAULT_FIXTURE_DIR,
    use_triage: bool = True,
    triage_model: str = TRIAGE_MODEL,
    classify_model: str = CLASSIFIER_MODEL,
    triage_effort: str = PRODUCTION_TRIAGE_EFFORT,
    classify_effort: str = PRODUCTION_CLASSIFY_EFFORT,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    warnings = []
    if triage_model != TRIAGE_MODEL or classify_model != CLASSIFIER_MODEL:
        warnings.append("models differ from the production classifier configuration")
    if (triage_effort, classify_effort) != (PRODUCTION_TRIAGE_EFFORT, PRODUCTION_CLASSIFY_EFFORT):
        warnings.append(
            "effort levels differ from the production classifier configuration "
            f"(triage {PRODUCTION_TRIAGE_EFFORT}, classification {PRODUCTION_CLASSIFY_EFFORT})"
        )
    return {
        "mode": mode,
        "eval_version": EVAL_VERSION,
        "triage_model": triage_model,
        "classify_model": classify_model,
        "triage_effort": triage_effort,
        "classify_effort": classify_effort,
        "prompt_version": PROMPT_VERSION,
        "classifier_prompt_sha256": CLASSIFIER_PROMPT_SHA256,
        "triage_prompt_sha256": TRIAGE_PROMPT_SHA256,
        "decay_policy": POLICY_VERSION,
        "fixture_digest": fixture_digest(root),
        "use_triage": use_triage,
        "warnings": warnings,
        **dict(extra or {}),
    }


def self_test(cases: Sequence[EvalCase], *, root: Path = DEFAULT_FIXTURE_DIR, use_triage: bool = True) -> Dict[str, Dict[str, Any]]:
    """Run the four scripted policies through the full pipeline (offline, seconds)."""
    out = {}
    for name, policy in POLICIES.items():
        rows, errors = run_cases(cases, scripted_classifier_for(policy), use_triage=use_triage)
        out[name] = summarize(rows, errors, run_meta(mode=f"self-test:{name}", root=root, use_triage=use_triage))
    return out


def self_test_checks(results: Mapping[str, Mapping[str, Any]], cases: Sequence[EvalCase]) -> List[Tuple[str, bool]]:
    """What the scripted policies must show for the harness and the labels to be trusted."""
    ref = results["reference"]
    none = results["always_no_effect"]
    block = results["always_block"]
    broken = results["broken"]
    effect_cases = sum(1 for c in cases if c.effect_required)
    broken_validity = next(g for g in broken["gates"] if g["name"] == "schema_validity_classify")
    return [
        ("reference answers pass every gate", ref["verdict"] == "PASS"),
        ("reference answers get every final action right", ref["overall"]["action"]["rate"] == 1.0),
        ("reference answers get every category right", ref["overall"]["category"]["rate"] in (1.0, None)),
        ("reference answers link every story right", ref["story_links"]["rate"] in (1.0, None)),
        ("a never-acting classifier misses every required effect", none["overall"]["missed_effects"] == effect_cases),
        ("a never-acting classifier causes no false effect", none["overall"]["false_effects"] == 0),
        ("a credulous classifier is caught by the single-source gate", block["verdict"] == "FAIL" and block["single_source"]["effects"] > 0),
        ("a credulous classifier causes false effects", block["overall"]["false_effects"] > 0),
        ("a broken classifier fails the schema-validity gate", broken_validity["pass"] is False),
        ("a broken classifier's BOOST replies are counted as prohibited", broken["prohibited_actions"] > 0),
        ("no scripted run hit an infrastructure error", all(r["errors"]["count"] == 0 for r in results.values())),
    ]
