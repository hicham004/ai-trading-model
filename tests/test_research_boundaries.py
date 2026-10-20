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
    files = list((ROOT / "research").rglob("*.py")) + [ROOT / "scripts" / "run_research.py"]
    assert files
    for path in files:
        for module in _imports(path):
            for forbidden in FORBIDDEN:
                assert not (module == forbidden or module.startswith(forbidden + ".")), (
                    f"{path.relative_to(ROOT)} imports {module} (forbidden: {forbidden})"
                )


def test_research_is_not_wired_into_the_live_registry():
    for name in ("registry.py", "library.py"):
        for module in _imports(ROOT / "app" / "strategy" / name):
            assert not module.startswith("research"), f"app/strategy/{name} imports {module}"
