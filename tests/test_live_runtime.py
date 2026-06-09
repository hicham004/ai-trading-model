"""Offline lifecycle tests for the supervised Phase 3 live runtime."""

from __future__ import annotations

import asyncio

import pytest

import app.live.runtime as runtime


def test_runtime_cancels_websockets_if_persistence_crashes(monkeypatch):
    cancelled = False

    async def blocking_adapters(adapters, stop_event):
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    class FailingPersistence:
        async def run(self, stop_event):
            raise RuntimeError("offline persistence failure")

    monkeypatch.setattr(runtime, "run_adapters", blocking_adapters)

    async def drive():
        with pytest.raises(RuntimeError, match="offline persistence failure"):
            await runtime.run_live_runtime(
                [],
                asyncio.Event(),
                FailingPersistence(),  # type: ignore[arg-type]
            )

    asyncio.run(drive())
    assert cancelled is True


def test_runtime_without_persistence_stops_normally(monkeypatch):
    async def adapters(adapters, stop_event):
        stop_event.set()

    monkeypatch.setattr(runtime, "run_adapters", adapters)
    stop = asyncio.Event()
    asyncio.run(runtime.run_live_runtime([], stop))
    assert stop.is_set()
