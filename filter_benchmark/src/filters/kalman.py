"""Group D — Kalman estimators (task spec §4 Group D).

State models (documented per filter):
  D01  x=[h,v]        F=[[1,dt],[0,1]]            meas z=h, var r
  D02  x=[h,v,a]      F=[[1,dt,dt^2/2],[0,1,dt],[0,0,1]]   meas z=h
  D03  x=[h,v,a,bias] — DEFERRED: with baro-only measurements the accel /
       bias pair is unobservable (spec: do not add states for sophistication).
       Runs only in the fusion phase with an IMU channel.
  D04  D01 + adaptive measurement noise (R from trailing innovation power)
  D05  D01 + innovation-based process-noise adaptation (q scaled by
       observed/expected innovation power)
  D06  D01 + robust measurement gating (innovation beyond g*sqrt(S) is
       deweighted, not dropped — no silent sample loss)

D02 with altitude-only measurements: 'a' is weakly observable through h
triple differences — documented limitation, evaluated empirically.

q is an acceleration PSD [m^2/s^3] (D02: jerk PSD [m^2/s^5]); r is altitude
measurement variance [m^2]. Defaults: r=0.035 m^2 (measured static floor
~0.19 m RMS, T-001/T-005 — Measured evidence, config-overridable).
"""
from __future__ import annotations

import numpy as np

from .base import Filter
from .tracking import ca_model, cv_model


class D01KalmanCV(Filter):
    name = "D01_Kalman_CV"

    def __init__(self, q: float = 1.0, r: float = 0.035, auto_r: bool = False,
                 q_h: float = None, q_v: float = None, warmup_s: float = 3.0):
        self.q = float(q)
        self.r = float(r)
        self.auto_r = bool(auto_r)
        # legacy knobs to reproduce the T-008 project estimator exactly (B02)
        self.q_h = q_h
        self.q_v = q_v
        self.warmup_s = float(warmup_s)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self.P = np.eye(2) * 10.0
        self._warm = []
        self._warm_t0 = None
        self._r_eff = self.r

    def _on_first(self, t, z):
        self._h = z
        self._warm = [z]
        self._warm_t0 = t

    def _Q(self, dt):
        if self.q_h is not None:      # T-008 legacy parameterization
            Q = np.array([[self.q_h * dt ** 3 / 3, self.q_h * dt ** 2 / 2],
                          [self.q_h * dt ** 2 / 2, self.q_h * dt]])
            Q[1, 1] += (self.q_v or 0.5) * dt
            return Q
        F, H, Q, r = cv_model(dt, self.q, self.r)
        return Q

    def _on_update(self, t, z, dt):
        if self.auto_r and self._warm is not None:
            self._warm.append(z)
            if t - self._warm_t0 >= self.warmup_s:
                w = np.asarray(self._warm)
                r = max(np.var(np.diff(w)) / (2 * dt ** 2), 0.01)
                self._r_eff = float(r)
                self._warm = None
            else:
                self._r_eff = self.r
        F = np.array([[1.0, dt], [0.0, 1.0]])
        xp = F @ np.array([self._h, self._v])
        Pp = F @ self.P @ F.T + self._Q(dt)
        y = z - xp[0]
        S = Pp[0, 0] + self._r_eff
        K = Pp[:, 0] / S
        xe = xp + K * y
        self._h, self._v = xe[0], xe[1]
        self.P = (np.eye(2) - np.outer(K, [1.0, 0.0])) @ Pp
        return self._v

    def _config_repr(self):
        if self.q_h is not None:
            return f"q_h={self.q_h},q_v={self.q_v},auto_r={self.auto_r}"
        return f"q={self.q},r={self.r}"


class D02KalmanCA(Filter):
    name = "D02_Kalman_CA"

    def __init__(self, q: float = 1.0, r: float = 0.035):
        self.q = float(q)
        self.r = float(r)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._a = 0.0
        self.P = np.eye(3) * 10.0

    def _on_first(self, t, z):
        self._h = z

    def _on_update(self, t, z, dt):
        F, H, Q, r = ca_model(dt, self.q, self.r)
        x = np.array([self._h, self._v, self._a])
        xp = F @ x
        Pp = F @ self.P @ F.T + Q
        y = z - xp[0]
        S = Pp[0, 0] + r
        K = Pp[:, 0] / S
        xe = xp + K * y
        self._h, self._v, self._a = xe
        self.P = (np.eye(3) - np.outer(K, [1.0, 0.0, 0.0])) @ Pp
        return self._v

    def _config_repr(self):
        return f"q={self.q},r={self.r}"


class _InnovationWindow:
    """Trailing window (seconds) of squared innovations + predicted S."""

    def __init__(self, window_s):
        self.window_s = float(window_s)
        self.items = []          # (t, y2, S)

    def push(self, t, y, S):
        self.items.append((t, y * y, S))
        cut = t - self.window_s
        i = 0
        while i < len(self.items) and self.items[i][0] < cut:
            i += 1
        if i:
            del self.items[:i]

    def stats(self):
        if len(self.items) < 5:
            return None
        y2 = np.mean([it[1] for it in self.items])
        S = np.mean([it[2] for it in self.items])
        return y2, S


class D04KalmanAdaptiveR(D01KalmanCV):
    """D01 with R adapted from trailing innovation power:
    r_eff = clip(E[y^2] - E[S_pred], r_min, r_max)."""
    name = "D04_Kalman_adaptR"

    def __init__(self, q: float = 1.0, r: float = 0.035, window_s: float = 5.0,
                 r_min: float = 0.005, r_max: float = 1.0):
        self.window_s = float(window_s)
        self.r_min = float(r_min)
        self.r_max = float(r_max)
        super().__init__(q=q, r=r)

    def _init_state(self):
        super()._init_state()
        self._innov = _InnovationWindow(self.window_s)

    def _on_update(self, t, z, dt):
        F = np.array([[1.0, dt], [0.0, 1.0]])
        xp = F @ np.array([self._h, self._v])
        Pp = F @ self.P @ F.T + self._Q(dt)
        y = z - xp[0]
        S = Pp[0, 0] + self.r
        self._innov.push(t, y, S)
        st = self._innov.stats()
        if st is not None:
            y2, s_mean = st
            self._r_eff = float(np.clip(y2 - s_mean + self.r, self.r_min, self.r_max))
        K = Pp[:, 0] / (Pp[0, 0] + self._r_eff)
        xe = xp + K * y
        self._h, self._v = xe[0], xe[1]
        self.P = (np.eye(2) - np.outer(K, [1.0, 0.0])) @ Pp
        return self._v

    def _config_repr(self):
        return f"q={self.q},r={self.r},window_s={self.window_s}"


class D05KalmanAdaptQ(D01KalmanCV):
    """D01 with q scaled by innovation power ratio:
    q_eff = q * clip(E[y^2]/E[S], q_lo, q_hi). Motion raises q (faster
    tracking); rest returns it to baseline."""
    name = "D05_Kalman_adaptQ"

    def __init__(self, q: float = 1.0, r: float = 0.035, window_s: float = 3.0,
                 q_lo: float = 0.2, q_hi: float = 20.0):
        self.q_lo = float(q_lo)
        self.q_hi = float(q_hi)
        self.window_s = float(window_s)   # must precede super().__init__
        super().__init__(q=q, r=r)

    def _init_state(self):
        super()._init_state()
        self._innov = _InnovationWindow(self.window_s)
        self._q_eff = self.q

    def _on_update(self, t, z, dt):
        F = np.array([[1.0, dt], [0.0, 1.0]])
        xp = F @ np.array([self._h, self._v])
        Pp = F @ self.P @ F.T + self._Q(dt)
        y = z - xp[0]
        S = Pp[0, 0] + self.r
        self._innov.push(t, y, S)
        st = self._innov.stats()
        if st is not None:
            y2, s_mean = st
            if s_mean > 0:
                self._q_eff = self.q * float(np.clip(y2 / s_mean, self.q_lo, self.q_hi))
        # rebuild Q with adapted q (legacy parameterization untouched)
        if self.q_h is None:
            _, _, Q, _ = cv_model(dt, self._q_eff, self.r)
            Pp = F @ self.P @ F.T + Q
            S = Pp[0, 0] + self.r
        K = Pp[:, 0] / S
        xe = xp + K * y
        self._h, self._v = xe[0], xe[1]
        self.P = (np.eye(2) - np.outer(K, [1.0, 0.0])) @ Pp
        return self._v

    def _config_repr(self):
        return f"q={self.q},r={self.r},window_s={self.window_s}"


class D06KalmanGated(D01KalmanCV):
    """D01 with robust gating: innovations beyond g*sqrt(S) are deweighted
    quadratically (equivalent R inflation) rather than dropped — the sample
    still contributes weakly, nothing is silently discarded."""
    name = "D06_Kalman_gated"

    def __init__(self, q: float = 1.0, r: float = 0.035, gate_sigma: float = 3.0):
        self.gate_sigma = float(gate_sigma)
        super().__init__(q=q, r=r)

    def _on_update(self, t, z, dt):
        F = np.array([[1.0, dt], [0.0, 1.0]])
        xp = F @ np.array([self._h, self._v])
        Pp = F @ self.P @ F.T + self._Q(dt)
        y = z - xp[0]
        S = Pp[0, 0] + self.r
        r_eff = self.r
        if abs(y) > self.gate_sigma * np.sqrt(S):
            r_eff = self.r * (y / (self.gate_sigma * np.sqrt(S))) ** 2
        K = Pp[:, 0] / (Pp[0, 0] + r_eff)
        xe = xp + K * y
        self._h, self._v = xe[0], xe[1]
        self.P = (np.eye(2) - np.outer(K, [1.0, 0.0])) @ Pp
        return self._v

    def _config_repr(self):
        return f"q={self.q},r={self.r},gate_sigma={self.gate_sigma}"
