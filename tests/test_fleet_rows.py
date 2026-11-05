"""research/fleet_rows.py and scripts/apply_fleet_rows.py (plan row R23): owner-decided shortlist rows built from a study's own record,
applied under the R12 rule (the file is restored when the fleet cannot load it), and the committed spec reproducing the committed rows."""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import json
from pathlib import Path

import pytest

from research import fleet_rows as fr
from research.paper_fleet.config import DEFAULT_SHORTLIST, load_manifest

ROOT = Path(__file__).resolve().parents[1]
R23_ADDED = ["c20-s1-btc-6h-none-trader", "ctl-s8-btc-6h-trader"]
R23_PRESENT = ["S8 BTC-USDT 6H [none] @ trader (control)", "S1 BTC-USDT 6H [none] @ trader"]


@pytest.fixture(scope="module")
def spec():
    return fr.load_spec(fr.DEFAULT_SPEC)


@pytest.fixture(scope="module")
def rows(spec):
    return fr.build_rows(spec)


@pytest.fixture(scope="module")
def cli():
    spec = importlib.util.spec_from_file_location("apply_fleet_rows", ROOT / "scripts" / "apply_fleet_rows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _without_r23(doc):
    """The committed shortlist as it was before plan row R23: its two rows and its amendment removed."""
    doc = copy.deepcopy(doc)
    doc["configurations"] = [c for c in doc["configurations"] if (c.get("source") or {}).get("study") != "R20 breadth v1"]
    doc["controls"] = [c for c in doc["controls"] if c["candidate"] != "S8"]
    doc["amendments"] = [a for a in doc["amendments"] if "plan row R23" not in a["note"]]
    return doc


def _write(path: Path, doc) -> str:
    text = json.dumps(doc, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def test_the_committed_spec_reproduces_the_two_committed_rows(spec, rows):
    assert spec["plan_row"] == "R23" and [r.role for r in spec["requests"]] == ["control", "candidate"] and len(spec["not_added"]) == 1
    assert spec["not_added"][0]["candidate"] == "S1+VC" and spec["not_added"][0]["instrument"] == "SOL-USDT"
    shortlist = json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8"))
    s8 = next(c for c in shortlist["controls"] if c["candidate"] == "S8")
    c20 = next(c for c in shortlist["configurations"] if c["rank"] == 20)
    assert rows[0] == s8 and rows[1] == {k: v for k, v in c20.items() if k != "rank"}
    assert rows[0]["source"]["role"] == "control" and rows[0]["control_label"].startswith("slow breakout S8") and rows[0]["holdout"] is None
    assert rows[0]["holdout_confirmed"] is None and rows[0]["source"]["tier"] == "trader" and rows[0]["source"]["cell"] == "trader|brakes|none"
    assert rows[0]["source"]["brakes"]["hard_stop_dd"] == 0.3 and rows[0]["source"]["protocol_variant"].startswith("fixed rule")
    assert rows[0]["passed"] is False and rows[0]["failed_gates"] == ["calmar_gt_0_5", "enough_trades"] and rows[0]["n_trades"] == 17
    assert rows[0]["sizing"] == "vt20/30 crash15/90dh cap2 turtle" and rows[0]["sizing_config"]["risk_cap"] == 0.02 and rows[0]["source"]["hypothesis"] == "H8"
    assert rows[0]["params"] == {"entry_days": 55, "exit_days": 20, "atr_window": 14, "atr_mult": 5.0, "bracket": "none"} and rows[0]["calmar"] == pytest.approx(0.443397)
    assert rows[1]["source"]["study"] == "R20 breadth v1" and rows[1]["source"]["results"] == "docs/research/breadth_v1_results.json"
    assert rows[1]["source"]["role"] == "candidate" and rows[1]["source"]["protocol_variant"] is None and "control_label" not in rows[1]
    assert rows[1]["passed"] is True and rows[1]["failed_gates"] == [] and rows[1]["holdout_confirmed"] is True and rows[1]["holdout"]["n_trades"] == 32
    assert rows[1]["holdout"]["total_return"] == pytest.approx(0.038343) and rows[1]["calmar"] == pytest.approx(0.606091)
    assert "no fleet ticket" in rows[1]["source"]["note"] and "2026-11-05" in rows[1]["source"]["decided"] and rows[1]["source"]["generated_at"]
    amendment = shortlist["amendments"][-1]
    assert amendment["note"] == spec["amendment_note"] and amendment["added"] == ["S8 BTC-USDT 6H [none] (control)", "S1 BTC-USDT 6H [none] @ trader"]
    assert fr.rows_present(shortlist, rows) == R23_PRESENT


def test_row_building_refuses_a_wrong_cell_an_unclean_record_a_bad_request_and_an_unknown_run(spec):
    req = spec["requests"][0]
    doc = fr.load_results(req.results)
    result = fr.find_result(doc, req)
    with pytest.raises(fr.FleetRowError, match="cell"):
        fr.row_from_result(result, dataclasses.replace(req, cell="reference|nobrakes|none"))
    dirty = copy.deepcopy(dict(result))
    dirty["protocol_check"]["unexplained_mismatches"] = {"fee": {"got": 0.002, "stored": 0.001}}
    with pytest.raises(fr.FleetRowError, match="not clean"):
        fr.row_from_result(dirty, req)
    with pytest.raises(ValueError, match="expected one research result"):
        fr.find_result(doc, dataclasses.replace(req, candidate="S4"))  # round 3 never ran S4
    with pytest.raises(fr.FleetRowError, match="control_label"):
        dataclasses.replace(req, control_label=None)
    with pytest.raises(fr.FleetRowError, match="role"):
        dataclasses.replace(req, role="portfolio")
    with pytest.raises(fr.FleetRowError, match="unknown keys"):
        fr.RowRequest.from_dict({**spec["rows"][1], "tier": "trader"})
    with pytest.raises(fr.FleetRowError, match="lacks"):
        fr.RowRequest.from_dict({k: v for k, v in spec["rows"][1].items() if k != "cell"})
    with pytest.raises(fr.FleetRowError, match="did not run"):
        fr.load_results.__wrapped__(req.results) if hasattr(fr.load_results, "__wrapped__") else _refused_study(req.results)


def _refused_study(rel: str):
    """A study whose top-level protocol check failed is refused before any row is built (the fleet loader refuses it the same way)."""
    doc = {"meta": {"protocol_check": {"ok": False, "mismatches": {"fee": 1}}}, "results": []}
    path = Path(fr.ROOT) / "logs" / "_test_refused_study.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
        fr.load_results(str(path))
    finally:
        if path.exists():
            path.unlink()


def test_apply_rows_follows_the_r12_rule_and_never_adds_twice(tmp_path, rows):
    before = _without_r23(json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8")))
    path = tmp_path / "shortlist.json"
    original = _write(path, before)
    assert len(load_manifest(path).accounts) == 31 and fr.rows_present(before, rows) == []
    ok, message, added = fr.apply_rows(path, rows, note="test", check_only=True)
    assert ok and added == R23_ADDED and "nothing was written" in message and path.read_text(encoding="utf-8") == original
    ok, message, added = fr.apply_rows(path, rows, note="test")
    assert ok and added == R23_ADDED and message.startswith("applied") and "33 fleet accounts" in message
    after = json.loads(path.read_text(encoding="utf-8"))
    assert len(after["configurations"]) == 20 and len(after["controls"]) == 11 and after["amendments"][-1]["note"] == "test"
    assert after["configurations"][19]["rank"] == 20 and "rank" not in after["controls"][10] and after["configurations"][:19] == before["configurations"]
    assert len(load_manifest(path).accounts) == 33 and fr.rows_present(after, rows) == R23_PRESENT
    # A row the fleet cannot reconcile (its results file is missing) rolls the whole amendment back: the file is byte for byte what it was.
    original = _write(path, before)
    broken = copy.deepcopy(rows)
    broken[1]["source"]["results"] = "docs/research/does_not_exist.json"
    ok, message, added = fr.apply_rows(path, broken, note="test")
    assert not ok and message.startswith("NOT applied") and added == [] and path.read_text(encoding="utf-8") == original
    ok, message, added = fr.apply_rows(path, broken, note="test", check_only=True)
    assert not ok and "nothing was written" in message and added == [] and path.read_text(encoding="utf-8") == original


def test_the_command_line_checks_applies_once_and_refuses_what_it_cannot_build_or_load(cli, tmp_path, capsys, spec):
    before = _without_r23(json.loads(DEFAULT_SHORTLIST.read_text(encoding="utf-8")))
    path = tmp_path / "shortlist.json"
    original = _write(path, before)
    assert cli.main(["--check", "--shortlist", str(path)]) == 0
    out = capsys.readouterr().out
    assert "R23: 2 row(s) built" in out and "check only: the fleet would load 33 accounts, adding c20-s1-btc-6h-none-trader, ctl-s8-btc-6h-trader" in out
    assert "S8 BTC-USDT 6H [none] @ trader|brakes|none (control) from R19 research round 3" in out and "no holdout (a control is never judged)" in out
    assert "holdout 0.038343 (32 trades, confirmed)" in out and path.read_text(encoding="utf-8") == original
    assert cli.main(["--shortlist", str(path), "--json"]) == 0
    out = capsys.readouterr().out
    assert "applied:" in out and "33 fleet accounts" in out and '"control_label"' in out
    assert cli.main(["--shortlist", str(path)]) == 0 and "nothing to add" in capsys.readouterr().out
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert [a["note"] for a in doc["amendments"]].count(spec["amendment_note"]) == 1 and len(load_manifest(path).accounts) == 33
    # A bad spec, a missing shortlist and a missing study are refused with exit 2 before anything is written.
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"plan_row": "X"}), encoding="utf-8")
    assert cli.main(["--spec", str(bad), "--shortlist", str(path)]) == 2 and "lacks" in capsys.readouterr().err
    assert cli.main(["--shortlist", str(tmp_path / "nope.json")]) == 2 and "cannot read" in capsys.readouterr().err
    no_study = copy.deepcopy(spec)
    no_study.pop("requests")
    no_study["rows"][0]["results"] = "docs/research/does_not_exist.json"
    bad.write_text(json.dumps(no_study), encoding="utf-8")
    assert cli.main(["--spec", str(bad), "--shortlist", str(path)]) == 2 and "refused" in capsys.readouterr().err
    # A record the fleet loader cannot reconcile (the study copy says the cell is another tier than its sizing describes): exit 1, file restored.
    study = json.loads((ROOT / "docs" / "research" / "breadth_v1_results.json").read_text(encoding="utf-8"))
    for r in study["results"]:
        if r["candidate"] == "S1" and r["instrument"] == "BTC-USDT" and r["timeframe"] == "6H" and r["cell"]["key"] == "trader|brakes|none":
            r["cell"]["tier"] = "aggressive"
    copy_path = tmp_path / "breadth_copy.json"
    copy_path.write_text(json.dumps(study), encoding="utf-8")
    other = copy.deepcopy(spec)
    other.pop("requests")
    other["rows"] = [dict(other["rows"][1], results=str(copy_path))]
    bad.write_text(json.dumps(other), encoding="utf-8")
    original = _write(path, before)
    assert cli.main(["--spec", str(bad), "--shortlist", str(path)]) == 1
    assert "NOT applied" in capsys.readouterr().out and path.read_text(encoding="utf-8") == original
    assert cli.main(["--spec", str(bad), "--shortlist", str(path), "--check"]) == 1 and path.read_text(encoding="utf-8") == original
