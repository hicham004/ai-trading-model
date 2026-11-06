# R14 part A review notes (lot-precision gating and stale-lock disarm)

**Reviewed:** 2026-11-05 (round 1, final review)
**Branch:** `sprint-6/position-persistence`, created from `origin/main` `57f89c0`
(June 2026 code); worktree `C:\Users\Admin\Desktop\ai-trading-partA`.
**Status:** independent agent review complete. Verdict below. Merge, deploy and
phase advance remain the owner's decisions; nothing here authorizes them.

## Scope

Part A of `docs/design/POSITION_PERSISTENCE.md` (the design lives on branch
`plan/auto`): section 5.4 (lot-precision flatness in the safety core), section
5.5 (`release_stale_lock` also disarms), section 6 rows 13 and 14, section 7
tests C (items 21-27) and D (items 28-29), reviewed by the path of section 9
and the owner's decision of section 12 (part A alone first, from `main`).

Part B (the resume protocol: sections 5.2, 5.3, the 5.6 heartbeat and
daily-report fields, the supervisor call order, tests A, B, E, F) is NOT part
of this branch. `app/shadow/`, `app/execution/runtime.py`,
`app/execution/identity.py`, `config/` and the strategy are untouched.

The reviewers worked in three lenses (safety invariants I1-I7 and the P0 list;
correctness and Decimal edge cases; tests, docs and PR hygiene), each finding
was checked by a verifier, a fix round followed, and this final review re-read
the complete change, re-ran the suite and ran its own mutation checks on a
scratch copy. The worktree was never edited by the reviewers.

## Changed files

| File | What changed | Safety-sensitive |
|---|---|---|
| `app/execution/driver.py` | `PositionView` (net, sellable, remainder, stop, flat; one definition), `_position_view`, `_note_unsellable_remainder`; the per-candle stop check and the FLAT exit gate use `sellable > 0` and pass the raw net to `consider_exit`; the entry gate receives the sellable size; `_equity_exposure` counts only sellable positions, marks any residue with a usable quote, fails closed without one unless the residue is sub-lot dust | yes |
| `app/execution/store.py` | `release_stale_lock`: the same guarded UPDATE also clears `armed_until`; `disarmed_on_stale_lock_release` (warning) recorded in the same transaction only when a stale lock was released | yes |
| `app/execution/precision.py` | docstring of `is_flat` updated to the new behaviour; no logic change | yes (surface; docstring only) |
| `scripts/run_demo_trading.py` | `_print_positions` (the `--reconcile`/`--arm` position lines) reuses `PositionView.from_summary` read-only: FLAT at lot precision / OPEN with sellable size / unsellable remainder; `--release-stale-lock` prints that arming was cleared or untouched | yes (operator CLI; read-only output change) |
| `tests/test_demo_driver.py` | helpers (`_armed_driver`, base-fee entry, residue-leaving exit, event readers) and 11 new tests (24 cases with parametrization) | no |
| `tests/test_demo_execution.py` | helpers and 2 new tests for the stale-lock release | no |
| `docs/PHASE5_DEMO_TRADING.md` | "Lot-precision gating" paragraphs (definitions, no-quote rule, observability), runtime-lock bullet and crashed-runner bullet (release also disarms) | no |
| `docs/PHASE5_VALIDATION.md` | flatness refinement dated 2026-11-05; open item 5 updated | no |

No new files besides this record. No identity field (`demo_identity_config`),
cap, floor, endpoint, allowlist, header or kill-switch value changed.

## Findings

| Id | Lens | Severity | Verdict | Resolution |
|---|---|---|---|---|
| safety-F1 / correctness-F1 / tests-docs-F1 | safety, correctness, docs | P2 | confirmed (three verifiers reproduced it): a residue without a usable quote was marked at zero, so a cash-only immutable daily baseline could be created and the daily-loss veto biased by up to one venue-minimum order; the docs omitted the no-quote rule | fixed: `_equity_exposure` fails closed for a sellable position OR an unsellable remainder without a usable quote (`app/execution/driver.py:698-702`, exactly `main`'s behaviour); only sub-lot dust is marked at zero and skipped (`driver.py:703`, bounded below one lot's value, about 0.001 USDT on BTC-USDT at 100,000; 1.2E-5 USDT for the live dust); rule and bounds in the docstring, `docs/PHASE5_DEMO_TRADING.md:188-195`, and tests `tests/test_demo_driver.py:1252` and `:1369`. The remaining dust exception is the one deliberate deviation from G5's letter; it is required by G3 in the two-instrument shape, is bounded (less than one lot), documented and tested, and is accepted as P3 |
| safety-F2 | safety | P2 | confirmed: no test pinned the rewired entry gate; mutants passing `Decimal(0)` or `open_positions=0` left the whole suite green | fixed: `tests/test_demo_driver.py:1294` (every LONG refused with `position_already_open`, the sellable size and `open_positions == 1` reach the gate, only the warm-up FLAT sell is placed); this review's mutations M10 and M11 confirm it bites |
| correctness-F2 / safety-F4 / tests-docs-F5 | correctness, docs | P3 | partly refuted by the verifier: the shadow `stop_eval` journal line and the report's breach count are not in this diff and already fire on dust today; the documentation gap was confirmed | fixed by one documentation sentence (`docs/PHASE5_DEMO_TRADING.md:197-204`); the supervisor code change was declined as out of part A scope (`app/shadow` untouched by instruction; a later reviewed supervisor change) |
| safety-F3 | docs | P3 | confirmed | fixed: remainder reachability (a partially filled then cancelled order: an exit, or an entry cancelled by the kill switch, the venue or the operator) and its bound stated in `PositionView` and the docs |
| correctness-F3 / tests-docs-F4 | correctness, docs | P3 | confirmed: the `unsellable_remainder` dedupe memory is per process | fixed by wording (`driver.py:240-244`, `:716-725`, `docs/PHASE5_DEMO_TRADING.md:197-199`); persisting the last value declined (no new store query in the safety core for an observability event) |
| correctness-F4 / tests-docs-F6 | tests | P3 | confirmed: boundaries, the two-instrument shape and the merge path were untested | fixed: `tests/test_demo_driver.py:1347` (7 boundary nets, exclusivity, agreement with `validate_sell`), `:1369` (BTC residue without a BTC quote beside ETH), `:1396` (row 13 merge path, new remainder reported again, never sold alone). The `meta is None` branch of `_equity_exposure` stays untested: unchanged behaviour, unreachable from `step` |
| tests-docs-F2 | docs | P3 | confirmed | fixed: `docs/PHASE5_VALIDATION.md:158-164` dated refinement, open item 5 updated |
| tests-docs-F3 | docs | P3 | confirmed | fixed: the design reference is qualified (the design lives on `plan/auto`; definitions restated in `PositionView`) |
| tests-docs-F7 | tests | P3 | confirmed as a preference | declined with reason: the full report lines pin the numbers the operator reads |
| final-R1 (this round) | docs | P3 | confirmed | open: `docs/PHASE5_VALIDATION.md:184-186` (open item 5) says "restart `shadow.service` after the merge" without the precondition that the shadow run is FLAT at lot precision; a restart's warm-up FLAT sells an open position through the reviewed exit path (open item 6; design section 12). Suggested text: "deployment to the VPS is an operator step: restart `shadow.service` after the merge only while the heartbeat reports `flat_at_lot: true` (open item 6)". Not blocking |

Design conformance notes (not defects): the helper is `_position_view(inst, meta)`
returning a frozen `PositionView` with an added `remainder` field rather than the
design's `(net, sellable, stop, flat)` tuple, and lives in the driver; the
supervisor's `_day_pnl` was not re-pointed at it (design: "unchanged in effect";
`app/shadow` untouched in part A); exposure sums sellable value and equity adds
the net value, as the 5.4 table says; `scripts/run_demo_trading.py --status`
prints no position line on `main` (the lot-precision line comes from the
`--reconcile`/`--arm` gate and the heartbeat's `flat_at_lot`).

## Invariants and the P0 list

- I1: `position_summary` unchanged; reconciliation and the reports keep the raw net.
- I2: the new calls sit inside the actionable branch of `step`
  (`driver.py:577-583`); context and backfill candles never reach them.
- I4: for a sellable position the stop check and the FLAT exit are the same
  condition as before with the raw net passed to `validate_sell`
  (`driver.py:585-597`, `:644-653`); dust and remainder exits were already
  no-ops (`exit_precision_rejected`), so no exit is lost or delayed.
- I5: no new endpoint or mutating route; the only writes are local
  `demo_events` rows and the existing lock UPDATE.
- I6: `app/execution/identity.py`, `config/` and the settings contract untouched.
- I7: caps, the 0.60 floor, arming TTL, the kill switch, the lock WHERE clause
  and foreign/wrong-scope handling untouched; the stale-lock release is
  stricter (also disarms); the sub-lot-dust no-quote exception is the single
  bounded deviation, recorded above.
- P0 list: demo-only headers and hosts, long-only SPOT, caps, kill switch,
  arming TTL, partition guard and fail-closed reconciliation unchanged; no LLM
  order authority; no secret in the diff (tests use the existing fakes).
- Scope: Phase 6a demo; no phase declared complete or authorized;
  `CLAUDE.md`, `PROJECT_RULES.md`, `docs/PHASES.md` untouched.

## Tests

Design section 7, parts C and D (all run from the worktree, offline):

| # | Test | Status |
|---|---|---|
| 21 | `test_dust_does_not_block_entry_with_position_already_open` | passed (new) |
| 22 | `test_dust_does_not_count_as_open_position_for_max_open_positions_or_exposure` | passed (new) |
| 23 | `test_dust_with_stale_stop_skips_stop_check_and_evaluates_strategy` | passed (new) |
| 24 | `test_sellable_position_still_exits_on_stop_breach_and_on_flat[stop,flat]` | passed (new; regression guard, raw net asserted through a `consider_exit` spy, sell size `0.00099999`) |
| 25 | `test_unsellable_remainder_is_reported_not_traded_and_does_not_block_entry` | passed (new) |
| 26 | `test_equity_includes_residue_value_but_exposure_excludes_it[sub_lot_dust,unsellable_remainder]` | passed (new; includes the no-quote rule) |
| 27 | `test_existing_is_flat_dust_case_unchanged` = the existing `tests/test_demo_execution.py::test_is_flat_lot_precision_dust`, unchanged | passed |
| 28 | `test_release_stale_lock_also_disarms_and_records_event` | passed (new) |
| 29 | `test_release_stale_lock_does_not_touch_a_fresh_lock_or_its_arming` | passed (new; regression guard) |

Beyond the design list, all passing: `test_print_positions_reports_sellable_and_remainder_state[open,dust,remainder]`,
`test_sellable_position_blocks_entry_with_position_already_open` (safety-F2),
`test_position_view_boundaries_are_exclusive_and_agree_with_validate_sell` (7 nets),
`test_two_instrument_residue_without_quote_dust_is_skipped_remainder_fails_closed[2]`,
`test_remainder_is_merged_by_the_next_entry_and_a_new_remainder_is_reported_again`.

Design part G (existing tests that must stay green): the named driver, store
and reconcile tests (34 selected) pass; `tests/test_shadow_supervisor.py` 38
passed; `tests/test_migrations.py` and `tests/test_demo_stops.py` do not exist
on `main` (not applicable to part A).

Full suite: `python -m pytest -q -p no:cacheprovider` from the worktree with
the repository venv: **exit code 0, `569 passed in 11.46s`** (545 on the
untouched base; the 24 added cases are the new tests). `git diff --check`:
clean (exit 0). `python -m compileall -q app scripts` (CI's syntax step): exit 0.

Mutation checks by this review (scratch copy only; the worktree was not
touched): twelve single-line mutants of the change, each caught by at least one
new test: stop check back to the raw net (M1), FLAT gate back to the raw net
(M2), floored size passed to the exit instead of the raw net (M3),
`armed_until` no longer cleared on stale release (M4), dedupe disabled (M5),
remainder boundary inclusive at `min_size` (M6), sellable boundary exclusive at
`min_size` (M7), unquoted remainder skipped (M8), equity excludes the residue
(M9), entry gate passed `Decimal(0)` (M10), `open_positions` always 0 (M11),
no fail-closed return without a quote (M12).

CI note: `main`'s workflow runs the offline suite on Python 3.12 and the
travel-mode guard. Run on a scratch commit of this diff, the guard lists four
safety-sensitive files (`driver.py`, `precision.py`, `store.py`,
`run_demo_trading.py`); with the repository variable `TRAVEL_MODE` unset or `0`
it reports and passes (exit 0); with `TRAVEL_MODE=1` it fails by design until
the owner turns travel mode off after review.

## Verdict

**SAFE TO MERGE**

Highest-severity open finding: **P3**, `docs/PHASE5_VALIDATION.md:184-186`
(final-R1, the missing flat-at-lot-precision restart precondition in open
item 5). No P0, P1 or P2 finding is open.

Merge, deploy and phase advance remain the owner's decisions. This branch was
reviewed by agents independent of its author (three lens reviewers with
verifiers, a fix round, and this final review); a clean suite and a clean
review are recommendations, never an authorization. Nothing in this change
trades, arms or touches the VPS; the running shadow account is affected only
after the owner deploys it.

## What the owner does next

1. Open and merge the pull request `main` <- `sprint-6/position-persistence`
   (compare page:
   `https://github.com/hicham004/ai-trading-model/compare/main...sprint-6/position-persistence`).
   CI must be green; if the travel-mode guard fails, the repository variable
   `TRAVEL_MODE` is on and the owner turns it off after this review. The
   `CLAUDE.md` open item 5 text ("driver stop check / exit gating still treat
   `position > 0` as open") is the owner's edit at merge; the P3 text fix for
   `docs/PHASE5_VALIDATION.md` open item 5 can ride along.
2. Update the VPS by the runbook only while the shadow run is FLAT at lot
   precision: the heartbeat says `flat_at_lot: true` and the `--reconcile`
   gate prints `FLAT at lot precision`. Stop `shadow.service`, pull `main`,
   run the suite and `--gate-check`, start the service, confirm a fresh
   heartbeat. After deployment the `demo-shadow-1h` account can enter on the
   next LONG that clears the 0.60 floor (design 5.4): that is the intended
   change in what the account does.
3. Design section 10, check V2 on the shadow run: the first LONG that clears
   the 0.60 floor must carry a `risk_decision` reason other than
   `position_already_open` (or `max_open_positions`), and a candle under the
   old June stop must record no `exit_precision_rejected`. The `--reconcile`
   position line should read `FLAT at lot precision (sub-lot dust 1.2E-10;
   sellable 0)` until that entry.
