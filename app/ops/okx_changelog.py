"""Daily watcher of OKX's public API changelog (plan row R6; master plan sections 5.4 and 9).

OKX announces API changes on one public page, https://www.okx.com/docs-v5/log_en/.
The shutdown of WebSocket port 8443 on October 31, 2026 was announced there; a
change like that can blind the system if nobody reads the page. This module:

1. fetches the page (one unauthenticated GET; the host is pinned, redirects are
   refused, the size is capped);
2. splits it into entries: the page is a list of ``<h1 id='YYYY-MM-DD'>`` date
   groups (and one "Upcoming Changes" group), each holding ``<h2>`` entries (or
   ``<h3>`` entries, or plain text in older groups);
3. remembers every entry it has seen (its heading id and a hash of its text), so
   a new entry, or an entry OKX edits later (for example a moved date), is
   noticed once;
4. flags the new or edited entries whose text mentions something this repository
   uses (``app/ops/okx_usage.py``: hosts, ports, REST paths, WebSocket channels,
   authentication) and words the alert for Telegram.

The first run records the whole page as a baseline and flags only the upcoming
changes and the entries of the last ``baseline_days`` days, so it does not send
five years of history. A page that cannot be read, or that suddenly holds far
fewer entries than the last good one (a changed layout, a block page), counts as
a failed check: the state keeps the last good entries and the failure is counted
until it is reported.

Observability only: no keys, no API call, no order path; nothing in the trading
runtime reads its output. A flag is a prompt for a human (or an agent session)
to read the entry; nothing changes automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from app.news.sanitize import sanitize_text
from app.ops.okx_usage import IMPACT_RE, WATCH_ITEMS, WatchItem

CHANGELOG_URL = "https://www.okx.com/docs-v5/log_en/"
CHANGELOG_HOST = "www.okx.com"
USER_AGENT = "ai-trading-model-ops/1.0 (reads the public OKX API changelog once a day)"
FETCH_TIMEOUT_SECONDS = 30.0
MAX_PAGE_BYTES = 8_000_000  # the page was 1.2 MB in October 2026

STATE_VERSION = 1
STATE_FILE = "changelog_state.json"
LOG_FILE = "changelog.jsonl"
DEFAULT_STATE_DIR = "logs/ops/okx_changelog"
STATE_DIR_ENV = "OKX_CHANGELOG_STATE_DIR"
DEFAULT_BASELINE_DAYS = 30
FAILURE_ALERT_AFTER = 3  # failed checks in a row before one Telegram alert
MIN_ENTRY_RATIO = 0.5  # fewer than half the entries of the last good page = broken page, not deleted history
MASS_CHANGE_MIN = 20  # more new or edited entries than this, and more than half the page, in one check:
MASS_CHANGE_SHARE = 0.5  # a new layout or new ids, not news; only the upcoming changes are flagged
PENDING_KEEP_DAYS = 7  # an alert that could not be delivered is re-sent with the next checks for this long
RECENT_KEEP = 50  # flagged entries remembered in the state for the digest
MAX_ALERT_ENTRIES = 10
TITLE_MAX_CHARS = 160

UPCOMING_GROUP = "upcoming-changes"
_DATE_ID = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LAST_UPDATE = re.compile(r"Last update:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
_WS = re.compile(r"\s+")
_BREAK_TAGS = frozenset({"p", "br", "li", "ul", "ol", "tr", "td", "th", "table", "blockquote", "div", "h4", "h5", "h6", "pre"})


class ChangelogError(RuntimeError):
    """The changelog could not be fetched or read; ``code`` is a short, stable reason."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# -- fetching --------------------------------------------------------------------------------


def check_url(url: str) -> str:
    """Only ``https://www.okx.com/docs-v5/...`` may be read (fail closed)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != CHANGELOG_HOST or parts.port not in (None, 443):
        raise ChangelogError("url_refused", f"only https://{CHANGELOG_HOST} may be read")
    if not parts.path.startswith("/docs-v5/") or parts.username or parts.password or parts.query:
        raise ChangelogError("url_refused", "only the public /docs-v5/ pages may be read")
    return url


def fetch_changelog(
    url: str = CHANGELOG_URL,
    *,
    session: Any = None,
    timeout: float = FETCH_TIMEOUT_SECONDS,
    max_bytes: int = MAX_PAGE_BYTES,
) -> str:
    """GET the public changelog page; no credentials, no cookies kept, no redirects followed."""
    check_url(url)
    import requests  # local import: tests inject a session and never need the network

    own = session is None
    http = session if session is not None else requests.Session()
    try:
        try:
            resp = http.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Language": "en"},
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise ChangelogError("fetch_failed", type(exc).__name__) from None
        try:
            status = int(resp.status_code)
            if 300 <= status < 400:
                raise ChangelogError("redirected", f"HTTP {status}: the page moved; check {url} by hand")
            if status != 200:
                raise ChangelogError("http_status", f"HTTP {status}")
            chunks: List[bytes] = []
            size = 0
            try:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise ChangelogError("too_large", f"more than {max_bytes} bytes")
                    chunks.append(chunk)
            except requests.RequestException as exc:
                raise ChangelogError("fetch_failed", type(exc).__name__) from None
        finally:
            resp.close()
    finally:
        if own:
            http.close()
    return b"".join(chunks).decode("utf-8", errors="replace")


# -- parsing ---------------------------------------------------------------------------------


@dataclass
class _Section:
    level: int
    anchor: Optional[str]
    title_parts: List[str] = field(default_factory=list)
    text_parts: List[str] = field(default_factory=list)
    codes: List[str] = field(default_factory=list)
    hrefs: List[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return _clean("".join(self.title_parts))

    @property
    def body(self) -> str:
        return _clean("".join(self.text_parts))


def _clean(text: str) -> str:
    """Normalized text: compatibility forms folded (NFKC) and invisible format characters removed, so a
    zero-width space inside "8443" or a bidi control cannot hide a term from the watch list."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Cc") or ch in "\t\n\r")
    return _WS.sub(" ", text).strip()


class _ChangelogParser(HTMLParser):
    """Collects h1/h2/h3 sections of the page's content column: prose, inline code tokens, links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: List[_Section] = []
        self._skip = 0  # inside <script>/<style>
        self._pre = 0  # inside <pre> (code examples: not prose)
        self._code: Optional[List[str]] = None  # an inline <code> being read
        self._heading: Optional[_Section] = None  # a heading being read
        self._div_depth = 0
        self._content_depth: Optional[int] = None
        self._done = False

    def _current(self) -> Optional[_Section]:
        return self.sections[-1] if self.sections and not self._done else None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if self._done:
            return
        a = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag == "div":
            self._div_depth += 1
            if self._content_depth is None and "content" in a.get("class", "").split():
                self._content_depth = self._div_depth
            return
        if tag in ("h1", "h2", "h3"):
            level = int(tag[1])
            if level > 1 and not self.sections:
                return  # headings before the first date group belong to the page chrome
            section = _Section(level=level, anchor=a.get("id") or None)
            self.sections.append(section)
            self._heading = section
            return
        current = self._current()
        if current is None:
            return
        if tag == "pre":
            self._pre += 1
        elif tag == "code" and not self._pre:
            self._code = []
        elif tag == "a" and a.get("href"):
            current.hrefs.append(a["href"])
        if tag in _BREAK_TAGS:
            current.text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._done:
            return
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "div":
            if self._content_depth is not None and self._div_depth == self._content_depth:
                self._done = True  # the content column ended; anything after it is page chrome
            self._div_depth = max(0, self._div_depth - 1)
            return
        if tag in ("h1", "h2", "h3"):
            self._heading = None
            return
        current = self._current()
        if current is None:
            return
        if tag == "pre":
            self._pre = max(0, self._pre - 1)
        elif tag == "code" and self._code is not None:
            token = _clean("".join(self._code))
            if token:
                current.codes.append(token)
            self._code = None
        if tag in _BREAK_TAGS:
            current.text_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._done or self._skip or not self.sections:
            return
        if self._code is not None:
            self._code.append(data)
        if self._heading is not None:
            self._heading.title_parts.append(data)
            return
        if self._pre:
            return  # code examples are not prose
        self.sections[-1].text_parts.append(data)


@dataclass(frozen=True)
class ChangelogEntry:
    """One entry of the page: its heading id (stable), group, title, date and content."""

    entry_id: str
    group: str
    title: str
    date: Optional[str]
    upcoming: bool
    text: str
    codes: Tuple[str, ...]
    hrefs: Tuple[str, ...]

    @property
    def body_sha(self) -> str:
        blob = json.dumps([self.title, self.text, list(self.codes), list(self.hrefs)], ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @property
    def url(self) -> str:
        return f"{CHANGELOG_URL}#{self.entry_id}" if _SAFE_ID.match(self.entry_id) else CHANGELOG_URL


_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9\-]{0,200}$")


def _first_words(text: str, limit: int = 100) -> str:
    """The first sentence of ``text``, cut at a word boundary within ``limit`` characters."""
    sentence = re.split(r"(?<=[.!?:])\s", text, maxsplit=1)[0].strip()
    if len(sentence) <= limit:
        return sentence
    cut = sentence[:limit].rsplit(" ", 1)[0]
    return (cut or sentence[:limit]) + " ..."


def _last_update(text: str) -> Optional[str]:
    m = _LAST_UPDATE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def _entry(head: _Section, parts: Sequence[_Section], group: _Section, entry_id: str, title: str) -> ChangelogEntry:
    texts = [title]
    for p in parts:
        if p is not head and p.title:
            texts.append(p.title)
        texts.append(p.body)
    text = _clean(" ".join(texts))
    group_id = group.anchor or _clean(group.title).lower()
    upcoming = group_id == UPCOMING_GROUP or group.title.strip().lower() == "upcoming changes"
    day = group_id if _DATE_ID.match(group_id) else (_last_update(text) if upcoming else None)
    codes = tuple(c for p in parts for c in p.codes)
    hrefs = tuple(h for p in parts for h in p.hrefs)
    return ChangelogEntry(entry_id=entry_id, group=group_id, title=title, date=day, upcoming=upcoming,
                          text=text, codes=codes, hrefs=hrefs)


def parse_changelog(html: str) -> List[ChangelogEntry]:
    """Every entry of the page, in page order (newest first). Never raises on odd HTML."""
    parser = _ChangelogParser()
    parser.feed(html)
    parser.close()
    groups: List[Tuple[_Section, List[_Section]]] = []
    for s in parser.sections:
        if s.level == 1:
            groups.append((s, []))
        elif groups:
            groups[-1][1].append(s)
    entries: List[ChangelogEntry] = []
    used: Dict[str, int] = {}

    def unique(base: str) -> str:
        n = used.get(base, 0) + 1
        used[base] = n
        return base if n == 1 else f"{base}~{n}"

    for h1, subs in groups:
        top = 2 if any(s.level == 2 for s in subs) else 3
        intro: List[_Section] = [h1]
        blocks: List[Tuple[_Section, List[_Section]]] = []
        for s in subs:
            if s.level == top:
                blocks.append((s, [s]))
            elif blocks:
                blocks[-1][1].append(s)
            else:
                intro.append(s)
        group_id = h1.anchor or _clean(h1.title).lower()
        intro_text = _clean(" ".join([p.title for p in intro[1:]] + [p.body for p in intro]))
        if intro_text or not blocks:
            # A group without sub-headings (older entries) is one entry: its first words are its title.
            title = f"{h1.title} (introduction)" if blocks else (_first_words(intro_text) or h1.title)
            entries.append(_entry(h1, intro, h1, unique(group_id), title))
        for head, parts in blocks:
            base = head.anchor or f"{group_id}-{hashlib.sha256(head.title.encode('utf-8')).hexdigest()[:12]}"
            entries.append(_entry(head, parts, h1, unique(base), head.title))
    return entries


# -- matching --------------------------------------------------------------------------------


def match_entry(entry: ChangelogEntry, items: Sequence[WatchItem] = WATCH_ITEMS) -> Tuple[str, ...]:
    """Labels of every watch item the entry mentions, in watch-list order."""
    hits: List[str] = []
    codes = set(entry.codes)
    for item in items:
        found = any(r.search(entry.text) for r in item.regexes("text"))
        found = found or any(t in codes for t in item.tokens())
        found = found or any(r.search(h) for r in item.regexes("anchor") for h in entry.hrefs)
        if found:
            hits.append(item.label)
    return tuple(hits)


_NEGATED = re.compile(r"\b(?:not|never|won't|isn't|aren't)(?:\s+(?:be|being|been))?(?:\s+(?:a|an|any))?\s*$", re.IGNORECASE)


def has_impact_wording(entry: ChangelogEntry) -> bool:
    """Breaking-change, deprecation or shutdown wording, unless negated ("will not be deprecated")."""
    for match in IMPACT_RE.finditer(entry.text):
        if not _NEGATED.search(entry.text[max(0, match.start() - 24):match.start()]):
            return True
    return False


# -- state -----------------------------------------------------------------------------------


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def empty_state() -> Dict[str, Any]:
    return {"version": STATE_VERSION, "url": CHANGELOG_URL, "created_at": None, "last_check_at": None, "last_ok_at": None,
            "last_error": None, "consecutive_failures": 0, "failure_alert_sent_at": None, "entry_count": 0,
            "entries": {}, "recent": [], "pending": []}


def load_state(state_dir: Path) -> Dict[str, Any]:
    """The saved state; a missing file is a first run. An unreadable one is set aside and starts a new baseline."""
    path = Path(state_dir) / STATE_FILE
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != STATE_VERSION or not isinstance(data.get("entries"), dict):
            raise ValueError("unknown state layout")
    except (OSError, ValueError):
        aside = path.with_name(f"{path.name}.unreadable-{datetime.now(tz=timezone.utc):%Y%m%dT%H%M%SZ}")
        try:
            os.replace(path, aside)
        except OSError:
            pass
        state = empty_state()
        state["last_error"] = "state_reset"
        return state
    merged = empty_state()
    merged.update(data)
    return merged


def save_state(state_dir: Path, state: Mapping[str, Any]) -> Path:
    path = Path(state_dir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def append_log(state_dir: Path, record: Mapping[str, Any]) -> None:
    path = Path(state_dir) / LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


# -- one check -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Flag:
    """A new or edited entry that mentions something this repository uses."""

    entry: ChangelogEntry
    change: str  # "new" | "updated"
    matches: Tuple[str, ...]
    impact: bool

    def to_record(self, at: datetime, notified: bool) -> Dict[str, Any]:
        return {"at": _iso(at), "entry_id": self.entry.entry_id, "change": self.change, "date": self.entry.date,
                "upcoming": self.entry.upcoming, "title": safe_title(self.entry.title), "matches": list(self.matches),
                "impact": self.impact, "url": self.entry.url, "notified": notified}


@dataclass
class CheckResult:
    ok: bool
    first_run: bool = False
    mass_change: bool = False
    entries: int = 0
    new: int = 0
    updated: int = 0
    flags: List[Flag] = field(default_factory=list)
    resent: int = 0  # earlier alerts that could not be delivered, sent again with this check
    delivered: bool = False
    error: Optional[str] = None
    failure_alert_due: bool = False
    consecutive_failures: int = 0


def safe_title(title: str) -> str:
    """A title fit for a log line and a Telegram message: zero-width/bidi/control characters removed, length capped."""
    return sanitize_text(title or "", max_chars=TITLE_MAX_CHARS).text or "(untitled)"


def _eligible_on_first_run(entry: ChangelogEntry, today: date, baseline_days: int) -> bool:
    if entry.upcoming:
        return True
    if not entry.date:
        return False
    try:
        return date.fromisoformat(entry.date) >= today - timedelta(days=baseline_days)
    except ValueError:
        return False


def evaluate(
    entries: Sequence[ChangelogEntry],
    state: Dict[str, Any],
    now: datetime,
    *,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    items: Sequence[WatchItem] = WATCH_ITEMS,
) -> CheckResult:
    """Compare a freshly parsed page with the state and update the state in place.

    A page without entries, or with fewer than ``MIN_ENTRY_RATIO`` of the last good
    page's entries, is a failed check: the known entries stay untouched. A page where
    most entries look new or edited at once (new ids or a new layout, not news) becomes
    the new baseline; only its upcoming changes are flagged, and the alert says so.
    """
    known: Dict[str, Any] = state["entries"]
    first_run = state.get("last_ok_at") is None or not known
    last_count = int(state.get("entry_count") or 0)
    if not entries:
        return record_failure(state, now, "no_entries")
    if last_count and len(entries) < MIN_ENTRY_RATIO * last_count:
        return record_failure(state, now, "page_shrank")
    result = CheckResult(ok=True, first_run=first_run, entries=len(entries))
    stamp = _iso(now)
    changes = []
    for entry in entries:
        old = known.get(entry.entry_id)
        sha = entry.body_sha
        if old is not None and old.get("sha") == sha:
            continue
        changes.append((entry, sha, old))
    result.new = sum(1 for _, _, old in changes if old is None)
    result.updated = len(changes) - result.new
    result.mass_change = not first_run and len(changes) > max(MASS_CHANGE_MIN, MASS_CHANGE_SHARE * len(entries))
    for entry, sha, old in changes:
        matches = match_entry(entry, items)
        known[entry.entry_id] = {"date": entry.date, "title": safe_title(entry.title), "sha": sha,
                                 "first_seen": (old or {}).get("first_seen", stamp), "last_changed": stamp,
                                 "matches": list(matches)}
        if not matches:
            continue
        if first_run and not _eligible_on_first_run(entry, now.date(), baseline_days):
            continue
        if result.mass_change and not entry.upcoming:
            continue
        result.flags.append(Flag(entry=entry, change="new" if old is None else "updated", matches=matches,
                                 impact=has_impact_wording(entry)))
    state["created_at"] = state.get("created_at") or stamp
    state["last_check_at"] = stamp
    state["last_ok_at"] = stamp
    state["last_error"] = None
    state["consecutive_failures"] = 0
    state["failure_alert_sent_at"] = None
    state["entry_count"] = len(entries)
    return result


def record_failure(state: Dict[str, Any], now: datetime, code: str) -> CheckResult:
    """Count one failed check; an alert is due once, after ``FAILURE_ALERT_AFTER`` failures in a row."""
    state["last_check_at"] = _iso(now)
    state["last_error"] = code
    state["consecutive_failures"] = int(state.get("consecutive_failures") or 0) + 1
    due = state["consecutive_failures"] >= FAILURE_ALERT_AFTER and not state.get("failure_alert_sent_at")
    return CheckResult(ok=False, error=code, failure_alert_due=due, consecutive_failures=state["consecutive_failures"])


def remember_flags(state: Dict[str, Any], flags: Iterable[Flag], now: datetime, notified: bool) -> None:
    recent = list(state.get("recent") or [])
    recent.extend(f.to_record(now, notified) for f in flags)
    state["recent"] = recent[-RECENT_KEEP:]


def _live_pending(state: Mapping[str, Any], now: datetime) -> List[Dict[str, Any]]:
    """Alerts that could not be delivered yet and are younger than ``PENDING_KEEP_DAYS``."""
    out = []
    for rec in state.get("pending") or []:
        at = _parse_at(rec.get("at")) if isinstance(rec, dict) else None
        if at is not None and now - at <= timedelta(days=PENDING_KEEP_DAYS):
            out.append(dict(rec))
    return out


def _parse_at(value: Any) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


# -- messages --------------------------------------------------------------------------------


def _when(rec: Mapping[str, Any]) -> str:
    if rec.get("upcoming"):
        return f"upcoming, last update {rec['date']}" if rec.get("date") else "upcoming"
    return rec.get("date") or "undated"


def render_alert(
    records: Sequence[Mapping[str, Any]],
    *,
    first_run: bool = False,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    mass_change: Optional[Tuple[int, int]] = None,
) -> str:
    """Plain-text Telegram message for flagged entries (``Flag.to_record`` dicts; no markup)."""
    resent = [r for r in records if r.get("resent")]
    entries = [r for r in records if r.get("change") != "bulk"]  # a re-sent bulk-change notice is not an entry
    if mass_change:
        lines = [f"OKX API changelog: the page changed in bulk ({mass_change[0]} of {mass_change[1]} entries look new or "
                 "edited: a new layout or new ids, not news). The watcher took it as its new baseline and lists only the "
                 f"upcoming changes that mention something this system uses ({len(entries)}). Skim the page by hand: "
                 f"{CHANGELOG_URL}"]
    elif not entries:
        lines = ["OKX API changelog: a notice that could not be delivered earlier, sent again"]
    else:
        lines = [f"OKX API changelog: {len(entries)} {'entry mentions' if len(entries) == 1 else 'entries mention'} "
                 "something this system uses"
                 + (f" (first check: the upcoming changes and the last {baseline_days} days only)" if first_run else "")]
    if resent and entries:
        lines.append(f"{len(resent)} of them could not be delivered earlier and are sent again.")
    lines.append("")
    for rec in list(records)[:MAX_ALERT_ENTRIES]:
        lines.append(f"- [{_when(rec)}, {rec.get('change')}] {rec.get('title')}")
        matches = list(rec.get("matches") or [])
        shown = matches[:6]
        more = len(matches) - len(shown)
        if shown:
            lines.append("  mentions: " + "; ".join(shown) + (f"; and {more} more" if more > 0 else ""))
        if rec.get("impact"):
            lines.append("  wording: breaking change, deprecation or shutdown")
        lines.append(f"  {rec.get('url')}")
    if len(records) > MAX_ALERT_ENTRIES:
        lines.append(f"... and {len(records) - MAX_ALERT_ENTRIES} more in logs/ops/okx_changelog/{LOG_FILE}")
    lines += ["", "Nothing changes by itself: read each entry and decide whether the system needs a change."]
    return "\n".join(lines)


def render_failure_alert(result: CheckResult, state: Mapping[str, Any]) -> str:
    return (
        f"OKX changelog watcher: {result.consecutive_failures} failed checks in a row (last: {result.error}). "
        f"Last good check: {state.get('last_ok_at') or 'never'}. Until it reads the page again it cannot warn about "
        f"API changes. Check {CHANGELOG_URL} by hand and see docs/runbooks/OPS_DIGEST.md."
    )


def _deliver(notify: Optional[Callable[[str], bool]], text: str) -> bool:
    if notify is None:
        return False
    try:
        return bool(notify(text))
    except Exception:  # a notification problem must never lose the check's state
        return False


def run_check(
    state_dir: Path,
    now: datetime,
    *,
    fetch: Callable[[], str],
    notify: Optional[Callable[[str], bool]] = None,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    persist: bool = True,
) -> CheckResult:
    """Fetch, parse, compare, log, alert, save. ``notify(text) -> delivered`` may be None (no alerts).

    ``notify`` must return True only when the message really went out (a Telegram dry run
    is not a delivery): alerts that were not delivered stay pending and are sent again with
    the next checks for ``PENDING_KEEP_DAYS`` days.

    ``persist=False`` is a preview: the same check and messages, but the state and the log
    are left exactly as they were (a manual look must not use up the timer's alerts).
    """
    state = load_state(state_dir) if persist else _read_state_for_preview(state_dir)
    try:
        html = fetch()
        entries = parse_changelog(html)
    except ChangelogError as exc:
        result = record_failure(state, now, exc.code)
    except Exception as exc:  # a parser or decoder surprise is a failed check, never a crash
        result = record_failure(state, now, f"unexpected_error:{type(exc).__name__}")
    else:
        result = evaluate(entries, state, now, baseline_days=baseline_days)
    log = (lambda record: append_log(state_dir, record)) if persist else (lambda record: None)
    if result.ok:
        fresh = [f.to_record(now, False) for f in result.flags]
        fresh_ids = {r["entry_id"] for r in fresh}  # a fresh alert about an entry replaces an older undelivered one
        carried = [{**r, "resent": True} for r in _live_pending(state, now) if r.get("entry_id") not in fresh_ids]
        result.resent = len(carried)
        to_send = fresh + carried
        delivered = bool(to_send or result.mass_change) and _deliver(notify, render_alert(
            to_send, first_run=result.first_run, baseline_days=baseline_days,
            mass_change=(result.new + result.updated, result.entries) if result.mass_change else None))
        result.delivered = delivered
        remember_flags(state, result.flags, now, delivered)
        if result.mass_change and not delivered:  # the bulk notice itself waits for delivery too
            to_send = to_send + [_bulk_notice(now, result.new + result.updated, result.entries)]
        _settle_pending(state, to_send, delivered)
        for flag in result.flags:
            log({"kind": "flag", **flag.to_record(now, delivered)})
        log({"kind": "check", "at": _iso(now), "ok": True, "first_run": result.first_run, "mass_change": result.mass_change,
             "entries": result.entries, "new": result.new, "updated": result.updated, "flagged": len(result.flags),
             "resent": result.resent, "notified": delivered})
    else:
        sent = result.failure_alert_due and _deliver(notify, render_failure_alert(result, state))
        if sent:
            state["failure_alert_sent_at"] = _iso(now)
        # Telegram does not depend on OKX: alerts still waiting are sent even when the page cannot be read.
        carried = [{**r, "resent": True} for r in _live_pending(state, now)]
        result.resent = len(carried)
        result.delivered = bool(carried) and _deliver(notify, render_alert(carried))
        _settle_pending(state, carried, result.delivered)
        log({"kind": "check", "at": _iso(now), "ok": False, "error": result.error,
             "consecutive_failures": result.consecutive_failures, "failure_alert_sent": sent,
             "resent": result.resent, "notified": result.delivered})
    if persist:
        save_state(state_dir, state)
    return result


def _bulk_notice(now: datetime, changed: int, total: int) -> Dict[str, Any]:
    return {"at": _iso(now), "entry_id": "__bulk_change__", "change": "bulk", "date": now.date().isoformat(),
            "upcoming": False, "title": f"The changelog page changed in bulk ({changed} of {total} entries); skim it by hand",
            "matches": [], "impact": False, "url": CHANGELOG_URL, "notified": False}


def _settle_pending(state: Dict[str, Any], records: Sequence[Mapping[str, Any]], delivered: bool) -> None:
    """After a send attempt: delivered alerts leave the queue (and count as notified), the others wait."""
    if delivered:
        sent_ids = {r.get("entry_id") for r in records}
        for rec in state.get("recent") or []:
            if rec.get("entry_id") in sent_ids:
                rec["notified"] = True
        state["pending"] = []
    else:
        state["pending"] = [{k: v for k, v in r.items() if k != "resent"} for r in records]


def _read_state_for_preview(state_dir: Path) -> Dict[str, Any]:
    """The saved state for a preview, without the side effects of ``load_state`` (nothing is moved aside)."""
    try:
        data = json.loads((Path(state_dir) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION or not isinstance(data.get("entries"), dict):
        return empty_state()
    merged = empty_state()
    merged.update(data)
    return merged


def status_summary(state: Mapping[str, Any], now: datetime, *, days: int = 7) -> Dict[str, Any]:
    """The facts the daily digest shows: last checks, failures, the entries flagged in the last ``days`` days,
    and the alerts the watcher could not deliver yet."""
    since = now - timedelta(days=days)
    recent = []
    for rec in state.get("recent") or []:
        at = _parse_at(rec.get("at")) if isinstance(rec, dict) else None
        if at is not None and at >= since:
            recent.append(rec)
    return {"last_check_at": state.get("last_check_at"), "last_ok_at": state.get("last_ok_at"),
            "last_error": state.get("last_error"), "consecutive_failures": int(state.get("consecutive_failures") or 0),
            "entries_known": len(state.get("entries") or {}), "flagged_recent": recent,
            "pending": _live_pending(state, now), "days": days}
