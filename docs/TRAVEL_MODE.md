# AgentOps Travel Mode

Travel mode lets work continue while the operator is away from the desk —
**without unsafe autonomy**. It is a PR-based workflow, not a direct-to-main
workflow. Agents propose; the human disposes.

## The One Rule

> Agents may build, test, review, report, and notify. Agents may **not**
> merge, deploy, advance a phase, or weaken any trading/risk/safety rule.

Everything below enforces that rule.

## What Agents MAY Do in Travel Mode

- Create **feature branches** (never commit to `main`).
- Implement **isolated, in-scope** changes.
- Open **pull requests** against `main`.
- Run **tests** (offline, mocked — never against real OKX or private keys).
- Write **reports** and changed-file summaries.
- **Notify** the operator (Telegram) about CI status, new/updated PRs, safety
  findings, and daily reports.

## What Agents MUST NOT Do in Travel Mode

- **No auto-merge to `main`.** Ever. A green CI is not a merge authorization.
- **No deploy / release / publish.**
- **No automatic phase advancement.** Phase 6b and later need explicit human
  approval (see `CLAUDE.md`).
- **No weakening of trading, risk, or safety rules** (demo-only, simulated-only,
  long-only, leverage=1, caps, kill switch, fail-closed reconcile).
- **No real OKX / production mode / `x-simulated-trading: 0` /
  withdrawal-capable keys / any non-simulated environment.**
- **No autonomous merge of safety-sensitive work.** When travel mode is on and
  a PR touches a safety-sensitive path, CI fails by design and the operator
  must intervene.
- **If in doubt, stop and request operator approval.**

## The Workflow

```text
Claude (builder)            Codex (reviewer)           Operator (phone)
-----------------           ----------------           ----------------
feature branch        -->   reviews every PR     -->   reads PR + review
implements in scope         safety-first (AGENTS.md)   on GitHub mobile/web
opens PR              -->   CI runs:                    merges ONLY if safe
                            - pytest                     (manual, human action)
                            - travel-mode guard
                            - test summary
Telegram notify       -->   Telegram notify       -->   Telegram receives
(CI status, via             (review ready)              CI status + links
 notify.yml)
```

1. **Claude builds on a feature branch only.** Branch naming is free-form
   (e.g. `agentops-...`, `fix-...`); `main` is never a work branch.
2. **Codex reviews every PR** using `AGENTS.md` + `docs/CODE_REVIEW.md`,
   safety regressions first.
3. **CI must pass** (`.github/workflows/ci.yml`): tests, the travel-mode safety
   guard, and a saved test summary. This workflow holds **no secrets**.
4. **Telegram notifies the operator** on CI pass / fail / safety-block, sent by
   a **separate** `workflow_run` workflow (`.github/workflows/notify.yml`) that
   never runs PR code (see "CI security" below).
5. **The operator reviews from their phone** using the GitHub mobile app/web,
   the Codex review, and (optionally) Claude mobile/web — then merges **only if
   safe**, manually.
6. **`main` stays protected.** Branch protection requires a PR, requires CI
   status checks, and disables direct pushes (see
   `docs/GITHUB_SETUP_FOR_TRAVEL.md`).
7. **No autonomous phase advancement** and **no autonomous merge of
   safety-sensitive work.**

## CI Security (secret isolation)

GitHub Actions has a well-known footgun: any secret made available to a job
that **checks out and runs PR-controlled code** (e.g. `pip install`, `pytest`,
repo scripts) can be exfiltrated by a malicious PR, and any
`${{ github.event.pull_request.title }}`-style value interpolated into a `run:`
shell body is a command-injection vector. This repo avoids both:

- **`ci.yml` runs untrusted PR code and holds NO secrets.** There is no
  `${{ secrets.* }}` anywhere in it. The only dynamic values reaching a shell
  (the diff SHAs) are passed via `env:` and referenced as quoted variables
  (`"$BASE_SHA"`), never inlined.
- **`notify.yml` holds the Telegram secrets and never runs PR code.** It is
  triggered by `workflow_run` (after CI completes), which always uses the
  workflow file and checked-out code from the **default branch** (trusted). It
  does not check out the PR head, does not install the PR's dependencies, and
  installs only a single pinned package to send the message. The pass/fail
  classification reads the CI summary artifact via `grep -q` against a file —
  file contents are never executed or interpolated into a shell.
- **A regression test (`tests/test_ci_workflow_isolation.py`) enforces these
  invariants** so the unsafe pattern cannot creep back in.

Consequence: `notify.yml` only takes effect once it exists on the default
branch (i.e. after this work is merged). Until then, PRs are reviewed directly;
no notifications fire, and nothing unsafe runs.

## Enabling / Disabling Travel Mode

Travel mode is controlled by a single switch, the `TRAVEL_MODE` value, read by
`scripts/check_travel_mode_safety.py` in CI:

- **In GitHub Actions:** set a repository **variable** `TRAVEL_MODE` to `1`
  (on) or `0`/unset (off). Toggling a repo variable needs no commit and no
  code change. See `docs/GITHUB_SETUP_FOR_TRAVEL.md`.
- **Locally / for testing:** set the `TRAVEL_MODE` environment variable.

When `TRAVEL_MODE` is **on**:

- The CI safety guard **fails** any PR that modifies a safety-sensitive path.
  This does not delete the PR or the work — it blocks the *autonomous* path and
  forces a human decision. The operator can still review and merge manually
  (and/or turn travel mode off) after looking at the diff.

When `TRAVEL_MODE` is **off**:

- The guard still runs and **reports** which safety-sensitive files a PR
  touches (informational), but does not fail the build for touching them.

The guard is intentionally **conservative**: when unsure whether a path is
safety-sensitive, it classifies it as safety-sensitive. The authoritative list
and its rationale live at the top of `scripts/check_travel_mode_safety.py`.

## What Counts as Safety-Sensitive

Summarized here; the machine-checkable source of truth is the script.

- OKX execution / private API / order placement — `app/execution/`,
  `app/exchange/`, `app/okx/`.
- Risk manager — `app/risk/`.
- Supervisor / restart / arming logic — `app/shadow/`.
- Phase authorization docs — `CLAUDE.md`, `PROJECT_RULES.md`,
  `docs/PHASES.md`, `docs/AGENT_WORKFLOW.md`, `docs/AGENT_HANDOFF.md`.
- Production/demo mode config & trading caps — `app/config.py`, `config/`.
- Secret / env handling — `.env`, `.env.example`, credentials modules.
- Kill switch & operator CLIs — `scripts/run_demo_trading.py`,
  `scripts/run_shadow_period.py`.
- CI / automation itself — `.github/`,
  `scripts/check_travel_mode_safety.py`.

## Boundaries This Mode Does NOT Cross

Travel mode adds **no** new trading capability and changes **no** safety-core
trading file. It is pure process tooling: branch discipline, a CI guard,
notifications, and documentation. It cannot place an order, cannot arm a run,
and cannot reach a real or production environment.
