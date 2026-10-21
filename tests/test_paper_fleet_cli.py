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
