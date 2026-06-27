# GitHub Setup for Travel Mode (Operator Runbook)

One-time setup so agents can work via pull requests while you travel, with
`main` protected and nothing able to merge or deploy without you. Do these on a
laptop before you leave; afterward everything is reviewable from your phone.

Repository: `hicham004/ai-trading-model` (adjust if forked).

> Reminder: none of this grants any agent the ability to merge, deploy, or
> advance a phase. Those stay manual, human actions. The CI workflow is
> read-only (`permissions: contents: read`) and cannot push or merge.

## 1. Protect the `main` branch

GitHub → repo → **Settings → Branches → Add branch ruleset** (or "Add rule"
for classic protection) targeting `main`:

- ✅ **Require a pull request before merging.**
  - Require at least **1 approval** (yours).
  - ✅ Dismiss stale approvals on new commits.
- ✅ **Require status checks to pass before merging.**
  - Add the check **`tests + travel-mode safety guard`** (the `test` job in
    `.github/workflows/ci.yml`). It appears in the list after CI runs once —
    open a throwaway PR first if needed.
  - ✅ Require branches to be up to date before merging.
- ✅ **Block force pushes.**
- ✅ **Restrict deletions.**
- ✅ **Do not allow bypassing the above** (or restrict bypass to yourself only).
- ✅ **Require conversation resolution before merging** (so review comments are
  addressed).

Result: no direct pushes to `main`; every change needs a PR + green CI + your
approval.

## 2. Disable direct pushes / auto-merge you don't want

- Settings → **General → Pull Requests**: leave **"Allow auto-merge"
  unchecked.** (We do not want GitHub auto-merging PRs.)
- Confirm no GitHub Action, app, or bot has `contents: write` /
  merge permission beyond what you control.

## 3. Enable Codex Cloud review for the repo

In ChatGPT/Codex (Codex Cloud):

1. Connect your GitHub account and **install the Codex GitHub app on this
   repository** (grant read access to code + pull requests).
2. Enable **Codex Cloud** for `ai-trading-model`.
3. Turn on **automatic PR review** so Codex reviews every new/updated PR.
4. Point Codex at the review guidelines: this repo ships **`AGENTS.md`** and
   **`docs/CODE_REVIEW.md`**; Codex reads `AGENTS.md` automatically. Confirm it
   is picking them up (the review should lead with safety regressions).

If automatic review is unavailable on your plan, you can trigger a review
per-PR from the Codex UI or by commenting the review prompt (see
[the exact prompt](#7-exact-codex-review-prompt)).

## 4. Add the AGENTS.md review guidelines

Already committed at the repo root (`AGENTS.md`) plus `docs/CODE_REVIEW.md`.
No action beyond making sure Codex/Claude are configured to read repo guidance.

## 5. Add Telegram secrets and the travel-mode variable

Create a bot and get your chat id:

1. In Telegram, message **@BotFather** → `/newbot` → copy the **bot token**.
2. Message your new bot once (say "hi"), then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and read
   `result[].message.chat.id` → that is your **chat id**. (Delete the browser
   tab afterward; never paste the token anywhere public.)

Add them as **repository secrets** (Settings → Secrets and variables →
Actions → **Secrets**):

- `TELEGRAM_BOT_TOKEN` = the bot token
- `TELEGRAM_CHAT_ID` = your chat id

Add the travel switch as a **repository variable** (same screen →
**Variables**):

- `TRAVEL_MODE` = `1` while travelling, `0` (or delete it) when back.

> The token and chat id are **secrets** (masked, never printed). `TRAVEL_MODE`
> is a **variable** (non-secret) so you can flip it without a commit. The
> notifier no-ops cleanly if the secrets are absent, so CI never fails for lack
> of Telegram.

**How the secrets stay safe (important):** the test workflow (`ci.yml`) runs
untrusted PR code and is given **no** secrets. Notifications are sent by a
**separate** workflow (`.github/workflows/notify.yml`) triggered by
`workflow_run`, which GitHub runs from the **default branch** and which never
checks out or runs PR code. This is why a malicious PR cannot read your bot
token. See "CI security" in `docs/TRAVEL_MODE.md` and the regression test
`tests/test_ci_workflow_isolation.py`.

> Note: `notify.yml` only becomes active once it is on the **default branch**
> (i.e. after this PR is merged). Until then you review PRs directly and no
> Telegram messages fire — nothing unsafe runs in the meantime.

## 6. (Optional) Claude Code GitHub Action / Routine

Optional and only if you want Claude to open PRs from a queue. See
`docs/CLAUDE_ROUTINE_SETUP.md`. Keep it PR-only; do not configure any loop that
commits directly to `main`.

## 7. Phone workflow (while travelling)

When Telegram pings you (PR opened/updated, CI pass/fail, safety-check blocked):

1. **Open the PR** on the GitHub mobile app (or web).
2. **Read the Codex review** — it leads with safety. Look for any P0/P1
   (demo-only/long-only/cap/secret/auto-merge regressions).
3. **Check CI**: the `tests + travel-mode safety guard` check must be green.
   - If the **safety guard failed**, that is by design: the PR touches a
     safety-sensitive path while travel mode is on. Do not merge on the road
     unless you have fully reviewed the diff yourself.
4. **Ask for changes from your phone** if needed:
   - Comment to Codex: *"Re-review for safety regressions and list P0/P1."*
   - Comment to Claude (if the Claude GitHub app is installed):
     *"@claude address the review comments on a new commit to this branch; do
     not merge."*
5. **Merge only if safe** — manually, with the GitHub "Merge" button, after the
   check is green and the review is clean. Nothing merges on its own.
6. **Never** merge a PR that weakens demo-only/simulated-only/long-only/caps,
   adds a production path, or advances a phase, without doing the full review
   at a desk.

## 8. Exact Codex review prompt

Use this as the per-PR review prompt (or rely on automatic review reading
`AGENTS.md`):

```
Review this PR as a safety-first reviewer per AGENTS.md and docs/CODE_REVIEW.md.

1. Safety regressions FIRST. Flag as P0/P1 anything that:
   - weakens demo-only / x-simulated-trading:1 / hostname allowlist
   - adds a production OKX path or production credentials
   - introduces shorting/margin/leverage/derivatives or breaks long-only/leverage=1
   - loosens any risk cap (notional, open positions, entries/day, daily-loss,
     confidence floor) or weakens the kill switch / arming / account-partition guard
   - adds auto-merge, auto-deploy, direct push to main, or bypass-permission behavior
   - logs or commits any secret/token/key/chat id
   - advances a phase without explicit human approval
2. Then scope/phase, correctness, tests, and docs.
3. Output: a one-line verdict (SAFE TO MERGE / NEEDS WORK / DO NOT MERGE),
   a changed-file summary marking safety-sensitive files, the highest-severity
   finding with path:line, and the test status.
4. State explicitly that merge/deploy/phase-advancement remain my decision.
```
