"""Daily ops digest (plan row R6; master plan section 5.4) — plain English, to Telegram; observability only.

One message a day that says what needs attention and how the Phase 6a shadow, the
news shadow, the paper fleet and the OKX changelog watcher did, built from the files
they already write (never their databases, never the exchange). A fixed template
decides every line; when ``ANTHROPIC_API_KEY`` is set, Claude adds a short summary on
top (``app/ops/digest_ai.py``), and the template goes out either way.

Modes::

    python scripts/ops_digest.py                  # build yesterday's digest and print it (no Telegram, no AI)
    python scripts/ops_digest.py --send           # the timer: save it under logs/ops/digest/, add the AI
                                                  #   summary when a key is set, send it to Telegram
    python scripts/ops_digest.py --day 2026-10-21 # another UTC day (with or without --send)
    python scripts/ops_digest.py --dry-run        # offline self-check on the bundled fixtures: no network, no key

Telegram credentials come from the environment only (``TELEGRAM_BOT_TOKEN``,
``TELEGRAM_CHAT_ID``; never printed); ``TELEGRAM_DRY_RUN=1`` formats but never sends.
This script holds no exchange keys, never loads the repository ``.env``, places,
sizes, approves, modifies and cancels nothing, and nothing in trading reads its output.

Exit codes: 0 = done; 1 = the Telegram send failed, or a dry run missed one of its
checks; 2 = setup error (a bad option, or ``--send`` without Telegram credentials).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

if __name__ == "__main__":
    sys.modules.setdefault("dotenv", None)  # nothing this process imports may load the repository .env

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.news.budget import DEFAULT_MONTHLY_CAP_USD as NEWS_DEFAULT_CAP_USD  # noqa: E402
from app.news.budget import MONTHLY_CAP_ENV as NEWS_CAP_ENV  # noqa: E402
from app.news.budget import env_float  # noqa: E402
from app.notify.telegram import TelegramNotifier  # noqa: E402
from app.ops import digest as dg  # noqa: E402
from app.ops import digest_ai  # noqa: E402
from app.ops.okx_changelog import DEFAULT_STATE_DIR as CHANGELOG_DEFAULT_DIR  # noqa: E402
from app.ops.okx_changelog import STATE_DIR_ENV as CHANGELOG_DIR_ENV  # noqa: E402
from app.ops.okx_changelog import run_check  # noqa: E402

SHADOW_DIR_ENV = "PHASE6A_JOURNAL_DIR"  # the same variable the news shadow reads
DEFAULT_SHADOW_DIR = "logs/shadow"
NEWS_DIR_ENV = "NEWS_SHADOW_LOG_DIR"
DEFAULT_NEWS_DIR = "logs/news_shadow"
FLEET_DIR_ENV = "PAPER_FLEET_DIR"
DEFAULT_FLEET_DIR = "logs/paper_fleet"
OPS_DIR_ENV = "OPS_DIR"
DEFAULT_OPS_DIR = "logs/ops"
TRUTHY = {"1", "true", "yes", "on"}

FIXTURES = ROOT / "tests" / "fixtures"
DRY_NEWS_FIXTURES = FIXTURES / "news_shadow"
DRY_FLEET_FIXTURE = FIXTURES / "paper_fleet_r5a"
DRY_CHANGELOG_PAGE = FIXTURES / "okx_changelog" / "changelog_v1.html"
DRY_DAY = date(2026, 10, 19)
DRY_NOW = datetime(2026, 10, 19, 13, 25, tzinfo=timezone.utc)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily ops digest (reads files only; no orders, no exchange keys).")
    p.add_argument("--send", action="store_true", help="Save the digest and send it to Telegram (the timer).")
    p.add_argument("--dry-run", action="store_true", help="Offline self-check on the bundled fixtures (no network, no key).")
    p.add_argument("--day", default=None, metavar="YYYY-MM-DD", help="The UTC day of the 'yesterday' lines (default: yesterday).")
    p.add_argument("--ai", dest="ai", action="store_true", default=None,
                   help="Add the Claude summary when printing (it costs a few cents; --send adds it by default).")
    p.add_argument("--no-ai", dest="ai", action="store_false", help="Never ask for the Claude summary.")
    p.add_argument("--shadow-dir", type=Path, default=None, help=f"Phase 6a folder, read-only (default ${SHADOW_DIR_ENV} or {DEFAULT_SHADOW_DIR}).")
    p.add_argument("--news-dir", type=Path, default=None, help=f"News shadow folder, read-only (default ${NEWS_DIR_ENV} or {DEFAULT_NEWS_DIR}).")
    p.add_argument("--fleet-dir", type=Path, default=None, help=f"Paper fleet folder, read-only (default ${FLEET_DIR_ENV} or {DEFAULT_FLEET_DIR}).")
    p.add_argument("--ops-dir", type=Path, default=None, help=f"This digest's own folder (default ${OPS_DIR_ENV} or {DEFAULT_OPS_DIR}).")
    p.add_argument("--changelog-dir", type=Path, default=None,
                   help=f"The changelog watcher's state, read-only (default ${CHANGELOG_DIR_ENV} or {CHANGELOG_DEFAULT_DIR}).")
    p.add_argument("--json", action="store_true", help="Print the facts as JSON instead of the text.")
    args = p.parse_args(argv)
    if args.day is not None:
        try:
            args.day = date.fromisoformat(args.day)
        except ValueError:
            p.error("--day must be YYYY-MM-DD")
    if args.dry_run and (args.send or args.day is not None):
        p.error("--dry-run runs on its own fixtures; it does not take --send or --day")
    return args


def telegram_dry_run(env: Mapping[str, str]) -> bool:
    return (env.get("TELEGRAM_DRY_RUN") or "").strip().lower() in TRUTHY


def notifier_from_env(env: Mapping[str, str]) -> TelegramNotifier:
    """The existing notifier; with TELEGRAM_DRY_RUN set it formats and never sends, credentials or not."""
    if telegram_dry_run(env):
        return TelegramNotifier(token="dry-run", chat_id="dry-run", dry_run=True)
    return TelegramNotifier.from_env(env)


@dataclass(frozen=True)
class Dirs:
    shadow: Path
    news: Path
    fleet: Path
    ops: Path
    changelog: Path

    @property
    def digest(self) -> Path:
        return self.ops / "digest"

    @property
    def ai_state(self) -> Path:
        return self.ops / "digest" / "_state"


def resolve_dirs(args: argparse.Namespace, env: Mapping[str, str]) -> Dirs:
    ops = args.ops_dir or Path(env.get(OPS_DIR_ENV) or DEFAULT_OPS_DIR)
    changelog = args.changelog_dir or (Path(env[CHANGELOG_DIR_ENV]) if env.get(CHANGELOG_DIR_ENV) else ops / "okx_changelog")
    return Dirs(
        shadow=args.shadow_dir or Path(env.get(SHADOW_DIR_ENV) or DEFAULT_SHADOW_DIR),
        news=args.news_dir or Path(env.get(NEWS_DIR_ENV) or DEFAULT_NEWS_DIR),
        fleet=args.fleet_dir or Path(env.get(FLEET_DIR_ENV) or DEFAULT_FLEET_DIR),
        ops=ops,
        changelog=changelog,
    )


def fleet_facts_safe(fleet_dir: Path, now: datetime) -> Dict[str, Any]:
    """The fleet's facts through its own read-only view; any failure becomes an error line, never a crash."""
    try:
        from research.paper_fleet.digest import fleet_facts

        return fleet_facts(fleet_dir, now)
    except Exception as exc:
        return {"dir": str(fleet_dir), "installed": Path(fleet_dir).is_dir(), "found": False,
                "error": f"the fleet could not be read ({type(exc).__name__})"}


def build(dirs: Dirs, day: date, now: datetime, env: Mapping[str, str], *, expect_shadow: bool = False) -> Dict[str, Any]:
    try:
        news_cap = env_float(env, NEWS_CAP_ENV, NEWS_DEFAULT_CAP_USD)
    except ValueError:
        news_cap = NEWS_DEFAULT_CAP_USD
    return dg.build_facts(now=now, day=day, shadow_dir=dirs.shadow, news_dir=dirs.news, changelog_dir=dirs.changelog,
                          fleet=fleet_facts_safe(dirs.fleet, now), news_cap_usd=news_cap, expect_shadow=expect_shadow)


def ai_summary(text: str, env: Mapping[str, str], state_dir: Path, client: Any = None) -> Tuple[Optional[str], Dict[str, Any]]:
    """(summary or None, a record of what happened). The digest never waits on this beyond one call."""
    if client is None:
        client, reason = digest_ai.build_client(env, state_dir)
        if client is None:
            return None, {"status": reason}
    outcome = digest_ai.summarize(text, client)
    return outcome.summary, outcome.to_dict()


AI_NOTES = {
    "skipped_action_items": "no AI summary today: something needs action, and the fixed lines above say what",
    "refusal": "AI summary left out: the model declined",
    "max_tokens": "AI summary left out: the answer was cut off",
    "unverified_numbers": "AI summary left out: it wrote a number that is not in the facts",
    "link": "AI summary left out: it contained a web address",
    "too_long": "AI summary left out: too long",
    "empty": "AI summary left out: empty answer",
}


def _ai_note(record: Mapping[str, Any]) -> Optional[str]:
    status = str(record.get("status") or "")
    if status in ("ok", "no_key", "off", ""):
        return None
    if status.startswith("spend_cap"):
        return "AI summary left out: its monthly cap is reached"
    return AI_NOTES.get(status, f"AI summary left out: {status}")


def cmd_digest(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    dirs = resolve_dirs(args, env)
    now = datetime.now(tz=timezone.utc)
    day = args.day or (now.date() - timedelta(days=1))
    notifier = None
    if args.send:
        notifier = notifier_from_env(env)
        if not notifier.configured:
            print("ops digest not sent: --send needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (or TELEGRAM_DRY_RUN=1)",
                  file=sys.stderr)
            return 2
    facts = build(dirs, day, now, env, expect_shadow=args.send)  # the timer runs next to the shadow
    use_ai = args.send if args.ai is None else args.ai
    summary, ai_record = (None, {"status": "off"})
    text = dg.render(facts)
    has_key = bool((env.get(digest_ai.API_KEY_ENV) or "").strip())
    if use_ai and not has_key:
        ai_record = {"status": "no_key"}
    elif use_ai and any(a.get("level") == "ACTION" for a in facts.get("attention") or []):
        ai_record = {"status": "skipped_action_items"}  # the fixed ACTION lines speak for themselves
        text = dg.render(facts, ai_note=_ai_note(ai_record))
    elif use_ai:
        summary, ai_record = ai_summary(text, env, dirs.ai_state)
        text = dg.render(facts, ai_summary=summary, ai_note=_ai_note(ai_record))
    facts["ai"] = ai_record
    if not args.send:
        print(json.dumps(facts, indent=1, sort_keys=True, default=str) if args.json else text, end="" if not args.json else "\n")
        return 0
    # Send first: a full disk or a folder this user cannot write must not cost the day's message.
    result = dg.send_text(text, notifier)
    saved = None
    try:
        md, _ = dg.write_outputs(dirs.digest, facts, text)
        saved = str(md)
        dg.append_run_log(dirs.digest, {"at": now.isoformat(timespec="seconds"), "day": day.isoformat(), "send": result.status,
                                        "parts": result.parts, "error": result.error, "ai": ai_record.get("status"),
                                        "attention": len(facts.get("attention") or []), "file": saved})
    except OSError as exc:
        print(f"ops digest {day}: could not save under {dirs.digest} ({type(exc).__name__})", file=sys.stderr)
    if result.status in ("sent", "dry-run"):
        print(f"ops digest {day}: {result.status} in {result.parts} message(s); " + (f"saved {saved}" if saved else "NOT saved"))
        return 0 if saved else 1
    print(f"ops digest {day}: NOT sent ({result.status}: {result.error or 'no detail'}); "
          + (f"saved {saved}" if saved else "NOT saved"), file=sys.stderr)
    return 1


# -- the offline dry run ---------------------------------------------------------------------


class ScriptedClient:
    """An offline stand-in for the AI client: returns the scripted replies in order (no network, no key)."""

    def __init__(self, replies: List[Dict[str, Any]]) -> None:
        self._replies = list(replies)
        self.messages = self
        self.calls: List[Dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self._replies.pop(0)
        content = [type("Block", (), {"type": "text", "text": reply.get("text", "")})()]
        usage = type("Usage", (), {"input_tokens": 1500, "output_tokens": 90})()
        return type("Reply", (), {"model": digest_ai.MODEL, "stop_reason": reply.get("stop_reason", "end_turn"),
                                  "content": content, "usage": usage})()


def _dry_shadow(out: Path, journal: Path) -> Path:
    shadow = out / "shadow"
    shadow.mkdir(parents=True)
    shutil.copy(journal, shadow / journal.name)
    (shadow / dg.HEARTBEAT_FILENAME).write_text(json.dumps({
        "ts": (DRY_NOW - timedelta(seconds=20)).isoformat(), "pid": 4242, "state": "running",
        "armed_until": (DRY_NOW + timedelta(minutes=50)).isoformat(), "kill": False, "kill_owner": None,
        "restarts_in_window": 0, "position": "0", "flat_at_lot": True, "entries_today": 2, "day_pnl": "0",
        "last_candle": "2026-10-19 12:00:00+00:00", "market_continuity_ok": True}), encoding="utf-8")
    (shadow / dg.STATE_FILENAME).write_text(json.dumps({"kill_owner": None, "capped_day": None, "alert": None, "restarts": []}),
                                            encoding="utf-8")
    return shadow


def _dry_fleet(out: Path) -> Path:
    fleet = out / "paper_fleet"
    shutil.copytree(DRY_FLEET_FIXTURE, fleet, ignore=shutil.ignore_patterns("README.md", "make_fixture.py"))
    path = fleet / "_state" / "fleet_state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    stamp = (DRY_NOW - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["last_cycle"] = stamp  # the copy plays a fleet that is running now
    state.setdefault("health", {})["last_cycle"] = stamp
    path.write_text(json.dumps(state), encoding="utf-8")
    return fleet


def cmd_dry_run(args: argparse.Namespace) -> int:
    from app.news.dryrun import run_dry

    out = Path(tempfile.mkdtemp(prefix="ops-digest-dry-run-"))
    checks: List[Tuple[str, bool, str]] = []
    news = run_dry(DRY_NEWS_FIXTURES, out / "news_shadow")
    checks.append(("the news shadow dry run passed its own checks", bool(news.ok), ""))
    shadow = _dry_shadow(out, news.out_dir / "phase6a" / f"journal-{DRY_DAY.isoformat()}.jsonl")
    fleet = _dry_fleet(out)
    changelog_dir = out / "ops" / "okx_changelog"
    page = DRY_CHANGELOG_PAGE.read_text(encoding="utf-8")
    sent: List[str] = []
    watch = run_check(changelog_dir, DRY_NOW - timedelta(hours=1), fetch=lambda: page, notify=lambda t: sent.append(t) or True)
    checks.append(("the changelog watcher flags the port-8443 entry", any("8443" in t for t in sent), f"{len(watch.flags)} flagged"))
    dirs = Dirs(shadow=shadow, news=news.out_dir, fleet=fleet, ops=out / "ops", changelog=changelog_dir)
    facts = build(dirs, DRY_DAY, DRY_NOW, {})
    text = dg.render(facts)
    levels = [a["level"] for a in facts["attention"]]
    checks.append(("every source was read", all((facts.get(k) or {}).get(flag) for k, flag in
                                                (("shadow", "present"), ("news", "installed"), ("fleet", "found"), ("changelog", "installed"))), ""))
    checks.append(("nothing is late or failing (no ACTION line)", "ACTION" not in levels, ", ".join(levels) or "none"))
    checks.append(("the new changelog flags are listed for attention", any("changelog" in a["text"] for a in facts["attention"]), ""))
    day = facts["shadow"]["day"]
    checks.append(("the shadow journal counts match the fixture",
                   (day["signals"]["long"], day["signals"]["cleared"], day["decisions"].get("entry_allowed"), day["decisions"].get("entry_blocked"))
                   == (4, 3, 3, 1), json.dumps(day["signals"])))
    headline = facts["news"]["day"].get("headline") or {}
    checks.append(("the news numbers match the news report", (headline.get("would_block"), headline.get("would_reduce"),
                                                              headline.get("invariants_ok")) == (1, 1, True), json.dumps(headline)))
    # The AI guard rails, offline: a faithful summary is kept; an invented number, a refusal and a link are dropped.
    good = (f"Nothing is late or failing. The shadow journaled {day['candles']} candles and the changelog watcher "
            "flagged entries to read.")
    flipped = f"The shadow saw -{day['candles']} candles."  # a real number with an invented sign
    client = ScriptedClient([{"text": good}, {"text": "The fleet gained 7.25% this week."}, {"text": flipped},
                             {"text": "", "stop_reason": "refusal"}, {"text": "Details are on example.com."}])
    statuses = []
    for _ in range(5):
        summary, record = ai_summary(text, {}, out / "ops" / "digest" / "_state", client=client)
        statuses.append(record["status"])
    checks.append(("AI summary guard: kept; invented number, flipped sign, refusal and web address dropped",
                   statuses == ["ok", "unverified_numbers", "unverified_numbers", "refusal", "link"], ", ".join(statuses)))
    checks.append(("no AI call without a key", digest_ai.build_client({}, out / "ops" / "digest" / "_state")[1] == "no_key", ""))
    pieces = dg.split_message(text * 3)
    checks.append(("long digests are split under Telegram's limit", len(pieces) > 1 and all(len(p) <= 4096 for p in pieces),
                   f"{len(pieces)} pieces"))
    dry = TelegramNotifier(token="dry-run", chat_id="dry-run", dry_run=True)
    checks.append(("Telegram in dry-run mode formats and sends nothing", dg.send_text(text, dry).status == "dry-run", ""))
    md, _ = dg.write_outputs(out / "ops" / "digest", facts, text)
    print("DRY RUN on the bundled fixtures (invented data, fixed clock 2026-10-19 13:25 UTC; no network, no key)\n")
    print(text)
    ok = True
    for name, passed, detail in checks:
        ok = ok and passed
        print(f"check: {name}: {'ok' if passed else 'FAILED'}" + (f" ({detail})" if detail and not passed else ""))
    print(f"files: {out} (digest {md.name})")
    return 0 if ok else 1


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    args = parse_args(argv)
    env = os.environ if env is None else env
    if args.dry_run:
        return cmd_dry_run(args)
    return cmd_digest(args, env)


if __name__ == "__main__":
    raise SystemExit(main())
