"""Boundaries of the ops digest and the OKX changelog watcher (plan row R6; PROJECT_RULES "Decision And Execution Authority").

1. ``app/ops`` and its two scripts import nothing from execution, risk, the exchange
   clients, the broker, strategies, the shadow supervisor, live feeds, local paper
   trading, the API, the database or the trading config.
2. Only the news agent's classifier imports an LLM SDK; ``app/ops`` reaches Claude through
   the news agent's client builder and spend guard.
3. The authenticated-API vocabulary appears only in the watch list (as words to look for
   in the changelog); the only network call is one GET of the public changelog page.
4. Nothing on the trading side imports ``app.ops``.
5. The units run confined, with their own environment file; the example holds no secret.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Iterator, Tuple

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "app" / "ops"
SCRIPTS = (ROOT / "scripts" / "ops_digest.py", ROOT / "scripts" / "watch_okx_changelog.py")
FLEET_DIGEST = ROOT / "research" / "paper_fleet" / "digest.py"

TRADING_PACKAGES = ("app.execution", "app.risk", "app.exchange", "app.okx", "app.broker", "app.strategy", "app.shadow",
                    "app.live", "app.paper", "app.api", "app.db", "app.backtest", "app.config", "app.datalake")
LLM_SDKS = ("anthropic", "openai", "google.generativeai", "google.genai", "mistralai", "cohere")
AUTH_MARKERS = ("x-simulated-trading", "OK-ACCESS-", "/api/v5/trade", "/api/v5/account", "/api/v5/asset", "OKX_DEMO_", "DEMO_ACCOUNT_NAME")


def _imports(path: Path) -> Iterator[Tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node.lineno
            for alias in node.names:
                yield f"{node.module}.{alias.name}", node.lineno


def _under(name: str, packages) -> bool:
    return any(name == p or name.startswith(p + ".") for p in packages)


def _ops_files():
    files = sorted(OPS.glob("*.py"))
    assert {p.name for p in files} >= {"digest.py", "digest_ai.py", "okx_changelog.py", "okx_usage.py"}
    return files


def test_ops_code_imports_no_trading_exchange_database_or_llm_code():
    for path in list(_ops_files()) + list(SCRIPTS) + [FLEET_DIGEST]:
        for name, line in _imports(path):
            where = f"{path.relative_to(ROOT)}:{line}"
            assert not _under(name, TRADING_PACKAGES), f"{where} imports {name}"
            assert not _under(name, LLM_SDKS + ("dotenv", "sqlalchemy")), f"{where} imports {name}"


def test_the_authenticated_vocabulary_lives_only_in_the_watch_list():
    usage = OPS / "okx_usage.py"
    assert {name.split(".")[0] for name, _ in _imports(usage)} <= {"__future__", "re", "dataclasses", "typing"}
    for path in [p for p in _ops_files() if p != usage] + list(SCRIPTS) + [FLEET_DIGEST]:
        text = path.read_text(encoding="utf-8").lower()
        for marker in AUTH_MARKERS + ("run_demo_trading", "run_shadow_period", "load_dotenv", "place_order"):
            assert marker.lower() not in text, f"{path.relative_to(ROOT)} mentions {marker}"


def test_the_only_network_call_is_a_get_of_the_public_changelog():
    network = ("requests", "websockets", "socket", "urllib.request", "http.client", "httpx", "httpx2", "aiohttp")
    for path in list(_ops_files()) + list(SCRIPTS):
        text = path.read_text(encoding="utf-8")
        for verb in (".post(", ".put(", ".patch(", ".delete(", "requests.request(", "urlopen("):
            assert verb not in text, f"{path.relative_to(ROOT)} uses {verb}"
        for name, line in _imports(path):
            if _under(name, network):  # only the watcher's fetch may open a connection (Telegram goes through app.notify)
                assert path.name == "okx_changelog.py" and name == "requests", f"{path.relative_to(ROOT)}:{line} imports {name}"
    changelog = (OPS / "okx_changelog.py").read_text(encoding="utf-8")
    assert changelog.count("http.get(") == 1 and "allow_redirects=False" in changelog
    assert 'CHANGELOG_HOST = "www.okx.com"' in changelog


def test_loading_the_ops_code_pulls_in_no_trading_exchange_database_or_llm_code():
    code = (
        "import sys, importlib.util\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "sys.modules.setdefault('dotenv', None)\n"
        "import app.ops.digest, app.ops.digest_ai, app.ops.okx_changelog, research.paper_fleet.digest\n"
        f"for i, p in enumerate({[str(s) for s in SCRIPTS]!r}):\n"
        "    spec = importlib.util.spec_from_file_location(f'ops_script_{i}', p)\n"
        "    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('anthropic', 'openai', 'sqlalchemy', 'psycopg') or m.startswith(("
        "'app.execution', 'app.exchange', 'app.risk', 'app.shadow', 'app.paper', 'app.live', 'app.api', 'app.db', 'app.broker'))]\n"
        "print('BAD:' + ','.join(sorted(bad)))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("BAD:"), out.stdout


def test_the_scripts_keep_the_repository_env_out_of_their_process():
    for script in SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert 'sys.modules.setdefault("dotenv", None)' in text.split("sys.path.insert", 1)[0], script.name


def test_nothing_on_the_trading_side_imports_the_ops_code():
    trading_dirs = [ROOT / "app" / p.split(".")[1] for p in TRADING_PACKAGES if (ROOT / "app" / p.split(".")[1]).is_dir()]
    files = [f for d in trading_dirs for f in d.rglob("*.py")]
    files += [ROOT / "app" / "config.py", ROOT / "scripts" / "run_demo_trading.py", ROOT / "scripts" / "run_shadow_period.py",
              ROOT / "scripts" / "run_paper_fleet.py", ROOT / "scripts" / "run_news_shadow.py"]
    files += sorted((ROOT / "app" / "news").glob("*.py"))
    assert len(files) > 30
    for path in files:
        for name, line in _imports(path):
            assert not _under(name, ("app.ops",)), f"{path.relative_to(ROOT)}:{line} imports {name}"
    for path in (ROOT / "app").rglob("*.py"):
        assert "paper_fleet" not in path.read_text(encoding="utf-8"), path  # the fleet stays out of app/ (its own boundary test)


def _unit(name: str) -> dict:
    text = (ROOT / "deploy" / "systemd" / name).read_text(encoding="utf-8")
    return {line.split("=", 1)[0]: line.split("=", 1)[1] for line in text.splitlines() if "=" in line and not line.startswith("#")}


def test_the_ops_units_are_oneshot_and_confined():
    for name, script in (("ops-digest.service", "scripts/ops_digest.py --send"),
                         ("okx-changelog-watch.service", "scripts/watch_okx_changelog.py --send")):
        unit = _unit(name)
        assert unit["Type"] == "oneshot" and unit["ExecStart"].endswith(script)
        assert unit["EnvironmentFile"] == "/etc/ai-trading/ops.env"  # its own file, never the repository .env
        assert unit["NoNewPrivileges"] == "yes" and unit["ProtectSystem"] == "strict" and unit["CapabilityBoundingSet"] == ""
        assert unit["ReadWritePaths"] == "/path/to/ai-trading-model/logs/ops" and unit["User"] != "root"
        assert set(unit["InaccessiblePaths"].split()) >= {"-/path/to/ai-trading-model/.env", "-/run/postgresql"}
        body = "\n".join(line for line in (ROOT / "deploy" / "systemd" / name).read_text(encoding="utf-8").splitlines()
                         if not line.startswith("#") and not line.startswith("InaccessiblePaths="))
        for forbidden in ("run_demo_trading", "run_shadow_period", "OKX_", "sk-ant", "/.env"):
            assert forbidden not in body, f"{name} mentions {forbidden}"
    for name, at in (("ops-digest.timer", "07:00:00"), ("okx-changelog-watch.timer", "06:30:00")):
        timer = _unit(name)
        assert timer["OnCalendar"] == f"*-*-* {at} Asia/Beirut" and timer["Persistent"] == "true"
        assert timer["Unit"] == name.replace(".timer", ".service") and timer["WantedBy"] == "timers.target"


def test_the_ops_env_example_holds_no_secret_and_no_okx_setting():
    example = (ROOT / "deploy" / "systemd" / "ops.env.example").read_text(encoding="utf-8")
    settings = dict(line.split("=", 1) for line in example.splitlines() if "=" in line and not line.startswith("#"))
    assert settings["TELEGRAM_BOT_TOKEN"] == "" and settings["TELEGRAM_CHAT_ID"] == "" and settings["ANTHROPIC_API_KEY"] == ""
    assert not [k for k in settings if k.startswith("OKX") or "SECRET" in k or "PASSPHRASE" in k]
    assert "sk-ant" not in example
