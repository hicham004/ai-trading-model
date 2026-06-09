# Phase 2 Review Notes

## Status

The findings in this document were corrected through Phase 2B, independently
verified by Codex, and explicitly accepted by the human owner on June 9, 2026.
Phase 2/2B is an accepted historical-research baseline. It does not authorize
Phase 3, paper/demo trading, private OKX access, or real orders.

## Codex Review Findings

### 1. Phase Authorization Was Invalid

The prototype was described as complete even though the governing documents
authorized Phase 1 only and required explicit human review before expansion.
An agent-authored roadmap cannot grant its own phase approval.

### 2. Stop-Loss Gap Fills Are Optimistic

When a bar gaps beyond a stop, the simulator fills at the stop price rather
than a realistic available price. This can materially overstate equity and
understate drawdown.

Required correction:

- model gap-through-stop execution conservatively;
- include spread/slippage at the executable price; and
- add adverse tests for large overnight/intrabar gaps.

### 3. Stale-Data Gate Is Miswired

The simulation supplies the execution candle timestamp as both decision time
and data time. A signal from an older candle can therefore appear fresh.

Required correction:

- distinguish signal time, source-data time, and execution time;
- enforce signal expiration and maximum age; and
- test delayed and out-of-order signals.

### 4. Simulation-Only Enforcement Is Weak

The simulator accepts any broker implementation but labels the result as a
simulation. A broker returning non-simulated fills can be injected without
rejection.

Required correction:

- enforce a simulation-safe broker contract;
- reject non-simulated fills in backtests; and
- test that execution-capable brokers cannot enter the backtest path.

### 5. Signal Identity And Alignment Are Not Validated

The simulator checks signal-list length but does not adequately verify
instrument, timeframe, timestamp, or candle alignment. Misidentified or
future-dated signals can be accepted.

Required correction:

- validate instrument and timeframe;
- validate timestamps and ordering;
- reject future, duplicate, stale, and misaligned signals; and
- add explicit adverse tests.

### 6. Passing Tests Missed Important Failures

All 80 tests passed during review, but the adverse cases above were not
covered. Test count is not a safety argument.

## Additional Realism Requirements

Before Phase 2 approval, backtests must explicitly cover:

- fees;
- bid/ask spread;
- slippage;
- funding where applicable;
- gaps through stops;
- stale and expired signals;
- wrong instrument/timeframe/timestamp signals;
- missing, duplicate, and out-of-order market data;
- no look-ahead bias; and
- later out-of-sample and walk-forward validation.

## Phase 2B Correction Status

> The sections below retain the builder's correction record. Codex subsequently
> verified the complete correction set and the human owner approved Phase 2/2B.

### Finding 2 - Stop-Loss Gap Fills: verified

- `app/backtest/simulator.py` now models gap-throughs conservatively for a long
  stop:
  - bar opens at/above the stop and its low pierces it -> fill reference = stop;
  - bar opens BELOW the stop (gap-down) -> fill reference = the worse open, not
    the unavailable stop price.
- The chosen reference is routed through the simulation broker, so sell
  slippage and fees still apply.
- OHLC assumption is documented in the simulator module docstring.
- Verification: `tests/test_simulator.py` adds
  `test_stop_loss_gap_through_fills_at_open_not_stop` (entry ~100, stop 95, next
  bar opens at 80 -> exit reference 80, pnl -2000, equity 8000),
  `test_stop_loss_intrabar_pierce_fills_at_stop`, and
  `test_stop_loss_gap_routes_through_broker_slippage`. The pre-existing
  `test_stop_loss_exit_is_recorded` was corrected from an optimistic 9500 to the
  conservative 9000 (gap-at-open fill).

### Finding 3 - Stale-Data/Signal Gate: verified

- `RiskContext` now carries distinct `now` (execution time) and `data_time`
  (signal/source-candle time). The simulator passes `data_time=signal.timestamp`
  and `now=execution_candle.timestamp`.
- The risk manager rejects naive timestamps (`naive_timestamp`), future-dated
  signals (`future_signal`), and stale signals (`stale_data`).
- Verification: `tests/test_risk_manager.py` adds
  `test_one_hour_old_signal_rejected_at_one_minute_staleness`,
  `test_rejects_future_dated_signal`, and `test_rejects_naive_timestamps`;
  `tests/test_simulator.py` adds `test_stale_signal_wiring_rejects_entries`
  (one-minute staleness rejects every hourly-bar entry, which the old
  same-timestamp wiring would have allowed).

### Finding 4 - Simulation-Only Enforcement: verified

- `Broker` has an explicit `is_simulation` capability flag (default `False`);
  `PaperBroker` sets it `True`.
- The simulator refuses any broker whose `is_simulation` is not `True` before it
  submits anything, and validates every returned fill (`is_simulated` true,
  matches the order, finite values) BEFORE any cash/position accounting, so a
  bad fill cannot leave partial state.
- Verification: `tests/test_simulation_only.py` adds a non-simulation broker
  (rejected before any submit; `submit_calls == 0`) and a broker that falsely
  claims simulation but returns a non-simulated fill (rejected on the first
  submit; `submit_calls == 1`, run aborts).

### Finding 5 - Signal Identity And Alignment: verified

- New `app/backtest/validation.py` validates, before any orders: one instrument
  per simulation; tz-aware, strictly increasing (no duplicate/out-of-order)
  candle and signal timestamps; positive/finite OHLC and coherent OHLC
  relationships; signal/candle count, instrument, and timestamp alignment; and
  timeframe where metadata is present.
- Timeframe metadata was added as an optional, backward-compatible field on
  `MarketCandle` and `Signal`, populated by the database runner and propagated
  to signals in `Strategy._validate_output`.
- The simulator also asserts finite cash/equity/trade results at the end.
- Verification: `tests/test_backtest_validation.py` covers each adverse case and
  two simulator-level integration rejections (wrong instrument, misaligned
  timestamps).

### Finding 6 - Adverse Coverage: verified

- Adverse/regression tests were added for every finding above. Test count alone
  is still not a safety argument; independent review is required.

## Phase 2B Second-Round Corrections

> These follow-up corrections were independently verified as part of the final
> Phase 2B review.

### Round 2, Item 1 - Fill/order matching: verified

- `app/backtest/simulator.py:_execute_simulated` now validates that each
  returned fill matches the submitted order's instrument, side, quantity
  (strict float compare via `math.isclose`), and timestamp, in addition to the
  existing `is_simulated` and finiteness checks. All checks run BEFORE any
  cash/position/trade mutation, so a bad fill aborts the run with no partial
  state.
- Verification: `tests/test_simulation_only.py` parametrises a simulated broker
  that returns a fill with double quantity, the wrong timestamp, the wrong
  instrument, or the wrong side; each is rejected on the first (entry) submit
  (`submit_calls == 1`).

### Round 2, Item 2 - Next-bar execution semantics: verified

- The simulator previously executed a previous-bar signal at the execution
  bar's CLOSE (look-ahead: the close is unknown when the bar opens). Normal
  signal execution now uses the execution bar's OPEN for entries and exits,
  used consistently for risk checks, position sizing, and the order. Stop-loss
  handling still runs first and keeps the conservative gap behaviour; a stop
  exit blocks same-bar re-entry. End-of-data liquidation still uses the final
  close (documented as terminal bookkeeping, not a tradable signal).
- Verification (`tests/test_simulator.py`): a bar-0 signal executes at the
  bar-1 open (120) not its close (90); a FLAT signal exits at the next bar's
  open; the final bar's signal is never executed; and no same-bar re-entry
  occurs after a stop.

### Round 2, Item 3 - Timeframe-aware signal staleness: verified

- A fixed two-hour staleness wrongly rejected valid previous-bar signals on 4H
  and 1D candles. New `app/strategy/timeframes.py` parses supported OKX
  timeframes (`m`/`H`/`D`/`W`) and rejects unknown formats. `run_strategy_backtest.py`
  gains `--max-signal-age-seconds`; when omitted, the limit is derived from the
  timeframe (one bar interval) so exactly the immediately-previous completed
  candle is fresh. Stale/future/naive rejection stays fail-closed.
- Verification (`tests/test_timeframes.py`): valid/invalid timeframe parsing;
  override vs derived resolution; 1H works with the normal default; 4H and 1D
  work with the derived default; an explicit one-minute limit still rejects a
  one-hour-old signal; unknown timeframes fail clearly; the CLI flag is parsed,
  validated, and fed into `RiskLimits`. The original one-hour-vs-one-minute
  regression test is unchanged.

## Phase 2B Third-Round Corrections

> These final corrections were independently verified as part of the final
> Phase 2B review.

### Round 3, Item 1 - Same-candle stop after entry: verified

- Previously the stop was only checked before opening a position, so a position
  entered at a bar's open could not be stopped out by that same bar's low (e.g.
  enter at 100, the bar trades to 80 through a 90 stop). The stop check is now
  factored into `apply_stop_loss(candle)` and is also run immediately after an
  entry, so a freshly opened position can be stopped out on its own bar. The
  entry open is above the stop, so the same-bar fill is at the stop price.
- Verification: `tests/test_simulator.py::test_stop_loss_triggers_on_same_bar_as_entry`
  (entry at 100, same bar low 80 -> stop fill 90, entry_time == exit_time,
  equity 9000).

### Round 3, Item 2 - Timeframe-aware staleness in the core path: verified

- Timeframe-derived staleness previously only applied through the CLI; calling
  `run_backtest_on_stored_candles` (or `run_signal_backtest`) directly fell back
  to the fixed two-hour default and rejected valid 4H/1D previous-bar signals.
  Now, when no `risk_manager` is supplied, the simulator derives the staleness
  from its `timeframe` argument (or a new `max_signal_age_seconds` override,
  threaded through the runner). Passing both an explicit risk_manager and the
  override is refused.
- Verification: `tests/test_strategy_runner.py::test_runner_is_timeframe_aware_for_4h`
  and `..._for_1d` (runner called directly, no risk_manager -> `rejected_entries == 0`,
  trades occur).

### Round 3, Item 3 - Invalid timeframe under override: verified

- `resolve_max_signal_age` now validates the timeframe FIRST, even when an
  override is supplied, so an unsupported timeframe (e.g. `1Q`) is rejected
  rather than silently accepted because `--max-signal-age-seconds` was passed.
- Verification: `tests/test_timeframes.py::test_resolve_validates_timeframe_even_with_override`
  (parametrised over `1Q`, `1M`, `abc`, `H1`).

## Remaining Limitations And Assumptions

- The intrabar price path is unknown. Normal signal execution uses the next
  bar's open; the non-gap stop assumption (fill at the stop when the bar opens
  at/above it, including the entry bar) remains the standard, slightly
  optimistic model. Only the gap-down stop case is made conservative.
  End-of-data liquidation uses the final close.
- Derived signal staleness equals exactly one bar interval, so a signal more
  than one bar old (e.g. across a missing bar) is rejected as stale. This is
  intentional fail-closed behaviour, not a guarantee about real feeds.
- Bid/ask spread is not yet modelled as a separate component; slippage_rate is
  the current proxy. This is noted for a later realism pass.
- Signal-level timeframe validation only triggers when timeframe metadata is
  present; direct (test) construction without timeframe is unvalidated for
  timeframe by design (documented backward-compatibility choice).
- Out-of-sample / walk-forward validation (Additional Realism Requirements) is
  explicitly out of Phase 2B scope and remains open.

## Verdict

Phase 2B passed independent Codex review on June 9, 2026: 150 offline tests,
static checks, security-scope scanning, and targeted reproductions of the final
three blockers passed. The human owner then explicitly accepted Phase 2/2B.

This acceptance is limited to historical simulation and the documented
modelling assumptions. It is not a profitability claim and does not authorize
Phase 3, paper/demo trading, private OKX access, or live trading.
