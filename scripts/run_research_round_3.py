"""Research round 3: the asymmetric setups of the Trader Plan, section 5 (plan row R19, SIMULATION ONLY).

Steps, in this order, public data only:

1. ``--preregister``: writes ``docs/research/research_round_3_preregistration.json`` (the fixed text, the rules, the
   cells, the gates, a hash) and the report with the pre-registration alone; it refuses to run twice.
2. The study: the frozen study lake (the nine markets' candles cut at Sprint 2c's data end, built with the replication
   study's ``freeze_lake`` when missing), Sprint 2c's own runner loaded as a module with the Trader tier's arguments and the
   fixed-rule protocol variant, the protocol check recorded for every job (the study stops on any mismatch a job does not
   explain), the reproduction of the stored numbers (Sprint 2c's, the replication study's, the Trader Policy study's; the
   study stops on any difference), then every job; ``--evaluate-holdout`` (full pre-registered study only) opens the
   untouched 12 months once for the judged passers and the hold controls at the judged cell and records every opening in
   an append-only ledger. Writes ``docs/research/RESEARCH_ROUND_3_REPORT.md`` and a results JSON; fleet-eligible confirmed
   passers are appended to the paper fleet's shortlist with a ``source`` tag (rolled back when the fleet cannot load the
   file); 1D passers are recorded, never applied.

Example::

    python scripts/run_research_round_3.py --preregister
    python scripts/run_research_round_3.py --evaluate-holdout --workers 12
    python scripts/run_research_round_3.py --hypotheses H8 --markets BTC-USDT --timeframes 6H --regime-modes none --no-barsize --skip-reproduction --report - --json - --holdout-ledger - --shortlist -
    python scripts/run_research_round_3.py --render-from-json docs/research/research_round_3_results.json

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
from research.replication import DATA_END, freeze_lake, load_ledger  # noqa: E402
from research.replication_data import lake_summary  # noqa: E402
from research.report_v1c import GATES  # noqa: E402
from research.round3 import (  # noqa: E402
    ALL_MARKETS,
    BARSIZE_TIMEFRAMES,
    CELLS,
    FIXED_TIMEFRAMES,
    HYPOTHESES,
    PREREGISTRATION,
    PREREGISTRATION_PATH,
    R12_PREREGISTRATION,
    R12_RESULTS,
    R18_RESULTS,
    REFERENCE_CELL,
    STUDY_LAKE_DIRNAME,
    STUDY_MODES,
    STUDY_NAME,
    V1C_RESULTS,
    Round3Config,
    Round3Error,
    annotate_all,
    barsize_table,
    check_replication_markets,
    earlier_looks,
    full_study_requested,
    guard_second_look,
    holdout_openings,
    hypothesis_verdicts,
    load_preregistration,
    merge_results,
    overall_summary,
    plan_jobs,
    preregister,
    preregistration_hash,
    rebuild_merged,
    reproduction_checks,
    result_key,
    run_job,
    shortlist_additions,
    stored_results,
    write_round3_ledger,
)
from research.trader_policy import TIER_GATES  # noqa: E402

DEFAULT_REPORT = "docs/research/RESEARCH_ROUND_3_REPORT.md"
DEFAULT_JSON = "docs/research/research_round_3_results.json"
DEFAULT_LEDGER = "docs/research/research_round_3_holdout_ledger.json"
DEFAULT_SHORTLIST = "docs/research/paper_fleet_shortlist_v1c.json"


def _rel(path: Path) -> str:
    return str(path.relative_to(Path(__file__).resolve().parents[1]).as_posix())


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Research round 3: the asymmetric setups of the Trader Plan, pre-registered (simulation only).")
    p.add_argument("--preregister", action="store_true", help="Write the pre-registration file and the report stub (once), then exit.")
    p.add_argument("--force-preregister", action="store_true", help="Overwrite an existing pre-registration (only before any result exists).")
    p.add_argument("--freeze", action="store_true", help="Build the study lake (the nine markets' candles cut at Sprint 2c's data end), then exit.")
    p.add_argument("--refreeze", action="store_true", help="Rebuild the study lake before the study.")
    p.add_argument("--hypotheses", nargs="+", default=[h.key for h in HYPOTHESES], choices=[h.key for h in HYPOTHESES])
    p.add_argument("--markets", nargs="+", default=list(ALL_MARKETS), choices=list(ALL_MARKETS))
    p.add_argument("--timeframes", nargs="+", default=list(FIXED_TIMEFRAMES), choices=list(FIXED_TIMEFRAMES))
    p.add_argument("--regime-modes", nargs="+", default=list(STUDY_MODES), choices=list(STUDY_MODES))
    p.add_argument("--cells", nargs="+", default=[c.key for c in CELLS], choices=[c.key for c in CELLS])
    p.add_argument("--no-barsize", action="store_true", help="Skip the bar-size comparison (smoke runs only).")
    p.add_argument("--evaluate-holdout", action="store_true", help="Open the untouched 12 months once for the judged passers (full study only).")
    p.add_argument("--quick", action="store_true", help="Cut grids, no reproduction: a smoke run, never a result.")
    p.add_argument("--skip-reproduction", action="store_true", help="Skip the reproduction gate (smoke runs only; refused with --evaluate-holdout).")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--lake-dir", default=None, help="The research lake (default $DATA_LAKE_DIR or data/lake).")
    p.add_argument("--study-lake-dir", default=None, help=f"The frozen study lake (default: <research lake>/../{STUDY_LAKE_DIRNAME}).")
    p.add_argument("--preregistration", default=_rel(PREREGISTRATION_PATH))
    p.add_argument("--r12-preregistration", default=_rel(R12_PREREGISTRATION), help="The replication study's pre-registration (its fixed market list).")
    p.add_argument("--v1c-results", default=_rel(V1C_RESULTS))
    p.add_argument("--r12-results", default=_rel(R12_RESULTS))
    p.add_argument("--r18-results", default=_rel(R18_RESULTS))
    p.add_argument("--report", default=DEFAULT_REPORT, help="'-' = do not write")
    p.add_argument("--json", default=DEFAULT_JSON, help="'-' = do not write")
    p.add_argument("--holdout-ledger", default=DEFAULT_LEDGER, help="Append-only record of every holdout opening ('-' = none; refused with --evaluate-holdout).")
    p.add_argument("--shortlist", default=DEFAULT_SHORTLIST, help="The paper fleet's shortlist to append fleet-eligible confirmed passers to ('-' = do not touch).")
    p.add_argument("--run-note", action="append", default=[], metavar="TEXT",
                   help="A sentence recorded in the results' meta and printed under the report's method notes (an honesty note about an earlier run, for instance).")
    p.add_argument("--render-from-json", default=None, metavar="PATH", help="Re-render the report from a saved results JSON.")
    p.add_argument("--apply-shortlist-from-json", default=None, metavar="PATH",
                   help="Apply the shortlist additions recorded in a saved results JSON (no re-run, no new holdout look), then re-render the report.")
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
    from research.report_round3 import render_report  # imported late: the study can run before a report is rendered

    return render_report(run)


def _strip(result: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON-safe view of one result (no pandas objects, no runner args)."""
    return {k: v for k, v in result.items() if k not in ("trades", "args")}


def cmd_preregister(args: argparse.Namespace) -> int:
    path = Path(args.preregistration)
    try:
        payload = preregister(path, force=args.force_preregister, r12_path=Path(args.r12_preregistration))
    except Round3Error as exc:
        print(f"not written: {exc}", file=sys.stderr)
        return 2
    print(f"pre-registration written: {path} (sha256 {payload['sha256'][:16]}..., {len(PREREGISTRATION['hypotheses'])} hypotheses, "
          f"{len(payload['candidates'])} fixed rules, cells {[c['key'] for c in payload['cells']]})")
    for key, h in PREREGISTRATION["hypotheses"].items():
        print(f"  {key}: {h['title']} - {', '.join(h['candidates'])} on {len(h['markets'])} markets, bars {h['timeframes']}")
    if args.report != "-":
        # The pre-registration goes into the report BEFORE the first run; the study overwrites it with the same text plus the results.
        stub = {"meta": {"study": STUDY_NAME, "preregistration": PREREGISTRATION, "preregistration_file": str(path.as_posix()), "preregistration_written_at": payload["written_at"],
                         "preregistration_sha256": preregistration_hash(Round3Config(), payload), "data_end": DATA_END, "gates": dict(GATES),
                         "tier_gates": {k: dict(v) for k, v in TIER_GATES.items()}}, "results": [], "verdicts": [], "overall": {}}
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(_render(stub), encoding="utf-8")
        print(f"report stub (pre-registration only): {args.report}")
    return 0


def cmd_freeze(research: LakeLayout, study: LakeLayout) -> Dict[str, Any]:
    print(f"freezing the study lake at {study.root} (bar close <= {DATA_END}) ...", flush=True)
    return freeze_lake(research, study, list(ALL_MARKETS), end=DATA_END, log=lambda m: print(m, flush=True))


def _apply_shortlist_additions(path: Path, additions: List[Dict[str, Any]]) -> str:
    """Append the fleet-eligible confirmed passers, then prove the paper fleet can still load its manifest; otherwise restore the file (the R12 rule)."""
    from research.paper_fleet.config import load_manifest
    from research.replication import append_to_shortlist

    original = path.read_text(encoding="utf-8")
    data = append_to_shortlist(path, additions, note="plan row R19: confirmed passers of research round 3 at the Trader tier under the fixed-rule protocol (holdout confirmed)")
    try:
        manifest = load_manifest(path)
    except Exception as exc:  # the fleet cannot read the amended file: put the original back, report, never break the fleet
        path.write_text(original, encoding="utf-8")
        return f"NOT applied — the paper fleet cannot load the amended shortlist ({type(exc).__name__}: {exc}); the file was restored; the rows stay recorded in the report"
    return f"{path.as_posix()} now lists {len(data.get('configurations', []))} configurations ({len(manifest.accounts)} fleet accounts)"


def cmd_apply_shortlist(args: argparse.Namespace) -> int:
    path = Path(args.apply_shortlist_from_json)
    run = json.loads(path.read_text(encoding="utf-8"))
    additions = run.get("shortlist_additions") or []
    if not additions:
        print("no shortlist additions are recorded in the results; nothing to apply")
        return 0
    if args.shortlist == "-":
        print("--apply-shortlist-from-json needs a shortlist file", file=sys.stderr)
        return 2
    note = _apply_shortlist_additions(Path(args.shortlist), additions)
    run["shortlist_note"] = note
    path.write_text(json.dumps(run, separators=(",", ":")), encoding="utf-8")
    if args.report != "-":
        Path(args.report).write_text(_render(run), encoding="utf-8")
    print(f"shortlist: {note}")
    return 0 if not note.startswith("NOT applied") else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.render_from_json:
        run = json.loads(Path(args.render_from_json).read_text(encoding="utf-8"))
        if run.get("results") and (run.get("meta") or {}).get("barsize_timeframes"):
            run["barsize"] = _rounded(barsize_table(rebuild_merged(run["results"])))  # a derived table: recomputed from the saved results
        if args.report != "-":
            Path(args.report).write_text(_render(run), encoding="utf-8")
            print(f"report re-rendered: {args.report}")
        return 0
    if args.apply_shortlist_from_json:
        return cmd_apply_shortlist(args)
    if args.preregister:
        return cmd_preregister(args)
    try:
        prereg = load_preregistration(Path(args.preregistration))
        check_replication_markets(Path(args.r12_preregistration))
    except (OSError, Round3Error, ValueError) as exc:
        print(f"no usable pre-registration ({exc}); run --preregister first", file=sys.stderr)
        return 2
    research = _research_lake(args)
    study = _study_lake(args, research)
    if args.freeze:
        print(json.dumps(cmd_freeze(research, study), indent=1))
        return 0
    cfg = Round3Config(hypotheses=tuple(args.hypotheses), markets=tuple(m for m in ALL_MARKETS if m in args.markets), timeframes=tuple(args.timeframes),
                       regime_modes=tuple(args.regime_modes), cells=tuple(args.cells), barsize=not args.no_barsize,
                       reproduction=not (args.quick or args.skip_reproduction), quick=bool(args.quick), lake_dir=str(study.root))
    full = full_study_requested(cfg)
    if args.evaluate_holdout and not full:
        print("--evaluate-holdout needs the full pre-registered study: every hypothesis, market, timeframe, mode and cell, the bar-size comparison, with the reproduction, "
              "without --quick", file=sys.stderr)
        return 2
    if args.evaluate_holdout and args.holdout_ledger == "-":
        print("--evaluate-holdout needs a holdout ledger", file=sys.stderr)
        return 2
    v1c_doc = json.loads(Path(args.v1c_results).read_text(encoding="utf-8"))
    r12_doc = json.loads(Path(args.r12_results).read_text(encoding="utf-8"))
    r18_doc = json.loads(Path(args.r18_results).read_text(encoding="utf-8"))
    v1c_meta = v1c_doc["meta"]
    stored = stored_results(v1c_doc, r12_doc, r18_doc)
    if args.refreeze or not all(any(study.candles_dir(m, b).exists() for b in ("1H", "4H")) for m in cfg.all_markets):
        cmd_freeze(research, study)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    t0 = time.monotonic()
    jobs = plan_jobs(cfg, evaluate_holdout=bool(args.evaluate_holdout))
    print(f"{len(jobs)} jobs on {args.workers} worker(s): " + ", ".join(f"{j['instrument']} {j['timeframe']} {j['kind']} @ {j['cell']['key']}" for j in jobs), flush=True)
    if args.workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(jobs))) as pool:
            outputs = list(pool.map(run_job, jobs))
    else:
        outputs = [run_job(j) for j in jobs]
    merged, series_info = merge_results(outputs, v1c_meta)
    trades: Dict[str, Any] = {}
    for o in outputs:
        if o.get("skipped"):
            continue
        for key, t in (o.get("trades") or {}).items():
            cand, mode = key.split("|")
            trades[result_key(cand, o["instrument"], o["timeframe"], mode, o["cell"]["key"])] = t
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
    annotate_all(merged)
    for r in merged.values():
        o = r["oos"]
        print(f"  {r['configuration']} @ {r['cell']['key']} ({r['role']}): CAGR {_pct(o.get('cagr'))} Sharpe {_f(o.get('sharpe'))} maxDD {_pct(o.get('max_drawdown'))} "
              f"Calmar {_f(o.get('calmar'))} PF {_f(o.get('profit_factor'))} trades {o.get('n_trades')} ({_f(o.get('trades_per_year'))}/yr) "
              f"pass4.6={r['acceptance_r18']['passed']} holdout={'opened' if r.get('holdout') else 'untouched'}", flush=True)
    verdicts = hypothesis_verdicts(merged, cfg, trades)
    overall = overall_summary(verdicts, merged)
    barsize = barsize_table(merged) if cfg.barsize else {"rows": [], "best": [], "reading": {}}
    openings = holdout_openings(merged, series_info)
    looks = earlier_looks(merged, stored)
    ledger = load_ledger(args.holdout_ledger)
    second_look = guard_second_look(ledger, openings, evaluate_holdout=bool(args.evaluate_holdout))
    source = {"study": STUDY_NAME, "report": args.report, "results": args.json, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    additions, recorded = shortlist_additions(merged, source=source) if (full and args.evaluate_holdout) else ([], [])
    reference_check = next((r["protocol_check"] for r in merged.values() if r["cell"]["key"] == REFERENCE_CELL.key and r["timeframe"] != "1D"
                            and r["kind"] in ("control", "barsize")), None)
    run_doc: Dict[str, Any] = {
        "meta": {
            "study": STUDY_NAME, "generated_at": source["generated_at"], "started_at": started, "elapsed_minutes": round((time.monotonic() - t0) / 60.0, 1),
            "config": cfg.to_dict(), "preregistration": PREREGISTRATION, "preregistration_file": args.preregistration,
            "preregistration_written_at": prereg.get("written_at"), "preregistration_sha256": preregistration_hash(cfg, prereg),
            # The protocol check of a Reference cell on 4H/6H bars is Sprint 2c's; every result carries its own job's check (a tier, the fixed-rule
            # protocol and 1D bars are documented mismatches), so nothing is duplicated here.
            "protocol_check": reference_check,
            "v1c_results": args.v1c_results, "r12_results": args.r12_results, "r18_results": args.r18_results,
            "v1c_meta": {k: v1c_meta.get(k) for k in ("generated_at", "data_span", "data_span_short", "holdout_span", "policy_sizing", "regime", "no_trade_label",
                                                      "train_days", "test_days", "purge_days", "fee_rate", "slippage_rate", "bracket_variants")},
            "markets": list(cfg.all_markets), "timeframes": list(cfg.timeframes), "barsize_timeframes": list(BARSIZE_TIMEFRAMES) if cfg.barsize else [],
            "full_study": full, "evaluate_holdout": bool(args.evaluate_holdout), "quick": bool(args.quick), "reproduction": cfg.reproduction,
            "skipped_series": [f"{s['instrument']} {s['timeframe']}: {s['skipped']}" for s in series_info.values() if s.get("skipped")],
            "data_end": DATA_END, "study_lake": str(study.root), "lake": lake_summary(study, list(cfg.all_markets)),
            "gates": dict(GATES), "tier_gates": {k: dict(v) for k, v in TIER_GATES.items()}, "workers": args.workers,
            "jobs": [{k: j[k] for k in ("instrument", "timeframe", "kind", "strategies", "evaluate_holdout")} | {"cell": j["cell"]["key"]} for j in jobs],
            "report_path": args.report, "json_path": args.json, "holdout_ledger_path": args.holdout_ledger, "second_look_warning": second_look,
            "run_notes": list(args.run_note),
        },
        "reproduction": reproduction,
        "results": [_strip(r) for r in merged.values()],
        "series_info": series_info,
        "verdicts": verdicts,
        "overall": overall,
        "barsize": barsize,
        "holdout_openings": openings,
        "earlier_looks": looks,
        "shortlist_additions": _rounded(additions),
        "shortlist_recorded_only": _rounded(recorded),
        "shortlist_note": None,
    }
    if openings and args.holdout_ledger != "-":
        ledger.append({"generated_at": source["generated_at"], "started_at": started, "preregistration_sha256": run_doc["meta"]["preregistration_sha256"],
                       "results_file": args.json, "openings": _rounded(openings), "earlier_looks": _rounded(looks)})
        write_round3_ledger(args.holdout_ledger, ledger)
        print(f"holdout ledger: {args.holdout_ledger} ({len(ledger)} entries)")
    run_doc["meta"]["holdout_ledger"] = ledger
    saved = json.loads(json.dumps(_rounded(run_doc), default=_json_default))
    if args.json != "-":
        # The results file first: the paper fleet validates a source-tagged shortlist row against it.
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8")
        print(f"results: {args.json}")
    if additions and args.shortlist != "-":
        if args.json == "-":
            saved["shortlist_note"] = "NOT applied — the paper fleet validates a shortlist row against the study's results file, and this run wrote none (--json -)"
        else:
            saved["shortlist_note"] = _apply_shortlist_additions(Path(args.shortlist), saved["shortlist_additions"])
        print(f"shortlist: {saved['shortlist_note']}")
        if args.json != "-":
            Path(args.json).write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8")
    if args.report != "-":
        Path(args.report).write_text(_render(saved), encoding="utf-8")
        print(f"report: {args.report}")
    labels = "; ".join(f"{k}: {v}" for k, v in overall["labels"].items())
    print(f"verdicts (primary): {labels} - {overall['n_passed']} of {overall['n_judged']} judged configurations pass; holdout confirmed {overall['n_confirmed']}, "
          f"contradicted {overall['n_contradicted']}; fleet-eligible {overall['fleet_eligible'] or 'none'}; bar size: "
          f"{'holds' if (barsize.get('reading') or {}).get('holds') else 'does not hold'}; done in {run_doc['meta']['elapsed_minutes']} min")
    return 0


def _pct(v: Any) -> str:
    return "-" if v is None else f"{float(v) * 100:+.1f}%"


def _f(v: Any) -> str:
    return "-" if v is None else f"{float(v):.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
