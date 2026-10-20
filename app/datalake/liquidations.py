"""Public OKX ``liquidation-orders`` WebSocket collector -> JSON lines (features only).

This is a *separate*, read-only public WebSocket consumer. It is intentionally
not wired into the reviewed market-data client (whose channel allowlist is part
of the trading path): it has no account, order, or strategy coupling and can
only append JSON lines under ``data/lake/liquidations/<instrument>/<day>.jsonl``.

Connection: ``wss://ws.okx.com/ws/v5/public`` (no port — OKX retires :8443 on
Oct 31, 2026), subscribe ``{"channel": "liquidation-orders", "instType": "SWAP"}``,
answer the idle timeout with a text ``ping`` every 20 s, reconnect with backoff.
Only ``BTC-USDT-SWAP`` / ``ETH-USDT-SWAP`` records are kept.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from app.datalake.derivatives import SWAP_INSTRUMENTS
from app.datalake.layout import LakeLayout
from app.exchange.okx_public_ws import validate_public_ws_url
from app.logging_config import get_logger

logger = get_logger(__name__)

PUBLIC_WS_URL = "wss://ws.okx.com/ws/v5/public"
CHANNEL = "liquidation-orders"
PING_INTERVAL_SECONDS = 20.0


def subscribe_message(inst_type: str = "SWAP") -> str:
    if inst_type != "SWAP":
        raise ValueError("only the SWAP liquidation feed is collected")
    return json.dumps({"op": "subscribe", "args": [{"channel": CHANNEL, "instType": inst_type}]})


def _num(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_liquidation_message(
    raw: str,
    *,
    instruments: Sequence[str] = SWAP_INSTRUMENTS,
    observed_at: Optional[datetime] = None,
) -> List[dict]:
    """Flatten one channel push into records; events/pongs/other channels -> []."""
    if raw == "pong":
        return []
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(message, dict) or "event" in message:
        return []
    arg = message.get("arg") or {}
    if arg.get("channel") != CHANNEL:
        return []
    observed = (observed_at or datetime.now(tz=timezone.utc)).isoformat(timespec="milliseconds")
    records: List[dict] = []
    for item in message.get("data") or []:
        if not isinstance(item, dict):
            continue
        instrument = item.get("instId")
        if instrument not in instruments:
            continue
        for detail in item.get("details") or []:
            if not isinstance(detail, dict):
                continue
            try:
                ts_ms = int(detail.get("ts"))
            except (TypeError, ValueError):
                continue
            if ts_ms <= 0:
                continue
            records.append(
                {
                    "ts_ms": ts_ms,
                    "time": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds"),
                    "instrument": instrument,
                    "inst_type": item.get("instType"),
                    "side": detail.get("side"),
                    "pos_side": detail.get("posSide"),
                    "bankruptcy_px": _num(detail.get("bkPx")),
                    "size": _num(detail.get("sz")),
                    "bankruptcy_loss": _num(detail.get("bkLoss")),
                    "ccy": detail.get("ccy") or "",
                    "observed_at": observed,
                }
            )
    return records


class JsonlSink:
    """Append records to ``liquidations/<instrument>/<YYYY-MM-DD>.jsonl`` (UTC day of ``ts_ms``)."""

    def __init__(self, layout: LakeLayout) -> None:
        self._layout = layout
        self.records_written = 0

    def write(self, records: Iterable[dict]) -> int:
        grouped: Dict[tuple, List[str]] = {}
        for record in records:
            day = datetime.fromtimestamp(record["ts_ms"] / 1000, tz=timezone.utc).date()
            grouped.setdefault((record["instrument"], day), []).append(json.dumps(record, sort_keys=True))
        written = 0
        for (instrument, day), lines in grouped.items():
            path = self._layout.liquidations_file(instrument, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            written += len(lines)
        self.records_written += written
        return written


@dataclass
class CollectorStats:
    messages: int = 0
    records: int = 0
    connects: int = 0
    reconnects: int = 0
    errors: int = 0
    last_error: str = ""
    notes: List[str] = field(default_factory=list)


async def run_collector(
    sink: JsonlSink,
    *,
    duration_seconds: float,
    url: str = PUBLIC_WS_URL,
    instruments: Sequence[str] = SWAP_INSTRUMENTS,
    connect: Optional[Callable] = None,
    clock: Callable[[], float] = time.monotonic,
    ping_interval: float = PING_INTERVAL_SECONDS,
    max_backoff: float = 30.0,
) -> CollectorStats:
    """Collect liquidation records for ``duration_seconds`` then return stats."""
    validate_public_ws_url(url, expected_path="/ws/v5/public")
    for inst in instruments:
        if inst not in SWAP_INSTRUMENTS:
            raise ValueError(f"instrument {inst!r} not allowed; allowed: {SWAP_INSTRUMENTS}")
    if connect is None:  # pragma: no cover - exercised live, not in the offline suite
        import websockets

        connect = websockets.connect

    stats = CollectorStats()
    deadline = clock() + float(duration_seconds)
    initial_backoff = min(1.0, float(max_backoff))
    backoff = initial_backoff
    while clock() < deadline:
        try:
            async with connect(url) as ws:
                stats.connects += 1
                await ws.send(subscribe_message("SWAP"))
                backoff = initial_backoff
                last_ping = clock()
                while clock() < deadline:
                    remaining = deadline - clock()
                    wait = max(0.05, min(ping_interval - (clock() - last_ping), remaining))
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=wait)
                    except asyncio.TimeoutError:
                        if clock() - last_ping >= ping_interval:
                            await ws.send("ping")
                            last_ping = clock()
                        continue
                    stats.messages += 1
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    records = parse_liquidation_message(raw, instruments=instruments)
                    if records:
                        stats.records += sink.write(records)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # network / protocol errors: reconnect with backoff
            stats.errors += 1
            stats.last_error = f"{type(exc).__name__}: {exc}"[:200]
            remaining = deadline - clock()
            if remaining <= 0:
                break
            stats.reconnects += 1
            await asyncio.sleep(min(backoff, remaining))
            backoff = min(backoff * 2, max_backoff)
    return stats
