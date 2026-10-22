"""Group E — adaptive and multi-timescale estimators (spec §4 Group E).

E01 One-Euro (on altitude; derivative from the filtered signal).
E02 EMA with data-dependent time constant: tau_eff = tau0 / (1 + (|v|/v0)^2)
    — faster when the signal moves (documented form, v from a fast EMA).
E03 Fast/slow parallel EMAs with disagreement switch (hysteresis via
    switch_hold_s — no chattering at the boundary).
E04 Innovation-based blending: a slow CV Kalman provides normalized
    innovation power that blends fast/slow EMA outputs.
E05 Change detection (CUSUM on altitude increments vs slow baseline)
    assists switching to the fast branch for a hold time after a detected
    change.
E06 Hampel preprocessing + D04 adaptive-R Kalman (robust + adaptive).
"""
from __future__ import annotations

import numpy as np

from .base import Filter
from .kalman import D04KalmanAdaptiveR
from .smoothing import A02EMA, A05Hampel


def _alpha(dt, cutoff_hz):
    tau = 1.0 / (2.0 * np.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt) if tau > 0 else 1.0


class E01OneEuro(Filter):
    name = "E01_OneEuro"

    def __init__(self, min_cutoff_hz: float = 0.5, beta: float = 1.0,
                 d_cutoff_hz: float = 1.0):
        self.min_cutoff_hz = float(min_cutoff_hz)
        self.beta = float(beta)
        self.d_cutoff_hz = float(d_cutoff_hz)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._dx = 0.0
        self._x_prev = None

    def _on_first(self, t, z):
        self._h = z
        self._x_prev = z

    def _on_update(self, t, z, dt):
        dx = (z - self._x_prev) / dt
        a_d = _alpha(dt, self.d_cutoff_hz)
        dx_hat = a_d * dx + (1 - a_d) * self._dx
        cutoff = self.min_cutoff_hz + self.beta * abs(dx_hat)
        a = _alpha(dt, cutoff)
        x_hat = a * z + (1 - a) * self._h
        self._v = (x_hat - self._h) / dt
        self._h = x_hat
        self._dx = dx_hat
        self._x_prev = z
        return self._v

    def _config_repr(self):
        return f"min_cutoff_hz={self.min_cutoff_hz},beta={self.beta}"


class E02AdaptiveEMA(Filter):
    name = "E02_AdaptiveEMA"

    def __init__(self, tau0_s: float = 1.0, v0: float = 0.5, tau_min_s: float = 0.1):
        self.tau0_s = float(tau0_s)
        self.v0 = float(v0)
        self.tau_min_s = float(tau_min_s)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._vf = 0.0
        self._hf = 0.0
        self._t_out_prev = None

    def _on_first(self, t, z):
        self._h = z
        self._hf = z
        self._t_out_prev = t

    def _on_update(self, t, z, dt):
        # fast EMA tracks motion to set the time constant (documented form)
        a_f = 1.0 - np.exp(-dt / max(self.tau_min_s, 1e-3))
        hf_new = self._hf + a_f * (z - self._hf)
        vf = (hf_new - self._hf) / dt
        self._hf = hf_new
        tau_eff = max(self.tau_min_s,
                      self.tau0_s / (1.0 + (abs(vf) / self.v0) ** 2))
        dt_out = t - self._t_out_prev
        a = 1.0 - np.exp(-dt_out / tau_eff) if tau_eff > 0 else 1.0
        h_new = self._h + a * (z - self._h)
        self._v = (h_new - self._h) / dt_out
        self._h = h_new
        self._t_out_prev = t
        return self._v

    def _config_repr(self):
        return f"tau0_s={self.tau0_s},v0={self.v0},tau_min_s={self.tau_min_s}"


class _FastSlowBase(Filter):
    """Shared fast/slow machinery. Subclasses set self._v_fast/_v_slow each
    update via the branch filters; combination policy differs per filter."""

    def __init__(self, tau_fast_s: float = 0.2, tau_slow_s: float = 1.5):
        self.tau_fast_s = float(tau_fast_s)
        self.tau_slow_s = float(tau_slow_s)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self._fast = A02EMA(self.tau_fast_s)
        self._slow = A02EMA(self.tau_slow_s)
        self._use_fast = False

    def _branch(self, t, z, dt):
        self._fast.update(z, t)
        self._slow.update(z, t)
        return self._fast.get_estimate(), self._slow.get_estimate()

    def _on_first(self, t, z):
        self._h = z
        self._fast.update(z, t)
        self._slow.update(z, t)

    def _config_repr(self):
        return f"tau_fast={self.tau_fast_s},tau_slow={self.tau_slow_s}"


class E03FastSlowSwitch(_FastSlowBase):
    """Output = slow; when |v_fast - v_slow| > thresh, switch to fast and
    HOLD for switch_hold_s (hysteresis by dwell time, not amplitude)."""
    name = "E03_FastSlow"

    def __init__(self, tau_fast_s: float = 0.2, tau_slow_s: float = 1.5,
                 thresh: float = 0.3, switch_hold_s: float = 1.0):
        self.thresh = float(thresh)
        self.switch_hold_s = float(switch_hold_s)
        super().__init__(tau_fast_s, tau_slow_s)

    def _init_state(self):
        super()._init_state()
        self._hold_until = None

    def _on_update(self, t, z, dt):
        vf, vs = self._branch(t, z, dt)
        if abs(vf - vs) > self.thresh:
            self._use_fast = True
            self._hold_until = t + self.switch_hold_s
        elif self._hold_until is not None and t > self._hold_until:
            self._use_fast = False
        return vf if self._use_fast else vs

    def _config_repr(self):
        return (f"tau_fast_s={self.tau_fast_s},tau_slow_s={self.tau_slow_s},"
                f"thresh={self.thresh},switch_hold_s={self.switch_hold_s}")


class E04InnovationBlend(_FastSlowBase):
    """Blend fast/slow by normalized innovation power of a slow adaptive
    Kalman: w = S/(S+C) with S = trailing E[y^2]; v = (1-w)*slow + w*fast."""
    name = "E04_InnovationBlend"

    def __init__(self, tau_fast_s: float = 0.2, tau_slow_s: float = 1.5,
                 window_s: float = 3.0, blend_c: float = 0.05):
        self.window_s = float(window_s)
        self.blend_c = float(blend_c)
        super().__init__(tau_fast_s, tau_slow_s)

    def _init_state(self):
        super()._init_state()
        self._kf = D04KalmanAdaptiveR(q=0.5, r=0.035, window_s=self.window_s)
        self._y2 = _Y2Window(self.window_s)

    def _on_update(self, t, z, dt):
        vf, vs = self._branch(t, z, dt)
        # innovation against the slow Kalman's one-step PREDICTION
        h_pred = self._kf.get_altitude() + self._kf.get_estimate() * dt
        self._kf.update(z, t)
        y = z - h_pred
        self._y2.push(t, y)
        s = self._y2.mean()
        w = s / (s + self.blend_c) if s is not None else 0.0
        w = float(np.clip(w, 0.0, 1.0))
        return (1.0 - w) * vs + w * vf

    def _config_repr(self):
        return (f"tau_fast_s={self.tau_fast_s},tau_slow_s={self.tau_slow_s},"
                f"blend_c={self.blend_c}")


class _Y2Window:
    def __init__(self, window_s):
        self.window_s = float(window_s)
        self.items = []

    def push(self, t, y):
        self.items.append((t, y * y))
        cut = t - self.window_s
        i = 0
        while i < len(self.items) and self.items[i][0] < cut:
            i += 1
        if i:
            del self.items[:i]

    def mean(self):
        if len(self.items) < 5:
            return None
        return float(np.mean([y2 for _, y2 in self.items]))


class E05ChangeDetect(_FastSlowBase):
    """CUSUM on altitude increments (positive or negative) against a slowly
    drifting baseline; on alarm, use fast branch for alarm_hold_s."""
    name = "E05_ChangeDetect"

    def __init__(self, tau_fast_s: float = 0.2, tau_slow_s: float = 1.5,
                 cusum_threshold_m: float = 0.5, alarm_hold_s: float = 1.5,
                 slack_m: float = 0.05):
        self.cusum_threshold_m = float(cusum_threshold_m)
        self.alarm_hold_s = float(alarm_hold_s)
        self.slack_m = float(slack_m)
        super().__init__(tau_fast_s, tau_slow_s)

    def _init_state(self):
        super()._init_state()
        self._baseline = A02EMA(5.0)
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        self._alarm_until = None

    def _on_first(self, t, z):
        super()._on_first(t, z)
        self._baseline.update(z, t)

    def _on_update(self, t, z, dt):
        vf, vs = self._branch(t, z, dt)
        base_prev = self._baseline.get_altitude() or z
        self._baseline.update(z, t)
        inc = (z - base_prev)
        self._cusum_pos = max(0.0, self._cusum_pos + inc - self.slack_m)
        self._cusum_neg = max(0.0, self._cusum_neg - inc - self.slack_m)
        if (self._cusum_pos > self.cusum_threshold_m or
                self._cusum_neg > self.cusum_threshold_m):
            self._alarm_until = t + self.alarm_hold_s
            self._cusum_pos = self._cusum_neg = 0.0
        if self._alarm_until is not None and t <= self._alarm_until:
            return vf
        return vs

    def _config_repr(self):
        return (f"tau_fast_s={self.tau_fast_s},tau_slow_s={self.tau_slow_s},"
                f"cusum_threshold_m={self.cusum_threshold_m},alarm_hold_s={self.alarm_hold_s}")


class E06RobustAdaptive(Filter):
    """Hampel preprocessing -> D04 adaptive-R Kalman. Elevation outliers are
    replaced by the window median BEFORE the adaptive tracker sees them."""
    name = "E06_RobustAdapt"

    def __init__(self, window_s: float = 2.0, n_sigma: float = 3.0,
                 q: float = 1.0, r: float = 0.035):
        self.window_s = float(window_s)
        self.n_sigma = float(n_sigma)
        self.q = float(q)
        self.r = float(r)
        super().__init__()

    def _init_state(self):
        self._hampel = A05Hampel(self.window_s, self.n_sigma)
        self._kf = D04KalmanAdaptiveR(q=self.q, r=self.r)
        self._h = 0.0

    def _on_first(self, t, z):
        self._hampel.update(z, t)
        self._kf.update(z, t)
        self._h = self._kf.get_altitude()

    def _on_update(self, t, z, dt):
        self._hampel.update(z, t)
        zr = getattr(self._hampel, "_last_clean", z)   # Hampeled sample
        self._kf.update(zr, t)
        self._h = self._kf.get_altitude()
        return self._kf.get_estimate()

    def _config_repr(self):
        return f"window_s={self.window_s},n_sigma={self.n_sigma},q={self.q}"
