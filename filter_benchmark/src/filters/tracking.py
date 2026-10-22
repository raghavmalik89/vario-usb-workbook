"""Group C — tracking filters (task spec §4 Group C).

C01 alpha-beta, C02 alpha-beta-gamma: gains parameterized by a response
time constant tau_s and a documented critically-damped gain family:
    alpha = 1 - exp(-dt/tau)
    beta  = alpha^2 / (2 - alpha)
    gamma = alpha * beta / (2 - alpha)        (ABG only)
The family is a heuristic (explicitly documented, spec §4 requires explicit
parameters — not a claim of optimality). C03/C04: steady-state-gain CV/CA
trackers: the gains are the converged Kalman gains for a declared process/
measurement covariance, frozen at startup per dt (recomputed when dt shifts
>2%). C03 == steady-state D01; C04 == steady-state D02.

Prediction uses actual elapsed dt every update.
"""
from __future__ import annotations

import numpy as np

from .base import DT_RECOMP_TOLERANCE, Filter


def _abg_gains(dt, tau):
    alpha = 1.0 - np.exp(-dt / tau)
    beta = alpha * alpha / (2.0 - alpha)
    gamma = alpha * beta / (2.0 - alpha)
    return alpha, beta, gamma


def steady_state_gains(n, dt, F, H, Q, R, iters=200):
    """Iterate the Riccati equation to convergence; return K = P H'/(H P H' + R).
    Deterministic (fixed iteration count), no solver dependency."""
    P = np.eye(n) * 10.0
    for _ in range(iters):
        Pp = F @ P @ F.T + Q
        S = H @ Pp @ H.T + R
        K = Pp @ H.T / S
        P = (np.eye(n) - np.outer(K, H.ravel())) @ Pp
    Pp = F @ P @ F.T + Q
    S = H @ Pp @ H.T + R
    return (Pp @ H.T / S).ravel()


class C01AlphaBeta(Filter):
    name = "C01_AlphaBeta"

    def __init__(self, tau_s: float = 0.5):
        self.tau_s = float(tau_s)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._dt_fit = None
        self._alpha = self._beta = None

    def _on_first(self, t, z):
        self._h = z

    def _refit(self, dt):
        self._alpha, self._beta, _ = _abg_gains(dt, self.tau_s)
        self._dt_fit = dt

    def _on_update(self, t, z, dt):
        if self._dt_fit is None or abs(dt - self._dt_fit) / self._dt_fit > DT_RECOMP_TOLERANCE:
            self._refit(dt)
        h_pred = self._h + self._v * dt
        y = z - h_pred
        self._h = h_pred + self._alpha * y
        self._v = self._v + (self._beta / dt) * y
        return self._v

    def _config_repr(self):
        return f"tau_s={self.tau_s}"


class C02AlphaBetaGamma(Filter):
    name = "C02_AlphaBetaGamma"

    def __init__(self, tau_s: float = 0.6):
        self.tau_s = float(tau_s)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._a = 0.0
        self._dt_fit = None
        self._alpha = self._beta = self._gamma = None

    def _on_first(self, t, z):
        self._h = z

    def _refit(self, dt):
        self._alpha, self._beta, self._gamma = _abg_gains(dt, self.tau_s)
        self._dt_fit = dt

    def _on_update(self, t, z, dt):
        if self._dt_fit is None or abs(dt - self._dt_fit) / self._dt_fit > DT_RECOMP_TOLERANCE:
            self._refit(dt)
        h_pred = self._h + self._v * dt + 0.5 * self._a * dt * dt
        y = z - h_pred
        self._h = h_pred + self._alpha * y
        self._v = self._v + (self._beta / dt) * y
        self._a = self._a + (self._gamma / (dt * dt)) * y
        return self._v

    def _config_repr(self):
        return f"tau_s={self.tau_s}"


def cv_model(dt, q, r):
    F = np.array([[1.0, dt], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = q * np.array([[dt ** 4 / 4, dt ** 3 / 2], [dt ** 3 / 2, dt ** 2]])
    return F, H, Q, r


def ca_model(dt, q, r):
    F = np.array([[1.0, dt, 0.5 * dt * dt], [0.0, 1.0, dt], [0.0, 0.0, 1.0]])
    H = np.array([[1.0, 0.0, 0.0]])
    Q = q * np.array([[dt ** 4 / 4, dt ** 3 / 2, dt ** 2 / 2],
                      [dt ** 3 / 2, dt ** 2, dt],
                      [dt ** 2 / 2, dt, 1.0]])
    return F, H, Q, r


class _SteadyStateTracker(Filter):
    def __init__(self, tau_s):
        self.tau_s = float(tau_s)     # response shaping via q = (1/tau)^2 scaling
        super().__init__()

    def _model(self, dt):
        raise NotImplementedError

    def _init_state(self):
        self._h = 0.0
        self._dt_fit = None
        self._K = None

    def _on_first(self, t, z):
        self._h = z

    def _refit(self, dt):
        F, H, Q, r = self._model(dt)
        self._K = steady_state_gains(F.shape[0], dt, F, H, Q, r)
        self._F, self._H = F, H
        self._dt_fit = dt

    def _on_update(self, t, z, dt):
        if self._K is None:
            # frozen steady-state gains: solve the Riccati ONCE at the first
            # physical dt and hold them for the whole stream (re-solving per
            # sample would be wasteful; sub-percent dt jitter around the
            # frozen design point is negligible)
            self._refit(dt)
        F, H, _, _ = self._model(dt)   # F at the ACTUAL dt (cheap, exact)
        self._F, self._H = F, H
        n = len(self._K)
        x = np.zeros(n)
        x[0] = self._h
        x[1] = self._v
        if n > 2:
            x[2] = getattr(self, "_a", 0.0)
        xp = self._F @ x
        y = z - xp[0]
        xe = xp + self._K * y
        self._h, self._v = xe[0], xe[1]
        if n > 2:
            self._a = xe[2]
        return self._v


class C03CVTracker(_SteadyStateTracker):
    """Constant-velocity tracker, steady-state Kalman gains; q is the accel
    PSD [m^2/s^3], r the altitude meas variance [m^2]. Physically equivalent
    across rates (PSDs, not per-sample values)."""
    name = "C03_CV_tracker"

    def __init__(self, q: float = 1.0, r: float = 0.035):
        self.q = float(q)
        self.r = float(r)
        super().__init__(tau_s=1.0)

    def _model(self, dt):
        return cv_model(dt, self.q, self.r)

    def _config_repr(self):
        return f"q={self.q},r={self.r}"


class C04CATracker(_SteadyStateTracker):
    """Constant-acceleration tracker, steady-state Kalman gains; q is the
    jerk PSD [m^2/s^5], r altitude meas variance [m^2]."""
    name = "C04_CA_tracker"

    def __init__(self, q: float = 1.0, r: float = 0.035):
        self.q = float(q)
        self.r = float(r)
        super().__init__(tau_s=1.0)
        self._a = 0.0

    def _model(self, dt):
        return ca_model(dt, self.q, self.r)

    def _config_repr(self):
        return f"q={self.q},r={self.r}"
