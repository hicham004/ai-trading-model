"""The shadow news overlay can only keep, shrink or block a NEW long entry (design 7.7, 12, 13)."""

from __future__ import annotations

import ast
import copy
import inspect
import random
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.news import overlay as overlay_module
from app.news.overlay import NewLongEntryCandidate, NewsOverlayDecision, evaluate_new_long_entry
from app.news.schema import Action, CorroborationStatus, SourceTier
from tests.news_fixtures import NOW, event

BLOCK = event(event_id="evt_20261020_hack_btc_eth_00000000000b")
REDUCE = event(event_id="evt_20261020_hack_btc_eth_00000000000c", confidence=0.7, impact=0.9)  # 0.567 -> x0.50
SINGLE = event(
    event_id="evt_20261020_hack_btc_eth_00000000000d", status=CorroborationStatus.SINGLE_SOURCE, action=Action.NO_EFFECT, count=1
)


def candidate(**kw) -> NewLongEntryCandidate:
    base = dict(instrument="BTC-USDT", decision_time=NOW + timedelta(minutes=1), baseline_allowed=True,
                baseline_size_fraction=Decimal("0.04"), signal_ref="candle:2026-10-20T12:00Z")
    base.update(kw)
    return NewLongEntryCandidate(**base)


def test_no_events_means_no_effect():
    d = evaluate_new_long_entry(candidate(), [])
    assert d.allowed and d.action is Action.NO_EFFECT and d.size_multiplier == 1 and d.reason == "news_no_effect"
    assert d.adjusted_size_fraction == Decimal("0.04") and not d.would_have_blocked_here and not d.would_have_reduced_here


def test_block_vetoes_an_allowed_entry():
    d = evaluate_new_long_entry(candidate(), [BLOCK])
    assert not d.allowed and d.action is Action.BLOCK_NEW_LONGS and d.reason == "news_block_new_longs"
    assert d.size_multiplier == 0 and d.adjusted_size_fraction == 0 and d.would_have_blocked_here
    assert d.event_id == BLOCK.event_id and d.active_event_ids == (BLOCK.event_id,)


def test_reduce_shrinks_an_allowed_entry():
    d = evaluate_new_long_entry(candidate(), [REDUCE])
    assert d.allowed and d.action is Action.REDUCE_SIZE and d.size_multiplier == Decimal("0.50")
    assert d.adjusted_size_fraction == Decimal("0.0200") and d.would_have_reduced_here


def test_a_baseline_block_stays_blocked_and_is_not_counted_as_prevented():
    for events in ([], [SINGLE], [REDUCE], [BLOCK]):
        d = evaluate_new_long_entry(candidate(baseline_allowed=False, baseline_reason="confidence_too_low"), events)
        assert not d.allowed and d.adjusted_size_fraction == 0
        assert not d.would_have_blocked_here and not d.would_have_reduced_here
        assert d.reason == "baseline_blocked" and d.baseline_reason == "confidence_too_low"


def test_single_source_expired_and_other_instrument_events_do_nothing():
    assert evaluate_new_long_entry(candidate(), [SINGLE]).action is Action.NO_EFFECT
    expired = evaluate_new_long_entry(candidate(decision_time=NOW + timedelta(hours=5)), [BLOCK])
    assert expired.allowed and expired.action is Action.NO_EFFECT
    eth = event(event_id="evt_20261020_hack_eth_00000000000e", assets=("ETH",))
    assert evaluate_new_long_entry(candidate(), [eth]).action is Action.NO_EFFECT
    assert evaluate_new_long_entry(candidate(instrument="ETH-USDT"), [eth]).action is Action.BLOCK_NEW_LONGS


def test_unhealthy_news_is_no_effect_never_a_block():
    d = evaluate_new_long_entry(candidate(), [BLOCK], news_healthy=False)
    assert d.allowed and d.action is Action.NO_EFFECT and d.reason == "news_unhealthy"


def test_malformed_events_are_no_effect():
    d = evaluate_new_long_entry(candidate(), [BLOCK, "not an event"])
    assert d.allowed and d.action is Action.NO_EFFECT and d.reason.startswith("news_error:")


def test_unknown_size_is_reported_as_unknown():
    d = evaluate_new_long_entry(candidate(baseline_size_fraction=None), [REDUCE])
    assert d.allowed and d.size_multiplier == Decimal("0.50") and d.adjusted_size_fraction is None


def test_never_allows_more_and_never_enlarges_randomized():
    rng = random.Random(11)
    for _ in range(400):
        events = [
            event(
                event_id=f"evt_20261020_hack_btc_eth_{i:012x}",
                confidence=rng.random(), impact=rng.random(), tier=rng.choice(list(SourceTier)),
                action=rng.choice(list(Action)), ttl_minutes=rng.choice([30, 120, 720]),
                assets=rng.choice([("BTC",), ("ETH",), ("BTC", "ETH")]),
            )
            for i in range(rng.randint(0, 4))
        ]
        c = candidate(
            baseline_allowed=rng.random() < 0.7,
            baseline_size_fraction=Decimal(rng.randint(0, 100)) / 100,
            decision_time=NOW + timedelta(minutes=rng.randint(-30, 900)),
        )
        frozen_events = copy.deepcopy(events)
        d = evaluate_new_long_entry(c, events, news_healthy=rng.random() < 0.9)
        assert events == frozen_events  # inputs untouched
        assert d.allowed <= c.baseline_allowed  # never allows what the baseline blocked
        assert Decimal(0) <= d.size_multiplier <= Decimal(1)
        assert d.adjusted_size_fraction <= c.baseline_size_fraction  # never enlarges
        assert d == evaluate_new_long_entry(c, events, news_healthy=d.reason != "news_unhealthy")  # deterministic


def test_candidate_validation():
    with pytest.raises(ValueError):
        candidate(decision_time=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        candidate(baseline_size_fraction=Decimal("1.5"))
    with pytest.raises(ValueError):
        candidate(baseline_size_fraction=Decimal("NaN"))
    with pytest.raises(ValueError):
        candidate(instrument=" ")
    with pytest.raises(ValueError):
        candidate(baseline_allowed="yes")
    assert candidate(baseline_size_fraction=0.25).baseline_size_fraction == Decimal("0.25")
    with pytest.raises(TypeError):
        evaluate_new_long_entry({"instrument": "BTC-USDT", "side": "sell"}, [BLOCK])


def test_decision_log_record_shape():
    record = evaluate_new_long_entry(candidate(), [REDUCE]).to_log_record()
    assert record["kind"] == "shadow_entry_overlay" and record["action"] == "REDUCE_SIZE"
    assert record["size_multiplier"] == "0.50" and record["adjusted_size_fraction"] == "0.0200"
    assert record["would_have_reduced_here"] and record["policy_version"] == "phase6b-decay-v1"
    for key in ("allowed", "reason", "event_id", "effective_severity"):  # design section 12 shape
        assert key in record


def test_the_overlay_has_no_exit_or_order_surface():
    """There is no way to express an exit, a stop, a cancel or an order in this module."""
    fields = set(NewLongEntryCandidate.__dataclass_fields__) | set(NewsOverlayDecision.__dataclass_fields__)
    forbidden = ("exit", "stop", "cancel", "kill", "disarm", "reconcil", "sell", "side", "order", "close")
    assert not [f for f in fields if any(word in f.lower() for word in forbidden)]
    public = [n for n, obj in vars(overlay_module).items() if not n.startswith("_") and callable(obj)
              and getattr(obj, "__module__", "") == overlay_module.__name__]
    assert sorted(public) == ["NewLongEntryCandidate", "NewsOverlayDecision", "evaluate_new_long_entry"]
    tree = ast.parse(Path(inspect.getfile(overlay_module)).read_text(encoding="utf-8"))
    imported = {
        (n.module or "") if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert all(m.startswith(("app.news", "__future__", "dataclasses", "datetime", "decimal", "typing")) for m in imported), imported
