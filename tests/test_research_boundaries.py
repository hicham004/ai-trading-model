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
                                                       ROOT / "scripts" / "run_long_short_study.py"]
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
