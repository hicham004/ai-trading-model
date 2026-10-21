# A paper fleet written by the R5a code

`_state/fleet_state.json`, `journals/` and `fleet.jsonl` were written by the
paper fleet as it was at commit `e0a3c37` (plan row R5a, state version 1,
before allocator v2). `tests/test_paper_fleet_runner.py` resumes it with the
current code to prove that a fleet started before plan row R5b keeps running:
its records stay untouched, it continues byte for byte as an uninterrupted run
would, and the allocator-v2 account joins it from its own start.

How it was made (simulation only, no network, no keys):

```bash
git archive e0a3c37 | tar -x -C /tmp/r5a_code
cd /tmp/r5a_code
python /path/to/repo/tests/fixtures/paper_fleet_r5a/make_fixture.py /tmp/r5a_code /tmp/r5a_fixture
```

The fleet holds two accounts, `ctl-hold-btc-4h` and the jointly sized
portfolio `pf-s1s2s4-btceth-vt15`, on the deterministic synthetic market of
`research/paper_fleet/replay.py` (`synthetic_market(days=1000, end=2026-10-19)`),
created at 2026-10-15 10:20 UTC and advanced in 3-hour steps to 2026-10-16
09:10 UTC, exactly as the runner tests drive it. `fleet.jsonl` keeps the
wall-clock `logged_at` times of the run that made it.
