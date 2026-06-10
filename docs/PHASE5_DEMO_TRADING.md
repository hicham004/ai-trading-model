# Phase 5 - Authenticated OKX DEMO Trading

## Status And Boundary

The human owner explicitly authorized Phase 5 implementation on June 10, 2026:
**authenticated OKX DEMO (simulated) trading only**, BTC-USDT and ETH-USDT SPOT
cash, long-only. Phase 5 was independently reviewed by Codex and **explicitly
accepted by the human owner on June 10, 2026** (recorded in
`docs/PHASE5_REVIEW_NOTES.md`). Acceptance covers the implementation as reviewed
and tested offline; Phase 5 was not exercised against the live OKX demo API in
this work, and no demo order has been submitted.

Every request is demo/simulated (`x-simulated-trading: 1`) to a strict hostname
allowlist. The following are forbidden and made unrepresentable in code:
real-money trading, production credentials/endpoints, `x-simulated-trading: 0`,
withdrawals/deposits/transfers/funding, leverage/margin/derivatives/shorting,
account-mode mutation, automatic demo-balance reset, any generic
arbitrary-endpoint method, any mutating HTTP route, and any LLM/AI order
authority. No demo order is ever submitted except under an explicitly armed,
separately opted-in smoke test (see Operator Commands).

## Credentials And Secret Handling

- Demo API credentials are read ONLY from the environment
  (`OKX_DEMO_API_KEY`, `OKX_DEMO_API_SECRET`, `OKX_DEMO_API_PASSPHRASE`) by
  `app/exchange/credentials.py`. They are never read from source, the database,
  the API, or a committed file. Loading fails closed if any is missing/blank,
  and the error text contains no values.
- The `DemoCredentials` object never reveals secrets in `repr`/`str` (only a
  non-reversible `sha256[:8]` key fingerprint hint).
- `SecretRedactingFilter` scrubs the exact secret values from every log record
  (message, args, structured extras) as defence-in-depth.
- The signed REST/WS code never logs request headers or bodies. Error messages
  carry only the OKX `code`/`msg`. The database stores no secret (only the key
  fingerprint hint for audit).

## Signing (verified against official OKX v5 docs)

- REST: `OK-ACCESS-SIGN = base64(HMAC_SHA256(secret, timestamp + METHOD +
  requestPath + body))`; `OK-ACCESS-TIMESTAMP` is ISO-8601 UTC milliseconds
  (`2020-12-08T09:08:57.715Z`); headers also include `OK-ACCESS-KEY`,
  `OK-ACCESS-PASSPHRASE`, and always `x-simulated-trading: 1`.
- WebSocket login: `sign = base64(HMAC_SHA256(secret, timestamp + 'GET' +
  '/users/self/verify'))` with a Unix-epoch-seconds timestamp.
- Signing (`app/exchange/okx_auth.py`) is pure and uses only the stdlib
  (`hmac`/`hashlib`); no new dependency was added.
- Server time is synchronized (`GET /api/v5/public/time`); the measured
  local-vs-server offset is applied to every timestamp, and a drift beyond
  `DEMO_CLOCK_DRIFT_MAX_SECONDS` fails closed.

Official references used:
- OKX API v5 guide: <https://www.okx.com/docs-v5/en/>
- OKX changelog: <https://www.okx.com/docs-v5/log_en/>

## Hostnames (strict allowlist; fail closed)

- REST demo base: `https://www.okx.com` (allowlist `{www.okx.com, aws.okx.com}`,
  https only, no path/query/credentials). Demo is selected by the header, not a
  different host.
- Private WebSocket: `wss://wspap.okx.com:8443/ws/v5/private`. The production
  host `ws.okx.com` is rejected for authenticated login.
- Only an explicit `(method, path)` allowlist of SPOT trading + account-read
  endpoints is reachable; there is no generic request method. Forbidden path
  tokens (withdrawal/transfer/funding/set-leverage/set-account-level/...) are
  rejected even if mistakenly added to the allowlist.

## Data Flow And Order Lifecycle

```text
confirmed public candle + synchronized public quote (reused Phase 3/4)
-> strategy signal (reused Phase 4)
-> deterministic risk veto (reused Phase 4 RiskManager) + demo env gates
-> Decimal tick/lot/min/notional/balance validation (SPOT, long-only)
-> PERSIST order intent (pending_submit)        <-- before any network
-> demo submission with a deterministic client order id
-> ack (live) | API rejection (rejected) | transport timeout (UNKNOWN)
-> UNKNOWN -> query the exchange by client order id (never blind retry)
-> private WS / REST order + fill updates
-> exchange-authoritative reconciliation
-> durable local projection (demo_* tables) + read-only observability
```

Crash-safety and idempotency:

- The intent is persisted before the network call. The client order id is
  deterministic (`d5` + sha256 of account|instrument|intent|signal, <=32 alnum),
  so a retry/reconnect/restart reproduces the same id; OKX rejects a duplicate
  client order id and the local store treats it as the unique key. Duplicate
  economic orders are therefore prevented across retries, reconnects, crashes,
  and DB failures.
- A transport failure/timeout is recorded as `unknown`, never `rejected`, and
  is resolved by querying the exchange by client order id. If the first query
  cannot see an attempted order, it remains `unknown` because exchange
  visibility may be delayed; it is never blindly resubmitted. Only an intent
  proven to have crashed before any place attempt is marked `failed`.
- A late/duplicate order update can never regress a terminal status
  (`filled`/`canceled`/`rejected`/`failed`). Fills are inserted idempotently by
  exchange `tradeId`.

## Long-Running Driver And Startup Gate

`app/execution/driver.py` (`DemoTradingDriver`, started by
`scripts/run_demo_trading.py --run`) is the supervised long-running runtime. It
connects accepted Phase 4 market data, strategy, and risk to the Phase 5
execution lifecycle:

- it acquires and continuously heartbeats the exact runtime lock; if the lock is
  lost it stops (fail closed);
- it runs ONE fail-closed startup gate before trading: acquire lock -> set
  `reconciliation_consistent=false` -> sync server time -> validate the demo
  account (below) -> resolve every non-terminal intent by client-order-id query
  -> exchange-authoritative reconcile -> refuse to be armable while any
  ambiguous (`unknown`) order remains;
- it starts the PUBLIC market-data stream and the AUTHENTICATED private-order
  stream;
- it warms strategy history from persisted public candles (context only; never
  retraded) and processes confirmed `1m` candles forward only;
- it evaluates the approved strategy + deterministic risk veto and submits only
  through `DemoExecutionRuntime` / `OrderLifecycle`;
- it projects private order/fill updates durably and periodically reconciles
  exchange truth;
- it stays DISARMED unless the persisted, expiring arming gate is valid (it
  never auto-arms);
- it shuts down cleanly, cancelling and reaping every supervised task and
  releasing the lock.

Account security validation (before arming, `account_validation.py`): the
account mode (`acctLv`) must be on the approved SPOT cash-only allowlist
(`DEMO_ALLOWED_ACCT_LEVELS`, strictly defaulted and hard-limited to `1`); the configured instruments must be
exactly approved BTC-USDT/ETH-USDT SPOT pairs with a matching quote currency and
a live state; and no liability / borrow / negative cash may be present.
Withdrawal/transfer authority is made unrepresentable by the endpoint allowlist;
least-privilege keys remain an operational requirement at key creation.

Private WebSocket integration: the driver reports `ws_authenticated` only after
BOTH an explicit login acknowledgement and an orders-channel subscription
acknowledgement for every instrument. Each private update is validated
(channel, instrument, client-order ownership, state, side, fill size/price,
identifiers). A foreign or unknown private update fails reconciliation closed
(blocks new entries); fills are recorded idempotently and order updates never
regress a terminal state. REST reconciliation remains authoritative after
reconnect or message loss. New entries are blocked when the private stream is
stale or disconnected (`DEMO_PRIVATE_STALE_SECONDS`).

## Reconciliation And Restart Recovery

At startup (one gate) and periodically, the exchange - not the local ledger - is
authoritative:

1. every non-terminal intent is resolved by querying the exchange by client
   order id; arming is blocked while any `unknown` intent remains;
2. exchange open orders whose client order id we do not recognise - or that
   conflict with a local terminal status / instrument - are FOREIGN: they make
   reconciliation inconsistent, require operator review, and are NEVER cancelled
   automatically;
3. only fills belonging to a known, matching local intent are recorded
   (idempotently); a foreign or mismatched fill fails closed;
4. total base and quote cash balances are compared against an immutable
   first-authenticated baseline adjusted by known owned fills and fees in
   either currency. OKX's preloaded demo assets are reserved inventory and are
   excluded from bot positions/exposure; foreign fills or a later material
   unexplained difference fail closed.

A `consistent=False` result blocks new entries; the runtime cannot be armed into
an inconsistent state, and health reports `reconciliation_consistent=false`
until a successful reconciliation.

## Risk, Kill Switch, And Arming

- Every entry passes the accepted Phase 4 deterministic `RiskManager` (minimum
  confidence, required stop below entry, naive/future/stale rejection, daily
  marked-equity loss lockout, risk-based sizing, leverage locked at 1.0) plus demo
  environment gates (armed, reconciliation consistent, kill switch, feed
  health, synchronized/fresh quote, exposure, max open positions, no duplicate
  entry). A no-trade decision is always valid and preferred.
- Sizing is bounded by the risk fraction, total-exposure cap, a hard per-order
  notional ceiling (`DEMO_MAX_ORDER_NOTIONAL`), and the available quote balance,
  all in `Decimal`. Entries below twice the venue minimum size are refused so
  an entry fee charged in base currency cannot leave a position below the
  minimum protective-exit size.
- Kill switch (persisted): engaging it persists the block FIRST (so new entries
  are blocked immediately), then cancels every owned pending ENTRY order, with
  the true post-cancel state resolved by query. A cancellation that cannot be
  confirmed remains `unknown` and the system stays killed (fail closed). The
  running driver also enforces an externally-engaged kill switch by cancelling
  owned pending entries on its next cycle. Protective EXITS remain possible so
  the switch can never trap a position. Durable amend (`OrderLifecycle.amend`)
  follows the same place/cancel safety: persist, never blind-retry an ambiguous
  POST, and resolve timeouts by querying exchange truth.
- Kill-switch release is authenticated and fail closed: it runs the full
  startup gate, requires exact runtime-lock ownership and a successful
  reconciliation, and refuses while any owned ENTRY intent remains unresolved.
- Arming: DISARMED by default. The runtime may submit orders only after an
  explicit arming action that sets an expiring `armed_until`; arming is refused
  unless reconciliation is consistent. Network mutations stay disabled during
  imports, API startup, tests, and ordinary readiness checks.
- Runtime lock: a single-runner advisory lock (atomic acquire; never
  auto-stolen). A heartbeat-expired lock is released only by the explicit
  `--release-stale-lock` operator command.

## Operator Commands (local CLI only; never HTTP)

```bash
python scripts/run_demo_trading.py --status                 # local DB status
python scripts/run_demo_trading.py --reconcile              # startup gate (needs creds)
python scripts/run_demo_trading.py --arm [--arm-ttl 900]    # gate + arm (needs creds)
python scripts/run_demo_trading.py --disarm
python scripts/run_demo_trading.py --engage-kill-switch     # persist + cancel owned entries
python scripts/run_demo_trading.py --release-kill-switch
python scripts/run_demo_trading.py --release-stale-lock
python scripts/run_demo_trading.py --run [--duration N]     # long-running driver (needs creds)
python scripts/run_demo_trading.py --smoke-test             # read-only demo
```

`--arm` runs the full startup gate (including account validation) and only arms
if armable. `--run` starts the long-running driver, which stays DISARMED unless
the persisted arming gate is valid. `--engage-kill-switch` persists the block
immediately, then cancels owned pending entries (when credentials are present
and no running driver holds the lock; otherwise the running driver performs the
cancellation). Network access happens only inside
`--reconcile/--arm/--run/--smoke-test` and the venue-cancellation half of
`--engage-kill-switch`. `--release-kill-switch` also requires credentials and
network reconciliation; it is never a blind local release.

The smoke test requires demo credentials in the environment AND
`OKX_DEMO_SMOKE_TEST=1` AND the `--smoke-test` flag. It is read-only unless
`--place-test-order` is also passed while armed, in which case it places ONE
far-below-market resting limit order (which cannot fill) and immediately
cancels it, exercising place -> query -> cancel with no economic effect.

## Observability (read-only)

`GET /demo/{health,account,accounts,balances,intents,submissions,fills,
reconciliations,events}`. All routes are GET/HEAD only. No route places,
modifies, cancels, arms, disarms, or otherwise mutates anything, and no
response contains a secret.

## Database Changes

New `demo_*` tables (additive; existing tables unchanged): `demo_accounts`,
`demo_runtime_status` (status, armed_until, kill switch, lock, ws auth),
`demo_order_intents` (durable outbox/projection, unique client order id,
persisted protective stop),
`demo_submissions` (append-only attempts), `demo_order_updates`, `demo_fills`
(unique tradeId), `demo_balance_snapshots`, `demo_reconciliations`,
`demo_daily_baselines`, `demo_events`. Monetary/size values are stored as exact
decimal strings.

## Tests

Offline only (fake transports, fixed clocks, temporary SQLite). Coverage
includes: signing vectors and canonical request construction; secret
non-leakage; demo-header always present; REST/WS hostname allowlists with
production rejection; endpoint allowlist and order-parameter whitelist
(margin/leverage/short rejected before any network); clock-drift fail-closed;
malformed/partial responses; rate-limit/transport-as-unknown and
GET-retry/POST-no-retry; deterministic client ids and idempotent intents/fills;
ambiguous-timeout resolve-by-client-id; delayed not-found remains unknown
without resubmission;
order-update terminal non-regression; restart resolution of open intents;
foreign-order and unexplained-balance reconciliation fail-closed (no
auto-cancel); atomic lock contention and explicit stale-lock release; expiring
arming; kill-switch blocks entries / allows exits / cancels pending entries;
Decimal precision, minimum size, insufficient balance, and notional cap;
read-only enforcement for every `/demo` route.

Driver/integration coverage (`tests/test_demo_driver.py`): account validation
(margin mode / liability / instrument mismatch rejected); the unified startup
gate (lock unavailable, time-sync failure, invalid account, ambiguous-unknown
blocking armability, happy path); WS subscription-ack gating and pre-ack order
suppression; durable amend (ack / timeout-resolve / error-resolve / unknown);
private projection (foreign clOrdId or instrument fails closed, idempotent
fills, invalid side fails closed); kill-switch venue cancellation and the
driver enforcing an externally-engaged kill switch; forward-only,
no-retrospective-trading after warmup; entries blocked on a stale private
stream; entry blocked when the runtime lock is lost; and supervised driver
startup/shutdown (lock released, tasks reaped) including refusal to run on an
invalid account.

## Known Limitations

- A bounded OKX demo integration check completed on June 10, 2026: authenticated
  account reads, instrument metadata, balances, pending orders, fills, and
  reconciliation succeeded. One explicitly armed smoke order was placed far
  below market and immediately canceled successfully. A second bounded visual
  test completed a filled BTC-USDT round trip through the durable application
  lifecycle, finished with zero bot-owned BTC and zero pending orders, then
  disarmed. Long-running private-WebSocket operation and strategy-generated
  trades remain unverified against the venue.
- Unexplained-balance detection uses immutable first-authenticated base and
  quote cash baselines plus owned net fills and fees. OKX's standard preloaded
  demo assets remain reserved inventory: they are not bot positions, cannot be
  sold by the strategy, and are excluded from exposure/equity calculations.
- Persistence uses SQLAlchemy `create_all`; a production migration workflow is
  not present.
- The private WebSocket adapter and the long-running driver are implemented and
  unit-tested offline (auth/subscription-ack/parse/projection/supervision), but
  their long-running live integration remains unverified.
- The demo driver persists one immutable UTC-day starting-equity baseline and
  applies the daily-loss gate to conservative marked equity. Venue-reported
  realized PnL attribution is not used, so deposits, withdrawals, or foreign
  account activity fail reconciliation rather than being treated as strategy
  PnL.
- Account-mode validation is allowlist-based (`DEMO_ALLOWED_ACCT_LEVELS`);
  withdrawal/transfer absence is enforced by the endpoint allowlist (made
  unrepresentable) rather than read from key permissions, which OKX does not
  expose via a clean endpoint. Least-privilege keys remain a key-creation
  requirement.
- The strategy uses the existing public `candle1m` feed; multi-timeframe and
  protective tick-by-tick stops are out of scope.

## Incident Recovery

- Stuck `unknown` intent: re-run `--reconcile`; it queries by client order id
  and projects the true state. An ambiguously submitted order remains unknown
  until exchange truth is established and is never resubmitted automatically.
- Foreign order or unexplained balance: reconciliation is inconsistent, new
  entries are blocked, and the runtime cannot be armed. An operator
  investigates on OKX; foreign orders are never auto-cancelled.
- Crashed runner: the lock is not auto-stolen; once the heartbeat is stale, an
  operator runs `--release-stale-lock`, then `--reconcile` before re-arming.
- To stop trading immediately: `--engage-kill-switch` (blocks entries, cancels
  pending entries) and/or `--disarm` (blocks all new submissions; protective
  exits require re-arming).

## Explicit Prohibition

Phase 5 is demo/simulated only. It authorizes no real-money trading, production
credentials or endpoints, `x-simulated-trading: 0`, withdrawals/transfers,
leverage/margin/derivatives/shorting, account-mode mutation, or Phase 6+ work.
It was independently reviewed by Codex and explicitly accepted by the human
owner on June 10, 2026; acceptance does not authorize real funds, production
access, or any later phase.
