"""Phase 6b event schema (design section 4) and story-level event ids (design 4, 7.3)."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.news import dedup
from app.news.schema import (
    ACTION_RANK,
    Action,
    AssetImpact,
    Category,
    ClassifiedCategory,
    ClassifierVerdict,
    CorroborationStatus,
    DecayFunction,
    Direction,
    ExpectedReaction,
    NewsEvent,
    SourceItemRef,
    SourceTier,
    TriageVerdict,
    less_aggressive,
    most_conservative,
)
from app.news.sources import CATEGORIES
from tests.news_fixtures import NOW, event, verdict

ROOT = Path(__file__).resolve().parents[1]

# The JSON example of PHASE6B_DESIGN section 4, verbatim.
DESIGN_EXAMPLE = {
    "event_id": "evt_20260617_geopol_iran_btc_eth_8f3a91c2",
    "category": "GEOPOLITICAL_ESCALATION",
    "first_seen_at": "2026-06-17T14:05:12Z",
    "expires_at": "2026-06-17T18:05:12Z",
    "confidence": 0.78,
    "corroboration_status": "INDEPENDENT_SOURCE_CONFIRMED",
    "source_quality": {
        "tier": "HIGH",
        "independent_source_count": 2,
        "primary_sources": ["official_government_statement"],
        "secondary_sources": ["major_wire_or_reputable_financial_news"],
        "source_ids": ["src_1", "src_2"],
        "notes": "Second source is independently reported, not a copy of the first.",
    },
    "asset_impact": {
        "assets": ["BTC", "ETH"],
        "instruments": ["BTC-USDT", "ETH-USDT"],
        "direction": "RISK_OFF",
        "expected_market_reaction": "DOWN_OR_VOLATILE",
        "impact_strength": 0.72,
        "volatility_risk": 0.88,
        "time_horizon_minutes": 240,
    },
    "action": "BLOCK_NEW_LONGS",
    "decay_function": {
        "type": "LINEAR_TO_ZERO",
        "starts_at": "2026-06-17T14:05:12Z",
        "half_life_minutes": 60,
        "zero_at": "2026-06-17T18:05:12Z",
    },
    "raw_summary": "Corroborated escalation headline raises short-term risk-off and reversal risk for BTC/ETH longs.",
}


def _with(path: str, value):
    data = json.loads(json.dumps(DESIGN_EXAMPLE))
    target = data
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    if value is KeyError:
        del target[keys[-1]]
    else:
        target[keys[-1]] = value
    return data


def _design_enum_block() -> dict:
    """Parse the 'Allowed enum values' block of PHASE6B_DESIGN section 4."""
    text = (ROOT / "docs" / "PHASE6B_DESIGN.md").read_text(encoding="utf-8")
    block = text.split("Allowed enum values:", 1)[1].split("```text", 1)[1].split("```", 1)[0]
    enums, current = {}, None
    for line in block.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            current = line.strip().rstrip(":")
            enums[current] = []
        else:
            enums[current].append(line.strip())
    return enums


# -- the event model ------------------------------------------------------------


def test_enums_are_exactly_the_design_lists():
    enums = _design_enum_block()
    assert [c.value for c in Category] == enums["category"]
    assert [s.value for s in CorroborationStatus] == enums["corroboration_status"]
    assert [t.value for t in SourceTier] == enums["source_quality.tier"]
    assert [d.value for d in Direction] == enums["asset_impact.direction"]
    assert [r.value for r in ExpectedReaction] == enums["asset_impact.expected_market_reaction"]
    assert [a.value for a in Action] == enums["action"]
    assert tuple(c.value for c in Category) == CATEGORIES  # the ingestion registry agrees
    assert [c.value for c in ClassifiedCategory] == enums["category"] + ["NONE"]


def test_design_example_validates_and_round_trips():
    event_ = NewsEvent.model_validate(DESIGN_EXAMPLE)
    assert event_.first_seen_at == datetime(2026, 6, 17, 14, 5, 12, tzinfo=timezone.utc)
    again = NewsEvent.model_validate_json(event_.model_dump_json())
    assert again == event_
    dumped = json.loads(event_.model_dump_json())
    assert dumped["first_seen_at"] == "2026-06-17T14:05:12Z" and dumped["action"] == "BLOCK_NEW_LONGS"
    with pytest.raises(ValidationError):  # frozen
        event_.action = Action.NO_EFFECT


@pytest.mark.parametrize("field", list(DESIGN_EXAMPLE))
def test_every_required_field_is_required(field):
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with(field, KeyError))


@pytest.mark.parametrize(
    "path",
    ["unexpected", "source_quality.unexpected", "asset_impact.unexpected", "decay_function.unexpected"],
)
def test_unknown_fields_are_rejected(path):
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with(path, "x"))


@pytest.mark.parametrize("bad", ["ENTER", "BUY", "LONG", "BOOST", "INCREASE_CONFIDENCE", "INCREASE_SIZE", "SELL", "", None])
def test_prohibited_actions_are_rejected(bad):
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with("action", bad))
    with pytest.raises(ValidationError):
        verdict(proposed_action=bad)


@pytest.mark.parametrize("status", ["SINGLE_SOURCE", "CONFLICTED", "REJECTED", "EXPIRED"])
def test_no_effect_statuses_force_no_effect(status):
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with("corroboration_status", status))
    ok = _with("corroboration_status", status)
    ok["action"] = "NO_EFFECT"
    assert NewsEvent.model_validate(ok).action is Action.NO_EFFECT


@pytest.mark.parametrize(
    "path,value",
    [
        ("confidence", 1.01),
        ("confidence", -0.01),
        ("confidence", math.nan),
        ("confidence", math.inf),
        ("asset_impact.impact_strength", 2),
        ("asset_impact.volatility_risk", -1),
        ("asset_impact.time_horizon_minutes", 0),
        ("source_quality.independent_source_count", -1),
        ("source_quality.tier", "PREMIUM"),
        ("category", "MEME_COIN_PUMP"),
        ("asset_impact.assets", ["BTC", "DOGE"]),
        ("asset_impact.instruments", ["BTC-USDT"]),  # must match the assets
        ("asset_impact.direction", "UP"),
        ("decay_function.type", "STEP"),
        ("event_id", "evt_bad"),
        ("event_id", "../../etc/passwd"),
    ],
)
def test_out_of_range_and_unknown_values_are_rejected(path, value):
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with(path, value))


def test_timestamps_must_be_aware_and_ordered():
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with("first_seen_at", "2026-06-17T14:05:12"))  # naive
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with("expires_at", "2026-06-17T14:05:12Z"))  # == first_seen_at
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with("decay_function.zero_at", "2026-06-17T19:05:12Z"))  # beyond expiry
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with("decay_function.starts_at", "2026-06-17T14:00:00Z"))  # before first seen
    offset = NewsEvent.model_validate(_with("first_seen_at", "2026-06-17T17:05:12+03:00"))
    assert offset.first_seen_at == datetime(2026, 6, 17, 14, 5, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "summary",
    ["", " padded ", "line one\nline two", "zero​width", "bidi‮text", "x" * 281, "ﬁ ligature not NFKC"],
)
def test_raw_summary_must_be_short_clean_single_line(summary):
    with pytest.raises(ValidationError):
        NewsEvent.model_validate(_with("raw_summary", summary))


def test_exponential_decay_needs_half_life():
    with pytest.raises(ValidationError):
        DecayFunction(type="EXPONENTIAL_TO_ZERO", starts_at=NOW, half_life_minutes=None, zero_at=NOW + timedelta(hours=1))
    with pytest.raises(ValidationError):
        DecayFunction(type="LINEAR_TO_ZERO", starts_at=NOW, half_life_minutes=0, zero_at=NOW + timedelta(hours=1))
    assert DecayFunction(type="LINEAR_TO_ZERO", starts_at=NOW, half_life_minutes=None, zero_at=NOW + timedelta(hours=1))


def test_action_at_is_zero_from_expiry():
    e = event(ttl_minutes=60)
    assert e.action_at(NOW + timedelta(minutes=59)) is Action.BLOCK_NEW_LONGS
    assert e.action_at(NOW + timedelta(minutes=60)) is Action.NO_EFFECT
    assert e.is_expired(NOW + timedelta(hours=5))
    with pytest.raises(ValueError):
        e.action_at(datetime(2026, 10, 20, 12, 30))  # naive


def test_action_ordering_helpers():
    assert most_conservative([Action.NO_EFFECT, Action.REDUCE_SIZE, Action.BLOCK_NEW_LONGS]) is Action.BLOCK_NEW_LONGS
    assert most_conservative([]) is Action.NO_EFFECT
    assert less_aggressive(Action.BLOCK_NEW_LONGS, Action.REDUCE_SIZE) is Action.REDUCE_SIZE
    assert ACTION_RANK[Action.NO_EFFECT] < ACTION_RANK[Action.REDUCE_SIZE] < ACTION_RANK[Action.BLOCK_NEW_LONGS]


def test_asset_impact_requires_matching_instruments():
    ok = AssetImpact(
        assets=("ETH",), instruments=("ETH-USDT",), direction="RISK_OFF", expected_market_reaction="VOLATILITY_ONLY",
        impact_strength=0.5, volatility_risk=0.5, time_horizon_minutes=60,
    )
    assert ok.instruments == ("ETH-USDT",)
    with pytest.raises(ValidationError):
        AssetImpact(
            assets=("ETH", "ETH"), instruments=("ETH-USDT",), direction="RISK_OFF", expected_market_reaction="VOLATILITY_ONLY",
            impact_strength=0.5, volatility_risk=0.5, time_horizon_minutes=60,
        )


# -- the LLM output models ---------------------------------------------------------


def test_classifier_verdict_is_strict():
    v = verdict()
    assert v.proposed_action is Action.BLOCK_NEW_LONGS and v.category is ClassifiedCategory.EXCHANGE_HACK_EXPLOIT
    with pytest.raises(ValidationError):
        ClassifierVerdict.model_validate({**v.model_dump(mode="json"), "order": "buy"})  # extra field
    with pytest.raises(ValidationError):
        verdict(confidence=1.5)
    with pytest.raises(ValidationError):
        verdict(assets=["BTC", "ETH", "SOL"])
    with pytest.raises(ValidationError):
        verdict(manipulation_signs=["TOTALLY_LEGIT"])
    with pytest.raises(ValidationError):
        verdict(claim_summary="x" * 401)
    with pytest.raises(ValidationError):
        verdict(time_horizon_minutes=0)
    data = v.model_dump(mode="json")
    del data["same_story_as"]  # required, even though it may be null
    with pytest.raises(ValidationError):
        ClassifierVerdict.model_validate(data)


def test_triage_verdict():
    t = TriageVerdict.model_validate({"relevant": True, "category": "FED_FOMC_RATES", "reason": "FOMC statement."})
    assert t.relevant and t.category is ClassifiedCategory.FED_FOMC_RATES
    with pytest.raises(ValidationError):
        TriageVerdict.model_validate({"relevant": True, "category": "FED_FOMC_RATES", "reason": "x", "action": "BUY"})


# -- source items -------------------------------------------------------------------


def test_source_item_from_ingestion_record():
    record = {
        "source_id": "sec_press",
        "publisher": "U.S. Securities and Exchange Commission",
        "publisher_owner": "U.S. Government",
        "canonical_url": "https://www.sec.gov/news/press-release/2026-1",
        "source_tier": "OFFICIAL",
        "observed_at": "2026-10-20T12:00:00+00:00",
        "published_at": "2026-10-20T11:30:00+00:00",
        "title": "SEC Charges Firm",
        "excerpt": "Washington D.C.",
        "sanitization_flags": [],
        "quarantined": False,
        "category_hints": ["ETF_SEC_DECISION"],
        "content_key": "ab" * 32,
    }
    ref = SourceItemRef.from_record(record)
    assert ref.item_id == "itm_" + ("ab" * 10) and ref.tier is SourceTier.OFFICIAL
    assert ref.published_at == datetime(2026, 10, 20, 11, 30, tzinfo=timezone.utc) and not ref.quarantined
    assert SourceItemRef.from_record({**record, "source_tier": "WEIRD"}).tier is SourceTier.UNKNOWN
    flagged = SourceItemRef.from_record({**record, "sanitization_flags": ["prompt_injection_suspect"]})
    assert flagged.quarantined  # severe flags always quarantine
    no_key = SourceItemRef.from_record({k: v for k, v in record.items() if k != "content_key"})
    assert no_key.item_id == "itm_" + dedup.content_key(record["canonical_url"], "", "")[:20]
    with pytest.raises(ValueError):
        SourceItemRef.from_record({**record, "observed_at": "2026-10-20T12:00:00"})  # naive
    with pytest.raises(ValueError):
        SourceItemRef.from_record({k: v for k, v in record.items() if k != "observed_at"})


# -- event ids ------------------------------------------------------------------------


def test_event_id_is_deterministic_and_story_level():
    story = dedup.story_key("Exchange halts withdrawals", NOW, NOW)
    a = dedup.event_id("EXCHANGE_HACK_EXPLOIT", story, NOW, ["BTC", "ETH"])
    assert re.fullmatch(r"evt_20261020_hack_btc_eth_[0-9a-f]{12}", a)
    # Same story seen through many articles: one id (asset order and later time in the bucket don't matter).
    assert a == dedup.event_id("EXCHANGE_HACK_EXPLOIT", story, NOW + timedelta(minutes=50), ["ETH", "BTC", "BTC"])
    # A genuinely new development is a different story key -> a new id.
    new_story = dedup.story_key("Exchange resumes withdrawals after audit", NOW, NOW)
    assert dedup.event_id("EXCHANGE_HACK_EXPLOIT", new_story, NOW, ["BTC", "ETH"]) != a
    assert dedup.event_id("EXCHANGE_HACK_EXPLOIT", story, NOW, ["BTC"]) != a
    assert dedup.event_id("MAJOR_REGULATORY_ACTION", story, NOW, ["BTC", "ETH"]) != a
    assert dedup.event_id("EXCHANGE_HACK_EXPLOIT", story, NOW + timedelta(hours=7), ["BTC", "ETH"]) != a
    assert dedup.event_id("FED_FOMC_RATES", story, NOW, []).startswith("evt_20261020_fed_none_")
    ev = event(event_id=a)  # ids satisfy the schema pattern
    assert ev.event_id == a
    with pytest.raises(ValueError):
        dedup.event_id("NOT_A_CATEGORY", story, NOW, ["BTC"])
    with pytest.raises(ValueError):
        dedup.event_id("FED_FOMC_RATES", story, datetime(2026, 10, 20, 12), ["BTC"])  # naive
    with pytest.raises(ValueError):
        dedup.event_id("FED_FOMC_RATES", story, NOW, ["BTC"], bucket_hours=5)
