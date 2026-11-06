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
    # 20 from Sprint 2c / R5b, 2 from R12, 1 from R13, 1 from R16, 5 Trader-tier accounts and 2 slow-trend controls from R18 (plan row R18b),
    # 1 Trader-tier candidate and 1 forward control at the Trader tier the owner added (plan row R23)
    assert len(ids) == len(shortlist["configurations"]) + len(shortlist["controls"]) + 2 == 33
    assert ids[0] == "c01-s1s5-btc-6h-none" and ids[-2:] == ["pf-s1s2s4-btceth-vt15", ALLOCATOR_V2_ACCOUNT]
    roles = {a.role for a in manifest.accounts}
    assert roles == {"candidate", "control", "portfolio"}
    for row, acc in zip(shortlist["configurations"], [a for a in manifest.accounts if a.role == "candidate"]):
        assert acc.shortlist_rank == row["rank"] and acc.sleeve.candidate == row["candidate"]
        assert acc.sleeve.instrument == row["instrument"] and acc.sleeve.timeframe == row["timeframe"]
        tier = (row.get("source") or {}).get("tier")
        assert acc.sleeve.regime.mode == row["regime_config"]["mode"] and acc.sleeve.rebalance_threshold == 0.25
        if tier in (None, "reference"):
            assert acc.sleeve.sizing.label == "vt10/30 crash15/90dh ladder" and acc.tier is None
            assert acc.sleeve.ladder().recovery_bars == (120 if acc.timeframe == "6H" else 180) and acc.sleeve.brakes is None
        else:
            assert tier == "trader" and acc.tier == "trader" and acc.sleeve.sizing.label == "vt20/30 crash15/90dh cap2" and acc.sleeve.ladder() is None
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
    assert manifest.series() == [("BTC-USDT", "4H"), ("BTC-USDT", "6H"), ("DOGE-USDT", "4H"), ("ETH-USDT", "4H"), ("ETH-USDT", "6H"), ("SOL-USDT", "6H")]
    assert manifest.instruments() == ["BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT"]  # DOGE-USDT 4H since plan row R16


def test_source_tagged_rows_from_the_replication_study_join_as_new_accounts(manifest, tmp_path):
    """Plan row R12: the two configurations confirmed on SOL-USDT join as accounts c11 and c12; the Sprint 2c accounts, the fleet's
    shared rules and every existing fingerprint are untouched; the rows are validated against the study's own results file."""
    from research.paper_fleet.config import ALLOWED_INSTRUMENTS, INSTRUMENTS, SleeveSpec

    assert INSTRUMENTS == ("BTC-USDT", "ETH-USDT") and "SOL-USDT" in ALLOWED_INSTRUMENTS and "BTC-USDT" in ALLOWED_INSTRUMENTS
    sol = [a for a in manifest.accounts if a.instrument == "SOL-USDT" and a.tier is None]  # the Trader-tier twins came with plan row R18b
    assert [a.account_id for a in sol] == ["c11-s1s5-sol-6h-none", "c12-s1-sol-6h-none"]
    for a in sol:
        assert a.role == "candidate" and a.timeframe == "6H" and a.sleeve.regime.mode == "none" and a.sleeve.sizing.label == "vt10/30 crash15/90dh ladder"
        assert a.expectations["source"]["study"] == "R12 replication" and a.expectations["source"]["results"] == "docs/research/replication_v1d_results.json"
        assert a.expectations["holdout_confirmed"] is True and a.expectations["holdout"]["total_return"] == pytest.approx(0.095279)
        assert a.expectations["passed_walk_forward"] is True and "from R12 replication" in a.label
    assert manifest.sources["results_r12replication"].endswith("docs/research/replication_v1d_results.json")
    with pytest.raises(ValueError, match="allowed markets"):
        SleeveSpec("S1", "XYZ-USDT", "6H", {"bracket": "none"})
    # A source row whose study lacks the configuration, or whose file is missing, is refused.
    shortlist = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))
    row = next(c for c in shortlist["configurations"] if c.get("source"))
    sl = tmp_path / "sl.json"
    bad = json.loads(json.dumps(shortlist))
    next(c for c in bad["configurations"] if c.get("source"))["candidate"] = "S4"  # the study never ran S4
    sl.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="expected one research result"):
        load_manifest(sl, DEFAULT_RESULTS)
    other = json.loads(json.dumps(shortlist))
    next(c for c in other["configurations"] if c.get("source"))["timeframe"] = "4H"  # a real SOL 4H result, but other rules and numbers
    sl.write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        load_manifest(sl, DEFAULT_RESULTS)
    missing = json.loads(json.dumps(shortlist))
    next(c for c in missing["configurations"] if c.get("source"))["source"]["results"] = "docs/research/does_not_exist.json"
    sl.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(OSError):
        load_manifest(sl, DEFAULT_RESULTS)
    untagged = json.loads(json.dumps(shortlist))
    del next(c for c in untagged["configurations"] if c.get("source"))["source"]  # without its tag the row is checked against Sprint 2c's file
    sl.write_text(json.dumps(untagged), encoding="utf-8")
    with pytest.raises(ValueError, match="expected one research result"):
        load_manifest(sl, DEFAULT_RESULTS)
    assert row["rank"] == 11


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
    # A changed rule (sizing) changes the fingerprint (a tier-tagged row's sizing is pinned to the study's record, so those stay).
    for row in shortlist["configurations"]:
        if not (row.get("source") or {}).get("tier"):
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
    from research.strategies.round1 import CrossAssetContext

    df = synthetic_4h(900, seed=2)
    other = synthetic_4h(900, seed=3)
    # The round-1 cross-asset rules (plan row R13) need the other market's candles; the plain context serves every other candidate.
    ctx = CrossAssetContext("4H", 2191.5, references={"BTC-USDT": other, "ETH-USDT": other})
    assert isinstance(ctx, FeatureContext)
    for key in ALL_KEYS:
        if key in OWN_EXIT_CANDIDATES:
            continue
        cand = get_candidate(key)
        frame = cand.build(df, cand.default_params, ctx)
        assert frame.target_distance is None and frame.time_stop_bars is None and frame.trail_r is None, key


# Fingerprints of the 19 R5a accounts and of the shared rules, taken before plan row R5b: a fleet started with the R5a code
# resumes only if none of them changes (the allocator-v2 account joins it as a new account). They were taken while the FOMC
# calendar ended in 2026; plan row R7 added the 2027 dates and they hold, because no fingerprint covers the dates.
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


def test_the_configuration_confirmed_by_research_round_1_joins_as_account_c13(manifest):
    """Plan row R13: the one confirmed configuration of research round 1 (S1 with a volume confirmation of entries, BTC-USDT 4H, regime
    gate) joins as account c13 with a source tag; it needs no new market and no new data path, and every existing account is untouched."""
    acc = manifest.account("c13-s1vc-btc-4h-gate")
    assert acc.role == "candidate" and acc.shortlist_rank == 13 and acc.sleeve.candidate == "S1+VC"
    assert acc.instrument == "BTC-USDT" and acc.timeframe == "4H" and acc.sleeve.regime.mode == "gate" and acc.sleeve.bracket == "none"
    assert acc.sleeve.sizing.label == "vt10/30 crash15/90dh ladder" and acc.sleeve.rebalance_threshold == 0.25 and not acc.sleeve.uses_positioning
    assert acc.expectations["source"]["study"] == "R13 research round 1" and acc.expectations["source"]["hypothesis"] == "H2"
    assert acc.expectations["source"]["results"] == "docs/research/research_round_1_results.json" and "from R13 research round 1" in acc.label
    assert acc.expectations["passed_walk_forward"] is True and acc.expectations["walk_forward"]["calmar"] == pytest.approx(0.551912)
    assert acc.expectations["holdout_confirmed"] is True and acc.expectations["holdout"]["total_return"] == pytest.approx(0.019813)
    assert manifest.sources["results_r13researchround1"].endswith("docs/research/research_round_1_results.json")
    assert manifest.instruments() == ["BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT"]  # DOGE since plan row R16
    assert [a.account_id for a in manifest.accounts if a.role == "candidate"][10:14] == ["c11-s1s5-sol-6h-none", "c12-s1-sol-6h-none", "c13-s1vc-btc-4h-gate",
                                                                                          "c14-s1vc-doge-4h-gate"]


def test_the_configuration_confirmed_by_research_round_2_joins_as_account_c14(manifest):
    """Plan row R16: the one confirmed configuration of research round 2 (the round-1 volume confirmation on S1, DOGE-USDT 4H, regime gate)
    joins as account c14 with a source tag; DOGE is a replication-study market the fleet already knows, and every existing account is untouched."""
    acc = manifest.account("c14-s1vc-doge-4h-gate")
    assert acc.role == "candidate" and acc.shortlist_rank == 14 and acc.sleeve.candidate == "S1+VC"
    assert acc.instrument == "DOGE-USDT" and acc.timeframe == "4H" and acc.sleeve.regime.mode == "gate" and acc.sleeve.bracket == "none"
    assert acc.sleeve.sizing.label == "vt10/30 crash15/90dh ladder" and acc.sleeve.rebalance_threshold == 0.25 and not acc.sleeve.uses_positioning
    assert acc.expectations["source"]["study"] == "R16 research round 2" and acc.expectations["source"]["hypothesis"] == "H4"
    assert acc.expectations["source"]["results"] == "docs/research/research_round_2_results.json" and "from R16 research round 2" in acc.label
    assert acc.expectations["passed_walk_forward"] is True and acc.expectations["walk_forward"]["calmar"] == pytest.approx(0.832962)
    assert acc.expectations["holdout_confirmed"] is True and acc.expectations["holdout"]["total_return"] == pytest.approx(0.017873)
    assert acc.expectations["holdout"]["n_trades"] == 18
    assert manifest.sources["results_r16researchround2"].endswith("docs/research/research_round_2_results.json")
    c13 = manifest.account("c13-s1vc-btc-4h-gate")
    assert c13.sleeve.candidate == acc.sleeve.candidate and c13.sleeve.params != acc.sleeve.params  # the same condition, the rule each walk-forward selected


# Plan row R17: the four accounts added by rows R12, R13 and R16 run on the laptop since 2026-11-04 23:00 UTC (24 accounts, manifest
# fingerprint 0b5a7ea75c0f). Resuming checks the shared rules' fingerprint and every running account's fingerprint, so R17 (a data feed
# and labels, no rule) must leave all of them exactly as the fleet stored them; these are the values from its state file.
R12_R16_FINGERPRINTS = {
    "c11-s1s5-sol-6h-none": "30ecf01bfc3d4c0b9d68ccadfc873da1d19ee9f75434da3688d88baaf4857c1c",
    "c12-s1-sol-6h-none": "3dd2e7a3c5136e81161894fb29a268df4b19a654985a897bed6f206cddc57874",
    "c13-s1vc-btc-4h-gate": "a1e35f2fd5b45806549776e81928532282e69cb3576a037d1d25aabf22618b01",
    "c14-s1vc-doge-4h-gate": "d38a8e33ee3fbe9bdc63a57b1164c2e76d29e04b8c56ebd3d3590d5173ef5860",
}


def test_the_accounts_added_since_r12_keep_their_fingerprints_so_the_running_fleet_resumes_after_r17(manifest):
    assert manifest.fleet_fingerprint() == R5A_FLEET_FINGERPRINT
    assert {aid: account_fingerprint(manifest.account(aid)) for aid in R12_R16_FINGERPRINTS} == R12_R16_FINGERPRINTS
    assert {a.account_id: account_fingerprint(a) for a in manifest.accounts if a.account_id in R5A_FINGERPRINTS} == R5A_FINGERPRINTS
    assert manifest.account("c11-s1s5-sol-6h-none").sleeve.uses_positioning and not manifest.account("c12-s1-sol-6h-none").sleeve.uses_positioning


# -- plan row R18b: the Trader-tier accounts and the slow-trend forward controls of the Trader Policy v1 study --------------------

from research.brakes import TRADER_BRAKES  # noqa: E402
from research.paper_fleet.config import SleeveSpec  # noqa: E402
from research.sizing import SIZING_TIERS  # noqa: E402

R18_RESULTS = "docs/research/trader_policy_v1_results.json"
TRADER_TWINS = {  # the Trader-tier account -> its Reference twin (the same rule, the same market, today's policy)
    "c15-s1s5-sol-6h-none-trader": "c11-s1s5-sol-6h-none",
    "c16-s1-sol-6h-none-trader": "c12-s1-sol-6h-none",
    "c17-s1s5-btc-6h-none-trader": "c01-s1s5-btc-6h-none",
    "c18-s1vc-doge-4h-gate-trader": "c14-s1vc-doge-4h-gate",
    "c19-s1vc-btc-4h-gate-trader": "c13-s1vc-btc-4h-gate",
}
# Taken when the rows were applied (2026-11-05): the laptop fleet stores these when it takes the accounts, and resumes only while they hold.
R18B_FINGERPRINTS = {
    "c15-s1s5-sol-6h-none-trader": "ee1f25746fd0be2d858c4253a6c9a61f074500b844ac6c1c6b0409f90943cb00",
    "c16-s1-sol-6h-none-trader": "c864159806843a3e2bf685d606b8f188e1b1fd1382b3a20cdcea85b1dc823018",
    "c17-s1s5-btc-6h-none-trader": "cd108c9b4edb1a482b17246afed37573a69b1404daa9f8051562537599d647c6",
    "c18-s1vc-doge-4h-gate-trader": "ce948cb53a09bcdfb1271aabc15164ea9fe3bedcf054d5c08ed04f143afdb775",
    "c19-s1vc-btc-4h-gate-trader": "1ec28628f1bb3d3de54b1b5d17084c8568d9d10bc03450204443c767744749e8",
    "ctl-tf-eth-6h": "1f036b847bd6c9473e3874c13c90c6a5a4a09be62bf688c47e519d6e62412951",
    "ctl-tf-btc-6h": "32845520d3337c0f1a590368fa9552c6e9127b4dc30fa7be8ee5504aaa539255",
}


def test_the_trader_tier_rows_of_the_trader_policy_study_join_as_new_accounts_beside_their_reference_twins(manifest):
    """Plan row R18b: the five configurations that passed at the Trader tier (brakes on, holdout confirmed) join as accounts c15-c19,
    each the same rule as an existing account but sized `vt20/30 crash15/90dh cap2` without the Reference ladder and with the
    section 4.3 brakes; the slow-trend forward control joins as two control accounts at the Reference sizing. Every row is validated
    against the study's own record of that cell. Existing accounts, their fingerprints and the shared rules are untouched."""
    ids = [a.account_id for a in manifest.accounts]
    assert ids[14:19] == list(TRADER_TWINS) and ids[28:30] == ["ctl-tf-eth-6h", "ctl-tf-btc-6h"]  # ids[19] is c20 since plan row R23
    for aid, twin_id in TRADER_TWINS.items():
        acc, twin = manifest.account(aid), manifest.account(twin_id)
        assert acc.role == "candidate" and acc.kind == "sleeve" and acc.tier == "trader" and twin.tier is None
        assert (acc.sleeve.candidate, acc.instrument, acc.timeframe, acc.sleeve.regime.mode, acc.sleeve.params) == (
            twin.sleeve.candidate, twin.instrument, twin.timeframe, twin.sleeve.regime.mode, twin.sleeve.params)  # the same rule
        assert acc.sleeve.sizing == SIZING_TIERS["trader"] and acc.sleeve.sizing.risk_cap == 0.02 and acc.sleeve.ladder() is None
        assert acc.sleeve.brakes == TRADER_BRAKES and acc.sleeve.rebalance_threshold == 0.25
        rules = acc.rules_dict()["sleeve"]
        assert rules["brakes"]["hard_stop_dd"] == 0.3 and "label" not in rules["brakes"] and rules["sizing"]["risk_cap"] == 0.02 and rules["ladder"] is None
        assert account_fingerprint(acc) != account_fingerprint(twin)
        exp = acc.expectations
        assert exp["source"]["study"] == "R18 Trader Policy v1" and exp["source"]["tier"] == "trader" and exp["source"]["cell"] == "trader|brakes|none"
        assert exp["source"]["results"] == R18_RESULTS and exp["source"]["variant"] == "none" and exp["source"]["protocol_variant"] is None
        assert exp["gates"] == "section 4.6 at the trader tier" and exp["passed_walk_forward"] is True and exp["failed_gates"] == []
        assert exp["holdout_confirmed"] is True and exp["holdout"]["n_trades"] >= 10 and exp["holdout"]["total_return"] > 0
        assert exp["tier"]["name"] == "trader" and 0.01 < exp["tier"]["risk_pct_mean"] < 0.02 and exp["tier"]["risk_pct_max"] < 0.021
        assert 0 < exp["tier"]["cap_binding_share"] < 1 and exp["tier"]["brake_counts"]["entry_after_exit"] > 0 and exp["tier"]["brakes_per_year"]
        assert "trader tier" in acc.label and "brakes on" in acc.label and "from R18 Trader Policy v1" in acc.label
        assert acc.to_dict()["tier"] == "trader" and "tier" not in twin.to_dict()
    c17 = manifest.account("c17-s1s5-btc-6h-none-trader")
    assert c17.expectations["walk_forward"]["cagr"] == pytest.approx(0.104362) and c17.expectations["walk_forward"]["max_drawdown"] == pytest.approx(0.140649)
    assert c17.expectations["holdout"]["total_return"] == pytest.approx(0.034127) and c17.sleeve.uses_positioning
    for aid, inst in (("ctl-tf-btc-6h", "BTC-USDT"), ("ctl-tf-eth-6h", "ETH-USDT")):
        ctl = manifest.account(aid)
        assert ctl.role == "control" and ctl.kind == "sleeve" and ctl.tier == "reference" and ctl.sleeve.candidate == "TF"
        assert ctl.instrument == inst and ctl.timeframe == "6H" and ctl.sleeve.params == {"sma_days": 200.0, "bracket": "none"}
        assert ctl.sleeve.sizing.label == "vt10/30 crash15/90dh ladder" and ctl.sleeve.ladder().recovery_bars == 120 and ctl.sleeve.brakes is None
        assert "brakes" not in ctl.rules_dict()["sleeve"] and ctl.expectations["holdout"] is None and ctl.expectations["holdout_confirmed"] is None
        assert ctl.expectations["source"]["role"] == "control" and "fixed rule" in ctl.expectations["protocol_variant"]
        assert "200-day average" in ctl.label and ctl.label.startswith("control:")
    assert manifest.account("ctl-tf-btc-6h").expectations["walk_forward"]["n_trades"] == 40
    assert manifest.sources["results_r18traderpolicyv1"].endswith(R18_RESULTS) and manifest.sources["results_r18traderpolicyv1_sha256"]
    assert manifest.series() == [("BTC-USDT", "4H"), ("BTC-USDT", "6H"), ("DOGE-USDT", "4H"), ("ETH-USDT", "4H"), ("ETH-USDT", "6H"), ("SOL-USDT", "6H")]
    assert {aid: account_fingerprint(manifest.account(aid)) for aid in R18B_FINGERPRINTS} == R18B_FINGERPRINTS
    assert manifest.fleet_fingerprint() == R5A_FLEET_FINGERPRINT
    assert {a.account_id: account_fingerprint(a) for a in manifest.accounts if a.account_id in R5A_FINGERPRINTS} == R5A_FINGERPRINTS
    assert {aid: account_fingerprint(manifest.account(aid)) for aid in R12_R16_FINGERPRINTS} == R12_R16_FINGERPRINTS
    with pytest.raises(ValueError, match="sized sleeve"):
        SleeveSpec("S1", "BTC-USDT", "6H", {"bracket": "none"}, brakes=TRADER_BRAKES)


def _edited(tmp_path, edit, name="sl.json"):
    doc = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))
    edit(doc)
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_a_tier_tagged_row_is_refused_on_any_mismatch_with_the_study_record(tmp_path):
    """The loader matches a tier-tagged row on its cell and accepts the recorded protocol check only when it is clean and the tier
    named is what the result's sizing and brakes describe; any other difference refuses the whole manifest (the fleet cannot start)."""
    probes = [
        (lambda d: d["configurations"][14]["source"].update(tier="aggressive"), "describe 'trader'"),
        (lambda d: d["configurations"][14]["source"].update(cell="trader|nobrakes|none"), "brakes recorded with the row are not"),
        (lambda d: d["configurations"][14]["source"].update(cell="aggressive|brakes|none", tier="aggressive"), "sizing is not the result's"),
        (lambda d: d["configurations"][14]["source"].pop("cell"), "found 18"),
        (lambda d: d["configurations"][14]["source"].update(cell="trader|brakes|add", variant="add"), "variant"),
        (lambda d: d["configurations"][14]["source"]["brakes"].update(hard_stop_dd=0.5), "brakes recorded with the row are not"),
        (lambda d: d["configurations"][14]["sizing_config"].update(risk_cap=0.03), "sizing is not the result's"),
        (lambda d: d["configurations"][14]["source"].update(protocol_variant="fixed rule"), "only for a registered fixed rule"),  # plan row R19: a fixed rule may; a swept rule may not
        (lambda d: d["configurations"][14]["source"].update(role="control"), "belongs under 'controls'"),
        (lambda d: d["configurations"][14]["params"].update(vote=2), "does not match"),
        (lambda d: d["controls"][8]["source"].update(tier="trader", cell="trader|brakes|none"), "brakes recorded with the row are not"),
        (lambda d: d["controls"][8]["source"].update(protocol_variant=None), "needs its protocol variant"),
        (lambda d: d["controls"][8]["source"].update(role="candidate"), "must name the control role"),
        (lambda d: d["controls"][8].update(candidate="S1"), "unknown control"),
    ]
    for edit, message in probes:
        with pytest.raises(ValueError, match=message):
            load_manifest(_edited(tmp_path, edit), DEFAULT_RESULTS)
    # A study record whose protocol check of that cell has an unexplained mismatch (a copy of the results file, edited) is refused too.
    doc = json.loads((DEFAULT_RESULTS.parent / "trader_policy_v1_results.json").read_text(encoding="utf-8"))
    for r in doc["results"]:
        if r["candidate"] == "S1+S5" and r["instrument"] == "SOL-USDT" and r["cell"]["key"] == "trader|brakes|none":
            r["protocol_check"]["unexplained_mismatches"] = {"fee": {"got": 0.002, "stored": 0.001}}
            r["protocol_check"]["ok_for_cell"] = False
    bad = tmp_path / "results_bad.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="not clean"):
        load_manifest(_edited(tmp_path, lambda d: d["configurations"][14]["source"].update(results=str(bad))), DEFAULT_RESULTS)
    # An explained mismatch the fleet does not know (the study would have had to change the protocol) is refused as well.
    for r in doc["results"]:
        if r["candidate"] == "S1+S5" and r["instrument"] == "SOL-USDT" and r["cell"]["key"] == "trader|brakes|none":
            r["protocol_check"]["unexplained_mismatches"] = {}
            r["protocol_check"]["ok_for_cell"] = True
            r["protocol_check"]["expected_mismatches"]["train_days"] = "a shorter train slice"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="does not accept"):
        load_manifest(_edited(tmp_path, lambda d: d["configurations"][14]["source"].update(results=str(bad))), DEFAULT_RESULTS)
    # The untouched file still loads, and the tier accounts' expectations are not in any fingerprint.
    changed = _edited(tmp_path, lambda d: d["configurations"][14]["holdout"].update(total_return=0.5), "exp.json")
    assert load_manifest(changed, DEFAULT_RESULTS).fingerprint() == load_manifest().fingerprint()


# -- plan row R23: the S8 forward control at the Trader tier and S1 BTC-USDT 6H at the Trader tier, both the owner's decision ------------

# Taken when the rows were applied (2026-11-05): the laptop fleet stores these when it takes the two accounts, and resumes only while they hold.
R23_FINGERPRINTS = {
    "c20-s1-btc-6h-none-trader": "10a09a9222457281d07534d53781feccddb7d5f206de75855818fbfd8ad81450",
    "ctl-s8-btc-6h-trader": "26fd553d0d79617530ac52ac859e9d1c670f0ee8ae015c8df23767c27eebb702",
}


def test_the_two_accounts_the_owner_added_join_and_every_running_account_is_untouched(manifest):
    """Plan row R23: `ctl-s8-btc-6h-trader` (the slow breakout S8 at the Trader tier with the brakes on, a forward control from research round
    3's record, never judged) and `c20-s1-btc-6h-none-trader` (plain S1 at the Trader tier with the brakes on, from the breadth study's record,
    holdout confirmed, no Reference twin). Both validated against their study's record of that cell; the 31 running accounts, their
    fingerprints and the shared rules are exactly what the laptop fleet stored."""
    from research.paper_fleet.config import CONTROL_TIERS, FIXED_RULES
    from research.trader_policy import TIERS

    # The documented budgets of the Trader Plan's section 4.1 (TIERS also lists `risk1.5`, which the plan reports for information only).
    assert CONTROL_TIERS == ("reference", "trader", "aggressive") and set(CONTROL_TIERS) < set(TIERS) and "S8" in FIXED_RULES
    ids = [a.account_id for a in manifest.accounts]
    assert len(ids) == 33 and ids[19] == "c20-s1-btc-6h-none-trader" and ids[28:31] == ["ctl-tf-eth-6h", "ctl-tf-btc-6h", "ctl-s8-btc-6h-trader"]
    c20 = manifest.account("c20-s1-btc-6h-none-trader")
    assert c20.role == "candidate" and c20.kind == "sleeve" and c20.tier == "trader" and c20.shortlist_rank == 20 and c20.sleeve.candidate == "S1"
    assert c20.instrument == "BTC-USDT" and c20.timeframe == "6H" and c20.sleeve.regime.mode == "none" and c20.sleeve.bracket == "none"
    assert c20.sleeve.sizing == SIZING_TIERS["trader"] and c20.sleeve.brakes == TRADER_BRAKES and c20.sleeve.ladder() is None
    assert c20.sleeve.rebalance_threshold == 0.25 and not c20.sleeve.uses_positioning
    assert c20.sleeve.params == dict(manifest.account("pf-s1s2s4-btceth-vt15").portfolio.sleeves)["S1/BTC/6H"].params  # the same rule as the portfolio's sleeve
    exp = c20.expectations
    assert exp["source"]["study"] == "R20 breadth v1" and exp["source"]["results"] == "docs/research/breadth_v1_results.json"
    assert exp["source"]["cell"] == "trader|brakes|none" and exp["source"]["tier"] == "trader" and exp["source"]["role"] == "candidate"
    assert "no fleet ticket" in exp["source"]["note"] and exp["source"]["protocol_variant"] is None and "protocol_variant" not in exp
    assert exp["gates"] == "section 4.6 at the trader tier" and exp["passed_walk_forward"] is True and exp["failed_gates"] == []
    assert exp["walk_forward"]["calmar"] == pytest.approx(0.606091) and exp["walk_forward"]["cagr"] == pytest.approx(0.08645)
    assert exp["walk_forward"]["max_drawdown"] == pytest.approx(0.142636) and exp["walk_forward"]["n_trades"] == 140
    assert exp["holdout_confirmed"] is True and exp["holdout"]["total_return"] == pytest.approx(0.038343) and exp["holdout"]["n_trades"] == 32
    assert exp["tier"]["name"] == "trader" and 0.01 < exp["tier"]["risk_pct_mean"] < 0.02 and exp["tier"]["brakes_per_year"]
    assert "trader tier" in c20.label and "brakes on" in c20.label and "from R20 breadth v1" in c20.label and c20.to_dict()["tier"] == "trader"
    # No Reference twin: plain S1 on BTC-USDT 6H never passed at the Reference sizing, so no account runs it there (the portfolio's sleeve is full size).
    assert not any(a.role == "candidate" and a.tier is None and a.sleeve.candidate == "S1" and a.instrument == "BTC-USDT" and a.timeframe == "6H"
                   for a in manifest.accounts)
    s8 = manifest.account("ctl-s8-btc-6h-trader")
    assert s8.role == "control" and s8.kind == "sleeve" and s8.tier == "trader" and s8.sleeve.candidate == "S8" and s8.shortlist_rank is None
    assert s8.instrument == "BTC-USDT" and s8.timeframe == "6H" and s8.sleeve.regime.mode == "none"
    assert s8.sleeve.params == {"entry_days": 55, "exit_days": 20, "atr_window": 14, "atr_mult": 5.0, "bracket": "none"}
    assert s8.sleeve.sizing == SIZING_TIERS["trader"] and s8.sleeve.brakes == TRADER_BRAKES and s8.sleeve.ladder() is None and s8.sleeve.rebalance_threshold == 0.25
    rules = s8.rules_dict()["sleeve"]
    assert rules["brakes"]["hard_stop_dd"] == 0.3 and "label" not in rules["brakes"] and rules["sizing"]["risk_cap"] == 0.02 and rules["ladder"] is None
    exp = s8.expectations
    assert exp["source"]["study"] == "R19 research round 3" and exp["source"]["results"] == "docs/research/research_round_3_results.json"
    assert exp["source"]["role"] == "control" and exp["source"]["cell"] == "trader|brakes|none" and exp["source"]["hypothesis"] == "H8"
    assert exp["protocol_variant"].startswith("fixed rule") and exp["holdout"] is None and exp["holdout_confirmed"] is None
    assert exp["gates"] == "section 4.6 at the trader tier" and exp["passed_walk_forward"] is False and exp["failed_gates"] == ["calmar_gt_0_5", "enough_trades"]
    assert exp["walk_forward"]["calmar"] == pytest.approx(0.443397) and exp["walk_forward"]["cagr"] == pytest.approx(0.039139)
    assert exp["walk_forward"]["n_trades"] == 17 and exp["walk_forward"]["trades_per_year"] == pytest.approx(3.942381)
    assert exp["tier"]["name"] == "trader" and exp["tier"]["expectancy_r"] == pytest.approx(0.541689) and exp["tier"]["brake_counts"]["entry_after_exit"] == 3
    assert s8.label.startswith("control: slow breakout S8") and "forward control" in s8.label and "trader tier" in s8.label
    assert "brakes on" in s8.label and "from R19 research round 3" in s8.label and s8.to_dict()["tier"] == "trader"
    tf = manifest.account("ctl-tf-btc-6h")
    assert tf.tier == "reference" and tf.sleeve.brakes is None and account_fingerprint(s8) != account_fingerprint(tf)
    assert manifest.sources["results_r19researchround3"].endswith("docs/research/research_round_3_results.json")
    assert manifest.sources["results_r20breadthv1"].endswith("docs/research/breadth_v1_results.json") and manifest.sources["results_r20breadthv1_sha256"]
    assert manifest.series() == [("BTC-USDT", "4H"), ("BTC-USDT", "6H"), ("DOGE-USDT", "4H"), ("ETH-USDT", "4H"), ("ETH-USDT", "6H"), ("SOL-USDT", "6H")]
    assert manifest.instruments() == ["BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT"]
    assert {aid: account_fingerprint(manifest.account(aid)) for aid in R23_FINGERPRINTS} == R23_FINGERPRINTS
    assert manifest.fleet_fingerprint() == R5A_FLEET_FINGERPRINT
    assert {a.account_id: account_fingerprint(a) for a in manifest.accounts if a.account_id in R5A_FINGERPRINTS} == R5A_FINGERPRINTS
    assert {aid: account_fingerprint(manifest.account(aid)) for aid in R12_R16_FINGERPRINTS} == R12_R16_FINGERPRINTS
    assert {aid: account_fingerprint(manifest.account(aid)) for aid in R18B_FINGERPRINTS} == R18B_FINGERPRINTS


def test_a_fixed_rule_control_at_a_tier_is_refused_on_any_mismatch_and_the_tf_controls_stay_at_the_reference_sizing(tmp_path, monkeypatch):
    """The S8 control row (controls[10]) is held to its study's record of the cell exactly as a fixed-rule candidate is; the slow-trend TF
    controls (controls[8], [9]) may not move off the Reference sizing; a control tier outside the documented ones is refused."""
    s8 = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))["controls"][10]
    assert s8["candidate"] == "S8" and s8["source"]["tier"] == "trader"
    probes = [
        (lambda d: d["controls"][10]["source"].update(role="candidate"), "must name the control role"),
        (lambda d: d["controls"][10]["source"].update(protocol_variant="fixed rule"), "the study recorded"),
        (lambda d: d["controls"][10]["source"].update(protocol_variant=None), "needs its protocol variant"),
        (lambda d: d["controls"][10]["source"].update(cell="reference|nobrakes|none", tier="reference"), "brakes recorded with the row are not"),
        (lambda d: d["controls"][10]["source"].update(cell="trader|nobrakes|none"), "found 0"),  # round 3 ran the Reference and the Trader cell only
        (lambda d: d["controls"][10]["source"]["brakes"].update(hard_stop_dd=0.5), "brakes recorded with the row are not"),
        (lambda d: d["controls"][10]["sizing_config"].update(risk_cap=0.03), "sizing is not the result's"),
        (lambda d: d["controls"][10]["source"].update(tier="aggressive"), "describe 'trader'"),
        (lambda d: d["controls"][10]["params"].update(entry_days=20), "does not match"),
        (lambda d: d["controls"][10].update(candidate="S7"), "does not match"),  # round 3 ran S7 at that cell too, with other parameters
        (lambda d: d["controls"][10].update(candidate="S1"), "unknown control"),
        (lambda d: d["controls"][10].pop("source"), "unknown control"),
        (lambda d: d["controls"][9]["source"].update(tier="trader", cell="trader|brakes|none", brakes=d["controls"][10]["source"]["brakes"])
         or d["controls"][9].update(sizing_config=d["controls"][10]["sizing_config"]), "Reference sizing without brakes"),
    ]
    for edit, message in probes:
        with pytest.raises(ValueError, match=message):
            load_manifest(_edited(tmp_path, edit), DEFAULT_RESULTS)
    # A row of an S8 control under 'configurations' is refused as a control row in the wrong place.
    with pytest.raises(ValueError, match="belongs under 'controls'"):
        load_manifest(_edited(tmp_path, lambda d: d["configurations"].append(dict(s8, rank=21))), DEFAULT_RESULTS)
    # A documented tier only: with the Trader tier struck from the documented list the row is refused (the TF rule is separate).
    monkeypatch.setattr("research.paper_fleet.config.CONTROL_TIERS", ("reference",))
    with pytest.raises(ValueError, match="documented tier"):
        load_manifest(DEFAULT_SHORTLIST, DEFAULT_RESULTS)
    monkeypatch.undo()
    # Expectations are not rules: an edited holdout or label leaves every fingerprint alone.
    changed = _edited(tmp_path, lambda d: d["controls"][10].update(control_label="another wording", cagr=d["controls"][10]["cagr"]), "label.json")
    assert load_manifest(changed, DEFAULT_RESULTS).fingerprint() == load_manifest().fingerprint()
