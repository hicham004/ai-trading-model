"""Tiny GET-only client for OKX PUBLIC statistics endpoints (no credentials, ever).

Separate from the reviewed trading client on purpose: it can reach only an
allowlist of public path prefixes (``/api/v5/public/``, ``/api/v5/rubik/stat/``,
``/api/v5/market/``), refuses any path containing account/trade/asset tokens,
sends no authentication headers, and only ever issues GET requests.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

import requests

from app.logging_config import get_logger
from app.okx.client import validate_public_rest_base_url

logger = get_logger(__name__)

ALLOWED_PATH_PREFIXES = ("/api/v5/public/", "/api/v5/rubik/stat/", "/api/v5/market/")
FORBIDDEN_PATH_TOKENS = (
    "account",
    "trade",
    "asset",
    "withdraw",
    "transfer",
    "deposit",
    "users",
    "subaccount",
    "broker",
    "finance",
    "copytrading",
    "tradingbot",
    "grid",
    "sprd",
)


class PublicRestError(RuntimeError):
    """Network failure, API-level error, or malformed response."""


def assert_public_path(path: str) -> str:
    """Allow only public statistics paths; refuse private-looking path SEGMENTS.

    Tokens are compared against whole path segments, so the public rubik
    endpoint ``.../long-short-account-ratio-contract`` is fine while
    ``/api/v5/account/balance`` (segment ``account``) is refused.
    """
    lowered = path.lower()
    if not lowered.startswith(ALLOWED_PATH_PREFIXES):
        raise ValueError(f"path {path!r} is not a public OKX statistics endpoint")
    segments = [seg for seg in lowered.split("/") if seg]
    for token in FORBIDDEN_PATH_TOKENS:
        if token in segments:
            raise ValueError(f"forbidden segment {token!r} in public path {path!r}")
    if ".." in segments or "?" in path or "#" in path:
        raise ValueError("path traversal / query in the path is not allowed")
    return path


class OKXPublicRest:
    """GET ``/api/v5/...`` public endpoints and return the ``data`` list."""

    def __init__(
        self,
        base_url: str = "https://www.okx.com",
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = validate_public_rest_base_url(base_url)
        self._timeout = float(timeout)
        self._max_retries = max(1, int(max_retries))
        self._session = session or requests.Session()
        self._sleep = sleep

    def get(self, path: str, params: Optional[Dict[str, str]] = None) -> List:
        assert_public_path(path)
        url = f"{self._base_url}{path}"
        clean = {k: str(v) for k, v in (params or {}).items() if v is not None}
        last_error: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._session.get(url, params=clean, timeout=self._timeout)
                if response.status_code == 429:
                    raise PublicRestError("rate limited (HTTP 429)")
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError, PublicRestError) as exc:
                last_error = exc
                logger.warning(
                    "OKX public request failed",
                    extra={"path": path, "attempt": attempt, "error": str(exc)},
                )
                if attempt < self._max_retries:
                    self._sleep(1.0 * attempt)
                continue
            if not isinstance(payload, dict):
                raise PublicRestError("OKX response was not a JSON object")
            if payload.get("code") != "0":
                raise PublicRestError(
                    f"OKX returned error code {payload.get('code')!r}: {payload.get('msg')!r}"
                )
            data = payload.get("data")
            if not isinstance(data, list):
                raise PublicRestError("OKX response 'data' field was not a list")
            return data
        raise PublicRestError(f"failed after {self._max_retries} attempts: {last_error}")
