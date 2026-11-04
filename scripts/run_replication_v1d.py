"""Replication study runner: the Sprint 2c rule families on OKX spot markets they were never tuned on (plan row R12, SIMULATION ONLY).

Four steps, in this order, all public data and GET only:

1. ``--preregister``: one public ticker snapshot fixes the markets (the pre-registered rule of
   ``research/markets.py``) and writes ``docs/research/replication_v1d_preregistration.json``;
   it refuses to run twice.
2. ``--collect``: the chosen markets' OKX 1H and 4H spot candles and Binance public funding into
   the research lake (resumable; ``research/replication_data.py``).
3. ``--freeze``: a study lake with every candle series cut at Sprint 2c's data end, so the
   untouched 12 months are the same calendar window as in Sprint 2c (done automatically by
   step 4 when the study lake does not exist yet).
4. The study: Sprint 2c's own runner (``scripts/run_research_v1c.py``, loaded as a module) first
   reproduces BTC-USDT and ETH-USDT against the stored Sprint 2c numbers — the study stops on
   any difference — then runs every chosen market; ``--evaluate-holdout`` (full pre-registered
   study only) opens each new market's 12 months once for the configurations that pass
   walk-forward there and records every opening in an append-only ledger. Writes
   ``docs/research/REPLICATION_V1D_REPORT.md`` and a results JSON; confirmed passers are
   appended to the paper fleet's shortlist with a ``source`` tag.

Example::

    python scripts/run_replication_v1d.py --preregister
    python scripts/run_replication_v1d.py --collect                      # ~30 min, resumable
    python scripts/run_replication_v1d.py --evaluate-holdout --workers 8
    python scripts/run_replication_v1d.py --quick --markets XRP-USDT --timeframes 4H --families S1 --report - --json -   # smoke run
    python scripts/run_replication_v1d.py --render-from-json docs/research/replication_v1d_results.json

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
from app.datalake.okx_public_rest import OKXPublicRest  # noqa: E402
from research.markets import SPRINT_2C_INSTRUMENTS  # noqa: E402
from research.replication import (  # noqa: E402
    DATA_END,
    PREREGISTRATION,
    PREREGISTRATION_PATH,
    STUDY_FAMILIES,
    STUDY_LAKE_DIRNAME,
    STUDY_MODES,
    STUDY_STRATEGIES,
    STUDY_TIMEFRAMES,
    V1C_RESULTS,
    ReplicationConfig,
    ReplicationError,
    beats_hold,
    btc_passers_2c,
    configuration_replication,
    family_verdicts,
    freeze_lake,
    full_study_requested,
    guard_second_look,
    holdout_openings,
    load_ledger,
    load_preregistration,
    overall_verdict,
    preregister,
    preregistration_hash,
    protocol_check,
    reproduction_check,
    run_market_job,
    shortlist_additions,
    append_to_shortlist,
    v1c_args,
    write_ledger,
)
from research.replication_data import COLLECTED_BARS, collect_research_funding, collect_spot_candles, lake_summary  # noqa: E402
from research.report_v1c import GATES  # noqa: E402

DEFAULT_REPORT = "docs/research/REPLICATION_V1D_REPORT.md"
DEFAULT_JSON = "docs/research/replication_v1d_results.json"
DEFAULT_LEDGER = "docs/research/replication_v1d_holdout_ledger.json"
DEFAULT_SHORTLIST = "docs/research/paper_fleet_shortlist_v1c.json"


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Replication of the Sprint 2c rule families on other OKX spot markets (simulation only).")
    p.add_argument("--preregister", action="store_true", help="Take the public ticker snapshot, fix the markets, write the pre-registration file, exit.")
    p.add_argument("--force-preregister", action="store_true", help="Overwrite an existing pre-registration (only before any result exists).")
    p.add_argument("--collect", action="store_true", help="Collect the chosen markets' public candles and funding into the research lake, then exit.")
    p.add_argument("--max-pages", type=int, default=None, help="Collect: page budget per series for this run (resumable).")
    p.add_argument("--freeze", action="store_true", help="Build the study lake (candles cut at Sprint 2c's data end), then exit.")
    p.add_argument("--refreeze", action="store_true", help="Rebuild the study lake before the study.")
    p.add_argument("--markets", nargs="+", default=None, help="Subset of the pre-registered markets (smoke runs; never opens the holdout).")
    p.add_argument("--families", nargs="+", default=list(STUDY_FAMILIES), choices=list(STUDY_FAMILIES))
    p.add_argument("--timeframes", nargs="+", default=list(STUDY_TIMEFRAMES), choices=list(STUDY_TIMEFRAMES))
    p.add_argument("--regime-modes", nargs="+", default=list(STUDY_MODES), choices=list(STUDY_MODES))
    p.add_argument("--no-control", action="store_true", help="Skip the hold + policy control (smoke runs).")
    p.add_argument("--evaluate-holdout", action="store_true", help="Open each new market's 12 months once for walk-forward passers (full study only).")
    p.add_argument("--quick", action="store_true", help="Cut grids, no reproduction check: a smoke run, never a result.")
    p.add_argument("--skip-reproduction", action="store_true", help="Skip the BTC/ETH reproduction (smoke runs only; refused with --evaluate-holdout).")
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
    from research.report_replication import render_report  # imported late: the study can run before a report is rendered

    return render_report(run)


def cmd_preregister(args: argparse.Namespace) -> int:
    path = Path(args.preregistration)
    try:
        payload = preregister(OKXPublicRest(), path, force=args.force_preregister)
    except ReplicationError as exc:
        print(f"not written: {exc}", file=sys.stderr)
        return 2
    print(f"pre-registration written: {path} (snapshot {payload['snapshot_at']})")
    for p in payload["picks"]:
        mark = "CHOSEN " if p["chosen"] else "       "
        print(f"  {mark}{p['instrument']:12s} {p['quote_volume_24h'] / 1e6:9.1f} M USDT  history before cutoff: {p['history_before_cutoff'] or '-':17s} {p['reason']}")
    print(f"markets: {', '.join(payload['chosen'])}")
    return 0


def cmd_collect(args: argparse.Namespace, markets: List[str], research: LakeLayout) -> int:
    rest = OKXPublicRest()
    failures = 0
    for inst in markets:
        for bar in COLLECTED_BARS:
            rep = collect_spot_candles(research, inst, bar, rest=rest, max_pages=args.max_pages)
            print(rep.summary(), flush=True)
            if not (rep.walk.complete or rep.walk.exhausted or rep.walk.reason == "max_pages"):
                failures += 1
        frep = collect_research_funding(research, inst, max_pages=args.max_pages)
        print(frep.summary(), flush=True)
        if frep.errors:
            print(f"  funding errors: {frep.errors}", file=sys.stderr, flush=True)
            failures += 1
    return 0 if failures == 0 else 1


def cmd_freeze(research: LakeLayout, study: LakeLayout, markets: List[str]) -> Dict[str, Any]:
    print(f"freezing the study lake at {study.root} (bar close <= {DATA_END}) ...", flush=True)
    return freeze_lake(research, study, list(SPRINT_2C_INSTRUMENTS) + list(markets), end=DATA_END, log=lambda m: print(m, flush=True))


def cmd_apply_shortlist(args: argparse.Namespace) -> int:
    """Apply recorded additions later (after a fleet-side change made them loadable) without re-running the study."""
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
    except (OSError, ReplicationError, ValueError) as exc:
        print(f"no usable pre-registration ({exc}); run --preregister first", file=sys.stderr)
        return 2
    chosen: List[str] = list(prereg["chosen"])
    markets = list(args.markets) if args.markets else chosen
    unknown = [m for m in markets if m not in chosen]
    if unknown:
        print(f"not pre-registered markets: {unknown} (chosen: {chosen})", file=sys.stderr)
        return 2
    research = _research_lake(args)
    if args.collect:
        return cmd_collect(args, markets, research)
    study = _study_lake(args, research)
    if args.freeze:
        rep = cmd_freeze(research, study, markets)
        print(json.dumps(rep, indent=1))
        return 0

    strategies = tuple(s for s in STUDY_STRATEGIES if (s in args.families) or (s == "hold" and not args.no_control))
    cfg = ReplicationConfig(strategies=strategies, regime_modes=tuple(args.regime_modes), timeframes=tuple(args.timeframes), quick=bool(args.quick),
                            lake_dir=str(study.root))
    full = full_study_requested(cfg, markets, chosen)
    if args.evaluate_holdout and not full:
        print("--evaluate-holdout needs the full pre-registered study: every chosen market, family, timeframe and mode, the control, without --quick",
              file=sys.stderr)
        return 2
    if args.evaluate_holdout and (args.holdout_ledger == "-" or args.skip_reproduction):
        print("--evaluate-holdout needs a holdout ledger and the BTC/ETH reproduction", file=sys.stderr)
        return 2
    v1c_doc = json.loads(Path(args.v1c_results).read_text(encoding="utf-8"))
    stored = v1c_doc["results"]
    if args.refreeze or not any(study.candles_dir(m, "1H").exists() for m in markets):
        cmd_freeze(research, study, markets)
    run_args = v1c_args(cfg, evaluate_holdout=bool(args.evaluate_holdout))
    repro_args = v1c_args(cfg, evaluate_holdout=False)
    protocol = protocol_check(run_args, v1c_doc["meta"])
    if not protocol["ok"] and not args.quick:
        print(f"STUDY STOPPED: the runner's defaults differ from the stored Sprint 2c protocol: {json.dumps(protocol['mismatches'], default=str)}",
              file=sys.stderr)
        return 2
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    t0 = time.monotonic()
    repro_jobs = [] if (args.quick or args.skip_reproduction) else [
        {"cfg": cfg.to_dict(), "args": repro_args, "instrument": i, "timeframe": t} for i in SPRINT_2C_INSTRUMENTS for t in cfg.timeframes]
    market_jobs = [{"cfg": cfg.to_dict(), "args": run_args, "instrument": m, "timeframe": t} for m in markets for t in cfg.timeframes]
    jobs = repro_jobs + market_jobs
    if args.workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(jobs))) as pool:
            outputs = list(pool.map(run_market_job, jobs))
    else:
        outputs = [run_market_job(j) for j in jobs]
    repro_series = outputs[: len(repro_jobs)]
    series = outputs[len(repro_jobs):]
    reproduction: List[Dict[str, Any]] = []
    for s in repro_series:
        checks = reproduction_check(s, stored)
        reproduction.extend(checks)
        for c in checks:
            print(f"reproduction {c['candidate']} {c['instrument']} {c['timeframe']} [{c['regime']}]: ok={c['ok']} "
                  f"max abs diff {c.get('max_abs_difference', float('nan')):.1e} trades {c.get('n_trades')}/{c.get('n_trades_stored')}", flush=True)
    if reproduction and not all(c["ok"] for c in reproduction):
        bad = [c for c in reproduction if not c["ok"]]
        print(f"STUDY STOPPED: {len(bad)} of {len(reproduction)} Sprint 2c reproductions differ from the stored numbers: "
              + "; ".join(f"{c['candidate']} {c['instrument']} {c['timeframe']} [{c['regime']}]" for c in bad), file=sys.stderr, flush=True)
        return 2
    skipped = [f"{s['instrument']} {s['timeframe']}: {s['skipped']}" for s in series if s.get("skipped")]
    series = [s for s in series if not s.get("skipped")]
    for s in series:
        for r in s["results"]:
            o = r["oos"]
            print(f"  {r['instrument']} {r['timeframe']} {r['display_candidate']} [{r['regime']['mode']}]: CAGR {_pct(o.get('cagr'))} "
                  f"Sharpe {_f(o.get('sharpe'))} maxDD {_pct(o.get('max_drawdown'))} Calmar {_f(o.get('calmar'))} PF {_f(o.get('profit_factor'))} "
                  f"trades {o.get('n_trades')} pass={r['acceptance']['passed']} holdout={'opened' if r.get('holdout') else 'untouched'}", flush=True)
    ledger = load_ledger(args.holdout_ledger)
    second_look = guard_second_look(ledger, series, evaluate_holdout=bool(args.evaluate_holdout))
    passers_2c = btc_passers_2c(stored, cfg)
    families = family_verdicts(series, stored, markets, cfg)
    run: Dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "started_at": started,
            "elapsed_minutes": round((time.monotonic() - t0) / 60.0, 1), "config": cfg.to_dict(), "preregistration": PREREGISTRATION,
            "preregistration_file": args.preregistration, "snapshot": {k: v for k, v in prereg.items() if k != "preregistration"},
            "preregistration_sha256": preregistration_hash(cfg, prereg), "protocol_check": protocol, "v1c_results": args.v1c_results,
            "v1c_meta": {k: v1c_doc["meta"].get(k) for k in ("generated_at", "data_span", "holdout_span", "policy_sizing", "regime", "no_trade_label",
                                                             "train_days", "test_days", "purge_days", "fee_rate", "slippage_rate", "bracket_variants")},
            "markets": markets, "chosen": chosen, "full_study": full, "evaluate_holdout": bool(args.evaluate_holdout), "quick": bool(args.quick),
            "skipped_series": skipped, "data_end": DATA_END, "study_lake": str(study.root), "lake": lake_summary(study, list(SPRINT_2C_INSTRUMENTS) + markets),
            "gates": dict(GATES), "workers": args.workers,
            "report_path": args.report, "json_path": args.json, "holdout_ledger_path": args.holdout_ledger,
            "second_look_warning": second_look,
        },
        "reproduction": reproduction,
        "series": series,
        "stored_2c": [r for r in stored if r["candidate"] in cfg.strategies and r["timeframe"] in cfg.timeframes
                      and (r.get("regime") or {}).get("mode") in cfg.regime_modes],
        "btc_passers_2c": passers_2c,
        "configuration_replication": configuration_replication(series, passers_2c, markets),
        "families": families,
        "overall": overall_verdict(families, series, markets),
        "beats_hold": beats_hold(series),
    }
    openings = holdout_openings(series)
    if openings and args.holdout_ledger != "-":
        ledger.append({"generated_at": run["meta"]["generated_at"], "started_at": started, "preregistration_sha256": run["meta"]["preregistration_sha256"],
                       "results_file": args.json, "openings": _rounded(openings)})
        write_ledger(args.holdout_ledger, ledger)
        print(f"holdout ledger: {args.holdout_ledger} ({len(ledger)} entries)")
    run["meta"]["holdout_ledger"] = ledger
    source = {"study": "R12 replication", "report": args.report, "results": args.json, "generated_at": run["meta"]["generated_at"]}
    additions = shortlist_additions(series, source=source) if full and args.evaluate_holdout else []
    run["shortlist_additions"] = _rounded(additions)
    run["shortlist_note"] = None
    if additions and args.shortlist != "-":
        run["shortlist_note"] = _apply_shortlist_additions(Path(args.shortlist), additions)
        print(f"shortlist: {run['shortlist_note']}")
    saved = json.loads(json.dumps(_rounded(run), default=_json_default))
    if args.json != "-":
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8")
        print(f"results: {args.json}")
    if args.report != "-":
        Path(args.report).write_text(_render(saved), encoding="utf-8")
        print(f"report: {args.report}")
    ov = run["overall"]
    print(f"verdict: {ov['label']} - {ov['n_passed']} of {ov['n_judged']} configurations pass on the new markets; "
          f"holdout confirmed {ov['n_confirmed']}, contradicted {ov['n_contradicted']}; done in {run['meta']['elapsed_minutes']} min")
    return 0


def _apply_shortlist_additions(path: Path, additions: List[Dict[str, Any]]) -> str:
    """Append the confirmed passers, then prove the paper fleet can still load its manifest; otherwise restore the file untouched.

    The fleet refuses to start on a shortlist it cannot reconcile with its results files, so an amendment it cannot read must never be
    left in place (a running fleet would stop at its next restart)."""
    from research.paper_fleet.config import load_manifest

    original = path.read_text(encoding="utf-8")
    data = append_to_shortlist(path, additions, note="plan row R12: confirmed passers of the replication study (holdout confirmed)")
    try:
        manifest = load_manifest(path)
    except Exception as exc:  # the fleet cannot read the amended file: put the original back, report, never break the fleet
        path.write_text(original, encoding="utf-8")
        return f"NOT applied — the paper fleet cannot load the amended shortlist ({type(exc).__name__}: {exc}); the file was restored; the additions are listed in the report"
    return f"{path.as_posix()} now lists {len(data.get('configurations', []))} configurations ({len(manifest.accounts)} fleet accounts)"


def _pct(v: Any) -> str:
    return "-" if v is None else f"{float(v) * 100:+.1f}%"


def _f(v: Any) -> str:
    return "-" if v is None else f"{float(v):.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
