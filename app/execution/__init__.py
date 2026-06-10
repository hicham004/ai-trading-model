"""Phase 5 - authenticated OKX DEMO (simulated) execution layer.

This package places, cancels, amends, and reconciles orders on OKX's DEMO
(simulated) trading environment only. Every request carries
``x-simulated-trading: 1`` to a strict hostname allowlist; production trading is
unrepresentable (see ``app.exchange.okx_demo_endpoints``). It is long-only SPOT
cash for BTC-USDT and ETH-USDT, reuses the accepted Phase 4 deterministic risk
manager, and is disarmed by default.

Phase 5 is authorized and WIP. It is NOT accepted: completion requires
independent review and explicit human approval (see
``docs/PHASE5_DEMO_TRADING.md``, ``CLAUDE.md``, ``PROJECT_RULES.md``). No demo
order is ever submitted except under an explicitly armed, separately opted-in
smoke test.
"""
