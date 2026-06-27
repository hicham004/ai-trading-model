# Code Review Checklist

This is the required checklist for any reviewer (human or AI) approving a pull
request in this repository. It operationalizes `AGENTS.md`, `CLAUDE.md`, and
`PROJECT_RULES.md`. A PR is only "review-clean" when every box below is either
checked or explicitly N/A with a reason.

A clean review is a **recommendation**, never an authorization to merge,
deploy, or advance a phase. Those remain human decisions.

## 1. Safety Boundaries Preserved

- [ ] No new real-money / live-trading path. Demo-only is intact.
- [ ] Every authenticated request still sends `x-simulated-trading: 1`.
- [ ] Hostname allowlist unchanged or tightened (no new/production hosts).
- [ ] Long-only, SPOT cash, leverage locked at 1.0 — no shorting, margin,
      leverage, derivatives, or borrowing introduced.
- [ ] No withdrawals, deposits, transfers, funding, or account-mode mutation.
- [ ] No generic/arbitrary-endpoint method exposed to callers; no new mutating
      HTTP route.
- [ ] No LLM/AI order authority: no AI code path can place, approve, modify,
      or cancel an order.
- [ ] Fail-closed behavior preserved (ambiguous reconcile, stale feeds, lost
      locks, unknown order outcomes still block new entries).

## 2. Demo / Simulated Only Preserved

- [ ] `LIVE_TRADING_ENABLED` stays the hard lock (default `False`); nothing
      bypasses it.
- [ ] No production OKX hostname, base URL, or WebSocket URL added.
- [ ] `x-simulated-trading: 0` remains unrepresentable in code.
- [ ] Active account stays an explicit demo account; account-partition guard
      still fails closed on shared key fingerprints.

## 3. No Production OKX Path

- [ ] No production credentials, endpoints, or environment introduced or
      referenced (except as explicitly forbidden documentation).
- [ ] No code path can be configured into production mode by env, flag, or
      config file.

## 4. No Credential Leaks

- [ ] No secret, API key, passphrase, bot token, or chat id is printed,
      logged, committed, or placed in tests/fixtures.
- [ ] Secret-redaction filters remain installed where credentials are loaded.
- [ ] `.env.example` contains documentation only — no real values.

## 5. No Safety-Cap Weakening

- [ ] Risk caps only tighten, never loosen: max order notional, max open
      positions, max entries/day, daily-loss lockout, arm TTL, restart budget.
- [ ] The 0.60 confidence floor and strategy logic are untouched (changes here
      are scope changes needing explicit owner approval).
- [ ] `config/shadow_period.json` loader still fails closed if a value would
      loosen the reviewed demo settings.

## 6. No Hidden Auto-Merge / Auto-Deploy Behavior

- [ ] No auto-merge action, auto-merge label automation, or `gh pr merge`
      automation added.
- [ ] No auto-deploy / release / publish step added.
- [ ] No direct push to `main` from CI or scripts.
- [ ] No `--dangerously-skip-permissions` / bypass-permission / unattended
      privileged automation added.
- [ ] `main` stays protected; merges require human action.
- [ ] `scripts/check_travel_mode_safety.py` and its CI step are present and not
      weakened.
- [ ] **CI secret isolation intact:** no secret (`${{ secrets.* }}`) is exposed
      to a job that checks out/runs PR code; notifications stay in the
      `workflow_run` workflow that does not run PR code; no untrusted
      `${{ github.event.* }}` value is interpolated into a `run:` shell body
      (`tests/test_ci_workflow_isolation.py` must pass).

## 7. Tests Added / Updated

- [ ] New behavior has tests; changed behavior has updated tests.
- [ ] Adverse / failure / fail-closed cases are tested where relevant.
- [ ] No test requires real OKX or private credentials; all external access is
      mocked/faked and offline.

## 8. Tests Run

- [ ] Targeted tests for the changed area were run and pass.
- [ ] Full `pytest` was run if feasible; if not, the reason is stated.
- [ ] CI is green (including the travel-mode safety check).

## 9. Changed Files Summarized

- [ ] The PR description (or review) lists every changed file with a one-line
      what/why and flags which are safety-sensitive.

## 10. Scope / Phase

- [ ] The change stays within the currently authorized phase.
- [ ] No document or code declares a phase complete or authorizes a new phase.
- [ ] If the change touches phase-gate docs (`CLAUDE.md`, `PROJECT_RULES.md`,
      `docs/PHASES.md`), it is flagged for explicit operator approval.

## Reviewer Sign-off

- **Verdict:** `SAFE TO MERGE` / `NEEDS WORK` /
  `DO NOT MERGE (operator decision required)`.
- **Highest-severity finding:** (P0–P3, with `path:line`).
- **Tests run:** (commands + result).
- **Safety-sensitive files touched:** (list, or "none").
- **Reminder:** merge, deploy, and phase advancement are human decisions; this
  review does not authorize them.
