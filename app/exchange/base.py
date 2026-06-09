"""Exchange-neutral public market-data adapter interface.

An adapter connects to a venue's PUBLIC market-data feed, normalizes messages
into the value objects in :mod:`app.live.schemas`, and writes them into a
:class:`~app.live.market_state.MarketState`. It owns connection lifecycle
concerns (subscribe, heartbeat, reconnect) but knows nothing about strategies,
risk, brokers, accounts, or orders.

Design rules:

* Constructing an adapter performs no I/O; only :meth:`run` opens a connection.
* :meth:`run` must be cancellation-safe and must stop promptly when the
  provided ``stop_event`` is set.
* Adapters consume UNAUTHENTICATED public data only.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import List


class PublicMarketDataAdapter(ABC):
    """Base class for live public market-data adapters."""

    #: Human-readable adapter name (e.g. "okx-public-ws").
    name: str = "unknown"

    @abstractmethod
    async def run(self, stop_event: asyncio.Event) -> None:
        """Stream public market data until ``stop_event`` is set or cancelled.

        Implementations connect, subscribe, handle heartbeats, and reconnect
        with bounded backoff, writing normalized updates into the market state
        supplied at construction time. The coroutine returns when the stop
        event is set and must re-raise :class:`asyncio.CancelledError`.
        """
        raise NotImplementedError

    @abstractmethod
    def subscription_labels(self) -> List[str]:
        """Return human-readable subscription descriptions (for health/logs)."""
        raise NotImplementedError
