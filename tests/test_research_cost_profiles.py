"""Plan row R24: the named cost profiles of the research engine (SIMULATION ONLY; no study is run, no results file changes).

The owner decided on 2026-11-05, from the R22 fill-cost replay, that studies pre-registered after that day on BTC-USDT and ETH-USDT
charge 2 bps of slippage a side (0.24 % a round trip) as a NAMED profile, so that the engine's default, every stored study, the paper
fleet's accounts and its own fill costs stay exactly as they are. Covered here: the three profiles and ``Costs()`` unchanged; the
breadth study's constants taken from the registry; the shared runner's ``--cost-profile``, recorded in the results ``meta`` and on
every result, charged only on the markets it was measured on, never overwriting Sprint 2c's stored files; a pre-registration naming
its profile with the numbers; the protocol checks of the R18a, R19 and R20 studies explaining a fee / slippage difference only when
the pre-registration names that profile; the reproduction at the stored run's profile; the paper fleet refusing any record at
another cost profile.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from app.datalake.layout import LakeLayout
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE, write_partitioned
from research import breadth_study, round3, trader_policy_study
from research.engine import (
    ALTCOIN_PROFILE,
    COST_PROFILE_INSTRUMENTS,
    COST_PROFILE_NOTES,
    COST_PROFILES,
    CUSTOM_PROFILE,
    GATE_PROFILE,
    MEASURED_BTC_ETH_PROFILE,
    Costs,
    buy_and_hold,
    cost_profile_for,
)
from research.replication import (
    V1C_RESULTS,
    ReplicationError,
    cost_profile_of,
    cost_profile_record,
    explain_cost_mismatches,
    load_v1c_runner,
    preregistered_cost_profile,
    protocol_check,
    reproduction_check,
)

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DOCS = ROOT / "docs" / "research"
MEASURED = MEASURED_BTC_ETH_PROFILE


@pytest.fixture(scope="module")
def v1c():
    return load_v1c_runner()


@pytest.fixture(scope="module")
def stored_meta():
    return json.loads(V1C_RESULTS.read_text(encoding="utf-8"))["meta"]


# -- the registry and Costs ---------------------------------------------------------------------------------------------

def test_the_three_named_profiles_and_their_numbers():
    assert list(COST_PROFILES) == [GATE_PROFILE, MEASURED, ALTCOIN_PROFILE] == ["gate", "measured_btc_eth_2026_11", "altcoin"]
    expected = {"gate": (0.0010, 0.0005, 0.0030), MEASURED: (0.0010, 0.0002, 0.0024), "altcoin": (0.0010, 0.0015, 0.0050)}
    for name, (fee, slip, round_trip) in expected.items():
        costs = Costs.named(name)
        assert costs is COST_PROFILES[name] and costs.profile == name and costs.profile_label == name
        assert (costs.fee_rate, costs.slippage_rate) == (fee, slip) and costs.round_trip == pytest.approx(round_trip, abs=1e-15)
        assert costs.to_dict() == {"profile": name, "fee_rate": fee, "slippage_rate": slip, "round_trip": pytest.approx(round_trip, abs=1e-15)}
        assert cost_profile_for(fee, slip) == name and COST_PROFILE_NOTES[name] and costs.label.startswith(f"{name}: fee 0.10 %")
    assert "0.24 % a round trip" in Costs.named(MEASURED).label and "0.50 % a round trip" in Costs.named("altcoin").label
    # A profile is chosen by its name only; the registry is read-only and no two profiles share numbers, so a name describes its numbers.
    for unknown in ("measured", CUSTOM_PROFILE, None):
        with pytest.raises(ValueError, match="unknown cost profile"):
            Costs.named(unknown)
    with pytest.raises(TypeError):
        COST_PROFILES["gate"] = Costs(0.0, 0.0)  # type: ignore[index]
    assert len({(c.fee_rate, c.slippage_rate) for c in COST_PROFILES.values()}) == len(COST_PROFILES)
    # The measured profile was measured on BTC-USDT and ETH-USDT only; the gate and altcoin profiles cover every market.
    assert dict(COST_PROFILE_INSTRUMENTS) == {MEASURED: ("BTC-USDT", "ETH-USDT")}
    measured = Costs.named(MEASURED)
    assert measured.covers("BTC-USDT") and measured.covers("ETH-USDT") and not measured.covers("SOL-USDT") and not measured.covers("DOGE-USDT")
    assert Costs.named("gate").covers("SOL-USDT") and Costs.named("altcoin").covers("DOGE-USDT") and Costs(0.0, 0.0).covers("XRP-USDT")
    assert "BTC-USDT and ETH-USDT only" in COST_PROFILE_NOTES[MEASURED] and "FILL_COST_REPLAY.md" in COST_PROFILE_NOTES[MEASURED]


def test_costs_default_is_unchanged_and_the_profile_name_is_not_part_of_equality():
    default = Costs()
    assert (default.fee_rate, default.slippage_rate) == (0.0010, 0.0005) and default.round_trip == pytest.approx(0.003, abs=1e-15)
    assert default == Costs(0.001, 0.0005) == Costs(fee_rate=0.001, slippage_rate=0.0005) == Costs.named("gate")
    assert hash(default) == hash(Costs.named("gate")) and default.profile == "gate" and len({default, Costs.named("gate")}) == 1
    zero = Costs(0.0, 0.0)  # numbers no profile has: unnamed, labelled "custom" in reports
    assert zero != default and zero.profile is None and zero.profile_label == "custom" and zero.label.startswith("custom: fee 0.00 %")
    assert zero.to_dict()["profile"] == "custom"
    assert Costs(0.001, 0.0002) == Costs.named(MEASURED) and Costs(0.001, 0.0002).profile == MEASURED
    with pytest.raises(ValueError, match="must be in"):
        Costs(fee_rate=0.5)
    with pytest.raises(ValueError, match="is fee 0.001 \\+ slippage 0.0005 a side"):
        Costs(0.001, 0.0002, profile="gate")  # a Costs never carries the name of a profile it does not charge
    with pytest.raises(ValueError, match="unknown cost profile"):
        Costs(0.001, 0.0005, profile="cheap")
    # The engine's default charges exactly the gate profile, and the measured profile charges less on the same trade.
    rng = np.random.default_rng(1)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 400)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    assert np.array_equal(buy_and_hold(open_, close), buy_and_hold(open_, close, costs=Costs.named("gate")))
    assert buy_and_hold(open_, close, costs=Costs.named(MEASURED))[-1] > buy_and_hold(open_, close)[-1]


def test_the_breadth_study_constants_are_the_registry_values_and_its_registration_still_holds():
    assert breadth_study.MAJOR_COSTS is Costs.named("gate") and breadth_study.ALTCOIN_COSTS is Costs.named("altcoin")
    assert (breadth_study.MAJOR_COSTS.fee_rate, breadth_study.MAJOR_COSTS.slippage_rate) == (0.0010, 0.0005)
    assert (breadth_study.ALTCOIN_COSTS.fee_rate, breadth_study.ALTCOIN_COSTS.slippage_rate) == (0.0010, 0.0015)
    assert breadth_study.costs_for("ETH-USDT").profile == "gate" and breadth_study.costs_for("LINK-USDT").profile == "altcoin"
    # The committed pre-registration recorded exactly these numbers, so the stored results reproduce with the registry's values.
    committed = json.loads(breadth_study.PREREGISTRATION_PATH.read_text(encoding="utf-8"))
    assert committed["costs"] == {"majors": {"fee_rate": 0.001, "slippage_rate": 0.0005}, "altcoins": {"fee_rate": 0.001, "slippage_rate": 0.0015}}
    assert breadth_study.load_preregistration()["sha256"] == committed["sha256"]


# -- the shared runner ----------------------------------------------------------------------------------------------------

def test_the_runner_takes_a_cost_profile_records_it_and_refuses_contradictions(v1c, stored_meta):
    default = v1c.parse_args([])
    assert (default.cost_profile, default.fee, default.slippage) == ("gate", 0.0010, 0.0005)
    measured = v1c.parse_args(["--cost-profile", MEASURED])
    assert (measured.cost_profile, measured.fee, measured.slippage) == (MEASURED, 0.0010, 0.0002)
    assert (v1c.parse_args(["--cost-profile", "altcoin"]).cost_profile, v1c.parse_args(["--cost-profile", "altcoin"]).slippage) == ("altcoin", 0.0015)
    # Hand-given numbers still work and are named after the profile they equal, otherwise "custom".
    assert v1c.parse_args(["--slippage", "0.0002"]).cost_profile == MEASURED
    assert v1c.parse_args(["--fee", "0.001", "--slippage", "0.0005"]).cost_profile == "gate"
    custom = v1c.parse_args(["--slippage", "0.0003"])
    assert (custom.cost_profile, custom.slippage) == ("custom", 0.0003)
    for bad in (["--cost-profile", "gate", "--slippage", "0.0002"], ["--cost-profile", MEASURED, "--fee", "0.0008"], ["--cost-profile", "cheap"],
                ["--fee", "0.5"]):
        with pytest.raises(SystemExit):
            v1c.parse_args(bad)
    # What a results meta records (the runner's own meta takes this block): the profile's name and the numbers charged.
    assert v1c._cost_meta(default) == {"cost_profile": "gate", "fee_rate": 0.001, "slippage_rate": 0.0005, "round_trip": pytest.approx(0.003, abs=1e-15)}
    assert v1c._cost_meta(measured) == {"cost_profile": MEASURED, "fee_rate": 0.001, "slippage_rate": 0.0002, "round_trip": pytest.approx(0.0024, abs=1e-15)}
    assert v1c._cost_meta(custom)["cost_profile"] == "custom"
    assert v1c._costs(measured) == Costs.named(MEASURED) and v1c._costs(measured).profile == MEASURED
    with pytest.raises(ValueError, match="names the cost profile 'gate'"):
        v1c._costs(argparse.Namespace(**dict(vars(default), slippage=0.0002)))  # a recorded name that does not describe the numbers
    # The defaults are still Sprint 2c's protocol: the protocol check against the stored run finds no cost difference.
    args = dict(vars(default), strategies=["S1", "S2"], regime_modes=["none", "gate"], timeframes=["4H", "6H"])
    assert protocol_check(args, stored_meta)["mismatches"] == {}
    assert set(protocol_check(dict(vars(measured), strategies=["S1"], regime_modes=["none"], timeframes=["6H"]), stored_meta)["mismatches"]) == {"slippage"}


def _write_candles(layout: LakeLayout, instrument: str, n: int = 7600) -> None:
    rng = np.random.default_rng(3)
    idx = pd.date_range("2021-01-01", periods=n, freq="4h", tz="UTC")
    regime = np.sign(np.sin(np.arange(n) / 60.0))
    close = 100 * np.exp(np.cumsum(0.004 * regime + rng.normal(0, 0.012, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    table = pa.table({
        "open_time": pa.array([t.to_pydatetime() for t in idx], type=TS_TYPE), "instrument": pa.array([instrument] * n),
        "timeframe": pa.array(["4H"] * n), "open": pa.array(open_), "high": pa.array(high), "low": pa.array(low), "close": pa.array(close),
        "volume": pa.array(rng.lognormal(3, 0.5, n)), "confirmed": pa.array([True] * n),
    }, schema=CANDLE_SCHEMA)
    write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA, file_for_year=lambda y: layout.candles_file(instrument, "4H", y))


@pytest.fixture(scope="module")
def btc_lake(tmp_path_factory):
    layout = LakeLayout(tmp_path_factory.mktemp("r24_lake") / "lake")
    _write_candles(layout, "BTC-USDT")
    _write_candles(layout, "SOL-USDT")
    return layout


def test_run_series_charges_the_named_profile_records_it_on_every_result_and_only_on_its_markets(v1c, btc_lake):
    common = ["--strategies", "hold", "S1", "--regime-modes", "none", "--timeframes", "4H", "--quick", "--no-comparison", "--mc-paths", "20",
              "--lake-dir", str(btc_lake.root)]
    gate = v1c.run_series(dict(vars(v1c.parse_args(common))), "BTC-USDT", "4H")
    measured = v1c.run_series(dict(vars(v1c.parse_args(common + ["--cost-profile", MEASURED]))), "BTC-USDT", "4H")
    assert {r["candidate"] for r in gate["results"]} == {r["candidate"] for r in measured["results"]} == {"hold", "S1"}
    assert all(r["costs"] == Costs.named("gate").to_dict() for r in gate["results"])
    assert all(r["costs"] == Costs.named(MEASURED).to_dict() for r in measured["results"])
    # The profile is charged: the same buy-and-hold benchmark costs 3 bps a side less at the measured profile.
    assert measured["benchmark"]["total_return"] > gate["benchmark"]["total_return"]
    # The measured profile is never charged to a market it was not measured on (the study stops); the altcoin profile is.
    with pytest.raises(ValueError, match="measured on BTC-USDT, ETH-USDT only, not on SOL-USDT"):
        v1c.run_series(dict(vars(v1c.parse_args(common + ["--cost-profile", MEASURED]))), "SOL-USDT", "4H")
    sol = v1c.run_series(dict(vars(v1c.parse_args(common + ["--cost-profile", "altcoin"]))), "SOL-USDT", "4H")
    assert sol["results"] and all(r["costs"]["profile"] == "altcoin" for r in sol["results"])


def test_a_run_at_another_profile_never_overwrites_sprint_2c_stored_files(v1c, tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):  # if the guard ever failed, the run stops here, before anything could be written
        raise AssertionError("the guard let a non-gate run reach the research")

    monkeypatch.setattr(v1c, "run_series", boom)
    monkeypatch.setattr(v1c, "render_report_v1c", boom)
    assert v1c.main(["--cost-profile", MEASURED]) == 2  # every default: Sprint 2c's results, its report and the paper fleet's shortlist
    err = capsys.readouterr().err
    assert "would overwrite Sprint 2c's stored gate-cost files" in err and "--json" in err and "--shortlist" in err
    own = ["--report", str(tmp_path / "r.md"), "--json", str(tmp_path / "r.json")]
    assert v1c.main(["--cost-profile", MEASURED] + own) == 2 and "--shortlist" in capsys.readouterr().err  # the shortlist default alone is enough
    assert v1c.main(["--slippage", "0.0003"] + own) == 2  # hand-given numbers are another profile too
    # With its own three paths a measured run passes the guard (and would run; not here), and a gate run writes its defaults as it always did.
    mine = v1c.parse_args(["--cost-profile", MEASURED, "--shortlist", str(tmp_path / "s.json")] + own)
    assert v1c._stored_outputs_hit(mine, mine.cost_profile) == []
    assert v1c._stored_outputs_hit(v1c.parse_args([]), "gate") == []
    assert v1c._stored_outputs_hit(v1c.parse_args([]), MEASURED) == ["--report", "--json", "--shortlist"]
    # Re-rendering a results file taken at another profile onto the stored paths is refused as well.
    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps({"meta": {"cost_profile": MEASURED, "fee_rate": 0.001, "slippage_rate": 0.0002}, "results": []}), encoding="utf-8")
    assert v1c.main(["--render-from-json", str(saved)]) == 2
    older = tmp_path / "older.json"  # a results file written before the profiles: named from its numbers
    older.write_text(json.dumps({"meta": {"fee_rate": 0.001, "slippage_rate": 0.0015}, "results": []}), encoding="utf-8")
    assert v1c.main(["--render-from-json", str(older)]) == 2
    unnamed = tmp_path / "unnamed.json"  # a profile record that names no profile is refused, never read as the gate profile
    unnamed.write_text(json.dumps({"meta": {"cost_profile": {"BTC-USDT": cost_profile_record(MEASURED)}, "fee_rate": 0.001, "slippage_rate": 0.0005},
                                   "results": []}), encoding="utf-8")
    assert v1c.main(["--render-from-json", str(unnamed)]) == 2


# -- pre-registration and the protocol checks ------------------------------------------------------------------------------

def test_a_preregistration_names_its_profile_with_the_numbers_and_one_that_names_none_is_the_gate_profile():
    record = cost_profile_record(MEASURED)
    assert record == {"name": MEASURED, "fee_rate": 0.001, "slippage_rate": 0.0002, "round_trip": pytest.approx(0.0024, abs=1e-15),
                      "note": COST_PROFILE_NOTES[MEASURED]}
    assert preregistered_cost_profile({"cost_profile": record}) == MEASURED and preregistered_cost_profile({"cost_profile": cost_profile_record("gate")}) == "gate"
    assert preregistered_cost_profile(None) == "gate" and preregistered_cost_profile({}) == "gate"
    # Every study finished by 2026-11-05 named no profile: they ran the gate profile, and nothing about them changes.
    for name in ("replication_v1d", "research_round_1", "research_round_2", "trader_policy_v1", "research_round_3", "breadth_v1"):
        committed = json.loads((RESEARCH_DOCS / f"{name}_preregistration.json").read_text(encoding="utf-8"))
        assert "cost_profile" not in committed and preregistered_cost_profile(committed) == "gate", name
    with pytest.raises(ReplicationError, match="without its numbers"):
        preregistered_cost_profile({"cost_profile": MEASURED})
    with pytest.raises(ReplicationError, match="a registered profile never changes"):
        preregistered_cost_profile({"cost_profile": dict(record, slippage_rate=0.0001)})
    with pytest.raises(ValueError, match="unknown cost profile"):
        preregistered_cost_profile({"cost_profile": dict(record, name="measured_btc_eth_2027_01")})


def test_the_shared_explanation_rule(v1c, stored_meta):
    narrow = {"strategies": ["S1"], "regime_modes": ["none"], "timeframes": ["6H"]}
    measured = dict(vars(v1c.parse_args(["--cost-profile", MEASURED])), **narrow)
    check = protocol_check(measured, stored_meta)
    assert check["mismatches"] == {"slippage": {"got": 0.0002, "stored": 0.0005}}
    assert explain_cost_mismatches(check, measured, None) == {} and explain_cost_mismatches(check, measured, "gate") == {}
    assert list(explain_cost_mismatches(check, measured, MEASURED)) == ["slippage"]
    assert "pre-registered cost profile" in explain_cost_mismatches(check, measured, MEASURED)["slippage"]
    assert explain_cost_mismatches(check, measured, "altcoin") == {}  # the job did not charge the profile registered
    hand = dict(vars(v1c.parse_args(["--slippage", "0.0003"])), **narrow)
    assert explain_cost_mismatches(protocol_check(hand, stored_meta), hand, MEASURED) == {}
    unnamed = {k: v for k, v in measured.items() if k != "cost_profile"}  # arguments that do not say what they charged explain nothing
    assert explain_cost_mismatches(check, unnamed, MEASURED) == {}
    with pytest.raises(ValueError, match="unknown cost profile"):
        explain_cost_mismatches(check, measured, "cheap")


def _study_checks(stored_meta):
    """The protocol check of each of the three studies on one of its own jobs: (argv of the job, check(args, profile))."""
    tp_cell, tp_run = trader_policy_study.Cell("trader", True), trader_policy_study.BY_KEY["C1"]
    return {
        "R18a Trader Policy": (trader_policy_study.cell_argv(tp_cell, tp_run, evaluate_holdout=False, lake_dir=None, quick=False),
                               lambda args, profile: trader_policy_study.protocol_check_cell(args, stored_meta, tp_cell, tp_run, cost_profile=profile)),
        "R19 round 3": (round3.job_argv(round3.JUDGED_CELL, "fixed", ["S8"], "6H", modes=("none",), evaluate_holdout=False, lake_dir=None, quick=False),
                        lambda args, profile: round3.protocol_check_job(args, stored_meta, round3.JUDGED_CELL, "fixed", "6H", cost_profile=profile)),
        "R20 breadth": (breadth_study.job_argv(breadth_study.JUDGED_CELL, ["hold", "S1"], evaluate_holdout=False, lake_dir=None, quick=False),
                        lambda args, profile: breadth_study.protocol_check_job(args, stored_meta, breadth_study.JUDGED_CELL, cost_profile=profile)),
    }


def test_the_three_studies_explain_fee_and_slippage_only_when_the_preregistration_names_the_profile(v1c, stored_meta):
    for study, (argv, check) in _study_checks(stored_meta).items():
        gate = dict(vars(v1c.parse_args(argv)))
        measured = dict(vars(v1c.parse_args(argv + ["--cost-profile", MEASURED])))
        altcoin = dict(vars(v1c.parse_args(argv + ["--cost-profile", "altcoin"])))
        hand = dict(vars(v1c.parse_args(argv + ["--slippage", "0.0003"])))
        # As the three studies were registered (no profile): the gate job has no cost difference, a measured job is STOPPED on its slippage.
        g = check(gate, None)
        assert g["ok_for_cell"] and not {"fee", "slippage"} & set(g["mismatches"]) and g["cost_profile"] == "gate", study
        stopped = check(measured, None)
        assert not stopped["ok_for_cell"] and set(stopped["unexplained_mismatches"]) == {"slippage"}, study
        assert "slippage" not in stopped["expected_mismatches"] and stopped["mismatches"]["slippage"] == {"got": 0.0002, "stored": 0.0005}, study
        assert not check(measured, "gate")["ok_for_cell"], study  # naming the gate profile is naming none
        # A pre-registered measured profile explains the measured job's slippage and nothing else.
        ok = check(measured, MEASURED)
        assert ok["ok_for_cell"] and ok["unexplained_mismatches"] == {} and ok["cost_profile"] == MEASURED, study
        assert MEASURED in ok["expected_mismatches"]["slippage"] and set(ok["expected_mismatches"]) - {"slippage"} == set(g["expected_mismatches"]), study
        # The gate job of a measured study (the reproduction of the stored numbers) has nothing to explain.
        repro = check(gate, MEASURED)
        assert repro["ok_for_cell"] and "slippage" not in repro["expected_mismatches"], study
        # A job at another profile than the registered one, or at hand-given numbers, stays unexplained: the study stops.
        assert not check(altcoin, MEASURED)["ok_for_cell"] and "slippage" in check(altcoin, MEASURED)["unexplained_mismatches"], study
        assert not check(hand, MEASURED)["ok_for_cell"], study
        with pytest.raises(ValueError, match="unknown cost profile"):
            check(measured, "measured")


def test_one_profile_flows_from_the_preregistration_through_the_runner_into_meta_and_the_protocol_check(v1c, stored_meta):
    """A study pre-registered after 2026-11-05 on BTC-USDT: the pre-registration records the profile, the job's command line charges it,
    the results meta and every result record it, and the study's protocol check explains the slippage because the pre-registration
    named it; the same study's reproduction job runs at the gate profile."""
    prereg = {"preregistration": {"question": "a future BTC-USDT study"}, "cost_profile": cost_profile_record(MEASURED)}
    profile = preregistered_cost_profile(json.loads(json.dumps(prereg)))  # as read back from the written file
    assert profile == MEASURED
    argv, check = _study_checks(stored_meta)["R20 breadth"]
    judged = v1c.parse_args(argv + ["--cost-profile", profile])
    reproduction = v1c.parse_args(argv)  # the reproduction of the stored numbers: the gate profile
    assert v1c._cost_meta(judged) == {"cost_profile": MEASURED, "fee_rate": prereg["cost_profile"]["fee_rate"],
                                      "slippage_rate": prereg["cost_profile"]["slippage_rate"], "round_trip": pytest.approx(0.0024, abs=1e-15)}
    assert v1c._costs(judged).to_dict()["profile"] == MEASURED and v1c._cost_meta(reproduction)["cost_profile"] == "gate"
    assert check(dict(vars(judged)), profile)["ok_for_cell"] and check(dict(vars(reproduction)), profile)["ok_for_cell"]
    assert not check(dict(vars(judged)), preregistered_cost_profile({}))["ok_for_cell"]  # the same job under a registration that named none


def test_the_reproduction_runs_at_the_stored_runs_cost_profile():
    stored = [{"candidate": "S1", "instrument": "BTC-USDT", "timeframe": "4H", "regime": {"mode": "none"}, "selected_params": {"bracket": "none"},
               "oos": {"total_return": 0.123457, "cagr": 0.02, "sharpe": 0.5, "max_drawdown": 0.1, "calmar": 0.2, "profit_factor": 1.3, "n_trades": 50},
               "acceptance": {"passed": False}}]
    before = json.loads(json.dumps(stored[0]))  # a result without a costs record (written before the profiles): the gate profile
    at_gate = dict(before, costs=Costs.named("gate").to_dict())
    at_measured = dict(before, costs=Costs.named(MEASURED).to_dict())
    assert cost_profile_of(before) == "gate" and cost_profile_of(at_measured) == MEASURED
    for ok in (before, at_gate):
        row = reproduction_check({"results": [ok]}, stored)[0]
        assert row["ok"] and row["cost_profile"] == "gate"
    row = reproduction_check({"results": [at_measured]}, stored)[0]
    assert not row["ok"] and row["cost_profile"] == MEASURED and "the stored run's cost profile ('gate')" in row["note"]
    # A stored result at the measured profile would be reproduced only at the measured profile.
    stored_measured = [dict(stored[0], costs=Costs.named(MEASURED).to_dict())]
    assert reproduction_check({"results": [at_measured]}, stored_measured)[0]["ok"]
    assert not reproduction_check({"results": [at_gate]}, stored_measured)[0]["ok"]


# -- the paper fleet keeps refusing a record at another cost --------------------------------------------------------------

def _copy(tmp_path: Path, filename: str, edit, name: str) -> Path:
    doc = json.loads((RESEARCH_DOCS / filename).read_text(encoding="utf-8"))
    edit(doc)
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _edit_result(doc, candidate: str, instrument: str, cell, change) -> None:
    pool = doc["results"] if isinstance(doc.get("results"), list) else [r for s in doc["series"] for r in s["results"]]
    found = [r for r in pool if r["candidate"] == candidate and r["instrument"] == instrument and (cell is None or r["cell"]["key"] == cell)]
    assert found, (candidate, instrument, cell)
    for r in found:
        change(r)


def test_the_paper_fleet_keeps_refusing_a_record_at_another_cost_profile(tmp_path):
    from research.paper_fleet.config import COSTS, DEFAULT_RESULTS, DEFAULT_SHORTLIST, load_manifest

    assert COSTS == Costs.named("gate") and COSTS.profile == "gate"  # the fleet charges the gate profile
    untouched = load_manifest()
    assert len(untouched.accounts) == 33

    def shortlist(edit, name="sl.json"):
        doc = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))
        edit(doc)
        path = tmp_path / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def explained_slippage(r):  # what a study pre-registered at the measured profile would record for that cell
        r["protocol_check"]["mismatches"]["slippage"] = {"got": 0.0002, "stored": 0.0005}
        r["protocol_check"]["expected_mismatches"]["slippage"] = "the pre-registered cost profile (measured_btc_eth_2026_11: ...)"
        r["protocol_check"]["cost_profile"] = MEASURED

    def checked_slippage(r):  # a protocol check on a row the tier path never sees (a replication-study row has no cell)
        r["protocol_check"] = {"ok": False, "ok_for_cell": True, "mismatches": {"slippage": {"got": 0.0002, "stored": 0.0005}},
                               "expected_mismatches": {"slippage": "the pre-registered cost profile"}, "unexplained_mismatches": {}}

    tp = "trader_policy_v1_results.json"
    probes = [
        # c15 (configurations[14]): the Trader Policy study's record of S1+S5 SOL-USDT 6H at the Trader cell, with an EXPLAINED slippage:
        # the tier path's own allow-list refuses it first, as it did before plan row R24 ...
        (14, _copy(tmp_path, tp, lambda d: _edit_result(d, "S1+S5", "SOL-USDT", "trader|brakes|none", explained_slippage), "tp1.json"),
         "does not accept \\(\\['slippage'\\]\\)"),
        # ... and the explicit cost guard refuses what no allow-list sees: the record's own costs at the measured profile,
        (14, _copy(tmp_path, tp, lambda d: _edit_result(d, "S1+S5", "SOL-USDT", "trader|brakes|none",
                                                       lambda r: r.update(costs=Costs.named(MEASURED).to_dict())), "tp2.json"), "taken at the cost profile"),
        # ... a protocol check that names the measured profile without any recorded difference,
        (14, _copy(tmp_path, tp, lambda d: _edit_result(d, "S1+S5", "SOL-USDT", "trader|brakes|none",
                                                       lambda r: r["protocol_check"].update(cost_profile=MEASURED)), "tp3.json"), "records another cost"),
        # c11 (configurations[10]): a replication-study row (no tier, no cell) whose study meta names another profile,
        (10, _copy(tmp_path, "replication_v1d_results.json", lambda d: d["meta"].update(cost_profile=cost_profile_record("altcoin")), "r12a.json"),
         "ran at the cost profile 'altcoin'"),
        # ... whose own result carries a costs record at hand-given numbers,
        (10, _copy(tmp_path, "replication_v1d_results.json", lambda d: _edit_result(d, "S1+S5", "SOL-USDT", None,
                                                                                 lambda r: r.update(costs=Costs(0.001, 0.0003).to_dict())), "r12b.json"),
         "taken at the cost profile 'custom'"),
        # ... or whose result's protocol check recorded a slippage difference, explained or not.
        (10, _copy(tmp_path, "replication_v1d_results.json", lambda d: _edit_result(d, "S1+S5", "SOL-USDT", None, checked_slippage), "r12c.json"),
         "records another cost \\(\\['slippage'\\]\\)"),
    ]
    for index, results, message in probes:
        with pytest.raises(ValueError, match=message):
            load_manifest(shortlist(lambda d, i=index, p=results: d["configurations"][i]["source"].update(results=str(p))), DEFAULT_RESULTS)
    # Sprint 2c's own results file re-run at another cost (its meta) is refused before any account is built.
    rerun = _copy(tmp_path, "ensemble_v1c_results.json", lambda d: d["meta"].update(slippage_rate=0.0002), "v1c_measured.json")
    with pytest.raises(ValueError, match="charged slippage_rate 0.0002"):
        load_manifest(DEFAULT_SHORTLIST, rerun)
    named = _copy(tmp_path, "ensemble_v1c_results.json", lambda d: d["meta"].update(cost_profile=MEASURED), "v1c_named.json")
    with pytest.raises(ValueError, match="ran at the cost profile 'measured_btc_eth_2026_11'"):
        load_manifest(DEFAULT_SHORTLIST, named)
    by_market = _copy(tmp_path, "ensemble_v1c_results.json", lambda d: d["meta"].update(cost_profile={"BTC-USDT": cost_profile_record("gate")}),
                      "v1c_by_market.json")
    with pytest.raises(ValueError, match="ran at the cost profile None"):  # a record that names no profile is refused, never read as gate
        load_manifest(DEFAULT_SHORTLIST, by_market)
    gate_named = _copy(tmp_path, "ensemble_v1c_results.json", lambda d: d["meta"].update(cost_profile=cost_profile_record("gate")), "v1c_gate.json")
    assert load_manifest(DEFAULT_SHORTLIST, gate_named).fingerprint() == untouched.fingerprint()
    # A gate-profile record (a costs record and a protocol check naming the gate profile, as a re-run would write) is accepted unchanged.
    gate_tp = _copy(tmp_path, tp, lambda d: _edit_result(d, "S1+S5", "SOL-USDT", "trader|brakes|none",
                                                       lambda r: (r.update(costs=Costs.named("gate").to_dict()), r["protocol_check"].update(cost_profile="gate"))),
                    "tp_gate.json")
    accepted = load_manifest(shortlist(lambda d: d["configurations"][14]["source"].update(results=str(gate_tp)), "sl_gate.json"), DEFAULT_RESULTS)
    assert len(accepted.accounts) == 33 and accepted.fingerprint() == untouched.fingerprint()
