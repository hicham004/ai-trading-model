"""Pure OKX v5 request signing (HMAC-SHA256). No I/O, no secret logging.

Everything here is a pure function of its inputs so it is trivially testable
with known vectors and never performs network or logging side effects. The
caller supplies the secret; it is used only to compute the HMAC and is never
stored, returned, or logged by this module.

REST signing (per OKX docs):
    prehash = timestamp + method + requestPath + body
    OK-ACCESS-SIGN = base64(HMAC_SHA256(secret, prehash))
    OK-ACCESS-TIMESTAMP = ISO-8601 UTC milliseconds, e.g. 2020-12-08T09:08:57.715Z
    - ``method`` is upper-case (GET/POST).
    - ``requestPath`` includes the leading ``/api/...`` and any query string.
    - ``body`` is the exact request body string (empty for GET).

WebSocket login signing (per OKX docs):
    prehash = timestamp + 'GET' + '/users/self/verify'
    sign = base64(HMAC_SHA256(secret, prehash))
    timestamp is the Unix epoch in SECONDS (string), e.g. "1704876947".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone

# OKX authentication header names (demo and production use the same names; the
# demo/simulated environment is selected by the x-simulated-trading header,
# which lives in app.exchange.okx_demo_endpoints, not here).
HEADER_API_KEY = "OK-ACCESS-KEY"
HEADER_SIGN = "OK-ACCESS-SIGN"
HEADER_TIMESTAMP = "OK-ACCESS-TIMESTAMP"
HEADER_PASSPHRASE = "OK-ACCESS-PASSPHRASE"

_WS_LOGIN_PATH = "/users/self/verify"


def iso_timestamp(moment: datetime) -> str:
    """Format ``moment`` as OKX ISO-8601 UTC milliseconds (``...Z``)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    # Millisecond precision, trailing 'Z' (OKX rejects microsecond precision).
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def epoch_seconds_timestamp(moment: datetime) -> str:
    """Format ``moment`` as a Unix-epoch-seconds string (WS login)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return str(int(moment.astimezone(timezone.utc).timestamp()))


def rest_prehash(timestamp: str, method: str, request_path: str, body: str) -> str:
    """Build the REST prehash string: ``timestamp + METHOD + requestPath + body``."""
    return f"{timestamp}{method.upper()}{request_path}{body}"


def _hmac_b64(secret: str, message: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def sign_rest(secret: str, timestamp: str, method: str, request_path: str, body: str) -> str:
    """Return the base64 ``OK-ACCESS-SIGN`` for a REST request."""
    return _hmac_b64(secret, rest_prehash(timestamp, method, request_path, body))


def ws_login_prehash(timestamp: str) -> str:
    """Build the WebSocket login prehash: ``timestamp + 'GET' + '/users/self/verify'``."""
    return f"{timestamp}GET{_WS_LOGIN_PATH}"


def sign_ws_login(secret: str, timestamp: str) -> str:
    """Return the base64 signature for a WebSocket ``login`` op."""
    return _hmac_b64(secret, ws_login_prehash(timestamp))
