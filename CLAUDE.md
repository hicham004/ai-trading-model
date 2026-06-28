# AI Agent Rules

<!-- Travel-mode safety-block smoke test. Do not merge this PR. -->

These rules apply to Claude Code, Codex, ChatGPT, and every other AI agent
working on this repository. Read this file before doing anything else; it is
loaded at the start of every session.

## Project Summary

An AI-assisted automated OKX trading system, built in human-approved phases.
The long-term goal is a controlled system that can eventually place trades
automatically. It is not merely a dashboard and not a manual trading
assistant. The current validated capability is authenticated **demo
(simulated)** trading only; live automation remains a future capability. The
repository is NOT authorized to place real trades or touch real funds.

## Phase Status

Phases 1-5 are COMPLETE and explicitly accepted by the human owner:

- **Phase 1** - data foundation (baseline).
- **Phase 2/2B** - strategy engine + backtesting with safety corrections;
  historical simulation and research only (accepted June 9, 2026).
- **Phase 3A/3B** - live UNAUTHENTICATED public OKX WebSocket market data
  (BTC-USDT, ETH-USDT) + hardening (accepted June 9, 2026).
- **Phase 4** - local paper trading: forward strategy evaluation on public
  data, virtual fills/balances, deterministic risk vetoes, local
  journaling/reconciliation (accepted June 9-10, 2026).
- **Phase 5** - authenticated OKX **demo/simulated** trading (BTC-USDT and
  ETH-USDT SPOT cash, long-only). Independently reviewed by Codex and accepted
  June 10, 2026; validated against the live OKX demo API June 10-11, 2026
  (authenticated reads, sustained 4-hour private WebSocket run, 481/481
  consistent reconciliations, kill switch, account-partition guard, and an
  owner-authorized operator round-trip validating fill handling, position
  sync, live software-stop tracking, the exit path, and post-exit
  reconciliation). Declared COMPLETE by the human owner on June 11, 2026.
  Records: `docs/PHASE5_DEMO_TRADING.md`, `docs/PHASE5_REVIEW_NOTES.md`,
  `docs/PHASE5_VALIDATION.md`.

**Phase 6a is AUTHORIZED** (human owner, June 11, 2026) — the mechanical
shadow period ONLY: a long-running unattended demo shadow run, SPOT BTC-USDT,
long-only 1x, `x-simulated-trading: 1`, software stop (accepted for demo per
the documented live blocker), `ma_crossover` UNTOUCHED. Scope: hardened shadow
supervisor (gated auto-restart, bounded restart budget, heartbeat file, daily
log rollover), decision journal, daily summary reports, persisted shadow risk
caps (10 USDT/entry, 1 open position, 3 entries/day, 1 USDT max daily loss
then disarm-for-day), and the offline `ma_crossover` clearance-rate study. The
supervisor may re-arm after a clean gated restart; ANY reconcile
inconsistency, wrong-scope, or foreign detection means permanent disarm until
the operator intervenes. No changes to the reviewed safety core beyond the
explicitly owner-approved `candle1H` public-channel allowlist entry; the live
run is started only by the human operator.

Phase 6a amendments (owner, June 12, 2026):

- **Strategy timeframe is 1H**, set in `config/shadow_period.json` (never a
  code constant), per the clearance study (stored 1H history clears the 0.60
  floor 87.5% vs 0/117 on live 1m). The 0.60 floor and the strategy logic are
  untouched; 1m evidence remains an open research question. One timeframe
  flows everywhere (feed subscription, driver candle filter/gap checks, stop
  evaluation on confirmed 1H closes — i.e. hourly, account identity, shadow
  evaluation); warm-up needs ~30 live 1H candles, so the first possible
  signal is ~30h after a (re)start.
- **The run uses account `demo-shadow-1h`** (timeframe is part of the
  immutable demo account identity, which requires a new account name;
  `demo-seeded` keeps the 1m Phase 5 history intact). The earlier wrong-scope
  gating window (June 11 fills aging out of the venue's 3-day window, ~June 14
  17:25 UTC) has PASSED, and `demo-shadow-1h` has zero fills, so wrong-scope
  no longer applies. The account has had no successful authenticated contact
  yet, so its first clean `--gate-check` doubles as the live integration smoke
  test of the 1H change (1H identity + `candle1H` feed + warm-up together) and
  the first `--run` heartbeat is the proof of 1H candle delivery.

**Phase 6a hardening landed (June 19, 2026, commit `4b63bde`).** The 1H
candle-gap recovery fix adds an entry-only continuity latch, bounded public
REST backfill, two live-candle confirmations before clearing the latch, a
3-successes/24h recovery cap, REST/WS divergence detection, exit/stop
evaluation independent of the entry latch, and sticky ALERT state across
restarts. This fixed a reviewed safety regression where a candle-gap latch
could also block exit/stop-loss evaluation. The implementation touches the
demo execution driver and shadow supervisor only inside the already
authorized Phase 6a demo scope; it does not retune `ma_crossover`.

**Phase 6a operational evidence (June 21-27, 2026):** local shadow reports show
the first organic 1H shadow trade on June 21 (19 LONG signals, 7 clearing the
0.60 floor, one allowed entry, one round-trip, small demo cash loss, and
consistent reconciliation in the daily report). They also show the
home/residential run was not durable enough for unattended travel: June 22 had
private-WS authentication flapping and thousands of supervisor re-arm events,
and June 27 had no authenticated private-WS/reconciliation progress. Repeated
OKX `50110` IP-whitelist failures remain expected whenever the residential
egress IP changes.

**Current operator-reported run plan (June 28, 2026):** migrate the Phase 6a
shadow run to a static-IP DigitalOcean Singapore VPS on Ubuntu 24.04 with
PostgreSQL, the `demo-shadow-1h` account, 1H timeframe, Telegram operator
notification, and a fail-closed `systemd` service plus nightly `pg_dump`
backup. Agents must verify the actual host state before relying on it:
checkout at `origin/main`, 530 tests passing, `.env` secrets present but never
printed, `DEMO_ACCOUNT_NAME=demo-shadow-1h`, `SHADOW_PERIOD_ENABLED=1`,
PostgreSQL available, `--gate-check` returning `armable=True`, Telegram test
notification delivered, and `ai-shadow`/heartbeat/state showing the run is
healthy. Do not infer these facts from this file alone.

**Phase 6b (news agent, log-only) is designed but NOT authorized.** Phase 6b
and all later phases require explicit human approval before any work begins.
The operator is travelling for roughly one week around June 28, 2026; while
away, no agent may advance a phase, weaken a safety rule, make a safety-core
change, merge/deploy autonomously, or treat a clean test run as approval.

## Standing Safety Contract

- **Demo-only until the human operator explicitly says otherwise.** Every
  authenticated request sends `x-simulated-trading: 1` to a strict
  regional-hostname allowlist. Production mode, `x-simulated-trading: 0`,
  withdrawals/transfers, leverage, margin, derivatives, shorting,
  account-mode mutation, demo-balance reset, generic arbitrary-endpoint
  methods, and mutating HTTP routes are forbidden and must stay
  unrepresentable in code.
- **SPOT cash, long-only, leverage locked at 1.0**, BTC-USDT/ETH-USDT only.
- **An AI or LLM must never directly place, approve, modify, or cancel an
  order.** Orders flow only through the strategy engine, deterministic risk
  manager (final veto), and controlled execution module for an explicitly
  approved phase. No demo order may be submitted except under an explicitly
  armed, separately opted-in, operator-authorized smoke test.
- **Fail closed on ambiguity**: inconsistent reconciliation, ambiguous
  account selection, unknown order outcomes, stale feeds, or lost locks block
  new entries; never guess, never blind-retry a submission.
- **No real/production API keys.** Never request, store, print, log,
  screenshot, prompt, or commit secrets. Never implement withdrawals or
  request withdrawal permissions.
- **No retuning of live/running strategies.** Strategy or risk-parameter
  changes (including the 0.60 confidence floor) are scope changes requiring
  explicit owner approval; research analysis is fine, acting on it is not.
- **No martingale, doubling down, or automated loss chasing.**
- **Exchange-side protective stops are a HARD BLOCKER for any live phase.**
  The current stop is software-only (enforced only while the runtime process
  is alive), accepted for demo only. See `docs/PHASE5_DEMO_TRADING.md`.
- **No auto-commit.** Commit only when the operator asks. A passing backtest
  or test suite never authorizes paper, demo, or live execution, and no agent
  may approve its own implementation or declare a phase complete.
- **Stop and ask** before changing agreed scope, adding authenticated
  exchange access, advancing phases, or on any conflict between instructions
  and this contract.

## Operational State

- Active demo account: **`demo-shadow-1h`** (`DEMO_ACCOUNT_NAME` in `.env`)
  for the Phase 6a 1H shadow run; **`demo-seeded`** holds the accepted Phase 5
  1m history (identities are immutable, so each timeframe has its own
  account). Account selection must be explicit; the account-partition guard
  fails closed when several local accounts share a key fingerprint.
- **Flatness definition (official):** a position is flat when
  `floor(position, lot_size) == 0` (`is_flat()` in
  `app/execution/precision.py`). Base-currency fees are finer than the lot
  size, so exact-zero is unreachable; sub-lot residue is unsellable dust.
- Operator CLI: `scripts/run_demo_trading.py`
  (`--status/--reconcile/--arm/--disarm/--engage-kill-switch/...`).
- AgentOps travel mode is merged on `main`: PR-based workflow, CI safety
  guard, and Telegram notification tooling exist for code-review process only.
  They do not run or protect the demo shadow process; the shadow run's
  durability depends on the VPS/service setup above.
- Telegram notification surfaces are separate and must not be confused:
  - **VPS/shadow-side notification:** the repo provides the generic,
    secret-redacting notifier in `app/notify/telegram.py` and the CLI wrapper
    `scripts/notify_telegram.py`. Credentials come from the VPS process
    environment (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, optional
    `TELEGRAM_DRY_RUN`), not from GitHub secrets. The CLI does not load `.env`
    by itself; if it is run under `systemd`, an `EnvironmentFile` or another
    export mechanism must put those variables into the service environment.
    The repo proves the notifier/CLI and `report_ready` event exist; it does
    not currently show the shadow supervisor or execution runtime wired to send
    Telegram messages for fills, ALERT files, stale heartbeat, private-WS auth
    drop, or permanent halt. If those runtime notifications are configured on
    the VPS, verify them on that host before relying on them.
  - **CI/code notification:** `.github/workflows/notify.yml` is merged on
    `main` and runs in GitHub Actions via `workflow_run` after pull-request CI.
    It uses GitHub Actions repository secrets named `TELEGRAM_BOT_TOKEN` and
    `TELEGRAM_CHAT_ID`, not the VPS `.env`, and emits `ci_pass`, `ci_fail`, or
    `safety_fail` based on the trusted CI conclusion and summary artifact. The
    current workflow does not send `pr_opened` or `pr_updated` notifications.
    External GitHub repo setup still must be confirmed there: repo secrets
    present, and `TRAVEL_MODE=1` set while travelling so safety-sensitive PRs
    fail closed.
- Operator security item: the Telegram bot token was operator-reported as
  exposed on screen during VPS setup. Revoke/regenerate it in BotFather before
  relying on notifications, then update every configured location: the VPS
  exported environment / `systemd` `EnvironmentFile`, and the GitHub Actions
  repository secret `TELEGRAM_BOT_TOKEN` if CI notifications are enabled. Do
  not paste tokens or chat ids into the repo, chats, screenshots, or logs.

## Deferred / Open Items (tracked)

1. Organic strategy-generated demo round-trip - first observed in the June 21
   Phase 6a shadow report; continue collecting out-of-sample evidence.
2. Exchange-side protective stops (`slTriggerPx`/`slOrdPx` or
   `attachAlgoOrds`) - implement + independent review + demo validation
   before ANY live phase.
3. Delete the stale empty `demo` account row sharing the demo key
   fingerprint (reviewed cleanup; the partition guard fails closed until
   then).
4. Research: historical clearance rate of the current `ma_crossover` config
   vs the 0.60 confidence floor (analysis only; no retuning authorized).
5. Safety-core adoption of lot-precision flatness (driver stop check / exit
   gating still treat `position > 0` as open) - future reviewed change.
6. Position persistence across restarts requires a reviewed change before any
   live phase: today a restart rebuilds the strategy window from live candles,
   so the warm-up FLAT closes any open position via the reviewed exit path
   (accepted for demo, June 12, 2026; crash churn = real fees live). This is
   higher priority on an always-on VPS/systemd host because reboots/restarts
   are more operationally realistic.
7. Persistence uses `create_all`; no production migration workflow. This is
   higher priority on an always-on PostgreSQL VPS; add a reviewed migration
   workflow before any live phase, and use operator-managed backups (e.g.
   nightly `pg_dump`) for the demo shadow period.

## Completion And Change Control

A phase is complete only when all of the following are true:

- the approved implementation exists;
- normal tests pass;
- adverse and safety tests pass;
- reviewer findings are resolved;
- documentation matches actual behavior;
- an independent review has occurred; and
- the human owner explicitly approves completion.

Tests alone are never phase approval. Stop and ask before changing the agreed
scope, adding authenticated exchange access, or advancing to another phase.

See `PROJECT_RULES.md`, `docs/PHASES.md`, and the per-phase review/validation
documents referenced above.
