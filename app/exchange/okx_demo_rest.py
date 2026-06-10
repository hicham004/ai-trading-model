"""Authenticated OKX DEMO (simulated) REST client. Demo-only, fail-closed.

Safety properties:

* Every request is signed and carries ``x-simulated-trading: 1`` (built by
  :func:`app.exchange.okx_demo_endpoints.demo_request_headers`). There is no way
  to send a production request.
* Only allowlisted SPOT/account endpoints are reachable; there is NO generic
  arbitrary-endpoint method exposed to callers. Each public method maps to one
  allowlisted ``(method, path)``.
* Order parameters are whitelisted: ``tdMode`` must be ``cash`` (no margin),
  and leverage/position-mode/derivative keys are rejected.
* Secrets are never logged. Request headers and bodies are never logged. Error
  messages contain only the OKX ``code``/``msg`` (which carry no secret).
* A transport failure or timeout raises :class:`OKXDemoTransportError`, which
  callers MUST treat as an UNKNOWN outcome (query by client order id), never as
  a rejection. Non-idempotent POSTs are not auto-retried.
* Construction performs no network I/O. Server-time sync detects clock drift
  and fails closed beyond the configured bound.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Deque, List, Optional

import requests

from app.config import Settings, get_settings
from app.exchange import okx_auth
from app.exchange.credentials import DemoCredentials
from app.exchange.okx_demo_endpoints import (
    ACCOUNT_BALANCE,
    ACCOUNT_CONFIG,
    ACCOUNT_TRADE_FEE,
    PUBLIC_INSTRUMENTS,
    PUBLIC_TIME,
    TRADE_FILLS,
    TRADE_ORDER_AMEND,
    TRADE_ORDER_CANCEL,
    TRADE_ORDER_GET,
    TRADE_ORDER_PLACE,
    TRADE_ORDERS_HISTORY,
    TRADE_ORDERS_PENDING,
    assert_endpoint_allowed,
    demo_request_headers,
    validate_demo_rest_base_url,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

# Whitelisted order parameter keys. Anything margin/leverage/derivative-related
# (lever, posSide, reduceOnly, ccy-margin, tdMode!=cash) is rejected.
_ALLOWED_ORDER_KEYS = {"instId", "tdMode", "side", "ordType", "sz", "px", "clOrdId", "tgtCcy"}
_ALLOWED_ORD_TYPES = {"limit", "post_only", "fok", "ioc", "market"}
_ALLOWED_SIDES = {"buy", "sell"}


class OKXDemoError(RuntimeError):
    """An OKX API-level error (non-zero code). Carries no secret material."""

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class OKXDemoTransportError(OKXDemoError):
    """A transport failure/timeout: the outcome is UNKNOWN, not a rejection."""


@dataclass(frozen=True)
class OKXResponse:
    code: str
    msg: str
    data: list


class _RateLimiter:
    """Bounds requests to ``max_per_window`` within ``window`` seconds."""

    def __init__(
        self,
        max_per_window: int,
        window: float,
        *,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._max = max_per_window
        self._window = window
        self._clock = clock
        self._sleep = sleep
        self._calls: Deque[float] = deque()

    def acquire(self) -> None:
        now = self._clock()
        while self._calls and now - self._calls[0] >= self._window:
            self._calls.popleft()
        if len(self._calls) >= self._max:
            wait = self._window - (now - self._calls[0])
            if wait > 0:
                self._sleep(wait)
            now = self._clock()
            while self._calls and now - self._calls[0] >= self._window:
                self._calls.popleft()
        self._calls.append(self._clock())


class OKXDemoRestClient:
    """Minimal signed client for OKX DEMO SPOT trading + account reads."""

    def __init__(
        self,
        credentials: DemoCredentials,
        *,
        settings: Optional[Settings] = None,
        session: Optional[object] = None,
        clock: Optional[Callable[[], datetime]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._credentials = credentials
        # Validate the origin even when a transport is injected. Dependency
        # injection must never become a way to bypass the demo-only boundary.
        self._base_url = validate_demo_rest_base_url(
            self._settings.okx_demo_rest_base_url
        )
        if session is None:
            session = requests.Session()
        self._session = session
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._server_offset = 0.0  # server_time - local_time, seconds
        self._rate = _RateLimiter(
            self._settings.demo_rate_limit_per_2s,
            2.0,
            clock=self._monotonic,
            sleep=self._sleep,
        )

    # -- time synchronization ----------------------------------------------

    def get_server_time(self) -> datetime:
        resp = self._signed_request(*PUBLIC_TIME)
        if not resp.data or "ts" not in resp.data[0]:
            raise OKXDemoError("server time response missing ts")
        ms = int(resp.data[0]["ts"])
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

    def sync_time(self) -> float:
        """Measure server-vs-local offset; fail closed on excessive drift."""
        local_before = self._clock()
        server = self.get_server_time()
        local_after = self._clock()
        midpoint = local_before + (local_after - local_before) / 2
        offset = (server - midpoint).total_seconds()
        if abs(offset) > self._settings.demo_clock_drift_max_seconds:
            raise OKXDemoError(
                f"clock drift {offset:.3f}s exceeds the allowed "
                f"{self._settings.demo_clock_drift_max_seconds}s"
            )
        self._server_offset = offset
        return offset

    def _signed_now(self) -> datetime:
        from datetime import timedelta

        return self._clock() + timedelta(seconds=self._server_offset)

    # -- account / public reads --------------------------------------------

    def get_account_config(self) -> dict:
        resp = self._signed_request(*ACCOUNT_CONFIG)
        return resp.data[0] if resp.data else {}

    def get_balances(self) -> dict:
        resp = self._signed_request(*ACCOUNT_BALANCE)
        return resp.data[0] if resp.data else {}

    def get_trade_fee(self, instrument: str) -> dict:
        resp = self._signed_request(
            *ACCOUNT_TRADE_FEE, params={"instType": "SPOT", "instId": instrument}
        )
        return resp.data[0] if resp.data else {}

    def get_instruments(self) -> List[dict]:
        resp = self._signed_request(*PUBLIC_INSTRUMENTS, params={"instType": "SPOT"})
        return list(resp.data)

    def get_order(
        self, instrument: str, *, cl_ord_id: Optional[str] = None, ord_id: Optional[str] = None
    ) -> Optional[dict]:
        """Query a single order by client order id (preferred) or order id."""
        if not cl_ord_id and not ord_id:
            raise ValueError("get_order requires cl_ord_id or ord_id")
        params = {"instId": instrument}
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id
        if ord_id:
            params["ordId"] = ord_id
        try:
            resp = self._signed_request(*TRADE_ORDER_GET, params=params)
        except OKXDemoError as exc:
            # OKX returns "order does not exist" as a code; treat as "not found".
            if exc.code == "51603" and not isinstance(exc, OKXDemoTransportError):
                return None
            raise
        return resp.data[0] if resp.data else None

    def get_pending_orders(self, instrument: Optional[str] = None) -> List[dict]:
        params = {"instType": "SPOT"}
        if instrument:
            params["instId"] = instrument
        resp = self._signed_request(*TRADE_ORDERS_PENDING, params=params)
        return list(resp.data)

    def get_orders_history(self, instrument: Optional[str] = None) -> List[dict]:
        params = {"instType": "SPOT"}
        if instrument:
            params["instId"] = instrument
        resp = self._signed_request(*TRADE_ORDERS_HISTORY, params=params)
        return list(resp.data)

    def get_fills(self, instrument: Optional[str] = None) -> List[dict]:
        params = {"instType": "SPOT"}
        if instrument:
            params["instId"] = instrument
        resp = self._signed_request(*TRADE_FILLS, params=params)
        return list(resp.data)

    # -- order mutations ----------------------------------------------------

    def place_order(self, params: dict) -> dict:
        """Place one demo SPOT order. Params are whitelisted (cash, long-only)."""
        body = self._validate_order_params(params)
        resp = self._signed_request(*TRADE_ORDER_PLACE, body=body, allow_retry=False)
        return self._single_order_result(resp)

    def cancel_order(self, instrument: str, cl_ord_id: str) -> dict:
        body = {"instId": instrument, "clOrdId": cl_ord_id}
        resp = self._signed_request(*TRADE_ORDER_CANCEL, body=body, allow_retry=False)
        return self._single_order_result(resp)

    def amend_order(
        self,
        instrument: str,
        cl_ord_id: str,
        *,
        new_size: Optional[str] = None,
        new_price: Optional[str] = None,
    ) -> dict:
        if new_size is None and new_price is None:
            raise ValueError("amend_order requires new_size or new_price")
        body: dict = {"instId": instrument, "clOrdId": cl_ord_id}
        if new_size is not None:
            body["newSz"] = str(new_size)
        if new_price is not None:
            body["newPx"] = str(new_price)
        resp = self._signed_request(*TRADE_ORDER_AMEND, body=body, allow_retry=False)
        return self._single_order_result(resp)

    @staticmethod
    def _validate_order_params(params: dict) -> dict:
        if not isinstance(params, dict):
            raise ValueError("order params must be a dict")
        extra = set(params) - _ALLOWED_ORDER_KEYS
        if extra:
            raise ValueError(f"forbidden order parameter(s): {sorted(extra)}")
        if params.get("tdMode") != "cash":
            raise ValueError("tdMode must be 'cash' (margin/leverage are forbidden)")
        if params.get("side") not in _ALLOWED_SIDES:
            raise ValueError("order side must be 'buy' or 'sell'")
        if params.get("ordType") not in _ALLOWED_ORD_TYPES:
            raise ValueError(f"ordType must be one of {sorted(_ALLOWED_ORD_TYPES)}")
        if not params.get("instId") or not params.get("clOrdId"):
            raise ValueError("order requires instId and clOrdId")
        return dict(params)

    @staticmethod
    def _single_order_result(resp: OKXResponse) -> dict:
        if not resp.data:
            raise OKXDemoError("order response contained no data", code=resp.code)
        row = resp.data[0]
        # Per-order status code: "0" success; otherwise raise with sCode/sMsg.
        scode = str(row.get("sCode", "0"))
        if scode not in ("0", ""):
            smsg = str(row.get("sMsg", "") or "")
            detail = f": {smsg}" if smsg else ""
            raise OKXDemoError(
                f"order rejected (sCode={scode}){detail}", code=scode
            )
        return row

    # -- internal signed request ------------------------------------------

    def _signed_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
        allow_retry: bool = True,
    ) -> OKXResponse:
        assert_endpoint_allowed(method, path)  # fail closed; never generic
        request_path = path
        if params:
            from urllib.parse import urlencode

            request_path = f"{path}?{urlencode(params)}"
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        url = f"{self._base_url}{request_path}"
        max_attempts = self._settings.demo_max_retries if allow_retry else 1
        last_transport: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            timestamp = okx_auth.iso_timestamp(self._signed_now())
            sign = okx_auth.sign_rest(
                self._credentials.secret, timestamp, method, request_path, body_str
            )
            headers = demo_request_headers(
                api_key=self._credentials.api_key,
                sign=sign,
                timestamp=timestamp,
                passphrase=self._credentials.passphrase,
            )
            self._rate.acquire()
            try:
                response = self._session.request(
                    method=method.upper(),
                    url=url,
                    data=body_str if body_str else None,
                    headers=headers,
                    timeout=self._settings.demo_request_timeout,
                )
            except requests.RequestException as exc:
                # Transport failure: outcome UNKNOWN. Only retry idempotent GETs.
                last_transport = exc
                logger.warning(
                    "demo request transport error",
                    extra={
                        "method": method,
                        "path": path,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                    },
                )
                if allow_retry and attempt < max_attempts:
                    self._sleep(0.5 * attempt)
                    continue
                raise OKXDemoTransportError(
                    f"transport error after {attempt} attempt(s): {type(exc).__name__}"
                ) from exc
            return self._parse_response(response, method, path)

        raise OKXDemoTransportError(
            f"transport error: {type(last_transport).__name__ if last_transport else 'unknown'}"
        )

    def _parse_response(self, response: object, method: str, path: str) -> OKXResponse:
        status = getattr(response, "status_code", 0)
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise OKXDemoError(
                f"demo response was not valid JSON (HTTP {status})"
            ) from exc
        if not isinstance(payload, dict):
            raise OKXDemoError("demo response was not a JSON object")
        code = str(payload.get("code", ""))
        msg = str(payload.get("msg", ""))
        data = payload.get("data")
        if not isinstance(data, list):
            data = []
        if status == 429 or code in {"50011", "50061"}:  # rate limited
            raise OKXDemoTransportError(f"rate limited (HTTP {status}, code {code})", code=code)
        if status >= 500:
            raise OKXDemoTransportError(f"server error HTTP {status}", code=code)
        order_mutation_paths = {
            TRADE_ORDER_PLACE[1],
            TRADE_ORDER_CANCEL[1],
            TRADE_ORDER_AMEND[1],
        }
        if code != "0" and path in order_mutation_paths and data:
            # OKX commonly returns top-level code "1" / "All operations
            # failed" while the actionable per-order sCode/sMsg is in data.
            # Let the mutation-specific parser surface that precise rejection.
            return OKXResponse(code=code, msg=msg, data=data)
        if code != "0":
            # API-level error. msg comes from OKX and contains no secret.
            raise OKXDemoError(f"OKX error code {code}: {msg}", code=code)
        logger.info(
            "demo request ok",
            extra={"method": method, "path": path, "rows": len(data)},
        )
        return OKXResponse(code=code, msg=msg, data=data)
