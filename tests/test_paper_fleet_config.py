"""The fleet manifest: every shortlist row and control becomes one account; nothing is re-selected; rule changes are detected."""

from __future__ import annotations

import json

import pytest

from research.paper_fleet.config import DEFAULT_RESULTS, DEFAULT_SHORTLIST, NO_TRADE, load_manifest


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


def test_one_account_per_shortlist_row_control_and_the_portfolio(manifest):
    shortlist = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))
    ids = [a.account_id for a in manifest.accounts]
    assert len(ids) == len(shortlist["configurations"]) + len(shortlist["controls"]) + 1 == 19
    assert ids[0] == "c01-s1s5-btc-6h-none" and "pf-s1s2s4-btceth-vt15" in ids
    roles = {a.role for a in manifest.accounts}
    assert roles == {"candidate", "control", "portfolio"}
    for row, acc in zip(shortlist["configurations"], [a for a in manifest.accounts if a.role == "candidate"]):
        assert acc.shortlist_rank == row["rank"] and acc.sleeve.candidate == row["candidate"]
        assert acc.sleeve.instrument == row["instrument"] and acc.sleeve.timeframe == row["timeframe"]
        assert acc.sleeve.regime.mode == row["regime_config"]["mode"] and acc.sleeve.sizing.label == "vt10/30 crash15/90dh ladder"
        assert acc.sleeve.rebalance_threshold == 0.25 and acc.sleeve.ladder().recovery_bars == (120 if acc.timeframe == "6H" else 180)
        assert {k: (list(v) if isinstance(v, tuple) else v) for k, v in acc.sleeve.params.items()} == row["params"]
        assert acc.expectations["walk_forward"]["cagr"] == pytest.approx(row["cagr"])
    confirmed = manifest.account("c01-s1s5-btc-6h-none")
    assert confirmed.expectations["holdout_confirmed"] is True and confirmed.expectations["holdout"]["total_return"] == pytest.approx(0.022704)
    assert NO_TRADE.scheduled_events and NO_TRADE.label == "S0 vol×3 spread p98 gap3 FOMC±6/6h"


def test_controls_and_the_portfolio(manifest):
    holds = [a for a in manifest.accounts if a.account_id.startswith("ctl-hold")]
    bhs = [a for a in manifest.accounts if a.kind == "buy_and_hold"]
    assert len(holds) == 4 and len(bhs) == 4
    assert all(a.sleeve.candidate == "hold" and a.sleeve.sizing is not None for a in holds)
    assert all(a.expectations.get("benchmark") for a in bhs)
    pf = manifest.account("pf-s1s2s4-btceth-vt15").portfolio
    names = [n for n, _ in pf.sleeves]
    assert names == ["S1/BTC/6H", "S1/ETH/6H", "S2/BTC/4H", "S2/ETH/4H", "S4/BTC/6H", "S4/ETH/6H"]
    sleeves = dict(pf.sleeves)
    assert all(s.sizing is None and s.ladder() is None and s.rebalance_threshold is None for s in sleeves.values())  # full size
    assert sleeves["S4/BTC/6H"].bracket == "trail1" and sleeves["S4/ETH/6H"].bracket == "tp2"
    assert (pf.target_vol, pf.vol_lookback_days, pf.weight_lookback_days) == (0.15, 30, 60)
    assert (pf.ladder.half_dd, pf.ladder.flat_dd, pf.ladder.recovery_bars) == (0.075, 0.15, 30)
    exp = manifest.account("pf-s1s2s4-btceth-vt15").expectations["walk_forward"]
    assert exp["cagr"] == pytest.approx(0.109314) and exp["max_drawdown"] == pytest.approx(0.131776)
    assert manifest.series() == [("BTC-USDT", "4H"), ("BTC-USDT", "6H"), ("ETH-USDT", "4H"), ("ETH-USDT", "6H")]


def test_fingerprint_covers_the_rules_not_the_expectations(tmp_path, manifest):
    assert load_manifest().fingerprint() == manifest.fingerprint()
    shortlist = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))
    results = json.loads(DEFAULT_RESULTS.read_text(encoding="utf-8"))
    shortlist["generated_at"] = "re-rendered later"
    shortlist["configurations"][0]["holdout"]["total_return"] = 0.5  # an expectation, not a rule
    sl, rs = tmp_path / "sl.json", tmp_path / "rs.json"
    sl.write_text(json.dumps(shortlist), encoding="utf-8")
    rs.write_text(json.dumps(results), encoding="utf-8")
    assert load_manifest(sl, rs).fingerprint() == manifest.fingerprint()
    # A changed rule (sizing) changes the fingerprint.
    for row in shortlist["configurations"]:
        row["sizing_config"]["target_vol"] = 0.12
    sl.write_text(json.dumps(shortlist), encoding="utf-8")
    assert load_manifest(sl, rs).fingerprint() != manifest.fingerprint()


def test_a_shortlist_that_disagrees_with_the_results_is_refused(tmp_path):
    shortlist = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))
    results = json.loads(DEFAULT_RESULTS.read_text(encoding="utf-8"))
    rs = tmp_path / "rs.json"
    rs.write_text(json.dumps(results), encoding="utf-8")
    bad = json.loads(json.dumps(shortlist))
    bad["configurations"][0]["params"]["vote"] = 3
    sl = tmp_path / "sl.json"
    sl.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        load_manifest(sl, rs)
    unlabelled = json.loads(json.dumps(shortlist))
    unlabelled["status"] = "approved"
    sl.write_text(json.dumps(unlabelled), encoding="utf-8")
    with pytest.raises(ValueError, match="forward evidence only"):
        load_manifest(sl, rs)


def test_candidates_with_their_own_exits_are_refused_and_no_fleet_candidate_has_any():
    from research.paper_fleet.config import OWN_EXIT_CANDIDATES, SleeveSpec
    from research.strategies import ALL_KEYS, get_candidate
    from research.strategies.base import FeatureContext
    from tests.test_paper_fleet_signals import synthetic_4h

    with pytest.raises(ValueError, match="own exits"):
        SleeveSpec("S3", "BTC-USDT", "4H", {"bracket": "none"})
    df = synthetic_4h(900, seed=2)
    ctx = FeatureContext("4H", 2191.5)
    for key in ALL_KEYS:
        if key in OWN_EXIT_CANDIDATES:
            continue
        cand = get_candidate(key)
        frame = cand.build(df, cand.default_params, ctx)
        assert frame.target_distance is None and frame.time_stop_bars is None and frame.trail_r is None, key
