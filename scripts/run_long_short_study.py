"""Phase 9 design study runner: long and short through perpetual swaps without leverage (plan row R9, SIMULATION ONLY).

Runs the pre-registered study of ``research/longshort_study.py`` over the
Parquet lake: per instrument x timeframe (one process each with
``--workers``), the long-only reproduction of Sprint 2c first (the run stops if
it does not match the stored numbers), then the hybrid and all-perp designs of
S1, S2, S4 and S1+S5 under Sprint 2c's walk-forward, policy sizing and gates,
the diagnostics, and — with ``--evaluate-holdout`` — the untouched 12 months
for the configurations that pass the walk-forward part of the evidence rule.
The holdout is opened only by the full pre-registered study (every family,
series and design, no ``--quick``), and every opening is appended to a ledger
(``docs/research/long_short_holdout_ledger.json``) that the report shows, so a
re-run can never hide an earlier look. Writes
``docs/research/LONG_SHORT_STUDY_REPORT.md`` and a results JSON.

Example::

    python scripts/run_long_short_study.py --collect-perp-candles          # public OKX swap candles into the lake (resumable, ~10 min)
    python scripts/run_long_short_study.py --evaluate-holdout --workers 4
    python scripts/run_long_short_study.py --quick --families S1 --instruments BTC-USDT --timeframes 4H --report - --json -
    python scripts/run_long_short_study.py --render-from-json docs/research/long_short_results.json

Public data only (OKX public candles through the GET-only client, Binance's
public funding files already in the lake). No key is read, no account is
touched, nothing here can reach an order; results never authorize trading.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datalake.layout import LakeLayout  # noqa: E402
from research.longshort_data import collect_perp_candles  # noqa: E402
from research.longshort_study import (  # noqa: E402
    JUDGED_VARIANTS,
    POST_HOC,
    PREREGISTRATION,
    REVIEW_FIXES,
    STUDY_FAMILIES,
    STUDY_INSTRUMENTS,
    STUDY_TIMEFRAMES,
    StudyConfig,
    StudyError,
    descriptive,
    holdout_openings,
    preregistration_hash,
    run_series,
)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 9 long/short design study over the Parquet lake (simulation only).")
    p.add_argument("--instruments", nargs="+", default=list(STUDY_INSTRUMENTS), choices=list(STUDY_INSTRUMENTS))
    p.add_argument("--timeframes", nargs="+", default=list(STUDY_TIMEFRAMES), choices=list(STUDY_TIMEFRAMES))
    p.add_argument("--families", nargs="+", default=list(STUDY_FAMILIES), choices=list(STUDY_FAMILIES))
    p.add_argument("--variants", nargs="+", default=list(JUDGED_VARIANTS), choices=list(JUDGED_VARIANTS))
    p.add_argument("--evaluate-holdout", action="store_true", help="Open the 12-month holdout for walk-forward passers (once).")
    p.add_argument("--quick", action="store_true", help="Small grids, no reproduction check: a smoke run, never a result.")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--lake-dir", default=None)
    p.add_argument("--v1c-results", default="docs/research/ensemble_v1c_results.json")
    p.add_argument("--report", default="docs/research/LONG_SHORT_STUDY_REPORT.md", help="'-' = do not write")
    p.add_argument("--json", default="docs/research/long_short_results.json", help="'-' = do not write")
    p.add_argument("--render-from-json", default=None, metavar="PATH", help="Re-render the report from a saved results JSON.")
    p.add_argument("--collect-perp-candles", action="store_true", help="Collect the swaps' public 1H candles into the lake, then exit.")
    p.add_argument("--holdout-ledger", default="docs/research/long_short_holdout_ledger.json",
                   help="Append-only record of every holdout opening ('-' = none; only allowed without --evaluate-holdout).")
    return p.parse_args(argv)


def full_study_requested(args: argparse.Namespace) -> bool:
    """The holdout may only be opened by the complete pre-registered set of configurations."""
    return (not args.quick and sorted(args.families) == sorted(STUDY_FAMILIES) and sorted(args.instruments) == sorted(STUDY_INSTRUMENTS)
            and sorted(args.timeframes) == sorted(STUDY_TIMEFRAMES) and sorted(args.variants) == sorted(JUDGED_VARIANTS))


def load_ledger(path: str) -> List[Dict[str, Any]]:
    if path == "-" or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise StudyError(f"the holdout ledger {path} is malformed")
    return list(data["entries"])


def write_ledger(path: str, entries: List[Dict[str, Any]]) -> None:
    payload = {"note": ("Every opening of the 12-month holdout by the Phase 9 long/short study (plan row R9), in order; entries are "
                        "appended, never edited. The report shows all of them."), "entries": entries}
    Path(path).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def _layout(lake_dir) -> LakeLayout:
    return LakeLayout(Path(lake_dir)) if lake_dir else LakeLayout.from_env()


def _series_job(job: Dict[str, Any]) -> Dict[str, Any]:
    cfg = StudyConfig(**job["cfg"])
    v1c = json.loads(Path(job["v1c_results"]).read_text(encoding="utf-8"))
    return run_series(_layout(job["lake_dir"]), job["instrument"], job["timeframe"], cfg, v1c, families=job["families"],
                      variants=job["variants"], evaluate_holdout_=job["evaluate_holdout"], log=lambda msg: print(msg, flush=True))


def _rounded(value: Any, digits: int = 6) -> Any:
    """Floats rounded to 6 decimals (as Sprint 2c's results file), non-finite values as null."""
    if isinstance(value, dict):
        return {str(k): _rounded(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v, digits) for v in value]
    if isinstance(value, float):
        return None if value != value or value in (float("inf"), float("-inf")) else round(value, digits)
    return value


def _render(run: Dict[str, Any]) -> str:
    from research.report_longshort import render_report  # imported late: the study can run before a report is rendered

    return render_report(run)


def _cfg_kwargs(cfg: StudyConfig) -> Dict[str, Any]:
    return {k: getattr(cfg, k) for k in cfg.__dataclass_fields__}


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.render_from_json:
        run = json.loads(Path(args.render_from_json).read_text(encoding="utf-8"))
        if args.report != "-":
            Path(args.report).write_text(_render(run), encoding="utf-8")
            print(f"report re-rendered: {args.report}")
        return 0
    if args.evaluate_holdout and not full_study_requested(args):
        print("--evaluate-holdout needs the full pre-registered study: every family, instrument, timeframe and design, without --quick",
              file=sys.stderr)
        return 2
    if args.evaluate_holdout and args.holdout_ledger == "-":
        print("--evaluate-holdout needs a holdout ledger (every opening is recorded)", file=sys.stderr)
        return 2
    layout = _layout(args.lake_dir)
    if args.collect_perp_candles:
        for inst in args.instruments:
            rep = collect_perp_candles(layout, inst)
            print(f"{rep.swap}: pages={rep.walk.pages} added={rep.added} complete={rep.walk.complete} reason={rep.walk.reason}", flush=True)
        return 0
    cfg = StudyConfig(quick=bool(args.quick))
    ledger = load_ledger(args.holdout_ledger)
    t0 = time.monotonic()
    jobs = [{"cfg": _cfg_kwargs(cfg), "v1c_results": args.v1c_results, "lake_dir": args.lake_dir, "instrument": i, "timeframe": t,
             "families": list(args.families), "variants": list(args.variants), "evaluate_holdout": bool(args.evaluate_holdout)}
            for i in args.instruments for t in args.timeframes]
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    series: List[Dict[str, Any]] = []
    try:
        if args.workers > 1 and len(jobs) > 1:
            with ProcessPoolExecutor(max_workers=min(args.workers, len(jobs))) as pool:
                series = list(pool.map(_series_job, jobs))
        else:
            series = [_series_job(j) for j in jobs]
    except StudyError as exc:
        print(f"STUDY STOPPED: {exc}", file=sys.stderr, flush=True)
        return 2
    holdout_start = min(pd.Timestamp(s["holdout_span"].split("->")[0], tz="UTC") for s in series if s.get("holdout_span"))
    run: Dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "started_at": started,
            "elapsed_minutes": round((time.monotonic() - t0) / 60.0, 1), "config": cfg.to_dict(),
            "preregistration": PREREGISTRATION, "preregistration_sha256": preregistration_hash(cfg), "post_hoc": POST_HOC,
            "review_fixes": REVIEW_FIXES,
            "instruments": list(args.instruments), "timeframes": list(args.timeframes), "families": list(args.families),
            "variants": list(args.variants), "evaluate_holdout": bool(args.evaluate_holdout), "quick": bool(args.quick),
            "v1c_results": args.v1c_results, "report_path": args.report, "json_path": args.json, "workers": args.workers,
            "holdout_ledger_path": args.holdout_ledger,
        },
        "series": series,
        "descriptive": descriptive(layout, cfg, holdout_start, instruments=args.instruments),
    }
    openings = holdout_openings(series)
    if openings:
        ledger.append({"generated_at": run["meta"]["generated_at"], "started_at": started,
                       "preregistration_sha256": run["meta"]["preregistration_sha256"], "results_file": args.json,
                       "openings": _rounded(openings)})
        write_ledger(args.holdout_ledger, ledger)
        print(f"holdout ledger: {args.holdout_ledger} ({len(ledger)} entries)")
    run["meta"]["holdout_ledger"] = ledger
    # The report is rendered from exactly what the results file holds, so --render-from-json reproduces it.
    saved = json.loads(json.dumps(_rounded(run), default=str))
    if args.json != "-":
        Path(args.json).write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8")
        print(f"results: {args.json}")
    if args.report != "-":
        Path(args.report).write_text(_render(saved), encoding="utf-8")
        print(f"report: {args.report}")
    print(f"done in {run['meta']['elapsed_minutes']} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
