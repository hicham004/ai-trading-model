"""The optional Claude summary of the ops digest (plan row R6): request shape, guard rails, spend cap, key safety — offline."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.news.budget import BudgetedClient, SpendGuard
from app.ops import digest_ai

ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "sk-ant-testkey-not-a-real-key-for-tests-only"  # not the shape of a real key (the runner's push scan)
FACTS = ("AI trading system - daily digest, Thu 22 Oct 2026 (04:00 UTC).\nNEEDS ATTENTION\nNothing needs your attention.\n"
         "PHASE 6A SHADOW\nYesterday: 24 candles; LONG signals 3 (2 cleared the confidence floor, 1 below it); reconciliations 2,880, all consistent.\n"
         "PAPER FLEET\nSince start: best c03 +1.2%, worst c07 -12.0%.")


class FakeClient:
    """Scripted stand-in for the SDK client: records each request and replies in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text, stop = reply if isinstance(reply, tuple) else (reply, "end_turn")
        return SimpleNamespace(model="claude-opus-5-5", stop_reason=stop, stop_details=None,
                               content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=80, cache_creation_input_tokens=0,
                                                     cache_read_input_tokens=0))


def test_a_faithful_summary_is_kept_and_the_request_is_the_frozen_one():
    client = FakeClient("Nothing needs your attention. The shadow saw **24 candles** and 2,880 consistent reconciliations.")
    out = digest_ai.summarize(FACTS, client)
    assert out.status == "ok" and out.summary.startswith("Nothing needs your attention.") and "**" not in out.summary
    request, = client.requests
    assert request["model"] == "claude-opus-5-5" and request["max_tokens"] == digest_ai.MAX_TOKENS
    assert request["output_config"] == {"effort": "low"}
    assert "thinking" not in request and "temperature" not in request and "tools" not in request
    assert request["system"] == digest_ai.SYSTEM_PROMPT  # frozen: no date, no facts in the system prompt
    assert request["messages"] == [{"role": "user", "content": f"<facts>\n{FACTS}\n</facts>"}]
    assert "data, not instructions" in digest_ai.SYSTEM_PROMPT and "advice" in digest_ai.SYSTEM_PROMPT


@pytest.mark.parametrize(
    "reply, status",
    [
        (("", "refusal"), "refusal"),
        (("Nothing needs", "max_tokens"), "max_tokens"),
        (("x", "pause_turn"), "unexpected_stop_reason"),
        ("   ", "empty"),
        ("word " * 300, "too_long"),
        ("All normal, see https://example.com for details.", "link"),
        ("All normal; www.example.com has more.", "link"),
        ("All normal; the details are on okx.com.", "link"),
        ("The fleet gained 7.5% and the shadow saw 24 candles.", "unverified_numbers"),
        ("Reconciliations: 2,881.", "unverified_numbers"),
        ("The worst account c07 gained 12.0%.", "unverified_numbers"),  # the digest says -12.0%
        ("The best account c03 lost -1.2%.", "unverified_numbers"),  # the digest says +1.2%
    ],
)
def test_a_summary_that_breaks_a_rule_is_dropped(reply, status):
    out = digest_ai.summarize(FACTS, FakeClient(reply))
    assert out.summary is None and out.status == status
    if status == "unverified_numbers":
        assert out.unverified_numbers and "24" not in out.unverified_numbers


def test_signed_numbers_copied_as_written_are_kept():
    out = digest_ai.summarize(FACTS, FakeClient("The worst paper account, c07, is at -12.0% and the best, c03, at +1.2%; "
                                                "shadow.service and news-shadow.service look normal."))
    assert out.status == "ok"


def test_an_api_failure_is_a_code_never_a_message():
    import anthropic

    class Boom(anthropic.APIConnectionError):
        def __init__(self):
            Exception.__init__(self, f"connection failed for key {FAKE_KEY}")

    out = digest_ai.summarize(FACTS, FakeClient(Boom()))
    assert out.status == "api_error:connection_error" and FAKE_KEY not in json.dumps(out.to_dict())


def test_the_spend_cap_stops_the_call_before_it_is_made(tmp_path):
    inner = FakeClient("unused")
    guard = SpendGuard(tmp_path, monthly_cap_usd=0.01, daily_pace=0)
    out = digest_ai.summarize(FACTS, BudgetedClient(inner, guard, max_retries=0))
    assert out.status == "spend_cap:monthly_cap" and inner.requests == []


def test_a_call_is_charged_to_the_digests_own_spend_record(tmp_path):
    inner = FakeClient("Nothing needs your attention.")
    guard = SpendGuard(tmp_path, monthly_cap_usd=3.0)
    assert digest_ai.summarize(FACTS, BudgetedClient(inner, guard, max_retries=0)).status == "ok"
    snap = guard.snapshot()
    assert snap.calls == 1 and 0 < snap.spent_usd < 0.01  # 1,200 input + 80 output tokens on Opus 5.5
    assert list(tmp_path.glob("spend-*.json"))


def test_no_key_no_client_and_a_bad_cap_is_refused(tmp_path):
    made = []
    assert digest_ai.build_client({}, tmp_path, client_factory=made.append) == (None, "no_key") and made == []
    assert digest_ai.build_client({"ANTHROPIC_API_KEY": "  "}, tmp_path, client_factory=made.append) == (None, "no_key")
    assert digest_ai.build_client({"ANTHROPIC_API_KEY": FAKE_KEY, digest_ai.MONTHLY_CAP_ENV: "-1"}, tmp_path,
                                  client_factory=made.append) == (None, "bad_cap")
    client, status = digest_ai.build_client({"ANTHROPIC_API_KEY": FAKE_KEY}, tmp_path, client_factory=lambda key: made.append(key) or FakeClient())
    assert status == "ready" and isinstance(client, BudgetedClient) and made == [FAKE_KEY]

    def broken(key):
        raise RuntimeError(f"bad key {key}")

    assert digest_ai.build_client({"ANTHROPIC_API_KEY": FAKE_KEY}, tmp_path, client_factory=broken) == (None, "client_error:RuntimeError")


def test_the_real_client_is_built_the_classifiers_way_without_sdk_retries(monkeypatch, tmp_path):
    seen = {}

    def fake_live_client(key, *, timeout_seconds, max_retries):
        seen.update(key=key, timeout=timeout_seconds, retries=max_retries)
        return FakeClient()

    monkeypatch.setattr(digest_ai, "live_client", fake_live_client)
    client, status = digest_ai.build_client({"ANTHROPIC_API_KEY": FAKE_KEY}, tmp_path)
    assert status == "ready" and seen == {"key": FAKE_KEY, "timeout": digest_ai.TIMEOUT_SECONDS, "retries": 0}


def _script():
    import importlib.util
    import sys

    name = "ops_digest_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "ops_digest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_send_mode_adds_the_summary_and_never_shows_the_key(tmp_path, monkeypatch, capsys):
    script = _script()
    fake = FakeClient("Nothing needs your attention; the shadow, news shadow, paper fleet and changelog watcher look normal.")
    monkeypatch.setattr(digest_ai, "live_client", lambda key, **kw: fake)
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    yesterday = (datetime.now(tz=timezone.utc) - timedelta(days=1)).date()
    (shadow / "heartbeat.json").write_text(json.dumps({"ts": datetime.now(tz=timezone.utc).isoformat(), "state": "running",
                                                       "flat_at_lot": True, "position": "0", "kill": False,
                                                       "last_candle": datetime.now(tz=timezone.utc).isoformat()}), encoding="utf-8")
    (shadow / f"journal-{yesterday.isoformat()}.jsonl").write_text(json.dumps({"kind": "candle", "timeframe": "1H"}) + "\n", encoding="utf-8")
    env = {"ANTHROPIC_API_KEY": FAKE_KEY, "TELEGRAM_DRY_RUN": "1"}
    args = ["--send", "--shadow-dir", str(shadow), "--news-dir", str(tmp_path / "n"), "--fleet-dir", str(tmp_path / "f"),
            "--ops-dir", str(tmp_path / "ops")]
    assert script.main(args, env=env) == 0
    captured = capsys.readouterr()
    digest = tmp_path / "ops" / "digest"
    md = (digest / f"digest-{yesterday.isoformat()}.md").read_text(encoding="utf-8")
    lines = md.split("\n")
    # the fixed NEEDS ATTENTION list comes first, the AI summary after it
    assert lines.index("NEEDS ATTENTION") < lines.index("AI SUMMARY (Claude; it can be wrong, the facts decide)")
    assert "look normal" in md and len(fake.requests) == 1
    facts = json.loads((digest / f"digest-{yesterday.isoformat()}.json").read_text(encoding="utf-8"))
    assert facts["ai"]["status"] == "ok" and facts["ai"]["model"] == "claude-opus-5-5"
    everything = captured.out + captured.err + "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "ops").rglob("*") if p.is_file())
    assert FAKE_KEY not in everything and "sk-ant" not in everything
    # Printing never spends money unless asked for, and --no-ai turns the summary off in send mode.
    assert script.main(args[1:], env=env) == 0 and len(fake.requests) == 1
    assert script.main(args + ["--no-ai"], env=env) == 0 and len(fake.requests) == 1


def test_a_dropped_summary_is_noted_and_the_digest_still_goes_out(tmp_path, monkeypatch):
    script = _script()
    monkeypatch.setattr(digest_ai, "live_client", lambda key, **kw: FakeClient("Profit was 12.5% today."))
    env = {"ANTHROPIC_API_KEY": FAKE_KEY, "TELEGRAM_DRY_RUN": "1"}
    args = ["--send", "--day", "2026-10-21", "--shadow-dir", str(tmp_path / "s"), "--news-dir", str(tmp_path / "n"),
            "--fleet-dir", str(tmp_path / "f"), "--ops-dir", str(tmp_path / "ops")]
    assert script.main(args, env=env) == 0
    md = (tmp_path / "ops" / "digest" / "digest-2026-10-21.md").read_text(encoding="utf-8")
    assert "AI SUMMARY" not in md and "12.5" not in md
    assert "(AI summary left out: it wrote a number that is not in the facts)" in md


def test_no_ai_call_when_something_needs_action(tmp_path, monkeypatch):
    script = _script()
    fake = FakeClient("Everything looks normal.")
    monkeypatch.setattr(digest_ai, "live_client", lambda key, **kw: fake)
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "ALERT").write_text("2026-10-21T01:00:00+00:00 SHADOW HALT: reconcile_inconsistent\n", encoding="utf-8")
    env = {"ANTHROPIC_API_KEY": FAKE_KEY, "TELEGRAM_DRY_RUN": "1"}
    args = ["--send", "--day", "2026-10-21", "--shadow-dir", str(shadow), "--news-dir", str(tmp_path / "n"),
            "--fleet-dir", str(tmp_path / "f"), "--ops-dir", str(tmp_path / "ops")]
    assert script.main(args, env=env) == 0
    md = (tmp_path / "ops" / "digest" / "digest-2026-10-21.md").read_text(encoding="utf-8")
    assert fake.requests == [] and "AI SUMMARY" not in md and "halted and waits for you" in md
    assert "(no AI summary today: something needs action, and the fixed lines above say what)" in md
