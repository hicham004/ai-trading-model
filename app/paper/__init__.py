"""Phase 4 - Local Paper Trading Loop (SIMULATION ONLY).

This package implements a safe, deterministic, restartable forward paper-trading
system driven exclusively by PUBLIC OKX market data. Every fill is virtual and
produced by the simulation-only paper broker; nothing here can authenticate,
reach a private endpoint, place a real or demo order, borrow, use leverage, or
move funds.

Phase 4 is authorized and WIP. It is NOT accepted: completion requires
independent review and explicit human approval (see ``docs/PHASE4_PAPER_TRADING.md``,
``CLAUDE.md``, and ``PROJECT_RULES.md``).
"""
