"""Builders shared by the news-agent tests (offline: no network, no API key, no LLM)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.news.corroborate import CorroborationResult, PublicCandle
from app.news.schema import (
    Action,
    AssetImpact,
    Category,
    ClassifierVerdict,
    CorroborationStatus,
    DecayFunction,
    DecayType,
    Direction,
    ExpectedReaction,
    NewsEvent,
    SourceItemRef,
    SourceQuality,
    SourceTier,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def item(
    n: int,
    *,
    publisher: str = "Example News",
    owner: str = "",
    url: Optional[str] = None,
    tier: SourceTier = SourceTier.MEDIUM,
    title: Optional[str] = None,
    excerpt: str = "",
    observed: datetime = NOW,
    published: Optional[datetime] = None,
    flags: Sequence[str] = (),
    quarantined: bool = False,
) -> SourceItemRef:
    return SourceItemRef(
        item_id=f"itm_{n:020x}",
        source_id="test_feed",
        publisher=publisher,
        publisher_owner=owner,
        canonical_url=url if url is not None else f"https://news{n}.example/story-{n}",
        tier=tier,
        observed_at=observed,
        published_at=published if published is not None else observed - timedelta(minutes=2),
        title=title if title is not None else f"Exchange halts withdrawals after wallet drain report {n}",
        excerpt=excerpt,
        sanitization_flags=tuple(flags),
        quarantined=quarantined,
    )


def verdict(**overrides: Any) -> ClassifierVerdict:
    base: Dict[str, Any] = dict(
        category="EXCHANGE_HACK_EXPLOIT",
        assets=["BTC", "ETH"],
        claim_summary="A major exchange reports a hot-wallet drain and pauses withdrawals.",
        manipulation_signs=[],
        corroboration_assessment="INDEPENDENT_SOURCE_CONFIRMED",
        independent_source_ids=[],
        hedging_uncertainty=0.2,
        direction="RISK_OFF",
        expected_market_reaction="DOWN_OR_VOLATILE",
        impact_strength=0.9,
        volatility_risk=0.9,
        time_horizon_minutes=240,
        confidence=0.9,
        same_story_as=None,
        new_development=False,
        why_not_more_aggressive="Block is already the most restrictive action available.",
        proposed_action="BLOCK_NEW_LONGS",
    )
    base.update(overrides)
    return ClassifierVerdict.model_validate(base)


def verdict_json(**overrides: Any) -> str:
    return verdict(**overrides).model_dump_json()


def corroboration(
    status: CorroborationStatus = CorroborationStatus.INDEPENDENT_SOURCE_CONFIRMED,
    *,
    count: int = 2,
    tier: SourceTier = SourceTier.HIGH,
    has_official: bool = False,
    source_ids: Sequence[str] = ("itm_1", "itm_2"),
) -> CorroborationResult:
    return CorroborationResult(
        status=status,
        independent_source_count=count,
        tier=tier,
        has_official=has_official,
        families={f"domain:f{i}.example": (sid,) for i, sid in enumerate(source_ids)},
        primary_sources=("Official Agency",) if has_official else (),
        secondary_sources=tuple(f"Publisher {i}" for i in range(max(0, count - (1 if has_official else 0)))),
        source_ids=tuple(source_ids),
        notes=f"{count} independent credible families",
    )


def event(
    *,
    event_id: str = "evt_20261020_hack_btc_eth_0123456789ab",
    category: Category = Category.EXCHANGE_HACK_EXPLOIT,
    first_seen: datetime = NOW,
    ttl_minutes: int = 240,
    confidence: float = 0.9,
    status: CorroborationStatus = CorroborationStatus.INDEPENDENT_SOURCE_CONFIRMED,
    tier: SourceTier = SourceTier.HIGH,
    count: int = 2,
    assets: Sequence[str] = ("BTC", "ETH"),
    impact: float = 0.9,
    volatility: float = 0.9,
    action: Action = Action.BLOCK_NEW_LONGS,
    decay_type: DecayType = DecayType.LINEAR_TO_ZERO,
    half_life: Optional[float] = None,
    summary: str = "A major exchange reports a hot-wallet drain and pauses withdrawals.",
) -> NewsEvent:
    expires = first_seen + timedelta(minutes=ttl_minutes)
    instruments = [f"{a}-USDT" for a in assets]
    return NewsEvent(
        event_id=event_id,
        category=category,
        first_seen_at=first_seen,
        expires_at=expires,
        confidence=confidence,
        corroboration_status=status,
        source_quality=SourceQuality(
            tier=tier,
            independent_source_count=count,
            primary_sources=(),
            secondary_sources=("Publisher A", "Publisher B")[: max(0, min(count, 2))],
            source_ids=("itm_a", "itm_b")[: max(0, min(count, 2))],
            notes="test",
        ),
        asset_impact=AssetImpact(
            assets=tuple(assets),
            instruments=tuple(instruments),
            direction=Direction.RISK_OFF,
            expected_market_reaction=ExpectedReaction.DOWN_OR_VOLATILE,
            impact_strength=impact,
            volatility_risk=volatility,
            time_horizon_minutes=ttl_minutes,
        ),
        action=action,
        decay_function=DecayFunction(
            type=decay_type,
            starts_at=first_seen,
            half_life_minutes=half_life if half_life is not None else ttl_minutes / 2,
            zero_at=expires,
        ),
        raw_summary=summary,
    )


def candles(
    closes: Sequence[float],
    *,
    start: datetime,
    minutes: int = 15,
    volumes: Optional[Sequence[float]] = None,
    spread: float = 10.0,
) -> List[PublicCandle]:
    """Candles with the given closes; open = previous close, high/low = +/- spread."""
    out: List[PublicCandle] = []
    prev = closes[0]
    for i, close in enumerate(closes):
        volume = volumes[i] if volumes is not None else 100.0
        out.append(
            PublicCandle(
                open_time=start + timedelta(minutes=minutes * i),
                interval=timedelta(minutes=minutes),
                open=prev,
                high=max(prev, close) + spread,
                low=min(prev, close) - spread,
                close=close,
                volume=volume,
            )
        )
        prev = close
    return out


# -- a fake Anthropic client (the real SDK is exercised separately on an offline transport) --


@dataclass
class FakeBlock:
    type: str
    text: str = ""
    thinking: str = ""


@dataclass
class FakeUsage:
    input_tokens: int = 1200
    output_tokens: int = 300
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 1100


@dataclass
class FakeStopDetails:
    category: Optional[str] = None


@dataclass
class FakeResponse:
    content: List[FakeBlock]
    stop_reason: str = "end_turn"
    model: str = "claude-opus-5-5"
    usage: FakeUsage = field(default_factory=FakeUsage)
    stop_details: Optional[FakeStopDetails] = None
    _request_id: str = "req_offline_test"


def text_response(text: str, *, stop_reason: str = "end_turn", model: str = "claude-opus-5-5") -> FakeResponse:
    return FakeResponse(content=[FakeBlock("thinking"), FakeBlock("text", text=text)], stop_reason=stop_reason, model=model)


class FakeMessages:
    def __init__(self, outer: "FakeClient") -> None:
        self._outer = outer

    def create(self, **kwargs: Any) -> FakeResponse:
        self._outer.calls.append(kwargs)
        reply = self._outer.replies.pop(0) if self._outer.replies else self._outer.default
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            return reply(kwargs)
        return reply


class FakeClient:
    """Records every ``messages.create`` call; replies from a queue (or a default)."""

    def __init__(self, *replies: Any, default: Any = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.replies = list(replies)
        self.default = default if default is not None else text_response(verdict_json())
        self.messages = FakeMessages(self)

    def user_payload(self, index: int = -1) -> Dict[str, Any]:
        text = self.calls[index]["messages"][0]["content"]
        body = text.split("\n", 1)[1].rsplit("\n", 1)[0]
        return json.loads(body)
