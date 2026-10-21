"""The OKX API changelog watcher (plan row R6): parsing, matching, state, failures, alerts — offline.

The page fixtures under ``tests/fixtures/okx_changelog/`` copy the structure of the
real page (https://www.okx.com/docs-v5/log_en/, checked 2026-10-22) with invented
text: ``changelog_v2.html`` is the same page a week later (one entry edited, three
new ones).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ops import okx_changelog as oc
from app.ops import okx_usage
from app.ops.okx_changelog import ChangelogEntry, ChangelogError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "okx_changelog"
V1 = (FIXTURES / "changelog_v1.html").read_text(encoding="utf-8")
V2 = (FIXTURES / "changelog_v2.html").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 22, 3, 30, tzinfo=timezone.utc)


def _entry(text: str = "", *, codes=(), hrefs=(), title: str = "t", upcoming: bool = False, day: str = "2026-10-20") -> ChangelogEntry:
    return ChangelogEntry(entry_id="x", group=day, title=title, date=day, upcoming=upcoming, text=f"{title} {text}",
                          codes=tuple(codes), hrefs=tuple(hrefs))


def _by_id(entries):
    return {e.entry_id: e for e in entries}


# -- parsing ------------------------------------------------------------------------------------


def test_the_page_is_split_into_its_entries():
    entries = oc.parse_changelog(V1)
    ids = [e.entry_id for e in entries]
    assert ids[:2] == ["upcoming-changes-websocket-port-8443-discontinuation", "upcoming-changes-signal-sharing-new-endpoint"]
    assert "2026-09-28" in ids  # the text before a group's first h2 is its own entry
    assert ids.count("2024-01-18") == 1 and "2024-01-18~2" in ids  # a repeated date heading stays two entries
    assert len(entries) == 12
    assert not any("2099" in i for i in ids)  # a heading in a <script> or after the content column is not an entry
    by_id = _by_id(entries)
    up = by_id["upcoming-changes-websocket-port-8443-discontinuation"]
    assert up.upcoming and up.date == "2026-10-16"  # an upcoming entry is dated by its "Last update"
    assert "Breaking change" in up.text and ":8443" in up.codes  # its h3 belongs to it
    assert by_id["2026-04-22-reclassification-of-instcategory"].title == "Reclassification of instCategory"  # an h3-only group
    assert by_id["2021-02-05"].title.startswith("Added a new response field to Get Balance")  # a group without headings
    assert by_id["2021-02-05"].hrefs == ("/docs-v5/en/#trading-account-rest-api-get-balance",)
    assert up.url == "https://www.okx.com/docs-v5/log_en/#upcoming-changes-websocket-port-8443-discontinuation"


def test_code_examples_are_not_prose():
    sharing = _by_id(oc.parse_changelog(V1))["upcoming-changes-signal-sharing-new-endpoint"]
    assert "shortLink" not in sharing.text and "8443" not in sharing.text  # the <pre> example is skipped
    assert oc.match_entry(sharing) == ()


def test_hidden_characters_never_reach_a_title_or_a_link():
    entries = oc.parse_changelog(V1)
    glp = next(e for e in entries if e.entry_id.startswith("2026-09-28-g"))
    assert "​" in glp.entry_id  # the id is kept as OKX wrote it (it is only a key)
    assert glp.title == oc.safe_title(glp.title) == "GLP program update"  # the text is cleaned when it is read
    assert "Ignore previous instructions" in glp.text and oc.match_entry(glp) == ()  # outside text is data, nothing more
    assert glp.url == oc.CHANGELOG_URL  # an id that is not a plain slug never becomes a link anchor


def test_parsing_odd_html_never_raises():
    for html in ("", "<html>", "<h2 id='x'>orphan</h2>", "<h1 id='2026-01-01'>2026-01-01</h1><h2>no id</h2><p>text", "\x00" * 10):
        oc.parse_changelog(html)
    entries = oc.parse_changelog("<h1 id='2026-01-01'>2026-01-01</h1><h2>No id here</h2><p>port 8443</p>")
    assert len(entries) == 1 and entries[0].entry_id.startswith("2026-01-01-") and "port 8443" in oc.match_entry(entries[0])


# -- matching -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry, expected, absent",
    [
        (_entry("Remove :8443 from your URLs."), {"port 8443"}, set()),
        (_entry("Order id 18443 and 84430 are examples."), set(), {"port 8443"}),
        (_entry("wss://wsaws.okx.com/ws/v5/public-sbe stays."), set(), {"host aws.okx.com", "WebSocket path /ws/v5/public"}),
        (_entry("REST via aws.okx.com and ws.okx.com."), {"host aws.okx.com", "host ws.okx.com"}, set()),
        (_entry("POST /api/v5/trade/order-algo changed."), {"POST /api/v5/trade/order-algo", "GET /api/v5/trade/order-algo"},
         {"POST /api/v5/trade/order", "GET /api/v5/trade/order"}),
        (_entry("", hrefs=["/docs-v5/en/#order-book-trading-market-data-get-candlesticks-history"]),
         {"GET /api/v5/market/history-candles"}, {"GET /api/v5/market/candles"}),
        (_entry("", hrefs=["/docs-v5/en/#order-book-trading-market-data-ws-all-trades-channel"]), set(), {"WebSocket channel trades"}),
        (_entry("the orders of all users", codes=["checksum"]), set(), {"WebSocket channel orders"}),
        (_entry("", codes=["orders"]), {"WebSocket channel orders"}, set()),
        (_entry("Bars of candle1H align to UTC."), {"WebSocket channel candle1H"}, set()),
        (_entry("Add the X-SIMULATED-TRADING header."), {"demo header x-simulated-trading"}, set()),
        (_entry("Create an API Key for a sub-account with perm and ip."), set(), {"API key rules"}),
        (_entry("Withdrawal requires that the API Key must be bound to an IP."), {"API key rules", "IP binding of keys"}, set()),
        (_entry("Only whitelisted users can use spread trading."), set(), {"API key rules", "IP binding of keys"}),
        (_entry("Error 50110: your IP is not allowed."), {"IP binding of keys"}, set()),
    ],
)
def test_watch_terms_are_specific(entry, expected, absent):
    found = set(oc.match_entry(entry))
    assert expected <= found, found
    assert not (absent & found), found


def test_impact_wording_ranks_but_never_flags_alone():
    assert oc.has_impact_wording(_entry("This parameter is deprecated."))
    assert oc.has_impact_wording(_entry("Connections on port 8443 will no longer be accepted."))
    assert not oc.has_impact_wording(_entry("www.okx.com will continue to work and will not be deprecated."))
    assert not oc.has_impact_wording(_entry("This endpoint won't be retired."))
    assert not oc.has_impact_wording(_entry("This is not a breaking change."))
    assert not oc.has_impact_wording(_entry("Requests take no longer than 5 seconds."))
    assert oc.match_entry(_entry("The XYZ program will be discontinued.")) == ()


def test_hidden_characters_cannot_hide_a_term():
    html = "<div class='content'><h1 id='2026-10-20'>2026-10-20</h1><h2 id='p'>Ports</h2><p>Port 84&#8203;43 stops; host ws&#x200D;.okx.com.</p></div>"
    entry, = oc.parse_changelog(html)
    assert {"port 8443", "host ws.okx.com"} <= set(oc.match_entry(entry))


# -- checks and state ---------------------------------------------------------------------------


def _run(tmp_path, html, now=NOW, notify=None, **kw):
    sent = []
    result = oc.run_check(tmp_path, now, fetch=lambda: html if not callable(html) else html(),
                          notify=notify or (lambda t: sent.append(t) or True), **kw)
    return result, sent


def test_the_first_check_is_a_quiet_baseline_with_recent_flags(tmp_path):
    result, sent = _run(tmp_path, V1)
    assert result.ok and result.first_run and result.new == 12
    flagged = [f.entry.entry_id for f in result.flags]
    # the upcoming change and the entries of the last 30 days that mention what we use; older history is recorded silently
    assert flagged == ["upcoming-changes-websocket-port-8443-discontinuation", "2026-10-01-orders-channel-push-behavior",
                       "2026-09-28-new-rest-api-domain"]
    assert len(sent) == 1 and "first check" in sent[0] and "8443" in sent[0]
    state = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))
    assert len(state["entries"]) == 12 and state["entry_count"] == 12 and state["consecutive_failures"] == 0
    assert [r["notified"] for r in state["recent"]] == [True, True, True]
    log = [json.loads(line) for line in (tmp_path / oc.LOG_FILE).read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in log] == ["flag", "flag", "flag", "check"]


def test_the_same_page_again_says_nothing(tmp_path):
    _run(tmp_path, V1)
    result, sent = _run(tmp_path, V1, now=NOW + timedelta(days=1))
    assert result.ok and not result.first_run and (result.new, result.updated) == (0, 0) and not result.flags and sent == []


def test_new_and_edited_entries_are_flagged_once(tmp_path):
    _run(tmp_path, V1)
    result, sent = _run(tmp_path, V2, now=NOW + timedelta(days=7))
    assert (result.new, result.updated) == (3, 1)
    flags = {f.entry.entry_id: f for f in result.flags}
    assert set(flags) == {"upcoming-changes-websocket-port-8443-discontinuation", "upcoming-changes-api-key-ip-binding",
                          "2026-10-20-candlesticks-channel-bar-alignment"}  # the event-contracts entry mentions nothing we use
    assert flags["upcoming-changes-websocket-port-8443-discontinuation"].change == "updated"
    assert flags["upcoming-changes-websocket-port-8443-discontinuation"].entry.date == "2026-10-23"
    assert set(flags["upcoming-changes-api-key-ip-binding"].matches) == {"API key rules", "IP binding of keys"}
    text = sent[0]
    assert "3 entries mention" in text and "updated" in text and "first check" not in text
    assert "#2026-10-20-candlesticks-channel-bar-alignment" in text
    again, sent_again = _run(tmp_path, V2, now=NOW + timedelta(days=8))
    assert not again.flags and sent_again == []


def test_failures_are_counted_and_reported_once(tmp_path):
    _run(tmp_path, V1)

    def broken():
        raise ChangelogError("fetch_failed", "ConnectionError")

    sent_all = []
    for day in range(1, 6):
        result, sent = _run(tmp_path, broken, now=NOW + timedelta(days=day))
        sent_all.append(len(sent))
        assert not result.ok and result.error == "fetch_failed" and result.consecutive_failures == day
    assert sent_all == [0, 0, 1, 0, 0]  # one alert, at the third failed check in a row
    state = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))
    assert len(state["entries"]) == 12  # the known entries survive the failures
    result, _ = _run(tmp_path, V1, now=NOW + timedelta(days=6))
    state = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))
    assert result.ok and state["consecutive_failures"] == 0 and state["failure_alert_sent_at"] is None


def test_a_block_page_or_a_shrunk_page_is_a_failure_not_an_empty_changelog(tmp_path):
    result, sent = _run(tmp_path, "<html><body>Access denied</body></html>")
    assert not result.ok and result.error == "no_entries" and sent == []
    _run(tmp_path, V1)
    tiny = "<div class='content'><h1 id='2026-10-21'>2026-10-21</h1><h2 id='a'>A</h2><p>port 8443</p></div>"
    result, sent = _run(tmp_path, tiny, now=NOW + timedelta(days=1))
    assert not result.ok and result.error == "page_shrank" and sent == []
    state = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))
    assert len(state["entries"]) == 12 and "a" not in state["entries"]


def test_an_unexpected_parser_error_is_a_failed_check(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "parse_changelog", lambda html: 1 / 0)
    result, _ = _run(tmp_path, V1)
    assert not result.ok and result.error == "unexpected_error:ZeroDivisionError"


def test_a_preview_leaves_the_state_alone(tmp_path):
    result, sent = _run(tmp_path, V1, persist=False)
    assert result.flags and sent and not any(tmp_path.iterdir())
    _run(tmp_path, V1)
    before = (tmp_path / oc.STATE_FILE).read_bytes(), (tmp_path / oc.LOG_FILE).read_bytes()
    result, sent = _run(tmp_path, V2, now=NOW + timedelta(days=7), persist=False)
    assert len(result.flags) == 3 and sent
    assert ((tmp_path / oc.STATE_FILE).read_bytes(), (tmp_path / oc.LOG_FILE).read_bytes()) == before


def test_an_unreadable_state_is_set_aside_and_a_new_baseline_starts(tmp_path):
    (tmp_path / oc.STATE_FILE).write_text("{not json", encoding="utf-8")
    result, _ = _run(tmp_path, V1)
    assert result.ok and result.first_run
    assert list(tmp_path.glob(f"{oc.STATE_FILE}.unreadable-*"))


def test_an_undelivered_alert_is_sent_again_with_the_next_check(tmp_path):
    def boom(text):
        raise RuntimeError("telegram down")

    result, _ = _run(tmp_path, V1, notify=boom)
    state = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))
    assert result.ok and not result.delivered and len(state["entries"]) == 12
    assert [r["notified"] for r in state["recent"]] == [False, False, False] and len(state["pending"]) == 3
    # a dry run (or another failure) delivers nothing either: the alerts stay pending
    result, sent = _run(tmp_path, V1, now=NOW + timedelta(days=1), notify=lambda t: False)
    assert result.resent == 3 and len(json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))["pending"]) == 3
    # Telegram is back: the three old alerts go out with the new ones, once
    result, sent = _run(tmp_path, V2, now=NOW + timedelta(days=2))
    assert result.resent == 2 and len(result.flags) == 3  # the edited 8443 entry is new news, not a repeat
    assert len(sent) == 1 and "2 of them could not be delivered earlier and are sent again." in sent[0]
    assert "#2026-10-01-orders-channel-push-behavior" in sent[0] and "#2026-09-28-new-rest-api-domain" in sent[0]
    state = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))
    assert state["pending"] == [] and all(r["notified"] for r in state["recent"])
    _, sent = _run(tmp_path, V2, now=NOW + timedelta(days=3))
    assert sent == []


def test_waiting_alerts_go_out_even_when_the_page_cannot_be_read(tmp_path):
    _run(tmp_path, V1, notify=lambda t: False)  # Telegram down at the first check

    def blocked():
        raise ChangelogError("http_status", "HTTP 503")

    result, sent = _run(tmp_path, blocked, now=NOW + timedelta(days=1))
    assert not result.ok and result.resent == 3 and result.delivered
    assert len(sent) == 1 and "3 of them could not be delivered earlier" in sent[0]
    state = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))
    assert state["pending"] == [] and all(r["notified"] for r in state["recent"])


def test_an_undelivered_bulk_notice_waits_too(tmp_path):
    _run(tmp_path, V1)
    big = "<div class='content'>" + "".join(
        f"<h1 id='2025-02-{d:02d}'>2025-02-{d:02d}</h1><h2 id='bulk-{d}'>Bulk {d}</h2><p>Text.</p>" for d in range(1, 26))
    page = V1.replace("<div class=\"content\">", big, 1)
    result, _ = _run(tmp_path, page, now=NOW + timedelta(days=1), notify=lambda t: False)
    assert result.mass_change
    pending = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))["pending"]
    assert [p["change"] for p in pending] == ["bulk"]
    _, sent = _run(tmp_path, page, now=NOW + timedelta(days=2))
    assert len(sent) == 1 and "The changelog page changed in bulk (25 of 37 entries); skim it by hand" in sent[0]
    assert sent[0].startswith("OKX API changelog: a notice that could not be delivered earlier, sent again")


def test_an_undelivered_alert_expires_after_a_week(tmp_path):
    _run(tmp_path, V1, notify=lambda t: False)
    result, sent = _run(tmp_path, V1, now=NOW + timedelta(days=oc.PENDING_KEEP_DAYS, hours=1))
    assert result.resent == 0 and sent == []


def test_a_page_wide_change_is_a_new_baseline_not_a_flood(tmp_path):
    _run(tmp_path, V1)
    big = "<div class='content'>" + "".join(
        f"<h1 id='2025-01-{d:02d}'>2025-01-{d:02d}</h1><h2 id='old-{d}'>Old {d}</h2><p>Place order /api/v5/trade/order changed.</p>"
        for d in range(1, 29)) + "</div>"
    page = V1.replace("<div class=\"content\">", big[:-6], 1)  # 28 old entries now appear with ids never seen before
    result, sent = _run(tmp_path, page, now=NOW + timedelta(days=1))
    assert result.mass_change and result.new == 28 and result.flags == []  # only upcoming changes could be flagged
    assert len(sent) == 1 and "the page changed in bulk (28 of 40 entries" in sent[0] and "Skim the page by hand" in sent[0]
    again, sent = _run(tmp_path, page, now=NOW + timedelta(days=2))
    assert not again.mass_change and sent == []  # the bulk page is the new baseline
    few = V1.replace("id='2026-10-01-orders-channel-push-behavior'", "id='2026-10-01-orders-channel-push-update'")
    result, sent = _run(tmp_path / "b", V1)
    result, sent = _run(tmp_path / "b", few, now=NOW + timedelta(days=1))
    assert not result.mass_change and [f.entry.entry_id for f in result.flags] == ["2026-10-01-orders-channel-push-update"]


def test_the_status_summary_lists_the_last_week(tmp_path):
    _run(tmp_path, V1)
    state = json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))
    assert len(oc.status_summary(state, NOW + timedelta(days=1))["flagged_recent"]) == 3
    assert oc.status_summary(state, NOW + timedelta(days=8))["flagged_recent"] == []


def test_the_alert_is_plain_text_and_bounded():
    flags = [oc.Flag(entry=_entry(title=f"Entry {i} ​**bold**", day="2026-10-20"), change="new",
                     matches=tuple(f"m{j}" for j in range(9)), impact=i == 0) for i in range(12)]
    text = oc.render_alert([f.to_record(NOW, False) for f in flags], first_run=True, baseline_days=14)
    assert text.count("\n- [") == 10 and "... and 2 more" in text and "and 3 more" in text
    assert "​" not in text and "breaking change, deprecation or shutdown" in text
    assert "the last 14 days only" in text


# -- fetching -----------------------------------------------------------------------------------


class _Resp:
    def __init__(self, status=200, body=b"<html></html>", chunk=65536):
        self.status_code, self._body, self._chunk, self.closed = status, body, chunk, False

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), self._chunk):
            yield self._body[i:i + self._chunk]

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.resp


@pytest.mark.parametrize("url", ["http://www.okx.com/docs-v5/log_en/", "https://okx.com/docs-v5/log_en/",
                                 "https://www.okx.com.evil.example/docs-v5/log_en/", "https://www.okx.com/api/v5/trade/order",
                                 "https://www.okx.com/docs-v5/log_en/?x=1", "https://user:pw@www.okx.com/docs-v5/log_en/",
                                 "https://www.okx.com:8443/docs-v5/log_en/"])
def test_only_the_public_docs_pages_may_be_read(url):
    with pytest.raises(ChangelogError) as info:
        oc.check_url(url)
    assert info.value.code == "url_refused"


def test_the_fetch_is_one_plain_get_without_redirects_or_credentials():
    session = _Session(_Resp(200, V1.encode("utf-8"), chunk=1000))
    assert oc.fetch_changelog(session=session) == V1
    (url, kwargs), = session.calls
    assert url == oc.CHANGELOG_URL and kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert set(kwargs["headers"]) == {"User-Agent", "Accept", "Accept-Language"}
    assert session.resp.closed


@pytest.mark.parametrize("resp, code", [(_Resp(301), "redirected"), (_Resp(503), "http_status"),
                                        (_Resp(200, b"x" * 5000, chunk=1000), "too_large")])
def test_fetch_failures_have_stable_codes(resp, code):
    with pytest.raises(ChangelogError) as info:
        oc.fetch_changelog(session=_Session(resp), max_bytes=4000)
    assert info.value.code == code and resp.closed


def test_a_network_error_is_reported_without_its_text():
    import requests

    class Down:
        def get(self, url, **kwargs):
            raise requests.ConnectionError("secret-looking detail")

    with pytest.raises(ChangelogError) as info:
        oc.fetch_changelog(session=Down())
    assert info.value.code == "fetch_failed" and "secret" not in str(info.value)


# -- the watch list -----------------------------------------------------------------------------


def test_every_watch_item_is_well_formed():
    labels = [i.label for i in okx_usage.WATCH_ITEMS]
    assert len(labels) == len(set(labels))
    for item in okx_usage.WATCH_ITEMS:
        assert item.category in okx_usage.CATEGORIES and item.used_by
        for kind, pattern in item.patterns:
            assert kind in okx_usage.KINDS
            if kind == "anchor":
                assert pattern.startswith("#") and re.search(r"[a-z]", pattern)
    for needed in ("port 8443", "host wspap.okx.com", "host ws.okx.com", "demo header x-simulated-trading",
                   "WebSocket channel candle1H", "POST /api/v5/trade/order", "POST /api/v5/trade/order-algo", "IP binding of keys"):
        assert needed in labels


def _code_files():
    """The code that talks to OKX (``app/ops`` only names hosts and paths to look for in the changelog)."""
    for folder in ("app", "research", "scripts"):
        yield from (p for p in (ROOT / folder).rglob("*.py") if "__pycache__" not in p.parts and "ops" not in p.relative_to(ROOT).parts[:2])


def test_the_watch_list_covers_every_okx_path_and_host_in_the_code():
    """Whoever adds an OKX endpoint or host to the code must add it to app/ops/okx_usage.py too."""
    paths, hosts = set(), set()
    for path in _code_files():
        text = path.read_text(encoding="utf-8")
        paths |= set(re.findall(r"/api/v5/[a-z0-9\-]+(?:/[a-z0-9\-]+)+(?![/\w\-])", text))  # a prefix ending in "/" is not an endpoint
        hosts |= set(re.findall(r"\b((?:[a-z0-9\-]+\.)+okx\.com)\b", text))
    assert {"/api/v5/market/candles", "/api/v5/trade/order"} <= paths  # the scan itself works
    assert paths <= okx_usage.used_rest_paths(), sorted(paths - okx_usage.used_rest_paths())
    assert hosts <= okx_usage.used_hosts(), sorted(hosts - okx_usage.used_hosts())
    assert {"candle1H", "orders", "liquidation-orders", "tickers", "trades", "books"} <= okx_usage.used_channels()


# -- the script ---------------------------------------------------------------------------------


def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("watch_okx_changelog_under_test", ROOT / "scripts" / "watch_okx_changelog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_previews_sends_and_reports(tmp_path, capsys):
    script = _script()
    page = FIXTURES / "changelog_v1.html"
    state = tmp_path / "state"
    assert script.main(["--from-file", str(page), "--state-dir", str(state)], env={}) == 0
    out = capsys.readouterr().out
    assert "preview: not sent, nothing saved" in out and "8443" in out and not state.exists()
    assert script.main(["--send", "--from-file", str(page), "--state-dir", str(state)], env={}) == 2  # no Telegram credentials
    assert not state.exists()
    assert script.main(["--send", "--from-file", str(page), "--state-dir", str(state)], env={"TELEGRAM_DRY_RUN": "1"}) == 0
    assert "Telegram dry run: formatted, not sent" in capsys.readouterr().out and (state / oc.STATE_FILE).exists()
    assert script.main(["--status", "--state-dir", str(state)], env={}) == 0
    assert "entries known 12" in capsys.readouterr().out
    missing = tmp_path / "missing.html"
    assert script.main(["--send", "--from-file", str(missing), "--state-dir", str(state)], env={"TELEGRAM_DRY_RUN": "1"}) == 2


def test_the_script_reports_a_failed_send_and_keeps_the_alert(tmp_path, monkeypatch, capsys):
    import app.notify.telegram as tg

    script = _script()
    monkeypatch.setattr(tg, "_requests_transport", lambda url, payload: (502, "bad gateway"))
    env = {"TELEGRAM_BOT_TOKEN": "123:not-a-real-token", "TELEGRAM_CHAT_ID": "42"}
    page = str(FIXTURES / "changelog_v1.html")
    assert script.main(["--send", "--from-file", page, "--state-dir", str(tmp_path)], env=env) == 0  # the check itself worked
    out = capsys.readouterr().out
    assert "NOT sent (failed" in out and "kept for the next check" in out and "not-a-real-token" not in out
    assert len(json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))["pending"]) == 3
    assert script.main(["--send", "--from-file", page, "--state-dir", str(tmp_path)], env={"TELEGRAM_DRY_RUN": "1"}) == 0
    assert "kept for the next real send" in capsys.readouterr().out
    assert len(json.loads((tmp_path / oc.STATE_FILE).read_text(encoding="utf-8"))["pending"]) == 3


def test_the_script_keeps_its_state_where_the_digest_reads_it(tmp_path):
    script = _script()
    ops = tmp_path / "ops"
    page = str(FIXTURES / "changelog_v1.html")
    assert script.main(["--send", "--from-file", page], env={"TELEGRAM_DRY_RUN": "1", "OPS_DIR": str(ops)}) == 0
    assert (ops / "okx_changelog" / oc.STATE_FILE).exists()
    other = tmp_path / "explicit"
    assert script.main(["--send", "--from-file", page], env={"TELEGRAM_DRY_RUN": "1", "OPS_DIR": str(ops),
                                                             oc.STATE_DIR_ENV: str(other)}) == 0
    assert (other / oc.STATE_FILE).exists()


def test_the_script_exits_1_when_the_page_cannot_be_read(tmp_path, monkeypatch, capsys):
    script = _script()

    def down(url):
        raise ChangelogError("fetch_failed", "ConnectionError")

    monkeypatch.setattr(script, "fetch_changelog", down)
    assert script.main(["--send", "--state-dir", str(tmp_path)], env={"TELEGRAM_DRY_RUN": "1"}) == 1
    assert "FAILED (fetch_failed)" in capsys.readouterr().err
