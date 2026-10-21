"""The log-only news shadow runner (PHASE6B_DESIGN sections 7, 11, 13): end to end offline, and its rules."""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest
import requests

import app.news.classifier as classifier_module
from app.news.decay import effective_signal
from app.news.dryrun import DEFAULT_SHADOW_FIXTURES, DryRunNetworkRefused, FixtureHttp, SimClock, load_scenario, run_dry
from app.news.evaluation import load_cases, reference_policy, run_story, scripted_classifier_for
from app.news.phase6a import Baseline, Phase6aCandidate, Phase6aJournal
from app.news.report import generate_daily_report
from app.news.schema import Action, CorroborationStatus
from app.news.shadow import (
    EventBook,
    NewsShadowRunner,
    RunnerLock,
    ShadowSettings,
    StoryEntry,
    group_stories,
    request_items,
    story_event,
)
from app.news.store import NewsShadowLog
from tests.news_fixtures import NOW, event, item, verdict

DAY = date(2026, 10, 19)
T = lambda hh, mm=0, ss=0: datetime(2026, 10, 19, hh, mm, ss, tzinfo=timezone.utc)  # noqa: E731


def records(out: Path, day: date = DAY) -> List[Dict[str, Any]]:
    path = out / f"events-{day.isoformat()}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def decisions(out: Path, day: date = DAY) -> List[Dict[str, Any]]:
    path = out / f"decisions-{day.isoformat()}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fixture_copy(tmp_path: Path, edit: Callable[[Path], None]) -> Path:
    root = tmp_path / "fixtures"
    shutil.copytree(DEFAULT_SHADOW_FIXTURES, root)
    edit(root)
    return root


def edit_json(path: Path, change: Callable[[Any], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


@pytest.fixture
def no_network(monkeypatch):
    """Any real HTTP request or real Anthropic client fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("the news shadow test tried to reach the network")

    monkeypatch.setattr(requests, "request", refuse)
    monkeypatch.setattr(requests.Session, "request", refuse)
    monkeypatch.setattr(classifier_module, "_default_client", refuse)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-value-not-a-key")  # set on purpose: the dry run must ignore it


@pytest.fixture(scope="module")
def baseline_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("dry") / "out"
    return run_dry(out_dir=out)


# -- the offline end-to-end run ------------------------------------------------------------------


def test_dry_run_meets_every_expectation_without_network_or_key(tmp_path: Path, no_network):
    result = run_dry(out_dir=tmp_path / "out")
    assert result.ok, result.expectations
    assert all(ok for *_, ok in result.expectations) and len(result.expectations) >= 9
    assert result.cycles == 53 and result.network_requests > 0  # all served by the fixture
    assert result.report_data["headline"]["invariants_ok"]


def test_the_fixture_network_refuses_everything_else():
    scenario = load_scenario()
    http = FixtureHttp(scenario, SimClock(scenario.start))
    with pytest.raises(DryRunNetworkRefused):
        http("GET", "https://api.anthropic.com/v1/messages", None, None, {})
    with pytest.raises(DryRunNetworkRefused):
        http("GET", "https://www.okx.com/api/v5/market/books", None, None, {})


def test_each_phase6a_candidate_gets_the_right_counterfactual(baseline_run):
    rows = {d["candle_ts"]: d for d in decisions(baseline_run.out_dir)}
    assert set(rows) == {"2026-10-19T10:00:00+00:00", "2026-10-19T11:00:00+00:00", "2026-10-19T12:00:00+00:00"}
    reduce_, blocked_baseline, block = (rows[f"2026-10-19T{h}:00:00+00:00"] for h in ("10", "11", "12"))
    # 11:00 decision, allowed by Phase 6a, while the confirmed Meridex event is live: reduced to 75 %.
    assert reduce_["action"] == "REDUCE_SIZE" and reduce_["size_multiplier"] == "0.75"
    assert reduce_["would_have_reduced_here"] and not reduce_["would_have_blocked_here"]
    assert Decimal(reduce_["hypothetical_adjusted_notional"]) == Decimal(reduce_["baseline_notional"]) * Decimal("0.75")
    # 12:00: Phase 6a had already blocked it (confidence floor); news would block too, but it is NOT counted.
    assert not blocked_baseline["baseline_allowed"] and blocked_baseline["baseline_reason"] == "confidence_too_low"
    assert blocked_baseline["action"] == "BLOCK_NEW_LONGS" and not blocked_baseline["would_have_blocked_here"]
    assert blocked_baseline["hypothetical_adjusted_notional"] is None
    # 13:00: allowed by Phase 6a while the corroborated SEC action is live: blocked.
    assert block["action"] == "BLOCK_NEW_LONGS" and block["would_have_blocked_here"] and block["hypothetical_adjusted_notional"] == "0"
    for d in rows.values():
        assert d["signal_action"] == "long" and d["news_healthy"] and d["overlay_version"] == "phase6b-overlay-v1"
        assert Decimal(d["size_multiplier"]) <= 1
        assert datetime.fromisoformat(d["evaluated_at"]) >= datetime.fromisoformat(d["decision_time"])


def test_the_candidate_from_before_the_shadow_started_is_not_evaluated(baseline_run):
    assert all(d["candle_ts"] != "2026-10-19T07:00:00+00:00" for d in decisions(baseline_run.out_dir))
    skipped = sum(s["overlay"].get("skipped_before_start", 0) for s in baseline_run.summaries)
    assert skipped == 1


def test_quarantined_and_stale_items_never_reach_the_model(baseline_run):
    recs = records(baseline_run.out_dir)
    observed = [r for r in recs if r["kind"] == "source_item_observed"]
    withheld = {r["item_id"] for r in observed if r["triage"]["status"] in ("quarantined", "skipped_stale")}
    assert len([r for r in observed if r["quarantined"]]) == 2 and len(withheld) == 7
    sent = {i for r in recs if r["kind"].startswith("classifier_") for i in r.get("item_ids", [])}
    assert sent and not (sent & withheld)


def test_copies_share_one_triage_call_and_a_later_copy_is_attached_without_a_call(baseline_run):
    recs = records(baseline_run.out_dir)
    statuses = [r["triage"]["status"] for r in recs if r["kind"] == "source_item_observed"]
    assert statuses.count("reused") == 2 and statuses.count("attached") == 1
    (attached,) = [r for r in recs if r["kind"] == "event_deduplicated" and r.get("reasons") == ["same_headline_copy"]]
    assert attached["event_id"].startswith("evt_20261019_hack_")


def test_a_story_is_corroborated_across_cycles_over_all_its_articles(baseline_run):
    updates = [r for r in records(baseline_run.out_dir) if r["kind"] == "corroboration_update"]
    hack = [u for u in updates if (u["event_id"] or "").startswith("evt_20261019_hack_") and u["linked_event_id"]]
    (merge,) = hack
    assert merge["corroboration"]["status"] == "INDEPENDENT_SOURCE_CONFIRMED"
    assert set(merge["corroboration"]["families"]) == {"wire:reuters", "domain:chainledger-news.example"}
    assert len(merge["story_item_ids"]) == 4  # the three wire copies from 10:05 and the 10:22 report


def test_a_repeat_never_refires_the_ttl_and_events_expire(baseline_run):
    recs = records(baseline_run.out_dir)
    hack_versions = [
        r["event"] for r in recs if r["kind"] in ("event_candidate_created", "event_deduplicated") and r.get("event") and r["event"]["event_id"].startswith("evt_20261019_hack_btc_eth_30")
    ]
    assert len({v["expires_at"] for v in hack_versions}) == 1 and len({v["first_seen_at"] for v in hack_versions}) == 1
    expired = [r for r in recs if r["kind"] == "effective_signal" and r.get("reason") == "expired"]
    assert expired and all(r["action"] == "NO_EFFECT" for r in expired)


def test_the_report_is_reproducible_from_the_logs(baseline_run):
    out = baseline_run.out_dir
    written = (out / "report-2026-10-19.md").read_text(encoding="utf-8")
    assert generate_daily_report(out, out / "phase6a", DAY) == written == generate_daily_report(out, out / "phase6a", DAY)
    for heading in ("## In short", "## Safety checks", "## Shadow entry overlays", "## Events", "## Sources and articles", "## AI calls", "## For manual review", "## Runner", "## Open anomalies"):
        assert heading in written
    assert "no claim about profit" in written and "**FAIL**" not in written


def test_the_spend_is_estimated_and_persisted(baseline_run):
    spend = json.loads((baseline_run.out_dir / "_state" / "spend-2026-10.json").read_text(encoding="utf-8"))
    assert spend["calls"] == 13 and 0.19 < spend["spent_usd"] < 0.20
    assert set(spend["by_model"]) == {"claude-haiku-5-5", "claude-opus-5-5"}


# -- variants of the scenario ----------------------------------------------------------------------


def test_a_weak_repeat_cannot_switch_off_a_live_event(tmp_path: Path, no_network):
    """The R4b gap: one more outlet repeating a live story keeps the evidence the story already has."""

    def edit(root: Path) -> None:
        edit_json(
            root / "feeds" / "gdelt_doc.json",
            lambda d: d["articles"].append(
                {"seen": "2026-10-19T10:48:00Z", "domain": "repeatsite.example", "url": "https://repeatsite.example/meridex", "title": "Another outlet repeats Meridex wallet breach report"}
            ),
        )

        def rule(model):
            model["classify"].insert(
                0,
                {
                    "match": "Another outlet repeats Meridex",
                    "independent": "all",
                    "link_to": "The Meridex exchange confirmed a security incident and paused withdrawals.",
                    "verdict": {
                        "category": "EXCHANGE_HACK_EXPLOIT", "assets": ["BTC", "ETH"],
                        "claim_summary": "One more outlet repeats the Meridex breach report.",
                        "corroboration_assessment": "SINGLE_SOURCE", "direction": "RISK_OFF",
                        "expected_market_reaction": "DOWN_OR_VOLATILE", "impact_strength": 0.9, "volatility_risk": 0.9,
                        "time_horizon_minutes": 360, "confidence": 0.9, "proposed_action": "BLOCK_NEW_LONGS",
                    },
                },
            )

        edit_json(root / "model.json", rule)
        edit_json(root / "scenario.json", lambda s: s.update(expect={}))

    result = run_dry(fixture_copy(tmp_path, edit), tmp_path / "out")
    hack = [r for r in records(result.out_dir) if r["kind"] == "event_deduplicated" and r.get("event") and r["event"]["event_id"].startswith("evt_20261019_hack_btc_eth_30")]
    last = hack[-1]["event"]
    assert last["corroboration_status"] == "INDEPENDENT_SOURCE_CONFIRMED"
    assert last["source_quality"]["independent_source_count"] == 3 and last["action"] == "REDUCE_SIZE"
    rows = {d["candle_ts"]: d for d in decisions(result.out_dir)}
    assert rows["2026-10-19T10:00:00+00:00"]["would_have_reduced_here"]
    assert result.report_data["headline"]["invariants_ok"]


def test_a_skewed_clock_makes_the_news_state_unhealthy_and_every_decision_no_effect(tmp_path: Path, no_network):
    root = fixture_copy(tmp_path, lambda r: edit_json(r / "scenario.json", lambda s: s.update(clock_skew_seconds=120.0, expect={})))
    result = run_dry(root, tmp_path / "out")
    rows = decisions(result.out_dir)
    assert len(rows) == 3 and all(d["action"] == "NO_EFFECT" and d["why_no_effect"] == "news_unhealthy" for d in rows)
    assert not any(d["would_have_blocked_here"] or d["would_have_reduced_here"] for d in rows)
    assert all(not s["healthy"] and "clock_skew" in s["unhealthy_reasons"] for s in result.summaries)
    assert result.report_data["headline"]["invariants_ok"]
    assert any("clock skew" in a for a in result.report_data["anomalies"])


def test_all_sources_down_is_unhealthy_and_harmless(tmp_path: Path, no_network):
    def edit(root: Path) -> None:
        edit_json(root / "scenario.json", lambda s: (s.update(expect={}), s["feeds"].clear()))

    result = run_dry(fixture_copy(tmp_path, edit), tmp_path / "out")
    assert all(not s["healthy"] and "all_sources_failed" in s["unhealthy_reasons"] for s in result.summaries)
    assert result.report_data["headline"]["events"] == 0
    assert all(d["action"] == "NO_EFFECT" for d in decisions(result.out_dir))


def test_a_zero_spend_cap_means_no_model_call_at_all(tmp_path: Path, no_network):
    root = fixture_copy(tmp_path, lambda r: edit_json(r / "scenario.json", lambda s: s.update(monthly_cap_usd=0.0, expect={})))
    result = run_dry(root, tmp_path / "out")
    recs = records(result.out_dir)
    assert not [r for r in recs if r["kind"].startswith("classifier_")]
    statuses = {r["triage"]["status"] for r in recs if r["kind"] == "source_item_observed"}
    assert "skipped_budget" in statuses and "called" not in statuses
    assert result.report_data["headline"]["events"] == 0
    assert all(d["action"] == "NO_EFFECT" for d in decisions(result.out_dir))
    # The cap holding back triage alone is visible: a runner event and a report anomaly.
    assert [r["event"] for r in recs if r["kind"] == "runner_event" and r["event"].startswith("spend_cap")] == ["spend_cap_reached"]
    assert any("spend cap held back" in a for a in result.report_data["anomalies"])


def test_no_model_mode_collects_news_and_calls_nothing(tmp_path: Path, no_network):
    result = run_dry(out_dir=tmp_path / "out", settings=ShadowSettings(interval_seconds=300, model_enabled=False))
    recs = records(result.out_dir)
    assert not [r for r in recs if r["kind"].startswith("classifier_")]
    assert {r["triage"]["status"] for r in recs if r["kind"] == "source_item_observed"} == {"model_disabled", "quarantined", "skipped_stale"}
    assert len(decisions(result.out_dir)) == 3 and "AI was switched off" in (result.out_dir / "report-2026-10-19.md").read_text(encoding="utf-8")


def test_a_restart_restores_state_and_gives_the_same_decisions(tmp_path: Path, baseline_run, no_network):
    result = run_dry(out_dir=tmp_path / "out", restart_at=T(10, 45))
    assert result.ok
    key = lambda d: (d["candle_ts"], d["action"], d["size_multiplier"], d["would_have_blocked_here"], d["would_have_reduced_here"])  # noqa: E731
    assert sorted(map(key, decisions(result.out_dir))) == sorted(map(key, decisions(baseline_run.out_dir)))
    starts = [r for r in records(result.out_dir) if r["kind"] == "runner_event" and r["event"] == "start"]
    assert [s["state_restored"] for s in starts] == [False, True] and starts[1]["events_tracked"] == 2


def test_the_triage_cycle_cap_is_logged_never_silent(tmp_path: Path, no_network):
    result = run_dry(out_dir=tmp_path / "out", settings=ShadowSettings(interval_seconds=300, max_triage_per_cycle=1))
    statuses = [r["triage"]["status"] for r in records(result.out_dir) if r["kind"] == "source_item_observed"]
    assert "skipped_cycle_cap" in statuses
    assert max(s["triage"].get("calls", 0) for s in result.summaries) == 1


# -- the rules, unit by unit ---------------------------------------------------------------------


def test_story_event_is_the_eval_path_for_every_eval_case():
    """For a story without earlier articles the shadow builds exactly what the R4b eval scores."""
    compared = 0
    for case in load_cases():
        result = run_story(case, scripted_classifier_for(reference_policy)(case, 1))
        if result.verdict is None or result.build is None:
            continue
        relevant = [i for (key, outcome), i in zip(result.triage, case.items) if outcome.relevant]
        linked = None
        if result.linked_event_id:
            existing = next(e for e in case.existing if e.event_id == result.linked_event_id)
            linked = StoryEntry(existing.event_id, "", case.now, versions=[(case.now, existing)], records={})
        story = story_event(result.verdict, relevant, {}, linked, case.candles, case.now)
        assert story.build.event == result.build.event, case.id
        assert story.build.reasons == result.build.reasons, case.id
        compared += 1
    assert compared >= 100


def test_group_stories_by_category_and_headline_words():
    a1 = item(1, title="Meridex exchange says hot wallet breached, $310 million drained")
    a2 = item(2, title="Meridex exchange says hot wallet breached, $310 million drained")
    a3 = item(3, title="Meridex hot wallet breached; exchange says $310 million drained")
    b = item(4, title="SEC sues exchange operator over missing customer funds")
    c = item(5, title="Meridex exchange says hot wallet breached, $310 million drained")
    stories = group_stories([(a1, "EXCHANGE_HACK_EXPLOIT"), (a2, "EXCHANGE_HACK_EXPLOIT"), (a3, "EXCHANGE_HACK_EXPLOIT"), (b, "MAJOR_REGULATORY_ACTION"), (c, "MAJOR_REGULATORY_ACTION")])
    groups = sorted(sorted(i.item_id for i in s.items) for s in stories)
    assert groups == sorted([sorted([a1.item_id, a2.item_id, a3.item_id]), [b.item_id], [c.item_id]])


def test_request_items_takes_one_article_per_publisher_first():
    from app.news.shadow import Story

    many = [item(i, publisher=f"Pub {i % 3}", title="Same story") for i in range(20)]
    story = Story("EXCHANGE_HACK_EXPLOIT", many, [frozenset()] * 20)
    chosen, left = request_items(story, limit=12)
    assert len(chosen) == 12 and len(left) == 8
    assert {i.publisher for i in chosen[:3]} == {"Pub 0", "Pub 1", "Pub 2"}


def _bare_runner(tmp_path: Path, **settings: Any) -> NewsShadowRunner:
    return NewsShadowRunner(
        sources=[],
        fetcher=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        seen=None,  # type: ignore[arg-type]
        market=None,  # type: ignore[arg-type]
        classifier=None,
        guard=None,
        log=NewsShadowLog(tmp_path / "logs", clock=lambda: NOW),
        journal=Phase6aJournal(tmp_path / "journal"),
        state_dir=tmp_path / "state",
        clock=lambda: NOW,
        settings=ShadowSettings(**settings),
    )


def strong_event(first_seen: datetime):
    """An official, long-lived, corroborated event that still blocks 40 minutes in."""
    from app.news.schema import SourceTier

    return event(first_seen=first_seen, ttl_minutes=1440, confidence=0.95, impact=0.95, tier=SourceTier.OFFICIAL)


def _candidate(at: datetime, allowed: bool = True) -> Phase6aCandidate:
    return Phase6aCandidate(
        key=f"BTC-USDT|{at.isoformat()}",
        instrument="BTC-USDT",
        timeframe="1H",
        candle_ts=at - timedelta(hours=1),
        close_time=at,
        signal_source="shadow_eval",
        confidence=0.7,
        cleared=True,
        veto_reason=None,
        signal_reason="",
        baseline=Baseline(allowed, "ok" if allowed else "disarmed", "runtime", at),
    )


def test_an_event_learned_after_the_decision_is_not_used(tmp_path: Path):
    runner = _bare_runner(tmp_path)
    ev = strong_event(NOW - timedelta(minutes=30))
    runner.book.record(ev, known_at=NOW + timedelta(minutes=2), story_key="k", records={})
    runner._health = [(NOW - timedelta(minutes=1), True)]
    before = runner.evaluate_candidate(_candidate(NOW), NOW + timedelta(minutes=5))
    assert before["action"] == "NO_EFFECT" and before["why_no_effect"] == "no_event_for_instrument"
    runner._health.append((NOW + timedelta(minutes=4), True))
    later = runner.evaluate_candidate(_candidate(NOW + timedelta(minutes=5)), NOW + timedelta(minutes=6))
    assert later["action"] == "BLOCK_NEW_LONGS" and later["would_have_blocked_here"]


def test_an_older_version_is_used_for_an_earlier_decision(tmp_path: Path):
    runner = _bare_runner(tmp_path)
    weak = event(first_seen=NOW - timedelta(minutes=30), status=CorroborationStatus.SINGLE_SOURCE, action=Action.NO_EFFECT)
    strong = event(first_seen=NOW - timedelta(minutes=30))
    runner.book.record(weak, known_at=NOW - timedelta(minutes=20), story_key="k", records={})
    runner.book.record(strong, known_at=NOW + timedelta(minutes=1), story_key="k", records={})
    runner._health = [(NOW - timedelta(minutes=2), True)]
    record = runner.evaluate_candidate(_candidate(NOW), NOW + timedelta(minutes=5))
    assert record["action"] == "NO_EFFECT" and record["events_at_decision"][0]["reason"] == "status_single_source"


def test_a_stale_news_state_at_decision_time_is_no_effect(tmp_path: Path):
    runner = _bare_runner(tmp_path, stale_after_seconds=900)
    runner.book.record(event(first_seen=NOW - timedelta(minutes=30)), known_at=NOW - timedelta(minutes=29), story_key="k", records={})
    runner._health = [(NOW - timedelta(minutes=16), True), (NOW - timedelta(minutes=5), False)]
    record = runner.evaluate_candidate(_candidate(NOW), NOW + timedelta(minutes=5))
    assert record["action"] == "NO_EFFECT" and record["why_no_effect"] == "news_unhealthy" and not record["news_healthy"]


def test_a_blocked_baseline_is_never_counted_as_prevented(tmp_path: Path):
    runner = _bare_runner(tmp_path)
    runner.book.record(strong_event(NOW - timedelta(minutes=30)), known_at=NOW - timedelta(minutes=29), story_key="k", records={})
    runner._health = [(NOW - timedelta(minutes=1), True)]
    record = runner.evaluate_candidate(_candidate(NOW, allowed=False), NOW + timedelta(minutes=5))
    assert record["action"] == "BLOCK_NEW_LONGS" and not record["would_have_blocked_here"] and not record["allowed"]


def test_event_book_versions_prune_and_round_trip_through_state(tmp_path: Path):
    book = EventBook(item_cap=2)
    ev = event(first_seen=NOW, ttl_minutes=60)
    book.record(ev, known_at=NOW, story_key="k", records={"a": {"x": 1}, "b": {"x": 2}, "c": {"x": 3}})
    book.record(ev, known_at=NOW - timedelta(minutes=5), story_key="k", records={})  # never back in time
    entry = book.get(ev.event_id)
    assert len(entry.records) == 2 and entry.versions[1][0] == NOW
    assert book.as_of(NOW - timedelta(seconds=1)) == [] and book.as_of(NOW) == [ev]
    restored = EventBook.from_state(json.loads(json.dumps(book.to_state())))
    assert restored.get(ev.event_id).event == ev and restored.get(ev.event_id).versions[0][0] == NOW
    assert book.prune(NOW + timedelta(hours=1), timedelta(minutes=30)) == []
    assert book.prune(NOW + timedelta(hours=2), timedelta(minutes=30)) == [ev.event_id] and len(book) == 0


def test_an_unreadable_state_file_is_set_aside_and_the_runner_starts_empty(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "shadow_state.json").write_text("{not json", encoding="utf-8")
    runner = _bare_runner(tmp_path)
    runner.start()
    assert len(runner.book) == 0 and not (state / "shadow_state.json").exists()
    assert any(p.name.startswith("shadow_state.json.unreadable-") for p in state.iterdir())
    logged = [json.loads(line) for line in (tmp_path / "logs" / f"events-{NOW.date().isoformat()}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["event"] for r in logged if r["kind"] == "runner_event"] == ["state_reset", "start"]


def test_only_one_runner_per_state_directory(tmp_path: Path):
    first, second = RunnerLock(tmp_path / "runner.lock"), RunnerLock(tmp_path / "runner.lock")
    assert first.acquire()
    try:
        assert not second.acquire()
    finally:
        first.release()
    assert second.acquire()
    second.release()


def test_settings_validation():
    with pytest.raises(ValueError):
        ShadowSettings(interval_seconds=0)
    with pytest.raises(ValueError):
        ShadowSettings(instruments=("SOL-USDT",))
    with pytest.raises(ValueError):
        ShadowSettings(link_candidates=-1)


def test_effective_signal_records_never_exceed_one_and_respect_status(baseline_run):
    for r in records(baseline_run.out_dir):
        if r["kind"] != "effective_signal":
            continue
        assert Decimal(r["size_multiplier"]) <= 1
        if r.get("scope") == "event" and r["action"] != "NO_EFFECT":
            assert r["status"] in ("INDEPENDENT_SOURCE_CONFIRMED", "PRICE_VOLUME_CONFIRMED")
            assert datetime.fromisoformat(r["at"]) < datetime.fromisoformat(r["expires_at"])


def test_a_triage_exception_is_a_failed_outcome_and_the_items_are_still_logged(tmp_path: Path, monkeypatch, no_network):
    from app.news.classifier import NewsClassifier

    real = NewsClassifier.triage

    def flaky(self, item, *, now):
        if "Kryvex" in item.title:
            raise RuntimeError("bug in a client")
        return real(self, item, now=now)

    monkeypatch.setattr(NewsClassifier, "triage", flaky)
    root = fixture_copy(tmp_path, lambda r: edit_json(r / "scenario.json", lambda s: s.update(expect={})))
    result = run_dry(root, tmp_path / "out")
    observed = [r for r in records(result.out_dir) if r["kind"] == "source_item_observed"]
    (kryvex,) = [r for r in observed if "Kryvex" in (r["title"] or "")]
    assert kryvex["triage"] == {"status": "failed", "failure": "unexpected_error:RuntimeError"}
    assert len(observed) == 18 and not any(s["errors"] for s in result.summaries)
    assert result.report_data["headline"]["would_block"] == 1  # everything else unaffected


def test_a_headline_found_off_watchlist_is_not_classified_again(tmp_path: Path, no_network):
    title = "Bitcoin conference announces keynote speaker lineup"

    def edit(root: Path) -> None:
        def feeds(d):
            d["articles"] += [
                {"seen": "2026-10-19T09:38:00Z", "domain": "eventsdesk.example", "url": "https://eventsdesk.example/conf", "title": title},
                {"seen": "2026-10-19T10:28:00Z", "domain": "otherdesk.example", "url": "https://otherdesk.example/conf", "title": title},
            ]

        def model(m):
            m["triage"].insert(0, {"match": "conference announces", "relevant": True, "category": "MAJOR_REGULATORY_ACTION"})

        edit_json(root / "feeds" / "gdelt_doc.json", feeds)
        edit_json(root / "model.json", model)
        edit_json(root / "scenario.json", lambda s: s.update(expect={}))

    result = run_dry(fixture_copy(tmp_path, edit), tmp_path / "out")
    recs = records(result.out_dir)
    copies = [r for r in recs if r["kind"] == "source_item_observed" and r["title"] == title]
    assert [c["triage"]["status"] for c in copies] == ["called", "reused"]
    assert copies[1]["triage"]["relevant"] is False
    classify_items = [r["item_ids"] for r in recs if r["kind"].startswith("classifier_") and r["stage"] == "classify"]
    assert sum(1 for ids in classify_items if copies[0]["item_id"] in ids or copies[1]["item_id"] in ids) == 1


# -- evidence is never erased; a doubtful link never pools evidence (review findings) -----------------


def _record(key: str, title: str, *, domain: str, observed: datetime) -> Dict[str, Any]:
    """An ingestion record whose item id is ``itm_<key>``."""
    return {
        "content_key": key,
        "source_id": "gdelt_doc",
        "publisher": domain,
        "publisher_owner": "",
        "canonical_url": f"https://{domain}/{key}",
        "source_tier": "MEDIUM",
        "observed_at": observed.isoformat(),
        "published_at": (observed - timedelta(minutes=2)).isoformat(),
        "title": title,
        "excerpt": "",
        "sanitization_flags": [],
        "quarantined": False,
        "story_key": f"story-{key}",
    }


def test_a_market_confirmation_is_never_forgotten_by_a_repeat():
    from app.news.corroborate import PriceVolumeCheck, PublicCandle
    from app.news.schema import SourceItemRef, SourceTier

    first_seen = NOW - timedelta(hours=2)
    title = "Meridex exchange says hot wallet breached"
    linked_event = event(first_seen=first_seen, status=CorroborationStatus.PRICE_VOLUME_CONFIRMED, count=1, tier=SourceTier.MEDIUM,
                         action=Action.REDUCE_SIZE, ttl_minutes=720)
    entry = StoryEntry(linked_event.event_id, "story-a", first_seen, versions=[(first_seen, linked_event)],
                       records={"itm_a": _record("a", title, domain="a.example", observed=first_seen)})
    confirmed = PriceVolumeCheck("BTC-USDT", True, "confirmed", first_seen + timedelta(minutes=30), first_seen, 100.0, 97.0, -3.0, 1.0, 3.0, 30, 6, 0)
    repeat = SourceItemRef.from_record(_record("b", title, domain="b.example", observed=NOW))  # same headline: a copy
    flat = [PublicCandle(NOW - timedelta(hours=6) + timedelta(minutes=5 * i), timedelta(minutes=5), 100, 100.2, 99.8, 100, 10) for i in range(70)]
    repeat_verdict = verdict(corroboration_assessment="SINGLE_SOURCE", independent_source_ids=[repeat.item_id], same_story_as=linked_event.event_id)
    # The price has retraced: today's check alone would not confirm, so without memory the story drops to one source.
    entry.price_volume = []
    forgotten = story_event(repeat_verdict, [repeat], {}, entry, {"BTC-USDT": flat}, NOW)
    assert forgotten.corroboration.status is CorroborationStatus.SINGLE_SOURCE
    entry.price_volume = [confirmed.to_dict()]
    kept = story_event(repeat_verdict, [repeat], {}, entry, {"BTC-USDT": flat}, NOW)
    assert kept.corroboration.status is CorroborationStatus.PRICE_VOLUME_CONFIRMED
    assert kept.build.event.corroboration_status is CorroborationStatus.PRICE_VOLUME_CONFIRMED
    assert kept.build.event.expires_at == linked_event.expires_at  # and the repeat never re-fires the TTL


def test_counted_sources_survive_the_article_cap():
    from app.news.schema import SourceQuality

    book = EventBook(item_cap=3)
    base = event(first_seen=NOW)
    copies = {f"itm_c{i}": _record(f"c{i}", "Same headline", domain=f"c{i}.example", observed=NOW) for i in range(5)}
    book.record(base, known_at=NOW, story_key="k", records=copies)  # fills the cap with copies
    counted = base.model_copy(update={"source_quality": SourceQuality(tier=base.source_quality.tier, independent_source_count=2,
                                                                        primary_sources=(), secondary_sources=(), source_ids=("itm_c0", "itm_z"), notes="n")})
    book.record(counted, known_at=NOW + timedelta(minutes=5), story_key="k",
                records={"itm_z": _record("z", "Independent report", domain="z.example", observed=NOW)})
    entry = book.get(base.event_id)
    assert len(entry.records) == 4 and "itm_z" in entry.records  # beyond the cap, because it is a counted source
    assert not book.attach(base.event_id, {"itm_c9": copies["itm_c4"]})  # copies stay capped


def test_link_problem_requires_category_assets_and_a_shared_distinctive_word():
    from app.news.schema import SourceItemRef
    from app.news.shadow import link_problem

    seen = NOW - timedelta(hours=1)
    linked_event = event(first_seen=seen)
    entry = StoryEntry(linked_event.event_id, "k", seen, versions=[(seen, linked_event)],
                       records={"itm_a": _record("a", "Unverified post claims Kryvex exchange froze withdrawals", domain="a.example", observed=seen)})
    same = SourceItemRef.from_record(_record("b", "Kryvex confirms withdrawal freeze after wallet breach", domain="b.example", observed=NOW))
    other = SourceItemRef.from_record(_record("c", "Unconfirmed claim: Zorbex lending desk halts redemptions", domain="c.example", observed=NOW))
    generic = SourceItemRef.from_record(_record("d", "Bitcoin exchange market prices fall, crypto traders say", domain="d.example", observed=NOW))
    assert link_problem(verdict(), [same], entry) is None
    assert link_problem(verdict(), [other], entry) == "no_shared_headline_words"
    assert link_problem(verdict(), [generic], entry) == "no_shared_headline_words"  # common market words prove nothing
    assert link_problem(verdict(category="GEOPOLITICAL_ESCALATION"), [same], entry) == "category_mismatch"
    narrowed = event(first_seen=seen, assets=("ETH",))
    eth_only = StoryEntry(narrowed.event_id, "k", seen, versions=[(seen, narrowed)], records=entry.records)
    assert link_problem(verdict(assets=["BTC"]), [same], eth_only) == "asset_mismatch"


def test_a_wrong_link_cannot_turn_two_rumours_into_a_confirmed_event(tmp_path: Path, no_network):
    def edit(root: Path) -> None:
        edit_json(
            root / "feeds" / "gdelt_doc.json",
            lambda d: d["articles"].append(
                {"seen": "2026-10-19T09:48:00Z", "domain": "lendingwatch.example", "url": "https://lendingwatch.example/zorbex",
                 "title": "Unconfirmed claim: Zorbex lending desk halts redemptions"}
            ),
        )

        def model(m):
            m["triage"].insert(0, {"match": "Zorbex", "relevant": True, "category": "EXCHANGE_HACK_EXPLOIT"})
            m["classify"].insert(0, {
                "match": "Zorbex", "independent": "all",
                "link_to": "An unverified social-media post claims the Kryvex exchange froze withdrawals.",
                "verdict": {"category": "EXCHANGE_HACK_EXPLOIT", "assets": ["BTC", "ETH"],
                            "claim_summary": "A wrongly linked second rumour.", "corroboration_assessment": "INDEPENDENT_SOURCE_CONFIRMED",
                            "direction": "RISK_OFF", "expected_market_reaction": "DOWN_OR_VOLATILE", "impact_strength": 0.9,
                            "volatility_risk": 0.9, "time_horizon_minutes": 240, "confidence": 0.9, "proposed_action": "BLOCK_NEW_LONGS"},
            })

        edit_json(root / "model.json", model)
        edit_json(root / "scenario.json", lambda s: s.update(expect={}))

    result = run_dry(fixture_copy(tmp_path, edit), tmp_path / "out")
    recs = records(result.out_dir)
    (update,) = [r for r in recs if r["kind"] == "corroboration_update" and r.get("classifier_link") and r.get("link_rejected")]
    assert update["link_rejected"] == "no_shared_headline_words" and update["linked_event_id"] is None
    assert update["corroboration"]["status"] == "SINGLE_SOURCE"
    kryvex = [r["event"] for r in recs if r["kind"] in ("event_candidate_created", "event_deduplicated") and r.get("event")
              and "Kryvex" in r["event"]["raw_summary"]]
    assert all(e["corroboration_status"] == "SINGLE_SOURCE" for e in kryvex)
    assert result.report_data["headline"]["events_with_effect"] == 2 and result.report_data["headline"]["invariants_ok"]


def test_an_unverifiable_clock_makes_the_news_state_unhealthy(tmp_path: Path, monkeypatch, no_network):
    from app.news.market import PublicMarketData

    monkeypatch.setattr(PublicMarketData, "clock_skew_seconds", lambda self, local_now: None)
    result = run_dry(out_dir=tmp_path / "out")
    assert all("clock_unverified" in s["unhealthy_reasons"] for s in result.summaries)
    assert all(d["why_no_effect"] == "news_unhealthy" for d in decisions(result.out_dir))
