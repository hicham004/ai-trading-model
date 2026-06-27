#!/usr/bin/env python3
"""Travel-mode safety guard for CI.

PURPOSE
-------
Part of "AgentOps travel mode" (see ``docs/TRAVEL_MODE.md``). While the
operator is travelling, agents may open pull requests but must NOT autonomously
merge changes to safety-sensitive code. This script is the CI gate that
enforces that: when travel mode is ON and a pull request modifies any
safety-sensitive path, it exits non-zero and fails the build, forcing a human
decision. It NEVER merges, deploys, or changes any trading behavior — it only
inspects the list of changed files.

When travel mode is OFF, the script still runs and *reports* which
safety-sensitive files a PR touches (informational), but does not fail the
build for touching them.

It places no orders, needs no credentials, and touches no exchange. It is pure,
offline file-path classification plus an optional ``git diff``.

THE SAFETY-SENSITIVE LIST (conservative by design)
--------------------------------------------------
Each rule below is ``(pattern, reason)``. A pattern ending in ``/`` matches any
path under that directory; otherwise it is an exact path or an ``fnmatch``
glob. The list is intentionally broad: blocking a PR here does NOT delete the
work, it only routes the change through the human (the operator can review and
merge manually, or turn travel mode off). When unsure, a path is classified as
safety-sensitive. Keep this list and its rationale in sync with ``AGENTS.md``,
``docs/CODE_REVIEW.md``, and ``docs/TRAVEL_MODE.md``.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys

# (pattern, human-readable reason). Order is informational only.
SAFETY_SENSITIVE_RULES: list[tuple[str, str]] = [
    # --- Order placement / execution / kill switch / reconcile ---
    ("app/execution/", "trading execution, order placement, kill switch, arming, reconcile"),
    # --- Authenticated OKX private API + credentials/secret handling ---
    ("app/exchange/", "OKX private API, auth signing, credentials, secret handling"),
    ("app/okx/", "OKX client"),
    # --- Risk manager: the deterministic final veto ---
    ("app/risk/", "risk manager (final veto on every order)"),
    # --- Supervisor / restart budget / arming / shadow caps loader ---
    ("app/shadow/", "shadow supervisor, restart logic, arming, caps loader, policy"),
    # --- Live feeds drive decisions; stale-feed fail-closed lives here ---
    ("app/live/", "live market-data feed runtime and persistence"),
    # --- Broker abstraction is execution-adjacent ---
    ("app/broker/", "broker abstraction (execution-adjacent)"),
    # --- Strategy logic and the 0.60 confidence floor are scope-gated ---
    ("app/strategy/", "strategy logic / confidence floor (scope change, owner-gated)"),
    # --- Production/demo mode config, env handling, the hard live lock ---
    ("app/config.py", "production/demo mode config, env handling, LIVE_TRADING lock"),
    # --- Persisted trading caps (e.g. shadow_period.json) ---
    ("config/", "persisted trading caps / risk limits"),
    # --- Operator CLIs that can arm, kill, or place demo orders ---
    ("scripts/run_demo_trading.py", "operator CLI: arm/kill/place demo orders"),
    ("scripts/run_shadow_period.py", "operator CLI: shadow supervisor launcher"),
    ("scripts/run_paper_trading.py", "paper-trading runner exercising risk vetoes"),
    ("scripts/run_live_market_data.py", "live market-data runner"),
    # --- Operator notification path (handles the Telegram bot token) ---
    ("app/notify/", "operator notification path / secret (token) handling"),
    ("scripts/notify_telegram.py", "notification CLI / secret (token) handling"),
    # --- The guard itself must not be quietly weakened ---
    ("scripts/check_travel_mode_safety.py", "the travel-mode safety guard itself"),
    # --- CI / automation could add auto-merge, auto-deploy, or bypass ---
    (".github/", "CI / automation (could add auto-merge, deploy, or bypass)"),
    # --- Secret / environment contract ---
    (".env", "environment / secret contract"),
    (".env.example", "environment / secret documentation"),
    # --- Phase authorization & safety-governance documents ---
    ("CLAUDE.md", "phase authorization / standing safety contract"),
    ("PROJECT_RULES.md", "project rules / phase approval"),
    ("AGENTS.md", "AI review guidelines (governance)"),
    ("docs/PHASES.md", "phase gate definitions"),
    ("docs/CODE_REVIEW.md", "review checklist (governance)"),
    ("docs/AGENT_WORKFLOW.md", "agent authority / review loop"),
    ("docs/AGENT_HANDOFF.md", "agent handoff / safety rules"),
    ("docs/TRAVEL_MODE.md", "travel-mode workflow / governance doc"),
    ("docs/GITHUB_SETUP_FOR_TRAVEL.md", "travel-mode setup runbook (governance)"),
    ("docs/CLAUDE_ROUTINE_SETUP.md", "automation setup doc (governance)"),
    # --- Dependency surface: a swap can introduce a network/bypass path ---
    ("requirements.txt", "dependency surface (supply chain)"),
    ("pyproject.toml", "build / dependency surface (supply chain)"),
]

_TRUTHY = {"1", "true", "yes", "on"}


def is_travel_mode_enabled(env: dict[str, str] | None = None) -> bool:
    """Return True when travel mode is ON (``TRAVEL_MODE`` is truthy)."""
    env = os.environ if env is None else env
    return env.get("TRAVEL_MODE", "").strip().lower() in _TRUTHY


def classify(path: str) -> str | None:
    """Return the reason a path is safety-sensitive, or ``None`` if it is not."""
    # Normalize to forward slashes so the check is OS-independent. Strip only a
    # leading "./" prefix (NOT arbitrary leading dots — that would mangle
    # ".github/" and ".env").
    norm = path.strip().replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    if not norm:
        return None
    for pattern, reason in SAFETY_SENSITIVE_RULES:
        if pattern.endswith("/"):
            if norm == pattern.rstrip("/") or norm.startswith(pattern):
                return reason
        elif norm == pattern or fnmatch.fnmatch(norm, pattern):
            return reason
    return None


def find_safety_sensitive(files: list[str]) -> list[tuple[str, str]]:
    """Return ``(path, reason)`` for every safety-sensitive file in ``files``."""
    hits: list[tuple[str, str]] = []
    for path in files:
        reason = classify(path)
        if reason is not None:
            hits.append((path, reason))
    return hits


def changed_files_from_git(base: str | None, head: str) -> list[str]:
    """Return files changed between ``base`` and ``head`` using ``git diff``.

    Uses a three-dot diff (changes on ``head`` since the merge-base) when a base
    is given. Raises ``RuntimeError`` on git failure so CI fails loud rather
    than silently passing.
    """
    if base:
        spec = [f"{base}...{head}"]
    else:
        spec = [head]
    cmd = ["git", "diff", "--name-only", "--no-color", *spec]
    try:
        out = subprocess.run(
            cmd, check=True, capture_output=True, text=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeError(f"git diff failed ({' '.join(cmd)}): {detail.strip()}") from exc
    return [line.strip() for line in out.splitlines() if line.strip()]


def _resolve_base_head(args: argparse.Namespace, env: dict[str, str]) -> tuple[str | None, str]:
    """Pick base/head refs from CLI args or GitHub Actions environment."""
    base = args.base or env.get("BASE_REF") or env.get("GITHUB_BASE_SHA")
    head = args.head or env.get("HEAD_REF") or env.get("GITHUB_HEAD_SHA") or "HEAD"
    if not base:
        # Fall back to the usual default branch ref for a local run.
        for candidate in ("origin/main", "main"):
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", "--quiet", candidate],
                    check=True, capture_output=True, text=True,
                )
                base = candidate
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
    return base, head


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Travel-mode safety guard for CI (offline).")
    p.add_argument("--files", nargs="*", default=None,
                   help="Explicit changed-file list (bypasses git). Used by tests/CI.")
    p.add_argument("--base", default=None, help="Base git ref/sha to diff from.")
    p.add_argument("--head", default=None, help="Head git ref/sha to diff to (default HEAD).")
    p.add_argument("--travel-mode", choices=["auto", "on", "off"], default="auto",
                   help="Override travel-mode state. 'auto' reads the TRAVEL_MODE env var.")
    return p.parse_args(argv)


def run(argv=None, *, env: dict[str, str] | None = None) -> int:
    args = parse_args(argv)
    env = dict(os.environ) if env is None else env

    if args.travel_mode == "on":
        travel_on = True
    elif args.travel_mode == "off":
        travel_on = False
    else:
        travel_on = is_travel_mode_enabled(env)

    if args.files is not None:
        files = [f for f in args.files if f.strip()]
    else:
        base, head = _resolve_base_head(args, env)
        try:
            files = changed_files_from_git(base, head)
        except RuntimeError as exc:
            print(f"[travel-guard] ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"[travel-guard] diff base={base or '(none)'} head={head}: "
              f"{len(files)} changed file(s)")

    hits = find_safety_sensitive(files)
    state = "ON" if travel_on else "OFF"
    print(f"[travel-guard] travel mode: {state}")

    if not hits:
        print("[travel-guard] no safety-sensitive files changed. OK.")
        return 0

    print(f"[travel-guard] {len(hits)} safety-sensitive file(s) changed:")
    for path, reason in hits:
        print(f"  - {path}  ->  {reason}")

    if travel_on:
        print("[travel-guard] FAIL: travel mode is ON and this PR modifies "
              "safety-sensitive paths.")
        print("[travel-guard] This change must NOT be merged autonomously. "
              "An operator must review and merge manually (or turn travel "
              "mode off after review). See docs/TRAVEL_MODE.md.")
        return 1

    print("[travel-guard] travel mode is OFF: reporting only, not failing the "
          "build. These paths still warrant careful human review.")
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
