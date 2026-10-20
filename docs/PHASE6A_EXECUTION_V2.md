# Execution v2 in demo (Sprint 3) — exchange-side protective stops, entry policy, exit bracket

Status: **BUILT, demo validation PENDING owner drills, independent review REQUIRED, NOT merged.**
Branch `sprint-3/exchange-side-stops` (based on `sprint-0/okx-8443-and-hygiene`). Built
2026-10-20 by Claude Code (Fable 5.1) from `docs/MASTER_PLAN_2026-10-20.md`, Sprint 3. This
machine had no OKX credentials: everything below was built and tested offline against fake
transports; the live demo drills in `docs/runbooks/DEMO_STOP_DRILLS.md` are the owner's.
Demo only (`x-simulated-trading: 1`); nothing here authorizes a live phase, and the
software-only stop remains the recorded live blocker until the drills, the review and the
owner's sign-off close it.

## Why

`docs/PHASE5_DEMO_TRADING.md` records the hard blocker: the protective stop is enforced only
while the driver process is alive (a confirmed-candle low check, hourly on the 1H shadow).
If the process dies with a position open, nothing on the venue protects it. Sprint 3 puts a
resting **OKX conditional SELL algo order** (market on trigger) on the venue for every open
position and keeps it in sync, so the venue executes the stop even while we are dead. The
reviewed software stop keeps running as a backstop.

## What was built (scope = master plan Sprint 3 items 1–4)

| Item | Where | What |
|---|---|---|
| 1. Exchange-side protective stop | `app/exchange/okx_demo_endpoints.py`, `app/exchange/okx_demo_rest.py`, `app/execution/stops.py`, `app/execution/store.py`, `app/db/models.py` (+ migration `0002`), `app/execution/driver.py`, `app/execution/reconcile.py`, `app/exchange/okx_demo_ws.py` | Six SPOT algo endpoints added to the strict allowlist; a stricter parameter whitelist (`tdMode=cash`, `side=sell` only, `ordType` `conditional`/`oco`, trigger type `last`, no `reduceOnly`/`posSide`/`closeFraction`/leverage keys); a durable stop ledger (`demo_algo_orders`); the stop manager (place → ack / reject / UNKNOWN-resolve-by-query, amend, cancel, never two stops, never lower a trigger); the driver syncs the stop to the fill-derived position on every cycle; the reconciler compares venue algo orders with the ledger (foreign algo orders fail closed, never cancelled) and classifies the venue-created SELL of a triggered stop as owned (by `algoClOrdId`, `algoId`, child `ordId`, or a bounded `GET /trade/order` lookup); the private WS subscribes to `orders-algo` and requires its ack before trading. |
| 1. Alarm when unprotected | `app/execution/stops.py` (`guard`), `app/execution/runtime.py`, `app/shadow/supervisor.py` | A sellable position without a live stop for more than `DEMO_STOP_UNPROTECTED_MAX_SECONDS` (30) raises a persisted alarm (`demo_runtime_status.stop_alarm`): new entries are blocked (`protective_stop_alarm`), an event is recorded, and the shadow supervisor turns it into an ALERT file + Telegram message. Cleared automatically once a stop is live again. |
| 2. Entry policy | `app/execution/runtime.py` (`consider_entry`, `manage_entry_timeouts`) | `DEMO_ENTRY_POLICY=post_only_then_market`: post-only limit one tick inside the spread (at the bid when the spread is one tick); after `DEMO_ENTRY_TIMEOUT_SECONDS` the remainder is cancelled and ONE marketable limit is sent only if the expected slippage versus the decision-time ask is within `DEMO_ENTRY_SLIPPAGE_BUDGET` (never a chase); expected and realized slippage (bps vs the reference ask) are persisted on the intents and logged as `entry_execution_quality`. The reviewed `marketable_limit` stays the default. |
| 3. Mechanical exit bracket | `app/execution/bracket.py`, driver `_manage_execution_v2` | Protective stop mandatory (not configurable). Optional, OFF by default: take-profit at `R x DEMO_BRACKET_TAKE_PROFIT_R` as the TP leg of an OCO stop; trailing stop after `DEMO_BRACKET_TRAIL_ACTIVATE_R` R, `DEMO_BRACKET_TRAIL_R` R below the running high, applied by amending the venue stop upward on confirmed closes (never down); time stop after `DEMO_BRACKET_TIME_STOP_BARS` confirmed candles via the reviewed exit path. Sprint 2b showed brackets cost profit factor on rules that already have exits, hence OFF. |
| 4. Demo validation drills | `docs/runbooks/DEMO_STOP_DRILLS.md`, `scripts/run_demo_trading.py` | Exact owner-run drills with expected outcomes (stop fires while the process is dead; kill switch; reconciliation after restart; partial fills; stop missing → fail closed; foreign algo order → fail closed), plus the guarded operator commands they need (`--stops`, `--place-test-position`, `--tighten-test-stop`, `--close-test-position`, all inside `--smoke-test` + opt-in + armed). |

Read-only observability: `GET /demo/stops` lists the stop ledger; `GET /demo/health` carries
`stop_alarm`; `--status` prints the alarm and the open stops.

## Safety contract (unchanged) and how the new code keeps it

- Every new request is signed by the same chokepoint and always carries `x-simulated-trading: 1`
  on the same host allowlist; the six new paths are explicit `(method, path)` pairs; `tradingBot`
  and `copytrading` were added to the forbidden path tokens.
- The stop can only ever **sell** (a BUY stop would be a new entry): the REST whitelist rejects
  `side != sell`, any margin mode, position side, reduce-only, close-fraction or leverage key.
- **No LLM anywhere near it**: the stop level is the reviewed `Signal.stop_loss` persisted on the
  entry intent; the manager only mirrors the fill-derived position.
- **Idempotent and crash-safe** like orders: the placement is persisted before the network call
  under a deterministic `algoClOrdId` (prefix `d5s`, derived from account, instrument, parent entry,
  version); a transport timeout is UNKNOWN and resolved by `GET /trade/order-algo`, never by a
  blind re-placement; while a stop is UNKNOWN nothing new is placed and the startup gate refuses to
  arm; a rejection is recorded (`protective_stop_rejected`), retried on the next cycle under a
  per-hour attempt budget (`DEMO_STOP_MAX_ATTEMPTS_PER_HOUR`), and alarms after the grace.
- **Never two stops for one position**: extras are cancelled; a size/trigger change is an
  amendment confirmed by query, with cancel-then-replace only once the old stop is confirmed gone.
- **A trigger never moves down**: a trailed stop survives a restart (the live, higher trigger is
  accepted as protection).
- **Exit path**: a software exit (signal FLAT, candle-low backstop, time stop, kill-switch flows)
  cancels the resting stop FIRST; if the venue says it already triggered, the exit is superseded
  (the venue is closing the position); if the cancel is ambiguous, the exit is deferred one cycle.
- **Kill switch** still cancels owned pending ENTRY orders only; the protective stop is a
  protective order and is never cancelled by it.
- **Reconciliation stays exchange-authoritative**: venue pending algo orders not in the ledger are
  foreign (inconsistent, never cancelled); local open stops absent from the venue are resolved by
  query (effective / canceled / order_failed); the venue-created child SELL of a triggered stop is
  mapped to a local synthetic exit intent (prefix `d5x`) so position and balance accounting stay
  fill-derived; a fill that cannot be attributed stays foreign (fail closed).
- **Account identity**: all new settings default to the reviewed behaviour, so the running
  `demo-shadow-1h` account boots unchanged under this code; opting in (`DEMO_STOP_MODE=exchange`,
  the entry policy, any bracket leg) changes the immutable identity and therefore requires a NEW
  demo account name (e.g. `demo-exec-v2`).

## Configuration (all defaults = reviewed Phase 5/6a behaviour)

```text
DEMO_STOP_MODE=software|exchange            (default software)
DEMO_STOP_UNPROTECTED_MAX_SECONDS=30
DEMO_STOP_MAX_ATTEMPTS_PER_HOUR=6
DEMO_ENTRY_POLICY=marketable_limit|post_only_then_market   (default marketable_limit)
DEMO_ENTRY_TIMEOUT_SECONDS=60
DEMO_ENTRY_SLIPPAGE_BUDGET=0.001            (fraction; 0.1 %)
DEMO_BRACKET_TAKE_PROFIT_R=0                (0 = off)
DEMO_BRACKET_TRAIL_ACTIVATE_R=0  DEMO_BRACKET_TRAIL_R=0   (0 = off)
DEMO_BRACKET_TIME_STOP_BARS=0               (0 = off)
```

Database: Alembic revision `0002_execution_v2` (additive: `demo_algo_orders`, execution-quality
columns on `demo_order_intents`, `stop_alarm` on `demo_runtime_status`). On the VPS: back up,
`alembic upgrade head` (runtime `create_all` also creates the new table/columns on a fresh
database but does not add columns to existing tables — run the migration).

## What could not be verified here (owner drills decide)

1. **`attachAlgoOrds` vs stand-alone algo order.** The plan asked to verify both in demo and pick
   the one that fills reliably. Without credentials the choice was made on documentation: the
   stand-alone conditional order is explicitly supported for SPOT (`tgtCcy` notes, the
   `orders-algo` channel with `instType SPOT` / `tdMode cash`), it is sized from the actual fill
   (safe with partial post-only fills), and its lifecycle is query-resolvable like an order.
   OKX's documentation does not state SPOT support for attached TP/SL on `POST /trade/order`,
   and the parent-partial-fill semantics of attached legs are undocumented. The attached form is
   therefore **not** implemented; the drills measure the window between the entry fill and the
   stop ack (expected: seconds; the alarm grace is 30 s).
2. **Algo "not found" error code.** Regular orders return `51603`; the algo variant is assumed to
   be `51293` and both are treated as "not found". A wrong code cannot create a duplicate (not
   found after an attempted placement stays UNKNOWN); the drill log shows the real code.
3. **Whether `/trade/fills` rows carry `algoClOrdId`.** Handled either way: a child fill without a
   local id is matched by the stop's recorded child `ordId` or by one bounded
   `GET /trade/order?ordId=` lookup per unattributed fill.
4. **Whether a SPOT conditional SELL freezes the base balance** on placement (it should not, but
   the drills check the balance view). If it does, the software exit path would need the
   cancel-first step it already has — no change expected.
5. **Rate limits**: algo endpoints are documented at 20 requests / 2 s per instrument; the client's
   global limiter (8 / 2 s) is well inside.

## Tests (offline)

`tests/test_demo_stops.py` (new) covers the allowlist and whitelist, deterministic ids, the manager's
place / UNKNOWN-resolve / reject-retry-cap / amend / never-lower / cancel-for-exit / triggered
paths, the guard alarm, OCO take-profit parameters, the bracket math, the post-only policy with
timeout and budgeted or abandoned fallback plus realized-slippage recording, the driver round
trip through a venue-created child order (WS and reconcile paths), the startup gate refusing to
arm while a stop is UNKNOWN, the kill switch leaving the stop in place with the software backstop
still firing, the private-WS `orders-algo` subscription/ack/dispatch, foreign algo updates failing
closed, and the identity opt-in. The migration test asserts revision `0002` matches the models.

## Acceptance (master plan Sprint 3) — what remains

- [ ] Owner drills in `docs/runbooks/DEMO_STOP_DRILLS.md` pass with the documented outcomes.
- [ ] A 2-week demo run on a NEW account (`DEMO_STOP_MODE=exchange`) with zero positions unprotected
      beyond the grace (events `protective_stop_alarm` absent; `GET /demo/stops` shows a live stop
      whenever `position > 0`).
- [ ] Independent review (Codex or a second Claude with `/code-review`) of this safety-core change.
- [ ] Owner sign-off; only then does `docs/PHASE5_DEMO_TRADING.md` "Known limitations" move the
      software-only stop from "hard blocker" to "closed for demo; live still needs the Phase 7 gates".
