"""Regression tests for CI secret isolation and injection safety.

These enforce the security invariant from the Codex review (P1): the workflow
that runs UNTRUSTED PR code must hold NO secrets, and notifications (which need
secrets) must run in a separate `workflow_run` workflow that never executes PR
code or interpolates untrusted metadata into a shell command.

They are deliberately text-based (no YAML dependency) so they run anywhere the
suite runs and fail loudly if someone reintroduces the unsafe pattern.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
NOTIFY = ROOT / ".github" / "workflows" / "notify.yml"


def _read(p: Path) -> str:
    assert p.exists(), f"missing workflow: {p}"
    return p.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Return the YAML with comments removed, for keyword scanning.

    A ``#`` starts a comment when it is at line start or preceded by
    whitespace (YAML rule), so ``echo "## CI summary"`` is preserved while
    ``key: value  # note`` and full-line ``# note`` are dropped.
    """
    out = []
    for line in text.splitlines():
        cut = None
        for i, ch in enumerate(line):
            if ch == "#" and (i == 0 or line[i - 1].isspace()):
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


# --- ci.yml: runs untrusted PR code, therefore must hold NO secrets -------

def test_ci_workflow_references_no_secrets():
    text = _read(CI)
    # The precise unsafe pattern is a GitHub secret expression; comments that
    # merely mention the word "secrets" are fine.
    assert "${{ secrets." not in text and "${{secrets." not in text, (
        "ci.yml runs untrusted PR code and must not reference any secret. "
        "Move secret-using steps to notify.yml (workflow_run)."
    )
    assert "TELEGRAM" not in _strip_comments(text), (
        "ci.yml must not handle Telegram credentials."
    )


def test_ci_workflow_is_read_only():
    text = _read(CI)
    assert "permissions:" in text and "contents: read" in text
    # No write permissions that could enable push/merge/deploy.
    assert "contents: write" not in text
    assert "pull-requests: write" not in text


def test_ci_workflow_has_no_inline_untrusted_metadata_in_run():
    """No `${{ github.event ... }}` interpolation inside a `run:` shell body.

    Untrusted PR metadata (titles, branch/ref names) must be passed via env and
    referenced as quoted shell variables, never substituted into the script.
    """
    text = _read(CI)
    # These are the classic injection sources; none may appear at all in ci.yml
    # (we pass SHAs through env: instead).
    for needle in (
        "github.event.pull_request.title",
        "github.event.pull_request.number",
        "github.head_ref",
        "github.ref_name",
    ):
        assert needle not in text, f"ci.yml must not inline `{needle}`"


def test_ci_workflow_does_not_merge_or_deploy():
    # Scan code only (comments legitimately describe what the workflow avoids).
    code = _strip_comments(_read(CI)).lower()
    for forbidden in ("pr merge", "auto-merge", "automerge", "deploy", "release "):
        assert forbidden not in code, f"ci.yml must not {forbidden!r}"


# --- notify.yml: holds secrets, must never run untrusted PR code ----------

def test_notify_workflow_is_triggered_only_by_workflow_run():
    text = _read(NOTIFY)
    assert "workflow_run:" in text, "notify.yml must use the workflow_run trigger"
    # It must not be triggered directly by pull_request (which would run with
    # the PR's workflow file / context).
    assert not re.search(r"^\s*pull_request:", text, re.MULTILINE), (
        "notify.yml must not be triggered by pull_request"
    )
    assert "pull_request_target" not in text


def test_notify_workflow_does_not_checkout_pr_head():
    text = _read(NOTIFY)
    # Never check out the PR/untrusted ref. The only safe checkout under
    # workflow_run is the implicit default branch (no `ref:`).
    for unsafe in (
        "head_branch",
        "head_sha",
        "head.sha",
        "pull_request.head",
    ):
        # head_branch/head_sha may appear in `env:` metadata, but never as a
        # checkout ref. Assert they are not used as a `ref:` value.
        assert f"ref: ${{{{ github.event.workflow_run.{unsafe}" not in text
        assert f"ref: ${{{{ github.event.pull_request" not in text


def test_notify_workflow_does_not_run_pr_code():
    code = _strip_comments(_read(NOTIFY)).lower()
    # Must not install the PR's full dependency set or run its tests/guards.
    assert "requirements.txt" not in code, "notify.yml must not install PR deps"
    assert "pytest" not in code, "notify.yml must not run PR tests"
    assert "check_travel_mode_safety" not in code, "notify.yml must not run PR guard"
    assert "pip install -e" not in code, "notify.yml must not editable-install PR code"


def test_notify_workflow_has_no_inline_untrusted_metadata_in_run():
    """Untrusted metadata must reach the shell only via env vars, not `${{ }}`.

    We check the `run:` blocks contain no `${{ github.event` interpolation.
    """
    text = _read(NOTIFY)
    # Find run: ... blocks (indented script bodies) and ensure no GitHub
    # expression interpolation of event data appears inside them.
    run_blocks = re.findall(r"run:\s*\|(.*?)(?=\n\S|\Z)", text, re.DOTALL)
    assert run_blocks, "expected at least one run: block in notify.yml"
    for block in run_blocks:
        assert "${{ github.event" not in block, (
            "notify.yml run blocks must not interpolate github.event data; "
            "pass it via env and use quoted shell variables"
        )


def test_notify_workflow_is_read_only():
    text = _read(NOTIFY)
    assert "contents: read" in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
