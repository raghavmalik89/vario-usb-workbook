"""Baro/IMU fusion interface (Phase 4 WP-C).

Purpose: define the timestamped barometer+IMU fusion contract and verify the
implementation against SYNTHETIC IMU streams only. No capture contains IMU
data (MPU6050 is probed at health-check but never streamed), so every number
produced from this module is SIMULATED and labelled as such. No real
sensor-fusion improvement is claimed anywhere in Phase 4.

Interface contract (the shape a real driver must feed):
  - update_baro(altitude_m, timestamp_s)  -> vertical-speed estimate [m/s]
  - update_imu(accel_body_m_s2, timestamp_s, quat=None)
        accel in the sensor body frame, 3-axis, m/s^2 (specific force);
        optional attitude quaternion (w, x, y, z) for gravity compensation;
        when attitude is absent the LAST known attitude is reused and the
        fusion marks itself orientation-stale.
  - outputs/flags: degraded (any auxiliary input stale/missing),
                   fault (baro innovation fault latch),
                   accel_bias (estimated 3-axis bias, body frame),
                   baro_only (True when no IMU has ever been seen).

Architecture: ASYNCHRONOUS IMU-predict / baro-correct. update_imu
propagates the state [h, v] with each accel sample between baro events
(proper coasting across baro gaps); update_baro corrects the propagated
state. With no IMU updates the propagation uses zero acceleration and the
estimator reduces to the plain CV Kalman used by the baro-only candidates
(verified in tests).

Design notes:
  - Earth frame is z-DOWN (aviation NED-ish): a stationary accelerometer
    reads specific force f = a - g = [0,0,-g] (z-down). Compensation
    recovers a_z = f_z + g: stationary -> 0, upward accel -> negative.
  - Acceleration bias is estimated only while the baro channel says the
    device is near stationary (|v_baro| below a threshold for a sustained
    window) AND the compensated residual is small (a large residual means
    the rest assumption is broken — folding it would integrate real motion
    into the bias). The baro channel is the only absolute reference
    available. The |v| threshold must tolerate the slow velocity drift an
    uncompensated bias itself induces (~the bias times the KF time
    constant); otherwise estimator and bias estimation deadlock. Constant
    slow climb is safe: sustained vertical ACCELERATION is what corrupts
    bias estimates, and a steady climb has ~zero vertical acceleration.
    The bias magnitude is sanity-clamped (default +/-2 m/s^2).
  - Timestamp jitter and sample gaps are handled by deriving every
    interval from physical timestamps; staleness flags trip when a
    sensor is silent beyond its documented timeout.
"""
from __future__ import annotations

import numpy as np

from filters.kalman import cv_model


def gravity_compensate(accel_body, quat):
    """Rotate body-frame specific force into the Earth frame (z-down) and
    remove gravity. Returns Earth-frame vertical acceleration a_z
    (m/s^2, +down). Stationary sensor -> ~0; accelerating upward -> negative.

    quat = (w, x, y, z) rotates BODY -> EARTH. f = R a_body; a_z = f_z + g."""
    w, x, y, z = quat
    R = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])
    f_earth = R @ np.asarray(accel_body, dtype=float)
    return float(f_earth[2] + 9.80665)


def _rot_z_from_quat(quat):
    """Third row of R(body->earth) — Earth-z axis expressed in body coords."""
    w, x, y, z = quat
    return np.array([2 * (x * z - w * y), 2 * (y * z + w * x),
                     1 - 2 * (x * x + y * y)])


class BaroImuFusion:
    """Timestamp-driven asynchronous baro/IMU complementary Kalman
    (state [h, v]). No heap, no global state, deterministic — the same
    discipline the portable C core (WP-D) implements."""

    G0 = 9.80665

    def __init__(self, q: float = 0.3, r: float = 0.035,
                 gate_sigma: float = 3.5,
                 imu_timeout_s: float = 0.25,
                 orient_timeout_s: float = 1.0,
                 bias_tau_s: float = 3.0,
                 rest_v_max: float = 0.5, rest_window_s: float = 1.0,
                 bias_abs_max: float = 2.0):
        self.q = float(q)
        self.r = float(r)
        self.gate_sigma = float(gate_sigma)
        self.imu_timeout_s = float(imu_timeout_s)
        self.orient_timeout_s = float(orient_timeout_s)
        self.bias_tau_s = float(bias_tau_s)
        self.rest_v_max = float(rest_v_max)
        self.rest_window_s = float(rest_window_s)
        self.bias_abs_max = float(bias_abs_max)
        self.reset()

    def reset(self):
        self._x = None                 # [h, v], propagated to _t_state
        self._P = None
        self._a_down = 0.0             # latest compensated vertical accel
        self._t_state = None           # state propagation time
        self._t_baro = None            # last baro-corrected time
        self._t_imu = None
        self._t_orient = None
        self._quat = (1.0, 0.0, 0.0, 0.0)
        self.accel_bias = np.zeros(3)
        self._rest_since = None
        self._fault_count = 0
        self.fault = False
        self.n_gated = 0
        self.n_reinit = 0
        self.baro_only = True

    # -- flags ----------------------------------------------------------------
    @property
    def degraded(self):
        """True when any auxiliary input is stale/missing."""
        if self._t_baro is None:
            return True
        if not self.baro_only and self._t_imu is not None:
            if self._t_baro - self._t_imu > self.imu_timeout_s:
                return True
        if self._t_orient is not None and \
                self._t_baro - self._t_orient > self.orient_timeout_s:
            return True
        return False

    # -- propagation -------------------------------------------------------------
    def _propagate(self, t):
        """Advance [h, v] to time t using the current accel (zero if the
        IMU path is silent). Idempotent per timestamp."""
        if self._x is None or self._t_state is None:
            return
        dt = float(t) - self._t_state
        if dt <= 0:
            return
        a = 0.0 if self.baro_only else self._a_down
        self._x = self._x + np.array(
            [self._x[1] * dt + 0.5 * a * dt * dt, a * dt])
        self._t_state = float(t)

    # -- IMU path ---------------------------------------------------------------
    def update_imu(self, accel_body, t, quat=None):
        """Feed one timestamped 3-axis accel sample (body frame)."""
        a = np.asarray(accel_body, dtype=float)
        self.baro_only = False
        self._propagate(t)                     # coast with the PREVIOUS accel
        if quat is not None:
            self._quat = tuple(float(v) for v in quat)
            self._t_orient = float(t)
        a_comp = gravity_compensate(a - self.accel_bias, self._quat)
        # bias estimation only while baro says near-stationary AND the
        # residual looks like a bias (small); else the rest assumption is
        # broken and folding would integrate real motion into the bias
        if (self._x is not None and abs(self._x[1]) < self.rest_v_max
                and abs(a_comp) < 1.0):
            if self._rest_since is None:
                self._rest_since = float(t)
            elif t - self._rest_since >= self.rest_window_s:
                dt = 0.0 if self._t_imu is None else float(t) - self._t_imu
                if dt > 0:
                    z_body = _rot_z_from_quat(self._quat)
                    self.accel_bias += z_body * a_comp * min(
                        dt / self.bias_tau_s, 1.0)
                    np.clip(self.accel_bias, -self.bias_abs_max,
                            self.bias_abs_max, out=self.accel_bias)
                    a_comp = gravity_compensate(a - self.accel_bias,
                                                self._quat)
        else:
            self._rest_since = None
        self._a_down = a_comp
        self._t_imu = float(t)
        return a_comp

    # -- baro path ---------------------------------------------------------------
    def update_baro(self, altitude_m, t):
        """Feed one timestamped baro altitude [m]; returns v estimate [m/s]."""
        z = float(altitude_m)
        t = float(t)
        if self._x is None:
            self._x = np.array([z, 0.0])
            self._P = np.diag([1.0, 1.0])
            self._t_state = t
            self._t_baro = t
            return 0.0
        dt = t - self._t_baro
        if dt <= 0:
            return float(self._x[1])
        self._propagate(t)                     # coast to the baro stamp
        Fm, H, Q, r = cv_model(dt, self.q, self.r)
        self._P = Fm @ self._P @ Fm.T + Q
        y = float(z - (H @ self._x)[0])
        S = float(self._P[0, 0] + r)
        sig = np.sqrt(S)
        # fault latch: persistent huge innovations -> loss of track. The
        # pre-Phase-5 behavior set a flag and kept coasting, which left v
        # frozen at a runaway value forever (measured [M]: one attitude
        # warm-up transient ran v to 14 m/s and the gate then rejected
        # every measurement for the whole session). Recovery = declared
        # reacquisition from the measurement, same as filter init.
        if abs(y) > 5.0 * sig:
            self._fault_count += 1
            if self._fault_count >= 8:
                self.fault = True
                self._fault_count = 0
                self.n_reinit += 1
                self._x = np.array([z, 0.0])
                self._P = np.diag([1.0, 1.0])
                self._t_state = t
                self._t_baro = t
                return float(self._x[1])
        else:
            self._fault_count = 0
            self.fault = False
        if abs(y) > self.gate_sigma * sig:
            self.n_gated += 1
            self._x = self._x.copy()           # prediction only
        else:
            K = (self._P @ H.T / S).ravel()
            self._x = self._x + K * y
            self._P = (np.eye(2) - np.outer(K, H)) @ self._P
        self._t_baro = t
        return float(self._x[1])
