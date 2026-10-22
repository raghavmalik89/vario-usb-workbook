"""Phase 3 stacked architectures S1-S3 (spec §2).

Each architecture is a Filter (velocity output), so it plugs into the same
causal replay / metrics machinery as the standalone Groups A-E. The audio
state machine is NOT inside any architecture — it is applied downstream
uniformly (src/audio.py), keeping filter and audio behaviour independently
measurable.

S1 RobustBaroAdaptiveKF — Hampel outlier rejection -> CV Kalman with
   innovation gating and motion-adaptive process noise.
S2 DualTimescale — fast AlphaBeta detector + slow CV-Kalman stabiliser,
   explicit gated blend; slow branch doubles as confidence/persistence.
S3 AccelerationAwareKF — CA Kalman (h, v, a) with innovation plausibility
   gating, acceleration-bias sanity check, fault detection and recovery.
   BAROMETER-ONLY here: no capture streams IMU data (MPU6050 is probed at
   health-check but never streamed), so no IMU fusion advantage is claimed
   anywhere. IMU fusion is a Phase-4 item contingent on capture validity.

All sub-components are the verified Phase-2 filters, composed; every
knob is physical (seconds, Hz, PSDs, m/s).
"""
from __future__ import annotations

import numpy as np

from .base import Filter
from .smoothing import A05Hampel
from .kalman import D01KalmanCV, D02KalmanCA
from .tracking import C01AlphaBeta, cv_model, ca_model


class S1RobustBaroAdaptiveKF(Filter):
    """Hampel (outlier rejection) -> CV Kalman with innovation gating and
    motion-adaptive q. q scales up with the estimated |v| so the estimator
    tracks aggressively in motion and quietly at rest."""

    name = "S1_RobustAdaptiveKF"

    def __init__(self, window_s: float = 1.0, n_sigma: float = 2.5,
                 q: float = 0.3, r: float = 0.035, gate_sigma: float = 3.5,
                 q_gain: float = 2.0, v_scale: float = 1.0):
        self.window_s = float(window_s)
        self.n_sigma = float(n_sigma)
        self.q = float(q)
        self.r = float(r)
        self.gate_sigma = float(gate_sigma)
        self.q_gain = float(q_gain)
        self.v_scale = float(v_scale)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._hampel = A05Hampel(window_s=self.window_s, n_sigma=self.n_sigma)
        self._x = None
        self._P = None
        self._q_eff = self.q
        self.n_gated = 0

    def _on_first(self, t, z):
        self._hampel.update(float(z), t)
        self._h = float(z)
        self._v = 0.0

    def _on_update(self, t, z, dt):
        # feed the KF the CLEANED RAW stream (outliers replaced by the window
        # median); the branch's median output is NOT used here because a
        # seconds-long median injects a half-window group delay on real motion
        self._hampel.update(float(z), t)
        zc = self._hampel._last_clean
        if zc is None:
            zc = float(z)
        if self._x is None:
            self._F, self._H, _, _ = cv_model(dt, self.q, self.r)
            self._x = np.array([zc, 0.0])
            self._P = np.diag([1.0, 1.0])
        F, H, Q, r = cv_model(dt, self._q_eff, self.r)
        xp = F @ self._x
        Pp = F @ self._P @ F.T + Q
        y = float(zc - (H @ xp)[0])
        S = float(Pp[0, 0] + r)
        if abs(y) > self.gate_sigma * np.sqrt(S):
            self.n_gated += 1            # reject: prediction only, P grows
            self._x = xp
            self._P = Pp
        else:
            K = (Pp @ H.T / S).ravel()
            self._x = xp + K * y
            self._P = (np.eye(2) - np.outer(K, H)) @ Pp
        self._h, self._v = float(self._x[0]), float(self._x[1])
        # motion-adaptive process noise (physical: q is a PSD)
        self._q_eff = self.q * (1.0 + self.q_gain *
                                min(abs(self._v) / self.v_scale, 3.0))
        return self._v

    def _config_repr(self):
        return (f"window_s={self.window_s},n_sigma={self.n_sigma},"
                f"q={self.q},r={self.r},gate_sigma={self.gate_sigma},"
                f"q_gain={self.q_gain},v_scale={self.v_scale}")


class S2DualTimescale(Filter):
    """Fast AlphaBeta (early detection) + slow CV Kalman (stability and
    confidence), explicit gated blend:
      w = clip(|v_fast| / v_scale, 0, 1)  — fast dominates once moving
      v = (1-w)*v_slow + w*v_fast
    plus persistence: after strong motion, the fast path stays authoritative
    until |v_fast| has stayed below exit_v for exit_hold_s (interruptible
    audio state machine requirement: rapid exit from lift)."""

    name = "S2_DualTimescale"

    def __init__(self, tau_fast_s: float = 0.35, q_slow: float = 0.3,
                 r_slow: float = 0.035, v_scale: float = 0.8,
                 exit_v: float = 0.15, exit_hold_s: float = 0.6,
                 v_plaus_max: float = 8.0, plaus_margin_m: float = 0.3):
        self.tau_fast_s = float(tau_fast_s)
        self.q_slow = float(q_slow)
        self.r_slow = float(r_slow)
        self.v_scale = float(v_scale)
        self.exit_v = float(exit_v)
        self.exit_hold_s = float(exit_hold_s)
        self.v_plaus_max = float(v_plaus_max)
        self.plaus_margin_m = float(plaus_margin_m)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._fast = C01AlphaBeta(tau_s=self.tau_fast_s)
        self._slow = D01KalmanCV(q=self.q_slow, r=self.r_slow)
        self._fast_hold = False
        self._below_since = None
        self.n_rejected = 0

    def _on_first(self, t, z):
        self._fast.update(float(z), t)
        self._slow.update(float(z), t)
        self._h = float(z)
        self._v = 0.0

    def _on_update(self, t, z, dt):
        # physical plausibility pre-clean shared by both branches: a single
        # sample farther than v_plaus_max*dt + margin from the fast branch's
        # own prediction cannot be real motion -> replace with prediction
        h_pred = self._fast.get_altitude() + self._fast.get_estimate() * dt
        max_dev = self.v_plaus_max * dt + self.plaus_margin_m
        if abs(z - h_pred) > max_dev:
            self.n_rejected += 1
            zc = h_pred
        else:
            zc = float(z)
        vf = self._fast.update(float(zc), t)
        vs = self._slow.update(float(zc), t)
        if not self._fast_hold and abs(vf) > self.v_scale:
            self._fast_hold = True          # strong motion: fast path latches
        if self._fast_hold:
            if abs(vf) < self.exit_v:
                if self._below_since is None:
                    self._below_since = t
                if t - self._below_since >= self.exit_hold_s:
                    self._fast_hold = False
                    self._below_since = None
            else:
                self._below_since = None
        w = min(abs(vf) / self.v_scale, 1.0)
        if self._fast_hold:
            w = max(w, 0.6)                 # persistence: keep fast path hot
        self._h = self._slow.get_altitude()
        self._v = (1.0 - w) * vs + w * vf
        return self._v

    def _config_repr(self):
        return (f"tau_fast_s={self.tau_fast_s},q_slow={self.q_slow},"
                f"r_slow={self.r_slow},v_scale={self.v_scale},"
                f"exit_v={self.exit_v},exit_hold_s={self.exit_hold_s},"
                f"v_plaus_max={self.v_plaus_max},"
                f"plaus_margin_m={self.plaus_margin_m}")


class S3AccelerationAwareKF(Filter):
    """CA Kalman (h, v, a) with:
      - innovation plausibility gating (per-sample, like D06),
      - acceleration sanity check: |a| clamped to a_plaus_max (baro-only a
        estimates beyond this indicate model stress, not real motion),
      - fault detection: |innovation| > fault_sigma*sqrt(S) for
        fault_n consecutive samples -> FAULT: freeze a-state, inflate R by
        fault_r_mult, resume when innovations return to normal (recovery).
    Barometer-only by construction (see module docstring)."""

    name = "S3_AccelerationAwareKF"

    def __init__(self, q: float = 0.3, r: float = 0.035,
                 gate_sigma: float = 3.5, a_plaus_max: float = 6.0,
                 fault_sigma: float = 5.0, fault_n: int = 8,
                 fault_r_mult: float = 25.0):
        self.q = float(q)
        self.r = float(r)
        self.gate_sigma = float(gate_sigma)
        self.a_plaus_max = float(a_plaus_max)
        self.fault_sigma = float(fault_sigma)
        self.fault_n = int(fault_n)
        self.fault_r_mult = float(fault_r_mult)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._x = None
        self._P = None
        self._fault = False
        self._fault_count = 0
        self._recover_count = 0
        self.n_faults = 0
        self.n_gated = 0
        self._r_eff = self.r

    def _on_first(self, t, z):
        self._x = np.array([float(z), 0.0, 0.0])
        self._P = np.diag([1.0, 1.0, 4.0])
        self._h = float(z)
        self._v = 0.0

    def _on_update(self, t, z, dt):
        F, H, Q, r = ca_model(dt, self.q, self._r_eff)
        xp = F @ self._x
        Pp = F @ self._P @ F.T + Q
        y = float(z - (H @ xp)[0])
        S = float(Pp[0, 0] + r)
        sig = np.sqrt(S)
        # fault detection / recovery on the innovation sequence
        if abs(y) > self.fault_sigma * sig:
            self._fault_count += 1
            self._recover_count = 0
            if self._fault_count >= self.fault_n and not self._fault:
                self._fault = True
                self.n_faults += 1
                self._r_eff = self.r * self.fault_r_mult
        else:
            self._fault_count = 0
            if self._fault:
                self._recover_count += 1
                if self._recover_count >= self.fault_n:
                    self._fault = False
                    self._r_eff = self.r
        # per-sample innovation gating (tighter during fault)
        gate = self.gate_sigma if not self._fault else self.gate_sigma / 2.0
        if abs(y) > gate * sig:
            self.n_gated += 1
            self._x = xp
            self._P = Pp
        else:
            K = (Pp @ H.T / S).ravel()
            self._x = xp + K * y
            self._P = (np.eye(3) - np.outer(K, H)) @ Pp
        # acceleration plausibility: clamp the a-state, not the estimate path
        if abs(self._x[2]) > self.a_plaus_max:
            self._x[2] = np.sign(self._x[2]) * self.a_plaus_max
        self._h, self._v = float(self._x[0]), float(self._x[1])
        return self._v

    def _config_repr(self):
        return (f"q={self.q},r={self.r},gate_sigma={self.gate_sigma},"
                f"a_plaus_max={self.a_plaus_max},fault_sigma={self.fault_sigma},"
                f"fault_n={self.fault_n},fault_r_mult={self.fault_r_mult}")


STACKED = {
    "S1_RobustAdaptiveKF": S1RobustBaroAdaptiveKF,
    "S2_DualTimescale": S2DualTimescale,
    "S3_AccelerationAwareKF": S3AccelerationAwareKF,
}
