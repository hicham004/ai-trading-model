# Runbook — demo drills for the exchange-side protective stop (Sprint 3)

Who: the owner/operator, with OKX **demo** keys (`x-simulated-trading: 1`; never production keys).
Where: a machine with the repo at branch `sprint-3/exchange-side-stops`, PostgreSQL or SQLite,
`.env` with the demo credentials (never printed). The VPS shadow run (`demo-shadow-1h`) is NOT
touched by these drills: use a NEW account name so the immutable identity of the shadow account
stays intact. Every step is demo-only and reversible; nothing here places a real-money order.

Record the outcome of every drill (date, command, observed vs expected, event types from
`--status` / `GET /demo/events`) in `docs/evidence/` for the reviewer. Do not paste keys or ids.

## 0. Preparation

```bash
git checkout sprint-3/exchange-side-stops
pip install -r requirements.txt && pip install -e .
python -m pytest -q                                # must be green
cp .env .env.bak                                   # keep the shadow settings
# in .env (or exported for this shell only):
#   DEMO_ACCOUNT_NAME=demo-exec-v2                  <- NEW name (identity changes)
#   DEMO_STOP_MODE=exchange
#   DEMO_STOP_UNPROTECTED_MAX_SECONDS=30
#   DEMO_INSTRUMENTS=BTC-USDT  DEMO_TIMEFRAME=1H  DEMO_STRATEGY=ma_crossover
#   DEMO_MAX_ORDER_NOTIONAL=10                      <- keep the Phase 6a cap
#   OKX_DEMO_SMOKE_TEST=1                           <- only while drilling
pg_dump "$DATABASE_URL" > "backup-$(date +%F).sql"  # if PostgreSQL
alembic upgrade head                                # adds demo_algo_orders + columns (revision 0002)
python scripts/run_demo_trading.py --reconcile      # gate: expect consistent=True armable=True, "algo_pending: 0"
python scripts/run_demo_trading.py --stops          # expect: no local stops; venue pending algos: 0
```

Expected: the gate passes; `--stops` shows an empty ledger and an empty venue list; `--status`
shows `stop_alarm: None`.

## Drill 1 — a position gets a venue stop within seconds (happy path)

```bash
python scripts/run_demo_trading.py --arm --arm-ttl 1800
python scripts/run_demo_trading.py --smoke-test --place-test-position   # buys 2 x minSz at a marketable limit
python scripts/run_demo_trading.py --run --duration 120                 # the driver syncs the stop
python scripts/run_demo_trading.py --stops
```

Expected: `--stops` shows one local stop `status=live` with `algo_id` set, `side=sell`,
`size` = the fill-derived position floored to the lot, `trigger_price` = the entry's persisted
stop (ma_crossover: 2 % below the close), `order_price=-1`; the OKX demo web UI (Orders →
Algo/TP-SL) shows the same conditional SELL. Events: `protective_stop_intent`,
`protective_stop_update … state=live`, `protective_stop_placed`. Note the time between the
entry fill event and the stop ack: it must be well inside the 30 s grace. No
`protective_stop_alarm` event.

Record: the OKX "not found" error code if any `aquery` submission shows one (expected `51293`
or `51603`); whether `GET /demo/balances` shows the base balance as frozen while the stop rests.

## Drill 2 — the stop fires while the process is DEAD (the live blocker)

Precondition: Drill 1 left a position with a live stop and the driver is NOT running.

```bash
python scripts/run_demo_trading.py --smoke-test --tighten-test-stop 0.0005   # trigger 0.05 % below last price (amend; never lowers)
python scripts/run_demo_trading.py --stops                                   # trigger_price moved up; status live
# wait (minutes) until BTC prints below the trigger; watch the OKX demo UI: the algo order becomes "effective"
# and a market SELL fills. The driver is not running: nothing on our side acted.
python scripts/run_demo_trading.py --reconcile                               # startup gate after "restart"
python scripts/run_demo_trading.py --stops
python scripts/run_demo_trading.py --status
```

Expected: the gate reports `consistent=True`, `armable=True`, `owned_children: 1`,
`unprotected_positions: 0`; the local stop is `status=effective` with `child_order_id` set;
`GET /demo/intents` shows a synthetic exit intent (client id starting `d5x`, `entry_policy=exchange_stop`)
`status=filled`; `GET /demo/fills` has the child SELL fill under that id; the position report
says `FLAT at lot precision`; there is **no** `private_foreign` / "foreign or mismatched fill"
issue. This is the proof that the venue, not our process, closed the position.

If the market does not dip within a reasonable time: tighten again (the amendment only ever
raises the trigger) — never place a second stop by hand.

## Drill 3 — the software backstop and the kill switch (process alive)

```bash
python scripts/run_demo_trading.py --smoke-test --place-test-position
python scripts/run_demo_trading.py --run                      # leave running in one terminal
# second terminal:
python scripts/run_demo_trading.py --engage-kill-switch
python scripts/run_demo_trading.py --stops                    # the stop is STILL live (never cancelled by the kill switch)
python scripts/run_demo_trading.py --status                   # kill_switch_engaged=True; entries blocked
python scripts/run_demo_trading.py --smoke-test --close-test-position    # software exit while killed: allowed
python scripts/run_demo_trading.py --stops                    # stop cancelled FIRST (status canceled), then the SELL filled
python scripts/run_demo_trading.py --release-kill-switch      # reconcile + release
```

Expected: the kill switch blocks entries but leaves the protective stop; the exit cancels the
stop before selling (`acancel ack`, then the sell intent); after the fill the position is flat
and `--stops` shows no live stop; the release succeeds after a consistent reconciliation.

## Drill 4 — restart recovery with a live stop

```bash
python scripts/run_demo_trading.py --smoke-test --place-test-position
python scripts/run_demo_trading.py --run --duration 60        # stop placed
# kill -9 the driver if it is still running; then:
python scripts/run_demo_trading.py --release-stale-lock        # only after the heartbeat is stale
python scripts/run_demo_trading.py --reconcile
python scripts/run_demo_trading.py --run --duration 60
```

Expected: the gate finds the stop `live` on the venue (resolved by query, `aquery ack`),
`armable=True`; the restarted driver reports `protective_stop … protected` without placing a
second one (`--stops` shows exactly one live stop, same `algo_cl_ord_id`). Note: the restart
rebuilds the strategy window; per the recorded Phase 6a behaviour a warm-up FLAT may close the
position through the exit path — that exit must cancel the stop first (events show `acancel`
before the sell).

## Drill 5 — partial fills (post-only entry policy)

```bash
# .env: DEMO_ENTRY_POLICY=post_only_then_market  DEMO_ENTRY_TIMEOUT_SECONDS=60  DEMO_ENTRY_SLIPPAGE_BUDGET=0.001
# (identity changes again: use another new account name, e.g. demo-exec-v2b)
python scripts/run_demo_trading.py --reconcile --arm
python scripts/run_demo_trading.py --run                      # wait for a LONG signal, or use --place-test-position
```

Expected on a post-only entry: `ord_type=post_only`, `entry_policy=post_only_then_market`,
`reference_price` = the ask at decision time, `expected_slippage_bps` ≤ 0. If it rests past 60 s:
`entry_timeout` cancel, then either `entry_fallback_submitted` (one marketable limit for the
remainder, `entry_policy=market_fallback`, `parent_client_order_id` = the post-only id) or
`entry_fallback_abandoned` with the reason (`slippage_budget`, `remainder_below_minimum`, …).
Whatever filled gets ONE stop sized to the fill-derived position; a later fill of the
remainder results in an **amendment** of the same stop (`aamend ack`, `protective_stop_amended`),
never a second stop. `entry_execution_quality` events carry realized vs expected slippage.

## Drill 6 — stop missing → fail closed (alarm)

Simulate a venue that refuses the stop: temporarily set `DEMO_MAX_ORDER_NOTIONAL` so low that
the stop size is below the venue minimum is NOT possible from here; instead cancel the stop by
hand in the OKX demo UI while the driver runs with a position.

Expected within the grace (30 s): the driver resolves the stop as `canceled` on the venue and
immediately places a new version (`protective_stop_placed`, `version` +1). If the venue keeps
rejecting (e.g. you cancel repeatedly): after `DEMO_STOP_MAX_ATTEMPTS_PER_HOUR` (6) attempts the
manager stops retrying (`protective_stop_capped`), the guard alarms (`protective_stop_alarm`,
`stop_alarm=protective_stop_rejected|protective_stop_missing` in `--status`), new entries are
blocked with reason `protective_stop_alarm`, the shadow supervisor writes an `ALERT` file and a
Telegram message. Protective exits remain possible (`--close-test-position`). The alarm clears
by itself once a stop is live again (`protective_stop_alarm_cleared`).

## Drill 7 — foreign algo order → fail closed

Place a conditional order by hand in the OKX demo UI on BTC-USDT (any size, any trigger), then:

```bash
python scripts/run_demo_trading.py --reconcile
```

Expected: `consistent=False` with issue "foreign algo order … NOT auto-cancelled; operator
review"; `armable=False`; the hand-placed order is still on the venue (we never cancel what we
do not own). Cancel it by hand, reconcile again: consistent.

## Cleanup

```bash
python scripts/run_demo_trading.py --smoke-test --close-test-position   # if a position remains
python scripts/run_demo_trading.py --disarm
unset OKX_DEMO_SMOKE_TEST   # or remove it from .env
cp .env.bak .env            # restore the shadow settings
```

## What "pass" means for Sprint 3

All seven drills behave as expected, a 2-week demo run on the new account shows no
`protective_stop_alarm` event and a live stop whenever a position exists, the independent
review is clean, and the owner signs off. Until then the software-only stop stays the recorded
live blocker.
