"""Trader Policy v1: the five confirmed configurations at three fixed risk budgets, with brakes and variants (plan row R18, SIMULATION ONLY).

Steps, in this order, public data only:

1. ``--preregister``: writes ``docs/research/trader_policy_v1_preregistration.json`` (the fixed text, the tiers, the brakes, the
   variants, the gates, a hash); it refuses to run twice.
2. The study: the frozen study lake (BTC, ETH, SOL and DOGE candles cut at Sprint 2c's data end, built with the replication study's
   ``freeze_lake`` when missing), Sprint 2c's own runner loaded as a module with its R18 arguments (tier sizing, brakes, variant,
   cost replays), the protocol check against the stored Sprint 2c run (recorded for every cell: a tier is a documented
   ``policy_sizing`` mismatch), the reproduction of the stored numbers at the Reference cell (the study stops on any difference),
   then every cell; ``--evaluate-holdout`` (full pre-registered study only) opens the untouched 12 months for the Reference
   reproduction, the hold controls and the brakes-on Trader / Aggressive cells that pass, recording every opening in an append-only
   ledger. Writes ``docs/research/TRADER_POLICY_V1_REPORT.md`` and a results JSON; the fleet rows (Trader-tier passers, the TF forward
   control) are RECORDED in the results for plan row R18b, which extends the fleet's loader before applying them.

Example::

    python scripts/run_trader_policy_v1.py --preregister
    python scripts/run_trader_policy_v1.py --evaluate-holdout --workers 12
    python scripts/run_trader_policy_v1.py --quick --runs C1 H2 --cells "reference|nobrakes|none" "trader|brakes|none" --skip-reproduction --report - --json - --holdout-ledger -
    python scripts/run_trader_policy_v1.py --render-from-json docs/research/trader_policy_v1_results.json

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
from research.trader_policy import TIER_GATES  # noqa: E402
from research.trader_policy_study import (  # noqa: E402
    ALL_RUNS,
    BY_KEY,
    CONFIGURATIONS,
    CONTROLS,
    CORE_CELLS,
    MARKETS,
    PREREGISTRATION,
    PREREGISTRATION_PATH,
    R12_RESULTS,
    R13_RESULTS,
    R16_RESULTS,
    STUDY_LAKE_DIRNAME,
    STUDY_NAME,
    V1C_RESULTS,
    VARIANT_CELLS,
    Cell,
    StudyConfig,
    TraderPolicyError,
    brake_analysis,
    configuration_verdict,
    cost_table,
    earlier_looks,
    full_study_requested,
    guard_second_look,
    holdout_openings,
    load_preregistration,
    merge_results,
    overall_summary,
    plan_jobs,
    pooled_conviction_test,
    preregister,
    preregistration_hash,
    reproduction_checks,
    run_job,
    shortlist_additions,
    stored_results,
    tier_table,
    variant_analysis,
    write_ledger,
)

DEFAULT_REPORT = "docs/research/TRADER_POLICY_V1_REPORT.md"
DEFAULT_JSON = "docs/research/trader_policy_v1_results.json"
DEFAULT_LEDGER = "docs/research/trader_policy_v1_holdout_ledger.json"
ALL_CELL_KEYS = [c.key for c in CORE_CELLS + VARIANT_CELLS]


def _rel(path: Path) -> str:
    return str(path.relative_to(Path(__file__).resolve().parents[1]).as_posix())


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Trader Policy v1: the confirmed configurations at three fixed risk budgets, with brakes and variants (simulation only).")
    p.add_argument("--preregister", action="store_true", help="Write the pre-registration file (once), then exit.")
    p.add_argument("--force-preregister", action="store_true", help="Overwrite an existing pre-registration (only before any result exists).")
    p.add_argument("--freeze", action="store_true", help="Build the study lake (the four markets' candles cut at Sprint 2c's data end), then exit.")
    p.add_argument("--refreeze", action="store_true", help="Rebuild the study lake before the study.")
    p.add_argument("--runs", nargs="+", default=[c.key for c in ALL_RUNS], choices=[c.key for c in ALL_RUNS], help="Configurations / controls to run (default all).")
    p.add_argument("--cells", nargs="+", default=list(ALL_CELL_KEYS), choices=list(ALL_CELL_KEYS), help="Cells (tier|brakes|variant) to run (default all).")
    p.add_argument("--evaluate-holdout", action="store_true", help="Open the untouched 12 months for the pre-registered cells (full study only).")
    p.add_argument("--quick", action="store_true", help="Cut grids, no reproduction: a smoke run, never a result.")
    p.add_argument("--skip-reproduction", action="store_true", help="Skip the reproduction gate (smoke runs only; refused with --evaluate-holdout).")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--lake-dir", default=None, help="The research lake (default $DATA_LAKE_DIR or data/lake).")
    p.add_argument("--study-lake-dir", default=None, help=f"The frozen study lake (default: <research lake>/../{STUDY_LAKE_DIRNAME}).")
    p.add_argument("--preregistration", default=_rel(PREREGISTRATION_PATH))
    p.add_argument("--v1c-results", default=_rel(V1C_RESULTS))
    p.add_argument("--r12-results", default=_rel(R12_RESULTS))
    p.add_argument("--r13-results", default=_rel(R13_RESULTS))
    p.add_argument("--r16-results", default=_rel(R16_RESULTS))
    p.add_argument("--report", default=DEFAULT_REPORT, help="'-' = do not write")
    p.add_argument("--json", default=DEFAULT_JSON, help="'-' = do not write")
    p.add_argument("--holdout-ledger", default=DEFAULT_LEDGER, help="Append-only record of every holdout opening ('-' = none; refused with --evaluate-holdout).")
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
    from research.report_trader_policy import render_report  # imported late: the study can run before a report is rendered

    return render_report(run)


def _strip(result: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON-safe view of one cell's result (no pandas objects, no runner args)."""
    return {k: v for k, v in result.items() if k not in ("trades", "args")}


def cmd_preregister(args: argparse.Namespace) -> int:
    path = Path(args.preregistration)
    try:
        payload = preregister(path, force=args.force_preregister)
    except TraderPolicyError as exc:
        print(f"not written: {exc}", file=sys.stderr)
        return 2
    print(f"pre-registration written: {path} (sha256 {payload['sha256'][:16]}..., {len(CONFIGURATIONS)} configurations, {len(CONTROLS)} hold controls, "
          f"{len(CORE_CELLS)} core cells, {len(VARIANT_CELLS)} variant cells)")
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
    except (OSError, TraderPolicyError, ValueError) as exc:
        print(f"no usable pre-registration ({exc}); run --preregister first", file=sys.stderr)
        return 2
    research = _research_lake(args)
    study = _study_lake(args, research)
    if args.freeze:
        print(json.dumps(cmd_freeze(research, study), indent=1))
        return 0
    cfg = StudyConfig(runs=tuple(args.runs), cells=tuple(args.cells), reproduction=not (args.quick or args.skip_reproduction), quick=bool(args.quick),
                      lake_dir=str(study.root))
    full = full_study_requested(cfg)
    if args.evaluate_holdout and not full:
        print("--evaluate-holdout needs the full pre-registered study: every configuration, control and cell, with the reproduction, without --quick", file=sys.stderr)
        return 2
    if args.evaluate_holdout and args.holdout_ledger == "-":
        print("--evaluate-holdout needs a holdout ledger", file=sys.stderr)
        return 2
    docs = {"Sprint 2c": json.loads(Path(args.v1c_results).read_text(encoding="utf-8")),
            "R12 replication": json.loads(Path(args.r12_results).read_text(encoding="utf-8")),
            "R13 research round 1": json.loads(Path(args.r13_results).read_text(encoding="utf-8")),
            "R16 research round 2": json.loads(Path(args.r16_results).read_text(encoding="utf-8"))}
    v1c_meta = docs["Sprint 2c"]["meta"]
    stored = stored_results(docs)
    if args.refreeze or not all(any(study.candles_dir(m, b).exists() for b in ("1H", "4H")) for m in cfg.markets):
        cmd_freeze(research, study)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    t0 = time.monotonic()
    jobs = plan_jobs(cfg, evaluate_holdout=bool(args.evaluate_holdout))
    print(f"{len(jobs)} jobs on {args.workers} worker(s)", flush=True)
    if args.workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(jobs))) as pool:
            outputs = list(pool.map(run_job, jobs))
    else:
        outputs = [run_job(j) for j in jobs]
    merged = merge_results(outputs, v1c_meta)
    reproduction: List[Dict[str, Any]] = []
    if cfg.reproduction:
        reproduction = reproduction_checks(merged, stored)
        for c in reproduction:
            print(f"reproduction {c['configuration']} ({c['study']}): ok={c['ok']} max abs diff {c.get('max_abs_difference', float('nan')):.1e} "
                  f"trades {c.get('n_trades')}/{c.get('n_trades_stored')} {c.get('note', '')}", flush=True)
        bad = [c for c in reproduction if not c["ok"]]
        if bad:
            print(f"STUDY STOPPED: {len(bad)} of {len(reproduction)} stored reproductions differ from the stored numbers: "
                  + "; ".join(c["configuration"] for c in bad), file=sys.stderr, flush=True)
            return 2
    unexplained = {k: r["protocol_check"]["unexplained_mismatches"] for k, r in merged.items() if not r.get("skipped") and not r["protocol_check"]["ok_for_cell"]}
    if unexplained and not args.quick:
        print(f"STUDY STOPPED: the runner's protocol differs from the stored Sprint 2c protocol beyond the tier: {json.dumps(unexplained, default=str)[:2000]}",
              file=sys.stderr)
        return 2
    for key, r in merged.items():
        if r.get("skipped"):
            print(f"  {key}: skipped ({r['skipped']})", flush=True)
            continue
        o = r["oos"]
        print(f"  {r['configuration']} @ {r['cell']['label']}: CAGR {_pct(o.get('cagr'))} Sharpe {_f(o.get('sharpe'))} maxDD {_pct(o.get('max_drawdown'))} "
              f"Calmar {_f(o.get('calmar'))} PF {_f(o.get('profit_factor'))} vol {_pct(o.get('ann_vol'))} trades {o.get('n_trades')} "
              f"pass4.6={r['acceptance_r18']['passed']} holdout={'opened' if r.get('holdout') else 'untouched'}", flush=True)
    runs = [BY_KEY[k] for k in cfg.runs]
    verdicts = [configuration_verdict(merged, run) for run in runs]
    overall = overall_summary(merged, verdicts)
    analyses = {run.key: {"run": run.to_dict(), "tiers": tier_table(merged, run), "brakes": brake_analysis(merged, run),
                          "variants": variant_analysis(merged, run) if run.role == "configuration" else [], "costs": cost_table(merged, run)} for run in runs}
    pooled = pooled_conviction_test(merged)
    openings = holdout_openings(merged)
    looks = earlier_looks(merged, stored)
    ledger = load_ledger(args.holdout_ledger)
    second_look = guard_second_look(ledger, openings, evaluate_holdout=bool(args.evaluate_holdout))
    source = {"study": STUDY_NAME, "report": args.report, "results": args.json, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    additions = shortlist_additions(merged, verdicts, source=source) if full and args.evaluate_holdout else []
    run_doc: Dict[str, Any] = {
        "meta": {
            "study": STUDY_NAME, "generated_at": source["generated_at"], "started_at": started, "elapsed_minutes": round((time.monotonic() - t0) / 60.0, 1),
            "config": cfg.to_dict(), "preregistration": PREREGISTRATION, "preregistration_file": args.preregistration,
            "preregistration_written_at": prereg.get("written_at"), "preregistration_sha256": preregistration_hash(cfg, prereg),
            # The protocol check of the Reference cell is Sprint 2c's; every cell carries its own (a tier is a documented mismatch).
            "protocol_check": next((r["protocol_check"] for r in merged.values() if not r.get("skipped") and r["cell"]["key"] == "reference|nobrakes|none"), None),
            "protocol_checks_by_cell": {k: r["protocol_check"] for k, r in merged.items() if not r.get("skipped")},
            "v1c_results": args.v1c_results, "r12_results": args.r12_results, "r13_results": args.r13_results, "r16_results": args.r16_results,
            "v1c_meta": {k: v1c_meta.get(k) for k in ("generated_at", "data_span", "data_span_short", "holdout_span", "policy_sizing", "regime", "no_trade_label",
                                                      "train_days", "test_days", "purge_days", "fee_rate", "slippage_rate", "bracket_variants")},
            "markets": list(cfg.markets), "full_study": full, "evaluate_holdout": bool(args.evaluate_holdout), "quick": bool(args.quick),
            "reproduction": cfg.reproduction, "data_end": DATA_END, "study_lake": str(study.root), "lake": lake_summary(study, list(cfg.markets)),
            "gates": dict(GATES), "tier_gates": {k: dict(v) for k, v in TIER_GATES.items()}, "workers": args.workers,
            "jobs": [{k: j[k] for k in ("run", "cell", "evaluate_holdout")} for j in jobs], "report_path": args.report, "json_path": args.json,
            "holdout_ledger_path": args.holdout_ledger, "second_look_warning": second_look,
        },
        "reproduction": reproduction,
        "results": [_strip(r) for r in merged.values()],
        "analyses": analyses,
        "verdicts": verdicts,
        "overall": overall,
        "pooled_conviction": pooled,
        "holdout_openings": openings,
        "earlier_looks": looks,
        "shortlist_additions": additions,
        "shortlist_note": ("recorded for plan row R18b: the fleet's loader must learn to validate a tier-tagged row before these are appended; "
                           "the shortlist file is untouched by this run" if additions else None),
    }
    if openings and args.holdout_ledger != "-":
        ledger.append({"generated_at": source["generated_at"], "started_at": started, "preregistration_sha256": run_doc["meta"]["preregistration_sha256"],
                       "results_file": args.json, "openings": _rounded(openings), "earlier_looks": _rounded(looks)})
        write_ledger(args.holdout_ledger, ledger)
        print(f"holdout ledger: {args.holdout_ledger} ({len(ledger)} entries)")
    run_doc["meta"]["holdout_ledger"] = ledger
    saved = json.loads(json.dumps(_rounded(run_doc), default=_json_default))
    if args.json != "-":
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8")
        print(f"results: {args.json}")
    if args.report != "-":
        Path(args.report).write_text(_render(saved), encoding="utf-8")
        print(f"report: {args.report}")
    print(f"fleet candidates at the {overall.get('fleet_tier', 'trader')} tier: {overall['fleet_candidates'] or 'none'}; "
          f"passes at trader/brakes-on: {overall.get('passed_trader|brakes|none')} of {overall.get('n_trader|brakes|none')}; done in {run_doc['meta']['elapsed_minutes']} min")
    return 0


def _pct(v: Any) -> str:
    return "-" if v is None else f"{float(v) * 100:+.1f}%"


def _f(v: Any) -> str:
    return "-" if v is None else f"{float(v):.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
