"""OKX WebSocket defaults must carry NO explicit port (OKX 8443 cutoff).

OKX discontinues WebSocket connections on port ``:8443`` on Oct 31, 2026 for
every path (public, business, private) including the demo host
``wspap.okx.com``. Every default URL in this repository must therefore be
port-less (implicit 443). The validators intentionally keep accepting an
explicit ``:443`` or ``:8443`` so an operator override is never rejected by
the fail-closed URL checks.

These tests are offline: they inspect module constants, ``Settings``
defaults, ``.env.example`` and the two phase docs that print the URLs.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.config import Settings
from app.exchange import okx_demo_endpoints as demo
from app.exchange import okx_public_ws as public

ROOT = Path(__file__).resolve().parents[1]

_WS_ENV_VARS = (
    "OKX_PUBLIC_WS_URL",
    "OKX_BUSINESS_WS_URL",
    "OKX_DEMO_PRIVATE_WS_URL",
)


def _assert_portless(url: str) -> None:
    parts = urlsplit(url)
    assert parts.scheme == "wss", url
    assert parts.port is None, f"default WebSocket URL must not pin a port: {url}"
    assert ":8443" not in url and ":443" not in url, url


def test_public_ws_module_defaults_have_no_port():
    _assert_portless(public.OKX_PUBLIC_WS_URL)
    _assert_portless(public.OKX_BUSINESS_WS_URL)


def test_demo_ws_module_defaults_have_no_port():
    _assert_portless(demo.DEMO_PRIVATE_WS_URL)
    _assert_portless(demo.DEMO_PUBLIC_WS_URL)
    _assert_portless(demo.DEMO_BUSINESS_WS_URL)


def test_settings_defaults_have_no_port(monkeypatch):
    # Ignore any operator override from a local .env / environment so the
    # test checks the shipped defaults, not the machine it runs on.
    for name in _WS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    _assert_portless(settings.okx_public_ws_url)
    _assert_portless(settings.okx_business_ws_url)
    _assert_portless(settings.okx_demo_private_ws_url)
    # And the shipped defaults are exactly the module constants.
    assert settings.okx_public_ws_url == public.OKX_PUBLIC_WS_URL
    assert settings.okx_business_ws_url == public.OKX_BUSINESS_WS_URL
    assert settings.okx_demo_private_ws_url == demo.DEMO_PRIVATE_WS_URL


def test_defaults_still_pass_the_fail_closed_validators():
    assert public.validate_public_ws_url(
        public.OKX_PUBLIC_WS_URL, expected_path="/ws/v5/public"
    ) == public.OKX_PUBLIC_WS_URL
    assert public.validate_public_ws_url(
        public.OKX_BUSINESS_WS_URL, expected_path="/ws/v5/business"
    ) == public.OKX_BUSINESS_WS_URL
    assert demo.validate_demo_ws_url(
        demo.DEMO_PRIVATE_WS_URL, expected_path="/ws/v5/private"
    ) == demo.DEMO_PRIVATE_WS_URL


@pytest.mark.parametrize("port", ["", ":443", ":8443"])
def test_validators_keep_accepting_operator_port_overrides(port):
    # An explicit :443 / :8443 override must not be rejected (the guard is
    # about host/scheme/path, not about forcing one port).
    assert public.validate_public_ws_url(f"wss://ws.okx.com{port}/ws/v5/public")
    assert demo.validate_demo_ws_url(f"wss://wspap.okx.com{port}/ws/v5/private")


@pytest.mark.parametrize("port", [":80", ":8080", ":8444"])
def test_validators_still_reject_unapproved_ports(port):
    with pytest.raises(ValueError):
        public.validate_public_ws_url(f"wss://ws.okx.com{port}/ws/v5/public")
    with pytest.raises(ValueError):
        demo.validate_demo_ws_url(f"wss://wspap.okx.com{port}/ws/v5/private")


def test_env_example_ws_urls_have_no_port():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    found = {}
    for line in text.splitlines():
        for name in _WS_ENV_VARS:
            if line.startswith(f"{name}="):
                found[name] = line.split("=", 1)[1].strip()
    assert set(found) == set(_WS_ENV_VARS), f".env.example missing WS vars: {found}"
    for name, url in found.items():
        _assert_portless(url)


@pytest.mark.parametrize(
    "relpath",
    ["docs/PHASE3A_LIVE_DATA.md", "docs/PHASE5_DEMO_TRADING.md", ".env.example"],
)
def test_docs_do_not_advertise_port_8443(relpath):
    text = (ROOT / relpath).read_text(encoding="utf-8")
    assert not re.search(r"wss://[^\s`]*:8443", text), (
        f"{relpath} still shows a :8443 WebSocket URL (OKX cutoff Oct 31, 2026)"
    )


def test_no_source_default_uses_port_8443():
    """No ``wss://...:8443`` literal anywhere under app/ (validator tuples are fine)."""
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        if re.search(r"wss://[^\s\"']*:8443", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], offenders
