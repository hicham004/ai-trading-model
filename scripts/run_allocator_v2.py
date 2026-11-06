"""Allocator v2 study (plan row R5b): v1 and v2 on the Sprint 2c portfolio's six full-size sleeves — SIMULATION ONLY.

Rebuilds the jointly sized BTC+ETH x S1/S2/S4 portfolio's sleeves from the
research data lake exactly as Sprint 2c ran them (and stops if allocator v1 does
not reproduce Sprint 2c's stored numbers), runs allocator v2 with its
pre-registered brakes (``research.allocator.DEFAULT_ALLOCATOR_V2``) and two
ablations, applies the Sprint 2c portfolio gates unchanged, and writes::

    docs/research/allocator_v2_results.json   numbers (the paper fleet reads its expectations from here)
    docs/research/ALLOCATOR_V2_REPORT.md      the report

Usage::

    python scripts/run_allocator_v2.py                      # walk-forward only; the 12-month holdout stays closed
    python scripts/run_allocator_v2.py --evaluate-holdout   # opens the holdout, but only if v2 passed the walk-forward gates
    python scripts/run_allocator_v2.py --render-from-json docs/research/allocator_v2_results.json

Public market data from the lake only; no network, no keys, nothing that can reach an order.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

if __name__ == "__main__":
    sys.modules.setdefault("dotenv", None)  # app/config.py then skips load_dotenv(): no .env secrets in this process

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datalake.layout import LakeLayout  # noqa: E402
from research.allocator_study import StudyError, render_report, run_study  # noqa: E402

DEFAULT_RESULTS = "docs/research/ensemble_v1c_results.json"
DEFAULT_JSON = "docs/research/allocator_v2_results.json"
DEFAULT_REPORT = "docs/research/ALLOCATOR_V2_REPORT.md"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Allocator v2 vs v1 on the Sprint 2c portfolio sleeves (simulation only).")
    p.add_argument("--lake-dir", default=None, help="Research lake (default $DATA_LAKE_DIR or data/lake).")
    p.add_argument("--results", default=DEFAULT_RESULTS, help="Sprint 2c results JSON (the sleeves and their stored portfolio numbers).")
    p.add_argument("--json", default=DEFAULT_JSON)
    p.add_argument("--report", default=DEFAULT_REPORT)
    p.add_argument("--evaluate-holdout", action="store_true", help="Open the 12-month holdout if (and only if) v2 passes walk-forward.")
    p.add_argument("--render-from-json", default=None, metavar="PATH", help="Re-render the report from a saved results JSON (no re-run).")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.render_from_json:
        result = json.loads(Path(args.render_from_json).read_text(encoding="utf-8"))
    else:
        layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
        results_doc = json.loads(Path(args.results).read_text(encoding="utf-8"))
        try:
            result = run_study(layout, results_doc, evaluate_holdout=args.evaluate_holdout)
        except StudyError as exc:
            print(f"allocator v2 study refused: {exc}", file=sys.stderr)
            return 2
        result["meta"]["generated_at"] = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        result["meta"]["source_results"] = Path(args.results).as_posix()
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        Path(args.json).write_text(text, encoding="utf-8")
        result = json.loads(text)  # the report is rendered from exactly what was saved (a re-render reproduces it)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(render_report(result), encoding="utf-8")
    wf = result["walk_forward"]
    m1, m2 = wf["v1"]["metrics"], wf["v2"]["metrics"]
    print(f"v1: CAGR {m1['cagr'] * 100:+.2f}% max DD {m1['max_drawdown'] * 100:.2f}% Sharpe {m1['sharpe']:.2f} Calmar {m1['calmar']:.2f}")
    print(f"v2: CAGR {m2['cagr'] * 100:+.2f}% max DD {m2['max_drawdown'] * 100:.2f}% Sharpe {m2['sharpe']:.2f} Calmar {m2['calmar']:.2f} "
          f"passed={wf['v2']['acceptance']['passed']} failed={wf['v2']['acceptance']['failed']}")
    print(f"holdout: {result.get('holdout')['evaluated'] if result.get('holdout') else None}")
    print(f"wrote {args.report}" + ("" if args.render_from_json else f" and {args.json}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
