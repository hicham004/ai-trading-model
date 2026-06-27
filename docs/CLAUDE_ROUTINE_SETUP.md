# Optional: Claude Routine / GitHub Action (PR-only)

This is **optional** and must stay strictly PR-based. It explains how to let
Claude pick the next task from a queue and open a **pull request** — never
commit to `main`, never merge, never deploy. If you do not want any autonomous
task pickup, skip this file entirely; travel mode works without it.

> Hard boundary: any automation set up here may only create a branch and open a
> PR. It must not merge, deploy, advance a phase, or modify safety-core trading
> files. `main` stays protected (see `docs/GITHUB_SETUP_FOR_TRAVEL.md`). The CI
> workflow is read-only and cannot merge.

## The task queue

Keep a simple, human-authored backlog the agent reads from. A plain Markdown
file is enough, e.g. `docs/TASK_QUEUE.md`:

```markdown
# Task Queue (operator-authored; in-scope, non-safety-core tasks only)

- [ ] Add a unit test for report rollover at UTC midnight
- [ ] Improve the daily-report wording for disarmed days
- [ ] Document the heartbeat file fields in docs/
```

Rules for the queue:

- Only the operator adds tasks.
- Only **in-scope, non-safety-core** tasks belong here. Anything touching the
  paths in `scripts/check_travel_mode_safety.py` should be left for desk work.
- One task → one branch → one PR.

## Option A — Claude Code GitHub Action (recommended, explicit)

Install the **Claude GitHub app** and add a workflow that runs Claude **only
when you ask**, on a branch, opening a PR:

- Trigger on `issue_comment` / `pull_request` mention (e.g. you comment
  `@claude take the next queue item`), or `workflow_dispatch` you start
  manually. Do **not** trigger on a timer that pushes to `main`.
- Give the job the minimum permissions it needs to open a PR
  (`contents: write` on a feature branch + `pull-requests: write`) and **no**
  merge step. Never add `gh pr merge`, auto-merge labels, or deploy steps.
- The action checks out a new branch, implements one queue item, runs
  `pytest` and `scripts/check_travel_mode_safety.py`, and opens a PR. Codex
  reviews it; you merge it manually if safe.

Keep the prompt constrained, e.g.:

```
Take the first unchecked item in docs/TASK_QUEUE.md. Work ONLY on a new feature
branch. Stay within the currently authorized phase. Do NOT modify any path in
scripts/check_travel_mode_safety.py's safety-sensitive list. Run pytest and the
travel-mode guard. Open a PR with a changed-file summary. Do NOT merge, deploy,
or advance a phase. If the task would touch safety-core files or is ambiguous,
stop and leave a comment asking the operator.
```

## Option B — Claude Routine (scheduled, still PR-only)

If you use a scheduled Claude Routine to pick up queue items, it must obey the
same constraints:

- Output is always a **branch + PR**, never a commit to `main`.
- No merge, no deploy, no phase advancement.
- Re-state the safety boundary in the routine prompt (copy the prompt above).
- Prefer a low cadence (e.g. once/day) so review stays manageable on the road.

## What NOT to build

- ❌ A loop that commits directly to `main`.
- ❌ Any job with merge or deploy authority.
- ❌ Any automation that edits safety-core trading files unattended.
- ❌ Any pickup of tasks that weaken demo-only/long-only/caps or advance a
  phase — those require you, at a desk.

## Verification before you rely on it

1. Open a test queue item and confirm the automation produces a **PR**, not a
   push to `main`.
2. Confirm CI runs on that PR (tests + travel-mode guard) and Telegram pings
   you.
3. Confirm you (and only you) can merge, and only after the checks are green.
