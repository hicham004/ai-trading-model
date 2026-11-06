"""Write a paper-fleet state and journals with the REAL R5a code (commit e0a3c37), for the resume test of plan row R5b.

Run with the R5a export as the working directory:  python make_r5a_fixture.py <r5a export> <output dir>
It mirrors tests/test_paper_fleet_runner.py: the deterministic synthetic market, window_days=120, the fleet created at
T0 with two accounts (ctl-hold-btc-4h and the v1 portfolio) and advanced in 3-hour steps to MID.
"""

import os
import shutil
import sys
from pathlib import Path

EXPORT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(EXPORT))
os.chdir(EXPORT)

import pandas as pd  # noqa: E402

from research.paper_fleet.config import INSTRUMENTS, FleetManifest, load_manifest  # noqa: E402
from research.paper_fleet.data import FleetLake, MarketData  # noqa: E402
from research.paper_fleet.replay import ReplayFeed, synthetic_market  # noqa: E402
from research.paper_fleet.runner import STATE_VERSION, FleetSettings, PaperFleet  # noqa: E402
from research.paper_fleet.store import FleetPaths  # noqa: E402

assert STATE_VERSION == 1, "this must run on the R5a code"
SETTINGS = FleetSettings(window_days=120.0)
T0 = pd.Timestamp("2026-10-15 10:20", tz="UTC")
MID = pd.Timestamp("2026-10-16 09:10", tz="UTC")

full = load_manifest(Path("docs/research/paper_fleet_shortlist_v1c.json"), Path("docs/research/ensemble_v1c_results.json"))
ids = ("ctl-hold-btc-4h", "pf-s1s2s4-btceth-vt15")
manifest = FleetManifest(accounts=tuple(a for a in full.accounts if a.account_id in ids), sources=full.sources)
candles, funding, oi = synthetic_market(days=1000, end=pd.Timestamp("2026-10-19 00:00", tz="UTC"))
feed = ReplayFeed(candles, funding, oi)
feed.now = T0
work = OUT.parent / (OUT.name + "-work")
shutil.rmtree(work, ignore_errors=True)
paths = FleetPaths(work)
market = MarketData(FleetLake(paths.lake), feed, instruments=INSTRUMENTS, history_days=SETTINGS.history_days)
fleet = PaperFleet(manifest, paths, market, settings=SETTINGS)
assert fleet.acquire()
fleet.open(T0.to_pydatetime())
t = T0 + pd.Timedelta(minutes=40)
while t < MID:
    feed.now = t
    fleet.cycle(t.to_pydatetime())
    t += pd.Timedelta(hours=3)
feed.now = MID
fleet.cycle(MID.to_pydatetime())
fleet.release()

shutil.rmtree(OUT, ignore_errors=True)
(OUT / "_state").mkdir(parents=True)
(OUT / "journals").mkdir()
shutil.copy2(paths.state_file, OUT / "_state" / "fleet_state.json")
for j in sorted(paths.journals.glob("*.jsonl")):
    shutil.copy2(j, OUT / "journals" / j.name)
shutil.copy2(paths.fleet_log, OUT / "fleet.jsonl")
print("wrote", OUT, sorted(p.name for p in (OUT / "journals").iterdir()))
