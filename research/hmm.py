"""Gaussian hidden Markov model with diagonal covariances (numpy only; SIMULATION ONLY).

Written for the regime-v2 entry gate (master plan Sprint 2c, item 1). The
project deliberately keeps ``hmmlearn``/``scipy`` out of the audited lockfile,
and a research regime filter needs one property those libraries do not expose
directly anyway: **filtered** state probabilities ``P(state_t | x_1..x_t)``
that use only bars up to and including ``t``. ``hmmlearn``'s ``predict`` /
``predict_proba`` are smoothed (forward-backward) over the whole sequence and
would leak the future into a trading decision.

- :meth:`GaussianHMM.fit` — Baum-Welch (EM) with a scaled forward-backward
  pass; deterministic initialisation (quantile groups on the first feature),
  so a fit is reproducible without a random seed.
- :meth:`GaussianHMM.filter` — forward pass only; the probabilities at bar
  ``t`` are a function of ``x_1..x_t`` and the fitted parameters. Running the
  filter on a prefix of a series gives a prefix of the result (tested).
- :meth:`GaussianHMM.score` — log-likelihood of a sequence under the model.

States carry no labels here; :mod:`research.regime_v2` orders them by mean
return. Nothing in this module reads market data or can reach an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

_LOG_2PI = float(np.log(2.0 * np.pi))


@dataclass
class GaussianHMM:
    n_states: int = 3
    n_iter: int = 200
    tol: float = 1e-5
    min_var: float = 1e-6
    sticky: float = 0.95  # initial self-transition probability
    startprob_: Optional[np.ndarray] = None
    transmat_: Optional[np.ndarray] = None
    means_: Optional[np.ndarray] = None
    vars_: Optional[np.ndarray] = None
    loglik_history_: List[float] = field(default_factory=list)
    converged_: bool = False

    def __post_init__(self) -> None:
        if int(self.n_states) < 2:
            raise ValueError("n_states must be at least 2")
        if int(self.n_iter) < 1:
            raise ValueError("n_iter must be positive")
        if not (0.0 < self.sticky < 1.0):
            raise ValueError("sticky must be in (0, 1)")
        if self.min_var <= 0:
            raise ValueError("min_var must be positive")

    # -- helpers ---------------------------------------------------------------

    @property
    def fitted(self) -> bool:
        return self.means_ is not None

    @staticmethod
    def _as_matrix(X) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            arr = arr[:, None]
        if arr.ndim != 2:
            raise ValueError("X must be a (T, D) matrix")
        if arr.shape[0] < 2:
            raise ValueError("need at least two observations")
        if not np.all(np.isfinite(arr)):
            raise ValueError("X must be finite (drop warm-up rows before fitting/filtering)")
        return arr

    def _initialise(self, X: np.ndarray) -> None:
        T, D = X.shape
        K = int(self.n_states)
        if T < 2 * K:
            raise ValueError(f"need at least {2 * K} observations to fit {K} states")
        order = np.argsort(X[:, 0], kind="mergesort")
        groups = np.array_split(order, K)
        self.means_ = np.array([X[g].mean(axis=0) for g in groups])
        self.vars_ = np.array([np.maximum(X[g].var(axis=0), self.min_var) for g in groups])
        self.startprob_ = np.full(K, 1.0 / K)
        off = (1.0 - self.sticky) / (K - 1)
        self.transmat_ = np.full((K, K), off)
        np.fill_diagonal(self.transmat_, self.sticky)

    def _log_emission(self, X: np.ndarray) -> np.ndarray:
        """(T, K) log densities of every observation under every state (diagonal Gaussian)."""
        var = self.vars_[None, :, :]
        diff = X[:, None, :] - self.means_[None, :, :]
        return -0.5 * np.sum(np.log(var) + _LOG_2PI + diff * diff / var, axis=2)

    def _forward(self, logB: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """Scaled forward pass. Returns (alpha, scales, log-likelihood).

        ``alpha[t]`` is the filtered posterior ``P(state_t | x_1..x_t)``.
        """
        T, K = logB.shape
        shift = logB.max(axis=1)
        B = np.exp(logB - shift[:, None])
        alpha = np.zeros((T, K))
        scales = np.zeros(T)
        a = self.startprob_ * B[0]
        scales[0] = a.sum()
        alpha[0] = a / scales[0]
        A = self.transmat_
        for t in range(1, T):
            a = (alpha[t - 1] @ A) * B[t]
            s = a.sum()
            if s <= 0.0 or not np.isfinite(s):  # numerically dead row: fall back to the prior transition
                a = alpha[t - 1] @ A
                s = a.sum()
            scales[t] = s
            alpha[t] = a / s
        loglik = float(np.sum(np.log(scales)) + np.sum(shift))
        return alpha, scales, loglik

    def _backward(self, logB: np.ndarray, scales: np.ndarray) -> np.ndarray:
        T, K = logB.shape
        shift = logB.max(axis=1)
        B = np.exp(logB - shift[:, None])
        beta = np.zeros((T, K))
        beta[T - 1] = 1.0
        A = self.transmat_
        for t in range(T - 2, -1, -1):
            beta[t] = (A @ (B[t + 1] * beta[t + 1])) / scales[t + 1]
        return beta

    # -- public API ----------------------------------------------------------

    def fit(self, X) -> "GaussianHMM":
        """Baum-Welch on one sequence (rows = time). Deterministic; returns self."""
        X = self._as_matrix(X)
        self._initialise(X)
        T, D = X.shape
        K = int(self.n_states)
        self.loglik_history_ = []
        self.converged_ = False
        previous = -np.inf
        for _ in range(int(self.n_iter)):
            logB = self._log_emission(X)
            alpha, scales, loglik = self._forward(logB)
            beta = self._backward(logB, scales)
            gamma = alpha * beta
            gamma /= np.maximum(gamma.sum(axis=1, keepdims=True), 1e-300)
            shift = logB.max(axis=1)
            B = np.exp(logB - shift[:, None])
            # xi[t, i, j] ∝ alpha[t, i] * A[i, j] * B[t+1, j] * beta[t+1, j] / scales[t+1]
            xi = (
                alpha[:-1, :, None]
                * self.transmat_[None, :, :]
                * (B[1:, None, :] * beta[1:, None, :])
                / scales[1:, None, None]
            )
            self.loglik_history_.append(loglik)
            # M-step.
            self.startprob_ = np.maximum(gamma[0], 1e-12)
            self.startprob_ /= self.startprob_.sum()
            trans = xi.sum(axis=0)
            trans = np.maximum(trans, 1e-12)
            self.transmat_ = trans / trans.sum(axis=1, keepdims=True)
            weight = gamma.sum(axis=0)  # (K,)
            for k in range(K):
                if weight[k] < 1e-8:  # a collapsed state keeps its parameters
                    continue
                mean = (gamma[:, k, None] * X).sum(axis=0) / weight[k]
                diff = X - mean[None, :]
                var = (gamma[:, k, None] * diff * diff).sum(axis=0) / weight[k]
                self.means_[k] = mean
                self.vars_[k] = np.maximum(var, self.min_var)
            if loglik - previous < self.tol and np.isfinite(previous):
                self.converged_ = True
                break
            previous = loglik
        return self

    def filter(self, X) -> np.ndarray:
        """Filtered state probabilities (T, K): row ``t`` uses only ``x_1..x_t``."""
        if not self.fitted:
            raise ValueError("fit the model first")
        X = self._as_matrix(X)
        if X.shape[1] != self.means_.shape[1]:
            raise ValueError("feature dimension does not match the fitted model")
        alpha, _, _ = self._forward(self._log_emission(X))
        return alpha

    def score(self, X) -> float:
        if not self.fitted:
            raise ValueError("fit the model first")
        X = self._as_matrix(X)
        _, _, loglik = self._forward(self._log_emission(X))
        return loglik

    def state_order(self, feature: int = 0) -> np.ndarray:
        """State indices sorted by their mean of ``feature`` (ascending)."""
        if not self.fitted:
            raise ValueError("fit the model first")
        return np.argsort(self.means_[:, feature], kind="mergesort")

    def to_dict(self) -> dict:
        if not self.fitted:
            return {"n_states": int(self.n_states), "fitted": False}
        return {
            "n_states": int(self.n_states),
            "fitted": True,
            "converged": bool(self.converged_),
            "iterations": len(self.loglik_history_),
            "loglik": float(self.loglik_history_[-1]) if self.loglik_history_ else None,
            "startprob": self.startprob_.tolist(),
            "transmat": self.transmat_.tolist(),
            "means": self.means_.tolist(),
            "vars": self.vars_.tolist(),
        }
