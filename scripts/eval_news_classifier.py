"""Phase 6b news-classifier eval (PHASE6B_DESIGN section 15, master plan 5.2) — LOG-ONLY tooling.

Runs the labeled eval set (``tests/fixtures/news_eval``, synthetic headlines)
through the same path the news shadow uses — sanitizer, Haiku triage, Opus
classification, corroboration, decay — and scores schema validity, prohibited
actions, single-source effects and per-kind / per-category accuracy.

Three modes:

- live (default): calls the Anthropic API, and ONLY when ``ANTHROPIC_API_KEY``
  is set. Without it the script prints ``not run: no API key`` and exits 0. Every
  model reply is recorded next to the results so the run can be re-scored for
  free later.
- ``--replay FILE``: re-scores a recorded run offline with the models and
  settings it was recorded with (no key, no network).
- ``--self-test``: runs four scripted offline "models" (the reference answers,
  one that never acts, one that blocks everything, one that returns broken
  output) to prove the harness and the labels work. No key, no network.

``--resume DIR`` continues an interrupted live or replay run exactly as it was
started (its cases, repetitions, models and effort levels), redoing only the
cases that have no scored result yet; a conflicting flag is refused.

Exit codes: 0 = all gates passed (or not run: no API key, or the self-test
checks held); 1 = a gate failed or the run was inconclusive; 2 = setup error.

The script reads no exchange or account state, places no order, and nothing in
the trading runtime reads its output. Outputs go to ``artifacts/news_eval/``
(git-ignored). The API key is passed to the SDK only and never printed or stored.

Examples::

    python scripts/eval_news_classifier.py --self-test
    python scripts/eval_news_classifier.py                        # live; needs ANTHROPIC_API_KEY
    python scripts/eval_news_classifier.py --kinds satire stale_repost --reps 3
    python scripts/eval_news_classifier.py --replay artifacts/news_eval/<run>/recording.jsonl
    python scripts/eval_news_classifier.py --resume artifacts/news_eval/<run>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.news import evaluation as ev  # noqa: E402
from app.news.classifier import API_KEY_ENV, CLASSIFIER_MODEL, EFFORT_LEVELS, TRIAGE_MODEL, NewsClassifier  # noqa: E402

DEFAULT_OUT_ROOT = Path("artifacts") / "news_eval"
NOT_RUN_MESSAGE = "not run: no API key"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score the Phase 6b news classifier on the labeled eval set (log-only).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, default=None, help="Re-score a recorded run (recording.jsonl); no key, no network.")
    mode.add_argument("--self-test", action="store_true", help="Run the scripted offline models to check the harness and labels.")
    p.add_argument("--fixtures", type=Path, default=ev.DEFAULT_FIXTURE_DIR, help="Eval set directory (default: tests/fixtures/news_eval).")
    p.add_argument("--kinds", nargs="+", default=None, choices=ev.KINDS, metavar="KIND", help=f"Only these case kinds: {', '.join(ev.KINDS)}.")
    p.add_argument("--cases", nargs="+", default=None, help="Only these case ids.")
    p.add_argument("--reps", type=int, default=None, help="Repetitions per case (default 1; a replay defaults to the recorded run's).")
    p.add_argument("--workers", type=int, default=4, help="Cases run in parallel in live mode (default 4).")
    p.add_argument("--no-triage", action="store_true", help="Skip the Haiku stage: every story goes straight to the classifier.")
    p.add_argument("--out", type=Path, default=None, help="Output directory (default: artifacts/news_eval/<UTC time>-<mode>).")
    p.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Continue an interrupted run in this directory with its own cases, repetitions and models (skips scored cases).",
    )
    # Model settings default to None so a resumed run can tell "not given" from "given".
    p.add_argument("--triage-model", default=None, help=f"Default {TRIAGE_MODEL} (the production setting).")
    p.add_argument("--classify-model", default=None, help=f"Default {CLASSIFIER_MODEL} (the production setting).")
    p.add_argument(
        "--triage-effort", default=None, choices=EFFORT_LEVELS, help=f"Default {ev.PRODUCTION_TRIAGE_EFFORT} (the production setting)."
    )
    p.add_argument(
        "--classify-effort", default=None, choices=EFFORT_LEVELS, help=f"Default {ev.PRODUCTION_CLASSIFY_EFFORT} (the production setting)."
    )
    p.add_argument("--json", action="store_true", help="Print the summary as JSON.")
    p.add_argument("--quiet", action="store_true", help="No per-case progress lines.")
    args = p.parse_args(argv)
    if (args.reps is not None and args.reps < 1) or args.workers < 1:
        p.error("--reps and --workers must be at least 1")
    if args.resume is not None and args.self_test:
        p.error("--resume does not apply to --self-test")
    return args


class RunFiles:
    """Append-only run outputs: results, errors and recorded replies, one JSON line each."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, name: str) -> Path:
        return self.root / name

    def append(self, name: str, record: Mapping[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
        with self._lock, self.path(name).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read(self, name: str) -> List[Dict[str, Any]]:
        path = self.path(name)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def write_text(self, name: str, text: str) -> None:
        self.path(name).write_text(text, encoding="utf-8")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _out_dir(args: argparse.Namespace, mode: str) -> Path:
    if args.resume is not None:
        return args.resume
    if args.out is not None:
        return args.out
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUT_ROOT / f"{stamp}-{mode}"


_SETTINGS = (
    ("triage_model", TRIAGE_MODEL),
    ("classify_model", CLASSIFIER_MODEL),
    ("triage_effort", ev.PRODUCTION_TRIAGE_EFFORT),
    ("classify_effort", ev.PRODUCTION_CLASSIFY_EFFORT),
)


def load_resumed_meta(args: argparse.Namespace, mode: str) -> Dict[str, Any]:
    """The settings of the run in ``--resume DIR``; a resume continues exactly that run."""
    meta_path = Path(args.resume) / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"nothing to resume: {meta_path} does not exist")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("mode") != mode:
        raise ValueError(f"{args.resume} holds a {meta.get('mode')} run, not a {mode} run")
    if meta.get("fixture_digest") != ev.fixture_digest(args.fixtures):
        raise ValueError("the eval set changed since this run started; start a new run")
    return meta


def resolve_settings(args: argparse.Namespace, recorded: Optional[Mapping[str, Any]], source: str) -> None:
    """Fill models, efforts and triage in place: from ``recorded`` (the resumed run's
    meta, or the replayed recording's header) where it has them — a conflicting flag
    is an error — else from the production defaults."""
    recorded = recorded or {}
    for name, default in _SETTINGS:
        given, known = getattr(args, name), recorded.get(name)
        if given is not None and known is not None and given != known:
            raise ValueError(f"--{name.replace('_', '-')} {given} differs from the {source}'s {known}")
        setattr(args, name, given or known or default)
    if recorded.get("use_triage") is not None:
        if args.no_triage and recorded["use_triage"]:
            raise ValueError(f"--no-triage differs from the {source}, which used triage")
        args.no_triage = not recorded["use_triage"]


def _classifier_kwargs(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "triage_model": args.triage_model,
        "classify_model": args.classify_model,
        "triage_effort": args.triage_effort,
        "classify_effort": args.classify_effort,
    }


def _print_summary(summary: Mapping[str, Any], out: Optional[Path], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        return
    overall = summary["overall"]["action"]
    print(f"Result: {summary['verdict']}")
    for g in summary["gates"]:
        state = "n/a" if g["pass"] is None else ("PASS" if g["pass"] else "FAIL")
        print(f"  {state:4s}  {g['label']}: {g['detail']} (target {g['target']})")
    rate = "n/a" if overall["rate"] is None else f"{100 * overall['rate']:.1f} %"
    print(f"  Final action right: {rate} ({overall['ok']} of {overall['n']}); errors not scored: {summary['errors']['count']}")
    if summary.get("estimated_usd") is not None:
        print(f"  Estimated cost: ${summary['estimated_usd']:.2f} (list prices)")
    if out is not None:
        print(f"  Report: {out / 'report.md'}")


def run_scored(
    args: argparse.Namespace,
    cases: Sequence[ev.EvalCase],
    classifier_for: ev.ClassifierFor,
    *,
    mode: str,
    files: RunFiles,
    workers: int,
    extra_meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run (or continue) one scored run into ``files``; returns the summary."""
    done = {(r["case_id"], r["rep"]) for r in files.read("results.jsonl")}
    meta_path = files.path("meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = ev.run_meta(
            mode=mode,
            root=args.fixtures,
            use_triage=not args.no_triage,
            triage_model=args.triage_model,
            classify_model=args.classify_model,
            triage_effort=args.triage_effort,
            classify_effort=args.classify_effort,
            extra={
                "started_at": _now(),
                "reps": args.reps,
                "case_count": len(cases),
                "case_ids": sorted(c.id for c in cases),
                **dict(extra_meta or {}),
            },
        )
        files.write_text("meta.json", json.dumps(meta, indent=2, sort_keys=True))
    total = len(cases) * args.reps - len(done)
    progress = {"n": 0}

    def on_done(row: Optional[Dict[str, Any]], err: Optional[Dict[str, Any]]) -> None:
        progress["n"] += 1
        if row is not None:
            files.append("results.jsonl", row)
        if err is not None:
            files.append("errors.jsonl", err)
        if not args.quiet:
            if row is not None:
                state = "ok" if row["grade"]["action_ok"] else f"WRONG ({row['grade']['error_type']})"
                print(f"[{progress['n']}/{total}] {row['case_id']} rep {row['rep']}: {row['final_action']} {state}", flush=True)
            else:
                print(f"[{progress['n']}/{total}] {err['case_id']} rep {err['rep']}: error {err['failure']}", flush=True)

    try:
        ev.run_cases(
            cases,
            classifier_for,
            reps=args.reps,
            workers=workers,
            use_triage=not args.no_triage,
            skip=frozenset(done),
            on_done=on_done,
        )
    except KeyboardInterrupt:
        print(f"interrupted: finished cases are saved; continue with --resume {files.root}", file=sys.stderr)
        raise
    meta["finished_at"] = _now()
    summary = ev.summarize(files.read("results.jsonl"), files.read("errors.jsonl"), meta)
    files.write_text("summary.json", json.dumps(summary, indent=2, sort_keys=True, default=str))
    files.write_text("report.md", ev.render_report(summary))
    return summary


def run_self_test(args: argparse.Namespace, cases: Sequence[ev.EvalCase]) -> int:
    results = ev.self_test(cases, root=args.fixtures, use_triage=not args.no_triage)
    checks = ev.self_test_checks(results, cases)
    if args.json:
        print(json.dumps({"summaries": results, "checks": checks}, indent=2, sort_keys=True, default=str))
    else:
        print(f"Self-test on {len(cases)} cases (scripted offline models; no key, no network)")
        print(f"{'model':18s} {'result':12s} {'right':>7s} {'missed':>6s} {'false':>6s} {'1-src':>6s} {'prohib':>6s} {'valid':>7s}")
        for name, s in results.items():
            rate = s["overall"]["action"]["rate"]
            validity = s["calls"]["classify"]["schema_validity"]
            print(
                f"{name:18s} {s['verdict']:12s} {('n/a' if rate is None else f'{100 * rate:.1f}%'):>7s} "
                f"{s['overall']['missed_effects']:>6d} {s['overall']['false_effects']:>6d} "
                f"{s['single_source']['effects']:>6d} {s['prohibited_actions']:>6d} "
                f"{('n/a' if validity is None else f'{100 * validity:.0f}%'):>7s}"
            )
        block = results["always_block"]
        print(
            f"Cases where only the model's judgment prevents a single-source effect: {block['single_source']['effects']} "
            f"of {block['single_source']['stories']} single-source stories."
        )
        for label, ok in checks:
            print(f"  {'OK ' if ok else 'BAD'} {label}")
    return 0 if all(ok for _, ok in checks) else 1


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    live_client_factory: Optional[Callable[[str], Any]] = None,
) -> int:
    args = parse_args(argv)
    env = os.environ if env is None else env
    live = args.replay is None and not args.self_test
    key = (env.get(API_KEY_ENV) or "").strip()
    if live and not key:  # the model is called only when a key is present
        print(NOT_RUN_MESSAGE)
        return 0
    recording = None
    if args.replay is not None:
        try:
            recording = ev.Recording.load(args.replay)
        except (OSError, ValueError) as exc:
            print(f"error: cannot read the recording: {exc}", file=sys.stderr)
            return 2
    try:
        if args.resume is not None:
            # A resume continues exactly the interrupted run: its cases, repetitions and models.
            resumed = load_resumed_meta(args, "replay" if recording is not None else "live")
            resolve_settings(args, resumed, "resumed run")
            args.reps = args.reps or resumed.get("reps")
            if args.cases is None and args.kinds is None and resumed.get("case_ids"):
                args.cases = list(resumed["case_ids"])
        else:
            resolve_settings(args, recording.settings if recording is not None else None, "recording")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        cases = ev.load_cases(args.fixtures, kinds=args.kinds, ids=args.cases)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load the eval set: {exc}", file=sys.stderr)
        return 2
    if not cases:
        print("error: no cases selected", file=sys.stderr)
        return 2

    if args.self_test:
        args.reps = args.reps or 1
        return run_self_test(args, cases)

    if recording is not None:
        args.reps = args.reps or recording.reps
        if args.cases is None and args.kinds is None:
            cases = [c for c in cases if c.id in recording.case_ids]
        if not cases:
            print("error: the recording covers none of the selected cases", file=sys.stderr)
            return 2
        files = RunFiles(_out_dir(args, "replay"))
        summary = run_scored(
            args,
            cases,
            ev.replay_classifier_for(recording, **_classifier_kwargs(args)),
            mode="replay",
            files=files,
            workers=1,
            extra_meta={"recording": str(args.replay)},
        )
        if recording.stale_prompts:
            print(f"warning: {recording.stale_prompts} recorded replies were made with a different prompt version", file=sys.stderr)
        _print_summary(summary, files.root, as_json=args.json)
        return 0 if summary["verdict"] == "PASS" else 1

    # Live mode (a key is present: checked above).
    args.reps = args.reps or 1
    try:
        client = (live_client_factory or ev.live_client)(key)
    except ImportError:
        print("not run: the anthropic SDK is not installed", file=sys.stderr)
        return 2
    except Exception as exc:  # never echo the key or the SDK's message
        print(f"not run: could not create the API client ({type(exc).__name__})", file=sys.stderr)
        return 2
    files = RunFiles(_out_dir(args, "live"))
    kwargs = _classifier_kwargs(args)
    header = ev.run_header((c.id for c in cases), args.reps, started_at=_now(), use_triage=not args.no_triage, **kwargs)
    files.append("recording.jsonl", header)

    def classifier_for(case: ev.EvalCase, rep: int) -> NewsClassifier:
        recorder = ev.RecordingClient(client, case, rep, lambda record: files.append("recording.jsonl", record))
        return NewsClassifier(recorder, **kwargs)

    if not args.quiet:
        print(f"Live eval: {len(cases)} cases x {args.reps} rep(s) -> {files.root}", flush=True)
    summary = run_scored(args, cases, classifier_for, mode="live", files=files, workers=args.workers)
    _print_summary(summary, files.root, as_json=args.json)
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
