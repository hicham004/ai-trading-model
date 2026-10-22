# The Federal Reserve's FOMC calendar, as published (plan row R7)

`federal_reserve_fomc.json` is the Federal Reserve's own FOMC meeting calendar
for 2020–2027, read from its website on 2026-10-22, one calendar entry per line.
`tests/test_fomc_calendar.py` checks the built-in calendar of the S0 no-trade
filter (`research/events.py`) against it, so a mistyped or missing date fails a
test instead of silently moving an event window. Research data only.

Sources (the file records each page's own "Last Update" date, which identifies
the version read; a hash of the page would not, because the Fed's site adds a
token that changes on every download):

- <https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm> — 2021–2027
  (last updated 2026-10-07);
- <https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm> — 2020
  (last updated 2026-01-16);
- the statement page of every decision so far (55, from 2020-01-29 to
  2026-09-16) for the release time printed on it: 2:00 p.m. New York time for
  every scheduled meeting (38 in daylight time, EDT, and 15 in winter, EST),
  10:00 a.m. EST on March 3, 2020 and 5:00 p.m. EDT on Sunday March 15, 2020 for
  the two unscheduled cuts.

Each entry keeps the text the Fed printed (`as_published`), its kind
(`scheduled`, `unscheduled`, `cancelled`, `notation vote`), the meeting's first
and last day, and `release_day`: the day of the press release the calendar links
to (for a meeting, its policy statement; empty for a meeting still ahead). A
decision day is a meeting's statement day: every scheduled meeting plus the two
unscheduled meetings of March 2020 (the March 2 meeting's statement came out on
March 3). The cancelled March 17–18, 2020 meeting and the notation votes (March
19, 23 and 31 and August 27, 2020; August 22, 2025 — none of them set rates) are
not meetings, so they are not decision days; the closest call is March 23, 2020,
an FOMC statement at 8:00 a.m. EDT that started unlimited bond buying with rates
unchanged. The Fed's note on the page: each date is tentative until it
is confirmed at the meeting before it; a two-day meeting is scheduled for
January 25–26, 2028.

## Refreshing it (for example when the Fed publishes the 2028 dates)

Download the pages into a new, empty folder (they are untrusted data), then run
the parser on them from the repository with `python -I`. It reads local files
only and writes the JSON. The statement pages are the ones the calendar pages
link to; the parser keeps the policy statements and leaves the other press
releases (notation votes) out, and it stops with the address of any statement
that is missing:

```bash
DL=$(mktemp -d) && mkdir "$DL/statements"
curl -sSL -o "$DL/fomccalendars.htm" https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
curl -sSL -o "$DL/fomchistorical2020.htm" https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm
for f in $(grep -oh 'monetary[0-9]\{8\}a\.htm' "$DL/fomccalendars.htm" "$DL/fomchistorical2020.htm" | sort -u); do
  curl -sSL -o "$DL/statements/$f" "https://www.federalreserve.gov/newsevents/pressreleases/$f"; sleep 1
done
.venv/bin/python -I tests/fixtures/fomc_calendar/make_fixture.py \
  --calendar "$DL/fomccalendars.htm" --historical "$DL/fomchistorical2020.htm" \
  --release-dir "$DL/statements" \
  --retrieved "$(date -u +%F)" --out tests/fixtures/fomc_calendar/federal_reserve_fomc.json
```

The calendar page lists the current year, the five years before it and the next
year (on 2026-10-22: 2021–2027). Once 2021 moves to its own historical page,
download `fomchistorical2021.htm` as well, add it to the `grep` line and pass it
with a second `--historical`. Then add the new dates to `FOMC_DECISION_DAYS` in
`research/events.py`, update the values `tests/test_fomc_calendar.py` pins (they
record what was checked: the retrieval date, the source pages and their years,
the counts of meetings, statements and release hours, the days left out, the new
year's dates, the last date and the meetings still ahead) and run
`pytest tests/test_fomc_calendar.py`. A running paper fleet picks up the new
dates at its next restart (`docs/runbooks/PAPER_FLEET.md`).
