"""Group B — classical causal filters (task spec §4 Group B).

B01: first-order low-pass (exponential, tau in seconds); v is the analytic
derivative of the filter state (same construction as the T-008 LPF baseline).
B02/B03: second-order low-pass via Tustin-discretized analog prototypes
(Butterworth / Bessel), refit when dt changes >2% so 45/50 Hz and 100 Hz
sessions share one physical cutoff. B04: trailing Savitzky-Golay derivative
(polynomial least squares over past samples only). B05: sliding-window
polynomial least-squares slope (order selectable; order 1 is the line-fit
family of spec-§3 baseline B01-of-baselines).

No filtfilt, no centered windows, no future samples anywhere in this module.
"""
from __future__ import annotations

import numpy as np

from .base import DT_RECOMP_TOLERANCE, Filter
from .smoothing import TrailingBuffer

_TWO_PI = 2.0 * np.pi

# z-descending kernels for (z-1)^i (z+1)^(2-i), i = 0..2
_Z = (np.array([1.0, 2.0, 1.0]),    # (z+1)^2
      np.array([1.0, 0.0, -1.0]),   # (z-1)(z+1)
      np.array([1.0, -2.0, 1.0]))   # (z-1)^2


def biquad_tustin(num, den, dt, wc):
    """Tustin discretization of analog H(s)=num(s)/den(s), cutoff wc [rad/s].
    num/den are ascending-power coefficient arrays of degree <= 2.
    Returns (b0,b1,b2,a1,a2) for y[n] = b0 x + b1 x1 + b2 x2 - a1 y1 - a2 y2.
    Prewarping at wc keeps the cutoff physically exact at the given dt."""
    wd = 2.0 / dt * np.tan(wc * dt / 2.0)
    n = len(num) - 1
    d = len(den) - 1
    numz = np.zeros(3)
    denz = np.zeros(3)
    for i, c in enumerate(num):        # term c * (wd(z-1))^i * (z+1)^(d-i)
        numz += c * wd ** i * _kern(i, d - i)
    for i, c in enumerate(den):
        denz += c * wd ** i * _kern(i, d - i)
    a0 = denz[0]
    denz /= a0
    numz /= a0
    return numz[0], numz[1], numz[2], denz[1], denz[2]


def _kern(i_raised, k_plus):
    """Coefficients of (z-1)^i * (z+1)^k, z-descending, length 3.
    Valid for total degree i+k = 2 (biquad designs only)."""
    if i_raised == 0 and k_plus == 2:
        return _Z[0]
    if i_raised == 1 and k_plus == 1:
        return _Z[1]
    if i_raised == 2 and k_plus == 0:
        return _Z[2]
    raise ValueError(f"unexpected (i,k)=({i_raised},{k_plus})")


class B01LowPass1(Filter):
    name = "B01_LP1"

    def __init__(self, tau_s: float = 0.5):
        self.tau_s = float(tau_s)
        super().__init__()

    def _init_state(self):
        self._h = 0.0

    def _on_first(self, t, z):
        self._h = z

    def _on_update(self, t, z, dt):
        a = dt / (self.tau_s + dt)
        v = a * (z - self._h) / dt
        self._h += a * (z - self._h)
        return v

    def _config_repr(self):
        return f"tau_s={self.tau_s}"


class _Analog2LP(Filter):
    def __init__(self, cutoff_hz: float = 0.5):
        self.cutoff_hz = float(cutoff_hz)
        super().__init__()

    def _prototype(self):
        raise NotImplementedError

    def _init_state(self):
        self._h = 0.0
        self._x1 = self._x2 = 0.0
        self._y1 = self._y2 = 0.0
        self._t1 = self._t2 = None
        self._dt_fit = None

    def _on_first(self, t, z):
        self._h = z

    def _refit(self, dt):
        num, den = self._prototype()
        self._b0, self._b1, self._b2, self._a1, self._a2 = biquad_tustin(
            num, den, dt, _TWO_PI * self.cutoff_hz)
        self._dt_fit = dt

    def _on_update(self, t, z, dt):
        if self._dt_fit is None or abs(dt - self._dt_fit) / self._dt_fit > DT_RECOMP_TOLERANCE:
            self._refit(dt)
        y = (self._b0 * z + self._b1 * self._x1 + self._b2 * self._x2
             - self._a1 * self._y1 - self._a2 * self._y2)
        # velocity BEFORE shifting state: true 2-point-back difference over
        # the actual elapsed physical time (robust to irregular dt)
        if self._t2 is not None and t > self._t2:
            v = (y - self._y2) / (t - self._t2)
        else:
            v = 0.0
        self._x2, self._x1 = self._x1, z
        self._y2, self._y1 = self._y1, y
        self._t2, self._t1 = self._t1, t
        self._h = y
        return v

    def _config_repr(self):
        return f"cutoff_hz={self.cutoff_hz}"


class B02Butter2(_Analog2LP):
    """Second-order Butterworth low-pass; analog 1/(s^2 + sqrt(2) s + 1)."""
    name = "B02_Butter2"

    def _prototype(self):
        return np.array([1.0]), np.array([1.0, np.sqrt(2.0), 1.0])


class B03Bessel2(_Analog2LP):
    """Second-order Bessel low-pass; analog 3/(s^2 + 3 s + 3) (unit DC gain)."""
    name = "B03_Bessel2"

    def _prototype(self):
        # ascending powers of s: 3 / (3 + 3s + s^2), DC gain 1
        return np.array([3.0]), np.array([3.0, 3.0, 1.0])


def _poly_slope(ts, zs, order):
    """Least-squares polynomial slope (m/s) at the newest sample."""
    if len(zs) < order + 2:
        return None
    u = ts - ts[-1]                              # seconds, <= 0 (causal)
    A = np.vander(u, order + 1, increasing=True)
    coef, *_ = np.linalg.lstsq(A, zs, rcond=None)
    return float(coef[1])


class B04SavGol(Filter):
    """Trailing Savitzky-Golay derivative: LS polynomial of given order over
    the trailing window (seconds); v = slope at the newest sample."""
    name = "B04_SavGol"

    def __init__(self, window_s: float = 1.0, order: int = 2):
        self.window_s = float(window_s)
        self.order = int(order)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self.buf = TrailingBuffer(self.window_s)

    def _on_first(self, t, z):
        self._h = z
        self.buf.push(t, z)

    def _on_update(self, t, z, dt):
        self.buf.push(t, z)
        ts, zs = self.buf.arrays()
        s = _poly_slope(ts, zs, self.order)
        self._h = z
        return self._v if s is None else s

    def _config_repr(self):
        return f"window_s={self.window_s},order={self.order}"


class B05LSSlope(Filter):
    """Sliding-window polynomial least-squares slope (order 1 = line fit)."""
    name = "B05_LS_slope"

    def __init__(self, window_s: float = 1.0, order: int = 1):
        self.window_s = float(window_s)
        self.order = int(order)
        super().__init__()

    def _init_state(self):
        self._h = 0.0
        self.buf = TrailingBuffer(self.window_s)

    def _on_first(self, t, z):
        self._h = z
        self.buf.push(t, z)

    def _on_update(self, t, z, dt):
        self.buf.push(t, z)
        ts, zs = self.buf.arrays()
        s = _poly_slope(ts, zs, self.order)
        self._h = z
        return self._v if s is None else s

    def _config_repr(self):
        return f"window_s={self.window_s},order={self.order}"
