"""Phase 6b event schema (PHASE6B_DESIGN sections 4-5, 7.4, 9) — validation only.

``NewsEvent`` is the design's event object and the only output a future
deterministic consumer may read; raw LLM prose never reaches trading logic.
Its enums are exactly the design's "Allowed enum values". ``TriageVerdict``
and ``ClassifierVerdict`` are what the two LLM stages may return (structured
outputs); deterministic code (``decay.build_event``) turns a verdict into an
event and can only lower its proposed action, never raise it.

Everything here is pure validation: no I/O, no network, no LLM, no import of
execution, risk, strategy or exchange code.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Iterable, Literal, Mapping, Optional, Tuple

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.news.dedup import content_key
from app.news.sanitize import flags_are_severe

SCHEMA_VERSION = "phase6b-event-v1"
RAW_SUMMARY_MAX_CHARS = 280
EVENT_ID_PATTERN = r"^evt_\d{8}_[a-z0-9_]{1,80}_[0-9a-f]{8,64}$"


# -- enums (PHASE6B_DESIGN section 4, "Allowed enum values") -------------------


class Category(StrEnum):
    ETF_SEC_DECISION = "ETF_SEC_DECISION"
    FED_FOMC_RATES = "FED_FOMC_RATES"
    MACRO_CPI_PPI_JOBS = "MACRO_CPI_PPI_JOBS"
    EXCHANGE_HACK_EXPLOIT = "EXCHANGE_HACK_EXPLOIT"
    MAJOR_REGULATORY_ACTION = "MAJOR_REGULATORY_ACTION"
    LIQUIDATION_CASCADE = "LIQUIDATION_CASCADE"
    GEOPOLITICAL_ESCALATION = "GEOPOLITICAL_ESCALATION"
    MAJOR_EXCHANGE_PROTOCOL_INCIDENT = "MAJOR_EXCHANGE_PROTOCOL_INCIDENT"


class CorroborationStatus(StrEnum):
    SINGLE_SOURCE = "SINGLE_SOURCE"
    INDEPENDENT_SOURCE_CONFIRMED = "INDEPENDENT_SOURCE_CONFIRMED"
    PRICE_VOLUME_CONFIRMED = "PRICE_VOLUME_CONFIRMED"
    CONFLICTED = "CONFLICTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SourceTier(StrEnum):
    OFFICIAL = "OFFICIAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Direction(StrEnum):
    RISK_OFF = "RISK_OFF"
    RISK_ON = "RISK_ON"
    MIXED = "MIXED"
    UNCLEAR = "UNCLEAR"


class ExpectedReaction(StrEnum):
    DOWN_OR_VOLATILE = "DOWN_OR_VOLATILE"
    UP_BUT_REVERSAL_RISK = "UP_BUT_REVERSAL_RISK"
    VOLATILITY_ONLY = "VOLATILITY_ONLY"
    NO_CLEAR_REACTION = "NO_CLEAR_REACTION"


class Action(StrEnum):
    """The whole v1 vocabulary. There is deliberately no value that enters,
    buys, boosts, or increases anything (PHASE6B_DESIGN section 2)."""

    BLOCK_NEW_LONGS = "BLOCK_NEW_LONGS"
    REDUCE_SIZE = "REDUCE_SIZE"
    NO_EFFECT = "NO_EFFECT"


# -- supporting enums (not in the design's list; used by the decay function and
# -- the classifier's structured output) ----------------------------------------


class DecayType(StrEnum):
    # Weight falls linearly from 1 at ``starts_at`` to 0 at ``zero_at``; the
    # design's example type. ``half_life_minutes`` is informational for it.
    LINEAR_TO_ZERO = "LINEAR_TO_ZERO"
    # Weight halves every ``half_life_minutes`` and is exactly 0 from ``zero_at``.
    EXPONENTIAL_TO_ZERO = "EXPONENTIAL_TO_ZERO"


class ClassifiedCategory(StrEnum):
    """A watchlist category, or NONE for anything outside the v1 watchlist."""

    ETF_SEC_DECISION = "ETF_SEC_DECISION"
    FED_FOMC_RATES = "FED_FOMC_RATES"
    MACRO_CPI_PPI_JOBS = "MACRO_CPI_PPI_JOBS"
    EXCHANGE_HACK_EXPLOIT = "EXCHANGE_HACK_EXPLOIT"
    MAJOR_REGULATORY_ACTION = "MAJOR_REGULATORY_ACTION"
    LIQUIDATION_CASCADE = "LIQUIDATION_CASCADE"
    GEOPOLITICAL_ESCALATION = "GEOPOLITICAL_ESCALATION"
    MAJOR_EXCHANGE_PROTOCOL_INCIDENT = "MAJOR_EXCHANGE_PROTOCOL_INCIDENT"
    NONE = "NONE"


class ManipulationSign(StrEnum):
    """Adversarial or low-reliability signs the classifier may report (design 7.4, 10)."""

    SINGLE_SOCIAL_POST = "SINGLE_SOCIAL_POST"
    UNVERIFIED_RUMOR = "UNVERIFIED_RUMOR"
    SATIRE_OR_PARODY = "SATIRE_OR_PARODY"
    STALE_REPOST = "STALE_REPOST"
    COPIED_WIRE_STORY = "COPIED_WIRE_STORY"
    SCREENSHOT_ONLY = "SCREENSHOT_ONLY"
    ADVERSARIAL_PHRASING = "ADVERSARIAL_PHRASING"
    HIDDEN_INSTRUCTIONS = "HIDDEN_INSTRUCTIONS"
    HOMOGLYPH_OR_SPOOFED_TEXT = "HOMOGLYPH_OR_SPOOFED_TEXT"
    PUMP_AND_DUMP_RISK = "PUMP_AND_DUMP_RISK"
    CONTRADICTED_BY_OTHER_SOURCE = "CONTRADICTED_BY_OTHER_SOURCE"
    AGGREGATOR_ONLY = "AGGREGATOR_ONLY"


class Asset(StrEnum):
    BTC = "BTC"
    ETH = "ETH"


Instrument = Literal["BTC-USDT", "ETH-USDT"]
INSTRUMENT_FOR_ASSET: Mapping[Asset, str] = {Asset.BTC: "BTC-USDT", Asset.ETH: "ETH-USDT"}
ASSET_ORDER: Tuple[Asset, ...] = (Asset.BTC, Asset.ETH)

# Statuses that may let an event affect risk (design section 2, rule 4).
ACTIVE_STATUSES = frozenset(
    {CorroborationStatus.INDEPENDENT_SOURCE_CONFIRMED, CorroborationStatus.PRICE_VOLUME_CONFIRMED}
)
# Statuses that force action NO_EFFECT (design section 4, schema constraints).
NO_EFFECT_STATUSES = frozenset(
    {
        CorroborationStatus.SINGLE_SOURCE,
        CorroborationStatus.CONFLICTED,
        CorroborationStatus.REJECTED,
        CorroborationStatus.EXPIRED,
    }
)
# Most conservative wins: BLOCK_NEW_LONGS beats REDUCE_SIZE beats NO_EFFECT (design 7.6).
ACTION_RANK: Mapping[Action, int] = {Action.NO_EFFECT: 0, Action.REDUCE_SIZE: 1, Action.BLOCK_NEW_LONGS: 2}


def most_conservative(actions: Iterable[Action]) -> Action:
    """The strongest restriction among ``actions`` (NO_EFFECT when empty)."""
    return max(actions, key=ACTION_RANK.__getitem__, default=Action.NO_EFFECT)


def less_aggressive(a: Action, b: Action) -> Action:
    """The weaker of two actions."""
    return a if ACTION_RANK[a] <= ACTION_RANK[b] else b


# -- validators ----------------------------------------------------------------


def require_utc(value: datetime) -> datetime:
    """Reject naive datetimes; return the instant in UTC."""
    if not isinstance(value, datetime):
        raise ValueError("expected a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware (UTC)")
    return value.astimezone(timezone.utc)


def check_clean_text(value: str) -> str:
    """Short audit text: NFKC-normalized, no control/format (zero-width, bidi) chars."""
    if unicodedata.normalize("NFKC", value) != value:
        raise ValueError("text must be NFKC-normalized (run it through the sanitizer)")
    for ch in value:
        if unicodedata.category(ch) in ("Cc", "Cf"):
            raise ValueError("text must not contain control, zero-width or bidi characters")
    if value != value.strip():
        raise ValueError("text must not have leading or trailing whitespace")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(require_utc)]
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
ShortLabel = Annotated[str, Field(min_length=1, max_length=200)]
CleanText = Annotated[str, AfterValidator(check_clean_text)]

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True)


# -- the design's event object (section 4) ---------------------------------------


class SourceQuality(BaseModel):
    model_config = _MODEL_CONFIG

    tier: SourceTier
    independent_source_count: int = Field(ge=0, le=100)
    primary_sources: Tuple[ShortLabel, ...] = Field(max_length=20)
    secondary_sources: Tuple[ShortLabel, ...] = Field(max_length=20)
    source_ids: Tuple[ShortLabel, ...] = Field(max_length=50)
    notes: Annotated[CleanText, Field(max_length=500)]


class AssetImpact(BaseModel):
    model_config = _MODEL_CONFIG

    assets: Tuple[Asset, ...] = Field(max_length=2)
    instruments: Tuple[Instrument, ...] = Field(max_length=2)
    direction: Direction
    expected_market_reaction: ExpectedReaction
    impact_strength: UnitFloat
    volatility_risk: UnitFloat
    time_horizon_minutes: int = Field(ge=1, le=10080)

    @model_validator(mode="after")
    def _instruments_match_assets(self) -> "AssetImpact":
        if len(set(self.assets)) != len(self.assets) or len(set(self.instruments)) != len(self.instruments):
            raise ValueError("assets and instruments must not repeat")
        if set(self.instruments) != {INSTRUMENT_FOR_ASSET[a] for a in self.assets}:
            raise ValueError("instruments must be exactly the SPOT USDT pairs of the listed assets")
        return self


class DecayFunction(BaseModel):
    model_config = _MODEL_CONFIG

    type: DecayType
    starts_at: UtcDatetime
    half_life_minutes: Optional[Annotated[float, Field(gt=0.0, le=10080.0, allow_inf_nan=False)]]
    zero_at: UtcDatetime

    @model_validator(mode="after")
    def _consistent(self) -> "DecayFunction":
        if self.zero_at <= self.starts_at:
            raise ValueError("decay zero_at must be after starts_at")
        if self.type is DecayType.EXPONENTIAL_TO_ZERO and self.half_life_minutes is None:
            raise ValueError("EXPONENTIAL_TO_ZERO needs half_life_minutes")
        return self


class NewsEvent(BaseModel):
    """One story-level event (PHASE6B_DESIGN section 4); validated, immutable."""

    model_config = _MODEL_CONFIG

    event_id: str = Field(pattern=EVENT_ID_PATTERN, max_length=160)
    category: Category
    first_seen_at: UtcDatetime
    expires_at: UtcDatetime
    confidence: UnitFloat
    corroboration_status: CorroborationStatus
    source_quality: SourceQuality
    asset_impact: AssetImpact
    action: Action
    decay_function: DecayFunction
    raw_summary: Annotated[CleanText, Field(min_length=1, max_length=RAW_SUMMARY_MAX_CHARS)]

    @model_validator(mode="after")
    def _schema_constraints(self) -> "NewsEvent":
        if self.expires_at <= self.first_seen_at:
            raise ValueError("expires_at must be greater than first_seen_at")
        if self.corroboration_status in NO_EFFECT_STATUSES and self.action is not Action.NO_EFFECT:
            raise ValueError(
                f"action must be NO_EFFECT when corroboration_status is {self.corroboration_status.value}"
            )
        decay = self.decay_function
        if not (self.first_seen_at <= decay.starts_at < decay.zero_at <= self.expires_at):
            raise ValueError("decay window must lie within [first_seen_at, expires_at]")
        return self

    def is_expired(self, now: datetime) -> bool:
        return require_utc(now) >= self.expires_at

    def action_at(self, now: datetime) -> Action:
        """The classified action, which is exactly NO_EFFECT from ``expires_at`` on."""
        return Action.NO_EFFECT if self.is_expired(now) else self.action


# -- what the LLM stages may return (structured outputs) --------------------------


class TriageVerdict(BaseModel):
    """Stage 1 (Haiku 5.5): is this one item worth the classifier's attention?"""

    model_config = _MODEL_CONFIG

    relevant: bool = Field(
        description="True if the item plausibly concerns a watchlist category and short-term BTC/ETH risk."
    )
    category: ClassifiedCategory = Field(description="Best-matching watchlist category, or NONE.")
    reason: str = Field(max_length=300, description="One short sentence for the audit log.")


class ClassifierVerdict(BaseModel):
    """Stage 2 (Opus 5.5): the classifier's assessment of one story (design 7.4).

    Fields are ordered so the assessment comes before the proposed action.
    Deterministic code builds the ``NewsEvent``; it may lower ``proposed_action``
    and never raises it.
    """

    model_config = _MODEL_CONFIG

    category: ClassifiedCategory = Field(description="Watchlist category of the story, or NONE.")
    assets: Tuple[Asset, ...] = Field(max_length=2, description="Assets whose short-term risk the story affects.")
    claim_summary: str = Field(max_length=400, description="One neutral sentence stating the claim; no instructions.")
    manipulation_signs: Tuple[ManipulationSign, ...] = Field(
        max_length=12, description="Adversarial or low-reliability signs observed, possibly empty."
    )
    corroboration_assessment: CorroborationStatus = Field(
        description="Your view of the corroboration; deterministic code makes the final call."
    )
    independent_source_ids: Tuple[str, ...] = Field(
        max_length=20,
        description="source_id values that independently report the claim (copies and quotes excluded).",
    )
    hedging_uncertainty: UnitFloat = Field(description="0 = definitive statement, 1 = pure speculation.")
    direction: Direction
    expected_market_reaction: ExpectedReaction
    impact_strength: UnitFloat = Field(description="Likely size of the short-term risk impact, 0 to 1.")
    volatility_risk: UnitFloat = Field(description="Likelihood of sharp, reversal-prone moves, 0 to 1.")
    time_horizon_minutes: int = Field(ge=1, le=10080, description="How long the risk likely matters.")
    confidence: UnitFloat = Field(description="Confidence in this classification, 0 to 1.")
    same_story_as: Optional[str] = Field(
        max_length=160,
        description="event_id from existing_event_candidates reporting the same story, else null.",
    )
    new_development: bool = Field(description="True only for a genuinely new development of that story.")
    why_not_more_aggressive: str = Field(
        max_length=400, description="Short audit note: why the action is not more restrictive."
    )
    proposed_action: Action


# -- source items as the agent sees them ------------------------------------------


def _parse_ts(value: object, *, field_name: str) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return require_utc(value)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(f"{field_name} must carry a timezone")
        return parsed.astimezone(timezone.utc)
    raise ValueError(f"{field_name} is not a timestamp")


def item_id_for(key: str) -> str:
    """Stable per-article id derived from the ingestion ``content_key``."""
    return "itm_" + key[:20]


@dataclass(frozen=True)
class SourceItemRef:
    """One sanitized article (a record written by the Sprint 1 ingestion pipeline)."""

    item_id: str
    source_id: str
    publisher: str
    publisher_owner: str
    canonical_url: str
    tier: SourceTier
    observed_at: datetime
    published_at: Optional[datetime]
    title: str
    excerpt: str
    sanitization_flags: Tuple[str, ...] = field(default_factory=tuple)
    quarantined: bool = False
    category_hints: Tuple[str, ...] = field(default_factory=tuple)
    language: str = "en"

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_utc(self.observed_at))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", require_utc(self.published_at))
        if flags_are_severe(self.sanitization_flags) and not self.quarantined:
            object.__setattr__(self, "quarantined", True)

    @classmethod
    def from_record(cls, record: Mapping) -> "SourceItemRef":
        observed = _parse_ts(record.get("observed_at"), field_name="observed_at")
        if observed is None:
            raise ValueError("record has no observed_at")
        canonical = str(record.get("canonical_url") or "")
        publisher = str(record.get("publisher") or "")
        title = str(record.get("title") or "")
        key = str(record.get("content_key") or "") or content_key(canonical, publisher, title)
        tier_raw = str(record.get("source_tier") or "UNKNOWN").upper()
        tier = SourceTier(tier_raw) if tier_raw in SourceTier.__members__ else SourceTier.UNKNOWN
        flags = tuple(str(f) for f in (record.get("sanitization_flags") or ()))
        return cls(
            item_id=item_id_for(key),
            source_id=str(record.get("source_id") or ""),
            publisher=publisher,
            publisher_owner=str(record.get("publisher_owner") or ""),
            canonical_url=canonical,
            tier=tier,
            observed_at=observed,
            published_at=_parse_ts(record.get("published_at"), field_name="published_at"),
            title=title,
            excerpt=str(record.get("excerpt") or ""),
            sanitization_flags=flags,
            quarantined=bool(record.get("quarantined")) or flags_are_severe(flags),
            category_hints=tuple(str(h) for h in (record.get("category_hints") or ())),
            language=str(record.get("language") or "en"),
        )
