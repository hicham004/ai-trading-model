"""Rebuild ``federal_reserve_fomc.json`` from the Federal Reserve's own pages (offline; standard library only).

Plan row R7 checked the built-in FOMC calendar (``research/events.py``) against the Fed's published meeting
calendar. This script turns the downloaded pages into the recorded fixture that ``tests/test_fomc_calendar.py``
compares the built-in calendar with. It reads local files only (download them first, see ``README.md``) and
writes one JSON file; it never touches the network. Run it with ``python -I`` from outside the download folder.

    python -I make_fixture.py --calendar DL/fomccalendars.htm --historical DL/fomchistorical2020.htm \
        --release-dir DL/statements --retrieved 2026-10-22 --out federal_reserve_fomc.json

``--release-dir`` holds the statement pages (``monetaryYYYYMMDDa.htm``): the release time printed on every
policy statement released so far is recorded, and a missing one stops the script with its address.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date, datetime
from pathlib import Path

BASE = "https://www.federalreserve.gov"
CALENDAR_URL = f"{BASE}/monetarypolicy/fomccalendars.htm"
HISTORICAL_URL = f"{BASE}/monetarypolicy/fomchistorical{{year}}.htm"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def _month(token: str) -> int:
    for i, name in enumerate(MONTHS, start=1):
        if token == name or token == name[:3]:
            return i
    raise ValueError(f"unknown month {token!r}")


def meeting_days(year: int, month_label: str, day_text: str) -> tuple[date, date]:
    """First and last day of a meeting: ``January`` + ``27-28*``, ``Apr/May`` + ``30-1``, ``August`` + ``22 (notation vote)``."""
    months = [_month(t) for t in month_label.split("/")]
    nums = [int(n) for n in re.findall(r"\d+", re.sub(r"\(.*?\)", "", day_text))]
    if len(nums) == 1 and len(months) == 1:
        return date(year, months[0], nums[0]), date(year, months[0], nums[0])
    if len(nums) != 2:
        raise ValueError(f"cannot read the days of {month_label!r} {day_text!r}")
    crosses = nums[1] < nums[0]
    if crosses != (len(months) == 2):
        raise ValueError(f"month label and days disagree: {month_label!r} {day_text!r}")
    return date(year, months[0], nums[0]), date(year, months[-1], nums[1])


def kind_of(note: str, *, is_meeting: bool = True) -> str:
    note = note.lower()
    if "notation vote" in note:
        return "notation vote"
    if "cancel" in note:
        return "cancelled"
    if "unscheduled" in note:
        return "unscheduled"
    if note or not is_meeting:
        raise ValueError(f"unknown kind of calendar entry: {note!r}")
    return "scheduled"


def release_day(block: str) -> str | None:
    """The day of the press release (for a meeting: its policy statement) linked from one calendar entry."""
    days = sorted({f"{y}-{m}-{d}" for y, m, d in re.findall(r"/newsevents/pressreleases/monetary(\d{4})(\d{2})(\d{2})a\.htm", block)})
    if len(days) > 1:
        raise ValueError(f"one calendar entry links several releases: {days}")
    return days[0] if days else None


def last_update(text: str) -> str:
    m = re.search(r"Last Update:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if not m:
        raise ValueError("no 'Last Update' date on the page")
    return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()


def parse_calendar(text: str) -> list[dict]:
    out: list[dict] = []
    heads = list(re.finditer(r'<h4><a id="\d+">(\d{4}) FOMC Meetings</a></h4>', text))
    if not heads:
        raise ValueError("no year panels on the calendar page")
    for k, head in enumerate(heads):
        year = int(head.group(1))
        panel = text[head.end(): heads[k + 1].start() if k + 1 < len(heads) else len(text)]
        rows = list(re.finditer(r'<div class="(?:fomc-meeting--shaded )?row fomc-meeting"', panel))
        if len(rows) != panel.count("fomc-meeting__date"):
            raise ValueError(f"{year}: meeting rows and date cells disagree")
        for j, row in enumerate(rows):
            block = panel[row.start(): rows[j + 1].start() if j + 1 < len(rows) else len(panel)]
            month = re.search(r"fomc-meeting__month[^>]*><strong>([^<]*)</strong>", block).group(1).strip()
            days = html.unescape(re.search(r"fomc-meeting__date[^>]*>([^<]*)<", block).group(1)).strip()
            note = re.search(r"\(([^)]*)\)", days)
            first, last = meeting_days(year, month, days)
            out.append({"year": year, "as_published": f"{month} {days}", "kind": kind_of(note.group(1) if note else ""),
                        "first_day": first.isoformat(), "last_day": last.isoformat(), "release_day": release_day(block),
                        "source": "calendar"})
    return out


def parse_historical(text: str, year: int) -> list[dict]:
    out: list[dict] = []
    heads = list(re.finditer(r'<h5 class="panel-heading[^"]*">([^<]*)</h5>', text))
    if not heads:
        raise ValueError(f"no entries on the {year} historical page")
    for k, head in enumerate(heads):
        title = html.unescape(head.group(1)).strip()
        m = re.fullmatch(r"([A-Za-z]+(?:/[A-Za-z]+)?) (\d+(?:-\d+)?)(?: \(([^)]*)\))?( Meeting)? - (\d{4})", title)
        if not m or int(m.group(5)) != year:
            raise ValueError(f"unexpected heading {title!r}")
        block = text[head.end(): heads[k + 1].start() if k + 1 < len(heads) else len(text)]
        first, last = meeting_days(year, m.group(1), m.group(2))
        out.append({"year": year, "as_published": title, "kind": kind_of(m.group(3) or "", is_meeting=bool(m.group(4))),
                    "first_day": first.isoformat(), "last_day": last.isoformat(), "release_day": release_day(block),
                    "source": f"historical_{year}"})
    return out


def parse_release_time(path: Path) -> dict:
    m = re.fullmatch(r"monetary(\d{4})(\d{2})(\d{2})a\.htm", path.name)
    if not m:
        raise ValueError(f"not a statement file name: {path.name}")
    day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    text = path.read_text(encoding="utf-8", errors="replace")
    dated = re.search(r'<p class="article__time">\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*</p>', text)
    if not dated or datetime.strptime(dated.group(1), "%B %d, %Y").date().isoformat() != day:
        raise ValueError(f"{path.name}: the page is not dated {day}")
    rt = re.search(r'<p class="releaseTime">\s*(For release at [^<]*?)\s*<', text)
    if not rt:
        raise ValueError(f"{path.name}: no release time")
    return {"day": day, "as_published": " ".join(rt.group(1).split()), "url": f"{BASE}/newsevents/pressreleases/{path.name}"}


def _source(url: str, text: str, years: list[int]) -> dict:
    # The Fed's own "Last Update" date identifies the version read; a hash of the page would not, because the site
    # adds a token that changes on every download.
    return {"url": url, "years": years, "last_update": last_update(text)}


def build(calendar: Path, historical: list[Path], releases: list[Path], retrieved: str) -> dict:
    """``historical``: saved ``fomchistoricalYYYY.htm`` pages for the years the calendar page no longer shows."""
    cal_text = calendar.read_text(encoding="utf-8", errors="replace")
    entries = parse_calendar(cal_text)
    sources = {"calendar": _source(CALENDAR_URL, cal_text, sorted({e["year"] for e in entries}))}
    for path in sorted(historical, key=lambda p: p.name):
        m = re.fullmatch(r"fomchistorical(\d{4})\.htm", path.name)
        if not m:
            raise ValueError(f"not a historical page file name: {path.name}")
        year = int(m.group(1))
        if any(e["year"] == year for e in entries):
            raise ValueError(f"{year} is on the calendar page and on a historical page")
        text = path.read_text(encoding="utf-8", errors="replace")
        entries += parse_historical(text, year)
        sources[f"historical_{year}"] = _source(HISTORICAL_URL.format(year=year), text, [year])
    entries.sort(key=lambda e: (e["first_day"], e["last_day"]))
    notes = [" ".join(html.unescape(n).split()) for n in re.findall(r"<p>(Note: [^<]*)</p>", cal_text)]
    # The release time printed on every policy statement so far; other press releases (notation votes) are left out.
    statements = {e["release_day"] for e in entries if e["kind"] in ("scheduled", "unscheduled") and e["release_day"]}
    times = {r["day"]: r for r in map(parse_release_time, releases) if r["day"] in statements}
    missing = sorted(statements - set(times))
    if releases and missing:
        raise ValueError("statement pages missing: " + " ".join(f"{BASE}/newsevents/pressreleases/monetary{d.replace('-', '')}a.htm"
                                                                for d in missing))
    return {
        "about": ("The Federal Reserve's published FOMC meeting calendar as read from its website, recorded for "
                  "tests/test_fomc_calendar.py (plan row R7). Research data only; made by make_fixture.py."),
        "retrieved": retrieved,
        "sources": sources,
        "page_notes": notes,
        "entries": entries,
        "release_times": [times[d] for d in sorted(times)],
    }


def dumps(data: dict) -> str:
    """JSON with one calendar entry (or source, or release time) per line, so the file reads like the Fed's page."""
    lines = ["{"]
    for i, (key, value) in enumerate(data.items()):
        end = "," if i < len(data) - 1 else ""
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            lines.append(f" {json.dumps(key)}: [")
            lines += [f"  {json.dumps(v, ensure_ascii=False)}{',' if j < len(value) - 1 else ''}" for j, v in enumerate(value)]
            lines.append(f" ]{end}")
        elif isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
            lines.append(f" {json.dumps(key)}: {{")
            lines += [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}{',' if j < len(value) - 1 else ''}"
                      for j, (k, v) in enumerate(value.items())]
            lines.append(f" }}{end}")
        else:
            lines.append(f" {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{end}")
    return "\n".join(lines + ["}"]) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--calendar", type=Path, required=True, help="saved copy of fomccalendars.htm")
    ap.add_argument("--historical", type=Path, action="append", default=[],
                    help="saved copy of fomchistoricalYYYY.htm for a year the calendar page no longer shows (repeatable)")
    ap.add_argument("--release", type=Path, action="append", default=[], help="saved statement page monetaryYYYYMMDDa.htm (repeatable)")
    ap.add_argument("--release-dir", type=Path, help="a folder of saved statement pages monetaryYYYYMMDDa.htm")
    ap.add_argument("--retrieved", required=True, help="the day the pages were downloaded (YYYY-MM-DD)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    releases = list(args.release) + (sorted(args.release_dir.glob("monetary*a.htm")) if args.release_dir else [])
    data = build(args.calendar, args.historical, releases, date.fromisoformat(args.retrieved).isoformat())
    text = dumps(data)
    if json.loads(text) != data:
        raise AssertionError("the line-per-entry JSON does not read back as the same data")
    args.out.write_text(text, encoding="utf-8")
    kinds: dict[str, int] = {}
    for e in data["entries"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"{len(data['entries'])} entries {kinds}, {len(data['release_times'])} statement release times "
          f"({len(releases) - len(data['release_times'])} other pages left out) -> {args.out}")


if __name__ == "__main__":
    main()
