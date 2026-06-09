"""Lifecycle helper for Phase 3 public-data services."""

from __future__ import annotations

import asyncio
from typing import Optional, Sequence

from app.exchange.okx_public_ws import (
    OKXPublicWebSocketAdapter,
    run_adapters,
)
from app.live.persistence import LiveDataPersistence


async def run_live_runtime(
    adapters: Sequence[OKXPublicWebSocketAdapter],
    stop_event: asyncio.Event,
    persistence: Optional[LiveDataPersistence] = None,
) -> None:
    """Run WebSocket adapters and optional persistence as one supervised unit."""
    tasks = [
        asyncio.create_task(
            run_adapters(adapters, stop_event),
            name="live-public-websockets",
        )
    ]
    if persistence is not None:
        tasks.append(
            asyncio.create_task(
                persistence.run(stop_event),
                name="live-public-persistence",
            )
        )
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
