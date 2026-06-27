"""Tests for the travel-mode safety guard (offline; no git, no network).

These verify the conservative path classification and the pass/fail behavior:
travel mode ON + a safety-sensitive change must FAIL the build; everything else
must pass.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# Load the script module by path (scripts/ is not an importable package).
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_travel_mode_safety.py"
_spec = importlib.util.spec_from_file_location("check_travel_mode_safety", _SCRIPT)
guard = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(guard)


# --- classification -------------------------------------------------------

SAFETY_SENSITIVE = [
    "app/execution/driver.py",
    "app/exchange/okx_demo_rest.py",
    "app/exchange/credentials.py",
    "app/okx/client.py",
    "app/risk/manager.py",
    "app/shadow/supervisor.py",
    "app/strategy/ma_crossover.py",
    "app/config.py",
    "config/shadow_period.json",
    "scripts/run_demo_trading.py",
    "scripts/run_shadow_period.py",
    "scripts/check_travel_mode_safety.py",
    "scripts/notify_telegram.py",
    "app/notify/__init__.py",
    "app/notify/telegram.py",
    ".github/workflows/ci.yml",
    ".github/workflows/notify.yml",
    ".env",
    ".env.example",
    "CLAUDE.md",
    "PROJECT_RULES.md",
    "AGENTS.md",
    "docs/PHASES.md",
    "docs/TRAVEL_MODE.md",
    "docs/GITHUB_SETUP_FOR_TRAVEL.md",
    "docs/CLAUDE_ROUTINE_SETUP.md",
    "requirements.txt",
    "pyproject.toml",
]

NOT_SENSITIVE = [
    "README.md",
    "dashboard/app.py",
    "docs/PHASE5_VALIDATION.md",
    "tests/test_travel_mode_safety.py",
    "app/backtest/runner.py",
    "UltimatePlan.md",
]


def test_safety_sensitive_paths_are_classified():
    for path in SAFETY_SENSITIVE:
        assert guard.classify(path) is not None, f"{path} should be safety-sensitive"


def test_non_sensitive_paths_are_not_classified():
    for path in NOT_SENSITIVE:
        assert guard.classify(path) is None, f"{path} should not be safety-sensitive"


def test_classify_normalizes_separators_and_prefixes():
    assert guard.classify("app\\risk\\manager.py") is not None  # windows sep
    assert guard.classify("./app/execution/store.py") is not None  # leading ./
    assert guard.classify("") is None
    assert guard.classify("   ") is None


def test_find_safety_sensitive_returns_only_hits():
    files = ["README.md", "app/risk/manager.py", "dashboard/app.py"]
    hits = guard.find_safety_sensitive(files)
    assert [h[0] for h in hits] == ["app/risk/manager.py"]
    assert "risk manager" in hits[0][1]


# --- travel-mode env parsing ---------------------------------------------

def test_is_travel_mode_enabled_truthy_values():
    for val in ["1", "true", "TRUE", "yes", "on", " On "]:
        assert guard.is_travel_mode_enabled({"TRAVEL_MODE": val}) is True


def test_is_travel_mode_disabled_values():
    for val in ["", "0", "off", "no", "false", "anything-else"]:
        assert guard.is_travel_mode_enabled({"TRAVEL_MODE": val}) is False
    assert guard.is_travel_mode_enabled({}) is False


# --- run() exit codes -----------------------------------------------------

def test_run_fails_when_travel_on_and_safety_file_changed():
    rc = guard.run(["--travel-mode", "on", "--files", "app/risk/manager.py", "README.md"])
    assert rc == 1


def test_run_passes_when_travel_on_and_only_safe_files():
    rc = guard.run(["--travel-mode", "on", "--files", "README.md", "dashboard/app.py"])
    assert rc == 0


def test_run_passes_when_travel_off_even_with_safety_file():
    rc = guard.run(["--travel-mode", "off", "--files", "app/execution/driver.py"])
    assert rc == 0


def test_run_auto_reads_env(monkeypatch):
    monkeypatch.setenv("TRAVEL_MODE", "1")
    rc = guard.run(["--files", "app/risk/manager.py"], env={"TRAVEL_MODE": "1"})
    assert rc == 1
    rc = guard.run(["--files", "app/risk/manager.py"], env={"TRAVEL_MODE": "0"})
    assert rc == 0


def test_run_passes_with_no_changed_files():
    assert guard.run(["--travel-mode", "on", "--files"]) == 0
