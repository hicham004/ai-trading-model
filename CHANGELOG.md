# Changelog

All notable changes to this repository. Dates are UTC. Nothing in this file
authorizes a phase, live trading, or a safety-core change; see
`PROJECT_RULES.md` and `CLAUDE.md`.

## Unreleased — R24: a named cost profile for future BTC-USDT and ETH-USDT studies (plan row R24, 2026-11-06)

Research code, tests and docs only (`research/`, `scripts/run_research_v1c.py`, `tests/`, `docs/`): nothing under `app/`, `config/` or
`migrations/` changed, no study was run and no results file changed; the engine's default cost, every finished study, the paper fleet's
33 accounts (fingerprints pinned) and its own fill costs are unchanged. The owner's decision of 2026-11-05 from the R22 fill-cost replay
(`docs/PLAN_STATUS.md`, section 2, "Decided — the owner, 2026-11-05 evening"). Simulation only; nothing here is an order or can place one.

### Added
- `research/engine.py`: the read-only registry `COST_PROFILES` — `gate` (0.10 % fee + 0.05 % slippage a side, 0.30 % a round trip:
  today's `Costs()`), `measured_btc_eth_2026_11` (0.10 % + 0.02 %, 0.24 %; BTC-USDT and ETH-USDT only, clips up to 20 K USDT) and
  `altcoin` (0.10 % + 0.15 %, 0.50 %) — with `Costs.named(name)`, the profile name every `Costs` carries (`profile`, left out of
  equality and hashing, so `Costs() == Costs.named("gate")`), `round_trip`, `label`, `covers(instrument)` and `to_dict()`. A `Costs`
  can never carry the name of a profile it does not charge.
- `scripts/run_research_v1c.py --cost-profile NAME` (default `gate`): the profile is charged, recorded in the results `meta`
  (`cost_profile`, `fee_rate`, `slippage_rate`, `round_trip`) and on every result (`costs`); `--fee` / `--slippage` alone still charge
  hand-given numbers (named after the profile they equal, else `custom`), and numbers that contradict a named profile are refused; the
  measured profile is refused on any other market; a run at a non-gate profile refuses to write over Sprint 2c's stored files (the
  default `--report`, `--json` and `--shortlist`, the paper fleet's shortlist among them), and so does a re-render of such a run.
- `research/replication.py`: `cost_profile_record` (what a pre-registration records: the name and the numbers),
  `preregistered_cost_profile` (`gate` when a pre-registration names none; stops on a bare name, an unknown name or changed numbers),
  `explain_cost_mismatches` (a fee / slippage difference from the stored Sprint 2c run is explained only when the pre-registration names
  a non-gate profile and the job charged exactly it) and `cost_profile_of`.
- `tests/test_research_cost_profiles.py`: the three profiles and `Costs()` unchanged; the breadth constants equal to the registry; the
  runner option recorded in `meta` and on every result, its refusals; the pre-registration record; the protocol checks of R18a, R19 and
  R20 explaining fee / slippage only when pre-registered and still stopping otherwise; the reproduction at the stored profile; the fleet's
  refusals.

### Changed
- `research/breadth_study.py`: `MAJOR_COSTS` / `ALTCOIN_COSTS` are the registry's `gate` / `altcoin` profiles (the same numbers, so its
  stored results and its committed pre-registration hold).
- `research/trader_policy_study.py` (`protocol_check_cell`), `research/round3.py` and `research/breadth_study.py` (`protocol_check_job`):
  an optional `cost_profile` (the pre-registered profile; default none = gate, as the three studies were registered, so their behaviour
  is unchanged), and every check records the job's `cost_profile`.
- `research/replication.py`, `reproduction_check`: a reproduction runs at the stored run's cost profile (the gate profile for every
  stored result); a result taken at another profile fails it.
- `research/paper_fleet/config.py`: the loader refuses, explicitly, a results file or study record taken at another cost than the
  fleet's gate cost (a `meta` naming another profile or other numbers, a result's `costs` record, or a fee / slippage difference in its
  protocol check, explained or not); it refused such records only through its protocol allow-lists before. The 33 accounts load
  unchanged (fingerprint 93cfcc282a1d).
- `research/report_v1c.py`: the report names the cost profile of a run that records one.
- Docs: `docs/TRADER_PLAN_2026-11-05.md` sections 2.9 and 4.6 (the dated decision), `docs/research/FILL_COST_REPLAY.md` section 7
  ("Decided"), `docs/RESEARCH_LAB.md` ("Named cost profiles for future studies"; there is no `docs/research/README.md`),
  `docs/runbooks/PAPER_FLEET.md` ("A study at the measured cost (plan row R24)").

## Unreleased — the PR #13 review: a security update, two fixes, the demo fix folded in, the runner on Opus (2026-11-06)

The blockers of pull request #13 (`plan/auto` into `main`), `docs/PLAN_STATUS.md` section 2, "From the PR #13 review".

### Security
- `requirements.in` / `requirements.txt`: streamlit 1.58.0 -> 1.66.1 and pillow 12.3.0 -> 13.0.0 (pinned): pip-audit reported
  39 advisories for pillow 12.x, all fixed in 13.0.0, and streamlit 1.58 capped pillow below 13. The lock was regenerated with
  the CI's uv 0.13.3; the CI's sync check and pip-audit pass locally. Streamlit 1.66 no longer needs gitpython, gitdb, smmap,
  blinker, cachetools, tenacity or toml.

### Fixed
- `research/engine.py`, the add variant (Codex review P2, then an independent review): the add is bought at the bar's open
  before that bar's stops are checked, so the bar's low can stop it and a whole-position stop, trailing stop or target reached
  later in the bar closes it with the first unit; never on a position that leaves at that open; of two stops crossed on one bar
  the higher fills first. 288 random runs without the add match the pre-fix engine to the last bit. The Trader Policy v1 report
  carries an erratum: its add-variant numbers overstate the variant. Tests in `tests/test_research_trader_policy_engine.py`.
- `app/news/budget.py` (Codex review P2, then an independent review): a reservation is written and flushed to the month's spend
  file before the paid call and cleared when the call is settled; a reservation left by a stopped process is charged in full,
  to its day, once; loading never writes the file (the operator's `status` stays read-only); a settlement is taken from the
  oldest open reservation first, so a call settled after midnight at a month's end cannot clear the new month's reservations.
  Six tests in `tests/test_news_budget.py`, the Codex reproduction among them. Log-only news shadow; no order path is involved.

### Changed
- `scripts/plan-runner.ps1`: the default model is Opus 5.5 again, at max effort (the owner, 2026-11-06).
- R14 part A (`sprint-6/position-persistence`, reviewed SAFE TO MERGE) is merged into `plan/auto`, so pull request #13 carries the
  demo safety-core fix; its own changelog and review record are in that branch's files.

## Unreleased — the paper fleet and the tokenized-stocks recorder on the server, with one line (2026-11-06)

Deploy files, one setup script, tests and docs only (`scripts/vps_research_setup.sh`, `deploy/systemd/xstocks-data.service`,
`deploy/systemd/paper-fleet.service`, `tests/test_research_services.py`, `docs/`): nothing under `app/`, `config/`, `migrations/` or
`research/` changed, the fleet's and the collector's code and every account's rules are unchanged, and nothing here reads or changes
`shadow.service`, its checkout, its `.env` or its database. Asked by the owner on 2026-11-06 ("i cant keep the laptop turned on for 60
days"). Simulation and public market data only; nothing here is an order or can place one.

### Added
- `scripts/vps_research_setup.sh` (`install`, the default; `status`; `update`; `uninstall`): checks the server (systemd, Python 3.11+,
  600 MB of free memory, 2.5 GB of disk) and stops before installing anything when it is short; installs `git` and `python3-venv`
  when missing; creates the unprivileged user `ai-research` and its own checkout of `plan/auto` in `/opt/ai-trading-research`; builds
  `.venv` from the hashed lockfile; runs the fleet's `--dry-run` before any service starts; writes `paper-fleet.service` and
  `xstocks-data.service` from the templates (every home folder hidden), checks them with `systemd-analyze verify`, starts them and
  waits until both run; refuses to overwrite a unit that runs from another folder (one record, one place). `update` pulls the newest
  `plan/auto`, re-runs the offline check and restarts both, putting the previous code back when the check fails or a service refuses
  the new code. The only line that names the shadow run is a read-only `systemctl is-active shadow.service`.
- `deploy/systemd/xstocks-data.service`: the tokenized-stocks recorder (plan row R21) as a service, with the fleet unit's hardening
  (read-only system except `data/lake/xstocks/`, the repository `.env` and the PostgreSQL socket unreachable, no capabilities),
  `Restart=always` except on the setup exit code 2, a quarter of a core, 512 MB, `Nice=10`, `OOMScoreAdjust=900`.
- `tests/test_research_services.py`: both units confined to their own folder, unprivileged, capped, first in line for the
  out-of-memory killer, free of secrets and of the demo header; the rendered units keep no placeholder and hide every home folder; the
  script never acts on `shadow.service`, never names an environment file or a home folder, installs from the hashed lockfile and runs
  the offline check; `bash -n` on Linux.

### Changed
- `scripts/vps_research_setup.sh` (after the first push): a server under 2 GB of memory without swap gets a 1 GB swap file at
  install and at update (an existing swap or `/swapfile` is left alone; where swap cannot be switched on, the file is removed and
  the setup goes on), because the owner deleted the old droplet on 2026-11-06 and the new one is a 1 GB droplet; recorded in
  `CLAUDE.md` (one dated paragraph under the VPS state), `docs/PLAN_STATUS.md` section 2 and the owner checklist (step 12 now
  creates the server; the steps that were about the old server are marked as waiting).
- `deploy/systemd/paper-fleet.service`: `OOMScoreAdjust=900`, so a memory shortage on the server ends the fleet before the shadow run;
  the install comment names the script.
- `docs/runbooks/PAPER_FLEET.md` (option A1, the record, updates after a fleet row, measured memory), `docs/runbooks/XSTOCKS_DATA.md`
  ("Where it runs": the server first), `docs/OWNER_CHECKLIST.md` (step 12, listed first), `docs/PLAN_STATUS.md` (section 1, and
  section 2 "From 2026-11-06").

### Tested
- In a stand-in server (Ubuntu 24.04, systemd 255, Python 3.12, a fake `shadow.service` and a fake key in a world-readable `.env`
  under `/home`): the documented one line installed and started both services; the fake shadow run stayed active with an unchanged
  start time; the fake key could not be read from inside either service; `status`, an `update` with nothing new, an `update` that changes the setup script itself (its new rules applied in the same run), an `update` to code that fails the offline check (refused, the previous code back, the fleet never restarted), `uninstall` (the records stay), a re-install from the existing checkout, the low-memory refusal (stopped before writing anything) and the refusal to overwrite another folder's unit behaved as documented; inside both services the system and their own code are read-only, they run as `ai-research` with no capabilities, an out-of-memory score of 900 and 4 threads each. The first run found one bug, fixed before release: the recorder's maths libraries open one thread per core, which broke a 32-task cap on a 16-core machine; both units now use one thread per library and allow 128 tasks. A key file outside `/home` (`/srv/...`) is walled off by the drop-in the script derives from `shadow.service`.
- Measured on Linux: the offline check passes on Python 3.12 in 85 s at no more than 405 MB; a first start from nothing builds the same 33 accounts as the laptop (fingerprint 93cfcc282a1d) and runs its first cycle with 0 errors at no more than 243 MB; a steady cycle takes 9 s at no more than 284 MB; the recorder's first pass (42,414 candles, 15 order books, 0 errors) takes 3.5 minutes at no more than 308 MB; as services, with one thread per maths library, the fleet held about 165 MB and the recorder 65 to 100 MB; the Python environment takes 652 MB of disk.
- The published one line, pasted as written on a fresh stand-in server after the push: the script came from GitHub, commit
  f8e07a8 was installed, `DONE.` after 9 min 47 s over a home connection, both services running, both fake keys (under `/home`
  and under `/srv`) unreadable from inside them, the fake shadow run never restarted.
- On the owner's new droplet (2026-11-06, 1 vCPU, 961 MB, Ubuntu 24.04, SGP1): the one line ended with `DONE.` (1023 MB of swap
  added, `python3-venv` installed, checkout 8a5739a, the offline check ok); `status` seven minutes later: 33 accounts at 10,000.00,
  data fresh, positioning data for all four swaps, the services at 144 MB and 108 MB. The console's bracketed paste broke the
  first paste; typing `bind 'set enable-bracketed-paste off'` first fixed it (documented).
- The full offline suite on Windows: exit code 0 (about 15 minutes); after the last changes the new tests, the deploy-unit tests and the 11 test files that scan the repository were run again: exit code 0.

## Unreleased — R23: two paper-fleet accounts the owner added — the S8 forward control and S1 BTC-USDT 6H, both at the Trader tier (plan row R23)

Fleet code, research-side row tooling, tests and docs only (`research/paper_fleet/config.py`, `research/paper_fleet/report.py`,
`research/fleet_rows.py`, `scripts/apply_fleet_rows.py`, `docs/`, `tests/`): nothing under `app/`, `config/` or `migrations/` changed;
`app/execution`, `app/risk`, `app/exchange` and `app/shadow` are untouched; the app's `ALLOWED_INSTRUMENTS` stays BTC-USDT / ETH-USDT and
the fleet's own allowed markets did not widen; no study was run, no holdout opened, no gate, rule or verdict changed. The authority for the
two rows is the owner's decision of 2026-11-05 ("do what you recommend": `docs/PLAN_STATUS.md`, section 2, "Decided — the owner,
2026-11-05 evening"), recorded in `docs/research/paper_fleet_additions_r23.json`. Simulation only, public data only; nothing here is an
order and nothing approves demo or live trading for any configuration.

### Added
- `ctl-s8-btc-6h-trader` (a forward CONTROL, never judged): the slow breakout S8 (Turtle System 2: 55-day high entry, 20-day low exit,
  5 × ATR stop) on BTC-USDT 6H without a regime gate, at the Trader tier with the brakes on, under the fixed-rule protocol variant — the
  cell research round 3 ran it in (`docs/research/research_round_3_results.json`, candidate S8, hypothesis H8: walk-forward Calmar 0.44,
  +3.9 % a year at an 8.8 % drawdown, 17 trades in 4.3 years, silenced by the 30-trade gate). No holdout; its backtest-consistency checks
  in the weekly report are information. R19's recommendation, the owner's go.
- `c20-s1-btc-6h-none-trader` (a candidate read as a hypothesis): plain S1 on BTC-USDT 6H without a gate, at the Trader tier with the
  brakes on, from the breadth study's single-sleeve record (`docs/research/breadth_v1_results.json`, candidate S1 at the Trader cell with
  brakes: section 4.6 gates passed, walk-forward Calmar 0.61, +8.6 % a year at a 14.3 % drawdown; holdout +3.8 %, PF 1.40, 32 trades,
  confirmed). The R20 pre-registration listed no fleet ticket for single sleeves (`source.note` says so); at the Reference tier the same
  rule never passed, so it has no Reference twin. R20's recommendation, the owner's go. S1+VC SOL-USDT 6H was NOT added, as R20 recommended.
- `research/fleet_rows.py` and `scripts/apply_fleet_rows.py`: owner-decided rows built from a study's stored record exactly as the studies
  build theirs (`_row` plus the R18b source tag read from the record's cell, brakes and protocol check), appended with
  `research.replication.append_to_shortlist` under an amendment naming the plan row and the decision, with the fleet-can-load check (the
  R12 rule: the file is restored when the fleet cannot load the amended shortlist); `--check` validates on a copy; a row already there is
  never added twice; exit codes 0 / 1 / 2. `docs/research/paper_fleet_additions_r23.json` is the decision record (the committed shortlist
  rows reproduce from it, tested).

### Changed
- Loader (`research/paper_fleet/config.py`): a control row of a registered fixed rule other than the slow-trend `TF` control may run at a
  documented tier (`CONTROL_TIERS`: Reference, Trader, Aggressive — the Trader Plan's section 4.1) with the brakes its study cell ran with,
  when that cell's recorded protocol check has no unexplained mismatch and names the fixed-rule protocol variant the row names (the same
  record check a fixed-rule candidate passes); its account id carries the tier. The `TF` controls keep the Reference sizing without brakes
  (refused otherwise, as before); a candidate row's `source.results` may name any study whose results carry the protocol check, so the R20
  record serves `c20` through the R18b path unchanged.
- Weekly report (`research/paper_fleet/report.py`): the S8 control is listed with the controls (the "In short" controls line, the controls
  table with its backtest numbers, and under each Trader-tier account of its market in the "Trader tier beside the Reference tier" section
  with its brakes); a Trader-tier account without a Reference twin is listed beside the other rules the fleet runs on its market and bars
  (`c20` beside `c01` and `c17`) with a "no Reference twin" line, and the "In short" tier line says so. Nothing changes for the fleets
  without such accounts.
- `docs/research/paper_fleet_shortlist_v1c.json`: 20 configurations and 11 controls (33 fleet accounts); amendment "plan row R23 …" of
  2026-11-05 20:23 UTC. The 31 running accounts' fingerprints and the shared rules are unchanged (pinned).
- `docs/runbooks/PAPER_FLEET.md` ("Two accounts the owner added (plan row R23)", the report-reading bullet, the expected account count);
  `docs/PLAN_STATUS.md` (row R23, section 2).

### Tests
- `tests/test_paper_fleet_config.py`: 33 accounts, both new accounts' rules, labels, sources and expectations, the two new fingerprints
  pinned beside every earlier one, the S8 control refused on any mismatch with its record (role, protocol variant, cell, brakes, sizing,
  tier, parameters, a different rule, a control row under the configurations), the TF controls refused off the Reference sizing, a control
  tier outside the documented ones refused, expectations outside every fingerprint. `tests/test_fleet_rows.py`: the committed spec
  reproduces the committed rows, the builder's refusals, the R12 rule for the apply path and the command line (check, apply once, the exit
  codes). `tests/test_paper_fleet_report.py`, `tests/test_paper_fleet_cli.py`, `tests/test_paper_fleet_runner.py`: the report's placement
  of the two accounts, `--status` for a control at a tier, and the S8 control running with its brakes on the synthetic market beside its
  hold control and `c20`, invariants intact.

## Unreleased — R22: fill-cost replay from OKX's public tick and order-book archive (plan row R22)

Research code, tests and docs only (`research/fill_replay.py`, `scripts/run_fill_replay.py`, `tests/`, `docs/`): nothing under
`config/`, `migrations/` or `research/paper_fleet/` changed, and under `app/` only `app/ops/okx_usage.py`, the OKX changelog
watcher's list of used endpoints and hosts, gains the public listing path (`GET /api/v5/public/market-data-history`) and the archive
host (`static.okx.com`) so the watcher covers them, as plan rows R12 and R21 did; `app/execution`, `app/risk`, `app/exchange` and
`app/shadow` are untouched; the research engine's `Costs` default is unchanged. Public data only: the listing through the data
lake's GET-only public client (no key, no header), the files through a GET-only downloader bound to `https://static.okx.com/cdn/...`
and to the URLs the listing returned (no redirect followed, no header sent). Nothing here trades, sizes or approves anything;
nothing is authorized by it; no finished study is re-judged.

### Added
- `research/fill_replay.py`: the archive listing (`instIdList`, modules 1 trades / 2 one-minute candles / 4 the 400-level L2 book,
  10-day and 10-instrument chunks, a day of padding because the listing reads the window in UTC+8 for the trades modules and in UTC
  for the book, files kept by the day in their name); `ArchiveDownloader` (host-pinned, GET-only, resumable: `.part` then verify
  against the listed size and the archive's own integrity check, a manifest with SHA-256 per file; a session is handed in, the module
  imports no network library); the parsers (trades and candle CSVs, the book's JSON lines), `OrderBook` (snapshot and updates, nothing
  read before the first snapshot), `walk_book` / `cost_bps`, `bar_boundaries`, `post_only_outcome` (trade-through or queue drained,
  FIFO, cancellations ahead ignored), the replay over pooled trades and candles (their files hold the UTC+8 day) and UTC book days
  (the book carried across consecutive days; three moments per boundary: the close, the next bar's first trade, one second later),
  the summaries, `write_results` (summaries indented, one record per line) and `render_tables`.
- `scripts/run_fill_replay.py`: `--list`, `--fetch`, `--replay [--keep]`, `--all`, `--status`; `--start/--end` or `--days` (default
  end T-3); the raw files are deleted after the summaries are written unless `--keep`; exit codes 0 / 1 / 2; the fleet's dotenv guard.
- `docs/research/FILL_COST_REPLAY.md` (the report: coverage, the cost of size against the mid, the candle close and the next open,
  timing, the post-only fill rates, the recommendation, caveats, how to reproduce), `docs/research/fill_cost_replay_results.json`
  (summaries, coverage, the 60 file manifests, one record per bar boundary), `docs/research/fill_cost_replay_tables.md` (the full
  generated tables); `docs/DATA_LAKE.md` (the `data/archive/okx` folder and the day-boundary difference), `docs/RESEARCH_LAB.md`
  (the R22 section), `docs/PLAN_STATUS.md` (row R22, section 2).
- Tests: `tests/test_research_fill_replay.py` (URL pinning, the recorded listing, chunking and padding, the downloader's manifests,
  resumption, refusals of foreign hosts, redirects and corrupt files, the parsers and the book, the arithmetic by hand, the post-only
  rule, the replay end to end on scripted synthetic days, the summaries, JSON and tables, the command line);
  `tests/test_research_boundaries.py` (R22 stays in the sandbox, names one public path and one archive host, never the demo header,
  follows no redirect, is not imported by the app or the fleet); `tests/fixtures/fill_replay/listing_2026-11-05.json` (recorded
  public listing responses).

### Result (2026-11-05; `docs/research/FILL_COST_REPLAY.md`)
- Ten UTC days (2026-10-25 to 2026-11-03), 60 files, 2,093 MB fetched in 18 minutes; 7.1 million trades and 64.2 million book
  events replayed in about 10 minutes; 100 bar boundaries per instrument, 4,800 market-order walks, 384 post-only bars judged.
- Spread plus impact against the next bar's open: 0.01 bps (BTC) and 0.04 bps (ETH) at the median for every clip from 1 K to 20 K
  USDT; the 20 K clip 0.08 / 0.33 bps on average, 0.82 / 2.09 bps at the 99th percentile, 2.5 bps at worst; the book one tick wide
  (0.013 / 0.043 bps). One second of latency: 0.5 / 1.0 bps median mid move, 1.8 / 2.9 bps at the 90th percentile, 15 bps once.
  A post-only order at the touch filled within the bar in every bar judged, usually within seconds, by trade-through.
- Recommendation for FUTURE BTC/ETH studies (owner's decision): 2 bps of slippage a side instead of 5, fee unchanged (0.24 % a round
  trip instead of 0.30 %); altcoins unchanged until measured. Demo fills are from a separate thin book and are not evidence.

## Unreleased — R21: tokenized US stocks on OKX — feasibility, log-only data collector, design note (plan row R21)

Research code, tests and docs only (`research/xstocks_data.py`, `scripts/collect_xstocks.py`, `scripts/xstocks-task.ps1`, `tests/`,
`docs/`): nothing under `config/`, `migrations/` or `research/paper_fleet/` changed, and under `app/` only `app/ops/okx_usage.py`, the
OKX changelog watcher's list of used endpoints, gains the two public paths the collector reads (books, price-limit) so the watcher
covers them, as plan row R12 did for the tickers path; `app/execution`, `app/risk`, `app/exchange` and `app/shadow` are untouched;
the app's `ALLOWED_INSTRUMENTS` stays BTC-USDT / ETH-USDT. Public data only, through the data lake's
GET-only public client (no key, no header) on six public endpoints (instruments, tickers, candles, history-candles, books, price-limit).
Nothing here trades, sizes or approves anything; nothing is authorized by it. The demo shadow run and its caps are untouched.

### Added
- `research/xstocks_data.py`: the log-only collector for OKX's tokenized US stock pairs. The universe rule (the 15 most liquid live SPOT
  instruments with `instCategory` 3 and an `X...-USDT` id, by 24-hour quote volume, ties by id; chosen ONCE and kept in a committed file,
  so every machine collects the same list; XRP, XLM, XAUT and XPL fail the category); the daily instrument-parameter record (`lotSz`,
  `minSz`, `tickSz`, `maxMktAmt`, the three price-band percentages, `groupId`, `listTime`, `state`, `upcChg`, ... exactly as OKX returns
  them); resumable 1H and `1Dutc` candles back to each pair's `listTime` through the lake's `BackwardWalker` (OKX's `1D` opens at 16:00 UTC
  and would cut the US session in two; the quote volume is stored beside the base volume); order-book snapshots on the New York schedule
  (09:30 and 16:00 America/New_York on weekdays, converted at run time, 03:00 UTC daily, 12:00 UTC on Saturdays; a slot missed by less
  than 30 minutes is still taken; taken slots are recorded so a restart never repeats one; US holidays and early closes labelled from a
  2026-2027 NYSE calendar); 400 levels requested (50 reach only 0.2-0.45 % from mid on XQQQ, XSPY and XGOOGL, which would cut the plan's
  "depth within 0.5 %" short), the levels within 2 % of mid stored with the spread, the depth within 0.5 % per side and whether the band
  was covered, plus the venue's price limits; the metrics of the feasibility report (days of history, coverage, weekday against weekend
  volume, US-hours share, weekend gaps, open jumps, weekend deviations and falls, spreads and depth per slot) and the Markdown tables;
  `run_once` / `run_loop` (snapshots at their slots, 1H top-up 90 s after every hour, 1Dutc and the parameters once a day); `lake_status`.
- `scripts/collect_xstocks.py`: `--select-universe` (once; refuses to overwrite without `--force`), `--once [--snapshot-now]`, `--loop
  [--max-minutes]`, `--status`, `--report [--out]`; exit codes 0 / 1 (errors in the pass) / 2 (setup); the fleet's dotenv guard (no `.env`
  secrets in the process). `scripts/xstocks-task.ps1`: the Windows scheduled-task wrapper (the fleet's pattern: STOP file, leftover
  process, no restart on exit code 2).
- `docs/research/xstocks_universe.json` (the 15 pairs chosen 2026-11-05 08:11:15 UTC with the whole 165-pair ranking and the summary),
  `docs/research/tokenized_stocks_feasibility.json` (the per-pair numbers), `docs/research/TOKENIZED_STOCKS_FEASIBILITY.md` (the
  report: the universe, plan 2.8's facts re-checked, the first data, the reading against the Trader policy's stops, caveats, next),
  `docs/design/TOKENIZED_STOCKS.md` (the design note: what the code assumes today and where, the six reviewed changes — allowlist and
  identity, rebasing-aware reconciliation, lot flatness via R14 part A, the session rule, price-band-aware orders, instrument-state
  watch and corporate actions — the 19 demo pairs, the fail-closed table, tests, the order of work, the review path, the demo validation
  plan, the owner's decisions), `docs/runbooks/XSTOCKS_DATA.md` (the laptop task next to the fleet, checks, troubleshooting, disk).
- Tests: `tests/test_research_xstocks_data.py` (25 tests on recorded public responses and a synthetic candle history: the universe
  rule and its exclusions, the file's write-once and tamper checks, the parameter record, the candle parser's grids, the resumable walk
  back to listing, the New York schedule in winter and summer with holidays and the grace window, the book parser, metrics and trim, the
  snapshot writer and its slot ledger, a failing pair, `run_once` end to end and idempotent, `run_loop` on a fake clock with a stop
  request, the history metrics on a constructed series, the report tables, the command line, the committed universe file);
  `tests/test_research_boundaries.py` (the collector stays in the sandbox, names only the six public paths, never the demo header, is
  not imported by the app or the fleet, and the allowlist is unchanged); `tests/fixtures/xstocks/recorded_2026-11-05.json`.
- `docs/DATA_LAKE.md` (the `xstocks/` subtree), `docs/RESEARCH_LAB.md` (the R21 section), `docs/OWNER_CHECKLIST.md` (step 9 pointer and
  the "meanwhile" note), `docs/PLAN_STATUS.md` (row R21, section 2).

### Result (2026-11-05; `docs/research/TOKENIZED_STOCKS_FEASIBILITY.md`)
- First live run 08:11-08:15 UTC: 165 live X-USDT stock pairs ranked (141.7 M USDT a day, top 10 = 79 %, 19 above 1 M, 53 below 10 K);
  the 15 chosen (XCRCL, XGOOGL, XQQQ, XINTC, XSOXL, XMSTR, XSNDK, XNVDA, XSPCX, XMU, XAMD, XSKHY, XSPY, XMRVL, XTSLA; XSKHY and XMRVL
  replace the XMETA and XAAPL of the 2026-11-04 list, which rank 16th and 21st) all listed 2026-07-16; 42,024 candles, no gaps, 15 books,
  0 errors; a 52-minute live `--loop` run afterwards (hourly top-up).
- About half of weekday volume trades while the US market is shut (US-hours share 43-60 %); weekends carry 16-36 % of a weekday's volume
  (XSPY's figure is three launch-week days). Over 16 weekends the token fell more than 2.4 % below Friday's close in 22 % of the 240
  pair-weekends (5 % more than 5 %); the index trackers never more than 1.8 %, XSOXL (a 3x leveraged ETF token) up to 17.9 %. One
  pre-market snapshot: spreads 0.8-8 bps, depth within 0.5 % of mid 3-126 K USDT per side. Nothing is a candidate; the decision gate is
  the plan's section 6.2 step 4 after 60-90 days of the laptop task's data.

### Deviations from the row text, with reasons
- 400 book levels requested and the levels within 2 % of mid stored, not 50 (the 0.5 % band would be cut short on the tightest books);
  `1Dutc` daily candles, not OKX's `1D` (a UTC day holds one whole US session; the 16:00 UTC bar does not); the universe is one day's
  ranking, as the row asked, so it differs from the row's 2026-11-04 example by two names.

## Unreleased — R20: breadth v1 — the S1 family on nine OKX markets as ONE Trader-tier book, and one pre-registered rotation test (plan row R20)

Research code, tests and docs only (`research/`, `scripts/run_breadth_v1.py`, `tests/`, `docs/`): nothing under `app/`, `config/`, `migrations/`
or `research/paper_fleet/` changed; `app/execution`, `app/risk`, `app/exchange` and `app/shadow` are untouched, the app's `ALLOWED_INSTRUMENTS`
is untouched. The demo shadow run, its caps and the 0.60 confidence floor are untouched; nothing reaches demo, live or the paper fleet.
Simulation only: nothing here places, sizes or approves an order. Public data only (the frozen study lake built from the research lake); no
network path of its own.

### Added
- `research/breadth.py`: `run_book`, a multi-market book simulator — several sleeves (a rule on a market, with the bar-by-bar signals the research
  engine trades) share ONE equity; each entry is sized by the Trader tier on the book's equity at the previous close and takes at most the cash
  left (spot, no leverage; an open position is never sold to make room for a new one); the section 4.3 brakes act at BOOK level (the Turtle
  ladder, the hard stop and the 24-hour / weekly / monthly loss limits read the R18 `EntryBrakes` state machine on the book's equity; one new
  entry per market per UTC day across the market's sleeves, three per day across the book, none in a market on the bar after an exit there, ties
  by the rules' strength then a fixed market order; the heat cap over the correlation groups scales every open and new position of a bet equally,
  only when a new entry is wanted in that bet, leaving a position whose stop sits above the price alone); allocator v2's correlation cap at the
  first bar of every UTC day and its daily record; a `start` bar before which the bars only warm up the correlations. On one sleeve with no brakes
  it is `research.engine.run_vectorized` bit for bit (tested on four exit brackets, with and without the brakes). `run_weekly_basket`: the
  daily-booked weekly-rebalanced basket of the rotation test and its benchmarks (decided at a day's close, filled at the next day's first open,
  costs out of the money invested, a volatility target, an optional daily filter), with `top_n_selector`, `fixed_selector`, `sma_filter`.
- `research/breadth_study.py`, `research/report_breadth.py`, `scripts/run_breadth_v1.py`: the pre-registered study — the nine markets (the
  replication study's fixed list plus BTC/ETH, checked), the S1 family (S1, S1+VC, S1+S5 where funding covers 90 % of the in-sample bars), 6H bars,
  no gate; one job per market and cell through Sprint 2c's own `run_series` (hold, S1, S1+VC, S1+S5 at the Reference and the Trader cell), the
  per-job protocol check (a tier is the only explained mismatch), the reproduction of the stored numbers first (Sprint 2c, R12, R13, R16 at the
  Reference cell; R18, R19 at the Trader cell; the study stops on any difference), every sleeve's own verdict at the Trader cell, the book from
  each sleeve's per-window selected rule (a replay, never a selection), its five pre-registered ablations and one post-hoc diagnostic (the hard
  stop off; added after the first run and labelled not pre-registered everywhere), the comparison lines (the Trader-cell hold control, the hold
  through the book simulator, BTC buy-and-hold, the equal-weight hold of the nine at the same volatility target), the diversification reading,
  the market and sleeve correlations, the R5b candidate rule, the holdout construction (the most-often rule, starting flat) behind the gates,
  the rotation test (top 3 of the nine by trailing 3-week return, weekly, BTC 200-day filter, 20 % volatility target, altcoin costs) with its
  benchmarks and pass rule, the append-only ledger with the earlier looks, the fleet rows RECORDED only (the fleet has no book or rotation
  account type), the report with every sentence computed from the numbers.
- `docs/research/breadth_v1_preregistration.json` (written before the first run, hashed; the committed file must match the module, the gates,
  the markets, the cell, the brakes, the book configuration and the rotation rule), `docs/research/BREADTH_V1_REPORT.md`,
  `breadth_v1_results.json`, `breadth_v1_holdout_ledger.json`.
- Tests: `tests/test_research_breadth.py` (the engine parity on one sleeve, the cross-sleeve entry caps, the heat cap's equal scaling per bet and
  its entries-only rule, the correlation cap, the cash constraint, the loss limits and the ladder on the book's equity, the daily records, the
  basket's fills, costs, volatility target, filter and no-look-ahead, the pre-registration write-once-and-check, the jobs and the protocol check,
  every sleeve's stored reproduction target, the verdict rules, an end-to-end run on a synthetic lake, the report, the command line's refusals);
  `tests/test_research_boundaries.py` (the breadth study stays in the sandbox, opens no network path, widens no allowlist, is not imported by the
  app or the paper fleet).
- `docs/RESEARCH_LAB.md` (the breadth section), `docs/PLAN_STATUS.md` (row R20, section 2), `docs/runbooks/PAPER_FLEET.md` (one paragraph).

### Result (2026-11-05; `docs/research/BREADTH_V1_REPORT.md`)
- 51 of 51 reproductions exact; 27 sleeves run, 26 in the book; 4.0 minutes on 12 workers.
- The breadth book FAILS: -6.7 % a year, a 30.1 % worst fall, Calmar -0.22, profit factor 0.68 over 460 funded trades; its equity fell 30 % by
  2022-04-26 and the pre-registered hard stop ended its entries for good; without the hard stop (post hoc) -8.3 % a year, a 43 % fall, 9.4 % of
  equity a year in costs. The construction loses: nine correlated markets form one bet, the heat cap trimmed every open position at almost every
  new signal (4.8 trims per trade), the average win fell to 1.12 x the average loss against 2.68 x for the sleeves alone. Not a candidate; nothing
  joins the fleet.
- 6 of 26 sleeves pass alone at the Trader cell; the holdout confirmed five (S1 and S1+S5 BTC; S1, S1+VC and S1+S5 SOL) and contradicted S1+VC ETH.
  S1 BTC-USDT 6H and S1+VC SOL-USDT 6H are confirmed but not in the fleet and had no fleet ticket here: an owner decision.
- The rotation does not beat BTC, as pre-registered: +20.6 % a year at a 20.3 % fall (Calmar 1.02) against +28.1 % at a 40.5 % fall (Calmar 0.69)
  for holding BTC at the same volatility target — the drawdown halved, the return did not follow. Question closed.

 — the asymmetric setups (trend-pullback continuation S7, the slow breakout S8, the bar size after costs), pre-registered (plan row R19)

Research code, tests and docs only (`research/`, `scripts/run_research_round_3.py`, `tests/`, `docs/`) plus one validation extension of the paper
fleet's loader (`research/paper_fleet/config.py`): nothing under `app/`, `config/` or `migrations/` changed; `app/execution`, `app/risk`,
`app/exchange` and `app/shadow` are untouched. The demo shadow run, its caps and the 0.60 confidence floor are untouched; no rule, tier or
protocol variant reaches demo or live. Simulation only: nothing here places, sizes or approves an order. Public data only (the frozen study lake
built from the research lake); no network path of its own.

### Added
- `research/strategies/round3.py`: the Trader Plan's section 5 setups as FIXED rules (one pre-registered parameter set each, nothing for the
  walk-forward to select): `S7` trend-pullback continuation (uptrend = close above its 100-day SMA and the 50-day above the 100-day; pullback = a
  close below the 20-day SMA; entry = a close above the previous bar's high while the uptrend holds; stop = under the pullback low floored at
  2 x ATR(14); exit = a close below the 50-day SMA or the stop) with the variants `S7e` (10-day EMA pullback), `S7w` (3 x ATR floor) and `S7t`
  (the same rule under the protocol's `trail3` exit bracket, applied through the `bracket` parameter by the runner and the fleet alike); `S8`
  slow Turtle System 2 breakout (55-day high entry, 20-day low exit, 5 x ATR(14) stop, no adds, no filters) with `S8g` (Garner's 90/45
  channels). Registered in `research.strategies` (`FIXED_RULES`, `VARIANT_OF`, `ROUND3_BASES`); causal state machines; no look-ahead.
- `research/round3.py`, `research/report_round3.py`, `scripts/run_research_round_3.py`: the pre-registered study — the fixed-rule protocol
  variant (`--brackets <fixed> --min-trades 0`: the 20-train-trade qualification that left round 2's slow rules flat is skipped, every window runs
  the rule's test slice; the walk-forward windows, costs, S0 filter, regime gate and the +-30 % robustness replay are Sprint 2c's), the Trader
  Policy's Trader tier with its brakes as the judged cell (`trader|brakes|none`, the paper fleet's cell) and the Reference cell beside it, the
  plan's section 4.6 gates at that tier, BTC-USDT and ETH-USDT as the primary markets and the seven R12 markets as replication, 1D and 6H bars
  (1D resampled from 1H at UTC midnight), hold + policy at the same cell as the comparison line; the bar-size comparison of S1, S2, S1+S5 and
  S2+S5 on 1D, 6H and 4H bars at both cells with the measured 0.20 % cost replayed; the per-job protocol check with its explained deviations
  (a tier, the fixed-rule protocol, 1D bars; the study stops on anything else); the reproduction of the stored numbers first (Sprint 2c's, the
  replication study's and the Trader Policy study's judged cell; the study stops on any difference); the pre-registered readings (the sign tests
  against hold + policy on the primary and the replication markets, the variants beside their base rule, the R12 replication reading, trades a
  year beside the plan's expectation, the plan's 40-trades-a-year turnover ceiling as a fleet condition, H8's pooled nine-market reading as
  information, the Trader cell beside the Reference cell); the holdout once for judged passers through an append-only ledger with the earlier
  looks; fleet-eligible confirmed passers appended to the shortlist as Trader-tier accounts naming the fixed-rule protocol (1D passers recorded,
  never applied: the fleet runs 4H and 6H); the report with every sentence computed from the numbers, including the parked ideas and their reasons.
- `docs/research/research_round_3_preregistration.json` (written before the first run, hashed; the committed file must match the module, the
  rules' numbers, the cell and the brakes), `docs/research/RESEARCH_ROUND_3_REPORT.md`, `research_round_3_results.json`,
  `research_round_3_holdout_ledger.json`.
- Tests: `tests/test_research_round3.py` (the state machine, the frames and variants, the fleet can build and decide for the rules including the
  trail bracket, the job plan and the runner arguments, the protocol checks, the bookkeeping on fabricated results, the bar-size reading, a
  synthetic-lake run through Sprint 2c's runner on 6H and 1D bars, the pre-registration file, the command line's holdout guards, the shortlist
  rollback, the fleet loader's acceptance and refusals); `tests/test_research_boundaries.py` (round 3 stays in the sandbox).

### Changed
- `research/paper_fleet/config.py`: a tier-tagged candidate row may name the fixed-rule protocol variant (`source.protocol_variant`) — only for a
  rule in `research.strategies.FIXED_RULES`, only when the study's recorded protocol check of that cell names the same variant, with the same two
  explained deviations (`brackets`, `min_trades`) the slow-trend control already has. Every existing account, its rules and its fingerprint are
  unchanged (`tests/test_paper_fleet_config.py` pins them).
- `tests/test_research_round2.py`, `tests/test_paper_fleet_config.py`: two pinned expectations updated for the new fixed rules and the loader's
  wording (`FIXED_RULES` now lists more than `TF`; a swept rule with a protocol variant is still refused).
- `scripts/run_research_v1c.py`: the regime-threshold sensitivity replay sizes the lead gated S1/S2/S4 rule with the policy spec; a stop-aware tier (a
  per-trade cap or a risk-sized kind) now reads that rule's own stop there, Sprint 2c's own policy reads no stop and takes exactly the path it always
  did (the study's 49 reproductions prove it). Found by the first full run of this study, which crashed on a gated S2 bar-size job at the Trader cell
  before writing anything; recorded in the report's method notes.
- `docs/RESEARCH_LAB.md` (the round-3 section), `docs/PLAN_STATUS.md` (row R19, section 2).

### Result (2026-11-05; `docs/research/RESEARCH_ROUND_3_REPORT.md`)
- 124 jobs, 568 results, 216 judged configurations on nine markets, 49 of 49 reproductions exact, 18.7 minutes on 12 workers.
- H7 (trend-pullback continuation, S7 and three variants): failed walk-forward on BTC/ETH (0 of 32) and on the seven replication markets (0 of 112);
  a higher Calmar than hold + policy at the same Trader budget in 5 of 144 (median -0.11 against 0.34); refuted, not merely untested.
- H8 (the slow breakout, S8 and Garner's variant): failed walk-forward everywhere (0 of 16, 0 of 56); the 30-trade gate bound in 72 of 72 (a median
  3.2 trades a year); the asymmetric shape is there pooled over nine markets (profit factor 1.6-1.9, average win 2.5-2.9 x the average loss, +0.13
  to +0.30 R a trade) but its Calmar is below holding at the same budget in 61 of 72 (median 0.20 against 0.34).
- Bar size: '6H is the cost-adjusted sweet spot' does not hold (6H best in 7 of 16 and 6 of 16, 8 needed; clarified with the untested S2-on-1D
  comparisons set aside: 7 and 7); 6H leads the S1 family at the gate cost (5 of 8), 4H leads the S2 family (6 of 8).
- Nothing joins the paper fleet; the holdout was opened only for the hold + policy comparison lines (18, all negative).

## Unreleased — R18a: Trader Policy v1 — three fixed risk budgets, entry brakes, position-management variants and the pre-registered study (plan row R18a)

Research code, tests and docs only (`research/`, `scripts/run_research_v1c.py`, `scripts/run_trader_policy_v1.py`, `tests/`, `docs/`): nothing under
`app/`, `config/` or `migrations/` changed; `app/execution`, `app/risk`, `app/exchange` and `app/shadow` are untouched. The demo shadow run, its caps
(10 USDT an entry, 1 USDT a day) and the 0.60 confidence floor are untouched; no tier, brake or variant reaches demo or live. Simulation only: nothing
here places, sizes or approves an order. The paper-fleet half of the row (loader extension, fleet engine, the new accounts, the weekly report) is plan
row R18b; the rows for it are RECORDED in the results file, not applied.

### Added
- `research/sizing.py`: a per-trade risk cap (`risk_cap`: allocation <= cap / (stop distance / close)) and a risk-sized kind (`kind="risk"`, Kovner's
  rule), both read from the candidate's own stop distance at the decision bar; `rule_fraction_matrix` (one policy column per rule column);
  `fraction_components` (how often the cap binds); `SIZING_TIERS` (Reference = Sprint 2c's policy unchanged; Trader `vt20/30 crash15/90dh cap2`;
  Aggressive `vt25/30 crash15/90dh cap2.5`; `risk1.5` for information). A spec without the new fields serialises exactly as before (the stored
  studies' protocol check compares it).
- `research/brakes.py`: the section 4.3 brakes, entries only — the Turtle ladder (x0.8 at -10 % from the equity peak, x0.64 at -20 %, restored on a
  new high), the -30 % hard stop, the entry caps (1 per market per day, 3 per day, none on the bar after an exit), the rolling 24-hour / weekly /
  monthly loss limits (3 / 6 / 10 %), the heat cap (6 %, variant 8 %) with the R5b correlation grouping and equal size-down — as an
  `EntryBrakes` state machine the engine consults once per bar before its entries, with per-column trigger counts; `BarCalendar` (UTC day,
  Monday-based week, month, bars per day; unit-independent).
- `research/engine.py`: the optional `brakes` / `bar_times` hook and `EngineVariants` (one add of half the initial quantity at +1 R with its own stop
  from the add bar, the first unit keeping its stop; a half scale-out at +2 R through the reduce-only path), both off by default and bit-for-bit
  today's engine when off; the extra trade columns `stop_price`, `risk`, `risk_pct`, `adds`, `add_worst_case_r`, `scale_outs` (the Sprint 2 columns
  unchanged). `research/bracket.py`: `trail3`. `research/montecarlo.py`: the share of bootstrap paths touching a drawdown threshold (`prob_max_dd_ge_30`).
- `research/trader_policy.py`: the tiers (`TIERS`, the comparison tiers with the Reference ladder and with no ladder, `tier_for` for the fleet
  loader), the variants (`VARIANTS`, `variant_frames`, the conviction multiplier), the section 4.6 gates (`acceptance_check_r18`: max drawdown <=
  25 % and worst year >= -15 % at the higher tiers, average win / average loss >= 2 at every tier), the size-neutral variant rule
  (`variant_counts`), the brake-cost flag (0.1 Calmar), the per-trade statistics (expectancy in R, payoff ratio, gaps past the stop, re-entries within
  two bars of a stop-out, risk per trade, cap binding, adds' worst case, the conviction test).
- `research/trader_policy_study.py`, `research/report_trader_policy.py`, `scripts/run_trader_policy_v1.py`: the pre-registered study — the five
  confirmed configurations (S1+S5 BTC 6H; S1 and S1+S5 SOL 6H; S1+VC BTC 4H gate; S1+VC DOGE 4H gate), six hold controls and four TF forward controls
  (long above the 200-day average, policy sizing, a fixed rule) at 11 core cells (tiers x brakes on/off, the comparison ladders, `risk1.5`) plus 7
  variant cells, 150 cells in all, through Sprint 2c's own runner; the reproduction of every stored number first (the study stops otherwise); the
  protocol check recorded per cell (a tier is a documented `policy_sizing` mismatch; the study stops on any other); costs replayed at 0.20 % and 0.50 %
  a round trip beside the 0.30 % gate cost; the holdout for the pre-registered cells only, through an append-only ledger with the earlier looks;
  `docs/research/TRADER_POLICY_V1_REPORT.md`, `trader_policy_v1_results.json`, `trader_policy_v1_preregistration.json`,
  `trader_policy_v1_holdout_ledger.json`; the fleet rows recorded in the results (`shortlist_additions`) for plan row R18b.
- Tests: `tests/test_research_brakes.py` (each brake's rule and counts, the calendar on nanosecond and microsecond indices, the heat-cap functions),
  `tests/test_research_trader_policy_engine.py` (tiers, cap, risk kind, per-rule matrices, the add and scale-out, flags off bit-for-bit, the walk-forward
  plumbing, cost replays, the Monte Carlo threshold), `tests/test_research_trader_policy.py` (gates, variant rule, statistics, cells, runner arguments,
  protocol honesty, pre-registration write-once and integrity, stored results found, a synthetic-lake run through the real runner, fleet rows, ledger,
  the command line); `tests/test_research_boundaries.py` covers the new script.

### Changed
- `scripts/run_research_v1c.py` (the Sprint 2c protocol runner) takes the plan-row-R18 arguments `--policy-kind`, `--policy-risk`, `--policy-risk-cap`,
  `--turtle-ladder`, `--brakes`, `--heat-cap`, `--variant`, `--cost-scenarios`, `--tier`; every default is Sprint 2c's and the stored numbers reproduce
  at the defaults (checked by the study: 11 of 11). The per-window rule selection never sees the tier; a tier run records `acceptance_r18`, `r18`
  (brake counts, trade statistics, cap binding, cost replays, the conviction test) and the tier label, and judges its holdout by the section 4.6 gates.
- `research/gated_walkforward.py`: `policy_fractions` may be an (n_bars, n_rules) matrix; `brakes`, `variants` and `test_frames` (the variant's frames
  for the test slice; the selection still runs on the originals) reach the engine; `replay_gated` / `slippage_stress_gated` take them;
  `cost_scenarios_gated`. `research/sweep.py`: `simulate_slice` / `simulate_sizing` pass `brakes` and `variants` through.
- `docs/PLAN_STATUS.md`: row R18 split into R18a (this) and R18b (the paper-fleet side); owner items in section 2. `docs/RESEARCH_LAB.md`: a section.

### Result (2026-11-05)
- `docs/research/TRADER_POLICY_V1_REPORT.md` (150 cells, 9.6 min on 12 workers). Reproduction: 11 of 11 stored results exact (differences below the
  stored 6-decimal rounding; same trades, rules and verdicts). **All five configurations pass the section 4.6 gates at the Trader tier with the
  brakes on, and their untouched 12 months confirm at that tier** (near-second looks at months the Reference tier already opened; the ledger names each
  earlier look). Trader tier, brakes on, 0.30 % a round trip: S1+S5 BTC 6H +10.4 % a year at a 14.1 % worst drawdown (Calmar 0.74, realized
  volatility 10.1 %, 1.66 x the Reference exposure, a stop costs 1.7 % of the account on average, the 2 % cap binding on 64 % of entries, holdout +3.4 %
  from 30 trades); S1 SOL 6H +9.8 % at 8.0 % (Calmar 1.22, vol 8.0 %, 1.61 x, holdout +8.5 % from 11 trades); S1+S5 SOL 6H +13.6 % at 9.8 % (Calmar
  1.39, vol 9.5 %, 1.63 x, the same 11 holdout trades); S1+VC BTC 4H gate +8.0 % at 13.8 % (Calmar 0.58, vol 10.5 %, 1.74 x, holdout +2.0 % from 27
  trades); S1+VC DOGE 4H gate +6.3 % at 9.4 % (Calmar 0.67, vol 7.9 %, 1.82 x, holdout +1.3 % from 16 trades). Average win 2.7-4.7 x average loss,
  expectancy 0.16-0.27 R, no stop-loss exit filled below its stop in 4.3 out-of-sample years, bootstrap chance of touching -30 % at most 0.6 % at
  Trader and 2.9 % at Aggressive (section 4.1 expected about 1 in 30 and 1 in 10). The Aggressive tier passes on all five with the brakes on (4 of 5
  without) at 9.8-12.7 % realized volatility and 9.9-17.2 % drawdowns; `risk1.5` sits between Reference and Trader (1.2-1.5 x the Reference exposure).
- Brakes, Trader tier, five sleeves summed: "no entry on the bar after an exit" acted 131 times, "one entry per market per day" 26 times, the Turtle
  ladder cut 7 entries, the 24-hour loss limit blocked 1; the weekly and monthly limits and the heat cap never acted. Cost beside the same sleeve
  without them: -0.18 to +0.10 Calmar (it IMPROVED S1 SOL 6H from 1.04 to 1.22); flagged above 0.1 Calmar only on S1+VC DOGE 4H at the Reference
  and Aggressive tiers (at Trader exactly 0.10). The Turtle ladder cost no sleeve more than 0.02 Calmar beside no ladder; the Reference ladder in
  its place is worse on SOL S1 (0.76 against 1.22) and no better elsewhere.
- Variants (size-neutral rule, each alone at Trader with brakes on): the +1 R add counted on S1+S5 BTC 6H only (Sharpe 1.03 to 1.24, Calmar 0.74 to
  0.95, 21 adds, worst case at the stops 1.52 R on average and 1.73 R at most) and lost on the four others; the +2 R half scale-out counted on the
  two SOL sleeves (Calmar 1.22 to 1.96 and 1.39 to 2.22) and lost on the three others; `trail2` / `trail3` lost everywhere; the wider stop counted on
  DOGE only; dropping the time stop counted on S1 SOL (no change: it never fired), S1+VC BTC 4H (0.58 to 0.78) and DOGE; the conviction split FAILED
  its pre-registered test (pooled: 46 high-conviction trades at 0.12 R against 277 at 0.25 R). Nothing changes in any account: a variant that counted
  is a candidate for a pre-registered forward test, an owner decision.
- Costs (fixed replays of the selected rule, Trader, brakes on): at 0.20 % a round trip the BTC sleeves gain (Calmar 0.74 to 0.90 and 0.58 to 0.66);
  at 0.50 % the altcoin sleeves keep their shape (SOL S1 1.22 to 0.94, SOL S1+S5 1.39 to 1.16, DOGE 0.67 to 0.62).
- Fleet rows recorded for plan row R18b: the five configurations at the Trader tier (brakes on, no variant) and the TF forward control on BTC-USDT
  and ETH-USDT 6H (Reference sizing, fixed rule). The shortlist file and the 24 running accounts are untouched.
- Two things to know: (1) the study's first run had a timestamp-unit bug in the brakes' calendar (stored 4H candles carry millisecond timestamps,
  read as nanoseconds, so every 4H bar fell on one day and the one-entry-per-day cap blocked almost every 4H entry); its own brake counts exposed
  it, the calendar was fixed (and tested on both units) and the whole study re-run with the pre-registration unchanged; both runs' holdout openings
  are in the append-only ledger. (2) The runner opens the holdout for any cell that passes the gates, and the TF forward control passed at the
  Trader and Aggressive cells on BTC-USDT 4H and 6H, so its 12 months were opened there although the pre-registration listed only the configurations
  and the hold controls; recorded in the ledger, no verdict (TF is never judged); the job planner now excludes the TF controls from the holdout.

## Unreleased — R17: paper-fleet hygiene — public positioning data for the replication markets and honest "filter without data" labels (plan row R17)

Fleet and research code, tests and docs only (`research/`, `scripts/run_paper_fleet.py`, `tests/`, `docs/`): nothing under `app/`,
`config/` or `migrations/` changed; `app/execution`, `app/risk`, `app/exchange` and `app/shadow` are untouched, and the app's
allowlists (`app/okx/client.py`, `app/datalake/derivatives.py`, `app/datalake/binance_public.py`) are not widened. The trading
safety contract is unchanged; the demo shadow run and its caps are untouched. Simulation only: nothing here places, sizes or
approves an order.

### Added
- `research/positioning_data.py`: a research-side, GET-only fetch of OKX's PUBLIC funding-rate history and rubik open-interest
  history for the replication study's swaps (`research.markets.RESEARCH_SWAP_FOR`), through the path-allowlisted
  `OKXPublicRest` with the app's own path constants and row parsers but without the app's BTC/ETH instrument bound (the R12
  precedent, `research/replication_data.py`); it refuses BTC/ETH and anything unknown before any request. Checked live on
  2026-11-05: both endpoints answer for SOL-USDT-SWAP and DOGE-USDT-SWAP in the BTC/ETH row format.
- `research/paper_fleet/data.py`: `positioning_status`, the S5 filter's data label at one bar — each series `current` (a value at
  or before the bar's open, at most one of its own periods, 8 h funding / 1 h open interest, plus the 30-minute refresh window
  old), `stale` (the filter uses the last known value) or `missing` (that leg passes) — with a plain-words note
  (`S5 data current`; `S5 running without data: the filter passes (funding missing, open interest missing)`; or which single
  leg is missing or stale); `MarketData.positioning_status` and `positioning_newest` (newest stored value per market, last
  refresh, its errors).
- Tests: `tests/test_research_positioning_data.py` (recorded responses, bounds, GET-only public paths, the app bound untouched);
  in the fleet tests the feed for a research market with the error line gone and BTC/ETH still on the app path, the label rules,
  the labels in the journal, the state and `--status`, a state written without the labels resuming once the feed serves the
  series (backfill at the resume, later bars "current"), the report's lines, and the pinned fingerprints of the four accounts
  added since R12 next to the R5a ones; `tests/test_research_boundaries.py` covers the new module.

### Changed
- `research/paper_fleet/data.py`: the feed routes the Sprint 2c pair's swaps through the app's collector, unchanged, and every
  other fleet market's swap through the research-side fetch, so the fleet lake gets SOL (and DOGE) funding and open interest.
- `research/paper_fleet/runner.py`: every S5 account's bar record carries `positioning_data` next to the ages; the state carries
  each S5 account's last label and, in `health.positioning`, the newest stored funding / open-interest value per market with the
  last refresh and its errors; `status_from_state` exposes both. Nothing in the rules, the fingerprints or the
  `positioning_source` check changed, so the running fleet resumes after the checkout update.
- `scripts/run_paper_fleet.py --status`: one `positioning data (S5 filter, ...)` line per fleet and the label under each S5 account.
- `research/paper_fleet/report.py`: "In short" names every S5 account whose last bar ran without data, "This week" marks its last
  decision `— S5 without data`, "Data and health" counts such bars since the start (bars from before R17 are read through the
  same rule) and shows the newest stored values per market.
- `docs/runbooks/PAPER_FLEET.md`: the R17 section (what was wrong, what changed, the labels, the resume guarantee, the period in
  which `c11` ran without its filter, the owner's restart step and checks), two troubleshooting rows, the first-hour check.

### For the record
- `c11-s1s5-sol-6h-none` ran without its funding and open-interest data from its creation at 2026-11-04T22:59:50Z (01:00 Beirut
  time) until the restart that picks up this row; when the row was built (2026-11-05 02:03 UTC) the laptop fleet had run 661
  cycles (the four new accounts joined at cycle 480), the account had processed one bar and made 0 trades. The fix reaches the
  running fleet only through the owner's update-and-restart step.

## Unreleased — Trader Plan: a research-backed strategy and risk plan, plan rows R17–R22 (2026-11-05)

Documentation only: nothing under `app/`, `config/`, `migrations/`, `research/` or `scripts/` changed.
The trading safety contract is unchanged; the demo shadow run and its caps are untouched.

### Added
- `docs/TRADER_PLAN_2026-11-05.md`: the owner's request ("profit when right, a slight loss when wrong;
  real-trader risk, not a savings account; tokenized US stocks later; human-like but disciplined risk")
  translated into requirements; the evidence from an 8-question web research sweep (about 270 sourced
  findings: payoff asymmetry and professional trend-following records, the professionals' risk rules,
  pyramiding/scaling/streak sizing, pullback/breakout/ORB/VCP setups, crypto rotation, tokenized US
  stocks on OKX, behavioural evidence, OKX costs and turnover); Trader Policy v1 (three fixed risk
  budgets, a volatility target with a per-trade loss cap, a heat cap, daily/weekly/monthly loss limits on new entries only, a
  Turtle-style drawdown ladder, a −30 % hard stop, bounded adds and a conviction tier as flagged
  variants, pre-registered gates); the setups for research round 3; the expansion path (breadth in
  crypto first; tokenized stocks through a staged, separately approved path); honest expectations;
  what stays non-negotiable. Independently reviewed before commit (four lenses: evidence fidelity,
  safety/scope and buildability, professional-trader critique, owner readability; 80 findings, all
  applied: among them the tier definitions, the lead sleeve's trade rate, the demo pair count, the
  fleet restart time and the fleet loader's source-study guard).
- `docs/PLAN_STATUS.md`: rows R17–R22 (fleet hygiene; Trader Policy v1; research round 3; breadth and
  one rotation test; tokenized stocks feasibility and log-only collector; fill-cost replay), the
  third-run note, the 2026-11-05 decisions and the questions left to the owner.
- `docs/OWNER_CHECKLIST.md`: step 9 (tokenized stocks: the two-minute in-app check), step 10 (the
  risk budget, optional) and step 11 (a one-line go for the R14 part A demo fix); the "meanwhile"
  section updated (24 fleet accounts since 2026-11-04 23:00 UTC; the runner's third run).
- `docs/MASTER_PLAN_2026-10-20.md`: a 2026-11-05 status-log entry pointing at the Trader Plan.

### Found
- The laptop paper fleet's positioning refresh asks the app's BTC/ETH-only derivatives collector for
  SOL-USDT-SWAP and DOGE-USDT-SWAP and logs `not allowed` every 30 minutes; the SOL S1+S5 account's
  funding filter therefore passes for lack of data (plain S1 in effect). Row R17 fixes it inside
  `research/paper_fleet/`; no fleet trade was affected (0 trades at the time).
- OKX's demo environment lists 19 tokenized-stock USDT pairs (instruments with the "Stocks" category
  and an X-prefixed `-USDT` id; public instruments endpoint with the demo header, 2026-11-05).

## Unreleased — R15: reviewed migration workflow and database backups, tooling only (plan row R15)

Tooling and documentation only. No schema change; nothing under `app/`, `config/`, `migrations/` or
`alembic.ini` changed; `app/execution`, `app/risk`, `app/exchange` and `app/shadow` are untouched. The
trading safety contract is unchanged. Nothing here was run on the VPS (agents cannot reach it): the
runbook gives the owner the exact steps.

### Added
- `scripts/db_backup.sh`: `backup` (a `pg_dump --format=custom` archive written to a temporary file, read
  back with `pg_restore --list` before it counts, renamed atomically, SHA-256 checksum next to it, then
  retention: dumps older than `DB_BACKUP_RETENTION_DAYS` (14) are removed, never the newest
  `DB_BACKUP_KEEP_MIN` (7), never after a failure, never a file the script did not write); `verify`
  (checksum + archive listing); `restore-drill` (restores a dump into a NEW scratch database, compares every
  table's row count with the live database — which it reads only, inside a read-only transaction — prints
  the Alembic revision inside the dump and drops the scratch database; `--keep` leaves it); `list`. The
  password inside `DATABASE_URL` is moved into `PGPASSWORD` so it is on no command line, and every printed
  tool message passes a redaction filter. `latest.json` and `history.jsonl` record each run. Exit codes:
  0 ok, 1 the dump/verification/drill failed (the timer retries the next night), 2 a setup problem.
- `deploy/systemd/db-backup.service`, `db-backup.timer` (02:30 UTC nightly, `Persistent=true`),
  `db-backup.env.example`: a confined oneshot in the repository's existing pattern (`StateDirectory`
  `/var/lib/ai-trading/db-backups` the only writable place, the checkout's `.env` unreachable, no
  capabilities, nice/idle I/O) with its own root-owned environment file holding the one secret.
- `tests/test_db_backup.py`: the script under bash with stub `pg_dump`/`pg_restore`/`psql` placed first on
  PATH (the dump, checksum and status files; the password on no command line and in no printed line; a
  failed or unreadable dump discarded with nothing pruned; the retention rules; libpq-variable mode; verify
  against a changed file; the drill's statements — `CREATE`/`DROP DATABASE` only on the scratch name,
  `SELECT count(*)` read-only on the live one — `--keep` and the failure paths), the units' confinement, the
  env example, and the runbook's contents. Skipped where bash is missing; CI (Ubuntu) runs them.

### Changed
- `tests/test_migrations.py` (tightened, not rebuilt): the SQLite comparison now also compares column types
  and server defaults (`compare_type=True`, `compare_server_default=True`; both green on the baseline). New
  tests: `alembic check` is clean after an upgrade and raises on a drifted database; the owner path is
  rehearsed (`create_all` database → `stamp head` → `check` clean → `upgrade head` a no-op); the runbook names
  this guard.
- `docs/runbooks/DB_MIGRATIONS.md` rewritten as the owner runbook: what the VPS runs on (`create_all` at every
  start; `main` at `57f89c0` has no Alembic, so its database has no `alembic_version` table and revision 0001
  is not stamped; `app/db/models.py` is identical on `main` and `plan/auto`, so the stamp will match), the
  two guards (`tests/test_migrations.py` and `alembic check`), the backup install, the restore drill, the
  stamp, the procedure for every future revision (backup and drill first, flat if possible, `alembic check`
  and `--gate-check` after), rollback and disaster restore with the reconciliation consequence
  (`POSITION_PERSISTENCE.md`, scenario 16), day-to-day checks, off-host copy options, troubleshooting.
- `docs/runbooks/VPS_8443_UPDATE.md` (post-merge step 3) and `docs/OWNER_CHECKLIST.md` (item 3) now point
  to that runbook: back up and drill before the stamp, `alembic check` after it.

### Verified (2026-11-04, throwaway PostgreSQL 16.15 container, the major version Ubuntu 24.04 ships)
- `alembic upgrade head` then `alembic check`: clean. A database built by `create_all`, then `stamp head`,
  then `check`: clean (`check` before the stamp says "Target database is not up to date").
- The script against the real server: backup (241 archive entries), verify, list, restore drill (24 tables,
  1,000 inserted candles counted on both sides, scratch database dropped), files mode 600, also as a
  non-root user; a percent-encoded password (`p%40ss%3Aw%2Frd`) authenticates through `PGPASSWORD`; a wrong
  password fails with a redacted message, `"status":"failed"` and nothing pruned; retention removed six
  twenty-day-old dumps and kept the newest two with `DB_BACKUP_KEEP_MIN=2`.
- Both units pass `systemd-analyze verify` on systemd 255 (Ubuntu 24.04); the calendar expression
  normalizes to `*-*-* 02:30:00 UTC`.

## Unreleased — R13: research round 1, three pre-registered entry conditions on the unchanged Sprint 2c rules (plan row R13)

Research only, public data only, pre-registered before the first run. Nothing under `app/`, `config/`,
`app/execution`, `app/risk`, `app/exchange` or `app/shadow` changed; the existing strategies' parameters,
grids and brackets are untouched. The trading safety contract is unchanged.

### Added
- `research/strategies/round1.py`: the three rules — H1 `S1+BT` / `S2+BT` (ETH's S1 / S2, new entries
  only while BTC's S1 trend is up), H2 `S1+VC` (S1, new entries only on a 30-day volume z-score above 1),
  H3 `DM-BTC` / `DM-ETH` (dual-momentum legs: long their own market only while both S1 trends are up and
  it is the stronger 90-day performer; mutually exclusive by construction) — all entries-only conditions
  with fixed, never-gridded parameters; `CrossAssetContext`, a feature context that carries the other
  market's candles, aligned by exact timestamp, failing closed where a bar is missing and raising when
  the reference is absent. Registered in `research/strategies/__init__.py` with `ROUND1_BASES`.
- `research/round1.py`: the pre-registration (hashed file, checked against the module's text at every
  run), the Sprint 2c runner loaded as a module with its feature context replaced by the cross-asset one
  (nothing else copied), the protocol check, one process-pool job per series and strategy group, the
  hold/S1/S2 reproduction through the patched context, the H3 combination (legs' returns multiplied bar
  by bar, pooled trades, the smaller robustness share), the legs' holdout simulated as the runner does it
  (checked against the runner in the tests), the comparison of every new configuration with its base
  rule, the pre-registered verdict labels and failure facts, the append-only ledger and the fleet
  shortlist additions (a confirmed H3 adds both legs, together one position).
- `research/report_round1.py`: the report; every sentence, including each failure analysis's reading, is
  computed from the numbers.
- `scripts/run_research_round_1.py`: `--preregister` (once), the study (`--evaluate-holdout` only for the
  full pre-registered study), `--render-from-json`, `--apply-shortlist-from-json`; a shortlist amendment
  the paper fleet cannot load is rolled back.
- `docs/research/research_round_1_preregistration.json` (written 2026-11-04 18:37 UTC, before the first
  run), `docs/research/RESEARCH_ROUND_1_REPORT.md`, `docs/research/research_round_1_results.json`,
  `docs/research/research_round_1_holdout_ledger.json`.
- `tests/test_research_round1.py` (the rules' entries-only and fail-closed behaviour, the legs' mutual
  exclusion, the Sprint 2c rules unchanged under the cross-asset context, the patched runner and protocol
  check, the combination, the leg holdout against the runner's own, an end-to-end quick study on a
  synthetic two-market lake, the pre-registration file, the verdict rules, the ledger, the shortlist
  additions and rollback, the report's sentences, the CLI); a boundary test for the round-1 files.

### Result
Official run 2026-11-04 18:50 UTC (4.4 min on 12 workers; a holdout-free dry run minutes earlier gave
identical walk-forward numbers for all 48 configurations and legs). The hold/S1/S2 reproduction through
the cross-asset context matched Sprint 2c's stored numbers in 20 of 20 configurations. 20 configurations
judged. **H1** (ETH's S1/S2 only while BTC's S1 trend is up): failed walk-forward, 0 of 8 — beside the
base rules the condition changed little (median Calmar 0.36 → 0.30, a median 19 % of trades removed;
the HMM gate already does most of what a BTC-trend condition does). **H2** (S1 with new entries only
on a 30-day volume z-score above 1): 1 of 8 passed — S1+VC BTC-USDT 4H with the regime gate, Calmar
0.55, Sharpe 0.71, +4.3 %/yr at a 7.8 % drawdown, 83 trades, 82.9 % of rolling 12-month windows
positive, robust to ±30 % parameter changes — and the untouched 12 months confirmed it (+2.0 %, PF
1.41, 25 trades); the condition raised Calmar in 6 of 8 configurations (median 0.29 → 0.33) and
removed a median 46 % of S1's trades, but on 6H and on ETH it did not pass. **H3** (dual momentum
between BTC and ETH, judged as the one-position curve): failed walk-forward, 0 of 4 — median Calmar
0.11 against 0.31 for the better plain S1 rule, 57 trades a year against 35; the switches added
trades and fees without return. The confirmed configuration joins the paper fleet's shortlist as
row 13 (`c13-s1vc-btc-4h-gate`, source tag `R13 research round 1`); the fleet loads 23 accounts
(tested), existing accounts and fingerprints unchanged. Caveats, in the report: one pass among 20
comparisons, just above two gates, a rule selected in 2 of 9 windows, and a holdout whose falling
direction was known before the study — the forward fleet is the judge. Nothing authorizes trading.

## Unreleased — R12: replication of the Sprint 2c rule families on markets they were never tuned on (plan row R12)

Research only, public data only, pre-registered. Nothing under `app/`, `config/`, `app/execution`,
`app/risk`, `app/exchange` or `app/shadow` changed; the app's instrument allowlist (which also bounds
demo and paper trading) was not widened. The trading safety contract is unchanged.

### Added
- `research/markets.py`: the candidate markets (public 1H history from before 2020-01-01, plus
  SOL-USDT), their Binance perpetual symbols and OKX swaps — tables only.
- `research/replication_data.py`: two bounded, resumable, GET-only collectors through the lake's
  public clients — OKX 1H and 4H spot candles for the markets (into `candles/<inst>/<bar>`) and
  Binance public funding for their perpetuals (into the existing external layout); a one-GET
  history probe; funding coverage.
- `research/replication.py`: the pre-registration (hashed with the market snapshot and the
  configuration), the ranked market selection from one public ticker snapshot, the frozen study
  lake (every candle series cut at Sprint 2c's data end so the untouched 12 months are the same
  calendar window), the Sprint 2c runner loaded as a module (its own `run_series` runs every
  market; nothing is copied), the protocol check of its defaults against the stored Sprint 2c
  run, the BTC/ETH reproduction check (6 decimals, trade counts, selected rules, gate verdicts),
  the pre-registered verdict rules, the append-only holdout ledger, and the fleet shortlist
  additions with a `source` tag.
- `research/report_replication.py`: the report; every plain-English sentence is computed from the run.
- `scripts/run_replication_v1d.py`: `--preregister` (once), `--collect`, `--freeze`, the study
  (`--evaluate-holdout` only for the full pre-registered study), `--render-from-json`,
  `--apply-shortlist-from-json`; a shortlist amendment the paper fleet cannot load is rolled back.
- `docs/research/replication_v1d_preregistration.json` (the snapshot of 2026-11-04 16:32 UTC and
  the chosen markets, hashed), `docs/research/REPLICATION_V1D_REPORT.md`,
  `docs/research/replication_v1d_results.json`, `docs/research/replication_v1d_holdout_ledger.json`.
- `tests/test_research_replication.py` (selection rule, collectors with fake GET-only sessions,
  the frozen lake, the loaded runner and its protocol check, an end-to-end quick run on a
  synthetic lake, the verdict rules, the ledger, the shortlist additions and rollback, the report,
  the CLI); a boundary test for the study's files; fleet tests for the source-tagged rows and a
  third market.

### Changed
- `research/data.py`: `positioning_context` looks a market up in the research symbol table only
  when the app's table does not know it (nothing changes for BTC/ETH; the reproduction proves it).
- Paper fleet (`research/paper_fleet/config.py`, `data.py`, `replay.py`, `scripts/run_paper_fleet.py`):
  a shortlist row with a `source` tag is validated against that study's results file and becomes
  one more sleeve account; the fleet's allowed markets include the study's markets (the app's
  `ALLOWED_INSTRUMENTS` is untouched); their OKX swaps feed the S5 filter; market data is fetched
  for the markets the accounts need instead of a fixed pair; the dry run's synthetic market covers
  every such market. Existing accounts, the fleet's shared rules and every fingerprint are unchanged
  (tested), so a running fleet resumes and takes the new accounts at its next restart.
- `docs/research/paper_fleet_shortlist_v1c.json`: rows 11 and 12 — S1+S5 and S1 on SOL-USDT 6H
  (no regime gate), the two configurations the study confirmed — with a `source` tag and an
  `amendments` record; rows 1–10 and the controls are byte-for-byte what they were.
- `docs/RESEARCH_LAB.md` (the R12 section), `docs/DATA_LAKE.md` (the research-side collectors),
  `docs/runbooks/PAPER_FLEET.md` (22 accounts; how a confirmed configuration joins), `docs/PLAN_STATUS.md`,
  `docs/OWNER_CHECKLIST.md` (the laptop fleet takes the two accounts after a pull and restart).
- `app/ops/okx_usage.py` (the changelog watcher's watch list, plan row R6): one entry for the public
  `GET /api/v5/market/tickers` endpoint the pre-registration snapshot used, so the watcher flags
  changelog entries about it (the watcher's own test requires every OKX path in the code to be listed).
  No other file under `app/` changed.

### Result (simulation)
- Markets fixed before any result: XRP, DOGE, LINK, TRX, ADA, LTC (top 6 of eleven pre-2020
  candidates by 24-hour quote volume) and SOL. All 36 BTC/ETH reproductions matched Sprint 2c.
- **Fragile.** 10 of 104 judged configurations passed every Sprint 2c gate on a new market; none of
  the three BTC passers of Sprint 2c replicated (needed 4 of 7 markets). The untouched 12 months
  confirmed 2 (S1 and S1+S5 on SOL 6H: +9.5 %, PF 5.5, 12 trades — the same trades), contradicted 7
  (TRX, ADA, DOGE 6H) and left DOGE S2 4H gate unconfirmed for lack of trades (+1.7 %, 8 trades).
  Median Calmar on the new markets stayed below BTC's for every family; LTC was negative for every
  rule; hold + policy sizing lost on every market's 12 months. DOGE's funding coverage (89.5 %) fell
  under the Sprint 2b threshold, so its S5 configurations were reported as run without S5.

## Unreleased — Second plan run on Fable 5.1, paper fleet started, 8443 runbook corrected (2026-11-04)

At the owner's go ("do the next appropriate steps without the need of my decisions ... all on
Fable max"). The trading safety contract is unchanged; nothing under `app/execution`, `app/risk`,
`app/exchange`, `app/shadow` or `config/` changed.

### Added
- `docs/OWNER_CHECKLIST.md`: the owner's remaining steps (G1–G5, the Telegram token, the stale
  `demo` row, the stale pull request #7) in order, with copy-paste commands and what each unlocks.
- `docs/PR_PLAN_AUTO.md`: the ready-to-paste text of the one pull request from `plan/auto` into
  `main` (plan row G2).
- `scripts/paper-fleet-task.ps1` and runbook option B2: the paper fleet as a Windows scheduled
  task from its own checkout; started on the owner's laptop on 2026-11-04 (plan row G6).
- Plan rows R4e, R12, R13, R14, R15 and R16 in `docs/PLAN_STATUS.md` (section 0) for the second
  unattended run; the owner's 2026-11-04 decision recorded in section 2.
- `scripts/watch_okx_changelog.py`: `OKX_CHANGELOG_NOW` (tests only) pins the watcher's clock.

### Changed
- `scripts/plan-runner.ps1`: a `-Model` parameter; the default model is Fable 5.1 (was Opus 5.5).
- `docs/runbooks/VPS_8443_UPDATE.md` rewritten: the OKX WebSocket URLs are part of the fixed demo
  account identity (`app/execution/identity.py`), so moving off port 8443 needs a new account name
  (`demo-shadow-1h-443`) and a flat position; the old Path A ("works with the code deployed today")
  would have made the existing account refuse to start. Also records that OKX still answered on
  port 8443 on 2026-11-04 with a "will be retired soon" notice.
- `docs/runbooks/PAPER_FLEET.md`: option B2 (Windows scheduled task, separate checkout), and how to
  move a running record to the VPS.

### Fixed
- `tests/test_okx_changelog.py`: one test compared the fixture's entry dates with the real clock
  and began failing on its own on 2026-10-29 (the fixture was recorded 2026-10-22; the oldest
  flagged entry left the 30-day first-run window). The two script tests now pin the clock to the
  recording day. Nothing in the watcher's behaviour changed.

## Unreleased — Travel mode removed (owner, 2026-10-22)

At the owner's request the AgentOps travel-mode tooling is gone. The trading safety contract
(demo-only, SPOT long-only at 1x, the risk manager's final veto, fail-closed, no LLM order
authority, PR-only merges by the owner) is unchanged.

### Removed
- `scripts/check_travel_mode_safety.py` (the CI safety guard), its tests and the `TRAVEL_MODE`
  switch (`.env.example`, CI).
- `.github/workflows/notify.yml` (CI → Telegram pings), the CI summary artifact it read, and the
  `ci_pass`, `ci_fail`, `pr_opened`, `pr_updated` and `safety_fail` notifier labels.
- `.github/workflows/claude.yml` (the GitHub Claude PR assistant).
- `docs/TRAVEL_MODE.md`, `docs/GITHUB_SETUP_FOR_TRAVEL.md`, `docs/CLAUDE_ROUTINE_SETUP.md`,
  `docs/agentops_smoke_test.md`.

### Changed
- The CI job is now named `tests` (was `tests + travel-mode safety guard`). The branch
  protection rule for `main` must require `tests` instead (owner step, plan row G2).
- `AGENTS.md` keeps the full list of safety-sensitive paths (it absorbed the guard's list).
  `CLAUDE.md`, `docs/CODE_REVIEW.md`, the plan runner's commit checks and the plan docs no
  longer mention the guard; runner chats now name every changed file under `app/execution`,
  `app/risk`, `app/exchange`, `app/shadow` or `config/` in their report.

## Unreleased — R9: Phase 9 design study, long and short through perpetual swaps without leverage (plan row R9)

Paper only, at the owner's go of 2026-10-21. Phase 9, trading shorts, perpetual swaps and any
derivatives access stay unauthorized and unrepresentable; nothing under `app/`, `config/` or
`deploy/` changed, no key was used, and the trading runtime imports none of this (tested).

### Added
- `research/longshort.py`: a long/short version of the research engine. With no shorts and no
  funding it is `run_vectorized` bit for bit (parity-tested on every overlay); every short exit
  path (stop on the high with gap fills, target, trailing stop on the running low, time stop,
  reduce-only buy-back, end of data) is tested against the long engine on the reflected price
  path; every conflict between the sides falls on the short side, so without the ladder the long
  side trades exactly like the long-only engine (tested on random paths with random shorts);
  funding charged per leg at the close of the bar it settles in; a 1x isolated liquidation
  tripwire and a leverage trace.
- `research/strategies/shorts.py`: the mirror images of S1, S2, S4 and the S5 filter (S1 and S2
  equal the reviewed long rules on the reflected market); a short starts only while the long rule
  is flat and the no-trade filter allows an entry.
- `research/longshort_data.py`: Binance's public funding history as the proxy for OKX's swaps
  (compared with OKX's own funding where both exist), settlement-to-bar assignment (time-unit
  safe: the lake stores milliseconds), OKX's public BTC-/ETH-USDT-SWAP 1H candles collected
  through the GET-only public client into `data/lake/candles/<SWAP>/1H`, basis.
- `research/longshort_study.py`, `scripts/run_long_short_study.py`, `research/report_longshort.py`:
  the pre-registered study (32 configurations: S1, S2, S4, S1+S5 x BTC/ETH x 4H/6H x hybrid and
  all-perp designs) under Sprint 2c's walk-forward, policy sizing and gates; the long-only path
  must first reproduce Sprint 2c's stored numbers (all 16 did); a stricter evidence rule (the v1c
  gates, a profitable short leg on its own, a Calmar above long-only, then a confirming holdout,
  opened only for walk-forward passers, only by the full pre-registered study, and recorded in an
  append-only ledger, `docs/research/long_short_holdout_ledger.json`); diagnostics; the generated
  report, in which every plain-English sentence follows the numbers it states.
- `docs/research/LONG_SHORT_STUDY_REPORT.md`, `docs/research/long_short_results.json`,
  `docs/research/okx_swap_reference_2026-10-22.json` (OKX's public contract, margin-tier and
  funding settings), and `docs/PHASE9_DESIGN_STUDY.md`: the numbers in plain words, sixteen
  proposed extra safety rules, what would change in the system and the review path.

### Result (simulation)
- Adding the mirrored shorts made the trend rules worse in most cases: Calmar above long-only in
  3 of 16 family-and-series pairs (median 0.35 -> 0.05); the BTC short legs lost in 7 of 8, the
  ETH short legs made a little in 6 of 8 (most of it went to fees); 2022 better in 13 of 16 pairs
  but positive in only 4 (median -2.6 % -> -1.5 %).
- 4 of 32 configurations met the walk-forward part of the rule — S2 (Donchian breakout) on ETH 4H
  and 6H, each in both designs. The untouched 12 months confirmed ETH 6H (+2.3 %, 28 trades, the
  gain from its short side) and contradicted ETH 4H (-4.8 %, 42 trades); their direction (a
  falling market) was known before they were opened, so the confirmation is weak.
- Funding flowed from longs to shorts (about 13 %/yr BTC, 16 %/yr ETH, 2020-2025): the hybrid
  design (longs on spot) beat the all-perp design in 13 of 16 pairs.
- Recommendation in the design study: no Phase 9 build now.

### Independent review
- A read-only review found one real defect: a switch from short to long was delayed by one bar
  when the short's stop also fired in that bar (the long side was then not exactly the long-only
  rule). Fixed — a short that the long side needs closes at the open first; a long that gives way
  keeps the long-only stop-first rule — with regression tests, and the study re-run; no rule, gate
  or setting changed and the pre-registration hash is the same. The first run's holdout openings
  (the same verdicts) are the first entry of the ledger. Also fixed from the review: the S5 mirror
  and the S0 filter gate a short in the long side's order; a loss-free leg's profit factor is 999;
  the holdout can only be opened by the full study; every summary sentence is conditional on its
  numbers; the disclosures in the report's method notes.

### Changed
- `tests/test_research_boundaries.py`: the study's files are inside the research sandbox (no
  risk, database, broker, execution or exchange imports; no network library of their own).
- `docs/RESEARCH_LAB.md`: the R9 section; `docs/PLAN_STATUS.md`: section 2.

## Unreleased — R7: FOMC calendar check (plan row R7)

Research data only. The calendar feeds the S0 no-trade filter of the research and the
paper fleet, which blocks NEW entries around FOMC statements; it never touches an exit,
a stop, the kill switch, reconciliation, demo or live trading. The research was not
re-run and the holdout was not touched.

### Checked
- The 57 FOMC decision days of 2020–2026 in `research/events.py` (written from memory in
  Sprint 2c) against the Federal Reserve's published calendar (federalreserve.gov
  `fomccalendars.htm`, last updated 2026-10-07, and `fomchistorical2020.htm`): all 57
  right — every scheduled statement day plus the unscheduled cuts of March 3 and 15,
  2020. By the calendar's rule (meetings only) the cancelled March 17–18, 2020 meeting
  and the notation votes are left out; none of them set rates. The closest call, the
  notation vote of March 23, 2020 (an FOMC statement that started unlimited bond buying,
  rates unchanged), lies only in the first walk-forward window's training data; the rule
  stays as Sprint 2c fixed it. Nothing was corrected, so no Sprint 2c verdict can change
  (paragraph in the owner-decisions section of `docs/research/ENSEMBLE_V1C_REPORT.md`).
  The release time printed on each of the 55 statements so far (2:00 p.m. New York time =
  19:00 UTC in winter, 18:00 UTC in daylight time; the March 2020 cuts at 15:00 and 21:00
  UTC) falls inside its ±6 h window centred on 18:00 UTC.

### Added
- The eight 2027 decision days from the same calendar (January 27, March 17, April 28,
  June 9, July 28, September 15, October 27, December 8): the built-in calendar now ends
  2027-12-08 instead of 2026-12-09. The Fed calls each date tentative until the meeting
  before it confirms it.
- `tests/fixtures/fomc_calendar/`: the Fed's calendar for 2020–2027 as published, one
  entry per line with each page's last-update date, the release time printed on every
  statement so far, the offline parser that made it and how to refresh it.
  `tests/test_fomc_calendar.py` compares the built-in calendar with it, checks that the S0
  filter blocks the 2027 meetings and that every published release time falls inside its
  window; a paper-fleet runner test shows that
  a fleet started on the old calendar resumes after a restart, blocks the 2027 meeting and
  keeps journals identical to a fleet that always had the new calendar.

### Changed
- `research/events.py`: the description records the check and its source, and gives
  winter and daylight time the right way round (wording only; no window moves).
- `research/paper_fleet/report.py`: the "FOMC calendar runs out" line says how to extend
  the calendar instead of pointing at plan row R7. The fleet's fingerprints do not cover
  the calendar's dates (the shared rules name the filter, `FOMC±6/6h`), so a running fleet
  resumes in its folder and picks up the 2027 dates at its next restart
  (`docs/runbooks/PAPER_FLEET.md`).
- `docs/RESEARCH_LAB.md`, `docs/runbooks/PAPER_FLEET.md`: the calendar is checked data;
  what a running fleet needs.

## Unreleased — R6: daily ops digest and OKX changelog watcher (plan row R6; master plan sections 5.4 and 9)

Observability only: both tools read files and one public web page, hold no OKX keys,
never open the demo database and cannot reach an order, a stop, the kill switch or
reconciliation; nothing in the trading runtime imports them. `app/notify`, `app/shadow`
and the safety core are unchanged.

### Added
- `app/ops/digest.py`, `scripts/ops_digest.py`: a plain-English daily digest (07:00
  Beirut) from the files the services already write — the Phase 6a heartbeat,
  `state.json`, `ALERT` and the day's journal with its ledger mirror (signals, risk
  decisions, fills and cash result after fees, reconciliations, uptime, restarts), the
  news shadow's state, spend and the day's numbers through its own
  `build_report_data`, the paper fleet's saved state, and the changelog watcher's
  state. Fixed rules list what needs attention (ACTION: an `ALERT`, a heartbeat older
  than 10 minutes, no candle closed for 2.5 hours, an inconsistent reconciliation, an
  unreadable `ALERT`/`state.json`/heartbeat, a failed news safety check, a stopped news
  shadow or fleet; CHECK: hours of downtime (missing candles), process starts and
  restarts, runtime errors and notable events such as a deferred exit, the
  market-continuity pause, uptime below 95 % while running, the kill switch, an
  incompletely read journal, AI spend above 80 % of the cap, stale fleet prices, a fleet
  drawdown ALARM, new or undelivered changelog flags, a blind or missing watcher). The
  heartbeat, the `ALERT`/state files and the journal are read independently and record
  by record, so a broken journal never hides a halt; downtime and uptime rules wait for a
  complete journal, a day that is not over only expects the hours that passed, and "no
  candle since a restart" is timed from the restart. Sent through the existing Telegram
  notifier in pieces under Telegram's size limit before it is saved under
  `logs/ops/digest/`; `TELEGRAM_DRY_RUN` honoured. A missing or broken file is one line,
  never a missing digest. Without `--send` it only prints; `--dry-run` checks the whole
  path offline on the bundled fixtures.
- `app/ops/digest_ai.py`: an optional Claude Opus 5.5 summary after the NEEDS ATTENTION
  list, only when `ANTHROPIC_API_KEY` is set and no ACTION line exists, through the news
  agent's client builder and spend guard with its own cap (`OPS_DIGEST_AI_MONTHLY_CAP_USD`,
  default $3). Dropped on a refusal, a cut-off, empty, over-long answer, a link or web
  address, or any number (with its sign) that is not in the digest; the template is sent
  either way. No server-side fallback model (the spend guard reserves one model's worst
  case).
- `app/ops/okx_changelog.py`, `app/ops/okx_usage.py`, `scripts/watch_okx_changelog.py`:
  a daily watcher of https://www.okx.com/docs-v5/log_en/ (one GET, host pinned,
  redirects refused, size capped). It splits the page into its entries (date groups,
  "Upcoming Changes", h2/h3 entries, older plain groups), remembers each entry's id and
  text hash, and flags new or edited entries that mention a host, port, REST path, doc
  anchor, WebSocket channel or authentication rule this repository uses (the watch list
  is kept in step with the code by a test; hidden characters are removed before matching,
  and negated wording such as "will not be deprecated" is not ranked as a deprecation).
  First run = silent baseline plus the upcoming changes and the last 30 days; a page where
  most entries look new at once is a new baseline with one notice; an alert or notice that
  was not delivered (Telegram down, or a dry run) is sent again for 7 days, also on days
  the page cannot be read; a block page, a
  shrunken page or a fetch failure is a failed check that keeps the known entries, with
  one alert after 3 in a row. Without `--send` it is a preview that saves nothing. Checked
  live on 2026-10-22: 449 entries; the first check flags the port-8443 shutdown and the
  coming SBE services.
- `research/paper_fleet/digest.py`: the fleet's facts for the digest, read-only through
  `status_from_state` and the weekly report's own verdicts (`build_report_data`).
- `deploy/systemd/ops-digest.{service,timer}`, `okx-changelog-watch.{service,timer}`
  (oneshot, 07:00 and 06:30 `Asia/Beirut`, `Persistent=true`, write access to `logs/ops`
  only, the repository `.env` and the PostgreSQL socket unreachable),
  `deploy/systemd/ops.env.example`, `docs/runbooks/OPS_DIGEST.md` (with cron lines as an
  alternative).
- Tests: `tests/test_okx_changelog.py`, `tests/test_ops_digest.py`,
  `tests/test_ops_digest_ai.py`, `tests/test_ops_boundaries.py` (offline; synthetic page
  fixtures under `tests/fixtures/okx_changelog/`).

## Unreleased — Sprint 5b: portfolio allocator v2 (plan row R5b; master plan Sprint 5 item 2)

Simulation only, in `research/` and the paper fleet; `app/risk` (the demo and live
risk manager) is unchanged and stays the reviewed core. Nothing here can reach an
order, and a good backtest or forward record approves nothing.

### Added
- `research/allocator.py`: allocator v2 = the Sprint 2c jointly sized portfolio
  (trailing inverse-vol weights, 15 % portfolio vol target, 7.5/15 % drawdown
  ladder with its 30-day cooling-off, on v2's own equity) times brakes between 0
  and 1: a correlation cap (sleeves on one coin, or BTC and ETH while their 60-day
  correlation is ≥ 0.70, are one bet; a bet above 50 % of equity at the previous
  close is scaled back to 50 %; entries during a day count from the next close),
  a weekly loss limit (−5 % over 7 days → cash) and a 7-day cooldown after it.
  Set before the study first ran (`DEFAULT_ALLOCATOR_V2`), sized from the
  previous close only; one step function shared by research and the fleet; a
  paired "v1 on the same sleeves" reference; with every brake off it equals
  `combine_sized` to floating-point rounding.
- `research/allocator_study.py`, `scripts/run_allocator_v2.py`: rebuild the six
  sleeves of the v1c portfolio with their daily positions, stop unless v1
  reproduces Sprint 2c's stored numbers (it does, to 1e-6), run v2 and two
  ablations, apply the unchanged v1c portfolio gates, and open the 12-month
  holdout only after a walk-forward pass. Results:
  `docs/research/ALLOCATOR_V2_REPORT.md`, `docs/research/allocator_v2_results.json`.
  Walk-forward 2021-06 → 2025-10: v2 +10.5 %/yr, max DD 12.3 %, Sharpe 0.86,
  Calmar 0.85 against v1 +10.9 %, 13.2 %, 0.82, 0.83; both pass. Holdout
  (364 full days 2025-10-21 → 2026-10-19, a bear market, BTC −26 %, ETH −39 %):
  v2 −9.2 %, v1 −15.0 %; neither confirmed.
- Paper fleet: `PortfolioSpec.allocator` (None = v1, rules and fingerprint
  unchanged) and a 20th account, `pf-s1s2s4-btceth-vt15-alloc2`, on the same
  six sleeves with its own journal and the study's expectations; its journal
  books v1 on its own sleeves beside it. Fleets created by the R5a code resume:
  their state is migrated to version 2 (portfolio states keyed by account id),
  the 19 accounts continue unchanged and the new account joins from its own
  start. Shared sleeves decide once per bar. A portfolio account's sleeves
  continue from their warm-up, a fleet is created and an account joins only once
  its series are ready (the bar that closed last is complete and no earlier bar is
  still waiting for a late candle; else exit 3, retry), and a journal left by an
  interrupted start is set aside. The weekly report gains an
  allocator section (v2, v1 on the same sleeves, the v1 account, every brake
  that acted, the state now, the research expectations); the dry run checks
  that v2's brakes only lower its own sizing; `--status` shows the allocator's
  state.
- Tests: `tests/test_research_allocator.py`, `tests/test_research_allocator_study.py`,
  and new cases in the paper-fleet config, portfolio, runner and report tests
  (pinned R5a fingerprints, research/fleet parity, resuming a fleet written by the
  real R5a code from `tests/fixtures/paper_fleet_r5a`, joining on lagging data,
  an interrupted start).

## Unreleased — Sprint 5a: paper fleet (plan row R5a; master plan Sprint 5 item 3)

Simulation only: every fill is virtual arithmetic on public OKX prices; no keys,
no demo account, no database, no order path. Nothing in the trading runtime
imports it. A good forward record approves nothing (plan row G7 decides).

### Added
- `research/paper_fleet/`: the Sprint 2c shortlist run forward on live PUBLIC OKX
  data as 19 local paper accounts — the 10 shortlisted configurations, the jointly
  sized BTC+ETH × S1/S2/S4 portfolio (15 % vol target, 7.5/15 % ladder) as one
  account, and 8 controls (always long with the policy sizing; plain buy-and-hold;
  BTC and ETH, 4H and 6H) — each with its own append-only journal.
  - `config.py`: the manifest from the shortlist and `ensemble_v1c_results.json`
    (rules, expectations, the portfolio's six full-size sleeves), checked against
    each other; a rules fingerprint makes a changed fleet refuse to resume.
  - `signals.py`: one decision per closed bar through the reviewed `Strategy`
    contract (`ResearchStrategyAdapter`: candidate, S5 filter, S0 filter with the
    FOMC calendar) plus the regime-v2 entries-only gate, the policy sizing
    fraction and the exit bracket; every decision is journaled with its signal
    and why each filter allowed or blocked it.
  - `engine.py`: a bar-by-bar transcription of `research.engine.run_vectorized`
    with JSON state and the walk-forward's 180-day test windows (every sleeve
    restarts flat, closing at the window's last close with costs; plain
    buy-and-hold never does); a missing decision keeps stops working and makes
    no entry.
  - `regime.py`: the regime model forward with the walk-forward geometry (540
    days ending 7 days before each 180-day period), stored so restarts reuse it;
    a failed fit blocks entries.
  - `portfolio.py`: UTC-day sleeve returns, trailing inverse-vol weights and the
    vol target over 120 days of warm-up plus the forward days, the ladder from
    the forward start (`combine_sized` semantics).
  - `data.py`: OKX public candles, funding rate and open interest through the
    GET-only allowlisted `OKXPublicRest`; the fleet's own lake (the research lake
    is only read, once, to seed it); 4H/6H bars rebuilt from confirmed 1H candles.
  - `runner.py`, `store.py`: the cycle (every new bar of every series in one time
    order, catch-up after downtime identical to live running, a missing candle
    waited for until 90 minutes after the next bar closed, then that bar is
    skipped with a note), sequence-numbered journals written before the atomic
    state (a crash never duplicates a record), one instance per directory, a
    shortlist that later adds an account (it starts then) or drops one (retired,
    journal kept) without restarting the record.
  - `report.py`: `reports/weekly-YYYY-Www.md`, controls first, with bands fixed
    before the first forward bar: return ± 2σ of the walk-forward volatility,
    Sharpe ± 2 standard errors (from 90 days), drawdown against the walk-forward
    worst (alarm at 1.5×), a Poisson band on trades, the holdout pace; verdicts
    from 30 days; a warning before the built-in FOMC calendar runs out.
  - `replay.py`: the offline dry run (recorded lake data or a synthetic market,
    simulated clock, invariants checked).
- `scripts/run_paper_fleet.py`: `--loop` (service), `--once`, `--dry-run [--days]
  [--out] [--synthetic]`, `--report [YYYY-Www]`, `--status`; exit 2 for setup
  problems (another instance, changed rules, bad option).
- `deploy/systemd/paper-fleet.service` (+ optional, secret-free
  `paper-fleet.env.example`): writes only `logs/paper_fleet`, cannot read `.env`
  or reach the PostgreSQL socket, `Nice=10`, 50 % CPU, 2 GB memory.
- `docs/runbooks/PAPER_FLEET.md` (VPS service or this laptop, reading the report,
  troubleshooting); a Sprint 5a section in `docs/RESEARCH_LAB.md`.
- Tests (offline): engine parity with the vectorized engine on every exit path;
  contract decisions equal to the research frames (S0, S5, brackets, regime gate,
  sizing); a gated policy-sized sleeve end to end against `simulate_sizing`;
  portfolio booking against `combine_sized`; regime fit geometry and exact JSON
  round trip; public-data parsing, GET-only public paths, seeding without
  touching the research lake, gaps; the runner on a replayed market (anchors,
  restart and crash equivalence, changed rules, the lock, gaps, failed decisions,
  stale data); the report's bands and verdicts; the CLI; import boundaries.

### Changed
- `research/strategies/adapters.py`: `fallback_stop_pct=None` keeps the research
  convention (no stop distance → a `LONG` signal without a stop, as for the
  always-long control). The default (3 % fallback stop) is unchanged.
- `tests/test_research_boundaries.py` also scans `scripts/run_paper_fleet.py`.

### Fixed (found by the independent review of this step)
- The always-long controls (and any long-held position) could only shrink: the
  research restarted every account flat at each 180-day test window, which is
  where reduce-only sizing was set again. The fleet now restarts the same way
  (parity-tested window by window against the research engine).
- A cycle whose save failed kept its advanced state in memory, so the next
  save could skip journal records; it now reloads the last saved state and
  redoes the cycle.
- Weekly reports of a past week were never rewritten as "final".
- A fleet could be created from failed or stale public data (the portfolio's
  warm-up is built once, at creation); it now refuses and the service retries.
- A resume with another `--positioning-source` silently changed the S5
  accounts' input; it is refused.
- The missing-candle grace never waited; it now waits until 90 minutes after
  the next bar closed.
- The Sharpe band used the per-period formula on an annual Sharpe; it is now
  `sqrt((1 + SR^2 / (2q)) / years)`.
- A journal line torn by a crash could swallow the next record; it is closed
  first.
- Run as a script the fleet keeps `python-dotenv` from loading the repository
  `.env` into its process; another instance holding the fleet, or data not
  ready, exits 3 so systemd retries (exit 2 stays for changed rules).
- Candidates with their own exits (S3's time stop) are refused instead of
  silently losing that exit.

### Verified live (public data only)
- Two live sessions on this laptop against OKX's public REST (no keys): 11:35–12:11
  and, with the final code, 11:38–12:13 UTC on 2026-10-21. Each created the
  19-account fleet in seconds (the research lake's history copied, then topped up
  from OKX in 6 requests), processed the 12:00 UTC bars of BTC/ETH 4H and 6H about
  45 seconds after the hour (regime models fitted for BTC 4H, ETH 4H and ETH 6H,
  S5 decisions on OKX funding and open interest at most 6 hours old, every
  decision journaled), wrote the weekly report, about 130 MB of memory, zero
  errors; a further `--once` resumed the live fleet and a resume with another
  `--positioning-source` was refused (exit 2). No fill happens before the bar
  after a fleet's first bar (16:00/18:00 UTC here), so fills were verified offline:
  the default `--dry-run` replays the last 3 recorded days of the research lake
  through all 19 accounts with every invariant check passing.

### Not done here
- The fleet is not started 24/7 (plan row G6 is the owner's: VPS or this laptop).
- No live fill was observed (see above); the 30–60+ days of forward evidence are
  the point of the fleet and are still to come.

## Unreleased — Sprint 4c: news shadow runner, daily report, VPS unit and runbook (plan row R4c; Phase 6b design §11, §13, §14)

Log-only: the runner places, sizes, approves, modifies and cancels nothing,
holds no OKX keys, never loads `.env`, never calls an authenticated endpoint,
never opens the demo database, and reads the Phase 6a journal read-only.
Nothing in the trading runtime imports it.

### Added
- `scripts/run_news_shadow.py`: `--loop` (service), `--once`, `--dry-run
  [--fixtures]`, `--report [DAY]`, `--status`, `--no-model`; refuses a live mode
  without `ANTHROPIC_API_KEY` (exit 2); one instance per state directory;
  graceful SIGTERM.
- `app/news/shadow.py`: the cycle — public candles and exchange clock, ingestion,
  one triage call per headline (copies reuse it; stale and quarantined items never
  sent; later same-headline copies attached to their event without a call),
  stories, Opus classification with link candidates, corroboration and event
  building over **all of a story's articles** (`story_event`; identical to the
  R4b eval path for a story without earlier articles — tested on every eval case),
  a versioned event book so each Phase 6a decision is judged only on what was known
  then, effective signals, the shadow overlay, health (clock skew, source outage,
  stage failure → NO_EFFECT), atomic state that survives restarts.
- `app/news/phase6a.py`: incremental read-only journal reader; LONG signals and
  runtime entry decisions become candidates with their baseline (allowed, blocked
  with the runtime's reason, or "not observed" after a settle window — never
  allowed); exits, FLAT/HOLD and stops never become candidates.
- `app/news/market.py`: public OKX candles and server time, host and paths pinned,
  no credentials, confirmed candles only.
- `app/news/budget.py`: monthly spend cap (default $40) with daily pacing,
  worst-case reservation before each call, list-price cost after; `BudgetedClient`
  enforces it around the SDK client.
- `app/news/report.py`: `report-YYYY-MM-DD.md` from the logs and the journal alone
  (reproducible), with the price path after each would-block/reduce, manual-review
  lists and eight safety invariants recomputed from the logs and checked against
  the Phase 6a journal itself.
- `app/news/dryrun.py` and `tests/fixtures/news_shadow/`: four invented hours run
  offline end to end (fixture network that refuses every other URL, scripted
  model, journal replay) with checked expectations.
- `deploy/systemd/news-shadow.service` and `news-shadow.env.example`; runbook
  `docs/runbooks/NEWS_SHADOW.md` (capped key in its own workspace, own
  environment file, install, checks, report, cap, stop/remove, troubleshooting).
- `app/news/store.py`: record kinds `source_fetch`, `cycle_summary`,
  `runner_event`. `app/news/pipeline.py`: `IngestSummary` also returns the cycle's
  records and fetch entries (additive).
- Tests (offline): the dry run with the network and the real client blocked, each
  counterfactual, no hindsight, unhealthy states, spend cap and pacing (including
  concurrency), restart equivalence, corrupt state, the journal reader's edge
  cases, the report's invariant checks, the CLI in every mode, the unit file and
  the import boundaries.

### Fixed (found by the independent review of this step)
- `app/news/fetch.py`: `parse_rss` handed the response text to `feedparser.parse`,
  which fetches a body that looks like a URL and opens a body that looks like a
  local path; a tampered feed could have made the host read local files or call
  internal addresses (e.g. a cloud metadata service). It now always passes a byte
  stream.
- Evidence a story already had (an earlier price/volume confirmation, a counted
  source beyond the article cap) can no longer be erased by a later repeat, and a
  classifier link pools evidence only when category, assets and a distinctive
  headline word agree.
- The spend cap now covers every HTTP attempt (SDK retries off, retries made by
  `BudgetedClient` with a fresh reservation; a timeout is charged its worst case).
- The report: tolerant of a line cut inside a multi-byte character; an event live
  at midnight keeps its effect in the next day's report; the exits, double-counting
  and baseline checks verify against the journal and the deciding event; a spend
  cap that held back triage is reported; reports refuse the Phase 6a directory.
- The unit makes the repository `.env` and the PostgreSQL socket inaccessible; a
  clock that could not be verified for 30 minutes makes the news state unhealthy.
- `tests/test_paper_api.py`: its "fresh" heartbeat was stamped when pytest imported
  the module, so it went stale (> 60 s) once the suite before it grew; it is now
  stamped when the test runs.

### Verified live (public data only)
- One `--once --no-model` cycle on this laptop against the SEC, Federal Reserve and
  Coinbase status RSS feeds and OKX public candles and server time: all sources
  HTTP 200, 299 confirmed 5-minute candles per instrument, clock skew −0.15 s.

### Not done here
- The capitalized wire-credit fix in `app/news/corroborate.py` (owner decision).
- No run against the real AI model (no key on this machine).

## Unreleased — Sprint 4b: news eval set and harness (plan row R4b; Phase 6b design §15, master plan §5.2)

Log-only tooling: nothing here gates an entry, reaches an order path, or is read
by the trading runtime.

### Added
- `tests/fixtures/news_eval/`: 134 labeled synthetic stories in 13 kinds
  (corroborated events, syndicated copies, single-source rumors, satire, stale
  reposts, prompt-injection text, homoglyph and zero-width text, plus
  corroborated-but-harmless, one-source-plus-market, off-watchlist, speculation,
  contradicted claims and story linking), each with its expected final action,
  category and label rationale; public-style candle scenarios (`market.json`,
  including a look-ahead trap and a bullish pump); a hand-written recorded run
  with deliberate flaws (`recorded/sample_run.jsonl`); README. The data files are
  ASCII-only: hidden and look-alike characters are written as `\u` escapes.
  Every label was re-derived by a second agent before commit; the flagged cases
  were corrected (an ambiguous single-source flag, aggregator repeats, same-owner
  outlets, invented incidents at real companies and tokens, label-revealing site
  names, accepted categories) and the stale reposts' single-source flags made
  consistent with the design's independence rules.
- `app/news/evaluation.py`: runs each story through the production path (real
  sanitizer, `NewsClassifier` triage and classification, price/volume check on
  candles closed before the decision, `assess`, `build_event`,
  `effective_signal`) and scores schema validity per stage (gate ≥ 95 %),
  prohibited actions (gate 0), single-source effects (gate 0), final-action and
  category accuracy per kind and per category with Wilson intervals, missed and
  false effects, triage recall, story links, refusals, truncations, tokens,
  latency and a list-price cost estimate. Infrastructure errors (including a
  reply from another model; a dated snapshot of the requested model counts as
  that model) are never scored, and only a case's last attempt counts, while the
  cost counts every attempt. Recording (the header keeps the run's models and
  settings) and replay clients (payload-hash checked) and four scripted offline
  models (reference answers, never-acting, block-everything, broken output) for a
  self-test of the harness and the labels; markdown report.
- `scripts/eval_news_classifier.py`: live run only when `ANTHROPIC_API_KEY` is
  set (otherwise prints `not run: no API key` and exits 0; five SDK retries
  against rate limits), `--replay` with the recorded settings, `--self-test`,
  case/kind filters, repetitions, parallel workers, and `--resume`, which
  continues an interrupted run with its own cases, repetitions and models and
  refuses conflicting flags; outputs under `artifacts/news_eval/`.
- `docs/NEWS_AGENT.md`: the news agent and its eval in plain words for the owner.
- Tests (offline): the eval set's coverage, ASCII-only data, the real sanitizer
  on adversarial text, label consistency through the reference answers and the
  independence rules, the three baselines, exact scoring of the recorded run,
  record/replay integrity, labels never reaching the model, error isolation,
  served-model checks, cost of retried attempts, look-ahead, the report and the
  CLI in every mode including resume.

### Found, not fixed here (outside this step's scope)
- `app/news/corroborate.py` recognizes "Associated Press" and "Agence
  France-Presse" credits only in lower case, so capitalized credits count as
  independent sources (eval case `syn-ap-attribution-capitalized`).
- `merge_event` in `app/news/decay.py` replaces a live event's corroboration with
  the repeat's own, so a repeat backed by one credible source switches a
  corroborated event off. Both are proposed for R4c (`docs/PLAN_STATUS.md`
  section 2).

## Unreleased — Sprint 4a: news agent core, log-only (plan row R4a; Phase 6b design §4–7, §9, §13)

Phase 6b is authorized for log-only operation only; nothing here gates an
entry, touches an order path, or is imported by the trading runtime.

### Added
- `app/news/schema.py`: the design's `NewsEvent` with exactly its enums and
  strict validation; `TriageVerdict` / `ClassifierVerdict` structured-output
  models; `SourceItemRef` from ingestion records.
- `app/news/classifier.py`: Claude Haiku 5.5 triage + Claude Opus 5.5
  classification through the Anthropic SDK with structured outputs, the frozen
  §9 system prompt (verbatim, plus a reference appendix) behind a 1-hour
  prompt-cache marker, strict validation; any failure or a missing
  `ANTHROPIC_API_KEY` is NO_EFFECT; API host pinned.
- `app/news/corroborate.py`: source families (wire copies, social-post relays,
  same owner, verbatim headlines), LLM may only narrow; price/volume
  confirmation from public candles closed before the decision.
- `app/news/decay.py`: §6 TTLs, monotonic decay, source weights, thresholds and
  reduction tiers, effective signal, most-conservative combination, event
  assembly (`build_event`) and same-story merging without TTL refresh.
- `app/news/overlay.py`: pure shadow overlay that can only keep, shrink or
  block a new long entry. `app/news/dedup.py`: story-level `event_id`.
- `app/news/store.py`: append-only `logs/news_shadow` event and decision
  JSONL logs with secret redaction.
- Dependency: `anthropic==1.15.0` (hashed lockfile regenerated with uv;
  pip-audit clean).
- Tests (offline: fakes and a mock HTTP transport, no key): schema, classifier
  failure paths and the real SDK request shape, corroboration and look-ahead,
  decay monotonicity, overlay invariants, logs, and import boundaries in both
  directions.

## Unreleased — Sprint 2b: sizing, risk, timeframe and positioning data (master plan Sprint 2b, research only)

### Added
- `research/sizing.py`: vol-targeted entry fractions, crash-state de-risking,
  drawdown ladder (state machine), the 390-variant sizing grid; all series
  backward-looking (look-ahead tests). `research/bracket.py`: take-profit,
  trailing-after-1R and time-stop exit brackets.
- `research/engine.py`: per-bar size matrices, reduce-only mid-trade
  de-risking (never adds), ladder in the loop, trailing stop, per-column time
  stops, MFE/MAE per trade; bit-for-bit the Sprint 2 engine with overlays off.
  Give-back metric (trades that reached +3 % unrealized yet closed negative).
- `research/resample.py`: UTC-aligned 1H → 6H bars (complete bars only).
- `app/datalake/binance_public.py` + `scripts/collect_binance_positioning.py`:
  Binance PUBLIC funding-rate (since 2019) and open-interest (since 2020-09 /
  2021-12, hourly from 5-minute bulk files, sha256-verified) history as
  research features only; lake layout `external/<venue>/…`; DuckDB views
  `binance_funding_rate`, `binance_metrics`. We never trade on Binance.
- `research/sized_walkforward.py`: two-stage walk-forward (rule, then sizing,
  both selected on the train slice; sizing under a train drawdown cap) with
  fixed replays (robustness, sizing sweep, ladder/bracket effects, slippage).
- `research/portfolio.py`: sleeve combination (daily compounding, buckets or
  daily rebalancing, equal-capital / equal-risk, correlation, portfolio ladder).
- `research/report_v1b.py` + `scripts/run_research_v1b.py`: Sprint 2b
  risk-adjusted gates (PF > 1.2, max DD < 20 % at the proposed sizing, Sharpe
  > 0.7, Calmar > 0.5, 4 of 5 positive years, ≥ 30 trades, ±30 % robustness,
  DSR reported), ranked paper-fleet shortlist, plain-English executive
  summary; `hold` always-long reference. Report
  `docs/research/ENSEMBLE_V1B_REPORT.md`. Docs: `docs/RESEARCH_LAB.md`,
  `docs/DATA_LAKE.md`.
- Lake writers retry the atomic replace on transient Windows file locks.

### Result
- 0 of 28 candidate configurations pass the Sprint 2b gates (0 of 28 with the
  fixed policy sizing as well). Sizing cut the median worst drawdown from
  54 % to 19 % but return fell in step (median Calmar 0.28 → 0.31); best
  single configuration S4 on ETH 6H (Calmar 0.58, max DD 13.2 %) misses only
  the 4-of-5 positive-years gate. Holdout untouched; nothing goes to demo.

## Unreleased — Sprint 2: research lab + ensemble v1 candidates (master plan Sprint 2)

### Added
- `research/`: dependency-free vectorized long-only sweep engine with the same
  execution conventions as the reviewed simulator (parity tested), features,
  candidates S0–S5 + SMA baseline in the `Strategy` contract via an adapter,
  cartesian sweeps with ±30 % robustness, walk-forward with purge gap and
  stitched out-of-sample curves, untouched 12-month holdout, Monte Carlo
  trade-order bootstrap, slippage stress, regime v1 labels, deflated Sharpe,
  hit-rate calibrated confidence. Runner `scripts/run_research.py`; report
  `docs/research/ENSEMBLE_V1_REPORT.md` (+ JSON). Docs: `docs/RESEARCH_LAB.md`.
- Import-boundary test: research code never imports execution, exchange,
  shadow, OKX client, notify, paper, live or the live strategy registry.

## Unreleased — Sprint 1: data lake v2 (master plan Sprint 1)

### Added
- `app/datalake/`: Parquet research lake over PUBLIC OKX data — resumable
  `history-candles` backfill (BTC/ETH × 1m 5m 1H 4H 1D, de-duplicated,
  year-partitioned, crash-safe cursors in `_state/`), SWAP statistics
  collectors as research features (funding rate, open interest, long/short
  ratio, taker volume), a public `liquidation-orders` WebSocket collector to
  JSON lines, DuckDB views, and a data-quality report (continuity, gaps,
  duplicates, alignment, OHLC coherence, outliers). Docs: `docs/DATA_LAKE.md`.
- Scripts: `backfill_history.py`, `collect_derivatives.py`,
  `collect_liquidations.py`, `data_quality_report.py`, `ingest_news.py`.
- `app/news/`: log-only news-ingestion skeleton (Phase 6b design §7.1–7.3):
  official RSS + GDELT sources, sanitization with audit hashes and flags,
  quarantine of injection/homoglyph/bidi-flagged items, dedup, JSON lines.
  No LLM call, no classification, no trading effect; the import boundary is
  tested. Docs: `docs/NEWS_INGESTION.md`.
- Dependencies: `duckdb`, `pyarrow` (now direct), `feedparser` (lockfile
  regenerated; pip-audit clean).

## Unreleased — Sprint 2c: regime gates, portfolio sizing, turnover (branch `sprint-2c/regime-portfolio`)

Research only (2026-10-20); no change under `app/execution`, `app/risk`,
`app/exchange` or `config/`. Result: 4 of 108 configurations pass the
walk-forward gates at the fixed policy sizing, the untouched holdout confirms
1 and contradicts 3; see `docs/research/ENSEMBLE_V1C_REPORT.md` and
`docs/RESEARCH_LAB.md`.

### Added
- `research/hmm.py` (numpy Gaussian HMM with a forward-only filter),
  `research/regime_v2.py` (3-state regime fitted per walk-forward train slice,
  entry gate / entry scale only), `research/events.py` + scheduled-event
  windows in the S0 filter (FOMC calendar, owner to verify),
  `research/strategies/turnover.py` + `S1h` hysteresis + `+S5s` re-test
  variants, `research/gated_walkforward.py`, portfolio-level sizing
  (`research/portfolio.py::combine_sized`), `research/report_v1c.py` (yearly
  gate v2 on rolling 12-month windows, holdout verdicts, machine-readable
  paper-fleet shortlist with controls), `scripts/run_research_v1c.py`
  (parallel, `--render-from-json`), tests for every component including
  no-look-ahead in HMM fitting/filtering.

## Unreleased — Sprint 0 (master plan `docs/MASTER_PLAN_2026-10-20.md`)

### Fixed
- **OKX WebSocket port 8443 cutoff (Oct 31, 2026):** every WebSocket default
  (`app/config.py`, `app/exchange/okx_public_ws.py`,
  `app/exchange/okx_demo_endpoints.py`, `.env.example`, phase docs) now
  connects without an explicit port (implicit 443). The fail-closed URL
  validators are unchanged and still accept `None`, `443` and `8443`.
  `tests/test_ws_defaults_no_port.py` asserts no default carries a port.
  Operator runbook: `docs/runbooks/VPS_8443_UPDATE.md`.
- Dashboard candle chart no longer anchors the y-axis at zero.

### Added
- `requirements.in` (direct deps) + generated, hashed, universal
  `requirements.txt` lockfile (uv); `.github/workflows/audit.yml` runs
  `pip-audit` on the locked set and checks lock/source sync; Dependabot
  config for pip and GitHub Actions.
- Alembic baseline (`alembic.ini`, `migrations/`, revision `0001`) matching
  the current `create_all` schema; `tests/test_migrations.py`;
  `docs/runbooks/DB_MIGRATIONS.md`. Runtime behavior unchanged.
- `docs/AUDIT_2026-10-20.md` and `docs/MASTER_PLAN_2026-10-20.md`.

### Changed
- CI and notify workflows run Python 3.13.
- Travel-mode guard also classifies `requirements.in`, `migrations/` and
  `alembic.ini` as safety-sensitive.
- Dependency security fixes found by `pip-audit`: `requests` 2.33.0,
  `python-dotenv` 1.2.2, `pytest` 9.0.3, `starlette` 1.3.1 (with
  `fastapi` 0.136.0).

### Removed
- `resume_claude_at_1.sh` (stale session-resume script).
