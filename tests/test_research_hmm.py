"""Gaussian HMM (research/hmm.py): EM monotonicity, recovery of a planted regime, forward-only filtering."""

from __future__ import annotations

import numpy as np
import pytest

from research.hmm import GaussianHMM


def _two_regime_series(n: int = 3000, seed: int = 0, switch: float = 0.02):
    rng = np.random.default_rng(seed)
    states = np.zeros(n, dtype=int)
    s = 0
    for i in range(n):
        if rng.random() < switch:
            s = 1 - s
        states[i] = s
    x = np.where(states == 0, rng.normal(0.8, 1.0, n), rng.normal(-1.2, 2.0, n))
    return x, states


def test_fit_is_deterministic_and_loglik_increases():
    x, _ = _two_regime_series()
    a = GaussianHMM(2, n_iter=50).fit(x)
    b = GaussianHMM(2, n_iter=50).fit(x)
    np.testing.assert_allclose(a.means_, b.means_)
    np.testing.assert_allclose(a.transmat_, b.transmat_)
    hist = np.asarray(a.loglik_history_)
    assert len(hist) >= 2 and np.all(np.diff(hist) > -1e-6), "EM must not decrease the log-likelihood"
    rows = a.transmat_.sum(axis=1)
    np.testing.assert_allclose(rows, 1.0)
    assert abs(a.startprob_.sum() - 1.0) < 1e-9
    assert (a.vars_ > 0).all()


def test_recovers_planted_regimes():
    x, states = _two_regime_series()
    m = GaussianHMM(2).fit(x)
    order = m.state_order()  # ascending mean: order[0] is the low-mean (planted state 1) regime
    low, high = int(order[0]), int(order[-1])
    assert m.means_[high, 0] > 0.3 and m.means_[low, 0] < -0.5
    assert m.vars_[low, 0] > m.vars_[high, 0]  # the bear regime is the noisier one
    assert np.diag(m.transmat_).min() > 0.9  # sticky regimes
    decoded = m.filter(x).argmax(axis=1)
    agreement = np.mean((decoded == low) == (states == 1))
    assert agreement > 0.8


def test_filter_uses_only_the_past():
    x, _ = _two_regime_series(seed=3)
    m = GaussianHMM(2).fit(x[:2000])
    full = m.filter(x)
    prefix = m.filter(x[:1200])
    np.testing.assert_allclose(prefix, full[:1200], atol=1e-12)
    # Appending wildly different future data must not change earlier filtered rows.
    extended = np.concatenate([x, np.full(500, 25.0)])
    np.testing.assert_allclose(m.filter(extended)[: len(x)], full, atol=1e-12)
    assert np.allclose(full.sum(axis=1), 1.0)


def test_multivariate_and_validation():
    rng = np.random.default_rng(1)
    X = np.column_stack([rng.normal(0, 1, 500), rng.normal(0, 1, 500)])
    m = GaussianHMM(3, n_iter=20).fit(X)
    assert m.means_.shape == (3, 2) and m.filter(X).shape == (500, 3)
    assert np.isfinite(m.score(X))
    d = m.to_dict()
    assert d["fitted"] and len(d["means"]) == 3
    with pytest.raises(ValueError):
        GaussianHMM(1)
    with pytest.raises(ValueError):
        GaussianHMM(2).filter(X)  # not fitted
    with pytest.raises(ValueError):
        GaussianHMM(2).fit(np.array([1.0, np.nan, 2.0]))
    with pytest.raises(ValueError):
        m.filter(rng.normal(size=(10, 3)))  # wrong dimension
    assert GaussianHMM(2).to_dict()["fitted"] is False
