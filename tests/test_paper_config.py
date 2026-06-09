"""Validation tests for Phase 4 configuration and CLI boundaries."""

from __future__ import annotations

import pytest

from app.paper.config import PaperRunConfig
from scripts.run_paper_trading import parse_args


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeframe": "5m"},
        {"fee_rate": 1.0},
        {"slippage_rate": -0.1},
        {"max_total_exposure": 1.1},
        {"max_open_positions": 0},
        {"window_size": 1},
        {"starting_cash": float("nan")},
    ],
)
def test_invalid_paper_config_fails_closed(kwargs):
    with pytest.raises(ValueError):
        PaperRunConfig(**kwargs)


def test_cli_rejects_out_of_range_fraction():
    with pytest.raises(SystemExit):
        parse_args(["--max-daily-loss", "1.1"])


def test_config_snapshot_is_explicitly_simulation_only():
    snapshot = PaperRunConfig().config_snapshot()
    assert snapshot["simulation_only"] is True
    assert "api_key" not in snapshot
