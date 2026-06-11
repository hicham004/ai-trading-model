# Phase 5 - Live Demo Validation Record (sanitized)

This document records the bounded operational validation of the Phase 5
authenticated OKX **DEMO (simulated) trading** implementation against the real
OKX demo environment, and the offline hardening that followed. It is an audit
summary; it contains no secrets, API keys, key fingerprints, order/trade ids, or
account balances beyond what is needed to understand the outcome.

Phase 5 remains **demo/simulated only** (`x-simulated-trading: 1`, SPOT cash,
long-only, BTC-USDT/ETH-USDT, leverage locked at 1.0). This record does not
authorize real funds, production access, or any later phase. Validation is not
phase completion; completion remains an explicit human-owner decision.

## Scope of the validation runs

- Owner-authorized, bounded runs against the live OKX demo API (June 10, 2026).
- Every request carried the demo header; no production path exists in code.
- No real-money trading, no withdrawals/transfers, no leverage/margin/shorting,
  no account-mode mutation, and no LLM order authority at any point.

## Part A/B results (June 10, 2026)

Validated live against the real demo venue:

1. **Authenticated demo reads** - account config (SPOT/Simple level), balances,
   instruments, pending orders, and fills all returned correctly. Bare `urllib`
   is rejected by the OKX edge (User-Agent filtering); the client uses
   `requests`, which is accepted.
2. **Private WebSocket health** - signed login + per-instrument `orders`
   subscription acknowledgement reach the authenticated/subscribed state;
   liveness flows; one transient connect failure recovered via backoff. The
   persisted `ws_authenticated` flag resets on shutdown (not a failure).
3. **Production unreachable** - the demo header is a hard constant, the REST/WS
   hostnames are allowlisted (production WS host rejected), and only an explicit
   SPOT-read/trade endpoint allowlist is callable.
4. **Order lifecycle (gated operator smoke order)** - one tiny limit BUY priced
   far below market (cannot fill): place -> live, query -> live, observed on the
   private `orders` channel, cancel -> canceled, reconcile -> consistent. No
   economic effect.
5. **Kill switch** - engaging blocks new entries (and would cancel owned pending
   entries); release is fail-closed (requires a consistent reconciliation and no
   unresolved entry orders). Clean disarm and lock release on shutdown.

Goals 3, 4, and 5 were signed off by the human owner. The genuine
**strategy-generated** order path was deliberately not forced and remains to be
exercised in a separate bounded run.

## Part A incident: account-partition shadowing

The first armed attempt was blocked by a fail-closed "inconsistent
reconciliation". Read-only investigation showed this was **not** foreign
exchange activity or ledger corruption. Two local account rows shared the same
demo API key: an empty default-named row and a populated row that owned a prior
demo round-trip. Reconciliation ran under the empty row, so the exchange's own
orders/fills had no local match and were flagged "foreign", and the balance
baseline could not attribute them.

Resolution (owner-approved): select the account that owns the ledger (set the
account name explicitly). Under the owning account, reconciliation was
consistent with zero data loss, and the full smoke-order lifecycle and kill
switch then passed.

## Offline hardening (post-incident)

To make that ambiguity impossible to hit silently again:

1. **Account-partition guard** - on startup/reconcile, if more than one local
   account shares this credential's key fingerprint and the operator did not
   choose one explicitly (no `--account` flag and no `DEMO_ACCOUNT_NAME`), the
   runtime fails closed and names the candidates instead of running under the
   default. (`app/execution/account_guard.py`, wired into the driver startup
   gate and the operator CLI.)
2. **Wrong-account-scope classification** - before labelling an order/fill
   "foreign", reconciliation checks the client order id against intents under
   **all** local accounts on the same key. A match elsewhere is reported as
   "wrong account scope" (naming the owning account) - a distinct alarm with
   distinct operator guidance - rather than "foreign". Reconciliation still
   fails closed. (`app/execution/reconcile.py`.)
3. **Regression tests** reproduce the exact Part A scenario (empty default
   account + populated sibling on the same key) and assert the new behavior.

These changes are deterministic and offline; they add no network capability and
do not relax any safety gate.

## Limitations / still open

- The organic, strategy-generated demo order path (a real `ma_crossover` signal
  driving entry -> fill -> position sync -> exit -> reconcile) has not yet run
  against the venue. It is the subject of a separate bounded armed run.
- Long-running private-WebSocket operation over hours remains unverified.
- Persistence uses `create_all`; no production migration workflow is present.

## Status

Validation accepted by the human owner for Goals 1-6. Phase 5 is **not** marked
complete; completion depends on the organic-path run or an explicit owner
decision to defer it. No agent may self-approve the phase.
