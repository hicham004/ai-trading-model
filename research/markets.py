"""The replication study's market universe (plan row R12, research only).

Sprint 2c tuned and judged its rule families on BTC-USDT and ETH-USDT. The
replication study (``research/replication.py``) runs the same rules on other
large OKX spot USDT pairs that they were never tuned on. This module holds
only tables — no code touches an exchange account and nothing here widens the
demo/paper instrument allowlist in ``app/okx/client.py``:

- ``REPLICATION_CANDIDATES``: the pairs with public OKX 1H history from
  before 2020-01-01 (found 2026-11-04) plus SOL-USDT (history from
  2020-09-29); the pre-registration step ranks them by public 24-hour volume
  and fixes the study's markets BEFORE any result exists.
- ``RESEARCH_SYMBOL_FOR_INSTRUMENT``: the Binance USDT-margined perpetual
  symbol whose PUBLIC funding history is the S5 positioning feature for each
  market (the research-side counterpart of
  ``app.datalake.binance_public.SYMBOL_FOR_INSTRUMENT``, which knows only
  BTC/ETH and bounds the app's collectors).
- ``RESEARCH_SWAP_FOR``: the OKX perpetual swap of each market, for a forward
  (paper-fleet) positioning feed should a configuration ever be confirmed.
"""

from __future__ import annotations

from typing import Dict, Mapping, Tuple

SPRINT_2C_INSTRUMENTS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT")

#: Candidate markets and why each is a candidate (the owner's row R12, written before the ticker snapshot).
REPLICATION_CANDIDATES: Mapping[str, str] = {
    "XRP-USDT": "1H history from before 2020-01-01",
    "LTC-USDT": "1H history from before 2020-01-01",
    "ADA-USDT": "1H history from before 2020-01-01",
    "LINK-USDT": "1H history from before 2020-01-01",
    "BCH-USDT": "1H history from before 2020-01-01",
    "DOGE-USDT": "1H history from before 2020-01-01",
    "TRX-USDT": "1H history from before 2020-01-01",
    "ETC-USDT": "1H history from before 2020-01-01",
    "XLM-USDT": "1H history from before 2020-01-01",
    "ATOM-USDT": "1H history from before 2020-01-01",
    "ALGO-USDT": "1H history from before 2020-01-01",
    "SOL-USDT": "always included (history from 2020-09-29; the largest pair after BTC/ETH that is not a stablecoin)",
}
ALWAYS_INCLUDED: Tuple[str, ...] = ("SOL-USDT",)
RANKED_PICKS = 6  # the top N candidates by 24-hour quote volume, plus ALWAYS_INCLUDED
HISTORY_CUTOFF = "2020-01-01"  # a ranked pick needs public 1H candles from before this day

RESEARCH_SYMBOL_FOR_INSTRUMENT: Dict[str, str] = {inst: inst.replace("-", "") for inst in REPLICATION_CANDIDATES}
RESEARCH_SWAP_FOR: Dict[str, str] = {inst: f"{inst}-SWAP" for inst in REPLICATION_CANDIDATES}


def research_symbol_for(instrument: str) -> str:
    """Binance USDT-margined perpetual symbol of a replication market (``ValueError`` for anything else)."""
    try:
        return RESEARCH_SYMBOL_FOR_INSTRUMENT[instrument]
    except KeyError:
        raise ValueError(f"{instrument!r} is not a replication market; known: {sorted(REPLICATION_CANDIDATES)}") from None
