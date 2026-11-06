"""Collect the PUBLIC OKX ``liquidation-orders`` feed (SWAP) into JSON lines.

Read-only public WebSocket; BTC-USDT-SWAP / ETH-USDT-SWAP records only; the
process stops after ``--duration`` seconds. Run it under cron/systemd for a
continuous feed. No credentials, no account or order coupling.

Example::

    python scripts/collect_liquidations.py --duration 3600
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.datalake.derivatives import SWAP_INSTRUMENTS  # noqa: E402
from app.datalake.layout import LakeLayout  # noqa: E402
from app.datalake.liquidations import PUBLIC_WS_URL, JsonlSink, run_collector  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Public OKX liquidation-orders collector -> JSON lines.")
    p.add_argument("--duration", type=float, default=3600.0, help="Seconds to run (default 3600).")
    p.add_argument("--instruments", nargs="+", default=list(SWAP_INSTRUMENTS), choices=list(SWAP_INSTRUMENTS))
    p.add_argument("--url", default=PUBLIC_WS_URL, help="Public WS URL (validated; default has no port).")
    p.add_argument("--lake-dir", default=None)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(get_settings().log_level)
    layout = LakeLayout(Path(args.lake_dir)) if args.lake_dir else LakeLayout.from_env()
    sink = JsonlSink(layout)
    stats = asyncio.run(
        run_collector(sink, duration_seconds=args.duration, url=args.url, instruments=args.instruments)
    )
    print(
        f"liquidations: messages={stats.messages} records={stats.records} connects={stats.connects} "
        f"reconnects={stats.reconnects} errors={stats.errors} last_error={stats.last_error!r}"
    )
    return 0 if stats.connects > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
