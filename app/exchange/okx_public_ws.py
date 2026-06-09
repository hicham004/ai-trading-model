"""OKX public WebSocket adapter (Phase 3A) - PUBLIC, UNAUTHENTICATED only.

This adapter connects to OKX's public market-data WebSocket, subscribes to
ticker / trades / candle channels for approved instruments, validates and
normalizes messages, and writes them into a :class:`MarketState`.

Safety:
- It only ever connects to the UNAUTHENTICATED public/business market-data
  WebSocket URLs, and the production connect path validates the URL scheme,
  host, port, and path (no private/arbitrary/insecure URLs).
- It sends no API key, login, or signature, and subscribes to no account or
  order channels. Only ``tickers``, ``trades``, and ``candle1m`` are allowed.
- It never evaluates strategies, generates signals, or places orders.
- Importing this module opens no connection; ``websockets`` is imported lazily
  inside the default connect factory, which only runs when ``run`` is awaited.

Connection correctness (Codex Phase 3A review):
- A feed is only reported CONNECTED once every requested subscription has been
  acknowledged; a subscription error or ack timeout closes and reconnects.
- A failed client heartbeat (ping) terminates the session and reconnects.
- Each feed (public ticker/trade vs business candle) has its own health.

Endpoints (both public/unauthenticated):
- ``tickers`` / ``trades``  -> public WS (``/ws/v5/public``)
- ``candle1m``              -> business WS (``/ws/v5/business``)
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlsplit

from app.exchange.base import PublicMarketDataAdapter
from app.live.market_state import MarketState
from app.live.schemas import (
    CandleUpdate,
    ConnectionStatus,
    TickerUpdate,
    TradeUpdate,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

OKX_PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_BUSINESS_WS_URL = "wss://ws.okx.com:8443/ws/v5/business"

SUPPORTED_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")

TICKERS_CHANNEL = "tickers"
TRADES_CHANNEL = "trades"
CANDLE_CHANNEL = "candle1m"
APPROVED_CHANNELS = (TICKERS_CHANNEL, TRADES_CHANNEL, CANDLE_CHANNEL)

PUBLIC_FEED_ID = "okx-public"
BUSINESS_FEED_ID = "okx-business"

# Approved (public, unauthenticated) endpoint scope for the production path.
_APPROVED_WS_HOST = "ws.okx.com"
_APPROVED_WS_PORTS = (None, 443, 8443)
_APPROVED_WS_PATHS = ("/ws/v5/public", "/ws/v5/business")

Update = Union[TickerUpdate, TradeUpdate, CandleUpdate]


def validate_public_ws_url(url: str, *, expected_path: Optional[str] = None) -> str:
    """Validate a production OKX public market-data WebSocket URL (fail closed).

    Allows only ``wss://`` to the approved OKX host and public/business paths,
    with no credentials, query, or fragment. Rejects ``ws://``, private or
    arbitrary hosts/paths, query-manipulated, and malformed URLs.
    """
    try:
        parts = urlsplit(url)
    except Exception as exc:  # pragma: no cover - urlsplit rarely raises
        raise ValueError(f"malformed WebSocket URL {url!r}: {exc}") from exc

    if parts.scheme != "wss":
        raise ValueError(f"insecure or non-wss WebSocket URL: {url!r}")
    if parts.username or parts.password:
        raise ValueError("credentials are not allowed in the WebSocket URL")
    if parts.hostname != _APPROVED_WS_HOST:
        raise ValueError(f"WebSocket host not approved: {parts.hostname!r}")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"malformed WebSocket port in {url!r}") from exc
    if port not in _APPROVED_WS_PORTS:
        raise ValueError(f"WebSocket port not approved: {port!r}")
    if parts.path not in _APPROVED_WS_PATHS:
        raise ValueError(f"WebSocket path not approved: {parts.path!r}")
    if expected_path is not None and parts.path != expected_path:
        raise ValueError(
            f"WebSocket path {parts.path!r} does not match required "
            f"{expected_path!r}"
        )
    if parts.query or parts.fragment:
        raise ValueError("query/fragment is not allowed in the WebSocket URL")
    return url


def candle_timeframe(channel: str) -> str:
    """Map an OKX candle channel (e.g. ``candle1m``) to a timeframe (``1m``)."""
    return channel[len("candle"):] if channel.startswith("candle") else channel


def endpoint_for_channel(channel: str, *, public_url: str, business_url: str) -> str:
    """Return the (public, unauthenticated) WS URL that serves ``channel``."""
    if channel in (TICKERS_CHANNEL, TRADES_CHANNEL):
        return public_url
    if channel == CANDLE_CHANNEL:
        return business_url
    raise ValueError(f"Unsupported channel: {channel!r}")


@dataclass
class ParseOutcome:
    """Result of parsing one raw OKX frame."""

    updates: List[Update] = field(default_factory=list)
    event: Optional[str] = None  # "subscribe" | "error" | None
    event_arg: Optional[dict] = None
    error_code: Optional[str] = None
    ignored: List[str] = field(default_factory=list)  # reasons


def _to_finite_float(value: object) -> Optional[float]:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _to_utc_from_ms(value: object) -> Optional[datetime]:
    try:
        ms = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_okx_message(
    raw: Union[str, bytes],
    supported_instruments: Sequence[str] = SUPPORTED_INSTRUMENTS,
) -> ParseOutcome:
    """Validate and normalize one raw OKX frame. Never raises (fails closed)."""
    outcome = ParseOutcome()

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            outcome.ignored.append("non_utf8")
            return outcome

    text = raw.strip()
    if not text:
        outcome.ignored.append("empty")
        return outcome

    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        outcome.ignored.append("invalid_json")
        return outcome

    if not isinstance(payload, dict):
        outcome.ignored.append("not_an_object")
        return outcome

    if "event" in payload:
        outcome.event = str(payload.get("event"))
        arg = payload.get("arg")
        outcome.event_arg = arg if isinstance(arg, dict) else None
        if outcome.event == "error":
            outcome.error_code = str(payload.get("code"))
        return outcome

    arg = payload.get("arg")
    data = payload.get("data")
    if not isinstance(arg, dict) or not isinstance(data, list):
        outcome.ignored.append("missing_arg_or_data")
        return outcome

    channel = arg.get("channel")
    instrument = arg.get("instId")
    if not isinstance(channel, str) or not isinstance(instrument, str):
        outcome.ignored.append("missing_channel_or_instrument")
        return outcome
    if channel not in APPROVED_CHANNELS:
        outcome.ignored.append(f"unsupported_channel:{channel}")
        return outcome
    if instrument not in supported_instruments:
        outcome.ignored.append(f"unsupported_instrument:{instrument}")
        return outcome

    for row in data:
        if channel == TICKERS_CHANNEL:
            update = _parse_ticker_row(row, instrument)
        elif channel == TRADES_CHANNEL:
            update = _parse_trade_row(row, instrument)
        else:  # CANDLE_CHANNEL
            update = _parse_candle_row(row, instrument, candle_timeframe(channel))
        if update is None:
            outcome.ignored.append(f"invalid_row:{channel}")
        else:
            outcome.updates.append(update)

    return outcome


def _parse_ticker_row(row: object, instrument: str) -> Optional[TickerUpdate]:
    if not isinstance(row, dict):
        return None
    # Identity: the row's instId must exist and exactly match the arg instId.
    if row.get("instId") != instrument:
        return None
    ts = _to_utc_from_ms(row.get("ts"))
    last = _to_finite_float(row.get("last"))
    bid = _to_finite_float(row.get("bidPx"))
    ask = _to_finite_float(row.get("askPx"))
    if ts is None or last is None or bid is None or ask is None:
        return None
    if last <= 0 or bid <= 0 or ask <= 0:
        return None
    if bid > ask:  # incoherent quote
        return None
    return TickerUpdate(
        instrument=instrument, timestamp=ts, last=last, bid=bid, ask=ask
    )


def _parse_trade_row(row: object, instrument: str) -> Optional[TradeUpdate]:
    if not isinstance(row, dict):
        return None
    if row.get("instId") != instrument:
        return None
    ts = _to_utc_from_ms(row.get("ts"))
    price = _to_finite_float(row.get("px"))
    size = _to_finite_float(row.get("sz"))
    side = row.get("side")
    trade_id = row.get("tradeId")
    if ts is None or price is None or size is None:
        return None
    if price <= 0 or size <= 0:  # require a positive trade size
        return None
    if not isinstance(side, str) or side not in ("buy", "sell"):
        return None
    if not isinstance(trade_id, str) or not trade_id:
        return None
    return TradeUpdate(
        instrument=instrument,
        timestamp=ts,
        price=price,
        size=size,
        side=side,
        trade_id=trade_id,
    )


def _parse_candle_row(
    row: object, instrument: str, timeframe: str
) -> Optional[CandleUpdate]:
    # OKX candle rows are arrays: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        return None
    ts = _to_utc_from_ms(row[0])
    o = _to_finite_float(row[1])
    h = _to_finite_float(row[2])
    low = _to_finite_float(row[3])
    c = _to_finite_float(row[4])
    vol = _to_finite_float(row[5])
    if ts is None or None in (o, h, low, c, vol):
        return None
    if min(o, h, low, c) <= 0 or vol < 0:  # type: ignore[arg-type]
        return None
    # Coherent OHLC: high is the max, low is the min.
    if h < max(o, c, low) or low > min(o, c, h):  # type: ignore[type-var]
        return None
    confirmed = len(row) >= 9 and str(row[8]) == "1"
    return CandleUpdate(
        instrument=instrument,
        timeframe=timeframe,
        timestamp=ts,  # type: ignore[arg-type]
        open=o,  # type: ignore[arg-type]
        high=h,  # type: ignore[arg-type]
        low=low,  # type: ignore[arg-type]
        close=c,  # type: ignore[arg-type]
        volume=vol,  # type: ignore[arg-type]
        confirmed=confirmed,
    )


@dataclass
class _Subscription:
    channel: str
    instrument: str

    def as_arg(self) -> Dict[str, str]:
        return {"channel": self.channel, "instId": self.instrument}

    def label(self) -> str:
        return f"{self.channel}:{self.instrument}"


class _SubscriptionSession:
    """Tracks which requested subscriptions have been acknowledged."""

    def __init__(self, subscriptions: Sequence[_Subscription]) -> None:
        self._required: set[Tuple[str, str]] = {
            (s.channel, s.instrument) for s in subscriptions
        }
        self._acked: set[Tuple[str, str]] = set()

    def record_ack(self, arg: Optional[dict]) -> str:
        """Return "ok" if a valid new ack was recorded, else "invalid"."""
        if not isinstance(arg, dict):
            return "invalid"
        key = (arg.get("channel"), arg.get("instId"))
        if key not in self._required:
            return "invalid"  # unexpected (not requested)
        if key in self._acked:
            return "invalid"  # duplicate
        self._acked.add(key)
        return "ok"

    def fully_acked(self) -> bool:
        return self._required == self._acked

    def acked_labels(self) -> List[str]:
        return [f"{channel}:{inst}" for (channel, inst) in sorted(self._acked)]


async def _default_connect(url: str):  # pragma: no cover - needs real network
    """Open a real OKX public WebSocket. Validates the URL; only public URLs."""
    validate_public_ws_url(url)
    import websockets  # local import keeps module import side-effect free

    return await websockets.connect(url, ping_interval=None, max_queue=64)


class OKXPublicWebSocketAdapter(PublicMarketDataAdapter):
    """One public/unauthenticated OKX WebSocket connection with reconnect."""

    def __init__(
        self,
        market_state: MarketState,
        url: str,
        subscriptions: Sequence[_Subscription],
        *,
        feed_id: str = PUBLIC_FEED_ID,
        connect: Optional[Callable[[str], Awaitable["object"]]] = None,
        supported_instruments: Sequence[str] = SUPPORTED_INSTRUMENTS,
        ping_interval: float = 20.0,
        ack_timeout: float = 10.0,
        initial_backoff: float = 1.0,
        backoff_factor: float = 2.0,
        max_backoff: float = 30.0,
        on_backoff: Optional[Callable[[float], None]] = None,
    ) -> None:
        if not subscriptions:
            raise ValueError("at least one subscription is required")
        if not feed_id.strip():
            raise ValueError("feed_id must not be empty")
        subscription_keys = [
            (subscription.channel, subscription.instrument)
            for subscription in subscriptions
        ]
        if len(subscription_keys) != len(set(subscription_keys)):
            raise ValueError("duplicate subscriptions are not allowed")
        for subscription in subscriptions:
            if subscription.channel not in APPROVED_CHANNELS:
                raise ValueError(
                    f"Unsupported channel: {subscription.channel!r}"
                )
            if subscription.instrument not in supported_instruments:
                raise ValueError(
                    f"Unsupported instrument: {subscription.instrument!r}"
                )
        for label, value in (
            ("ping_interval", ping_interval),
            ("ack_timeout", ack_timeout),
            ("initial_backoff", initial_backoff),
            ("max_backoff", max_backoff),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be a positive finite number")
        if not math.isfinite(backoff_factor) or backoff_factor < 1:
            raise ValueError("backoff_factor must be finite and at least 1")
        if max_backoff < initial_backoff:
            raise ValueError("max_backoff must be greater than or equal to initial_backoff")
        if connect is None:
            channels = {subscription.channel for subscription in subscriptions}
            if channels <= {TICKERS_CHANNEL, TRADES_CHANNEL}:
                expected_path = "/ws/v5/public"
            elif channels == {CANDLE_CHANNEL}:
                expected_path = "/ws/v5/business"
            else:
                raise ValueError(
                    "one production connection cannot mix public and business "
                    "channel subscriptions"
                )
            validate_public_ws_url(url, expected_path=expected_path)

        self._state = market_state
        self._url = url
        self._subscriptions = list(subscriptions)
        self.feed_id = feed_id
        self.name = feed_id
        self._connect = connect or _default_connect
        self._supported = tuple(supported_instruments)
        self.ping_interval = ping_interval
        self.ack_timeout = ack_timeout
        self.initial_backoff = initial_backoff
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        self._on_backoff = on_backoff or (lambda _delay: None)
        # Registration performs no I/O and ensures aggregate health knows every
        # required feed before any adapter task gets a chance to run.
        self._state.register_feed(self.feed_id, self.subscription_labels())

    def subscription_labels(self) -> List[str]:
        return [s.label() for s in self._subscriptions]

    # -- main loop ----------------------------------------------------------

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = self.initial_backoff
        try:
            while not stop_event.is_set():
                self._state.set_feed_status(self.feed_id, ConnectionStatus.CONNECTING)
                self._state.reset_feed_acks(self.feed_id)
                try:
                    conn = await self._connect(self._url)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "live connect failed",
                        extra={"feed": self.feed_id, "url": self._url, "error": str(exc)},
                    )
                    backoff = await self._backoff_then_continue(backoff, stop_event)
                    continue

                acked = False
                try:
                    await self._subscribe(conn)
                    stopped, acked = await self._session_loop(conn, stop_event)
                    if stopped:
                        break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "live session error",
                        extra={"feed": self.feed_id, "error": str(exc)},
                    )
                finally:
                    await self._safe_close(conn)

                if stop_event.is_set():
                    break
                if acked:
                    backoff = self.initial_backoff  # healthy session -> reset
                backoff = await self._backoff_then_continue(backoff, stop_event)
        except asyncio.CancelledError:
            logger.info("live stream cancelled", extra={"feed": self.feed_id})
            raise
        finally:
            self._state.set_feed_status(self.feed_id, ConnectionStatus.STOPPED)

    async def _backoff_then_continue(self, backoff: float, stop_event: asyncio.Event) -> float:
        self._state.set_feed_status(self.feed_id, ConnectionStatus.RECONNECTING)
        self._on_backoff(backoff)
        await self._sleep_with_stop(backoff, stop_event)
        return min(backoff * self.backoff_factor, self.max_backoff)

    async def _sleep_with_stop(self, seconds: float, stop_event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return

    async def _subscribe(self, conn) -> None:
        # Send the subscribe request. We do NOT mark the feed CONNECTED or record
        # acknowledged subscriptions here - only once acknowledgements arrive.
        message = {"op": "subscribe", "args": [s.as_arg() for s in self._subscriptions]}
        await conn.send(json.dumps(message))

    async def _session_loop(self, conn, stop_event: asyncio.Event) -> Tuple[bool, bool]:
        """Process one connection. Returns (stopped, reached_full_ack)."""
        loop = asyncio.get_running_loop()
        session = _SubscriptionSession(self._subscriptions)
        ack_deadline = loop.time() + self.ack_timeout
        acked = False

        while not stop_event.is_set():
            if not acked:
                remaining = ack_deadline - loop.time()
                if remaining <= 0:
                    logger.warning(
                        "subscription acknowledgement timed out; reconnecting",
                        extra={"feed": self.feed_id},
                    )
                    return (False, False)
                timeout = min(self.ping_interval, remaining)
            else:
                timeout = self.ping_interval

            recv_task = asyncio.ensure_future(conn.recv())
            stop_task = asyncio.ensure_future(stop_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {recv_task, stop_task},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError:
                await self._cancel_tasks(recv_task, stop_task)
                raise

            await self._cancel_tasks(
                *[t for t in (recv_task, stop_task) if not t.done()]
            )

            if stop_event.is_set():
                return (True, acked)
            if recv_task not in done:
                # Heartbeat window elapsed with no frame.
                if not acked:
                    continue  # keep waiting for acks until the deadline
                if not await self._send_heartbeat(conn):
                    return (False, acked)  # failed ping -> reconnect
                continue

            try:
                raw = recv_task.result()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "live recv failed; will reconnect",
                    extra={"feed": self.feed_id, "error": str(exc)},
                )
                return (False, acked)

            signal = await self._process_frame(conn, raw, session)
            if signal == "reconnect":
                return (False, acked)
            if signal == "ack_complete":
                acked = True
                self._state.set_feed_acked(self.feed_id, session.acked_labels())
                self._state.set_feed_status(self.feed_id, ConnectionStatus.CONNECTED)
                logger.info(
                    "feed subscriptions acknowledged",
                    extra={"feed": self.feed_id, "subscriptions": session.acked_labels()},
                )
        return (True, acked)

    async def _process_frame(self, conn, raw: Union[str, bytes], session) -> str:
        # Any received frame counts as transport liveness (NOT market-data
        # freshness, which only valid accepted updates refresh).
        self._state.mark_feed_transport(self.feed_id)
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        stripped = text.strip()
        if stripped == "pong":
            return "ok"
        if stripped == "ping":  # defensive; OKX clients normally initiate ping
            await self._send_pong(conn)
            return "ok"

        outcome = parse_okx_message(text, self._supported)
        if outcome.event == "error":
            logger.warning(
                "okx error event; reconnecting",
                extra={"feed": self.feed_id, "code": outcome.error_code},
            )
            return "reconnect"
        if outcome.event == "subscribe":
            if session.record_ack(outcome.event_arg) != "ok":
                logger.warning(
                    "unexpected or duplicate subscription ack; reconnecting",
                    extra={"feed": self.feed_id, "arg": outcome.event_arg},
                )
                return "reconnect"
            self._state.set_feed_acked(self.feed_id, session.acked_labels())
            return "ack_complete" if session.fully_acked() else "ok"
        if outcome.event is not None:
            logger.warning(
                "unexpected OKX control event; reconnecting",
                extra={"feed": self.feed_id, "event": outcome.event},
            )
            return "reconnect"

        if outcome.updates and not session.fully_acked():
            logger.debug(
                "ignored market data before all subscriptions were acknowledged",
                extra={"feed": self.feed_id},
            )
            return "ok"

        for update in outcome.updates:
            self._apply_update(update)
        for reason in outcome.ignored:
            logger.debug("ignored live message", extra={"feed": self.feed_id, "reason": reason})
        return "ok"

    def _apply_update(self, update: Update) -> bool:
        # MarketState refreshes the feed's market-data freshness only on accept.
        if isinstance(update, TickerUpdate):
            return self._state.apply_ticker(update, self.feed_id)
        if isinstance(update, TradeUpdate):
            return self._state.apply_trade(update, self.feed_id)
        if isinstance(update, CandleUpdate):
            return self._state.apply_candle(update, self.feed_id)
        return False  # pragma: no cover - defensive

    async def _send_heartbeat(self, conn) -> bool:
        """Send a client ping. Returns False on failure (never hidden)."""
        try:
            await conn.send("ping")
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "heartbeat send failed; reconnecting",
                extra={"feed": self.feed_id, "error": str(exc)},
            )
            return False

    async def _send_pong(self, conn) -> None:
        # Best-effort courtesy reply to a server ping. If the connection is
        # broken, the next recv fails and triggers reconnect anyway.
        try:
            await conn.send("pong")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("pong send failed", extra={"feed": self.feed_id, "error": str(exc)})

    @staticmethod
    async def _cancel_tasks(*tasks: "asyncio.Future") -> None:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # pragma: no cover - loser task errors are irrelevant
                pass

    async def _safe_close(self, conn) -> None:
        try:
            await conn.close()
        except asyncio.CancelledError:  # pragma: no cover - best effort on cancel
            pass
        except Exception:  # pragma: no cover - best effort
            pass


def build_subscriptions(
    instruments: Sequence[str],
    channels: Sequence[str],
) -> List[_Subscription]:
    """Build (channel, instrument) subscriptions, validating both."""
    if len(instruments) != len(set(instruments)):
        raise ValueError("duplicate instruments are not allowed")
    if len(channels) != len(set(channels)):
        raise ValueError("duplicate channels are not allowed")
    subs: List[_Subscription] = []
    for instrument in instruments:
        if instrument not in SUPPORTED_INSTRUMENTS:
            raise ValueError(f"Unsupported instrument: {instrument!r}")
        for channel in channels:
            if channel not in APPROVED_CHANNELS:
                raise ValueError(f"Unsupported channel: {channel!r}")
            subs.append(_Subscription(channel=channel, instrument=instrument))
    return subs


def build_default_adapters(
    market_state: MarketState,
    instruments: Sequence[str] = SUPPORTED_INSTRUMENTS,
    *,
    public_url: str = OKX_PUBLIC_WS_URL,
    business_url: str = OKX_BUSINESS_WS_URL,
    candle_channel: str = CANDLE_CHANNEL,
    connect: Optional[Callable[[str], Awaitable["object"]]] = None,
    **adapter_kwargs,
) -> List[OKXPublicWebSocketAdapter]:
    """Build the standard Phase 3A adapters (validates the production config).

    Tickers and trades use the public WS feed; the candle channel uses the
    business WS feed. Both are public and unauthenticated. Returns one adapter
    per feed, each with its own feed id and health.
    """
    # Validate the production endpoint scope up front (fail closed). A test may
    # still inject ``connect`` to use a fake connection without real URLs.
    validate_public_ws_url(public_url, expected_path="/ws/v5/public")
    validate_public_ws_url(business_url, expected_path="/ws/v5/business")
    if candle_channel != CANDLE_CHANNEL:
        raise ValueError(f"Unsupported candle channel: {candle_channel!r}")

    public_subs = build_subscriptions(instruments, [TICKERS_CHANNEL, TRADES_CHANNEL])
    business_subs = build_subscriptions(instruments, [candle_channel])

    return [
        OKXPublicWebSocketAdapter(
            market_state, public_url, public_subs,
            feed_id=PUBLIC_FEED_ID, connect=connect, **adapter_kwargs,
        ),
        OKXPublicWebSocketAdapter(
            market_state, business_url, business_subs,
            feed_id=BUSINESS_FEED_ID, connect=connect, **adapter_kwargs,
        ),
    ]


async def run_adapters(
    adapters: Sequence[OKXPublicWebSocketAdapter], stop_event: asyncio.Event
) -> None:
    """Run adapters together, cancelling every sibling if one exits."""
    tasks = [
        asyncio.create_task(adapter.run(stop_event), name=f"feed:{adapter.feed_id}")
        for adapter in adapters
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
