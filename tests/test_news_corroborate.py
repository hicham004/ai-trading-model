"""Deterministic corroboration: independent sources and price/volume (design 2, 7.5, 10)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.news.corroborate import (
    SOCIAL_FAMILY,
    PublicCandle,
    assess,
    assign_families,
    confirm_price_volume,
    market_context,
    quotes_social_post,
    source_family,
    wire_attribution,
)
from app.news.schema import CorroborationStatus, ExpectedReaction, SourceTier
from tests.news_fixtures import NOW, candles, item

S = CorroborationStatus


# -- independence ------------------------------------------------------------------


def test_single_source_is_single_source():
    result = assess([item(1)])
    assert result.status is S.SINGLE_SOURCE and result.independent_source_count == 1
    assert result.source_quality().independent_source_count == 1


def test_two_independent_publishers_confirm():
    result = assess([item(1, publisher="Alpha News"), item(2, publisher="Beta Daily", title="Exchange freezes withdrawals")])
    assert result.status is S.INDEPENDENT_SOURCE_CONFIRMED and result.independent_source_count == 2
    assert result.tier is SourceTier.MEDIUM and not result.has_official
    assert set(result.source_ids) == {"itm_00000000000000000001", "itm_00000000000000000002"}


def test_syndicated_wire_copies_count_once():
    items = [
        item(1, url="https://www.reuters.com/markets/x", title="Exchange halts withdrawals", tier=SourceTier.HIGH),
        item(2, title="Crypto exchange pauses withdrawals, Reuters reports"),
        item(3, excerpt="LONDON (Reuters) - A large exchange said on Monday it paused withdrawals."),
        item(4, excerpt="According to Reuters, withdrawals are paused."),
    ]
    families = assign_families(items)
    assert set(families.values()) == {"wire:reuters"}
    result = assess(items)
    assert result.status is S.SINGLE_SOURCE and result.independent_source_count == 1
    assert result.tier is SourceTier.HIGH  # the wire's own tier


def test_wire_attribution_patterns():
    assert wire_attribution("WASHINGTON (AP) — Officials said") == "ap"
    assert wire_attribution("as first reported by Bloomberg") == "bloomberg"
    assert wire_attribution("agence france-presse reported") == "afp"
    assert wire_attribution("Apple shares rose") is None and wire_attribution("") is None


def test_articles_quoting_one_social_post_are_one_source():
    items = [
        item(1, publisher="Alpha", title="CEO says withdrawals paused", excerpt="The CEO said in a post on X that withdrawals are paused."),
        item(2, publisher="Beta", title="Withdrawals reportedly paused", excerpt="A screenshot circulating online shows the notice."),
        item(3, publisher="Gamma", title="Exchange boss tweets about pause", excerpt="He tweeted the update."),
    ]
    assert {source_family(i) for i in items} == {SOCIAL_FAMILY}
    assert assess(items).status is S.SINGLE_SOURCE
    assert quotes_social_post("an X post by the founder") and not quotes_social_post("the exchange's status page")


def test_same_owner_counts_once_and_overrides_apply():
    items = [
        item(1, publisher="Alpha News", owner="MediaCorp", title="Exchange hacked"),
        item(2, publisher="Alpha Business", owner="MediaCorp", title="Hackers drain exchange wallet"),
    ]
    assert assess(items).independent_source_count == 1
    unknown_owner = [item(1, url="https://a.example/x", title="Exchange hacked"), item(2, url="https://b.example/y", title="Wallet drained")]
    assert assess(unknown_owner).independent_source_count == 2
    overrides = {"a.example": "Same Group", "b.example": "Same Group"}
    assert assess(unknown_owner, owner_overrides=overrides).independent_source_count == 1


def test_identical_headlines_are_copies_of_the_earliest():
    items = [
        item(1, publisher="Alpha", title="Exchange halts withdrawals!", observed=NOW),
        item(2, publisher="Beta", title="exchange HALTS withdrawals", observed=NOW + timedelta(minutes=5)),
    ]
    families = assign_families(items)
    assert families[items[0].item_id] == families[items[1].item_id]
    assert assess(items).status is S.SINGLE_SOURCE


def test_a_verbatim_repost_of_an_official_headline_is_not_independent():
    for repost_first in (False, True):
        official_time = NOW + (timedelta(minutes=5) if repost_first else timedelta(0))
        official = item(1, publisher="SEC", owner="U.S. Government", url="https://www.sec.gov/news/press-release/1",
                        tier=SourceTier.OFFICIAL, title="SEC Approves Spot Ether ETF Options", observed=official_time)
        repost = item(2, publisher="Aggregator", title="SEC approves spot ether ETF options!",
                      observed=NOW + (timedelta(0) if repost_first else timedelta(minutes=5)))
        families = assign_families([official, repost])
        assert families[official.item_id] == families[repost.item_id] == "owner:u.s. government"
        assert assess([official, repost]).status is S.SINGLE_SOURCE
    reporting = item(3, publisher="Beta Daily", title="Options on ether ETFs cleared by regulator")
    assert assess([official, repost, reporting]).status is S.INDEPENDENT_SOURCE_CONFIRMED


def test_low_unknown_and_quarantined_sources_never_count():
    low = [item(1, tier=SourceTier.LOW, title="Exchange hacked"), item(2, tier=SourceTier.UNKNOWN, title="Wallet drained")]
    result = assess(low)
    assert result.status is S.SINGLE_SOURCE and result.independent_source_count == 0 and result.tier is SourceTier.LOW
    mixed = [item(1, title="Exchange hacked"), item(2, title="Wallet drained", quarantined=True)]
    result = assess(mixed)
    assert result.independent_source_count == 1 and "1 quarantined" in result.notes


def test_official_source_plus_independent_reporting():
    items = [
        item(1, publisher="Coinbase Status", owner="Coinbase", url="https://status.coinbase.com/incidents/1", tier=SourceTier.OFFICIAL,
             title="Degraded performance: withdrawals delayed"),
        item(2, publisher="Beta Daily", title="Coinbase users report delayed withdrawals"),
    ]
    result = assess(items)
    assert result.status is S.INDEPENDENT_SOURCE_CONFIRMED and result.has_official and result.tier is SourceTier.OFFICIAL
    assert result.primary_sources == ("Coinbase Status",) and result.secondary_sources == ("Beta Daily",)


def test_llm_can_only_narrow_never_widen():
    a, b = item(1, title="Exchange hacked"), item(2, title="Wallet drained")
    # The model lists only one source as independent: deterministic count drops to 1.
    assert assess([a, b], supporting_ids=[a.item_id]).status is S.SINGLE_SOURCE
    # The model claims independence for ids that deterministic rules reject: ignored.
    copies = [item(3, title="Same headline"), item(4, title="Same headline")]
    result = assess(copies, supporting_ids=[c.item_id for c in copies] + ["itm_invented"],
                    llm_assessment=S.INDEPENDENT_SOURCE_CONFIRMED)
    assert result.status is S.SINGLE_SOURCE
    # Its CONFLICTED / REJECTED / EXPIRED verdicts are respected even over two independent sources.
    for terminal in (S.CONFLICTED, S.REJECTED, S.EXPIRED):
        assert assess([a, b], llm_assessment=terminal).status is terminal


# -- price / volume ------------------------------------------------------------------


EVENT = NOW
START = NOW - timedelta(minutes=15 * 30)  # 30 pre-event candles of 15 minutes


def _series(reaction_closes, reaction_volume=300.0, base_close=60000.0):
    closes = [base_close] * 30 + list(reaction_closes)
    volumes = [100.0] * 30 + [reaction_volume] * len(reaction_closes)
    return candles(closes, start=START, volumes=volumes)


def test_price_volume_confirms_a_down_move_on_high_volume():
    series = _series([59900.0, 59800.0])  # ATR ~ 20 (spread 10 each side); move -200
    check = confirm_price_volume(series, instrument="BTC-USDT", event_time=EVENT, decision_time=NOW + timedelta(minutes=30),
                                 reaction=ExpectedReaction.DOWN_OR_VOLATILE)
    assert check.confirmed and check.reason == "confirmed" and check.move == pytest.approx(-200.0)
    assert check.baseline_candles == 30 and check.reaction_candles == 2 and check.volume_ratio == pytest.approx(3.0)


def test_price_volume_uses_only_candles_closed_before_the_decision():
    series = _series([60000.0, 59000.0])  # the confirming drop is in the SECOND reaction candle
    early = confirm_price_volume(series, instrument="BTC-USDT", event_time=EVENT, decision_time=NOW + timedelta(minutes=15),
                                 reaction=ExpectedReaction.DOWN_OR_VOLATILE)
    assert not early.confirmed and early.ignored_unclosed_candles == 1 and early.reaction_candles == 1
    # One second before that candle closes it is still unknown, whatever the caller passed in.
    almost = confirm_price_volume(series, instrument="BTC-USDT", event_time=EVENT,
                                  decision_time=NOW + timedelta(minutes=30) - timedelta(seconds=1),
                                  reaction=ExpectedReaction.DOWN_OR_VOLATILE)
    assert not almost.confirmed
    later = confirm_price_volume(series, instrument="BTC-USDT", event_time=EVENT, decision_time=NOW + timedelta(minutes=30),
                                 reaction=ExpectedReaction.DOWN_OR_VOLATILE)
    assert later.confirmed


def test_price_volume_direction_thresholds_and_data_rules():
    down = _series([59800.0])
    up = _series([60200.0])
    at = NOW + timedelta(minutes=15)
    kw = dict(instrument="BTC-USDT", event_time=EVENT, decision_time=at)
    assert not confirm_price_volume(down, reaction=ExpectedReaction.UP_BUT_REVERSAL_RISK, **kw).confirmed
    assert confirm_price_volume(up, reaction=ExpectedReaction.UP_BUT_REVERSAL_RISK, **kw).confirmed
    assert confirm_price_volume(up, reaction=ExpectedReaction.VOLATILITY_ONLY, **kw).confirmed
    assert confirm_price_volume(down, reaction=ExpectedReaction.VOLATILITY_ONLY, **kw).confirmed
    assert confirm_price_volume(down, reaction=ExpectedReaction.NO_CLEAR_REACTION, **kw).reason == "no_clear_reaction_expected"
    assert confirm_price_volume(down, reaction=ExpectedReaction.DOWN_OR_VOLATILE, **kw).confirmed
    small = _series([59995.0])  # below 0.5 x ATR
    assert confirm_price_volume(small, reaction=ExpectedReaction.DOWN_OR_VOLATILE, **kw).reason == "move_below_threshold"
    quiet = _series([59800.0], reaction_volume=120.0)  # 1.2x volume < 1.5x
    assert confirm_price_volume(quiet, reaction=ExpectedReaction.DOWN_OR_VOLATILE, **kw).reason == "volume_below_threshold"
    short = _series([59800.0])[15:]  # 15 pre-event candles: fewer than the 20 the volume average needs
    assert confirm_price_volume(short, reaction=ExpectedReaction.DOWN_OR_VOLATILE, **kw).reason == "insufficient_data"
    assert confirm_price_volume(down, reaction=ExpectedReaction.DOWN_OR_VOLATILE, instrument="BTC-USDT",
                                event_time=EVENT, decision_time=EVENT - timedelta(minutes=1)).reason == "decision_before_event"
    stale = confirm_price_volume(down, reaction=ExpectedReaction.DOWN_OR_VOLATILE, instrument="BTC-USDT", event_time=EVENT,
                                 decision_time=at, reaction_window=timedelta(minutes=0))
    assert stale.reason == "insufficient_data"  # moves outside the reaction window do not count


def test_conflicting_candles_never_confirm():
    series = _series([59800.0])
    clash = PublicCandle(series[-1].open_time, series[-1].interval, 1, 2, 0.5, 1.5, 999)
    check = confirm_price_volume(series + [clash], instrument="BTC-USDT", event_time=EVENT,
                                 decision_time=NOW + timedelta(minutes=15), reaction=ExpectedReaction.DOWN_OR_VOLATILE)
    assert not check.confirmed and check.reason == "conflicting_candles"


def test_price_volume_feeds_the_status():
    series = _series([59800.0])
    check = confirm_price_volume(series, instrument="BTC-USDT", event_time=EVENT, decision_time=NOW + timedelta(minutes=15),
                                 reaction=ExpectedReaction.DOWN_OR_VOLATILE)
    one = [item(1, tier=SourceTier.OFFICIAL, owner="Coinbase", title="Withdrawals delayed")]
    result = assess(one, price_volume=[check])
    assert result.status is S.PRICE_VOLUME_CONFIRMED and result.price_volume_confirmed
    assert "price/volume confirmed" in result.notes and result.to_dict()["price_volume"][0]["confirmed"]
    # A LOW-tier rumor plus a coincident move is still not corroborated.
    assert assess([item(2, tier=SourceTier.LOW)], price_volume=[check]).status is S.SINGLE_SOURCE


def test_candle_validation_and_market_context():
    with pytest.raises(ValueError):
        PublicCandle(NOW, timedelta(0), 1, 1, 1, 1, 1)
    with pytest.raises(ValueError):
        PublicCandle(NOW, timedelta(minutes=1), 1, float("nan"), 1, 1, 1)
    series = _series([59800.0])
    ctx = market_context(series, decision_time=NOW + timedelta(minutes=15))
    assert ctx["last_price"] == "59800" and ctx["atr_reference"] == "available_before_now_only"
    assert float(ctx["move_15m_pct"]) == pytest.approx(-200 / 60000 * 100, abs=1e-3)
    assert float(ctx["volume_vs_rolling"]) == pytest.approx(3.0)
    # Context at the event time cannot see the reaction candle.
    assert market_context(series, decision_time=NOW)["last_price"] == "60000"
    assert market_context(series[:1], decision_time=NOW) is None
