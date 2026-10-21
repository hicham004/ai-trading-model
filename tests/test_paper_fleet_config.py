"""The fleet manifest: every shortlist row and control becomes one account; nothing is re-selected; rule changes are detected."""

from __future__ import annotations

import json

import pytest

from research.allocator import DEFAULT_ALLOCATOR_V2
from research.paper_fleet.config import (
    ALLOCATOR_V2_ACCOUNT,
    DEFAULT_ALLOCATOR_RESULTS,
    DEFAULT_RESULTS,
    DEFAULT_SHORTLIST,
    NO_TRADE,
    account_fingerprint,
    load_manifest,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


def test_one_account_per_shortlist_row_control_and_the_two_portfolios(manifest):
    shortlist = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))
    ids = [a.account_id for a in manifest.accounts]
    assert len(ids) == len(shortlist["configurations"]) + len(shortlist["controls"]) + 2 == 20
    assert ids[0] == "c01-s1s5-btc-6h-none" and ids[-2:] == ["pf-s1s2s4-btceth-vt15", ALLOCATOR_V2_ACCOUNT]
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


# Fingerprints of the 19 R5a accounts and of the shared rules, taken before plan row R5b: a fleet started with the R5a code
# resumes only if none of them changes (the allocator-v2 account joins it as a new account).
R5A_FLEET_FINGERPRINT = "ef9a24cda90e2fd1d29735d29bf30b6bfc22d4699abe3ed8b2c6b1255f24b48e"
R5A_FINGERPRINTS = {
    "c01-s1s5-btc-6h-none": "4d2045a7a638be352b44cc60e42731c3f83738d04fd7de216137414fb07b0550",
    "c02-s2s5-btc-4h-gate": "fabc446f7339bd95f709de66eadae7653ccafea6bb33fdd30d3308c1cf500dc8",
    "c03-s2-btc-4h-gate": "b686bf8b3bee3c1e40fbc3d67c0f875e60e47a2676fdd1ee810d050aa0a16175",
    "c04-s2s5s-btc-4h-gate": "7babe931f49a58240605d1423aa821153056f862f2f80daaff0f2aec3a4990b8",
    "c05-s1h-eth-6h-none": "53dea9804de53a96694a91f23190379efe211ea81b3f05b82b8b97e0369019b1",
    "c06-s1h-eth-4h-gate": "d2fdfaf1a15c13988b7010fe19beac018a0dab8a14be5784e3212ce576ba61a6",
    "c07-s2d-eth-6h-gate": "4d37911fc6c69ca4ab0b6c75f0be7581e973f13ed2cae0519faaf5bd1ee8302b",
    "c08-s2s5s-eth-6h-gate": "794e6e2287cbfd800d5652517baef84d79a6d2b72ffc1ee222149ece21873d64",
    "c09-s2s5-eth-4h-none": "ecf03478664962f2e7277fa17706dcbda16288344f21e1cb45dca658fb193297",
    "c10-s2-eth-6h-gate": "48fb9bb1ec0abaeaff83798edc7fe3614540d29ccd9d9ff5e51a03abc0656fd9",
    "ctl-hold-btc-4h": "3a9c7a6a347a6869e7d1a0844913e7832d3f6132fbbfceba182e7d0fecb48abe",
    "ctl-hold-btc-6h": "81b8a98457a80d4bfdf4148e056904d65cf7bfce0cc38d21f3bb877f2829121e",
    "ctl-hold-eth-4h": "8430282e422cc08a8eee41e4a30aeef1bf47334047a50415c541496412d2e396",
    "ctl-hold-eth-6h": "5df97bd0be5fad817db32e888d1ba32065f33b5bcd1c9a634cbe853513a1313d",
    "ctl-bh-btc-4h": "827f64781133b3961240f20dfe924fb2bcc4bf5fd74c951c51cd26086651de02",
    "ctl-bh-btc-6h": "13530e8999f74f4f5ac3cd27fce614536f1418653a70981a7d251f0ff76b4e67",
    "ctl-bh-eth-4h": "fc5a638862809742e7148f4968979718766f06713f7f6ec45287cabcdaa44ebc",
    "ctl-bh-eth-6h": "7e5d551782159fd10081d3d0388cad2e671ccf532df36ac81ae6c1cd9905d8ec",
    "pf-s1s2s4-btceth-vt15": "7ad55450b831d0f3b618580f21e75581e471a0cb26969d8290eb837ce4bdca65",
}


def test_every_r5a_account_keeps_its_fingerprint_so_a_running_fleet_resumes(manifest):
    assert manifest.fleet_fingerprint() == R5A_FLEET_FINGERPRINT
    assert {a.account_id: account_fingerprint(a) for a in manifest.accounts if a.account_id in R5A_FINGERPRINTS} == R5A_FINGERPRINTS
    assert "allocator" not in manifest.account("pf-s1s2s4-btceth-vt15").rules_dict()["portfolio"]


def test_the_allocator_v2_account_runs_the_same_sleeves_with_its_pre_registered_brakes(manifest):
    v1 = manifest.account("pf-s1s2s4-btceth-vt15").portfolio
    acc = manifest.account(ALLOCATOR_V2_ACCOUNT)
    v2 = acc.portfolio
    assert (acc.role, acc.kind) == ("portfolio", "portfolio") and "allocator v2" in acc.label
    assert v2.sleeves == v1.sleeves and v2.allocator == DEFAULT_ALLOCATOR_V2 and v1.allocator is None
    assert (v2.target_vol, v2.vol_lookback_days, v2.weight_lookback_days, v2.ladder, v2.cap, v2.warmup_days) == (
        v1.target_vol, v1.vol_lookback_days, v1.weight_lookback_days, v1.ladder, v1.cap, v1.warmup_days)
    assert account_fingerprint(acc) != account_fingerprint(manifest.account("pf-s1s2s4-btceth-vt15"))
    rules = acc.rules_dict()["portfolio"]["allocator"]
    assert rules["group_cap"] == 0.5 and rules["loss_limit"] == 0.05 and "label" not in rules  # the fingerprint covers numbers, not wording
    exp = acc.expectations
    assert exp["walk_forward"]["cagr"] == pytest.approx(0.104697, abs=1e-6) and exp["walk_forward"]["max_drawdown"] == pytest.approx(0.122896, abs=1e-6)
    assert exp["passed_walk_forward"] is True and exp["holdout"]["confirmed"] is False and exp["holdout"]["bars"] == 364
    assert (exp["holdout"]["first_day"], exp["holdout"]["last_day"]) == ("2025-10-21", "2026-10-19")  # full UTC days only
    assert exp["holdout"]["reference_v1_total_return"] < exp["holdout"]["total_return"] < 0
    assert v2.sleeve_assets == {"S1/BTC/6H": "BTC-USDT", "S1/ETH/6H": "ETH-USDT", "S2/BTC/4H": "BTC-USDT", "S2/ETH/4H": "ETH-USDT",
                                "S4/BTC/6H": "BTC-USDT", "S4/ETH/6H": "ETH-USDT"}


def test_allocator_results_that_do_not_describe_the_account_are_refused(tmp_path):
    result = json.loads(DEFAULT_ALLOCATOR_RESULTS.read_text(encoding="utf-8"))
    path = tmp_path / "alloc.json"
    for edit, message in ((lambda r: r["meta"]["allocator_v2"].update(group_cap=0.6), "other brakes"),
                          (lambda r: r["meta"]["sleeves"][0]["params"].update(vote=3), "other sleeves"),
                          (lambda r: r["meta"]["settings"].update(target_vol=0.10), "vol target"),
                          (lambda r: r.update(status="approved"), "SIMULATION ONLY")):
        doc = json.loads(json.dumps(result))
        edit(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_manifest(DEFAULT_SHORTLIST, DEFAULT_RESULTS, path)
