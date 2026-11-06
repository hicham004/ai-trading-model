"""Forward regime fits: walk-forward geometry, train-only fitting, exact JSON round trip, fail-closed, refit cadence."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research.data import bars_per_year
from research.regime_v2 import RegimeV2Config, bear_probability, fit_regime
from research.paper_fleet.config import PURGE_DAYS, REFIT_DAYS, TRAIN_DAYS
from research.paper_fleet.regime import RegimeFit, fit_series, gate_inputs, needs_refit
from tests.test_paper_fleet_signals import synthetic_4h

TF = "4H"
CFG = RegimeV2Config(mode="gate", vol_window_days=7.0)


@pytest.fixture(scope="module")
def bars():
    return synthetic_4h(1300, seed=3)


def test_fit_uses_only_the_train_window_ending_a_purge_before_the_start(bars):
    active = bars.index[1200]
    fit = fit_series(bars, "BTC-USDT", TF, active, CFG)
    assert fit.train_end == active - pd.Timedelta(days=PURGE_DAYS)
    assert fit.train_start == fit.train_end - pd.Timedelta(days=TRAIN_DAYS)
    assert fit.active_until == active + pd.Timedelta(days=REFIT_DAYS)
    train = bars[(bars.index >= fit.train_start) & (bars.index < fit.train_end)]
    ref = fit_regime(train, TF, bars_per_year(TF), CFG)
    np.testing.assert_array_equal(fit.fitted.model.means_, ref.model.means_)
    np.testing.assert_array_equal(fit.fitted.model.transmat_, ref.model.transmat_)
    # Bars after the train end (the purge and the forward bars) never change the fit.
    changed = bars.copy()
    changed.loc[changed.index >= fit.train_end, ["open", "high", "low", "close"]] *= 1.5
    again = fit_series(changed, "BTC-USDT", TF, active, CFG)
    np.testing.assert_array_equal(again.fitted.model.means_, fit.fitted.model.means_)


def test_saved_fit_gives_bit_identical_probabilities(bars):
    fit = fit_series(bars, "BTC-USDT", TF, bars.index[1100], CFG)
    back = RegimeFit.from_dict(json.loads(json.dumps(fit.to_dict(), allow_nan=False)))
    a = gate_inputs(bars, fit, CFG)
    b = gate_inputs(bars, back, CFG)
    pd.testing.assert_series_equal(a["bear_prob"], b["bear_prob"], check_exact=True)
    pd.testing.assert_series_equal(a["ok"], b["ok"])
    # The filter runs from the train start, exactly as the research applied it.
    ref = bear_probability(fit.fitted, bars[bars.index >= fit.train_start], TF, bars_per_year(TF), CFG)
    pd.testing.assert_series_equal(a["bear_prob"], ref.rename("bear_prob"), check_names=False)


def test_filtered_probabilities_never_change_when_bars_are_appended(bars):
    fit = fit_series(bars, "BTC-USDT", TF, bars.index[1000], CFG)
    full = gate_inputs(bars, fit, CFG)["bear_prob"]
    prefix = gate_inputs(bars.iloc[:1150], fit, CFG)["bear_prob"]
    pd.testing.assert_series_equal(full.iloc[: len(prefix)], prefix)


def test_failed_fit_fails_closed(bars):
    fit = fit_series(bars.iloc[:50], "BTC-USDT", TF, bars.index[1000], CFG)
    assert fit.fitted is None and "200" in fit.error
    gate = gate_inputs(bars, fit, CFG)
    assert not gate["ok"].any()
    scale = gate_inputs(bars, fit, RegimeV2Config(mode="scale", vol_window_days=7.0, bear_scale=0.25))
    assert (scale["mult"] == 0.25).all() and scale["ok"].all()
    assert RegimeFit.from_dict(fit.to_dict()).fitted is None


def test_refit_cadence():
    start = pd.Timestamp("2026-10-21 12:00", tz="UTC")
    assert needs_refit(None, start)
    fit = RegimeFit("BTC-USDT", TF, start, start + pd.Timedelta(days=REFIT_DAYS), start, start, None, "x")
    assert not needs_refit(fit, start + pd.Timedelta(days=179))
    assert needs_refit(fit, start + pd.Timedelta(days=180))
