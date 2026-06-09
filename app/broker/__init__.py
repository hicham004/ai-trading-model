"""Execution layer (Phase 2: simulated only).

This package defines a small, abstract :class:`~app.broker.base.Broker`
interface and a single concrete implementation, :class:`~app.broker.paper.PaperBroker`,
which produces SIMULATED fills.

This is the seam where a future, separately-approved live broker would plug in.
For now, and for several phases to come, the ONLY implementation is the paper
broker. There is intentionally no code here that:
- uses real or private OKX API keys,
- accesses any exchange account,
- places real orders, or
- enables withdrawals or leverage on a real exchange.
"""
