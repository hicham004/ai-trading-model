"""Breadth study (plan row R20): the S1 family on the nine liquid OKX markets as ONE Trader-tier book, and one rotation test (SIMULATION ONLY).

Steps, in this order, public data only:

1. ``--preregister``: writes ``docs/research/breadth_v1_preregistration.json`` (the fixed text, the numbers, a hash) and the
   report with the pre-registration alone; it refuses to run twice.
2. The study: the frozen study lake (the nine markets' candles cut at Sprint 2c's data end, built with the replication
   study's ``freeze_lake`` when missing); Sprint 2c's own runner loaded as a module runs hold / S1 / S1+VC / S1+S5 on every
   market at the Reference and the Trader cell (the protocol check recorded per job, the study stops on any mismatch a job
   does not explain; the reproduction of the stored numbers first, the study stops on any difference); then the book from
   the sleeves' per-window selected rules, its ablations and comparison lines, the rotation test and its benchmarks;
   ``--evaluate-holdout`` (full pre-registered study only) opens the untouched 12 months once as pre-registered and records
   every opening in an append-only ledger. Writes ``docs/research/BREADTH_V1_REPORT.md`` and a results JSON. Fleet rows are
   RECORDED in the results, never applied (the fleet has no book or rotation account type).

Example::

    python scripts/run_breadth_v1.py --preregister
    python scripts/run_breadth_v1.py --evaluate-holdout --workers 12
    python scripts/run_breadth_v1.py --markets BTC-USDT ETH-USDT --rules S1 --quick --skip-reproduction --report - --json - --holdout-ledger -
    python scripts/run_breadth_v1.py --render-from-json docs/research/breadth_v1_results.json

Nothing here can reach an order or an account; results never authorize trading.
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

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datalake.layout import LakeLayout  # noqa: E402
from research.breadth_study import (  # noqa: E402
    CELLS,
    DATA_END,
    MARKETS,
    PREREGISTRATION,
    PREREGISTRATION_PATH,
    R12_PREREGISTRATION,
    R12_RESULTS,
    R13_RESULTS,
    R16_RESULTS,
    R18_RESULTS,
    R19_RESULTS,
    RULES,
    STUDY_LAKE_DIRNAME,
    STUDY_NAME,
    V1C_RESULTS,
    BreadthError,
    StudyConfig,
    check_replication_markets,
    diversification,
    earlier_looks,
    fleet_rows,
    full_study_requested,
    guard_second_look,
    holdout_openings,
    load_market,
    load_preregistration,
    market_correlations,
    merge_results,
    overall_summary,
    plan_jobs,
    preregister,
    preregistration_hash,
    reproduction_checks,
    result_of,
    run_book_study,
    run_job,
    run_rotation_study,
    sleeve_table,
    stored_results,
    write_breadth_ledger,
    JUDGED_CELL,
    CONTROL,
    _metrics_of,
)
from research.replication import freeze_lake, load_ledger  # noqa: E402
from research.replication_data import lake_summary  # noqa: E402
from research.report_v1c import GATES  # noqa: E402
from research.trader_policy import TIER_GATES  # noqa: E402

DEFAULT_REPORT = "docs/research/BREADTH_V1_REPORT.md"
DEFAULT_JSON = "docs/research/breadth_v1_results.json"
DEFAULT_LEDGER = "docs/research/breadth_v1_holdout_ledger.json"


def _rel(path: Path) -> str:
    return str(path.relative_to(Path(__file__).resolve().parents[1]).as_posix())


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Breadth study (plan row R20): the S1 family on nine markets as one Trader-tier book, and one rotation test (simulation only).")
    p.add_argument("--preregister", action="store_true", help="Write the pre-registration file and the report stub (once), then exit.")
    p.add_argument("--force-preregister", action="store_true", help="Overwrite an existing pre-registration (only before any result exists).")
    p.add_argument("--freeze", action="store_true", help="Build the study lake (the nine markets' candles cut at Sprint 2c's data end), then exit.")
    p.add_argument("--refreeze", action="store_true", help="Rebuild the study lake before the study.")
    p.add_argument("--markets", nargs="+", default=list(MARKETS), choices=list(MARKETS))
    p.add_argument("--rules", nargs="+", default=list(RULES), choices=list(RULES))
    p.add_argument("--cells", nargs="+", default=[c.key for c in CELLS], choices=[c.key for c in CELLS])
    p.add_argument("--no-book", action="store_true", help="Skip the book (smoke runs only).")
    p.add_argument("--no-rotation", action="store_true", help="Skip the rotation test (smoke runs only).")
    p.add_argument("--evaluate-holdout", action="store_true", help="Open the untouched 12 months once as pre-registered (full study only).")
    p.add_argument("--quick", action="store_true", help="Cut grids, no reproduction: a smoke run, never a result.")
    p.add_argument("--skip-reproduction", action="store_true", help="Skip the reproduction gate (smoke runs only; refused with --evaluate-holdout).")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--lake-dir", default=None, help="The research lake (default $DATA_LAKE_DIR or data/lake).")
    p.add_argument("--study-lake-dir", default=None, help=f"The frozen study lake (default: <research lake>/../{STUDY_LAKE_DIRNAME}).")
    p.add_argument("--preregistration", default=_rel(PREREGISTRATION_PATH))
    p.add_argument("--r12-preregistration", default=_rel(R12_PREREGISTRATION), help="The replication study's pre-registration (its fixed market list).")
    p.add_argument("--v1c-results", default=_rel(V1C_RESULTS))
    p.add_argument("--r12-results", default=_rel(R12_RESULTS))
    p.add_argument("--r13-results", default=_rel(R13_RESULTS))
    p.add_argument("--r16-results", default=_rel(R16_RESULTS))
    p.add_argument("--r18-results", default=_rel(R18_RESULTS))
    p.add_argument("--r19-results", default=_rel(R19_RESULTS))
    p.add_argument("--report", default=DEFAULT_REPORT, help="'-' = do not write")
    p.add_argument("--json", default=DEFAULT_JSON, help="'-' = do not write")
    p.add_argument("--holdout-ledger", default=DEFAULT_LEDGER, help="Append-only record of every holdout opening ('-' = none; refused with --evaluate-holdout).")
    p.add_argument("--run-note", action="append", default=[], metavar="TEXT", help="A sentence recorded in the results' meta and printed under the report's method notes.")
    p.add_argument("--render-from-json", default=None, metavar="PATH", help="Re-render the report from a saved results JSON.")
    return p.parse_args(argv)


def _research_lake(args: argparse.Namespace) -> LakeLayout:
    return LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()


def _study_lake(args: argparse.Namespace, research: LakeLayout) -> LakeLayout:
    if args.study_lake_dir:
        return LakeLayout(Path(args.study_lake_dir))
    return LakeLayout(Path(research.root).parent / STUDY_LAKE_DIRNAME)


def _rounded(value: Any, digits: int = 6) -> Any:
    if isinstance(value, dict):
        return {str(k): _rounded(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v, digits) for v in value]
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return None if not np.isfinite(f) else round(f, digits)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Series, pd.DataFrame)):
        return None
    return str(value)


def _render(run: Dict[str, Any]) -> str:
    from research.report_breadth import render_report  # imported late: the study can run before a report is rendered

    return render_report(run)


def _strip(result: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON-safe view of one runner result (no pandas objects, no runner args; the per-window records stay: the book is built from them)."""
    return {k: v for k, v in result.items() if k not in ("trades", "args")}


def cmd_preregister(args: argparse.Namespace) -> int:
    path = Path(args.preregistration)
    try:
        payload = preregister(path, force=args.force_preregister, r12_path=Path(args.r12_preregistration))
    except BreadthError as exc:
        print(f"not written: {exc}", file=sys.stderr)
        return 2
    print(f"pre-registration written: {path} (sha256 {payload['sha256'][:16]}..., {len(payload['markets'])} markets, rules {payload['rules']}, "
          f"cells {[c['key'] for c in payload['cells']]})")
    if args.report != "-":
        stub = {"meta": {"study": STUDY_NAME, "preregistration": PREREGISTRATION, "preregistration_file": str(path.as_posix()), "preregistration_written_at": payload["written_at"],
                         "preregistration_sha256": preregistration_hash(StudyConfig(), payload), "data_end": DATA_END, "gates": dict(GATES),
                         "tier_gates": {k: dict(v) for k, v in TIER_GATES.items()}}, "results": [], "sleeves": [], "book": None, "rotation": None, "overall": {}}
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(_render(stub), encoding="utf-8")
        print(f"report stub (pre-registration only): {args.report}")
    return 0


def cmd_freeze(research: LakeLayout, study: LakeLayout) -> Dict[str, Any]:
    print(f"freezing the study lake at {study.root} (bar close <= {DATA_END}) ...", flush=True)
    return freeze_lake(research, study, list(MARKETS), end=DATA_END, log=lambda m: print(m, flush=True))


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.render_from_json:
        run = json.loads(Path(args.render_from_json).read_text(encoding="utf-8"))
        if args.report != "-":
            Path(args.report).write_text(_render(run), encoding="utf-8")
            print(f"report re-rendered: {args.report}")
        return 0
    if args.preregister:
        return cmd_preregister(args)
    try:
        prereg = load_preregistration(Path(args.preregistration))
        check_replication_markets(Path(args.r12_preregistration))
    except (OSError, BreadthError, ValueError) as exc:
        print(f"no usable pre-registration ({exc}); run --preregister first", file=sys.stderr)
        return 2
    research = _research_lake(args)
    study = _study_lake(args, research)
    if args.freeze:
        print(json.dumps(cmd_freeze(research, study), indent=1))
        return 0
    cfg = StudyConfig(markets=tuple(m for m in MARKETS if m in args.markets), rules=tuple(r for r in RULES if r in args.rules), cells=tuple(args.cells),
                      book=not args.no_book, rotation=not args.no_rotation, reproduction=not (args.quick or args.skip_reproduction), quick=bool(args.quick),
                      lake_dir=str(study.root))
    full = full_study_requested(cfg)
    if args.evaluate_holdout and not full:
        print("--evaluate-holdout needs the full pre-registered study: every market, rule and cell, the book and the rotation, with the reproduction, without --quick",
              file=sys.stderr)
        return 2
    if args.evaluate_holdout and args.holdout_ledger == "-":
        print("--evaluate-holdout needs a holdout ledger", file=sys.stderr)
        return 2
    if cfg.book and JUDGED_CELL.key not in cfg.cells:
        print("the book needs the Trader cell (its sleeves' selected rules come from it); add it or pass --no-book", file=sys.stderr)
        return 2
    docs = {"Sprint 2c": json.loads(Path(args.v1c_results).read_text(encoding="utf-8")), "R12 replication": json.loads(Path(args.r12_results).read_text(encoding="utf-8")),
            "R13 research round 1": json.loads(Path(args.r13_results).read_text(encoding="utf-8")), "R16 research round 2": json.loads(Path(args.r16_results).read_text(encoding="utf-8")),
            "R18 Trader Policy v1": json.loads(Path(args.r18_results).read_text(encoding="utf-8")), "R19 research round 3": json.loads(Path(args.r19_results).read_text(encoding="utf-8"))}
    v1c_meta = docs["Sprint 2c"]["meta"]
    stored = stored_results(docs)
    if args.refreeze or not all(study.candles_dir(m, "1H").exists() for m in cfg.markets):
        cmd_freeze(research, study)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    t0 = time.monotonic()
    jobs = plan_jobs(cfg, evaluate_holdout=bool(args.evaluate_holdout))
    print(f"{len(jobs)} jobs on {args.workers} worker(s): " + ", ".join(f"{j['instrument']} @ {j['cell']['key']}" for j in jobs), flush=True)
    if args.workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(jobs))) as pool:
            outputs = list(pool.map(run_job, jobs))
    else:
        outputs = [run_job(j) for j in jobs]
    merged, series_info = merge_results(outputs, v1c_meta)
    reproduction: List[Dict[str, Any]] = []
    if cfg.reproduction:
        reproduction = reproduction_checks(merged, stored)
        for c in reproduction:
            print(f"reproduction {c['configuration']} @ {c['cell']} ({c['study']}): ok={c['ok']} max abs diff {c.get('max_abs_difference', float('nan')):.1e} "
                  f"trades {c.get('n_trades')}/{c.get('n_trades_stored')}", flush=True)
        if reproduction and not all(c["ok"] for c in reproduction):
            bad = [c for c in reproduction if not c["ok"]]
            print(f"STUDY STOPPED: {len(bad)} of {len(reproduction)} stored reproductions differ from the stored numbers: "
                  + "; ".join(f"{c['configuration']} @ {c['cell']}" for c in bad), file=sys.stderr, flush=True)
            return 2
    unexplained = {k: r["protocol_check"]["unexplained_mismatches"] for k, r in merged.items() if not r["protocol_check"]["ok_for_cell"]}
    if unexplained and not args.quick:
        print(f"STUDY STOPPED: the runner's protocol differs from the stored Sprint 2c protocol beyond what a job explains: {json.dumps(unexplained, default=str)[:2000]}",
              file=sys.stderr)
        return 2
    for r in merged.values():
        o = r["oos"]
        print(f"  {r['configuration']} @ {r['cell']['key']} ({r['role']}): CAGR {_pct(o.get('cagr'))} Sharpe {_f(o.get('sharpe'))} maxDD {_pct(o.get('max_drawdown'))} "
              f"Calmar {_f(o.get('calmar'))} PF {_f(o.get('profit_factor'))} trades {o.get('n_trades')} pass4.6={r['acceptance_r18']['passed']} "
              f"in_book={r.get('in_book')} holdout={'opened' if r.get('holdout') else 'untouched'}", flush=True)
    sleeves = sleeve_table(merged)
    data = {m: load_market(study, m) for m in cfg.markets}
    book = run_book_study(study, data, merged, rules=cfg.rules, evaluate_holdout=bool(args.evaluate_holdout and full), log=lambda m: print(m, flush=True)) if cfg.book else None
    rotation = run_rotation_study(data, evaluate_holdout=bool(args.evaluate_holdout and full), log=lambda m: print(m, flush=True)) if (cfg.rotation and "BTC-USDT" in data) else None
    correlations = market_correlations(data)
    div = None
    if book is not None:
        hold_tr = result_of(merged, CONTROL, "BTC-USDT", JUDGED_CELL)
        ew = ((rotation or {}).get("lines") or {}).get("equal_weight_nine_vt20") if rotation else None
        div = diversification(book["judged"], sleeves, None if hold_tr is None else _metrics_of(hold_tr), book.get("hold_btc_book_sim"), ew)
    openings = holdout_openings(merged, series_info, book, rotation)
    looks = earlier_looks(merged, stored)
    ledger = load_ledger(args.holdout_ledger)
    second_look = guard_second_look(ledger, openings, evaluate_holdout=bool(args.evaluate_holdout))
    source = {"study": STUDY_NAME, "report": args.report, "results": args.json, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    recorded = fleet_rows(book, rotation, source=source) if (full and args.evaluate_holdout) else []
    overall = overall_summary(reproduction, sleeves, book, rotation)
    reference_check = next((r["protocol_check"] for r in merged.values() if r["cell"]["key"] == "reference|nobrakes|none"), None)
    run_doc: Dict[str, Any] = {
        "meta": {
            "study": STUDY_NAME, "generated_at": source["generated_at"], "started_at": started, "elapsed_minutes": round((time.monotonic() - t0) / 60.0, 1),
            "config": cfg.to_dict(), "preregistration": PREREGISTRATION, "preregistration_file": args.preregistration,
            "preregistration_written_at": prereg.get("written_at"), "preregistration_sha256": preregistration_hash(cfg, prereg),
            "protocol_check": reference_check, "stored_results": {"v1c": args.v1c_results, "r12": args.r12_results, "r13": args.r13_results, "r16": args.r16_results,
                                                                   "r18": args.r18_results, "r19": args.r19_results},
            "v1c_meta": {k: v1c_meta.get(k) for k in ("generated_at", "data_span", "data_span_short", "holdout_span", "policy_sizing", "regime", "no_trade_label",
                                                      "train_days", "test_days", "purge_days", "fee_rate", "slippage_rate", "bracket_variants")},
            "markets": list(cfg.markets), "rules": list(cfg.rules), "cells": list(cfg.cells), "full_study": full, "evaluate_holdout": bool(args.evaluate_holdout),
            "quick": bool(args.quick), "reproduction": cfg.reproduction, "skipped_series": [f"{s['instrument']}: {s['skipped']}" for s in series_info.values() if s.get("skipped")],
            "data_end": DATA_END, "study_lake": str(study.root), "lake": lake_summary(study, list(cfg.markets)), "gates": dict(GATES),
            "tier_gates": {k: dict(v) for k, v in TIER_GATES.items()}, "workers": args.workers,
            "jobs": [{k: j[k] for k in ("instrument", "timeframe", "strategies", "evaluate_holdout")} | {"cell": j["cell"]["key"]} for j in jobs],
            "report_path": args.report, "json_path": args.json, "holdout_ledger_path": args.holdout_ledger, "second_look_warning": second_look, "run_notes": list(args.run_note),
        },
        "reproduction": reproduction,
        "results": [_strip(r) for r in merged.values()],
        "series_info": series_info,
        "sleeves": sleeves,
        "book": book,
        "rotation": rotation,
        "correlations": correlations,
        "diversification": div,
        "overall": overall,
        "holdout_openings": openings,
        "earlier_looks": looks,
        "shortlist_recorded_only": recorded,
        "shortlist_note": ("recorded only: the paper fleet has no account type for a multi-market book or a weekly rotation; applying a recorded row is a new plan row"
                           if recorded else "nothing recorded for the fleet"),
    }
    if openings and args.holdout_ledger != "-":
        ledger.append({"generated_at": source["generated_at"], "started_at": started, "preregistration_sha256": run_doc["meta"]["preregistration_sha256"],
                       "results_file": args.json, "openings": _rounded(openings), "earlier_looks": _rounded(looks)})
        write_breadth_ledger(args.holdout_ledger, ledger)
        print(f"holdout ledger: {args.holdout_ledger} ({len(ledger)} entries)")
    run_doc["meta"]["holdout_ledger"] = ledger
    saved = json.loads(json.dumps(_rounded(run_doc), default=_json_default))
    if args.json != "-":
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8")
        print(f"results: {args.json}")
    if args.report != "-":
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(_render(saved), encoding="utf-8")
        print(f"report: {args.report}")
    print(f"done in {run_doc['meta']['elapsed_minutes']} min: " + json.dumps({k: v for k, v in overall.items() if not isinstance(v, (list, dict))}, default=str))
    return 0


def _pct(v: Any) -> str:
    return "-" if v is None else f"{float(v) * 100:+.1f}%"


def _f(v: Any) -> str:
    return "-" if v is None else f"{float(v):.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
