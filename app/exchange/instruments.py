"""SPOT instrument metadata for demo trading (tick/lot/min sizes).

Only ``SPOT`` instruments are representable. Parsing rejects any non-SPOT
instrument type (``SWAP``, ``FUTURES``, ``OPTION``, ``MARGIN``), so derivatives
and margin can never enter the order path. Sizes are parsed as :class:`Decimal`
so all downstream precision math is exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List

SPOT = "SPOT"


class InstrumentError(ValueError):
    """Raised when instrument metadata is missing, malformed, or non-SPOT."""


@dataclass(frozen=True)
class InstrumentMeta:
    """Validated SPOT instrument trading rules (all sizes are Decimals)."""

    instrument: str
    inst_type: str
    base_ccy: str
    quote_ccy: str
    tick_size: Decimal
    lot_size: Decimal
    min_size: Decimal
    state: str

    def is_tradable(self) -> bool:
        return self.inst_type == SPOT and self.state == "live"


def _positive_decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InstrumentError(f"{label} is not a valid decimal: {value!r}") from exc
    if not result.is_finite() or result <= 0:
        raise InstrumentError(f"{label} must be a positive finite decimal: {value!r}")
    return result


def parse_instrument(row: dict) -> InstrumentMeta:
    """Parse one OKX ``/public/instruments`` row. SPOT only, else fail closed."""
    if not isinstance(row, dict):
        raise InstrumentError("instrument row must be an object")
    inst_type = str(row.get("instType", ""))
    if inst_type != SPOT:
        raise InstrumentError(
            f"only SPOT instruments are allowed (got {inst_type!r}); "
            "margin, futures, swaps, and options are forbidden"
        )
    instrument = str(row.get("instId", ""))
    if not instrument:
        raise InstrumentError("instrument row missing instId")
    base_ccy = str(row.get("baseCcy", ""))
    quote_ccy = str(row.get("quoteCcy", ""))
    if not base_ccy or not quote_ccy:
        raise InstrumentError(f"instrument {instrument} missing base/quote currency")
    return InstrumentMeta(
        instrument=instrument,
        inst_type=inst_type,
        base_ccy=base_ccy,
        quote_ccy=quote_ccy,
        tick_size=_positive_decimal(row.get("tickSz"), "tickSz"),
        lot_size=_positive_decimal(row.get("lotSz"), "lotSz"),
        min_size=_positive_decimal(row.get("minSz"), "minSz"),
        state=str(row.get("state", "")),
    )


def parse_instruments(rows: List[dict]) -> dict[str, InstrumentMeta]:
    """Parse SPOT instrument rows into a mapping, skipping non-SPOT entries."""
    out: dict[str, InstrumentMeta] = {}
    for row in rows:
        try:
            meta = parse_instrument(row)
        except InstrumentError:
            continue  # ignore non-SPOT / malformed entries
        out[meta.instrument] = meta
    return out
