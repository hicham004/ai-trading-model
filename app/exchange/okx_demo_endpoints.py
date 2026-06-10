"""Demo-only endpoint allowlists and the demo request-header builder.

This module is the single chokepoint that makes PRODUCTION trading
unrepresentable in Phase 5:

* The demo/simulated header is a hard constant: ``x-simulated-trading: 1``.
  There is no symbol anywhere that produces ``0``.
* Every demo request header is built by :func:`demo_request_headers`, which
  always injects the simulated header - there is no code path that signs an
  OKX request without it.
* REST base URLs and WebSocket URLs are validated against strict allowlists
  (demo WS host ``wspap.okx.com`` only; the production WS host ``ws.okx.com``
  is rejected). Wrong scheme/host/port/path fails closed.
* Only an explicit allowlist of SPOT trading and account-read endpoints may be
  called. Funding, withdrawal, transfer, account-mode-mutation, and any other
  path are rejected, so there is no generic arbitrary-endpoint capability.
"""

from __future__ import annotations

from typing import Dict
from urllib.parse import urlsplit

from app.exchange.okx_auth import (
    HEADER_API_KEY,
    HEADER_PASSPHRASE,
    HEADER_SIGN,
    HEADER_TIMESTAMP,
)

# --- the hard demo selector -------------------------------------------------
SIMULATED_TRADING_HEADER = "x-simulated-trading"
SIMULATED_TRADING_VALUE = "1"  # 1 == demo. There is deliberately no "0" here.

# --- regional hostname allowlists -------------------------------------------
# OKX selects demo trading by the simulated header, not by host; the demo
# environment is still reached on the same regional REST hosts. Keep the list
# strict and small. The default is www.okx.com.
DEFAULT_DEMO_REST_BASE_URL = "https://www.okx.com"
APPROVED_DEMO_REST_HOSTS = ("www.okx.com", "aws.okx.com")
_APPROVED_REST_PORTS = (None, 443)

# Demo WebSocket host is distinct from production. Production is ws.okx.com;
# the demo/simulated WS host is wspap.okx.com. Using the production host for an
# authenticated private login must fail closed.
DEMO_WS_HOST = "wspap.okx.com"
_APPROVED_WS_PORTS = (None, 8443, 443)
DEMO_PRIVATE_WS_URL = "wss://wspap.okx.com:8443/ws/v5/private"
DEMO_PUBLIC_WS_URL = "wss://wspap.okx.com:8443/ws/v5/public"
DEMO_BUSINESS_WS_URL = "wss://wspap.okx.com:8443/ws/v5/business"
_APPROVED_WS_PATHS = ("/ws/v5/private", "/ws/v5/public", "/ws/v5/business")

# --- REST endpoint allowlist (SPOT cash + account reads only) ---------------
# (METHOD, path) pairs. This is the COMPLETE set of endpoints the demo client
# may ever call. There is no generic request method exposed to callers.
PUBLIC_TIME = ("GET", "/api/v5/public/time")
PUBLIC_INSTRUMENTS = ("GET", "/api/v5/public/instruments")
ACCOUNT_CONFIG = ("GET", "/api/v5/account/config")
ACCOUNT_BALANCE = ("GET", "/api/v5/account/balance")
ACCOUNT_TRADE_FEE = ("GET", "/api/v5/account/trade-fee")
TRADE_ORDER_GET = ("GET", "/api/v5/trade/order")
TRADE_ORDERS_PENDING = ("GET", "/api/v5/trade/orders-pending")
TRADE_ORDERS_HISTORY = ("GET", "/api/v5/trade/orders-history")
TRADE_FILLS = ("GET", "/api/v5/trade/fills")
TRADE_ORDER_PLACE = ("POST", "/api/v5/trade/order")
TRADE_ORDER_CANCEL = ("POST", "/api/v5/trade/cancel-order")
TRADE_ORDER_AMEND = ("POST", "/api/v5/trade/amend-order")

ALLOWED_ENDPOINTS = frozenset(
    {
        PUBLIC_TIME,
        PUBLIC_INSTRUMENTS,
        ACCOUNT_CONFIG,
        ACCOUNT_BALANCE,
        ACCOUNT_TRADE_FEE,
        TRADE_ORDER_GET,
        TRADE_ORDERS_PENDING,
        TRADE_ORDERS_HISTORY,
        TRADE_FILLS,
        TRADE_ORDER_PLACE,
        TRADE_ORDER_CANCEL,
        TRADE_ORDER_AMEND,
    }
)

# Defensive: tokens that must never appear in any requested path, even if a
# future edit accidentally adds them to the allowlist.
_FORBIDDEN_PATH_TOKENS = (
    "withdrawal",
    "withdraw",
    "transfer",
    "/asset/",
    "deposit",
    "set-account-level",
    "set-position-mode",
    "set-leverage",
    "set-isolated-mode",
    "purchase",
    "redempt",
    "borrow",
    "repay",
    "savings",
    "finance",
)


class EndpointNotAllowedError(ValueError):
    """Raised when a (method, path) is not on the strict demo allowlist."""


def assert_endpoint_allowed(method: str, path: str) -> None:
    """Fail closed unless ``(method, path)`` is explicitly allowlisted."""
    lowered = path.lower()
    for token in _FORBIDDEN_PATH_TOKENS:
        if token in lowered:
            raise EndpointNotAllowedError(
                f"forbidden endpoint path token {token!r} in {path!r}"
            )
    if (method.upper(), path) not in ALLOWED_ENDPOINTS:
        raise EndpointNotAllowedError(
            f"endpoint {method.upper()} {path} is not on the demo allowlist"
        )


def validate_demo_rest_base_url(url: str) -> str:
    """Allow only an approved HTTPS demo REST origin (no path/query/creds)."""
    try:
        parts = urlsplit(url)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"malformed demo REST URL: {type(exc).__name__}") from exc
    if parts.scheme != "https":
        raise ValueError("demo REST URL must use https")
    if parts.username or parts.password:
        raise ValueError("credentials are not allowed in the demo REST URL")
    if parts.hostname not in APPROVED_DEMO_REST_HOSTS:
        raise ValueError(f"demo REST host not approved: {parts.hostname!r}")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("malformed demo REST port") from exc
    if port not in _APPROVED_REST_PORTS:
        raise ValueError(f"demo REST port not approved: {port!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("demo REST base URL must not include path/query/fragment")
    return url.rstrip("/")


def validate_demo_ws_url(url: str, *, expected_path: str | None = None) -> str:
    """Allow only the demo WS host/paths (rejects the production ws.okx.com)."""
    try:
        parts = urlsplit(url)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"malformed demo WS URL: {type(exc).__name__}") from exc
    if parts.scheme != "wss":
        raise ValueError(f"insecure or non-wss demo WS URL: {url!r}")
    if parts.username or parts.password:
        raise ValueError("credentials are not allowed in the demo WS URL")
    if parts.hostname != DEMO_WS_HOST:
        raise ValueError(
            f"demo WS host not approved: {parts.hostname!r} "
            f"(must be {DEMO_WS_HOST!r}; the production host is forbidden)"
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("malformed demo WS port") from exc
    if port not in _APPROVED_WS_PORTS:
        raise ValueError(f"demo WS port not approved: {port!r}")
    if parts.path not in _APPROVED_WS_PATHS:
        raise ValueError(f"demo WS path not approved: {parts.path!r}")
    if expected_path is not None and parts.path != expected_path:
        raise ValueError(
            f"demo WS path {parts.path!r} does not match required {expected_path!r}"
        )
    if parts.query or parts.fragment:
        raise ValueError("query/fragment is not allowed in the demo WS URL")
    return url


def demo_request_headers(
    *, api_key: str, sign: str, timestamp: str, passphrase: str
) -> Dict[str, str]:
    """Build OKX auth headers, ALWAYS including ``x-simulated-trading: 1``.

    This is the only header builder for signed requests, so a signed demo
    request can never be sent without the simulated-trading header.
    """
    return {
        HEADER_API_KEY: api_key,
        HEADER_SIGN: sign,
        HEADER_TIMESTAMP: timestamp,
        HEADER_PASSPHRASE: passphrase,
        SIMULATED_TRADING_HEADER: SIMULATED_TRADING_VALUE,
        "Content-Type": "application/json",
    }
