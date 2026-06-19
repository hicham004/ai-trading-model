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

## Session 2: bounded armed run (June 11, 2026)

A 4-hour owner-authorized armed run (BTC-USDT, 10 USDT per-order cap, max 2
entries, software stop) completed with **zero orders placed**. This is accepted
as a valid, honest outcome: the infrastructure goals were proven (4 hours of
continuous public + private WebSocket operation, 481/481 periodic
reconciliations consistent, clean disarm/shutdown), and every one of the 117
`ma_crossover` LONG signals generated during the run was deterministically
vetoed by the risk manager at the 0.60 confidence floor. No retuning was
performed in response.

**Open research question (analysis only, not action):** what is the historical
clearance rate of the current `ma_crossover` configuration against the 0.60
demo confidence floor (`DEMO_MIN_CONFIDENCE`)? If signals essentially never
clear the floor on 1m BTC-USDT data, the organic demo order path can never be
exercised by waiting. This is a research/backtest question for the historical
dataset; any parameter or floor change would be a scope change requiring
explicit owner approval and is NOT authorized by this note.

## Session 2b: operator-authorized fillable round-trip (June 11, 2026)

A bounded, owner-authorized operator smoke test (explicitly NOT a strategy
signal; every intent tagged `op2b` in its persisted `signal_id`) exercised the
remaining live paths end to end: one marketable limit BUY (~9.98 USDT notional,
BTC-USDT, 0.2% price band), filled in ~2 seconds and confirmed via both REST
and the private WebSocket; fill-derived position sync matched exactly
(including the base-currency entry fee); the position was held with the
persisted software stop active (9 heartbeats, 3 confirmed-candle
candle-low-vs-stop evaluations, no breach; plus one log-only hypothetical
would-trigger evaluation - the stored stop was never mutated); an
operator-triggered full exit through the protective-exit path filled in three
partial fills accumulated correctly; and the post-exit reconciliation was
consistent with foreign=0 and unexplained=0, the USDT balance delta matching
the fill-derived PnL to the last digit. Round-trip cost ~0.032 USDT (two taker
fees + spread). The ma_crossover strategy was replaced for this run only by a
HOLD-emitting stub so no organic entry/exit could interfere; no reviewed code
was modified.

**Finding (sub-lot fee dust):** because OKX charges the SPOT entry fee in the
base currency at finer precision than the lot size, a full exit (floored to
the lot) can leave an unsellable sub-lot residue - here 1.2E-10 BTC. The
ledger and reconciliation handle it coherently (balances were exactly
explained), but fill-derived "position zero" is only reachable at lot
precision. The run harness's exact-zero flatness assertion flagged this and
aborted fail-closed (kill switch engaged), which incidentally live-validated
the abort path; the kill switch was then released through its fail-closed CLI
path after a consistent reconciliation. Future tooling should treat
"flat" as floor(position, lot_size) == 0.

## Limitations / still open

- The organic, strategy-generated demo order path (a real `ma_crossover` signal
  driving entry -> fill -> position sync -> exit -> reconcile) has not yet run
  against the venue (see the Session 2 outcome and the open research question
  above). Per the owner's June 11, 2026 decision it is deferred to the Phase 6
  shadow period as a tracked open item.
- Persistence uses `create_all`; no production migration workflow is present.

## Status: Phase 5 COMPLETE (owner declaration, June 11, 2026)

The human owner explicitly declared Phase 5 COMPLETE on June 11, 2026, after
Session 2b passed all five validation goals (fill handling, position sync,
software-stop live tracking, exit path, post-exit reconciliation). The
exit-path PASS was accepted by the owner under the **lot-precision flatness
definition**, which is hereby the official definition for this project:

> A position is flat when `floor(position, lot_size) == 0`. Exact-zero
> fill-derived positions are structurally unreachable whenever the
> base-currency entry fee is not a lot multiple; sub-lot residue is
> unsellable dust, not an open position.

The definition is codified as `is_flat()` in `app/execution/precision.py`
(unit-tested against the live 1.2E-10 BTC dust case) and used by operator
reporting. The safety core (driver stop check / exit gating via
`position_summary`) still treats `position > 0` as open; migrating it to
lot-precision flatness is a tracked future change requiring independent
review.

This declaration was made by the human owner; no agent self-approved the
phase. Completion does NOT authorize Phase 6 or any live trading.

### Deferred / open items carried forward (tracked)

1. **Organic strategy-generated demo round-trip** (a real `ma_crossover`
   signal driving entry -> fill -> exit -> reconcile) - explicitly deferred to
   the Phase 6 shadow period as a tracked open item.
2. **Exchange-side protective stops** (`slTriggerPx`/`slOrdPx` or
   `attachAlgoOrds`) - HARD BLOCKER for any live phase; must be implemented,
   independently reviewed, and validated on demo first.
3. **Stale empty `demo` account row** (the default-named local account sharing
   the demo API-key fingerprint, source of the Part A partition incident) -
   delete via a reviewed cleanup; the account-partition guard fails closed in
   the meantime.
4. **Research question**: historical clearance rate of the current
   `ma_crossover` configuration against the 0.60 confidence floor (analysis
   only; no retuning authorized).
5. **Safety-core adoption of lot-precision flatness** (see above) - future
   reviewed change.
6. Persistence uses `create_all`; no production migration workflow exists.

---

## Known issues — Phase 6a gap-recovery fix (commit 4b63bde, reviewed June 19 2026)

The following two edge cases were identified during independent code review of
the candle-gap recovery implementation. Neither is a safety blocker for the
Phase 6a demo shadow run; both are documented here for future reviewed
resolution.

### KI-1: Double-gap-in-same-batch confirmation counting

**What it is:** If two independent gaps appear in the same `out` batch during a
single `_new_confirmed_candle_items` call (e.g., T2 missing and T4 missing,
both detected in one driver step), the second `_handle_candle_gap` call
overwrites the `pending` state that the first set. The live candle after the
first gap (T3 — now processed before T4's backfill overwrites state) carries
`confirms_recovery=True` and counts as a confirmation toward the *second*
backfill's `confirmations_remaining`, not its own. Net effect: recovery can
clear after 2 total confirmations split across two backfills, rather than 2
confirmations per individual backfill.

**Why it is not a blocker:** On 1H candles in a well-connected run, two
independent gaps in a single one-second poll cycle is extremely unlikely. The
24h recovery cap (3/24h) and REST/WS OHLC divergence detection
(`_check_recovered_overlap`) provide independent backstops. Entry blocking is
maintained throughout — the continuity latch is never cleared prematurely, only
the confirmation count is underestimated relative to ideal.

**Future fix:** Batch confirmation accounting should be keyed per individual
backfill event (by `expected_missing` set), not shared across a single `state`
object that can be overwritten within the same batch.

### KI-2: `_check_recovered_overlap` runs before the watermark filter

**What it is:** In `_new_confirmed_candle_items`, `_check_recovered_overlap` is
called for every confirmed WS update *before* the `update.timestamp <=
watermark` filter discards already-processed candles. If OKX re-delivers a
confirmed candle for a slot that was previously backfilled via public REST (e.g.
a late WS redelivery of a confirmed bar), and its OHLC differs from the REST
version by even one LSB, `_check_recovered_overlap` fires divergence and latches
`_market_continuity[inst] = False`, blocking new entries.

**Why it is not a blocker:** OKX REST and WS return the same OHLC string
representation for confirmed bars. The `_ohlc()` comparison uses
`Decimal(str(...))` throughout — floating-point re-interpretation is
not in the path. A false-positive latch would be visible in the journal as
`market_candle_backfill_divergence`, surfaced as a readiness ALERT requiring
operator review before re-arming, which is the correct conservative outcome.

**Future fix:** Restrict the divergence check to candles with
`update.timestamp > watermark` (i.e., candles that would be newly added to the
window), or clear `_recovered_ohlc` entries once a slot has been committed and
the watermark has advanced past it.
