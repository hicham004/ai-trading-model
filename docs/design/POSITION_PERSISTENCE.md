# Design — position persistence across restarts, and lot-precision flatness in the safety core

Plan row R14 (`CLAUDE.md` open items 5 and 6; `docs/MASTER_PLAN_2026-10-20.md` section 8,
gate 6). Written 2026-11-04 on branch `plan/auto`.

**Status: DESIGN AND TEST PLAN ONLY.** Nothing under `app/`, `config/` or `migrations/`
changes with this document. The change it describes touches the reviewed safety core
(`app/execution/driver.py`, `app/execution/runtime.py`, `app/execution/store.py`, the shadow
supervisor's start-up order and `scripts/run_demo_trading.py`), so building it needs the
owner's explicit go, its own branch, an independent review and demo validation before it
reaches the VPS (section 12). The safety contract is unchanged: demo only
(`x-simulated-trading: 1`), SPOT cash, long only, leverage 1.0, no LLM anywhere near an
order, fail closed on ambiguity, never a blind retry.

Every statement about today's behaviour below was checked against the code on `plan/auto`
(file and line references are to that branch) and, where marked *reproduced*, against an
offline run of the real driver with the test fakes of `tests/test_demo_driver.py` (fake
REST, fake clock, in-memory SQLite, no network, no key). The reproduction script was a
throwaway outside the repository; the three results are quoted in section 2.5.

## 1. The answer on one page

**What a restart does today.** The demo ledger already remembers the position: it is derived
from the recorded fills, and the protective stop level is stored on the entry order. Those
survive a restart. What does not survive is the strategy's memory, the window of recent 1H
candles the `ma_crossover` rule reads. After a restart the window is empty, the rule can say
nothing but FLAT until it has seen 30 candles, and the driver treats a FLAT signal while a
position is open as "sell". So the first confirmed candle after a restart (up to one hour
later) sells any open position through the reviewed exit path, and about 30 hours later the
rule may buy it back. This was accepted for demo on June 12, 2026, and is harmless there; live
it is two sets of fees and a random exit at every reboot, crash or deploy, which is why the
master plan lists it as gate 6 before any real money.

**Three findings from checking the code (details in sections 2.5 and 3).**

1. *Sub-lot fee dust blocks every later entry.* OKX charges the SPOT entry fee in BTC at a
   finer precision than the lot size, so a full exit leaves a residue such as 1.2E-10 BTC
   (seen live on June 11, 2026). Reporting already calls that "flat", but the driver's entry
   gate does not: with a residue in the ledger every LONG signal is refused with
   `position_already_open`, and on candles whose low is under the stale stop level the rule
   is not even evaluated. *Reproduced offline.* The shadow account `demo-shadow-1h` made one
   round trip on June 21, 2026, so it has very likely been unable to open a position since
   that day. Section 2.5 says how to confirm this from the VPS journals.
2. *A hard crash halts the shadow run permanently.* After a kill, an out-of-memory kill or a
   power loss the dead process's runtime lock stays in the database (by design: locks are
   never auto-stolen). The supervisor's gate then fails with "runtime lock unavailable",
   retries three times within about two minutes and writes a permanent ALERT. Until the
   operator runs `--release-stale-lock`, acknowledges the alert and starts the service, an
   open position is unmanaged (only the venue-side stop of Sprint 3 would protect it, once
   that is deployed).
3. *Exits need the private WebSocket.* The driver's exit path requires a usable feed, and
   "usable" includes an authenticated private stream. During the June 22 authentication
   flapping a stop breach could not have been executed; the exit is deferred to the next
   candle. The Sprint 3 venue stop is the answer; this design does not change that rule.

**The proposal, in five parts.**

- *Resume protocol* (section 5.2): after the existing fail-closed gate (lock, time sync,
  account validation, resolve every open order by query, reconcile against the venue), the
  driver resumes the open position and its stop from the ledger, states them in an event,
  and rebuilds the strategy window from OKX's public candle history, exactly: the same 300
  confirmed, contiguous candles an uninterrupted run would hold. The first live candle then
  produces the same signal the uninterrupted run would have produced, so a restart no longer
  sells a position the rule would have kept, and still sells it when the rule says so. The
  rebuilt history is context only, never traded (the existing invariant for warm-up and
  gap-recovery candles).
- *Fail closed, bounded* (section 5.3): if the history cannot be fetched or does not line up
  exactly, the driver retries until the first live candle arrives and then falls back to
  today's reviewed behaviour (sell at the first candle). The position is never left to a rule
  that is blind to it. Any mismatch between the ledger and the venue stays what it is today:
  reconciliation inconsistent, no arming, supervisor halt, operator review.
- *Lot-precision flatness in the safety core* (section 5.4, open item 5): the stop check, the
  FLAT-exit gate, the entry gate and the open-position count use "a sellable position
  exists" (the lot-floored size is at least the venue minimum) instead of `position > 0`.
  Dust stops blocking entries. This part is small, independent of the window rebuild, and
  unblocks the shadow period's evidence; it should be built first.
- *A crashed process's arming does not outlive its lock* (section 5.5): `--release-stale-lock`
  also disarms. A tightening only.
- *Observability* (section 5.6): resume events in the ledger, resume state in the heartbeat,
  one line in the daily report.

**What this does not change.** No new venue endpoint, no new table, no identity change (the
precedent is the June 19 gap-recovery fix, deployed to the same account), no automatic lock
stealing, no "hold a position without a strategy", no change to `ma_crossover`, to the
0.60 floor or to any cap. Nothing here authorizes a live phase.

**The decision** (section 12): whether to build it, on its own branch, after this design is
reviewed. Recommendation: yes, in two parts, the lot-precision part first.

## 2. How the code behaves today

### 2.1 What the demo store already persists

The ledger (`app/execution/store.py`, the only writer of the `demo_*` tables; models in
`app/db/models.py:418-660`; migration `0001_baseline`) keeps, per account:

| Table | What it holds | Role in a restart |
|---|---|---|
| `demo_accounts` | name, key fingerprint, the immutable identity JSON (`app/execution/identity.py`) | a changed setting refuses to open the account (`AccountIdentityMismatch`) |
| `demo_runtime_status` | lock token + heartbeat, `armed_until`, kill switch, `reconciliation_consistent`, feed flags | the lock decides whether a new process may run; arming and the kill switch survive |
| `demo_order_intents` | one row per logical order: deterministic `client_order_id`, side, size, price, **`stop_loss`** on entries, status, filled size, average price | the open position's stop level is the latest entry intent's `stop_loss` (`store.py:626`) |
| `demo_submissions`, `demo_order_updates` | append-only attempts and state updates | an ambiguous order is resolved by query at start-up, never resubmitted |
| `demo_fills` | append-only venue fills (unique `tradeId`), fee and fee currency | **the position is fill-derived**: net buys minus sells plus base-currency fees (`store.py:626`) |
| `demo_balance_snapshots` | the immutable first-run baseline plus every reconcile snapshot | venue balances must equal baseline + own fills (`reconcile.py:323`) |
| `demo_daily_baselines` | immutable UTC-day starting equity | the daily-loss gate |
| `demo_reconciliations`, `demo_events` | every reconcile result; every operational event | the supervisor's halt watch and the journal read these |

Branch `sprint-3/exchange-side-stops` (not merged; `docs/PHASE6A_EXECUTION_V2.md` there)
adds `demo_algo_orders` (the venue-side stop ledger, deterministic `algoClOrdId`, one row per
placement), `stop_alarm` on the status row and entry-policy columns, in migration `0002`.

So "position persistence" in the ledger sense exists. The position, its stop level, every
order and the baseline survive a restart, and the start-up gate re-reads the venue before
anything is armed.

### 2.2 What is not persisted

- The **strategy window**: `DemoTradingDriver._windows`, one `deque(maxlen=300)` per
  instrument (`paper_window_size`, part of the identity as `strategy_window_size`).
- The **watermark** of the last processed confirmed candle (`_watermark`), the
  market-continuity flags and the gap-recovery state (`_market_continuity`,
  `_gap_recovery`, `_recovered_ohlc`).
- Instrument metadata (re-fetched at the gate), balances (re-fetched by reconcile), the
  private-stream liveness clock.
- The supervisor's own shadow-evaluation window (observability only, `supervisor.py`,
  `_supervise_loop`), rebuilt from live candles each attempt.

### 2.3 The start-up sequence, step by step

Both runners build a fresh `DemoTradingDriver` (new lock token) and call
`startup_gate()` (`driver.py:278`):

1. account-partition guard; `acquire_lock` (`store.py:768`) succeeds only when the stored
   token is empty or already ours: a dead process's token blocks every newcomer until
   `scripts/run_demo_trading.py --release-stale-lock` is run after the heartbeat is older
   than `DEMO_LOCK_STALE_SECONDS` (60 s). Nothing in the driver or the supervisor releases a
   stale lock (checked: `release_stale_lock`, `store.py:790`, has one caller, the CLI);
2. `reconciliation_consistent=False` is persisted (fail closed until proven);
3. server-time sync; account validation (`acctLv` allowlist, instruments, no liabilities),
   which also loads the instrument metadata (lot size, tick, minimum size);
4. `OrderLifecycle.resolve_open_intents()` (`lifecycle.py:456`): every non-terminal intent is
   queried by client order id; a first "not found" after an attempted placement stays
   `unknown` (never resubmitted);
5. `DemoReconciler.reconcile()` (`reconcile.py`): venue pending orders (anything not ours is
   foreign, never cancelled), venue fills of the last 3 days (OKX's `/trade/fills` window)
   recorded idempotently, so fills that happened while the process was dead enter the
   ledger here; balances compared with baseline + own fills to 1E-8;
6. armable only if consistent and no `unknown` intent remains.

Then the two runners differ:

- `scripts/run_demo_trading.py --run` (`driver.run()`, `driver.py:1027`) calls `warmup()`
  (`driver.py:217`), which loads the local `candles` table for the instrument and timeframe
  (filled by `app/ingest.py` or `app/live/persistence.py`, if either runs), appends it as
  context with a continuity check, and sets the watermark. It stays disarmed unless the
  persisted arming is still valid.
- `scripts/run_shadow_period.py --run` (the VPS) composes the driver's tasks itself
  (`supervisor.py:120`, `default_driver_tasks`) and **skips warm-up on purpose** (module
  docstring: a stale local candle table could wedge the continuity check), arms the runtime
  after a clean gate (`supervisor.py:819`) and re-arms every 10 minutes. The window starts
  empty and fills from live confirmed 1H candles only.

### 2.4 The first confirmed candle after a restart

`step()` (`driver.py:500`) runs for each new actionable candle: if a position is open and the
candle's low is at or below the stored stop, `consider_exit`; otherwise the strategy runs on
the window and the last signal decides: LONG → `consider_entry` (refused while a position is
open), FLAT with `base > 0` → `consider_exit` (`driver.py:578`).

`MovingAverageCrossover.generate_signals` (`app/strategy/library.py:50`; defaults 10/30, stop
2 %) emits FLAT whenever either moving average is undefined, that is for every candle until
the window holds 30. Hence, after a restart with an open position:

- the first confirmed candle (at most one hour after start on 1H) yields FLAT and the
  position is sold at a marketable limit (bid minus the 0.2 % band), if the runtime is armed
  and the feed is usable (public feed connected and not stale, private stream authenticated
  and not stale); otherwise the exit is deferred (`exit_deferred` event) and retried at the
  next candle, one hour later;
- from the 30th candle (about 30 hours later) the rule can say LONG again and the driver
  re-enters if everything else allows. Two taker fees and a spread per restart, plus the
  market move between exit and re-entry, in either direction.

`CLAUDE.md` open item 6 records this as accepted for demo (June 12, 2026) and as a reviewed
change before any live phase. `docs/runbooks/VPS_8443_UPDATE.md` turns it into an operator
rule: restart only while the heartbeat says `flat_at_lot: true`.

### 2.5 Flatness today — three offline reproductions

Set-up: the real `DemoTradingDriver`, `FakeRest` (lot size 1E-8, minimum 1E-5), a fake clock,
in-memory SQLite, armed, private stream marked authenticated; an entry of 0.001 BTC whose fee
of 1E-9 BTC is charged in BTC (finer than the lot, as OKX does), then a full exit of the
lot-floored sellable size (fee in USDT).

- **A. Dust blocks entries.** After the round trip the ledger holds 9E-9 BTC;
  `is_flat(9E-9, 1E-8)` is `True`. Forty-five rising 1-minute candles then produce LONG
  signals; orders placed: **0**; the last risk decisions read `entry blocked:
  position_already_open` (`runtime.py:298`). The open-position count in `_equity_exposure`
  (`driver.py:602`) also counts the dust as one open position, which would trip
  `max_open_positions` (1) if the first check did not fire.
- **B. A restart sells an open position at the first candle.** A second driver on the same
  ledger (the first released its lock), no warm-up, armed: the first confirmed candle places
  `sell 0.001` (the FLAT exit). The fake venue's balances do not follow fills, so the fake
  gate reported the expected "unexplained balance" and refused to arm; the exit went through
  on the arming the first driver had persisted (a point section 5.5 tightens).
- **C. Dust plus a stale stop.** With the 9E-9 BTC residue and the old stop still on the entry
  intent, a candle whose low is under the stop triggers the stop branch: `validate_sell`
  floors the residue to zero, `exit_precision_rejected` is recorded, and the strategy is not
  evaluated for that candle (the `else` branch of `driver.py:521-578`).

Confirming finding A on the VPS (plan row G4 copies the files): the daily reports after
June 21 say `FLAT at lot precision (sub-lot dust 1.2E-10)` or similar, and the journals'
`event` lines (the ledger poller mirrors `demo_events`) carry `risk_decision` with
`position_already_open` on every LONG that cleared the 0.60 floor after that date. If the June 21 entry's fee happened to be a lot
multiple there is no dust and the account is fine; the report line settles it.

## 3. Restart scenarios on the VPS

The service is `shadow.service` on Ubuntu 24.04 with local PostgreSQL (its unit file is not in
the repository; the validation plan records it). `config/shadow_period.json`: 3 restarts per
3600 s, 30 s backoff, arming TTL 3600 s renewed every 600 s, heartbeat every 20 s.

| Scenario | What happens | Open position | Operator needed |
|---|---|---|---|
| **Planned restart** (`systemctl restart/stop`, token rotation, `.env` edit) | SIGTERM → the supervisor cancels the tasks, **disarms**, releases the lock, exits 0; on start: gate → arm → empty window | sold at the first confirmed candle (≤ 1 h); unmanaged in between (software stop not running) | no; the runbook asks for `flat_at_lot: true` first |
| **Planned reboot** | systemd stops the service cleanly (default stop timeout 90 s), the service is enabled, so it starts at boot | as above | no |
| **Driver task dies** inside the supervisor (a WebSocket task ends, an exception escapes a task) | attempt cleanup: disarm, release lock, outcome `crashed`; restart counted; 30 s backoff; new gate; re-arm | as above; the window is empty again | no, within the budget; `restart_budget_exhausted` → ALERT, permanent halt |
| **Hard crash** (kill -9, OOM kill, kernel panic, power loss) | the lock token stays; every gate says `runtime lock unavailable` (a transient marker, `policy.py:54`) → retry, retry, retry → ALERT within ≈ 2 min; exit 1 | **unmanaged until the operator acts**; arming persists in the database up to its TTL (1 h) | yes: wait ≥ 60 s, `--release-stale-lock`, `--acknowledge-alert`, `systemctl start` |
| **Deploy** (`git pull`, dependency install, migration, restart) | as a planned restart, plus: any identity setting change (URLs, timeframe, caps) makes the account refuse to open → new account name → the old position can never be sold by the new account (`VPS_8443_UPDATE.md`) | as a planned restart; with an identity change the position must be flat **before** | yes, by runbook |
| **Permanent halt** (foreign order, wrong scope, unexplained balance, readiness alert) | kill switch (entries), ALERT file, exit 1; the supervisor refuses to start while the ALERT exists | protective exits stay possible while the process runs; after exit 1 nothing manages it | yes, always (by design) |
| **Private WebSocket down**, process alive | `ws_authenticated=False` → entries blocked; **exits deferred** (feed not usable); re-arming continues | protected only by the venue stop (Sprint 3) | no; Telegram warns after 30 s |
| **Candle gap** (1H feed interruption) | bounded public REST backfill, two live confirmations, entry latch; exits and stops keep evaluating (commit `4b63bde`) | managed | no, unless the gap exceeds the policy |

Two consequences for this design: the resume protocol must work for every row of the table
without weakening the halt rows, and the hard-crash row is where an unattended VPS loses the
most. The design keeps "never auto-steal a lock" (section 11 lists the alternative for the
owner) and makes the operator's recovery safer (section 5.5).

## 4. What the Sprint 3 exchange-side stop adds

`app/execution/stops.py` on `sprint-3/exchange-side-stops` (`ProtectiveStopManager`) keeps a
resting OKX conditional SELL on the venue for every sellable position, sized from the
fill-derived position floored to the lot (below the minimum size is "dust", nothing to
protect), placed under a deterministic `algoClOrdId`, resolved by query when ambiguous, never
two for one position, never moved down. At start-up its `resolve_open()` runs inside the gate,
and the gate refuses to arm while a stop is `unknown`; the driver's `_manage_execution_v2`
re-syncs on every cycle, so after a restart a live venue stop is recognised and kept (drill 4
of `docs/runbooks/DEMO_STOP_DRILLS.md`). The venue-created SELL of a triggered stop is mapped
to a synthetic exit intent so a stop that fired while the process was dead leaves a flat,
reconciled ledger after the gate.

Relevance here: the venue stop closes the "unmanaged while down" gap of section 3; the
resume protocol closes the "sold at the first candle" gap. They are independent, but the
software exit path cancels the venue stop first, and the resumed window's first FLAT or stop
exit must go through that same path. Building the resume on top of Sprint 3 (section 9) keeps
one exit path instead of two.

## 5. The proposed reviewed change

### 5.1 Goals and invariants

Goals: (G1) a restart never sells a position the strategy would have kept; (G2) a restart
never keeps a position the strategy, the stop or the operator would have sold; (G3) dust never
blocks trading; (G4) nothing is decided before the venue has been read and agrees with the
ledger; (G5) every failure degrades to today's reviewed behaviour or stricter, never looser.

Invariants the build and the review hold to:

- I1 **Ledger first, venue authoritative.** The position is the fill-derived net
  (`position_summary`), unchanged; a ledger/venue disagreement is a reconcile inconsistency
  (no arm, supervisor halt), never corrected automatically.
- I2 **History is context only.** Candles obtained by the rebuild are appended with
  `actionable=False` semantics: they move the window and the watermark, never trigger an
  entry, an exit or a stop evaluation. Same rule as warm-up and gap backfill.
- I3 **Exactness or fallback.** The rebuilt window is accepted only when it is exactly the
  window an uninterrupted run would hold (section 5.3); otherwise the legacy path applies.
- I4 **Exits are never delayed by the resume.** A stop breach or a FLAT on a live candle
  behaves exactly as today whether the rebuild succeeded, is pending or failed.
- I5 **No new mutating path.** The rebuild uses the GET-only public candle client already
  injected for gap recovery (`OKXPublicClient.get_history_candles`); no authenticated
  endpoint is added; the endpoint allowlist is untouched.
- I6 **No identity change.** Resume behaviour and flatness gating are runtime policy, like
  the gap-recovery constants, so the fix can be deployed to the running account. (The
  reviewer confirms no field of `demo_identity_config` changes.)
- I7 **Nothing loosens.** Caps, the 0.60 floor, arming, the kill switch, the lock rule,
  foreign/wrong-scope handling and the stop-first exit order are untouched.

### 5.2 The resume protocol

A new synchronous, offline-testable driver method, `resume()`, called by both runners after a
gate that returned armable (the supervisor: after `GateDecision.PROCEED` and before
`runtime.arm`; the plain driver: in `run()` in place of `warmup()`), and re-entered from the
trading loop while its state is `retrying`:

- **R0 — Preconditions unchanged.** Everything in section 2.3 steps 1 to 6 (and, with
  Sprint 3, `stops.resolve_open()`), in the same order. `resume()` runs only when the gate
  was armable; a non-armable gate skips it (there is nothing safe to resume into).
- **R1 — Ledger resume.** For each instrument: `position, stop = position_summary(...)`,
  `lot, min_size` from the validated metadata, `sellable = floor(position, lot)` if that is
  `>= min_size` else 0, `flat = is_flat(position, lot)`. Persist `resume_position`
  (payload: raw net, sellable, stop, flat, latest entry id, latest fill id). A sellable
  position with `stop is None` is persisted as `resume_position_unprotected` (warning) and
  handled by the legacy path (sold at the first candle), with Sprint 3's guard alarm on top.
- **R2 — Venue cross-check.** No new call: the gate's reconcile already compared the base
  and quote cash with baseline + own fills (I1). `resume()` re-reads the last reconcile row
  and refuses (`resume_refused`, state `not_resumed`) if it is not consistent or older than
  the gate. A position present in the ledger but absent from the venue (or the reverse) is
  therefore already an "unexplained balance" issue → halt.
- **R3 — Stop resume.** The software stop is the persisted entry stop (nothing to do: the
  per-candle check reads it). With Sprint 3: the venue stop was resolved by query in R0; the
  first `_manage_execution_v2` cycle keeps a live stop, re-places a missing one if armed, and
  the gate already refused to arm on `unknown`. The resumed stop is stated in
  `resume_position` (`venue_stop: live | none | n/a`).
- **R4 — Window rebuild** (section 5.3). On success: window = the rebuilt candles,
  watermark = the last rebuilt candle, continuity `ok`, state `rebuilt`,
  event `resume_window_rebuilt` (first, last, count, pages). On failure: state `retrying`,
  event `resume_window_failed` (reason), retried once per trading-loop pass (1 s poll) until
  the first live confirmed candle for that instrument is observed; at that point the state
  becomes `fallback_legacy` (event `resume_window_fallback`), the window starts from that
  candle and today's behaviour applies, including the FLAT exit.
- **R5 — First live candle.** Through the existing `_new_confirmed_candle_items`: the candle
  must be `watermark + interval`; a later one goes through the existing bounded gap recovery
  (backfill, two confirmations, entry latch), an earlier or equal one is ignored by the
  watermark, and an overlapping one with different OHLC trips the existing divergence check
  (entries latched, exits unaffected). The signal computed on the first live candle is the
  one an uninterrupted run would compute (section 7, the equivalence test).
- **R6 — Decisions.** Unchanged code path: stop breach → exit; FLAT with a sellable position
  → exit; LONG → entry gate (refused while a sellable position exists). G1 and G2 follow from
  R4 and R5 without any suppression logic: there is no "ignore FLAT during warm-up" rule to
  get wrong.
- **R7 — Observability** (section 5.6).

The supervisor's shadow-evaluation window (journals only) is seeded from a read-only copy of
the driver's rebuilt window so the journal's `signal` lines match the driver from the first
candle; if the rebuild failed it starts empty as today.

### 5.3 Window rebuild: source, size, validation, fallback

- **Source**: `OKXPublicClient.get_history_candles(inst, timeframe, limit=100, after=...,
  confirmed_only=True)` (`app/okx/client.py:117`, GET `/market/history-candles`, public,
  no key), through the injected `public_candle_client` the gap recovery already uses, so
  tests inject `FakePublicCandleClient`. `ALLOWED_INSTRUMENTS` bounds it to BTC/ETH as today.
- **Size**: exactly `paper_window_size` (300, the identity's `strategy_window_size`), paged
  from the open time of the current, unconfirmed bar backwards (3 pages of 100). This makes
  the rebuilt window identical to a long-running driver's deque, for any strategy in the
  registry, not only for the 30-bar moving average.
- **Validation** (all or nothing, reusing the checks of `_fetch_exact_backfill`,
  `driver.py:764`): every row is for the instrument and timeframe, confirmed, with a
  timestamp on the interval grid; timestamps are strictly contiguous at the interval; no
  duplicates; the newest row is the last completed bar before `now` (not older than one
  interval plus the configured candle-age tolerance, `demo_max_candle_age_seconds`); the
  count equals the requested size. OHLC are stored in `_recovered_ohlc` so a later WebSocket
  copy of any rebuilt candle is divergence-checked.
- **Budget**: at most one attempt per trading-loop pass, each attempt at most
  `ceil(size / 100)` requests through the client's rate limiter; attempts stop at the first
  live candle (R4). No attempt is made while the public market state reports the candle feed
  disconnected (nothing to confirm against); the loop simply waits.
- **Fallback = today's behaviour**, with its events. The design deliberately does not
  propose "hold the position with only the stop until the window fills" (section 11, choice
  2): a rule-blind position for 30 hours is a new behaviour that needs its own review.

### 5.4 Lot-precision flatness in the safety core (open item 5)

Definitions (the official one from `docs/PHASE5_VALIDATION.md` plus one refinement):

- **flat**: `is_flat(position, lot)`, that is `floor(position, lot) == 0` (unchanged,
  `precision.py:131`);
- **sellable size**: `floor(position, lot)` when that is `>= min_size`, else 0;
- **unsellable remainder**: `0 < floor(position, lot) < min_size`. Reachable only through a
  partially filled then cancelled exit (entries require twice the minimum, so fees alone
  cannot produce it). Reported, never traded, and not an open position for gating.

Where each is used after the change (the only call sites of `position > 0` logic in the
core, `driver.py:521`, `driver.py:578`, `driver.py:602`, `runtime.py:298`):

| Call site | Today | Proposed |
|---|---|---|
| per-candle stop check (`step`) | `position_size > 0 and low <= stop` | `sellable > 0 and low <= stop`; `base_balance` passed to `consider_exit` stays the raw net (`validate_sell` floors it) |
| FLAT exit gate (`step`) | `base > 0` | `sellable > 0` |
| entry gate (`consider_entry`, `instrument_position_size`) | the raw net `> 0` | the driver passes the **sellable** size; `runtime.py` keeps its `> 0` check unchanged |
| open-position count and exposure (`_equity_exposure`) | counts any `size > 0` | counts sellable positions; exposure sums sellable value; equity still adds the marked value of any residue (negligible, keeps equity equal to cash + holdings) |
| supervisor `_day_pnl` | marks `position > 0` | unchanged in effect; aligned to the same helper for consistency |
| Sprint 3 `desired_spec` / `guard` | already floor and min-size based | unchanged |

One helper in the driver, `_position_view(inst) -> (net, sellable, stop, flat)`, computed
from `position_summary` and the validated metadata, is the single place the definitions live;
`position_summary` itself does not change (the reconciler and the reports depend on the raw
net). When the metadata for an instrument is missing, `step` already skips the instrument
(`if meta is not None`); the helper is never called without it.

Effect on the running shadow account: after deployment the dust no longer blocks entries, the
stale stop on the June entry is irrelevant (no sellable position, no stop check), and the
next cleared LONG can enter under the shadow caps. This is the behaviour the June 11
definition intended; it is nonetheless a change in what the account does, so it is reviewed
and the owner is told (section 12).

### 5.5 Arming after a hard crash

Reproduction B shows arming outliving the process that armed. The supervisor's clean paths
disarm; the hard-crash path cannot. Proposed tightening: `release_stale_lock`
(`store.py:790`) also clears `armed_until` and records `disarmed_on_stale_lock_release`. The
only way a crashed process's lock is cleared is that call, so a restart after a hard crash
starts disarmed until the supervisor's gate re-arms it or the operator runs `--arm`. The
documented `--arm` then `--run` operator flow is unaffected (no stale lock involved).

### 5.6 Observability

- Ledger events (`demo_events`, journaled by the supervisor's `LedgerPoller`):
  `resume_position`, `resume_position_unprotected`, `resume_refused`,
  `resume_window_rebuilt`, `resume_window_failed`, `resume_window_fallback`,
  `disarmed_on_stale_lock_release`, and `unsellable_remainder` (warning, once per change).
- Heartbeat (`logs/shadow/heartbeat.json`): `resume_state` per instrument
  (`rebuilt | retrying | fallback_legacy | not_resumed`), `sellable` beside `position` and
  `flat_at_lot`.
- Daily report: one line, "restart resume: N rebuilt, M fallback, K refused".
- `GET /demo/health` and `--status`: the same fields, read-only.

### 5.7 Settings and identity

No new setting. The rebuild size is the identity's window size; the retry bound is the first
live candle; the flatness definitions are the venue's own lot and minimum size. No field of
`demo_identity_config` changes (I6), so the running account keeps its name.

### 5.8 Explicitly out of scope

Automatic stale-lock release; holding a position without a formed window; migrating a
position between account names; new venue endpoints (`fills-history` for fills older than
3 days stays an operator-review path, section 6 row 2); any change to strategy, floor or
caps; anything live.

## 6. What can go wrong, and the fail-closed answer

| # | Failure | Answer (all are existing behaviour unless marked NEW) |
|---|---|---|
| 1 | Venue base balance ≠ baseline + ledger fills (a fill missed, a manual sale in the OKX UI, a drill on the same OKX account) | reconcile inconsistent → not armable → supervisor halt + ALERT; `resume()` not entered; nothing corrected automatically |
| 2 | Process dead for more than 3 days with an open position and a venue-side exit in between | the fill is outside `/trade/fills` → row 1 (correct: the ledger cannot explain the balance); operator reviews with the OKX history; no new endpoint proposed |
| 3 | An entry filled while dead | the gate's reconcile records the fill → position and stop resumed, protected |
| 4 | A venue stop (Sprint 3) triggered while dead | child SELL attributed → flat → `resume_position` says flat; nothing to resume |
| 5 | A software exit was resting on the venue when the process died | resolved by query at the gate (`live`); `consider_exit` refuses a second exit while one is open; it fills or is cancelled by the operator |
| 6 | An entry or exit `unknown` after the restart | not armable → no resume, no trading until resolved (`--reconcile`) |
| 7 | Public history unreachable at start | NEW: `retrying` until the first live candle, then `fallback_legacy` = today's sale at the first candle; entries are not delayed beyond today |
| 8 | History incomplete, duplicated, unconfirmed, off-grid or stale | NEW: rejected whole, as row 7 |
| 9 | History later contradicted by a WebSocket candle | existing divergence check → entries latched (readiness ALERT), exits unaffected |
| 10 | First live candle not contiguous with the rebuilt window | existing gap recovery (≤ 3 bars, two confirmations, 3 per 24 h cap), entries latched meanwhile, exits unaffected |
| 11 | Clock skew between the host and the venue | time sync at the gate fails closed above 5 s; the rebuild's "newest bar" check uses the synced clock |
| 12 | Position without a stored stop level | NEW event `resume_position_unprotected`; legacy sale at the first candle; Sprint 3 guard alarms |
| 13 | Unsellable remainder (0 < floored < minimum) | NEW: reported, not an open position, next entry merges it; never sold alone (`validate_sell` would refuse) |
| 14 | Hard crash: stale lock | unchanged rule (operator releases); NEW: the release disarms |
| 15 | Resume while disarmed (plain driver without `--arm`) | `resume_position` is still recorded; exits remain blocked by `exit_block_reason: disarmed` as today; the warning makes the unmanaged position visible |
| 16 | Database restored from an older backup (R15) with a live venue stop | venue algo order not in the ledger → foreign → halt; restores happen with the service stopped and are followed by `--gate-check` (runbook) |
| 17 | Two processes (an operator CLI while the service runs) | the lock refuses the second driver; read-only commands unaffected |
| 18 | `resume()` itself raises | caught like any gate error: `set_reconcile_consistent(False)`, event `resume_error`, not armable |

## 7. Tests (adverse cases first)

Offline only, with the fakes of `tests/test_demo_driver.py` (`FakeRest`,
`FakePublicCandleClient`, `_connected_state`, `_feed_candles`, `_open_demo_position`) and the
supervisor fakes of `tests/test_shadow_supervisor.py`. New file `tests/test_demo_resume.py`;
additions to `tests/test_demo_execution.py` and `tests/test_shadow_supervisor.py`. Every test
asserts on the venue fake's `placed` list and on `demo_events`, never on logs.

**A. Adverse resume cases**

1. `test_resume_is_skipped_when_gate_not_armable`: an `unknown` intent → `resume()` records
   `resume_refused`, the window stays empty, no REST history call.
2. `test_resume_position_mismatch_fails_closed`: the venue base balance differs from baseline +
   fills → gate inconsistent → no resume, `arm` refused, supervisor halt reason
   `reconcile_unexplained_balances` (supervisor test).
3. `test_resume_without_history_retries_then_falls_back_to_legacy_flat_exit`: the fake history
   client raises; trading-loop passes retry (one call per pass); the first live candle sets
   `fallback_legacy` and places the sell, as today.
4. `test_resume_rejects_gap_in_history`: 300 rows with one missing → rejected whole, state
   `retrying`, no partial window.
5. `test_resume_rejects_unconfirmed_wrong_timeframe_or_wrong_instrument_rows`.
6. `test_resume_rejects_off_grid_or_duplicate_timestamps`.
7. `test_resume_rejects_stale_history`: newest row two intervals old → rejected.
8. `test_resume_never_retrades_history`: a rebuilt window whose last 30 bars say LONG with no
   position → no entry until a live candle; with a position and a window that says FLAT → no
   exit until a live candle (I2).
9. `test_resume_first_live_candle_must_be_contiguous_else_gap_recovery`: watermark set to the
   last rebuilt bar; a live candle two bars later goes through backfill and two confirmations
   with the entry latch, exits unaffected (reuses the existing gap tests' shape).
10. `test_resume_divergence_with_ws_latches_entries_not_exits`: a WebSocket copy of a rebuilt
    candle with different OHLC → `market_candle_backfill_divergence`, a stop breach still
    exits.
11. `test_resume_with_fill_while_dead_recovers_position_and_stop`: the venue fake returns a
    fill the ledger lacks → after the gate `resume_position` shows the position and the entry's
    stop; a breach on the first live candle exits.
12. `test_resume_with_exit_filled_while_dead_is_flat`: the exit's fill is recovered → flat →
    no sell on the first candle.
13. `test_resume_with_live_exit_intent_does_not_submit_second_exit`.
14. `test_resume_position_without_stop_level_is_unprotected_and_flattened`: event present; the
    first live candle sells (legacy); entries blocked meanwhile.
15. `test_resume_disarmed_records_position_and_blocks_exits_until_armed`.
16. `test_resume_error_fails_closed`: the history client raises a non-transport exception in a
    later pass → `resume_error`, consistency flag false, not armable.
17. `test_resume_makes_no_authenticated_call`: the REST fake records every method; `resume()`
    touches only the public candle client (I5).
18. `test_resume_rest_budget_is_bounded`: at most 3 history calls per attempt, one attempt per
    pass, none after the first live candle.

**B. The equivalence property (the heart of G1/G2)**

19. `test_resume_reproduces_uninterrupted_signals`: for several synthetic 1H series (a trend
    that keeps the rule LONG, a series that crosses down to FLAT, a series that breaches the
    stop) and several cut points k: driver U runs all N candles; driver R runs to k, is torn
    down with the position open, a new driver rebuilds the window from a history fake that
    serves the same series, then runs candles k+1..N. Assert the order lists after k are
    identical (sides, sizes, signal ids) and the first-candle signals match. This is the test
    that fails today (R sells at k+1) and must pass after the change.
20. `test_resume_window_equals_identity_window_size`: the rebuilt deque holds exactly
    `paper_window_size` candles ending at the last confirmed bar.

**C. Lot-precision flatness (open item 5)**

21. `test_dust_does_not_block_entry_with_position_already_open` (reproduction A, inverted).
22. `test_dust_does_not_count_as_open_position_for_max_open_positions_or_exposure`.
23. `test_dust_with_stale_stop_skips_stop_check_and_evaluates_strategy` (reproduction C).
24. `test_sellable_position_still_exits_on_stop_breach_and_on_flat`: the raw net is passed,
    `validate_sell` floors it, the sell size equals the floored size.
25. `test_unsellable_remainder_is_reported_not_traded_and_does_not_block_entry`.
26. `test_equity_includes_residue_value_but_exposure_excludes_it`.
27. `test_existing_is_flat_dust_case_unchanged` (1.2E-10 BTC, `test_is_flat_lot_precision_dust`
    stays green).

**D. Arming and the stale lock**

28. `test_release_stale_lock_also_disarms_and_records_event`.
29. `test_release_stale_lock_does_not_touch_a_fresh_lock_or_its_arming`.

**E. Supervisor**

30. `test_supervisor_calls_resume_after_proceed_and_before_arm` (order asserted with a
    recording fake driver).
31. `test_supervisor_journals_resume_events_and_heartbeat_resume_state`.
32. `test_supervisor_halts_on_mismatch_before_resume` (row 2 above, supervisor side).
33. `test_supervisor_seeds_shadow_window_from_driver_on_success_and_empty_on_fallback`.

**F. Sprint 3 interplay (if built on that branch)**

34. `test_resume_keeps_live_venue_stop_and_places_none` (drill 4 offline).
35. `test_resume_first_live_flat_exit_cancels_venue_stop_first`.
36. `test_resume_after_stop_triggered_while_dead_is_flat_and_consistent`.

**G. Existing tests that must stay green, by name**: `test_no_retrospective_trading_after_warmup`
(rewritten to the REST source, same invariant), the candle-gap recovery tests
(`test_candle_gap_*`, `test_gap_latch_blocks_long_entry_on_same_candle_as_successful_backfill`,
`test_candle_backfill_divergence_stays_latched`,
`test_market_continuity_gap_blocks_entries_only_not_exit_readiness`),
`test_terminal_gap_latch_does_not_gate_stop_or_flat_exits`,
`test_protective_stop_submits_exit_and_daily_baseline_is_immutable`,
`test_kill_switch_cancels_pending_entries_and_blocks`, `test_entry_blocked_when_lock_lost`,
`test_driver_run_starts_and_shuts_down_cleanly`, every `test_reconcile_*`,
`test_lock_is_atomic_and_not_auto_stolen`, `test_arming_expires_and_disarm`, the supervisor's
gate/halt/budget tests, `tests/test_migrations.py`, and on Sprint 3 the whole
`tests/test_demo_stops.py`.

## 8. Migration

**None.** The resume protocol reads tables that exist (`demo_fills`, `demo_order_intents`,
`demo_runtime_status`, `demo_reconciliations`) and writes only `demo_events`. The rebuilt
candles are not persisted (public data, re-fetchable, journaled by the supervisor). If the
review prefers the driver to persist the confirmed candles it processes, the existing
`candles` table with its `(instrument, timeframe, open_time)` uniqueness serves without a
schema change; the design does not need it. Sprint 3's revision `0002` is independent and
is applied by its own runbook before that branch runs. `tests/test_migrations.py` keeps
asserting models and migrations agree.

## 9. Review path (`AGENTS.md`, `docs/CODE_REVIEW.md`)

- **Branch and base.** Its own branch, `sprint-6/position-persistence`. Part A (section 12)
  from `main` once G2 has merged `plan/auto`; part B on top of `sprint-3/exchange-side-stops`
  after the G3 drills, so the single exit path (cancel the venue stop, then sell) is reviewed
  once. Never on the VPS before merge; never while the shadow run holds a position.
- **Safety-sensitive files touched**: `app/execution/driver.py`, `app/execution/runtime.py`
  (only if the helper lands there), `app/execution/store.py` (`release_stale_lock`),
  `app/shadow/supervisor.py` (call order, journal fields), `scripts/run_demo_trading.py`
  (`--status` fields). The PR lists each with "what changed" and "safety-sensitive: yes".
- **Review order**: safety regressions first (the P0 list: demo-only, long-only, caps, kill
  switch, arming TTL, partition guard, fail-closed reconciliation, no LLM order authority,
  no secrets), then scope (Phase 6a demo; nothing live), then correctness against section 6,
  then tests against section 7, then this document against the code.
- **Reviewer**: independent of the author (Codex, or a second Claude session with
  `/code-review` at high effort). The review must try to break I1 to I7: a rebuilt candle
  that trades, a resume that arms into an inconsistency, a FLAT suppressed, a stop delayed, a
  lock stolen, an identity field changed.
- **Verdict line** (`SAFE TO MERGE` / `NEEDS WORK` / `DO NOT MERGE (operator decision
  required)`), changed-file summary, test status (full suite run, offline), highest-severity
  finding with `path:line`, and the statement that merge, deploy and phase advance remain the
  owner's decisions.
- **Documentation**: `docs/PHASE5_DEMO_TRADING.md` (restart recovery section),
  `docs/runbooks/VPS_8443_UPDATE.md` (the flatness precondition relaxes to "identity changes
  only" after deployment), `CLAUDE.md` open items 5 and 6 (owner's edit at merge), the
  heartbeat field list in `docs/runbooks/OPS_DIGEST.md` if the digest reads it.

## 10. Demo validation plan

Who: the operator, with demo keys (`x-simulated-trading: 1`), on a machine with the branch,
PostgreSQL or SQLite. Which OKX account: **not the one the VPS shadow run reconciles** (the
G3 hazard: a drill fill on the same OKX account disarms the shadow run for good); use the
drills account of G3 or another OKX demo account, and a new local account name
(`demo-resume-v1`). The Sprint 3 drill commands (`--place-test-position`,
`--close-test-position`, `--stops`) are the practical way to create and remove a controlled
position; without them only the strategy can open one (about one 1H entry a month), which is
why part B is validated on top of Sprint 3. Record every drill (date, command, expected vs
observed, event types from `--status` and the journal; no keys, no ids) in `docs/evidence/`.

| Drill | Steps | Expected |
|---|---|---|
| V0 Baseline | `pytest -q` green; `--reconcile` armable; `systemctl cat shadow.service` saved (unit file, `Restart=`, `TimeoutStopSec`) | documents the service behaviour the design assumed |
| V1 Clean restart with a position | place a test position; `--run` until a stop is live (Sprint 3) and `resume_position` is journaled; `systemctl stop`; wait past the hour; `systemctl start` | `resume_window_rebuilt` (300 bars); the first live candle's `signal` line equals what the rule says on the same bar in the shadow journal; **no sell** unless the rule says FLAT; position and stop unchanged; one venue stop, same id |
| V2 Dust only (part A) | on the drills account: a round trip with the Sprint 3 commands (`--place-test-position`, `--close-test-position`), then `--status` and `--run --duration 120` through at least one confirmed candle; on the shadow run after deployment: the first LONG that clears the 0.60 floor | drills account: `FLAT at lot precision (sub-lot dust ...)`, `sellable: 0`, no `exit_precision_rejected` on a candle under the old stop, a `risk_decision` for that candle; shadow run: the LONG's `risk_decision` reason is anything but `position_already_open` or `max_open_positions` |
| V3 Hard crash | position open, `kill -9` the process; wait 60 s; `--release-stale-lock`; `--status` | arming cleared (`disarmed_on_stale_lock_release`); gate armable; after start the position resumes as in V1 |
| V4 History unavailable | cannot be staged on the venue: the public history and the authenticated REST share the host, so blocking one blocks the gate. Evidence is the offline tests A3 to A8 in the review's test run, plus one live check: start with a position while OKX's public candle history is healthy and confirm the event order `resume_position`, `resume_window_rebuilt`, `armed` in the journal | offline: `resume_window_failed` at most once per pass, then `resume_window_fallback` and the legacy sell on the first live candle; live: the three events in that order |
| V5 Mismatch | with the service stopped, sell a tiny amount of the position by hand in the OKX demo UI; start | gate inconsistent (`unexplained BTC balance`), no resume, supervisor ALERT; that local account is finished (new name afterwards) |
| V6 Fill while dead | place the entry below the market so it rests; stop the process; let it fill; start | `resume_position` shows the position and stop from the ledger after the gate recorded the fill; protected |
| V7 Venue stop fired while dead (Sprint 3 drill 2 repeated) | as the drill, then start | gate consistent, child fill attributed, `resume_position` flat, no sell |
| V8 Soak | 14 days on the test account with at least three planned restarts at random hours while a position is open and one hard crash | zero sells caused by a restart (every exit traced to a FLAT, a stop or the operator); zero reconcile inconsistencies; every restart leaves `resume_state: rebuilt` |

Acceptance: V1 to V8 pass with the expected outcomes, the full suite is green, the
independent review's verdict is `SAFE TO MERGE`, and the owner signs. Then, and only then,
the VPS deployment by runbook; the shadow run's restart precondition changes from "flat"
to "flat if the identity changes".

## 11. Choices for the reviewer (with recommendations)

1. **Where `resume()` is called.** Inside `startup_gate()` or as a separate step the runners
   call. Recommendation: separate, so `--gate-check` stays a pure gate (no public fetch) and
   the supervisor keeps control of the order (gate, resume, arm).
2. **Fallback behaviour when the window cannot be rebuilt.** Today's sale at the first candle
   (proposed) or "hold with the venue stop only until the window fills". Recommendation: the
   proposed; the alternative is a new behaviour for a later review once Sprint 3 has a
   two-week record.
3. **Automatic stale-lock release by the supervisor** after a hard crash (heartbeat older
   than 60 s, token not its own). Recommendation: no; keep "never auto-stolen" (it is what
   protects against two writers on one account) and keep the operator step, now safer
   (section 5.5). Revisit only with a PID/host-bound lock design.
4. **Unsellable remainder** treated as not open (proposed) or as open (blocks entries until
   the operator intervenes). Recommendation: not open; it cannot be sold alone and merging it
   into the next position is the only way it ever clears.
5. **Persisting processed candles** to the `candles` table for an offline warm-up path.
   Recommendation: no; one source (the venue's public history) with an exactness check is
   simpler to review than two.
6. **Part A alone first.** Recommendation: yes (section 12).

## 12. The owner's decision

Build it, on its own branch, after this design has been independently reviewed. One
decision, with the recommendation to build in two parts: **part A** (section 5.4, lot-precision
gating, plus 5.5 and the matching tests C and D) first, as a small reviewed change from `main`
once G2 has merged, deployed to the shadow run by runbook so Phase 6a can produce entries
again; **part B** (sections 5.2, 5.3, 5.6 and tests A, B, E, F) on top of
`sprint-3/exchange-side-stops` after the G3 drills, validated by section 10 on a non-shadow
OKX account, then merged and deployed. Until part B is deployed the operator rule stands:
restart the shadow run only while the heartbeat says `flat_at_lot: true`.

The decision line is recorded in `docs/PLAN_STATUS.md`, section 2 ("From R14").
