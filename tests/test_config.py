"""Tests for configuration defaults and the Phase 1 safety lock (offline)."""

from __future__ import annotations

import app.config as config
from app.config import Settings, get_settings


def test_live_trading_is_disabled_by_default():
    # The default settings must keep live trading disabled (Phase 1 lock).
    assert Settings().live_trading_enabled is False


def test_get_settings_returns_safe_settings_and_is_cached():
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second  # cached singleton
    assert first.live_trading_enabled is False


def test_get_settings_rejects_enabled_live_trading(monkeypatch):
    # If someone flips the lock on, get_settings must refuse to start.
    get_settings.cache_clear()
    monkeypatch.setattr(config, "Settings", lambda: Settings(live_trading_enabled=True))
    try:
        raised = False
        try:
            get_settings()
        except RuntimeError:
            raised = True
        assert raised, "get_settings should refuse live trading in Phase 1"
    finally:
        get_settings.cache_clear()


def test_get_bool_parses_truthy_values(monkeypatch):
    monkeypatch.setenv("SOME_FLAG", "yes")
    assert config._get_bool("SOME_FLAG", False) is True
    monkeypatch.setenv("SOME_FLAG", "off")
    assert config._get_bool("SOME_FLAG", True) is False
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert config._get_bool("SOME_FLAG", True) is True
