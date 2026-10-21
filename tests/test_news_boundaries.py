"""Import boundaries of the log-only news agent (Phase 6b; PROJECT_RULES "Decision And Execution Authority").

1. ``app/news`` imports nothing from execution, risk, exchange/OKX clients, the
   broker, strategies, the shadow supervisor, live feeds, paper trading, the API,
   notifications, the database or the trading config.
2. Only ``app/news/classifier.py`` may import the Anthropic SDK; nothing imports
   another LLM vendor's SDK.
3. No ``app/news`` source mentions an authenticated OKX header or private endpoint.
4. Nothing on the trading side imports ``app.news``: news output cannot reach an
   order path, a stop, the kill switch or reconciliation.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, Tuple

ROOT = Path(__file__).resolve().parents[1]
NEWS = ROOT / "app" / "news"

TRADING_PACKAGES = (
    "app.execution",
    "app.risk",
    "app.exchange",
    "app.okx",
    "app.broker",
    "app.strategy",
    "app.shadow",
    "app.live",
    "app.paper",
    "app.api",
    "app.notify",
    "app.db",
    "app.backtest",
    "app.config",
)
LLM_SDKS = ("anthropic", "openai", "google.generativeai", "google.genai", "mistralai", "cohere")
AUTH_MARKERS = ("x-simulated-trading", "OK-ACCESS-", "/api/v5/trade", "/api/v5/account", "/api/v5/asset", "OKX_DEMO_")


def _imports(path: Path) -> Iterator[Tuple[str, int]]:
    """Every imported module name in ``path`` (top level, functions and classes alike)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node.lineno
            for alias in node.names:  # "from app import execution"
                yield f"{node.module}.{alias.name}", node.lineno


def _under(name: str, packages) -> bool:
    return any(name == p or name.startswith(p + ".") for p in packages)


def test_news_package_imports_no_trading_or_exchange_code():
    files = sorted(NEWS.glob("*.py"))
    assert {p.name for p in files} >= {"schema.py", "classifier.py", "corroborate.py", "decay.py", "overlay.py", "store.py"}
    for path in files:
        for name, line in _imports(path):
            assert not _under(name, TRADING_PACKAGES), f"app/news/{path.name}:{line} imports {name}"


def test_only_the_classifier_touches_an_llm_sdk():
    for path in sorted(NEWS.glob("*.py")):
        for name, line in _imports(path):
            if _under(name, ("anthropic",)) and path.name == "classifier.py":
                continue
            assert not _under(name, LLM_SDKS), f"app/news/{path.name}:{line} imports {name}"


def test_news_sources_never_mention_authenticated_exchange_access():
    for path in sorted(NEWS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for marker in AUTH_MARKERS:
            assert marker.lower() not in text.lower(), f"app/news/{path.name} mentions {marker}"


def test_the_news_shadow_script_stays_outside_the_trading_side():
    script = ROOT / "scripts" / "run_news_shadow.py"
    for name, line in _imports(script):
        assert not _under(name, TRADING_PACKAGES), f"scripts/run_news_shadow.py:{line} imports {name}"
        assert not _under(name, ("dotenv",) + LLM_SDKS), f"scripts/run_news_shadow.py:{line} imports {name}"
    text = script.read_text(encoding="utf-8")
    for marker in AUTH_MARKERS + ("load_dotenv", "run_demo_trading", "run_shadow_period"):
        assert marker.lower() not in text.lower(), f"scripts/run_news_shadow.py mentions {marker}"


def test_the_news_shadow_unit_is_log_only_and_confined():
    unit = (ROOT / "deploy" / "systemd" / "news-shadow.service").read_text(encoding="utf-8")
    lines = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in unit.splitlines() if "=" in line and not line.startswith("#")}
    assert lines["ExecStart"].endswith("scripts/run_news_shadow.py --loop")
    assert lines["EnvironmentFile"] == "/etc/ai-trading/news-shadow.env"  # its own file, never the repository .env
    assert lines["NoNewPrivileges"] == "yes" and lines["ProtectSystem"] == "strict" and lines["CapabilityBoundingSet"] == ""
    assert sorted(lines["ReadWritePaths"].split()) == [
        "/path/to/ai-trading-model/data/news",
        "/path/to/ai-trading-model/logs/news_shadow",
    ]
    assert lines["RestartPreventExitStatus"] == "2" and lines["User"] != "root"
    assert "MemoryMax" in lines and "CPUQuota" in lines
    assert set(lines["InaccessiblePaths"].split()) >= {"-/path/to/ai-trading-model/.env", "-/run/postgresql"}
    body = "\n".join(line for line in unit.splitlines() if not line.startswith("#") and not line.startswith("InaccessiblePaths="))
    for forbidden in ("shadow.service", "run_demo_trading", "run_shadow_period", "OKX_", "sk-ant", "/.env"):
        assert forbidden not in body, f"the news shadow unit mentions {forbidden}"


def test_the_news_shadow_env_example_holds_no_secret_and_no_okx_setting():
    example = (ROOT / "deploy" / "systemd" / "news-shadow.env.example").read_text(encoding="utf-8")
    settings = dict(line.split("=", 1) for line in example.splitlines() if "=" in line and not line.startswith("#"))
    assert settings["ANTHROPIC_API_KEY"] == ""
    assert not [k for k in settings if k.startswith("OKX") or "SECRET" in k or "PASSPHRASE" in k]
    assert "sk-ant" not in example


def test_nothing_on_the_trading_side_imports_the_news_agent():
    trading_dirs = [ROOT / "app" / p.split(".")[1] for p in TRADING_PACKAGES if (ROOT / "app" / p.split(".")[1]).is_dir()]
    files = [f for d in trading_dirs for f in d.rglob("*.py")]
    files += [ROOT / "app" / "config.py", ROOT / "scripts" / "run_demo_trading.py", ROOT / "scripts" / "run_shadow_period.py"]
    assert len(files) > 20
    for path in files:
        for name, line in _imports(path):
            assert not _under(name, ("app.news",)), f"{path.relative_to(ROOT)}:{line} imports {name}"
