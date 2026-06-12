"""Historical ma_crossover clearance-rate study (ANALYSIS ONLY, offline).

Tracked Phase 5 open item #4: how often does the current, UNMODIFIED
``ma_crossover`` configuration produce LONG signals that clear the demo
confidence floor (``DEMO_MIN_CONFIDENCE``, 0.60) over the stored historical
candles? Replays the database history through the strategy exactly as the
runtime would see it. No network calls, no orders, NO retuning — any
parameter or floor change remains a scope change requiring explicit owner
approval.

    python scripts/analyze_signal_clearance.py [--instrument BTC-USDT]
        [--timeframe 1m] [--strategy ma_crossover] [--out report.md]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.database import get_session_factory, init_db  # noqa: E402
from app.strategy.base import SignalAction  # noqa: E402
from app.strategy.registry import build_strategy  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline ma_crossover clearance-rate study.")
    p.add_argument("--instrument", default=None, help="Default: first demo instrument.")
    p.add_argument("--timeframe", default=None, help="Default: the demo timeframe.")
    p.add_argument("--strategy", default=None, help="Default: the demo strategy.")
    p.add_argument("--out", default=None, help="Optional output file for the report.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    instrument = args.instrument or settings.demo_instruments[0]
    timeframe = args.timeframe or settings.demo_timeframe
    strategy_name = args.strategy or settings.demo_strategy
    floor = settings.demo_min_confidence

    init_db()
    from app.backtest.runner import load_market_candles

    session = get_session_factory()()
    try:
        candles = load_market_candles(session, instrument, timeframe)
    finally:
        session.close()
    if not candles:
        print(f"No stored candles for {instrument} {timeframe}; run the ingest first.")
        return 1

    strategy = build_strategy(strategy_name)
    signals = strategy.generate_signals(candles)

    longs = [s for s in signals if s.action == SignalAction.LONG]
    cleared = [s for s in longs if s.confidence >= floor]
    actions = Counter(s.action.value for s in signals)

    # Confidence histogram for LONG signals (0.05-wide buckets).
    hist: Counter = Counter()
    for s in longs:
        bucket = min(int(s.confidence / 0.05) * 5, 100)
        hist[bucket] += 1

    # Per-UTC-day clearance.
    per_day: dict = defaultdict(lambda: [0, 0])  # day -> [longs, cleared]
    for s in longs:
        day = s.timestamp.date().isoformat()
        per_day[day][0] += 1
        if s.confidence >= floor:
            per_day[day][1] += 1

    rate = (100.0 * len(cleared) / len(longs)) if longs else 0.0
    max_conf = max((s.confidence for s in longs), default=0.0)

    lines = [
        f"# ma_crossover clearance-rate study — {instrument} {timeframe}",
        "",
        "ANALYSIS ONLY. No live calls were made, no orders exist, and no",
        "parameters were changed. Retuning requires explicit owner approval.",
        "",
        f"- strategy: {strategy.name} (registry name {strategy_name!r}, unmodified defaults)",
        f"- confidence floor: {floor:.2f} (DEMO_MIN_CONFIDENCE)",
        f"- candles analyzed: {len(candles)} "
        f"({candles[0].timestamp.isoformat()} .. {candles[-1].timestamp.isoformat()})",
        f"- signal actions: " + ", ".join(f"{k}={v}" for k, v in sorted(actions.items())),
        f"- LONG signals: {len(longs)}",
        f"- LONG signals clearing the floor: {len(cleared)}",
        f"- clearance rate: {rate:.2f}%",
        f"- highest LONG confidence observed: {max_conf:.4f}",
        "",
        "## LONG confidence histogram (bucket lower bound, %)",
    ]
    for bucket in sorted(hist):
        lines.append(f"- {bucket / 100:.2f}+ : {hist[bucket]}")
    if not hist:
        lines.append("- (no LONG signals)")
    lines += ["", "## Per-UTC-day (longs / cleared)"]
    for day in sorted(per_day):
        total, ok = per_day[day]
        lines.append(f"- {day}: {total} / {ok}")
    report = "\n".join(lines)
    print(report)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report + "\n", encoding="utf-8")
        print(f"\n[written: {args.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
