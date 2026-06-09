"""Offline tests for the Phase 3A standalone live-data runner."""

from __future__ import annotations

import asyncio
from argparse import Namespace
from types import SimpleNamespace

import pytest

import scripts.run_live_market_data as runner


@pytest.mark.parametrize(
    "argv",
    [
        ["--duration", "-1"],
        ["--duration", "nan"],
        ["--duration", "inf"],
        ["--status-interval", "0"],
        ["--status-interval", "-1"],
        ["--status-interval", "nan"],
        ["--status-interval", "inf"],
    ],
)
def test_runner_rejects_invalid_timing_arguments(argv):
    with pytest.raises(SystemExit):
        runner.parse_args(argv)


def test_runner_returns_failure_when_stream_task_crashes(monkeypatch, capsys):
    async def fail_stream(adapters, stop_event):
        raise RuntimeError("offline test failure")

    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: SimpleNamespace(
            live_stale_after_seconds=30,
            okx_public_ws_url="wss://ws.okx.com:8443/ws/v5/public",
            okx_business_ws_url="wss://ws.okx.com:8443/ws/v5/business",
        ),
    )
    monkeypatch.setattr(runner, "build_default_adapters", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "run_adapters", fail_stream)

    result = asyncio.run(
        runner._run(
            Namespace(
                instruments=["BTC-USDT"],
                duration=0.0,
                status_interval=5.0,
            )
        )
    )

    assert result == 1
    assert "public-market-stream failed" in capsys.readouterr().err


def test_runner_duration_stops_cleanly(monkeypatch):
    async def wait_for_stop(adapters, stop_event):
        await stop_event.wait()

    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: SimpleNamespace(
            live_stale_after_seconds=30,
            okx_public_ws_url="wss://ws.okx.com:8443/ws/v5/public",
            okx_business_ws_url="wss://ws.okx.com:8443/ws/v5/business",
        ),
    )
    monkeypatch.setattr(runner, "build_default_adapters", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "run_adapters", wait_for_stop)

    result = asyncio.run(
        runner._run(
            Namespace(
                instruments=["BTC-USDT"],
                duration=0.01,
                status_interval=5.0,
            )
        )
    )

    assert result == 0
