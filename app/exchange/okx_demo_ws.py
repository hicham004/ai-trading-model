"""Authenticated OKX DEMO private WebSocket (order/fill updates). Demo-only.

Connects to the DEMO private WS host (``wspap.okx.com``; the production host is
rejected), logs in with a signed ``login`` op, subscribes to the private
``orders`` channel for the configured SPOT instruments, and dispatches parsed
order/fill updates to a handler. Pure helpers (:func:`build_login_args`,
:func:`parse_private_message`) are side-effect-free and fully testable offline.

The signature and secret are never logged. Construction performs no I/O; only
``run`` opens a connection, and only when a connect factory is provided/created.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional

from app.exchange import okx_auth
from app.exchange.credentials import DemoCredentials
from app.exchange.okx_demo_endpoints import DEMO_PRIVATE_WS_URL, validate_demo_ws_url
from app.logging_config import get_logger

logger = get_logger(__name__)

ORDERS_CHANNEL = "orders"


def build_login_args(credentials: DemoCredentials, timestamp: str) -> dict:
    """Build the ``login`` op payload. Timestamp is Unix epoch seconds (string)."""
    sign = okx_auth.sign_ws_login(credentials.secret, timestamp)
    return {
        "op": "login",
        "args": [
            {
                "apiKey": credentials.api_key,
                "passphrase": credentials.passphrase,
                "timestamp": timestamp,
                "sign": sign,
            }
        ],
    }


def build_orders_subscribe(instruments: List[str]) -> dict:
    return {
        "op": "subscribe",
        "args": [
            {"channel": ORDERS_CHANNEL, "instType": "SPOT", "instId": inst}
            for inst in instruments
        ],
    }


@dataclass
class PrivateOutcome:
    """Result of parsing one raw private-WS frame (never raises)."""

    event: Optional[str] = None  # "login" | "subscribe" | "error" | "channel"
    code: Optional[str] = None
    channel: Optional[str] = None
    instrument: Optional[str] = None
    orders: List[dict] = field(default_factory=list)
    ignored: Optional[str] = None


def parse_private_message(raw: object) -> PrivateOutcome:
    """Validate/normalize one private-WS frame. Fails closed (never raises)."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return PrivateOutcome(ignored="non_utf8")
    if not isinstance(raw, str):
        return PrivateOutcome(ignored="not_text")
    text = raw.strip()
    if not text or text == "pong":
        return PrivateOutcome(ignored="empty_or_pong")
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return PrivateOutcome(ignored="invalid_json")
    if not isinstance(payload, dict):
        return PrivateOutcome(ignored="not_object")

    if "event" in payload:
        event = str(payload.get("event"))
        code = str(payload.get("code")) if payload.get("code") is not None else None
        arg = payload.get("arg") if isinstance(payload.get("arg"), dict) else {}
        return PrivateOutcome(
            event=event,
            code=code,
            channel=arg.get("channel"),
            instrument=arg.get("instId"),
        )

    arg = payload.get("arg")
    data = payload.get("data")
    if not isinstance(arg, dict) or not isinstance(data, list):
        return PrivateOutcome(ignored="missing_arg_or_data")
    channel = arg.get("channel")
    if channel != ORDERS_CHANNEL:
        return PrivateOutcome(ignored=f"unsupported_channel:{channel}")
    orders = [row for row in data if isinstance(row, dict)]
    return PrivateOutcome(event="channel", channel=channel, orders=orders)


async def _default_connect(url: str):  # pragma: no cover - needs real network
    validate_demo_ws_url(url)
    import websockets

    return await websockets.connect(url, ping_interval=None, max_queue=64)


class OKXDemoPrivateWebSocket:
    """One authenticated demo private WS connection with reconnect."""

    def __init__(
        self,
        credentials: DemoCredentials,
        *,
        instruments: List[str],
        url: str = DEMO_PRIVATE_WS_URL,
        on_orders: Optional[Callable[[List[dict]], None]] = None,
        on_status: Optional[Callable[[bool], None]] = None,
        on_liveness: Optional[Callable[[], None]] = None,
        connect: Optional[Callable[[str], Awaitable[object]]] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
        ping_interval: float = 20.0,
        login_timeout: float = 10.0,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        if not instruments:
            raise ValueError("at least one instrument is required")
        if connect is None:
            validate_demo_ws_url(url, expected_path="/ws/v5/private")
        self._credentials = credentials
        self._instruments = list(instruments)
        self._url = url
        self._on_orders = on_orders or (lambda rows: None)
        self._on_status = on_status or (lambda authed: None)
        self._on_liveness = on_liveness or (lambda: None)
        self._connect = connect or _default_connect
        self._clock = clock
        self._ping_interval = ping_interval
        self._login_timeout = login_timeout
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._authenticated = False
        self._subscribed = False
        self._last_message_time: Optional[datetime] = None

    @property
    def authenticated(self) -> bool:
        """True only after BOTH login and every orders-channel subscription ack."""
        return self._authenticated and self._subscribed

    @property
    def subscribed(self) -> bool:
        return self._subscribed

    @property
    def last_message_time(self) -> Optional[datetime]:
        return self._last_message_time

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = self._initial_backoff
        try:
            while not stop_event.is_set():
                self._set_authed(False)
                try:
                    conn = await self._connect(self._url)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "demo private connect failed",
                        extra={"error_type": type(exc).__name__},
                    )
                    backoff = await self._wait_backoff(backoff, stop_event)
                    continue
                try:
                    ok = await self._session(conn, stop_event)
                    if ok:
                        backoff = self._initial_backoff
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "demo private session error",
                        extra={"error_type": type(exc).__name__},
                    )
                finally:
                    await self._safe_close(conn)
                if stop_event.is_set():
                    break
                backoff = await self._wait_backoff(backoff, stop_event)
        except asyncio.CancelledError:
            raise
        finally:
            self._set_authed(False)

    async def _session(self, conn, stop_event: asyncio.Event) -> bool:
        ts = okx_auth.epoch_seconds_timestamp(self._clock())
        await conn.send(json.dumps(build_login_args(self._credentials, ts)))
        # Await login result.
        raw = await asyncio.wait_for(conn.recv(), timeout=self._login_timeout)
        self._last_message_time = self._clock()
        outcome = parse_private_message(raw)
        if outcome.event != "login" or outcome.code != "0":
            logger.warning("demo private login failed", extra={"code": outcome.code})
            return False
        self._notify_liveness()
        # Logged in, but NOT yet authenticated for trading: require an explicit
        # subscription acknowledgement for every instrument first (fail closed).
        self._authenticated = True
        self._subscribed = False
        required_subs = {inst for inst in self._instruments}
        acked_subs: set[str] = set()
        await conn.send(json.dumps(build_orders_subscribe(self._instruments)))
        while not stop_event.is_set():
            recv_task = asyncio.ensure_future(conn.recv())
            stop_task = asyncio.ensure_future(stop_event.wait())
            done, pending = await asyncio.wait(
                {recv_task, stop_task},
                timeout=self._ping_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if recv_task not in done:
                if stop_event.is_set():
                    return True
                # heartbeat window: send a ping to keep the session alive
                try:
                    await conn.send("ping")
                except Exception:
                    return True
                continue
            try:
                raw = recv_task.result()
            except Exception:
                return True
            self._last_message_time = self._clock()
            outcome = parse_private_message(raw)
            if outcome.ignored == "empty_or_pong" or outcome.event is not None:
                self._notify_liveness()
            if outcome.event == "error":
                logger.warning("demo private error event", extra={"code": outcome.code})
                return True
            if outcome.event == "subscribe" and outcome.channel == ORDERS_CHANNEL:
                if outcome.instrument:
                    acked_subs.add(outcome.instrument)
                if required_subs <= acked_subs and not self._subscribed:
                    self._subscribed = True
                    self._notify_status(True)
                continue
            if outcome.orders:
                if not self._subscribed:
                    # Defensive: never project order data before full ack.
                    continue
                try:
                    self._on_orders(outcome.orders)
                except Exception as exc:  # pragma: no cover - handler safety
                    logger.error(
                        "demo private order handler failed",
                        extra={"error_type": type(exc).__name__},
                    )
        return True

    def _set_authed(self, value: bool) -> None:
        self._authenticated = value
        if not value:
            self._subscribed = False
        self._notify_status(self.authenticated)

    def _notify_status(self, authed: bool) -> None:
        try:
            self._on_status(authed)
        except Exception:  # pragma: no cover - status callback safety
            pass

    def _notify_liveness(self) -> None:
        try:
            self._on_liveness()
        except Exception:  # pragma: no cover - liveness callback safety
            pass

    async def _wait_backoff(self, backoff: float, stop_event: asyncio.Event) -> float:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
        return min(backoff * 2.0, self._max_backoff)

    async def _safe_close(self, conn) -> None:
        try:
            await conn.close()
        except Exception:  # pragma: no cover - best effort
            pass
