"""Offline end-to-end run of the news shadow from fixtures (``run_news_shadow.py --dry-run --fixtures``).

Everything the live shadow touches is replaced, and nothing else changes:

- the clock is simulated: one cycle every ``cycle_minutes`` from ``start`` to ``end``;
- the network is a fixture server (``FixtureHttp``): it renders the real wire
  formats — RSS 2.0 XML for the official feeds, GDELT DOC JSON (the last hour of
  articles, like the live ``timespan=1h`` query), OKX candle and server-time JSON —
  so the production parsers run unchanged, and it REFUSES every other URL;
- the model is a scripted offline client (``FixtureModel``) answering from the
  fixture's rules, in the same reply shape as the SDK; it is wrapped in the same
  spend guard as the live client;
- the Phase 6a journal is replayed line by line as the clock passes each line's
  time, into a fresh directory, exactly as the supervisor would append it.

No network, no API key (a key in the environment is ignored), no OKX access. The
outputs (logs, state, report) go to a new directory that is never the live one.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from app.news.budget import BudgetedClient, SpendGuard
from app.news.classifier import NewsClassifier
from app.news.dedup import SeenStore
from app.news.evaluation import Reply, ReplyBlock, ReplyUsage, parse_request
from app.news.fetch import NewsFetcher
from app.news.market import CANDLES_PATH, OKX_PUBLIC_REST, TIME_PATH, BAR_MINUTES, PublicMarketData
from app.news.phase6a import Phase6aJournal
from app.news.report import build_report_data, write_daily_report
from app.news.shadow import NewsShadowRunner, ShadowSettings
from app.news.sources import DEFAULT_SOURCES, Source, get_sources
from app.news.store import NewsShadowLog, NewsStore

DEFAULT_SHADOW_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "news_shadow"


class DryRunNetworkRefused(RuntimeError):
    """The dry run asked for a URL the fixture does not serve (it never reaches the network)."""


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"fixture time {value!r} needs a timezone")
    return parsed.astimezone(timezone.utc)


class SimClock:
    """The dry run's clock: moved forward only by the dry-run loop."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


# -- the scenario ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Move:
    instrument: str
    start: datetime
    bars: int
    pct_per_bar: float
    volume_x: float


@dataclass(frozen=True)
class Scenario:
    root: Path
    description: str
    start: datetime
    end: datetime
    cycle: timedelta
    source_ids: Tuple[str, ...]
    feeds: Mapping[str, Mapping[str, Any]]
    market: Mapping[str, Any]
    moves: Tuple[Move, ...]
    clock_skew_seconds: float
    journal: Optional[Path]
    model: Mapping[str, Any]
    monthly_cap_usd: float
    expect: Mapping[str, Any]

    @property
    def sources(self) -> List[Source]:
        return get_sources(self.source_ids)


def load_scenario(root: Path = DEFAULT_SHADOW_FIXTURES) -> Scenario:
    root = Path(root)
    spec = json.loads((root / "scenario.json").read_text(encoding="utf-8"))
    start, end = _utc(spec["start"]), _utc(spec["end"])
    cycle = timedelta(minutes=float(spec.get("cycle_minutes", 5)))
    if end < start or cycle <= timedelta(0):
        raise ValueError("scenario needs start <= end and a positive cycle")
    known = {s.source_id for s in DEFAULT_SOURCES}
    source_ids = tuple(spec["sources"])
    for source_id in source_ids:
        if source_id not in known:
            raise ValueError(f"unknown source {source_id!r}")
    feeds = {sid: json.loads((root / spec["feeds"][sid]).read_text(encoding="utf-8")) for sid in spec.get("feeds", {})}
    moves = tuple(
        Move(m["instrument"], _utc(m["from"]), int(m["bars"]), float(m["pct_per_bar"]), float(m.get("volume_x", 1.0)))
        for m in spec["market"].get("moves", [])
    )
    journal = root / spec["phase6a_journal"] if spec.get("phase6a_journal") else None
    model = json.loads((root / spec["model"]).read_text(encoding="utf-8"))
    return Scenario(
        root=root,
        description=str(spec.get("description", "")),
        start=start,
        end=end,
        cycle=cycle,
        source_ids=source_ids,
        feeds=feeds,
        market=spec["market"],
        moves=moves,
        clock_skew_seconds=float(spec.get("clock_skew_seconds", 0.0)),
        journal=journal,
        model=model,
        monthly_cap_usd=float(spec.get("monthly_cap_usd", 40.0)),
        expect=dict(spec.get("expect") or {}),
    )


# -- the fixture network -------------------------------------------------------------------------


def _rss(feed: Mapping[str, Any], now: datetime, limit: int = 25) -> str:
    channel = feed.get("channel", {})
    items = sorted((i for i in feed.get("items", []) if _utc(i["published"]) <= now), key=lambda i: i["published"], reverse=True)
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<rss version="2.0"><channel>',
        f"<title>{escape(str(channel.get('title', 'feed')))}</title>",
        f"<link>{escape(str(channel.get('link', '')))}</link>",
        f"<description>{escape(str(channel.get('description', '')))}</description>",
        "<language>en-us</language>",
    ]
    for item in items[:limit]:
        parts.append(
            "<item>"
            f"<title>{escape(item['title'])}</title>"
            f"<link>{escape(item['link'])}</link>"
            f"<description>{escape(item.get('description', ''))}</description>"
            f"<pubDate>{format_datetime(_utc(item['published']), usegmt=True)}</pubDate>"
            f"<guid>{escape(item.get('guid', item['link']))}</guid>"
            "</item>"
        )
    parts.append("</channel></rss>")
    return "\n".join(parts)


def _gdelt(feed: Mapping[str, Any], now: datetime, window: timedelta = timedelta(hours=1)) -> str:
    articles = []
    for article in sorted(feed.get("articles", []), key=lambda a: a["seen"], reverse=True):
        seen = _utc(article["seen"])
        if now - window < seen <= now:
            articles.append(
                {
                    "url": article["url"],
                    "url_mobile": "",
                    "title": article["title"],
                    "seendate": seen.strftime("%Y%m%dT%H%M%SZ"),
                    "socialimage": "",
                    "domain": article["domain"],
                    "language": article.get("language", "English"),
                    "sourcecountry": article.get("country", "United States"),
                }
            )
    return json.dumps({"articles": articles})


class FixtureHttp:
    """The dry run's whole network: fixture feeds, fixture market data, nothing else."""

    def __init__(self, scenario: Scenario, clock: SimClock) -> None:
        self._scenario = scenario
        self._clock = clock
        self._by_url: Dict[str, str] = {}
        for source in scenario.sources:
            if source.url:
                self._by_url[source.url] = source.source_id
        self.requests: List[Tuple[str, str]] = []

    def __call__(self, method: str, url: str, params: Optional[dict], json_body: Optional[dict], headers: dict) -> Tuple[int, str]:
        self.requests.append((method, url))
        now = self._clock()
        if url in self._by_url:
            source_id = self._by_url[url]
            feed = self._scenario.feeds.get(source_id)
            if feed is None:
                return 404, ""
            return 200, (_gdelt(feed, now) if feed.get("kind") == "gdelt" else _rss(feed, now))
        if url == OKX_PUBLIC_REST + CANDLES_PATH:
            return 200, self._candles(str((params or {}).get("instId")), str((params or {}).get("bar")), int((params or {}).get("limit", 300)), now)
        if url == OKX_PUBLIC_REST + TIME_PATH:
            served = now + timedelta(seconds=-self._scenario.clock_skew_seconds)
            return 200, json.dumps({"code": "0", "msg": "", "data": [{"ts": str(int(served.timestamp() * 1000))}]})
        raise DryRunNetworkRefused(f"dry run: no network ({urlsplit(url).hostname})")

    def _candles(self, instrument: str, bar: str, limit: int, now: datetime) -> str:
        spec = self._scenario.market["instruments"].get(instrument)
        if spec is None or bar not in BAR_MINUTES:
            return json.dumps({"code": "51001", "msg": "instrument not in fixture", "data": []})
        step = timedelta(minutes=BAR_MINUTES[bar])
        start = _utc(self._scenario.market["start"])
        wiggle = float(self._scenario.market.get("wiggle_pct", 0.03)) / 100
        half_range = float(spec.get("range_pct", 0.16)) / 200
        rows = []
        price = float(spec["price"])
        t = start
        i = 0
        while t <= now:
            move = next((m for m in self._scenario.moves if m.instrument == instrument and m.start <= t < m.start + step * m.bars), None)
            close = price * (1 + move.pct_per_bar / 100) if move else price * (1 + (wiggle if i % 2 == 0 else -wiggle))
            volume = float(spec["volume"]) * (move.volume_x if move else 1.0)
            high = max(price, close) * (1 + half_range)
            low = min(price, close) * (1 - half_range)
            confirmed = t + step <= now
            rows.append([str(int(t.timestamp() * 1000)), f"{price:.2f}", f"{high:.2f}", f"{low:.2f}", f"{close:.2f}", f"{volume:.4f}", "0", "0", "1" if confirmed else "0"])
            price = close
            t += step
            i += 1
        rows.reverse()  # OKX returns the newest candle first
        return json.dumps({"code": "0", "msg": "", "data": rows[:limit]})


# -- the scripted model --------------------------------------------------------------------------


_VERDICT_DEFAULTS: Dict[str, Any] = {
    "category": "NONE",
    "assets": [],
    "claim_summary": "Fixture story outside the watchlist.",
    "manipulation_signs": [],
    "corroboration_assessment": "SINGLE_SOURCE",
    "independent_source_ids": [],
    "hedging_uncertainty": 0.5,
    "direction": "UNCLEAR",
    "expected_market_reaction": "NO_CLEAR_REACTION",
    "impact_strength": 0.1,
    "volatility_risk": 0.1,
    "time_horizon_minutes": 60,
    "confidence": 0.5,
    "same_story_as": None,
    "new_development": False,
    "why_not_more_aggressive": "Fixture answer.",
    "proposed_action": "NO_EFFECT",
}


class _Messages:
    def __init__(self, create: Callable[..., Any]) -> None:
        self.create = create


class FixtureModel:
    """Answers the classifier from the fixture's rules (first matching rule wins); thread-safe, offline."""

    def __init__(self, rules: Mapping[str, Any]) -> None:
        self._rules = rules
        self.calls: List[str] = []
        self.messages = _Messages(self._create)

    @staticmethod
    def _matches(rule: Mapping[str, Any], titles: Sequence[str]) -> bool:
        needle = str(rule.get("match", "")).lower()
        return bool(needle) and any(needle in t.lower() for t in titles)

    def _usage(self, stage: str) -> ReplyUsage:
        raw = dict((self._rules.get("usage") or {}).get(stage) or {})
        return ReplyUsage(**{k: int(v) for k, v in raw.items() if k in ReplyUsage.__dataclass_fields__})

    def _create(self, **kwargs: Any) -> Reply:
        stage, payload, _ = parse_request(kwargs)
        self.calls.append(stage)
        model = str(kwargs.get("model", ""))
        if stage == "triage":
            title = str(payload["item"].get("title_sanitized", ""))
            rule = next((r for r in self._rules.get("triage", []) if self._matches(r, [title])), self._rules.get("triage_default"))
            answer = {
                "relevant": bool(rule.get("relevant", False)),
                "category": str(rule.get("category", "NONE")),
                "reason": str(rule.get("reason", "Fixture triage answer.")),
            }
            return Reply([ReplyBlock("thinking"), ReplyBlock("text", json.dumps(answer))], "end_turn", model, self._usage("triage"))
        items = payload.get("source_items", [])
        titles = [str(i.get("title_sanitized", "")) for i in items]
        rule = next((r for r in self._rules.get("classify", []) if self._matches(r, titles)), None)
        verdict = dict(_VERDICT_DEFAULTS)
        if rule is not None:
            verdict.update(rule.get("verdict", {}))
            independent = rule.get("independent", "all")
            if independent == "all":
                verdict["independent_source_ids"] = [str(i["source_id"]) for i in items]
            elif independent == "first":
                first = min(items, key=lambda i: (str(i.get("published_at") or i.get("observed_at")), str(i["source_id"])))
                verdict["independent_source_ids"] = [str(first["source_id"])]
            else:
                verdict["independent_source_ids"] = [
                    str(i["source_id"]) for i in items if any(str(n).lower() in str(i.get("title_sanitized", "")).lower() for n in independent)
                ]
            link = rule.get("link_to")
            if link:
                match = next((c for c in payload.get("existing_event_candidates", []) if c.get("summary") == link), None)
                verdict["same_story_as"] = match["event_id"] if match else None
        return Reply([ReplyBlock("thinking"), ReplyBlock("text", json.dumps(verdict))], "end_turn", model, self._usage("classify"))


# -- the replayed Phase 6a journal ---------------------------------------------------------------


class JournalReplay:
    """Appends the fixture journal's lines to ``dest`` as the clock passes each line's ``ts``."""

    def __init__(self, source: Optional[Path], dest: Path) -> None:
        self._dest = Path(dest)
        self._dest.mkdir(parents=True, exist_ok=True)
        self._lines: List[Tuple[datetime, str]] = []
        if source is not None:
            for raw in Path(source).read_text(encoding="utf-8").splitlines():
                if raw.strip():
                    self._lines.append((_utc(json.loads(raw)["ts"]), raw))
            self._lines.sort(key=lambda x: x[0])
        self._next = 0

    def advance(self, now: datetime) -> int:
        written = 0
        while self._next < len(self._lines) and self._lines[self._next][0] <= now:
            when, raw = self._lines[self._next]
            with (self._dest / f"journal-{when.date().isoformat()}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(raw + "\n")
            self._next += 1
            written += 1
        return written


# -- the run --------------------------------------------------------------------------------------


@dataclass
class DryRunResult:
    out_dir: Path
    cycles: int
    summaries: List[Dict[str, Any]]
    reports: List[Path]
    report_data: Dict[str, Any]
    expectations: List[Tuple[str, Any, Any, bool]] = field(default_factory=list)
    network_requests: int = 0

    @property
    def ok(self) -> bool:
        return self.report_data["headline"]["invariants_ok"] and all(e[3] for e in self.expectations)


def _check(expect: Mapping[str, Any], data: Mapping[str, Any]) -> List[Tuple[str, Any, Any, bool]]:
    headline = data["headline"]
    overlay = data["overlay"]
    actual = {
        "decisions": overlay["decisions"],
        "would_block": overlay["would_block"],
        "would_reduce": overlay["would_reduce"],
        "quarantined": headline["quarantined"],
        "events": headline["events"],
        "corroborated_events": headline["corroborated_events"],
        "events_with_effect": headline["events_with_effect"],
        "classify_calls": headline["classify_calls"],
        "invariants_ok": headline["invariants_ok"],
    }
    checks = []
    for key, wanted in sorted(expect.items()):
        got = actual.get(key)
        checks.append((key, wanted, got, got == wanted))
    return checks


def run_dry(
    fixtures: Path = DEFAULT_SHADOW_FIXTURES,
    out_dir: Optional[Path] = None,
    *,
    settings: Optional[ShadowSettings] = None,
    restart_at: Optional[datetime] = None,
    on_cycle: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> DryRunResult:
    """Run the whole scenario offline; returns the summaries, the report and the expectation checks.

    ``restart_at`` stops the runner at that time and continues with a brand-new
    runner on the same directories (state, news store, logs), like a service restart.
    """
    scenario = load_scenario(fixtures)
    out = Path(out_dir) if out_dir is not None else Path(tempfile.mkdtemp(prefix="news-shadow-dry-run-"))
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError(f"the dry-run output directory must be new or empty: {out}")
    clock = SimClock(scenario.start)
    http = FixtureHttp(scenario, clock)
    journal_dir = out / "phase6a"
    replay = JournalReplay(scenario.journal, journal_dir)
    settings = settings or ShadowSettings(interval_seconds=scenario.cycle.total_seconds(), triage_workers=1)

    def new_runner() -> NewsShadowRunner:
        store = NewsStore(out / "news_data")
        guard = SpendGuard(out / "_state", monthly_cap_usd=scenario.monthly_cap_usd, clock=clock)
        classifier = NewsClassifier(BudgetedClient(FixtureModel(scenario.model), guard))
        return NewsShadowRunner(
            sources=scenario.sources,
            fetcher=NewsFetcher(http, now=clock, min_gap_seconds=0.0, sleep=lambda _s: None),
            store=store,
            seen=SeenStore(store.seen_file),
            market=PublicMarketData(http),
            classifier=classifier,
            guard=guard,
            log=NewsShadowLog(out, clock=clock),
            journal=Phase6aJournal(journal_dir),
            state_dir=out / "_state",
            clock=clock,
            settings=settings,
            report_writer=lambda day: write_daily_report(out, journal_dir, day),
        )

    replay.advance(clock())
    runner = new_runner()
    runner.start()
    summaries = []
    restarted = False
    while clock() <= scenario.end:
        if restart_at is not None and not restarted and clock() >= restart_at:
            runner.stop("dry_run_restart")
            runner = new_runner()
            runner.start()
            restarted = True
        replay.advance(clock())
        summary = runner.run_cycle()
        summaries.append(summary)
        if on_cycle is not None:
            on_cycle(summary)
        clock.now += scenario.cycle
    clock.now -= scenario.cycle
    runner.stop("dry_run_finished")
    days = sorted({scenario.start.date() + timedelta(days=i) for i in range((scenario.end.date() - scenario.start.date()).days + 1)})
    reports = [write_daily_report(out, journal_dir, day) for day in days]
    data = build_report_data(out, journal_dir, days[-1])
    return DryRunResult(
        out_dir=out,
        cycles=len(summaries),
        summaries=summaries,
        reports=reports,
        report_data=data,
        expectations=_check(scenario.expect, data),
        network_requests=len(http.requests),
    )
