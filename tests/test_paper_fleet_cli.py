"""scripts/run_paper_fleet.py: options, the offline dry run end to end, --status, --report, setup errors exit 2."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from research.paper_fleet.config import FleetManifest, load_manifest
from research.paper_fleet.runner import FleetSettings

ROOT = Path(__file__).resolve().parents[1]
LIGHT = ("c01-s1s5-btc-6h-none", "ctl-hold-btc-4h", "ctl-bh-eth-6h")


@pytest.fixture(scope="module")
def cli():
    spec = importlib.util.spec_from_file_location("run_paper_fleet", ROOT / "scripts" / "run_paper_fleet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_options_are_validated(cli):
    with pytest.raises(SystemExit):
        cli.parse_args([])
    with pytest.raises(SystemExit):
        cli.parse_args(["--loop", "--dry-run"])
    with pytest.raises(SystemExit):
        cli.parse_args(["--once", "--days", "5"])
    with pytest.raises(SystemExit):
        cli.parse_args(["--loop", "--interval", "2"])
    with pytest.raises(SystemExit):
        cli.parse_args(["--report", "week-43"])
    args = cli.parse_args(["--report", "2026-W43"])
    assert args.report == "2026-W43"
    assert cli.parse_args(["--loop"]).positioning_source == "okx"


def test_status_without_a_fleet(cli, tmp_path, capsys):
    assert cli.main(["--status", "--fleet-dir", str(tmp_path)], env={}) == 0
    assert "no fleet" in capsys.readouterr().out
    assert cli.main(["--report", "--fleet-dir", str(tmp_path)], env={}) == 2


def test_dry_run_end_to_end_offline_then_status_and_report(cli, tmp_path, capsys, monkeypatch):
    full = load_manifest()
    light = FleetManifest(accounts=tuple(a for a in full.accounts if a.account_id in LIGHT), sources=full.sources)
    monkeypatch.setattr(cli, "load_manifest", lambda *a, **k: light)  # the CLI wiring, not the whole fleet's runtime
    monkeypatch.setattr(cli, "DRY_RUN_SETTINGS", FleetSettings(window_days=90.0, history_days=400.0))
    out = tmp_path / "dry"
    code = cli.main(["--dry-run", "--synthetic", "--days", "1.5", "--out", str(out), "--json"], env={})
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and payload["ok"], payload["checks"]
    assert payload["source"].startswith("synthetic") and payload["requests_served_offline"] > 0
    assert len(payload["accounts"]) == len(LIGHT) and payload["reports"]
    assert all(s["bars"] > 0 for aid, s in payload["accounts"].items() if not aid.startswith("pf-"))
    assert cli.main(["--status", "--fleet-dir", str(out)], env={}) == 0
    status = capsys.readouterr().out
    assert "c01-s1s5-btc-6h-none" in status and "ctl-bh-eth-6h" in status
    assert cli.main(["--report", "--fleet-dir", str(out)], env={}) == 0
    assert "report:" in capsys.readouterr().out
    # A dry run never reuses a directory that already holds something.
    assert cli.main(["--dry-run", "--synthetic", "--days", "1", "--out", str(out)], env={}) == 2


def test_a_second_instance_exits_3_so_the_service_retries(cli, tmp_path, capsys, monkeypatch):
    from research.paper_fleet.store import FleetLock

    monkeypatch.setattr(FleetLock, "acquire", lambda self: False)
    assert cli.main(["--once", "--fleet-dir", str(tmp_path)], env={}) == 3
    assert "another instance" in capsys.readouterr().err


def test_run_as_a_script_it_never_loads_the_repository_env(tmp_path):
    """python-dotenv is kept out of the process, so app.config's load_dotenv() cannot put .env secrets into it."""
    script = ROOT / "scripts" / "run_paper_fleet.py"
    code = chr(10).join([
        "import runpy, sys",
        f"sys.argv = ['run_paper_fleet.py', '--status', '--fleet-dir', {str(tmp_path)!r}]",
        "try:",
        f"    runpy.run_path({str(script)!r}, run_name='__main__')",
        "except SystemExit as exc:",
        "    assert exc.code == 0, exc.code",
        "import app.config",
        "print('DOTENV', sys.modules.get('dotenv', 'absent'))",
    ])
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr
    assert "DOTENV None" in out.stdout and "no fleet" in out.stdout


def test_status_says_plainly_when_an_s5_account_runs_without_positioning_data(cli, tmp_path, capsys):
    """Plan row R17: the status line reads the labels the runner stores in the state (no journal, no network)."""
    from research.paper_fleet.store import FleetPaths, write_state

    paths = FleetPaths(tmp_path)
    paths.ensure()
    accounts = [{"account_id": "c11-s1s5-sol-6h-none", "role": "candidate", "kind": "sleeve", "label": "S1+S5 SOL-USDT 6H"},
                {"account_id": "c01-s1s5-btc-6h-none", "role": "candidate", "kind": "sleeve", "label": "S1+S5 BTC-USDT 6H"},
                {"account_id": "c12-s1-sol-6h-none", "role": "candidate", "kind": "sleeve", "label": "S1 SOL-USDT 6H"}]
    engine = {"equity": 10_000.0, "in_pos": False, "alloc": 0.0, "last_bar_time": "2026-11-04T18:00:00Z", "trades_closed": 0, "fees_paid": 0.0, "lad_level": 0}
    note = "S5 running without data: the filter passes (funding missing, open interest missing)"
    state = {"version": 2, "created_at": "2026-11-04T14:55:15Z", "last_cycle": "2026-11-05T01:44:56Z", "cycles": 643, "fingerprint": "f",
             "positioning_source": "okx", "manifest": {"init_cash": 10_000.0, "accounts": accounts}, "series": {}, "fits": {}, "portfolios": {},
             "accounts": {"c11-s1s5-sol-6h-none": {"seq": 2, "engine": engine, "created_at": "2026-11-04T22:59:50Z", "retired_at": None,
                                                   "positioning": {"source": "okx", "funding": "missing", "open_interest": "missing", "complete": False,
                                                                   "note": note, "bar": "2026-11-04T18:00:00Z"}},
                          "c01-s1s5-btc-6h-none": {"seq": 3, "engine": engine, "created_at": "2026-11-04T14:55:15Z", "retired_at": None,
                                                   "positioning": {"source": "okx", "funding": "current", "open_interest": "current", "complete": True,
                                                                   "note": "S5 data current", "bar": "2026-11-04T18:00:00Z"}},
                          "c12-s1-sol-6h-none": {"seq": 2, "engine": engine, "created_at": "2026-11-04T22:59:50Z", "retired_at": None}},
             "health": {"stale": False, "newest_candle": {"BTC-USDT": "2026-11-05T00:00:00Z", "SOL-USDT": "2026-11-05T00:00:00Z"}, "last_errors": [],
                        "positioning": {"source": "okx", "last_refresh": "2026-11-05T01:29:56Z", "last_errors": [],
                                        "markets": {"BTC-USDT": {"swap": "BTC-USDT-SWAP", "funding_newest": "2026-11-05T00:00:00Z",
                                                                 "open_interest_newest": "2026-11-05T01:00:00Z"},
                                                    "SOL-USDT": {"swap": "SOL-USDT-SWAP", "funding_newest": None, "open_interest_newest": None}}}}}
    write_state(paths.state_file, state)
    assert cli.main(["--status", "--fleet-dir", str(tmp_path)], env={}) == 0
    out = capsys.readouterr().out
    assert ("positioning data (S5 filter, source okx, last refresh 2026-11-05T01:29:56Z): BTC-USDT-SWAP funding 2026-11-05T00:00:00Z / open interest "
            "2026-11-05T01:00:00Z; SOL-USDT-SWAP funding missing / open interest missing") in out
    lines = out.splitlines()
    i = next(k for k, line in enumerate(lines) if line.strip().startswith("c11-s1s5-sol-6h-none"))
    assert lines[i + 1].strip() == f"{note} (bar 2026-11-04T18:00:00Z)"
    j = next(k for k, line in enumerate(lines) if line.strip().startswith("c01-s1s5-btc-6h-none"))
    assert lines[j + 1].strip() == "S5 data current (bar 2026-11-04T18:00:00Z)"
    k = next(k for k, line in enumerate(lines) if line.strip().startswith("c12-s1-sol-6h-none"))
    assert k == len(lines) - 1 or not lines[k + 1].strip().startswith("S5")  # plain S1: no label
    assert cli.main(["--status", "--fleet-dir", str(tmp_path), "--json"], env={}) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["accounts"]["c11-s1s5-sol-6h-none"]["positioning"]["complete"] is False and "positioning" not in payload["accounts"]["c12-s1-sol-6h-none"]
    # A state written before R17 (no labels, no feed summary) prints as before.
    for meta in state["accounts"].values():
        meta.pop("positioning", None)
    state["health"].pop("positioning")
    write_state(paths.state_file, state)
    assert cli.main(["--status", "--fleet-dir", str(tmp_path)], env={}) == 0
    before = capsys.readouterr().out
    assert "positioning data (S5 filter" not in before and "S5 running" not in before and "c11-s1s5-sol-6h-none" in before


def test_status_names_a_trader_tier_accounts_brakes(cli, tmp_path, capsys):
    """Plan row R18b: under a Trader-tier account the status prints what its brakes hold (from the state alone); a Reference account prints as before."""
    from research.paper_fleet.store import FleetPaths, write_state

    paths = FleetPaths(tmp_path)
    paths.ensure()
    accounts = [{"account_id": "c17-s1s5-btc-6h-none-trader", "role": "candidate", "kind": "sleeve", "label": "S1+S5 BTC-USDT 6H — trader tier", "tier": "trader"},
                {"account_id": "c01-s1s5-btc-6h-none", "role": "candidate", "kind": "sleeve", "label": "S1+S5 BTC-USDT 6H"}]
    base = {"equity": 9_700.0, "in_pos": False, "alloc": 0.0, "last_bar_time": "2026-11-20T18:00:00Z", "trades_closed": 3, "fees_paid": 12.0, "lad_level": 0}
    brakes = {"peak": 10_100.0, "lad_mult": 0.8, "halted": False, "bars_blocked": 2, "trips": {"hard_stop": 0, "daily_loss": 1, "weekly_loss": 0, "monthly_loss": 0}}
    state = {"version": 2, "created_at": "2026-11-06T00:00:00Z", "last_cycle": "2026-11-21T00:00:56Z", "cycles": 100, "fingerprint": "f", "positioning_source": "okx",
             "manifest": {"init_cash": 10_000.0, "accounts": accounts}, "series": {}, "fits": {}, "portfolios": {},
             "accounts": {"c17-s1s5-btc-6h-none-trader": {"seq": 9, "engine": dict(base, brakes=brakes), "created_at": "2026-11-06T00:00:00Z", "retired_at": None},
                          "c01-s1s5-btc-6h-none": {"seq": 9, "engine": dict(base), "created_at": "2026-11-06T00:00:00Z", "retired_at": None}},
             "health": {"stale": False, "newest_candle": {"BTC-USDT": "2026-11-21T00:00:00Z"}, "last_errors": []}}
    write_state(paths.state_file, state)
    assert cli.main(["--status", "--fleet-dir", str(tmp_path)], env={}) == 0
    lines = capsys.readouterr().out.splitlines()
    i = next(k for k, line in enumerate(lines) if line.strip().startswith("c17-s1s5-btc-6h-none-trader"))
    assert lines[i + 1].strip() == "trader tier: Turtle multiplier 0.8, no hard stop, entries blocked so far 2, limits tripped daily_loss x1"
    j = next(k for k, line in enumerate(lines) if line.strip().startswith("c01-s1s5-btc-6h-none"))
    assert j == len(lines) - 1 or "tier:" not in lines[j + 1]
    state["accounts"]["c17-s1s5-btc-6h-none-trader"]["engine"]["brakes"].update(halted=True, trips={"hard_stop": 1})
    write_state(paths.state_file, state)
    assert cli.main(["--status", "--fleet-dir", str(tmp_path), "--json"], env={}) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["accounts"]["c17-s1s5-btc-6h-none-trader"]["brakes"] == {"turtle_multiplier": 0.8, "halted": True, "entries_blocked_so_far": 2, "trips": {"hard_stop": 1}}
    assert payload["accounts"]["c17-s1s5-btc-6h-none-trader"]["tier"] == "trader" and "brakes" not in payload["accounts"]["c01-s1s5-btc-6h-none"]
    assert cli.main(["--status", "--fleet-dir", str(tmp_path)], env={}) == 0
    assert "HALTED by the hard stop until its window restarts" in capsys.readouterr().out


def test_status_names_a_forward_controls_tier_and_brakes_too(cli, tmp_path, capsys):
    """Plan row R23: the S8 forward control runs at the Trader tier with the brakes, so --status prints its tier line like a candidate's."""
    from research.paper_fleet.store import FleetPaths, write_state

    paths = FleetPaths(tmp_path)
    paths.ensure()
    accounts = [{"account_id": "ctl-s8-btc-6h-trader", "role": "control", "kind": "sleeve", "label": "control: slow breakout S8 — trader tier", "tier": "trader"},
                {"account_id": "ctl-tf-btc-6h", "role": "control", "kind": "sleeve", "label": "control: long above the 200-day average", "tier": "reference"}]
    base = {"equity": 10_000.0, "in_pos": False, "alloc": 0.0, "last_bar_time": "2026-11-06T06:00:00Z", "trades_closed": 0, "fees_paid": 0.0, "lad_level": 0}
    brakes = {"peak": 10_000.0, "lad_mult": 1.0, "halted": False, "bars_blocked": 0, "trips": {"hard_stop": 0, "daily_loss": 0, "weekly_loss": 0, "monthly_loss": 0}}
    state = {"version": 2, "created_at": "2026-11-06T00:00:00Z", "last_cycle": "2026-11-06T06:00:56Z", "cycles": 7, "fingerprint": "f", "positioning_source": "okx",
             "manifest": {"init_cash": 10_000.0, "accounts": accounts}, "series": {}, "fits": {}, "portfolios": {},
             "accounts": {"ctl-s8-btc-6h-trader": {"seq": 3, "engine": dict(base, brakes=brakes), "created_at": "2026-11-06T00:00:00Z", "retired_at": None},
                          "ctl-tf-btc-6h": {"seq": 3, "engine": dict(base), "created_at": "2026-11-06T00:00:00Z", "retired_at": None}},
             "health": {"stale": False, "newest_candle": {"BTC-USDT": "2026-11-06T06:00:00Z"}, "last_errors": []}}
    write_state(paths.state_file, state)
    assert cli.main(["--status", "--fleet-dir", str(tmp_path)], env={}) == 0
    lines = capsys.readouterr().out.splitlines()
    i = next(k for k, line in enumerate(lines) if line.strip().startswith("ctl-s8-btc-6h-trader"))
    assert "equity 10,000.00  flat" in lines[i]
    assert lines[i + 1].strip() == "trader tier: Turtle multiplier 1.0, no hard stop, entries blocked so far 0, no limit tripped"
    j = next(k for k, line in enumerate(lines) if line.strip().startswith("ctl-tf-btc-6h"))
    assert j == len(lines) - 1 or "tier:" not in lines[j + 1]
    assert cli.main(["--status", "--fleet-dir", str(tmp_path), "--json"], env={}) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["accounts"]["ctl-s8-btc-6h-trader"]["role"] == "control" and payload["accounts"]["ctl-s8-btc-6h-trader"]["tier"] == "trader"
    assert payload["accounts"]["ctl-s8-btc-6h-trader"]["brakes"]["halted"] is False and "brakes" not in payload["accounts"]["ctl-tf-btc-6h"]
