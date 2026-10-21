"""The paper fleet stays a public-data simulation: no trading, exchange-auth, risk, database or AI code; GET-only public paths."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "research" / "paper_fleet").glob("*.py")) + [ROOT / "scripts" / "run_paper_fleet.py"]
FORBIDDEN = (
    "app.execution",
    "app.exchange",
    "app.risk",
    "app.shadow",
    "app.okx",
    "app.paper",
    "app.live",
    "app.api",
    "app.db",
    "app.notify",
    "app.broker",
    "app.news",
    "app.strategy.registry",
    "anthropic",
    "openai",
)
IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", re.MULTILINE)


def test_no_forbidden_imports_in_the_fleet():
    assert len(FILES) >= 10
    for path in FILES:
        for match in IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
            module = match.group(1) or match.group(2)
            for forbidden in FORBIDDEN:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.name} imports {module}"


def test_loading_the_fleet_pulls_in_no_trading_or_private_exchange_code():
    code = (
        "import sys, importlib.util\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import research.paper_fleet.runner, research.paper_fleet.replay, research.paper_fleet.report\n"
        f"spec = importlib.util.spec_from_file_location('rpf', {str(ROOT / 'scripts' / 'run_paper_fleet.py')!r})\n"
        "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('anthropic', 'openai', 'sqlalchemy') or m.startswith(("
        "'app.execution', 'app.exchange', 'app.risk', 'app.shadow', 'app.paper', 'app.live', 'app.api', 'app.db', 'app.notify', 'app.broker'))]\n"
        "print('BAD:' + ','.join(sorted(bad)))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("BAD:"), out.stdout


def test_only_public_market_data_paths_and_no_order_vocabulary():
    text = "\n".join(p.read_text(encoding="utf-8") for p in FILES)
    for needle in ("/api/v5/trade", "/api/v5/account", "/api/v5/asset", "x-simulated-trading", "OK-ACCESS", "place_order", "ANTHROPIC_API_KEY",
                   ".post(", "requests.post", "DEMO_ACCOUNT_NAME"):
        assert needle not in text, needle
    paths = set(re.findall(r'"(/api/v5/[\w/\-]+)"', text))
    assert paths <= {"/api/v5/market/candles", "/api/v5/market/history-candles"}, paths


def test_nothing_in_the_trading_runtime_imports_the_fleet():
    for path in (ROOT / "app").rglob("*.py"):
        assert "paper_fleet" not in path.read_text(encoding="utf-8"), path
    for name in ("run_demo_trading.py", "run_shadow_period.py", "run_paper_trading.py"):
        assert "paper_fleet" not in (ROOT / "scripts" / name).read_text(encoding="utf-8")
