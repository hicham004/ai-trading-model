"""Deterministic OKX-compatible client order ids (idempotency anchor).

OKX ``clOrdId`` allows up to 32 case-sensitive alphanumeric characters. We
derive it deterministically from the logical order identity
(account, instrument, intent, signal) so a retry, reconnect, or restart always
reproduces the SAME id - which makes duplicate economic submissions impossible
(OKX rejects a duplicate clOrdId, and our store treats the id as the unique
key). The id intentionally contains no timestamp or attempt counter.
"""

from __future__ import annotations

import hashlib

# Short, fixed alphanumeric prefix marking a Phase 5 demo order.
CLIENT_ORDER_PREFIX = "d5"


def derive_client_order_id(
    account_name: str, instrument: str, intent: str, signal_id: str
) -> str:
    """Return a stable <=32-char alphanumeric clOrdId for a logical order."""
    material = f"{account_name}|{instrument}|{intent}|{signal_id}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    cl_ord_id = f"{CLIENT_ORDER_PREFIX}{digest}"[:32]
    # hex + ascii prefix is alphanumeric by construction.
    assert cl_ord_id.isalnum() and len(cl_ord_id) <= 32
    return cl_ord_id
