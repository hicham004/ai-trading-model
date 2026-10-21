"""Deterministic corroboration: independent sources and price/volume (design 2, 7.5, 10)."""

from __future__ import annotations

import itertools
import random
from datetime import timedelta

import pytest

from app.news import corroborate as corroborate_module
from app.news.corroborate import (
    SOCIAL_FAMILY,
    PublicCandle,
    assess,
    assign_families,
    confirm_price_volume,
    market_context,
    family_links,
    linked_credits,
    quotes_social_post,
    source_family,
    wire_attribution,
)
from app.news.sanitize import sanitize_text
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


def test_wire_credits_match_in_any_capitalisation_and_dash():
    for text in ("Velmont freezes withdrawals, the Associated Press reports", "THE ASSOCIATED PRESS said",
                 "according to the associated  press", "Associated-Press"):
        assert linked_credits(text) == {"ap"}, text
    for text in ("Agence France-Presse reported", "AGENCE FRANCE-PRESSE", "agence France Presse said",
                 "Agence France\u2011Presse said", "AGENCE FRANCE\u2013PRESSE", "Agence France\u2212Presse",
                 "Agence France\u00adPresse"):  # a soft hyphen is deleted: "FrancePresse"
        # Through the real sanitizer, which turns a non-breaking hyphen into U+2010.
        assert linked_credits(sanitize_text(text, max_chars=200).text) == {"afp"}, text
    # The short forms only as the wires print them (the original rules).
    assert wire_attribution("PARIS (AFP) -") == "afp" and wire_attribution("WASHINGTON (AP) -") == "ap"
    assert not linked_credits("the app shows a map") and wire_attribution("the app shows a map") is None


def test_relays_crediting_the_associated_press_are_one_source():
    """Eval story syn-ap-attribution-capitalized: one AP report and two relays crediting it."""
    items = [
        item(1, url="https://apnews.com/article/velmont", tier=SourceTier.HIGH,
             title="Hackers hit crypto exchange Velmont, freezing customer withdrawals"),
        item(2, url="https://blockfeedtoday.com/velmont", title="Exchange Velmont freezes withdrawals after hack, the Associated Press reports"),
        item(3, url="https://dailycoinbrief.com/velmont", title="Velmont hack: withdrawals frozen, according to the Associated Press"),
    ]
    result = assess(items)
    assert result.status is S.SINGLE_SOURCE and result.independent_source_count == 1 and result.tier is SourceTier.HIGH
    assert set(result.families) == {"wire:ap"}
    afp = [item(4, url="https://www.afp.com/en/news/port", title="Explosions reported near port"),
           item(5, title="Blasts heard near the port, AGENCE FRANCE-PRESSE says")]
    assert assess(afp).status is S.SINGLE_SOURCE


def test_dow_jones_brands_never_count_as_two_sources():
    sites = [
        item(1, url="https://www.wsj.com/finance/x", tier=SourceTier.HIGH, title="Exchange halts withdrawals after breach"),
        item(2, url="https://www.marketwatch.com/story/y", title="Crypto exchange hacked, withdrawals frozen"),
        item(3, url="https://www.barrons.com/articles/z", title="What the exchange hack means for bitcoin"),
        item(4, url="https://newswires.dowjones.com/w", tier=SourceTier.HIGH, title="Exchange confirms wallet breach"),
    ]
    result = assess(sites)
    assert result.status is S.SINGLE_SOURCE and result.independent_source_count == 1 and result.tier is SourceTier.HIGH
    assert set(result.families) == {"wire:dowjones"}
    for n, credit in enumerate(("the Wall Street Journal reported", "per WSJ", "Barron's reports", "Barron\u2019s says",
                                "MarketWatch reports", "Dow Jones Newswires said"), start=10):
        relay = item(n, title=f"Exchange halts withdrawals, {credit}")
        assert family_links(relay) == {"wire:dowjones"}, credit
        assert assess([sites[1], relay]).status is S.SINGLE_SOURCE, credit
    # "Dow Jones" alone is the stock index, not a credit; another owner's outlet is independent.
    index = item(30, title="Dow Jones Industrial Average falls 500 points after exchange halts withdrawals")
    assert source_family(index) == "domain:news30.example" and not family_links(index)
    assert assess([sites[0], item(31, title="Exchange confirms the breach")]).status is S.INDEPENDENT_SOURCE_CONFIRMED


def test_look_alike_sites_are_not_the_outlet():
    assert source_family(item(1, url="https://uk.reuters.com/x")) == "wire:reuters"
    assert family_links(item(2, url="https://www.wsj.com/x")) == {"wire:dowjones"}
    for n, url in enumerate(("https://reuters.com.evil.example/x", "https://evilreuters.com/x", "https://reut\u0435rs.com/x",
                             "https://wsj.com.evil.example/x"), start=3):
        look_alike = item(n, url=url)
        assert not source_family(look_alike).startswith("wire:") and not family_links(look_alike), url


def _original_count(items, supporting=None, owner_overrides=None):
    """Independent families under the rules before R4d (``assign_families`` is unchanged)."""
    usable = [i for i in items if not i.quarantined]
    families = assign_families(usable, owner_overrides)
    counted = [i for i in usable if i.tier in (SourceTier.OFFICIAL, SourceTier.HIGH, SourceTier.MEDIUM)
               and (supporting is None or i.item_id in supporting)]
    return len({families[i.item_id] for i in counted})


def test_new_recognitions_never_add_a_source_and_never_merge_two_publishers():
    """Each pair was one source under the original rules and stays one (first review of R4d)..."""
    pairs = {
        "an AP copy on MarketWatch": [
            item(1, url="https://apnews.com/article/x", tier=SourceTier.HIGH, title="Exchange halts withdrawals"),
            item(2, url="https://www.marketwatch.com/story/y", excerpt="NEW YORK (AP) - An exchange halted withdrawals.",
                 title="Crypto exchange halts withdrawals after breach"),
        ],
        "a WSJ page crediting Reuters": [
            item(3, url="https://www.reuters.com/x", tier=SourceTier.HIGH, title="Exchange halts withdrawals"),
            item(4, url="https://www.wsj.com/y", tier=SourceTier.HIGH, title="Exchange halts withdrawals after breach, Reuters reports"),
        ],
        "MarketWatch and a blog relaying one X post": [
            item(5, url="https://www.marketwatch.com/x", title="CEO says withdrawals paused",
                 excerpt="The CEO said in a post on X that withdrawals are paused."),
            item(6, url="https://blog.example/y", title="Withdrawals paused, CEO says", excerpt="He said in a post on X that withdrawals are paused."),
        ],
        "an AFP story and a relay crediting both wires": [
            item(7, url="https://www.afp.com/x", title="Blasts near port"),
            item(8, url="https://relay.example/y", title="Explosions near port, the Associated Press and AFP report"),
        ],
    }
    for name, items in pairs.items():
        assert assess(items).independent_source_count == _original_count(items) == 1, name
    news_corp = [item(9, url="https://www.wsj.com/x", title="Exchange hacked"), item(10, url="https://nypost.com/y", title="Hackers drain exchange")]
    assert assess(news_corp, owner_overrides={"wsj.com": "News Corp", "nypost.com": "News Corp"}).independent_source_count == 1
    # ...and two wires that each published the story stay two, whoever names both (second review).
    originals = [item(11, url="https://www.reuters.com/a", tier=SourceTier.HIGH, title="Port attacked"),
                 item(12, url="https://apnews.com/article/b", tier=SourceTier.HIGH, title="Missiles strike port")]
    for relay in ("Reuters and the Associated Press reported", "Reuters and Agence France-Presse reported",
                  "Reuters and AP News reported", "per Reuters and the WSJ"):
        story = originals + [item(13, url="https://relay.example/c", title=f"Port hit, {relay}")]
        assert assess(story).independent_source_count == 2, relay
        assert assess(story, supporting_ids=[i.item_id for i in originals]).independent_source_count == 2, relay


def test_the_count_is_never_above_the_original_rules():
    """A seeded random search over sites, credits, copies, owners, tiers and classifier narrowing."""
    rng = random.Random(20261021)
    sites = ["https://www.reuters.com", "https://apnews.com", "https://www.afp.com", "https://www.bloomberg.com",
             "https://www.wsj.com", "https://www.marketwatch.com", "https://www.barrons.com", "https://www.dowjones.com",
             "https://www.ft.com", "https://www.coindesk.com", "https://blog.example", "https://www.sec.gov"]
    credits = ["", "(AP)", "the Associated Press reported", "AGENCE FRANCE-PRESSE said", "Reuters reported", "the WSJ said",
               "Barron's reports", "MarketWatch says", "according to Bloomberg", "said in a post on X", "AFP"]
    titles = ["Exchange halts withdrawals", "Hackers drain exchange", "Exchange confirms breach"]
    tiers = [SourceTier.HIGH, SourceTier.MEDIUM, SourceTier.MEDIUM, SourceTier.LOW, SourceTier.OFFICIAL]
    for case in range(400):
        items = []
        for n in range(rng.randint(1, 7)):
            tier = rng.choice(tiers)
            items.append(item(case * 10 + n, url=f"{rng.choice(sites)}/{case}/{n}", tier=tier,
                              owner=rng.choice(["", "", "News Corp", "U.S. Government"]),
                              title=rng.choice(titles) + rng.choice(["", f" {n}"]),
                              excerpt=" ".join(rng.sample(credits, rng.randint(0, 2))),
                              quarantined=rng.random() < 0.1))
        supporting = None if rng.random() < 0.5 else {i.item_id for i in items if rng.random() < 0.7}
        overrides = rng.choice([None, {"wsj.com": "News Corp", "nypost.com": "News Corp"}, {"coindesk.com": "Digital Group"}])
        new = assess(items, supporting_ids=supporting, owner_overrides=overrides).independent_source_count
        assert new <= _original_count(items, supporting, overrides), case


def test_the_fewest_families_are_a_true_minimum(monkeypatch):
    """The cover step alone, on arbitrary families and links, against brute force."""
    rng = random.Random(7)
    for case in range(300):
        items = [item(case * 10 + k) for k in range(rng.randint(1, 6))]
        own = {i.item_id: rng.choice(["domain:a", "domain:b", "domain:c", "wire:ap", "social:post"]) for i in items}
        links = {i.item_id: frozenset(rng.sample(["wire:ap", "wire:afp", "wire:dowjones"], rng.randint(0, 2))) for i in items}
        monkeypatch.setattr(corroborate_module, "family_links", lambda it: links[it.item_id])
        official = {"domain:c"} if rng.random() < 0.3 else set()
        chosen = corroborate_module._fewest_families(list(reversed(items)), own, official)
        assert chosen == corroborate_module._fewest_families(items, own, official), case  # order does not matter
        options = [{own[i.item_id]} | (set() if own[i.item_id] in official else set(links[i.item_id])) for i in items]
        assert all(chosen[i.item_id] in opts for i, opts in zip(items, options)), case
        assert len(set(chosen.values())) == min(len(set(pick)) for pick in itertools.product(*options)), case
        for i, opts in zip(items, options):
            if opts == {own[i.item_id]}:  # an article without links keeps its family
                assert chosen[i.item_id] == own[i.item_id], case


def test_a_link_never_joins_an_official_source():
    official = item(1, publisher="SEC", owner="U.S. Government", url="https://www.sec.gov/news/press-release/1",
                    tier=SourceTier.OFFICIAL, title="SEC Charges Altora Global With Misusing Customer Assets")
    # A verbatim copy of the official headline that also credits a wire stays with the official source...
    copy = item(2, title="SEC charges Altora Global with misusing customer assets",
                excerpt="The action was first reported by the Associated Press.")
    reporting = item(3, url="https://apnews.com/article/altora", tier=SourceTier.HIGH, title="US regulator sues crypto exchange Altora")
    result = assess([official, copy, reporting])
    # ...so the official source plus independent AP reporting are still two sources,
    assert result.status is S.INDEPENDENT_SOURCE_CONFIRMED and result.independent_source_count == 2 and result.has_official
    # also when the classifier leaves the official item itself out.
    narrowed = assess([official, copy, reporting], supporting_ids=[copy.item_id, reporting.item_id])
    assert narrowed.independent_source_count == 2


def test_a_wires_own_article_stands_only_for_that_wire():
    reuters = item(1, url="https://www.reuters.com/a", tier=SourceTier.HIGH, title="Exchange founder charged",
                   excerpt="Prosecutors told The Wall Street Journal the probe is widening.")
    wsj = item(2, url="https://www.wsj.com/b", tier=SourceTier.HIGH, title="Founder of crypto exchange indicted")
    ap = item(3, url="https://apnews.com/article/c", tier=SourceTier.HIGH, title="Blasts hit port city",
              excerpt="Agence France-Presse journalists at the scene saw smoke.")
    afp = item(4, url="https://www.afp.com/d", title="Explosions in port city")
    assert not family_links(reuters) and not family_links(ap)
    assert assess([reuters, wsj]).independent_source_count == 2
    assert assess([ap, afp]).independent_source_count == 2


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
