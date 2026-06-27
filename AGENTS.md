# AGENTS.md — Review Guidelines for Codex / Claude / Any AI Reviewer

This file tells every AI reviewer (Codex Cloud, Claude, ChatGPT, or any other
automated reviewer) how to review a pull request in this repository. It is the
review companion to `CLAUDE.md` and `PROJECT_RULES.md`, which remain binding.
If anything here appears to conflict with `CLAUDE.md` or `PROJECT_RULES.md`,
those two files win and you must stop and flag the conflict.

This repository builds an AI-assisted **OKX DEMO (simulated) only** trading
system, advanced in human-approved phases. It is NOT authorized to place real
trades or touch real funds. Reviews exist to keep it that way.

## Review Order: Safety First, Always

Review every PR in this order. Do not move to a later step until the earlier
one is clear.

1. **Safety regressions** (highest priority — see below).
2. **Scope / phase boundaries** — does this PR stay inside the currently
   authorized phase? (Phases 1–5 accepted; Phase 6a authorized as the
   mechanical shadow period only; Phase 6b and later are NOT authorized.)
3. **Correctness** — does the code do what it claims, with adverse cases
   handled and fail-closed behavior preserved?
4. **Tests** — are there new/updated tests, and do they cover the change and
   its failure modes?
5. **Documentation** — does the doc match the actual behavior?

## Safety-Sensitive Surfaces (treat changes here as high-risk)

Treat any change touching the following as safety-sensitive. Read the full
diff for these, not just the summary:

- **Trading execution / order placement** — `app/execution/` (driver,
  lifecycle, runtime, reconcile, store, account guard, precision, ids,
  identity).
- **Risk manager** — `app/risk/` (the final veto).
- **OKX private API / authenticated access** — `app/exchange/`
  (credentials, auth signing, demo REST, demo private WebSocket, endpoints),
  `app/okx/`.
- **Phase gates / authorization docs** — `CLAUDE.md`, `PROJECT_RULES.md`,
  `docs/PHASES.md`, `docs/AGENT_WORKFLOW.md`, `docs/AGENT_HANDOFF.md`.
- **Config caps / trading caps** — `config/` (e.g. `shadow_period.json`),
  cap-related settings in `app/config.py`, the `DEMO_*` / `PAPER_*` env
  contract.
- **Supervisor / restart logic** — `app/shadow/` (supervisor, restart budget,
  arming, policy, journal, report).
- **Kill switch logic** — kill-switch and arming code paths in
  `app/execution/` and `scripts/run_demo_trading.py`.
- **Credentials / secret / env handling** — `app/exchange/credentials.py`,
  secret-redaction filters, `.env`, `.env.example`.
- **Operator CLIs** — `scripts/run_demo_trading.py`,
  `scripts/run_shadow_period.py` (they can arm, kill, or place demo orders).
- **CI / automation** — `.github/`, `scripts/check_travel_mode_safety.py`
  (the travel-mode guard itself).

The authoritative, machine-checkable list lives in
`scripts/check_travel_mode_safety.py`. When in doubt, classify a path as
safety-sensitive.

## P0 / P1 — Block the PR

Flag any of the following as **P0 (must fix, blocks merge)** or **P1 (must fix
before merge)** and recommend the operator do NOT merge:

- **Weakening demo-only / simulated-only.** Anything that could send
  `x-simulated-trading: 0`, hit a production OKX host, add production
  credentials, or otherwise create a real-money path. This is P0.
- **Weakening long-only / spot / leverage=1.** Any shorting, margin,
  leverage, derivatives, or borrowing path. P0.
- **Weakening risk caps or limits.** Loosening max notional, max open
  positions, max entries/day, daily-loss lockout, confidence floor (0.60),
  or any cap so the system risks more. Caps may only tighten. P0/P1.
- **Weakening the kill switch, arming TTL, account-partition guard, or
  fail-closed reconciliation.** P0/P1.
- **Auto-merge, auto-deploy, direct push to `main`, or
  bypass-permission/`--dangerously-skip-permissions`-style behavior** added in
  code, CI, or automation config. P0.
- **Secret logging or committed tokens/keys.** Any credential, API key, bot
  token, or chat id printed, logged, or committed (including in tests or
  fixtures). P0.
- **Phase advancement without explicit human approval** — code or docs that
  declare a new phase complete/authorized, or begin Phase 6b+ work. P1
  (stop and require operator approval).
- **Removing or disabling `scripts/check_travel_mode_safety.py` or its CI
  step.** P0.

## P2 / P3 — Note, Don't Block

- Correctness bugs that are not safety regressions, missing edge-case tests,
  unclear naming, doc drift, minor inefficiency. Note them; they do not by
  themselves block a safety-clean PR, but the operator decides.

## Every Review Must Include

- A one-line **verdict**: `SAFE TO MERGE`, `NEEDS WORK`, or
  `DO NOT MERGE (operator decision required)`.
- A **changed-file summary** (path + what changed + whether it is
  safety-sensitive).
- **Test status**: were tests added/updated, and what was run
  (`pytest` targeted and/or full). If tests were not run, say so.
- The **highest-severity finding** and its location (`path:line`).
- An explicit statement that **merge/deploy/phase-advance remain a human
  decision** — your review is a recommendation, never an authorization.

## Hard Rules for Reviewers (and for any agent acting on a review)

- You may recommend; you may not merge, deploy, or advance a phase.
- Never request, paste, or echo real credentials or secrets in a review.
- If a test requires real OKX or private credentials, that is itself a P0
  finding — tests must run offline against mocks/fakes.
- If you cannot tell whether a change is safe, treat it as unsafe and say so.
- When the change is safety-sensitive and travel mode is on, expect the
  travel-mode CI guard to fail by design; do not recommend "just disable the
  guard."

See `docs/CODE_REVIEW.md` for the full reviewer checklist and
`docs/TRAVEL_MODE.md` for how this fits the travel workflow.
