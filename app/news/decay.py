"""TTL, decay, source weights, thresholds and the effective signal
(PHASE6B_DESIGN sections 5, 6 and 7.6) — deterministic, no I/O, no LLM.

At event creation (``build_event``) every event gets an absolute ``expires_at``
from its category's TTL range and a decay function; repeated articles about the
same story update that record (``merge_event``) without re-firing the TTL. At
any time ``now`` the effective signal is::

    time_weight        = decay_function(now - first_seen_at)   # 1 -> 0, never rises
    effective_severity = confidence * source_weight(tier) * impact_strength * time_weight

and maps to an action through fixed thresholds, capped by the event's own
classified action, which is itself capped by the classifier's proposal. So the
effect can only shrink as the event ages, is exactly zero from ``expires_at``,
and is zero for single-source, conflicted, rejected or LOW/UNKNOWN-tier events.
Several active events on one instrument resolve to the most conservative one
(BLOCK_NEW_LONGS > REDUCE_SIZE > NO_EFFECT); reductions are never compounded.

Only new independent evidence can make an event stronger; repeats and time can
only make it weaker. Nothing here reads credentials or touches an order path.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from pydantic import ValidationError

from app.news.corroborate import CorroborationResult
from app.news.dedup import event_id as make_event_id
from app.news.sanitize import sanitize_text
from app.news.schema import (
    ACTION_RANK,
    ACTIVE_STATUSES,
    ASSET_ORDER,
    INSTRUMENT_FOR_ASSET,
    NO_EFFECT_STATUSES,
    RAW_SUMMARY_MAX_CHARS,
    Action,
    AssetImpact,
    Category,
    ClassifiedCategory,
    ClassifierVerdict,
    CorroborationStatus,
    DecayFunction,
    DecayType,
    Direction,
    ExpectedReaction,
    ManipulationSign,
    NewsEvent,
    SourceItemRef,
    SourceTier,
    check_clean_text,
    less_aggressive,
    require_utc,
)

POLICY_VERSION = "phase6b-decay-v1"


@dataclass(frozen=True)
class CategoryPolicy:
    min_ttl_minutes: int
    max_ttl_minutes: int
    allow_block: bool = True
    # ETF_SEC_DECISION: "4h to 24h, depending on official status" — without an
    # official source among the counted families the TTL stays at the minimum.
    official_required_for_max: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.min_ttl_minutes <= self.max_ttl_minutes:
            raise ValueError("TTL range must satisfy 0 < min <= max")


# PHASE6B_DESIGN section 6, the conservative v1 starting TTLs (minutes).
DEFAULT_CATEGORY_POLICIES: Mapping[Category, CategoryPolicy] = MappingProxyType(
    {
        Category.ETF_SEC_DECISION: CategoryPolicy(240, 1440, official_required_for_max=True),
        Category.FED_FOMC_RATES: CategoryPolicy(60, 240),
        Category.MACRO_CPI_PPI_JOBS: CategoryPolicy(30, 180),
        Category.EXCHANGE_HACK_EXPLOIT: CategoryPolicy(120, 720),
        Category.MAJOR_REGULATORY_ACTION: CategoryPolicy(240, 1440),
        Category.LIQUIDATION_CASCADE: CategoryPolicy(30, 120),
        Category.GEOPOLITICAL_ESCALATION: CategoryPolicy(60, 360),
        Category.MAJOR_EXCHANGE_PROTOCOL_INCIDENT: CategoryPolicy(60, 720),
    }
)
# PHASE6B_DESIGN section 6, suggested source weights (LOW/UNKNOWN are 0 in v1).
DEFAULT_SOURCE_WEIGHTS: Mapping[SourceTier, float] = MappingProxyType(
    {
        SourceTier.OFFICIAL: 1.00,
        SourceTier.HIGH: 0.90,
        SourceTier.MEDIUM: 0.65,
        SourceTier.LOW: 0.00,
        SourceTier.UNKNOWN: 0.00,
    }
)


@dataclass(frozen=True)
class DecayPolicy:
    """Frozen thresholds, TTLs and decay rules (design 11: freeze before the shadow run)."""

    categories: Mapping[Category, CategoryPolicy] = field(default_factory=lambda: DEFAULT_CATEGORY_POLICIES)
    source_weights: Mapping[SourceTier, float] = field(default_factory=lambda: DEFAULT_SOURCE_WEIGHTS)
    # Section 6 thresholds and section 5 reduction tiers.
    no_effect_below: float = 0.35
    block_at: float = 0.70
    reduce_tiers: Tuple[Tuple[float, Decimal], ...] = ((0.35, Decimal("0.75")), (0.55, Decimal("0.50")))
    # ">= 0.70: max 25% of baseline size or block, depending on category policy".
    block_fallback_multiplier: Decimal = Decimal("0.25")
    decay_type: DecayType = DecayType.LINEAR_TO_ZERO
    exponential_half_life_fraction: float = 0.25
    # A story first published longer ago than its category's maximum TTL is a
    # stale repost: it is logged as EXPIRED with zero effect.
    stale_after_max_ttl: bool = True
    version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        if set(self.categories) != set(Category):
            raise ValueError("a category policy is required for every watchlist category")
        for tier in SourceTier:
            weight = self.source_weights.get(tier)
            if weight is None or not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
                raise ValueError(f"source weight for {tier.value} must be in [0, 1]")
        if self.source_weights[SourceTier.LOW] != 0.0 or self.source_weights[SourceTier.UNKNOWN] != 0.0:
            raise ValueError("LOW and UNKNOWN sources carry zero weight in v1")
        thresholds = [t for t, _ in self.reduce_tiers]
        multipliers = [m for _, m in self.reduce_tiers]
        if not thresholds or thresholds[0] != self.no_effect_below or thresholds != sorted(set(thresholds)):
            raise ValueError("reduce tiers must start at no_effect_below and ascend")
        if not 0.0 < self.no_effect_below < self.block_at <= 1.0 or thresholds[-1] >= self.block_at:
            raise ValueError("thresholds must satisfy 0 < no_effect_below < tiers < block_at <= 1")
        if any(not Decimal(0) < m < Decimal(1) for m in multipliers) or multipliers != sorted(multipliers, reverse=True):
            raise ValueError("reduce multipliers must be in (0, 1) and fall as severity rises")
        if not Decimal(0) < self.block_fallback_multiplier <= multipliers[-1]:
            raise ValueError("block fallback multiplier must be in (0, smallest reduce multiplier]")
        if not 0.0 < self.exponential_half_life_fraction <= 1.0:
            raise ValueError("exponential half-life fraction must be in (0, 1]")
        object.__setattr__(self, "categories", MappingProxyType(dict(self.categories)))
        object.__setattr__(self, "source_weights", MappingProxyType(dict(self.source_weights)))


DEFAULT_POLICY = DecayPolicy()


# -- TTL and decay -----------------------------------------------------------------


def ttl_minutes(category: Category, horizon_minutes: int, has_official_source: bool, policy: DecayPolicy = DEFAULT_POLICY) -> int:
    """The classifier's horizon clamped into the category's TTL range."""
    cp = policy.categories[category]
    upper = cp.min_ttl_minutes if (cp.official_required_for_max and not has_official_source) else cp.max_ttl_minutes
    return max(cp.min_ttl_minutes, min(int(horizon_minutes), upper))


def make_decay_function(starts_at: datetime, zero_at: datetime, policy: DecayPolicy = DEFAULT_POLICY) -> DecayFunction:
    window = (require_utc(zero_at) - require_utc(starts_at)).total_seconds() / 60.0
    if policy.decay_type is DecayType.LINEAR_TO_ZERO:
        half_life = window / 2.0  # where the linear weight reaches 0.5
    else:
        half_life = window * policy.exponential_half_life_fraction
    return DecayFunction(type=policy.decay_type, starts_at=starts_at, half_life_minutes=round(half_life, 3), zero_at=zero_at)


def time_weight(decay: DecayFunction, at: datetime) -> float:
    """Monotonic non-increasing weight in [0, 1]; 0 before ``starts_at`` and from ``zero_at``."""
    at = require_utc(at)
    if at < decay.starts_at or at >= decay.zero_at:
        return 0.0
    age = (at - decay.starts_at).total_seconds() / 60.0
    if decay.type is DecayType.LINEAR_TO_ZERO:
        window = (decay.zero_at - decay.starts_at).total_seconds() / 60.0
        weight = 1.0 - age / window
    else:
        weight = 0.5 ** (age / float(decay.half_life_minutes))
    return min(1.0, max(0.0, weight))


def source_weight(tier: SourceTier, policy: DecayPolicy = DEFAULT_POLICY) -> float:
    return policy.source_weights[tier]


def base_score(event: NewsEvent, policy: DecayPolicy = DEFAULT_POLICY) -> float:
    """``confidence * source_quality_weight * impact_strength`` (before decay)."""
    return event.confidence * source_weight(event.source_quality.tier, policy) * event.asset_impact.impact_strength


def threshold_action(severity: float, category: Category, policy: DecayPolicy = DEFAULT_POLICY) -> Tuple[Action, Decimal]:
    """Section 6 thresholds with section 5 reduction tiers -> (action, size multiplier)."""
    if not math.isfinite(severity) or severity < policy.no_effect_below:
        return Action.NO_EFFECT, Decimal(1)
    if severity >= policy.block_at:
        if policy.categories[category].allow_block:
            return Action.BLOCK_NEW_LONGS, Decimal(0)
        return Action.REDUCE_SIZE, policy.block_fallback_multiplier
    multiplier = Decimal(1)
    for threshold, tier_multiplier in policy.reduce_tiers:
        if severity >= threshold:
            multiplier = tier_multiplier
    return Action.REDUCE_SIZE, multiplier


def cap_action(action: Action, multiplier: Decimal, ceiling: Action, policy: DecayPolicy = DEFAULT_POLICY) -> Tuple[Action, Decimal]:
    """Never more restrictive than ``ceiling`` (the event's classified action)."""
    if ceiling is Action.NO_EFFECT:
        return Action.NO_EFFECT, Decimal(1)
    if ceiling is Action.REDUCE_SIZE and action is Action.BLOCK_NEW_LONGS:
        return Action.REDUCE_SIZE, policy.block_fallback_multiplier
    return action, multiplier


# -- effective signal ------------------------------------------------------------------


@dataclass(frozen=True)
class EffectiveSignal:
    """What one event does at time ``at`` (design 7.6); kept apart from the raw event."""

    event_id: str
    category: Category
    instruments: Tuple[str, ...]
    action: Action
    size_multiplier: Decimal
    effective_severity: float
    time_weight: float
    reason: str
    at: datetime

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "category": self.category.value,
            "instruments": list(self.instruments),
            "action": self.action.value,
            "size_multiplier": str(self.size_multiplier),
            "effective_severity": round(self.effective_severity, 6),
            "time_weight": round(self.time_weight, 6),
            "reason": self.reason,
            "at": self.at.isoformat(),
        }


def effective_signal(event: NewsEvent, at: datetime, policy: DecayPolicy = DEFAULT_POLICY) -> EffectiveSignal:
    at = require_utc(at)
    instruments = tuple(event.asset_impact.instruments)

    def no_effect(reason: str, weight: float = 0.0, severity: float = 0.0) -> EffectiveSignal:
        return EffectiveSignal(event.event_id, event.category, instruments, Action.NO_EFFECT, Decimal(1), severity, weight, reason, at)

    if at < event.first_seen_at:
        return no_effect("not_yet_observed")
    if at >= event.expires_at:
        return no_effect("expired")
    if event.corroboration_status not in ACTIVE_STATUSES:
        return no_effect(f"status_{event.corroboration_status.value.lower()}")
    if event.action is Action.NO_EFFECT:
        return no_effect("classified_no_effect")
    if not instruments:
        return no_effect("no_affected_instruments")
    weight = time_weight(event.decay_function, at)
    if source_weight(event.source_quality.tier, policy) <= 0.0:
        return no_effect("source_weight_zero", weight)
    severity = base_score(event, policy) * weight
    action, multiplier = cap_action(*threshold_action(severity, event.category, policy), event.action, policy)
    if action is Action.NO_EFFECT:
        return no_effect("below_threshold", weight, severity)
    return EffectiveSignal(event.event_id, event.category, instruments, action, multiplier, severity, weight, "active", at)


@dataclass(frozen=True)
class InstrumentSignal:
    """The combined news signal for one instrument at one time."""

    instrument: str
    action: Action
    size_multiplier: Decimal
    effective_severity: float
    deciding_event_id: Optional[str]
    active_event_ids: Tuple[str, ...]
    at: datetime

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "action": self.action.value,
            "size_multiplier": str(self.size_multiplier),
            "effective_severity": round(self.effective_severity, 6),
            "deciding_event_id": self.deciding_event_id,
            "active_event_ids": list(self.active_event_ids),
            "at": self.at.isoformat(),
        }


def combine(signals: Iterable[EffectiveSignal], instrument: str, at: datetime) -> InstrumentSignal:
    """Most conservative active signal for ``instrument``; the lowest multiplier, never a product."""
    at = require_utc(at)
    active = [s for s in signals if instrument in s.instruments and s.action is not Action.NO_EFFECT]
    if not active:
        return InstrumentSignal(instrument, Action.NO_EFFECT, Decimal(1), 0.0, None, (), at)
    best = min(active, key=lambda s: (-ACTION_RANK[s.action], s.size_multiplier, -s.effective_severity, s.event_id))
    return InstrumentSignal(
        instrument,
        best.action,
        best.size_multiplier,
        best.effective_severity,
        best.event_id,
        tuple(sorted({s.event_id for s in active})),
        at,
    )


def signal_for_instrument(
    events: Iterable[NewsEvent], instrument: str, at: datetime, policy: DecayPolicy = DEFAULT_POLICY
) -> Tuple[InstrumentSignal, Tuple[EffectiveSignal, ...]]:
    """Effective signals of every event at ``at`` and their combination for ``instrument``."""
    signals = tuple(effective_signal(e, at, policy) for e in events)
    return combine(signals, instrument, at), signals


# -- event assembly (design 7: TTL and decay assignment -> structured event) -----------

# Signs that alone force NO_EFFECT, whatever the corroboration.
VETO_SIGNS = frozenset(
    {
        ManipulationSign.SATIRE_OR_PARODY,
        ManipulationSign.STALE_REPOST,
        ManipulationSign.HIDDEN_INSTRUCTIONS,
        ManipulationSign.HOMOGLYPH_OR_SPOOFED_TEXT,
    }
)
STICKY_STATUSES = frozenset({CorroborationStatus.CONFLICTED, CorroborationStatus.REJECTED, CorroborationStatus.EXPIRED})
WITHHELD_SUMMARY = "Summary withheld: the classifier summary did not pass sanitization."


def clean_summary(text: str) -> str:
    """The classifier's claim as short sanitized audit text (or a fixed placeholder)."""
    sanitized = sanitize_text(text or "", max_chars=RAW_SUMMARY_MAX_CHARS)
    if sanitized.severe:
        return WITHHELD_SUMMARY
    candidate = unicodedata.normalize("NFKC", sanitized.text)[:RAW_SUMMARY_MAX_CHARS].strip()
    try:
        return check_clean_text(candidate) if candidate else WITHHELD_SUMMARY
    except ValueError:
        return WITHHELD_SUMMARY


@dataclass(frozen=True)
class EventBuild:
    """The assembled (or merged) event plus every deterministic downgrade applied."""

    event: Optional[NewsEvent]
    reasons: Tuple[str, ...]
    merged: bool = False
    evidence_upgraded: bool = False

    def to_dict(self) -> dict:
        return {
            "event": self.event.model_dump(mode="json") if self.event is not None else None,
            "reasons": list(self.reasons),
            "merged": self.merged,
            "evidence_upgraded": self.evidence_upgraded,
        }


def _source_time(item: SourceItemRef) -> datetime:
    if item.published_at is not None and item.published_at <= item.observed_at:
        return item.published_at
    return item.observed_at


def _classified_action(
    verdict: ClassifierVerdict,
    status: CorroborationStatus,
    tier: SourceTier,
    category: Category,
    instruments: Sequence[str],
    policy: DecayPolicy,
) -> Tuple[Action, List[str]]:
    """The classifier's proposal, lowered by every deterministic rule that applies."""
    action = verdict.proposed_action
    reasons: List[str] = []

    def lower_to_no_effect(reason: str) -> None:
        nonlocal action
        if action is not Action.NO_EFFECT:
            reasons.append(reason)
        action = Action.NO_EFFECT

    if status not in ACTIVE_STATUSES:
        lower_to_no_effect(f"status_{status.value.lower()}")
    vetoes = sorted(s.value for s in set(verdict.manipulation_signs) & VETO_SIGNS)
    if vetoes:
        lower_to_no_effect("manipulation_veto:" + ",".join(vetoes))
    if verdict.expected_market_reaction is ExpectedReaction.NO_CLEAR_REACTION:
        lower_to_no_effect("no_clear_reaction")
    if verdict.direction is Direction.RISK_ON and verdict.expected_market_reaction not in (
        ExpectedReaction.UP_BUT_REVERSAL_RISK,
        ExpectedReaction.VOLATILITY_ONLY,
    ):
        lower_to_no_effect("bullish_without_volatility_danger")
    if source_weight(tier, policy) <= 0.0:
        lower_to_no_effect("source_weight_zero")
    if not instruments:
        lower_to_no_effect("no_affected_assets")
    if action is not Action.NO_EFFECT:
        score = verdict.confidence * source_weight(tier, policy) * verdict.impact_strength
        capped, _ = cap_action(*threshold_action(score, category, policy), action, policy)
        if capped is not action:
            reasons.append(f"threshold_at_creation:{capped.value}")
        action = capped
    return action, reasons


def build_event(
    *,
    verdict: ClassifierVerdict,
    items: Sequence[SourceItemRef],
    corroboration: CorroborationResult,
    story_key: str,
    existing: Optional[NewsEvent] = None,
    policy: DecayPolicy = DEFAULT_POLICY,
) -> EventBuild:
    """Turn a validated verdict into a ``NewsEvent`` (or merge it into ``existing``).

    Identity, timestamps, TTL, decay and corroboration status are deterministic;
    the verdict's ``proposed_action`` is only a ceiling. Returns ``event=None``
    (with the reason) for non-watchlist stories and for anything that fails
    validation — a failure is NO_EFFECT, never an exception into the caller.
    """
    if verdict.category is ClassifiedCategory.NONE:
        return EventBuild(None, ("not_a_watchlist_category",))
    usable = [i for i in items if not i.quarantined]
    if not usable:
        return EventBuild(None, ("no_usable_items",))
    category = Category(verdict.category.value)
    first_seen = min(i.observed_at for i in usable)
    first_source = min(_source_time(i) for i in usable)
    assets = tuple(a for a in ASSET_ORDER if a in set(verdict.assets))
    instruments = tuple(INSTRUMENT_FOR_ASSET[a] for a in assets)

    status = corroboration.status
    reasons: List[str] = []
    max_ttl = timedelta(minutes=policy.categories[category].max_ttl_minutes)
    if policy.stale_after_max_ttl and first_seen - first_source >= max_ttl:
        status = CorroborationStatus.EXPIRED
        reasons.append("stale_repost")
    ttl = ttl_minutes(category, verdict.time_horizon_minutes, corroboration.has_official, policy)
    expires_at = first_seen + timedelta(minutes=ttl)
    action, action_reasons = _classified_action(verdict, status, corroboration.tier, category, instruments, policy)
    reasons.extend(action_reasons)
    try:
        fresh = NewsEvent(
            event_id=existing.event_id
            if existing is not None
            else make_event_id(category.value, story_key, first_source, [a.value for a in assets]),
            category=category,
            first_seen_at=first_seen,
            expires_at=expires_at,
            confidence=verdict.confidence,
            corroboration_status=status,
            source_quality=corroboration.source_quality(),
            asset_impact=AssetImpact(
                assets=assets,
                instruments=instruments,
                direction=verdict.direction,
                expected_market_reaction=verdict.expected_market_reaction,
                impact_strength=verdict.impact_strength,
                volatility_risk=verdict.volatility_risk,
                time_horizon_minutes=verdict.time_horizon_minutes,
            ),
            action=action,
            decay_function=make_decay_function(first_seen, expires_at, policy),
            raw_summary=clean_summary(verdict.claim_summary),
        )
    except (ValidationError, ValueError) as exc:
        return EventBuild(None, tuple(reasons) + (f"event_validation_failed:{type(exc).__name__}",))
    if existing is None:
        return EventBuild(fresh, tuple(reasons))
    return merge_event(existing, fresh, reasons=reasons)


def _evidence(event: NewsEvent) -> Tuple[int, int]:
    return (1 if event.corroboration_status in ACTIVE_STATUSES else 0, event.source_quality.independent_source_count)


def merge_event(existing: NewsEvent, fresh: NewsEvent, *, reasons: Sequence[str] = ()) -> EventBuild:
    """Same story again (design 6): keep identity and TTL, refresh evidence.

    - ``event_id``, ``category``, ``first_seen_at``, ``expires_at`` and the decay
      function never change: a repeat never re-fires the TTL.
    - CONFLICTED, REJECTED and EXPIRED are sticky.
    - Strength (confidence, impact, volatility, action, summary) may rise only
      when the evidence rose (an inactive event became corroborated, or more
      independent sources); otherwise each is the weaker of old and new.
    """
    notes = list(reasons)
    sticky = existing.corroboration_status in STICKY_STATUSES
    status = existing.corroboration_status if sticky else fresh.corroboration_status
    source_quality = existing.source_quality if sticky else fresh.source_quality
    upgraded = (not sticky) and status in ACTIVE_STATUSES and _evidence(fresh) > _evidence(existing)
    if sticky:
        notes.append(f"sticky_status:{existing.corroboration_status.value}")
    if fresh.category is not existing.category:
        notes.append("category_kept_from_existing")
    if upgraded:
        notes.append("evidence_upgraded")
        confidence, impact, action, summary = fresh.confidence, fresh.asset_impact, fresh.action, fresh.raw_summary
    else:
        confidence = min(existing.confidence, fresh.confidence)
        impact = existing.asset_impact.model_copy(
            update={
                "impact_strength": min(existing.asset_impact.impact_strength, fresh.asset_impact.impact_strength),
                "volatility_risk": min(existing.asset_impact.volatility_risk, fresh.asset_impact.volatility_risk),
            }
        )
        action = less_aggressive(existing.action, fresh.action)
        summary = existing.raw_summary
    if status in NO_EFFECT_STATUSES:
        action = Action.NO_EFFECT
    try:
        merged = NewsEvent(
            event_id=existing.event_id,
            category=existing.category,
            first_seen_at=existing.first_seen_at,
            expires_at=existing.expires_at,
            confidence=confidence,
            corroboration_status=status,
            source_quality=source_quality,
            asset_impact=impact,
            action=action,
            decay_function=existing.decay_function,
            raw_summary=summary,
        )
    except (ValidationError, ValueError) as exc:
        return EventBuild(existing, tuple(notes) + (f"merge_validation_failed:{type(exc).__name__}",), merged=False)
    return EventBuild(merged, tuple(notes) + ("merged",), merged=True, evidence_upgraded=upgraded)
