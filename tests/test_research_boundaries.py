"""The research sandbox must never import the trading, exchange or supervisor code paths."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "app.execution",
    "app.exchange",
    "app.shadow",
    "app.okx",
    "app.notify",
    "app.paper",
    "app.live",
    "app.api",
    "app.strategy.registry",  # candidates are never auto-registered for the demo runtime
    "anthropic",
    "openai",
)
IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", re.MULTILINE)


def _imports(path: Path):
    text = path.read_text(encoding="utf-8")
    for match in IMPORT_RE.finditer(text):
        yield match.group(1) or match.group(2)


def test_research_package_and_runner_stay_in_the_sandbox():
    files = list((ROOT / "research").rglob("*.py")) + [ROOT / "scripts" / "run_research.py", ROOT / "scripts" / "run_research_v1b.py", ROOT / "scripts" / "run_research_v1c.py",
                                                       ROOT / "scripts" / "run_paper_fleet.py", ROOT / "scripts" / "run_allocator_v2.py",
                                                       ROOT / "scripts" / "run_long_short_study.py", ROOT / "scripts" / "run_replication_v1d.py"]
    assert files
    for path in files:
        for module in _imports(path):
            for forbidden in FORBIDDEN:
                assert not (module == forbidden or module.startswith(forbidden + ".")), (
                    f"{path.relative_to(ROOT)} imports {module} (forbidden: {forbidden})"
                )


def test_the_allocator_code_imports_no_risk_database_or_broker_code_either():
    """Plan row R5b: allocator v2 stays research code; `app/risk` (the demo and live risk manager) is never touched or used."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    for path in [ROOT / "research" / "allocator.py", ROOT / "research" / "allocator_study.py", ROOT / "scripts" / "run_allocator_v2.py",
                 *sorted((ROOT / "research" / "paper_fleet").glob("*.py"))]:
        for module in _imports(path):
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
    for path in (ROOT / "app").rglob("*.py"):
        assert "research.allocator" not in path.read_text(encoding="utf-8"), path


def test_research_is_not_wired_into_the_live_registry():
    for name in ("registry.py", "library.py"):
        for module in _imports(ROOT / "app" / "strategy" / name):
            assert not module.startswith("research"), f"app/strategy/{name} imports {module}"


def test_the_long_short_design_study_stays_paper_only():
    """Plan row R9: the long/short study is research code — no risk, database, broker, execution or exchange code, and the
    trading runtime never imports it. Its only network access is the GET-only public client of the data lake."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    study_files = [ROOT / "research" / name for name in ("longshort.py", "longshort_data.py", "longshort_study.py", "report_longshort.py")]
    study_files += [ROOT / "research" / "strategies" / "shorts.py", ROOT / "scripts" / "run_long_short_study.py"]
    for path in study_files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "research.longshort" not in text and "research.strategies.shorts" not in text, path


def test_the_replication_study_stays_in_the_sandbox_and_widens_no_app_allowlist():
    """Plan row R12: the replication study is research code. Its collectors reach the network only through the data lake's GET-only
    public clients; the trading runtime never imports it; the app's instrument and symbol allowlists are not widened for it."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    study_files = [ROOT / "research" / name for name in ("markets.py", "replication.py", "replication_data.py", "report_replication.py")]
    study_files.append(ROOT / "scripts" / "run_replication_v1d.py")
    for path in study_files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    text = "\n".join(p.read_text(encoding="utf-8") for p in study_files)
    for needle in ("/api/v5/trade", "/api/v5/account", "/api/v5/asset", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post"):
        assert needle not in text, needle
    paths = set(re.findall(r'"(/api/v5/[\w/\-]+)"', text))
    assert paths <= {"/api/v5/market/candles", "/api/v5/market/history-candles", "/api/v5/market/tickers"}, paths
    for path in (ROOT / "app").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "research.replication" not in content and "research.markets" not in content, path
    from app.datalake.binance_public import SYMBOLS
    from app.okx.client import ALLOWED_INSTRUMENTS

    assert ALLOWED_INSTRUMENTS == ("BTC-USDT", "ETH-USDT") and SYMBOLS == ("BTCUSDT", "ETHUSDT")
