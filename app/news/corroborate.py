"""Deterministic corroboration (PHASE6B_DESIGN sections 2, 7.5 and 10) — no LLM.

An event may affect risk only after a second *independent* credible source, or
public price/volume confirmation, backs it. This module decides both:

Independence (``source_family``): every article is mapped to the family it
really comes from, and only distinct families count.

- A wire service's own article and every article attributing the story to that
  wire ("Reuters reported", "(AP)") are one family: syndicated copies.
- Articles that only relay a social-media post ("said in a post on X",
  "screenshot", "Telegram channel") are one family: the post.
- Outlets with the same known owner are one family.
- Articles carrying the same headline are copies of the earliest one.
- LOW and UNKNOWN tiers never count (their v1 weight is zero), nor do
  quarantined items. The classifier may *narrow* the counted set (it lists the
  sources it believes independent) but can never add to it, and its
  CONFLICTED / REJECTED / EXPIRED assessments are respected: the LLM can only
  push an event toward NO_EFFECT.

Price/volume (``confirm_price_volume``): uses only candles that CLOSED at or
before the decision time — later candles are ignored even when supplied.
Confirmed when the move since the last pre-event close is at least
``0.5 x ATR`` (ATR from pre-event candles only), the reaction volume averages
at least ``1.5 x`` the pre-event rolling volume, and the move's direction
matches the expected reaction. An upward move never authorizes a boost; for
``UP_BUT_REVERSAL_RISK`` it only confirms that the volatility danger is real.

Public market data only; nothing here reads credentials or touches an order.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from app.news.dedup import normalize_title_key
from app.news.schema import (
    CorroborationStatus,
    ExpectedReaction,
    SourceItemRef,
    SourceQuality,
    SourceTier,
    require_utc,
)

CREDIBLE_TIERS = frozenset({SourceTier.OFFICIAL, SourceTier.HIGH, SourceTier.MEDIUM})
TIER_RANK: Mapping[SourceTier, int] = {
    SourceTier.UNKNOWN: 0,
    SourceTier.LOW: 1,
    SourceTier.MEDIUM: 2,
    SourceTier.HIGH: 3,
    SourceTier.OFFICIAL: 4,
}
SOCIAL_FAMILY = "social:post"

# Wire services: the domains they publish on, and attribution phrases in other outlets' text.
_WIRE_DOMAINS: Mapping[str, str] = {
    "reuters.com": "reuters",
    "apnews.com": "ap",
    "ap.org": "ap",
    "afp.com": "afp",
    "bloomberg.com": "bloomberg",
    "dowjones.com": "dowjones",
}
_WIRE_ATTRIBUTION: Tuple[Tuple[str, re.Pattern], ...] = (
    ("reuters", re.compile(r"\breuters\b", re.I)),
    ("ap", re.compile(r"\bassociated press\b|\(AP\)|\bAP News\b")),
    ("afp", re.compile(r"\bagence france[- ]presse\b|\bAFP\b")),
    ("bloomberg", re.compile(r"\bbloomberg\b", re.I)),
    ("dowjones", re.compile(r"\bdow jones newswires?\b", re.I)),
)
_SOCIAL_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(
        r"\b(?:posted|post|posts|wrote|said|says|announced|claimed|shared)\s+(?:on|to|via)\s+"
        r"(?:x|twitter|telegram|truth social|discord|weibo|reddit|tiktok)\b",
        re.I,
    ),
    re.compile(r"\b(?:a|an|the|his|her|their|its)\s+(?:social media\s+|viral\s+)?(?:x|twitter|telegram)\s+post\b", re.I),
    re.compile(r"\btweet(?:s|ed)?\b", re.I),
    re.compile(r"\bscreenshots?\b", re.I),
    re.compile(r"\btelegram (?:channel|group|post|message)\b", re.I),
    re.compile(r"\bviral (?:post|video|tweet|clip)\b", re.I),
    re.compile(r"\baccording to (?:a|an) (?:social media )?post\b", re.I),
)
_MULTI_PART_SUFFIXES = frozenset({"co", "com", "org", "net", "gov", "ac", "edu"})


def _domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower() if url else ""
    if host.startswith("www."):
        host = host[4:]
    labels = [p for p in host.split(".") if p]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def wire_attribution(text: str) -> Optional[str]:
    for wire, pattern in _WIRE_ATTRIBUTION:
        if pattern.search(text or ""):
            return wire
    return None


def quotes_social_post(text: str) -> bool:
    return any(p.search(text or "") for p in _SOCIAL_PATTERNS)


def source_family(item: SourceItemRef, owner_overrides: Optional[Mapping[str, str]] = None) -> str:
    """The family an article really comes from (independence unit; see module doc)."""
    domain = _domain(item.canonical_url)
    owner = _norm((owner_overrides or {}).get(domain, "") or item.publisher_owner)
    if item.tier is SourceTier.OFFICIAL:
        # An official primary source is its own family (never a copy of a wire).
        return f"owner:{owner}" if owner else (f"domain:{domain}" if domain else f"publisher:{_norm(item.publisher)}")
    if domain in _WIRE_DOMAINS:
        return f"wire:{_WIRE_DOMAINS[domain]}"
    text = f"{item.title} {item.excerpt}"
    wire = wire_attribution(text)
    if wire:
        return f"wire:{wire}"
    if quotes_social_post(text):
        return SOCIAL_FAMILY
    if owner:
        return f"owner:{owner}"
    if domain:
        return f"domain:{domain}"
    return f"publisher:{_norm(item.publisher) or item.item_id}"


def _source_time(item: SourceItemRef) -> datetime:
    if item.published_at is not None and item.published_at <= item.observed_at:
        return item.published_at
    return item.observed_at


def assign_families(
    items: Sequence[SourceItemRef], owner_overrides: Optional[Mapping[str, str]] = None
) -> Dict[str, str]:
    """``item_id -> family``. Articles sharing a headline are copies: they join the
    family of the earliest OFFICIAL item with that headline, else of the earliest
    item. An official item always keeps its own family."""
    ordered = sorted(items, key=lambda i: (i.tier is not SourceTier.OFFICIAL, _source_time(i), i.item_id))
    own = {i.item_id: source_family(i, owner_overrides) for i in ordered}
    by_title: Dict[str, str] = {}
    for item in ordered:  # official items first, so a verbatim repost of one joins its family
        title_key = normalize_title_key(item.title)
        if title_key:
            by_title.setdefault(title_key, own[item.item_id])
    families: Dict[str, str] = {}
    for item in ordered:
        title_key = normalize_title_key(item.title)
        if item.tier is SourceTier.OFFICIAL or not title_key:
            families[item.item_id] = own[item.item_id]
        else:
            families[item.item_id] = by_title[title_key]
    return families


# -- price / volume confirmation -------------------------------------------------


@dataclass(frozen=True)
class PublicCandle:
    """One PUBLIC OHLCV candle (open time + interval; floats are fine for analysis)."""

    open_time: datetime
    interval: timedelta
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_time", require_utc(self.open_time))
        if self.interval <= timedelta(0):
            raise ValueError("candle interval must be positive")
        for name in ("open", "high", "low", "close", "volume"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"candle {name} must be finite")

    @property
    def close_time(self) -> datetime:
        return self.open_time + self.interval


@dataclass(frozen=True)
class PriceVolumeCheck:
    instrument: str
    confirmed: bool
    reason: str
    decision_time: datetime
    event_time: datetime
    reference_close: Optional[float] = None
    last_close: Optional[float] = None
    move: Optional[float] = None
    atr: Optional[float] = None
    volume_ratio: Optional[float] = None
    baseline_candles: int = 0
    reaction_candles: int = 0
    ignored_unclosed_candles: int = 0

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "confirmed": self.confirmed,
            "reason": self.reason,
            "decision_time": self.decision_time.isoformat(),
            "event_time": self.event_time.isoformat(),
            "reference_close": self.reference_close,
            "last_close": self.last_close,
            "move": self.move,
            "atr": self.atr,
            "volume_ratio": self.volume_ratio,
            "baseline_candles": self.baseline_candles,
            "reaction_candles": self.reaction_candles,
            "ignored_unclosed_candles": self.ignored_unclosed_candles,
        }


def _closed_before(candles: Iterable[PublicCandle], decision_time: datetime) -> Tuple[List[PublicCandle], int]:
    """Candles that closed at or before ``decision_time``, sorted; plus how many were dropped."""
    known: Dict[datetime, PublicCandle] = {}
    dropped = 0
    for c in candles:
        if c.close_time > decision_time:
            dropped += 1
            continue
        if c.open_time in known and known[c.open_time] != c:
            raise ValueError("conflicting candles for the same open time")
        known[c.open_time] = c
    return [known[t] for t in sorted(known)], dropped


def average_true_range(candles: Sequence[PublicCandle], period: int) -> Optional[float]:
    """Simple mean of the last ``period`` true ranges (needs ``period + 1`` candles)."""
    if period <= 0 or len(candles) < period + 1:
        return None
    ranges = []
    for prev, cur in zip(candles[-period - 1 : -1], candles[-period:]):
        ranges.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(ranges) / period


_REACTION_DIRECTIONS: Mapping[ExpectedReaction, Tuple[int, ...]] = {
    ExpectedReaction.DOWN_OR_VOLATILE: (-1,),
    ExpectedReaction.UP_BUT_REVERSAL_RISK: (1,),
    ExpectedReaction.VOLATILITY_ONLY: (-1, 1),
    ExpectedReaction.NO_CLEAR_REACTION: (),
}


def confirm_price_volume(
    candles: Iterable[PublicCandle],
    *,
    instrument: str,
    event_time: datetime,
    decision_time: datetime,
    reaction: ExpectedReaction,
    atr_period: int = 14,
    volume_period: int = 20,
    atr_multiple: float = 0.5,
    volume_multiple: float = 1.5,
    reaction_window: timedelta = timedelta(hours=4),
) -> PriceVolumeCheck:
    """Did public price/volume confirm the expected reaction, using only data
    known at ``decision_time``? (design 7.5 suggested starting rule)"""
    event_time = require_utc(event_time)
    decision_time = require_utc(decision_time)

    def result(confirmed: bool, reason: str, **kw) -> PriceVolumeCheck:
        return PriceVolumeCheck(instrument, confirmed, reason, decision_time, event_time, **kw)

    if decision_time < event_time:
        return result(False, "decision_before_event")
    try:
        known, dropped = _closed_before(candles, decision_time)
    except ValueError:
        return result(False, "conflicting_candles")
    baseline = [c for c in known if c.close_time <= event_time]
    reaction_candles = [c for c in known if c.close_time > event_time and c.open_time < event_time + reaction_window]
    counts = dict(baseline_candles=len(baseline), reaction_candles=len(reaction_candles), ignored_unclosed_candles=dropped)
    if not _REACTION_DIRECTIONS[reaction]:
        return result(False, "no_clear_reaction_expected", **counts)
    if len(baseline) < max(atr_period + 1, volume_period) or not reaction_candles:
        return result(False, "insufficient_data", **counts)
    atr = average_true_range(baseline, atr_period)
    base_volume = sum(c.volume for c in baseline[-volume_period:]) / volume_period
    if not atr or atr <= 0 or base_volume <= 0:
        return result(False, "insufficient_data", **counts)
    reference = baseline[-1].close
    last = reaction_candles[-1].close
    move = last - reference
    volume_ratio = (sum(c.volume for c in reaction_candles) / len(reaction_candles)) / base_volume
    detail = dict(reference_close=reference, last_close=last, move=move, atr=atr, volume_ratio=volume_ratio, **counts)
    sign = (move > 0) - (move < 0)
    if sign not in _REACTION_DIRECTIONS[reaction]:
        return result(False, "direction_mismatch", **detail)
    if abs(move) < atr_multiple * atr:
        return result(False, "move_below_threshold", **detail)
    if volume_ratio < volume_multiple:
        return result(False, "volume_below_threshold", **detail)
    return result(True, "confirmed", **detail)


def market_context(
    candles: Iterable[PublicCandle], *, decision_time: datetime, lookback: timedelta = timedelta(minutes=15), volume_period: int = 20
) -> Optional[Dict[str, str]]:
    """Classifier market context from candles closed before ``decision_time`` only."""
    decision_time = require_utc(decision_time)
    try:
        known, _ = _closed_before(candles, decision_time)
    except ValueError:
        return None
    if len(known) < 2:
        return None
    last = known[-1]
    earlier = [c for c in known if c.close_time <= last.close_time - lookback]
    ref = earlier[-1].close if earlier else known[0].close
    prior = known[-1 - volume_period : -1]
    avg_volume = sum(c.volume for c in prior) / len(prior) if prior else 0.0
    move_pct = (last.close - ref) / ref * 100 if ref else 0.0
    return {
        "last_price": f"{last.close:.8g}",
        f"move_{int(lookback.total_seconds() // 60)}m_pct": f"{move_pct:.3f}",
        "volume_vs_rolling": f"{(last.volume / avg_volume) if avg_volume > 0 else 0.0:.3f}",
        "as_of": last.close_time.isoformat(),
        "atr_reference": "available_before_now_only",
    }


# -- the corroboration decision ---------------------------------------------------


@dataclass(frozen=True)
class CorroborationResult:
    status: CorroborationStatus
    independent_source_count: int
    tier: SourceTier
    has_official: bool
    families: Mapping[str, Tuple[str, ...]]
    primary_sources: Tuple[str, ...]
    secondary_sources: Tuple[str, ...]
    source_ids: Tuple[str, ...]
    notes: str
    price_volume: Tuple[PriceVolumeCheck, ...] = field(default_factory=tuple)

    @property
    def price_volume_confirmed(self) -> bool:
        return any(c.confirmed for c in self.price_volume)

    def source_quality(self) -> SourceQuality:
        return SourceQuality(
            tier=self.tier,
            independent_source_count=self.independent_source_count,
            primary_sources=self.primary_sources,
            secondary_sources=self.secondary_sources,
            source_ids=self.source_ids,
            notes=self.notes,
        )

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "independent_source_count": self.independent_source_count,
            "tier": self.tier.value,
            "has_official": self.has_official,
            "families": {k: list(v) for k, v in self.families.items()},
            "source_ids": list(self.source_ids),
            "notes": self.notes,
            "price_volume": [c.to_dict() for c in self.price_volume],
        }


_LLM_TERMINAL = frozenset({CorroborationStatus.CONFLICTED, CorroborationStatus.REJECTED, CorroborationStatus.EXPIRED})


def _clean(text: str, limit: int) -> str:
    """NFKC, no control/format characters, single spaces, at most ``limit`` chars."""
    normalized = unicodedata.normalize("NFKC", text or "")
    kept = "".join(ch for ch in normalized if unicodedata.category(ch) not in ("Cc", "Cf"))
    return re.sub(r"\s+", " ", kept).strip()[:limit].strip()


def _label(text: str) -> str:
    return _clean(text, 200) or "unknown"


def assess(
    items: Sequence[SourceItemRef],
    *,
    llm_assessment: Optional[CorroborationStatus] = None,
    supporting_ids: Optional[Iterable[str]] = None,
    price_volume: Sequence[PriceVolumeCheck] = (),
    owner_overrides: Optional[Mapping[str, str]] = None,
) -> CorroborationResult:
    """Deterministic corroboration status for one story's items (design 7.5)."""
    usable = [i for i in items if not i.quarantined]
    families = assign_families(usable, owner_overrides)
    supporting = None if supporting_ids is None else set(supporting_ids)
    counted = [
        i
        for i in usable
        if i.tier in CREDIBLE_TIERS and (supporting is None or i.item_id in supporting)
    ]
    grouped: Dict[str, List[SourceItemRef]] = {}
    for item in counted:
        grouped.setdefault(families[item.item_id], []).append(item)
    family_tier = {f: max((i.tier for i in its), key=TIER_RANK.__getitem__) for f, its in grouped.items()}
    count = len(grouped)
    if family_tier:
        tier = max(family_tier.values(), key=TIER_RANK.__getitem__)
    else:
        tier = max((i.tier for i in usable), key=TIER_RANK.__getitem__, default=SourceTier.UNKNOWN)
    pv = tuple(price_volume)
    pv_ok = any(c.confirmed for c in pv)

    if llm_assessment in _LLM_TERMINAL:
        status = llm_assessment
    elif count >= 2:
        status = CorroborationStatus.INDEPENDENT_SOURCE_CONFIRMED
    elif count >= 1 and pv_ok:
        status = CorroborationStatus.PRICE_VOLUME_CONFIRMED
    else:
        status = CorroborationStatus.SINGLE_SOURCE

    def first_publisher(its: List[SourceItemRef]) -> str:
        return _label(min(its, key=lambda i: (_source_time(i), i.item_id)).publisher)

    primary = tuple(sorted(first_publisher(its) for f, its in grouped.items() if family_tier[f] is SourceTier.OFFICIAL))
    secondary = tuple(sorted(first_publisher(its) for f, its in grouped.items() if family_tier[f] is not SourceTier.OFFICIAL))
    excluded = len(usable) - len(counted)
    collapsed = len(counted) - count
    notes = (
        f"{count} independent credible famil{'y' if count == 1 else 'ies'}"
        f" ({', '.join(sorted(grouped)) or 'none'}); {collapsed} copies collapsed; "
        f"{excluded} items not counted; {len(items) - len(usable)} quarantined; "
        f"price/volume {'confirmed' if pv_ok else 'not confirmed'}"
        + (f"; classifier assessed {llm_assessment.value}" if llm_assessment is not None else "")
    )
    return CorroborationResult(
        status=status,
        independent_source_count=count,
        tier=tier,
        has_official=any(t is SourceTier.OFFICIAL for t in family_tier.values()),
        families={f: tuple(sorted(i.item_id for i in its)) for f, its in sorted(grouped.items())},
        primary_sources=primary[:20],
        secondary_sources=secondary[:20],
        source_ids=tuple(sorted(i.item_id for i in counted))[:50],
        notes=_clean(notes, 500),
        price_volume=pv,
    )
