"""OKX PUBLIC positioning series for the research markets (plan row R17, SIMULATION ONLY).

The S5 positioning filter reads a perpetual swap's funding-rate history and
open-interest history. The app's collector (``app.datalake.derivatives``) is
bounded to ``BTC-USDT-SWAP`` and ``ETH-USDT-SWAP`` by ``SWAP_INSTRUMENTS``, a
bound that also serves the demo and paper trading code and is NOT widened
here. The paper fleet, however, may run a configuration confirmed on one of
the replication study's markets (plan row R12, ``research.markets``), and its
S5 filter needs that market's own swap data; until this module existed the
fleet asked the app's collector for ``SOL-USDT-SWAP``, got ``not allowed``
every 30 minutes, and the filter passed for lack of data.

This module is the research-side counterpart, the R12 precedent
(``research/replication_data.py``) applied to positioning data:

- GET only, through the path-allowlisted
  :class:`app.datalake.okx_public_rest.OKXPublicRest` (no headers, no keys),
  on the same two public endpoints the app uses,
  ``/api/v5/public/funding-rate-history`` and
  ``/api/v5/rubik/stat/contracts/open-interest-history`` (the path constants
  and the row parsers are the app's own, so the stored rows are identical in
  shape to the BTC/ETH rows; only the instrument bound differs);
- bounded to the research markets' swaps (``RESEARCH_SWAP_FOR``): the Sprint
  2c pair is refused here on purpose, so BTC/ETH data can only ever come
  through the app's reviewed path, and anything else is refused too.

Nothing here can authenticate, place an order or reach an account.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.datalake.derivatives import (
    FUNDING_PATH,
    OPEN_INTEREST_PATH,
    PAGE_LIMIT,
    PERIODS,
    parse_funding_rows,
    parse_open_interest_rows,
)
from app.datalake.okx_public_rest import OKXPublicRest
from research.markets import RESEARCH_SWAP_FOR

#: The OKX perpetual swaps this module may ask for: one per replication market, never the Sprint 2c pair.
RESEARCH_SWAPS: Tuple[str, ...] = tuple(sorted(RESEARCH_SWAP_FOR.values()))


class PositioningDataError(ValueError):
    """Asked for a swap outside the research markets (the fleet logs it and goes on without that series)."""


def is_research_swap(swap: str) -> bool:
    return swap in RESEARCH_SWAPS


def _check_swap(swap: str) -> str:
    if swap not in RESEARCH_SWAPS:
        raise PositioningDataError(f"{swap!r} is not a research market's swap; known: {RESEARCH_SWAPS}")
    return swap


def _check_period(period: str) -> str:
    if period not in PERIODS:
        raise PositioningDataError(f"period {period!r} not allowed; allowed: {PERIODS}")
    return period


def fetch_research_funding_history(rest: OKXPublicRest, swap: str, *, after_ms: Optional[int] = None, limit: int = PAGE_LIMIT) -> List[dict]:
    """One page (newest first) of a research swap's public funding settlements older than ``after_ms`` (the OKX ``after`` cursor)."""
    _check_swap(swap)
    data = rest.get(FUNDING_PATH, {"instId": swap, "limit": limit, "after": after_ms})
    return parse_funding_rows(data, swap)


def fetch_research_open_interest_history(
    rest: OKXPublicRest, swap: str, period: str = "1H", *, end_ms: Optional[int] = None, limit: int = PAGE_LIMIT
) -> List[dict]:
    """One page (newest first) of a research swap's public open-interest history up to and including ``end_ms``."""
    _check_swap(swap)
    _check_period(period)
    data = rest.get(OPEN_INTEREST_PATH, {"instId": swap, "period": period, "end": end_ms, "limit": limit})
    return parse_open_interest_rows(data, swap, period)
