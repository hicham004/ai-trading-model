"""``scripts/run_news_shadow.py``: modes, refusals and the live path on a fake network."""

from __future__ import annotations

import ast
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Tuple

import pytest
import requests

import app.news.fetch as fetch_module
import app.news.market as market_module
from app.news.shadow import RunnerLock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_news_shadow.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_news_shadow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cli = _load()


@pytest.fixture(autouse=True)
def restore_root_logging():
    """``main`` configures JSON logging on the (captured) stdout; put the root logger back after each test."""
    import logging

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def no_real_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the CLI test tried to reach the network")

    monkeypatch.setattr(requests, "request", refuse)
    monkeypatch.setattr(requests.Session, "request", refuse)


def test_dry_run_passes_and_prints_where_everything_went(tmp_path: Path, capsys, no_real_network):
    code = cli.main(["--dry-run", "--out", str(tmp_path / "out")], env={"ANTHROPIC_API_KEY": "ignored-in-dry-run"})
    out = capsys.readouterr().out
    assert code == 0
    assert "safety checks: all passed" in out and "MISMATCH" not in out and str(tmp_path / "out") in out
    assert (tmp_path / "out" / "report-2026-10-19.md").exists()


def test_dry_run_json_summary(tmp_path: Path, capsys, no_real_network):
    assert cli.main(["--dry-run", "--json", "--out", str(tmp_path / "o")], env={}) == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["ok"] and payload["headline"]["would_block"] == 1


def test_live_mode_refuses_cleanly_without_a_key(tmp_path: Path, capsys, no_real_network):
    for argv in (["--loop"], ["--once"]):
        code = cli.main(argv + ["--log-dir", str(tmp_path / "logs")], env={"ANTHROPIC_API_KEY": "  "})
        assert code == 2
        assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
    assert not (tmp_path / "logs").exists()  # refused before writing anything


def test_option_errors(capsys):
    for argv in ([], ["--fixtures", "x", "--once"], ["--out", "x", "--loop"], ["--loop", "--interval", "1"], ["--dry-run", "--once"]):
        with pytest.raises(SystemExit) as err:
            cli.parse_args(argv)
        assert err.value.code == 2


def test_bad_cap_in_the_environment_is_a_setup_error(tmp_path: Path, capsys, no_real_network):
    code = cli.main(["--once", "--no-model", "--log-dir", str(tmp_path)], env={"NEWS_SHADOW_MONTHLY_CAP_USD": "-5"})
    assert code == 2 and "NEWS_SHADOW_MONTHLY_CAP_USD" in capsys.readouterr().err


def test_a_second_instance_is_refused(tmp_path: Path, capsys, no_real_network):
    lock = RunnerLock(tmp_path / "logs" / "_state" / "runner.lock")
    assert lock.acquire()
    try:
        code = cli.main(["--once", "--no-model", "--log-dir", str(tmp_path / "logs")], env={})
    finally:
        lock.release()
    assert code == 2 and "another instance" in capsys.readouterr().err


def test_report_and_status_read_files_only(tmp_path: Path, capsys, no_real_network):
    out = tmp_path / "dry"
    assert cli.main(["--dry-run", "--out", str(out)], env={}) == 0
    written = (out / "report-2026-10-19.md").read_text(encoding="utf-8")
    (out / "report-2026-10-19.md").unlink()
    capsys.readouterr()
    assert cli.main(["--report", "2026-10-19", "--log-dir", str(out), "--journal-dir", str(out / "phase6a")], env={}) == 0
    assert (out / "report-2026-10-19.md").read_text(encoding="utf-8") == written  # reproducible from the logs
    assert cli.main(["--status", "--log-dir", str(out)], env={}) == 0
    status = capsys.readouterr().out
    assert "last cycle saved: 2026-10-19T13:20:00+00:00" in status and "ANTHROPIC_API_KEY in this environment: no" in status
    assert cli.main(["--status", "--json", "--log-dir", str(tmp_path / "empty")], env={}) == 0
    assert "no state yet" in json.loads(capsys.readouterr().out)["state"]


RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>t</title><link>https://www.sec.gov/</link><description>d</description>
<item><title>SEC Announces Fixture Roundtable</title><link>https://www.sec.gov/newsroom/press-releases/fixture-cli-1</link>
<pubDate>{pub}</pubDate><guid>fixture-cli-1</guid></item></channel></rss>"""


class FakeNet:
    """Answers the live code paths' requests: one RSS feed and the two public OKX endpoints."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, str]] = []

    def __call__(self, method: str, url: str, params: Any, json_body: Any, headers: dict) -> Tuple[int, str]:
        self.calls.append((method, url))
        assert "authorization" not in {h.lower() for h in headers} and not any(h.lower().startswith("ok-") for h in headers)
        now = datetime.now(tz=timezone.utc)
        if url == "https://www.sec.gov/news/pressreleases.rss":
            return 200, RSS.format(pub=(now - timedelta(minutes=3)).strftime("%a, %d %b %Y %H:%M:%S GMT"))
        if url == "https://www.okx.com/api/v5/market/candles":
            start = now.replace(second=0, microsecond=0) - timedelta(minutes=5 * 30)
            rows = [[str(int((start + timedelta(minutes=5 * i)).timestamp() * 1000)), "100", "101", "99", "100", "10", "1", "1", "1"] for i in range(30)]
            return 200, json.dumps({"code": "0", "msg": "", "data": rows[::-1]})
        if url == "https://www.okx.com/api/v5/public/time":
            return 200, json.dumps({"code": "0", "msg": "", "data": [{"ts": str(int(now.timestamp() * 1000))}]})
        raise AssertionError(f"unexpected URL {url}")


def test_one_live_cycle_without_the_model_on_a_fake_network(tmp_path: Path, monkeypatch, capsys, no_real_network):
    net = FakeNet()
    monkeypatch.setattr(fetch_module, "default_http", net)
    monkeypatch.setattr(market_module, "default_http", net)
    logs = tmp_path / "logs"
    code = cli.main(
        ["--once", "--no-model", "--sources", "sec_press", "--log-dir", str(logs), "--news-dir", str(tmp_path / "news"), "--journal-dir", str(tmp_path / "none")],
        env={},
    )
    assert code == 0, capsys.readouterr()
    assert "cycle 1: healthy=True items=1" in capsys.readouterr().out
    hosts = {url.split("/")[2] for _, url in net.calls}
    assert hosts == {"www.sec.gov", "www.okx.com"}
    day = datetime.now(tz=timezone.utc).date().isoformat()
    events = [json.loads(line) for line in (logs / f"events-{day}.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "runner_event" and kinds[-1] == "runner_event" and "cycle_summary" in kinds
    assert not any(k.startswith("classifier_") for k in kinds)
    (observed,) = [e for e in events if e["kind"] == "source_item_observed"]
    assert observed["triage"]["status"] == "model_disabled"
    assert (logs / f"report-{day}.md").exists() and (logs / "_state" / "shadow_state.json").exists()
    assert not (tmp_path / "none").exists()  # the journal directory is only ever read


def test_the_log_directory_can_never_be_the_phase6a_journal_directory(tmp_path: Path, capsys, no_real_network):
    shadow_dir = tmp_path / "logs" / "shadow"
    shadow_dir.mkdir(parents=True)
    for argv in (["--once", "--no-model"], ["--report", "2026-10-19"]):
        code = cli.main(argv + ["--log-dir", str(shadow_dir), "--journal-dir", str(shadow_dir)], env={})
        assert code == 2 and "Phase 6a journal directory" in capsys.readouterr().err
    assert list(shadow_dir.iterdir()) == []


def test_at_runtime_the_script_loads_no_trading_config_dotenv_or_database_code(tmp_path: Path):
    """Imports can be indirect: check what is really loaded after a whole dry run."""
    import subprocess
    import sys

    probe = (
        "import json, runpy, sys\n"
        f"sys.argv = ['run_news_shadow.py', '--dry-run', '--out', {str(tmp_path / 'out')!r}]\n"
        "try:\n"
        f"    runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n"
        "except SystemExit as exit_:\n"
        "    code = exit_.code\n"
        "print(json.dumps({'code': code, 'modules': sorted(sys.modules)}))\n"
    )
    out = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=300, cwd=str(tmp_path))
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["code"] == 0, out.stderr[-2000:]
    forbidden = ("app.config", "dotenv", "app.execution", "app.risk", "app.exchange", "app.okx", "app.shadow", "app.db", "app.strategy",
                 "app.broker", "app.notify", "sqlalchemy", "pydantic_settings")
    loaded = [m for m in result["modules"] if any(m == f or m.startswith(f + ".") for f in forbidden)]
    assert loaded == []


def test_the_script_never_loads_dotenv_or_the_trading_config():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    forbidden = ("dotenv", "app.config", "app.execution", "app.risk", "app.exchange", "app.okx", "app.shadow", "app.db", "app.strategy", "app.broker", "app.notify")
    assert not [n for n in names if any(n == f or n.startswith(f + ".") for f in forbidden)]
    text = SCRIPT.read_text(encoding="utf-8")
    assert "load_dotenv" not in text and "run_demo_trading" not in text and "run_shadow_period" not in text
