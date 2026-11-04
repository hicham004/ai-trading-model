"""Research round 1: three pre-registered hypotheses on the unchanged Sprint 2c rules (plan row R13, SIMULATION ONLY).

Steps, in this order, public data only:

1. ``--preregister``: writes ``docs/research/research_round_1_preregistration.json`` (the fixed text, the
   configuration, the gates, a hash); it refuses to run twice.
2. The study: the frozen study lake (BTC/ETH candles cut at Sprint 2c's data end, built with the
   replication study's ``freeze_lake`` when missing), Sprint 2c's own runner loaded as a module with a
   feature context that also carries the other market's candles, the protocol check against the stored
   Sprint 2c run, the hold/S1/S2 reproduction on BTC and ETH (the study stops on any difference), then the
   new rules; ``--evaluate-holdout`` (full pre-registered study only) opens the untouched 12 months once
   for walk-forward passers and records every opening in an append-only ledger. Writes
   ``docs/research/RESEARCH_ROUND_1_REPORT.md`` and a results JSON; confirmed passers are appended to the
   paper fleet's shortlist with a ``source`` tag (rolled back when the fleet cannot load the file).

Example::

    python scripts/run_research_round_1.py --preregister
    python scripts/run_research_round_1.py --evaluate-holdout --workers 12
    python scripts/run_research_round_1.py --quick --hypotheses H2 --timeframes 4H --regime-modes none --skip-reproduction --report - --json - --holdout-ledger - --shortlist -
    python scripts/run_research_round_1.py --render-from-json docs/research/research_round_1_results.json

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
from research.markets import SPRINT_2C_INSTRUMENTS  # noqa: E402
from research.replication import DATA_END, freeze_lake, load_ledger  # noqa: E402
from research.replication_data import lake_summary  # noqa: E402
from research.report_v1c import GATES  # noqa: E402
from research.round1 import (  # noqa: E402
    HYPOTHESES,
    PREREGISTRATION,
    PREREGISTRATION_PATH,
    REPRODUCTION_STRATEGIES,
    STUDY_LAKE_DIRNAME,
    STUDY_MODES,
    STUDY_NAME,
    STUDY_TIMEFRAMES,
    V1C_RESULTS,
    Round1Config,
    Round1Error,
    annotate_all,
    build_combined_results,
    full_study_requested,
    guard_second_look,
    holdout_openings,
    hypothesis_verdicts,
    load_preregistration,
    merge_series,
    overall_summary,
    plan_jobs,
    preregister,
    preregistration_hash,
    protocol_check_round1,
    reproduction_check,
    round1_args,
    run_job,
    shortlist_additions,
    write_round1_ledger,
)

DEFAULT_REPORT = "docs/research/RESEARCH_ROUND_1_REPORT.md"
DEFAULT_JSON = "docs/research/research_round_1_results.json"
DEFAULT_LEDGER = "docs/research/research_round_1_holdout_ledger.json"
DEFAULT_SHORTLIST = "docs/research/paper_fleet_shortlist_v1c.json"


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Research round 1: pre-registered entry conditions on the Sprint 2c rules (simulation only).")
    p.add_argument("--preregister", action="store_true", help="Write the pre-registration file (once), then exit.")
    p.add_argument("--force-preregister", action="store_true", help="Overwrite an existing pre-registration (only before any result exists).")
    p.add_argument("--freeze", action="store_true", help="Build the study lake (BTC/ETH candles cut at Sprint 2c's data end), then exit.")
    p.add_argument("--refreeze", action="store_true", help="Rebuild the study lake before the study.")
    p.add_argument("--hypotheses", nargs="+", default=[h.key for h in HYPOTHESES], choices=[h.key for h in HYPOTHESES])
    p.add_argument("--timeframes", nargs="+", default=list(STUDY_TIMEFRAMES), choices=list(STUDY_TIMEFRAMES))
    p.add_argument("--regime-modes", nargs="+", default=list(STUDY_MODES), choices=list(STUDY_MODES))
    p.add_argument("--evaluate-holdout", action="store_true", help="Open the untouched 12 months once for walk-forward passers (full study only).")
    p.add_argument("--quick", action="store_true", help="Cut grids, no reproduction: a smoke run, never a result.")
    p.add_argument("--skip-reproduction", action="store_true", help="Skip the hold/S1/S2 reproduction (smoke runs only; refused with --evaluate-holdout).")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--lake-dir", default=None, help="The research lake (default $DATA_LAKE_DIR or data/lake).")
    p.add_argument("--study-lake-dir", default=None, help=f"The frozen study lake (default: <research lake>/../{STUDY_LAKE_DIRNAME}).")
    p.add_argument("--preregistration", default=str(PREREGISTRATION_PATH.relative_to(Path(__file__).resolve().parents[1]).as_posix()))
    p.add_argument("--v1c-results", default=str(V1C_RESULTS.relative_to(Path(__file__).resolve().parents[1]).as_posix()))
    p.add_argument("--report", default=DEFAULT_REPORT, help="'-' = do not write")
    p.add_argument("--json", default=DEFAULT_JSON, help="'-' = do not write")
    p.add_argument("--holdout-ledger", default=DEFAULT_LEDGER, help="Append-only record of every holdout opening ('-' = none; refused with --evaluate-holdout).")
    p.add_argument("--shortlist", default=DEFAULT_SHORTLIST, help="The paper fleet's shortlist to append confirmed passers to ('-' = do not touch).")
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
    from research.report_round1 import render_report  # imported late: the study can run before a report is rendered

    return render_report(run)


def _strip_series(series: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON-safe view of a merged series (no pandas objects, no runner args)."""
    return {k: v for k, v in series.items() if k not in ("sleeves", "trades", "args")}


def cmd_preregister(args: argparse.Namespace) -> int:
    path = Path(args.preregistration)
    try:
        payload = preregister(path, force=args.force_preregister)
    except Round1Error as exc:
        print(f"not written: {exc}", file=sys.stderr)
        return 2
    print(f"pre-registration written: {path} (sha256 {payload['sha256'][:16]}..., {len(PREREGISTRATION['hypotheses'])} hypotheses)")
    for key, h in PREREGISTRATION["hypotheses"].items():
        print(f"  {key}: {h['title']} — {', '.join(h['candidates'])} on {', '.join(h['markets'])}")
    return 0


def cmd_freeze(research: LakeLayout, study: LakeLayout) -> Dict[str, Any]:
    print(f"freezing the study lake at {study.root} (bar close <= {DATA_END}) ...", flush=True)
    return freeze_lake(research, study, list(SPRINT_2C_INSTRUMENTS), end=DATA_END, log=lambda m: print(m, flush=True))


def _apply_shortlist_additions(path: Path, additions: List[Dict[str, Any]]) -> str:
    """Append the confirmed passers, then prove the paper fleet can still load its manifest; otherwise restore the file untouched (the R12 rule)."""
    from research.paper_fleet.config import load_manifest
    from research.replication import append_to_shortlist

    original = path.read_text(encoding="utf-8")
    data = append_to_shortlist(path, additions, note="plan row R13: confirmed passers of research round 1 (holdout confirmed)")
    try:
        manifest = load_manifest(path)
    except Exception as exc:  # the fleet cannot read the amended file: put the original back, report, never break the fleet
        path.write_text(original, encoding="utf-8")
        return f"NOT applied — the paper fleet cannot load the amended shortlist ({type(exc).__name__}: {exc}); the file was restored; the additions are listed in the report"
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
    except (OSError, Round1Error, ValueError) as exc:
        print(f"no usable pre-registration ({exc}); run --preregister first", file=sys.stderr)
        return 2
    research = _research_lake(args)
    study = _study_lake(args, research)
    if args.freeze:
        print(json.dumps(cmd_freeze(research, study), indent=1))
        return 0
    cfg = Round1Config(hypotheses=tuple(args.hypotheses), regime_modes=tuple(args.regime_modes), timeframes=tuple(args.timeframes),
                       reproduction=not (args.quick or args.skip_reproduction), quick=bool(args.quick), lake_dir=str(study.root))
    full = full_study_requested(cfg)
    if args.evaluate_holdout and not full:
        print("--evaluate-holdout needs the full pre-registered study: every hypothesis, timeframe and mode, with the reproduction, without --quick", file=sys.stderr)
        return 2
    if args.evaluate_holdout and args.holdout_ledger == "-":
        print("--evaluate-holdout needs a holdout ledger", file=sys.stderr)
        return 2
    v1c_doc = json.loads(Path(args.v1c_results).read_text(encoding="utf-8"))
    stored = v1c_doc["results"]
    if args.refreeze or not all(any(study.candles_dir(m, b).exists() for b in ("1H", "4H")) for m in SPRINT_2C_INSTRUMENTS):
        cmd_freeze(research, study)
    all_strategies = list(REPRODUCTION_STRATEGIES) + list(dict.fromkeys(c for c, _ in cfg.new_candidates if c not in REPRODUCTION_STRATEGIES))
    protocol = protocol_check_round1(round1_args(cfg, all_strategies, evaluate_holdout=bool(args.evaluate_holdout)), v1c_doc["meta"])
    if not protocol["ok"] and not args.quick:
        print(f"STUDY STOPPED: the runner's defaults differ from the stored Sprint 2c protocol: {json.dumps(protocol['mismatches'], default=str)}", file=sys.stderr)
        return 2
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    t0 = time.monotonic()
    jobs = plan_jobs(cfg, evaluate_holdout=bool(args.evaluate_holdout))
    print(f"{len(jobs)} jobs on {args.workers} worker(s): " + ", ".join(f"{j['instrument']} {j['timeframe']} {j['kind']}" for j in jobs), flush=True)
    if args.workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(jobs))) as pool:
            outputs = list(pool.map(run_job, jobs))
    else:
        outputs = [run_job(j) for j in jobs]
    merged = merge_series(outputs)
    reproduction: List[Dict[str, Any]] = []
    if cfg.reproduction:
        for s in merged.values():
            repro_series = dict(s, results=[r for r in s.get("results") or [] if r["candidate"] in REPRODUCTION_STRATEGIES])
            checks = reproduction_check(repro_series, stored)
            reproduction.extend(checks)
            for c in checks:
                print(f"reproduction {c['candidate']} {c['instrument']} {c['timeframe']} [{c['regime']}]: ok={c['ok']} "
                      f"max abs diff {c.get('max_abs_difference', float('nan')):.1e} trades {c.get('n_trades')}/{c.get('n_trades_stored')}", flush=True)
        if reproduction and not all(c["ok"] for c in reproduction):
            bad = [c for c in reproduction if not c["ok"]]
            print(f"STUDY STOPPED: {len(bad)} of {len(reproduction)} Sprint 2c reproductions differ from the stored numbers: "
                  + "; ".join(f"{c['candidate']} {c['instrument']} {c['timeframe']} [{c['regime']}]" for c in bad), file=sys.stderr, flush=True)
            return 2
    skipped = [f"{k[0]} {k[1]}: {s['skipped']}" for k, s in merged.items() if s.get("skipped")]
    merged = {k: s for k, s in merged.items() if not s.get("skipped")}
    annotate_all(merged, stored)
    combined = build_combined_results(merged, cfg, evaluate_holdout=bool(args.evaluate_holdout), layout=study, log=lambda m: print(m, flush=True))
    for s in merged.values():
        for r in s["results"]:
            o = r["oos"]
            print(f"  {r['configuration']} ({r['role']}): CAGR {_pct(o.get('cagr'))} Sharpe {_f(o.get('sharpe'))} maxDD {_pct(o.get('max_drawdown'))} "
                  f"Calmar {_f(o.get('calmar'))} PF {_f(o.get('profit_factor'))} trades {o.get('n_trades')} pass={r['acceptance']['passed']} "
                  f"holdout={'opened' if r.get('holdout') else 'untouched'}", flush=True)
    for c in combined:
        o = c["oos"]
        print(f"  {c['configuration']} (combined): CAGR {_pct(o.get('cagr'))} Sharpe {_f(o.get('sharpe'))} maxDD {_pct(o.get('max_drawdown'))} "
              f"Calmar {_f(o.get('calmar'))} PF {_f(o.get('profit_factor'))} trades {o.get('n_trades')} pass={c['acceptance']['passed']} "
              f"holdout={'opened' if c.get('holdout') else 'untouched'}", flush=True)
    verdicts = hypothesis_verdicts(merged, combined, cfg, stored)
    overall = overall_summary(verdicts, merged, combined)
    openings = holdout_openings(merged, combined)
    ledger = load_ledger(args.holdout_ledger)
    second_look = guard_second_look(ledger, openings, evaluate_holdout=bool(args.evaluate_holdout))
    run: Dict[str, Any] = {
        "meta": {
            "study": STUDY_NAME, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "started_at": started,
            "elapsed_minutes": round((time.monotonic() - t0) / 60.0, 1), "config": cfg.to_dict(), "preregistration": PREREGISTRATION,
            "preregistration_file": args.preregistration, "preregistration_written_at": prereg.get("written_at"),
            "preregistration_sha256": preregistration_hash(cfg, prereg), "protocol_check": protocol, "v1c_results": args.v1c_results,
            "v1c_meta": {k: v1c_doc["meta"].get(k) for k in ("generated_at", "data_span", "data_span_short", "holdout_span", "policy_sizing", "regime", "no_trade_label",
                                                             "train_days", "test_days", "purge_days", "fee_rate", "slippage_rate", "bracket_variants")},
            "full_study": full, "evaluate_holdout": bool(args.evaluate_holdout), "quick": bool(args.quick), "reproduction": cfg.reproduction,
            "skipped_series": skipped, "data_end": DATA_END, "study_lake": str(study.root), "lake": lake_summary(study, list(SPRINT_2C_INSTRUMENTS)),
            "gates": dict(GATES), "workers": args.workers, "jobs": [{k: j[k] for k in ("instrument", "timeframe", "kind", "strategies")} for j in jobs],
            "report_path": args.report, "json_path": args.json, "holdout_ledger_path": args.holdout_ledger, "second_look_warning": second_look,
        },
        "reproduction": reproduction,
        "series": [_strip_series(s) for s in merged.values()],
        "combined": combined,
        "verdicts": verdicts,
        "overall": overall,
    }
    if openings and args.holdout_ledger != "-":
        ledger.append({"generated_at": run["meta"]["generated_at"], "started_at": started, "preregistration_sha256": run["meta"]["preregistration_sha256"],
                       "results_file": args.json, "openings": _rounded(openings)})
        write_round1_ledger(args.holdout_ledger, ledger)
        print(f"holdout ledger: {args.holdout_ledger} ({len(ledger)} entries)")
    run["meta"]["holdout_ledger"] = ledger
    source = {"study": STUDY_NAME, "report": args.report, "results": args.json, "generated_at": run["meta"]["generated_at"]}
    additions = shortlist_additions(merged, combined, source=source) if full and args.evaluate_holdout else []
    run["shortlist_additions"] = _rounded(additions)
    run["shortlist_note"] = None
    saved = json.loads(json.dumps(_rounded(run), default=_json_default))
    if args.json != "-":
        # The results file first: the paper fleet validates a source-tagged shortlist row against it.
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8")
        print(f"results: {args.json}")
    if additions and args.shortlist != "-":
        if args.json == "-":
            run["shortlist_note"] = "NOT applied — the paper fleet validates a shortlist row against the study's results file, and this run wrote none (--json -)"
        else:
            run["shortlist_note"] = _apply_shortlist_additions(Path(args.shortlist), saved["shortlist_additions"])
        saved["shortlist_note"] = run["shortlist_note"]
        print(f"shortlist: {run['shortlist_note']}")
        if args.json != "-":
            Path(args.json).write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8")
    if args.report != "-":
        Path(args.report).write_text(_render(saved), encoding="utf-8")
        print(f"report: {args.report}")
    labels = "; ".join(f"{k}: {v}" for k, v in overall["labels"].items())
    print(f"verdicts: {labels} - {overall['n_passed']} of {overall['n_judged']} configurations pass; holdout confirmed {overall['n_confirmed']}, "
          f"contradicted {overall['n_contradicted']}; done in {run['meta']['elapsed_minutes']} min")
    return 0


def _pct(v: Any) -> str:
    return "-" if v is None else f"{float(v) * 100:+.1f}%"


def _f(v: Any) -> str:
    return "-" if v is None else f"{float(v):.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
