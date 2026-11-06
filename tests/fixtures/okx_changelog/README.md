# OKX changelog page fixtures (plan row R6)

Used by `tests/test_okx_changelog.py`, `tests/test_ops_digest.py` and
`python scripts/ops_digest.py --dry-run`. They copy the **structure** of OKX's
public API changelog (https://www.okx.com/docs-v5/log_en/, checked on 2026-10-22)
with **invented text**; nothing here is OKX's wording or a real announcement.

The real page, as the parser relies on it: a `<div class="content">` column holding
`<h1 id='YYYY-MM-DD'>` date groups (newest first) and one `<h1 id='upcoming-changes'>`
group; inside a group, `<h2 id='...'>` entries with `<h3>`/`<h4>` sub-sections, or (in
some groups) `<h3>` entries, or (in older groups) plain lists; endpoints linked as
`/docs-v5/en/#<anchor>`; code examples in `<pre>`; "Last update: Month D, YYYY" under
each upcoming change.

| File | What it is |
|---|---|
| `changelog_v1.html` | 12 entries: an upcoming port-8443 shutdown (an h3 inside it), an upcoming entry whose only mentions of `orders`, `8443` and `www.okx.com` are inside a `<pre>` example (must not flag), dated h2 entries (orders channel; a new REST domain naming our hosts; an unrelated instruments-channel change), a group with text before its first h2, an h2 whose id and title carry zero-width and bidi characters and an instruction-like sentence (data only), an old order-book entry, an h3-only group, a date heading that appears twice, a plain 2021 group, and decoys: a heading inside `<script>` and one after the content column |
| `changelog_v2.html` | The same page a week later: the port-8443 entry edited (new "Last update", a moved date), a new upcoming entry on API-key IP binding (error 50110), a new `candle1H` entry and a new unrelated entry |
