"""Group A — basic smoothing filters (task spec §4 Group A).

All windows/time constants are in SECONDS (physically equivalent across
sampling rates). A01–A04 operate on altitude; the estimate is the filter's
vertical-speed channel: for pure smoothers (SMA/median/Hampel) that is the
causal finite difference of the smoothed altitude over the actual elapsed
time between the newest and previous smoothed output — documented as a
deliberate, if crude, derivative (Group B exists for proper derivative
designs).
"""
from __future__ import annotations

import numpy as np

from .base import Filter


class TrailingBuffer:
    """(t, z) ring buffer with seconds-based retention."""

    def __init__(self, window_s: float):
        self.window_s = float(window_s)
        self.ts: list[float] = []
        self.zs: list[float] = []

    def push(self, t: float, z: float):
        self.ts.append(t)
        self.zs.append(z)
        cut = t - self.window_s
        i = 0
        while i < len(self.ts) and self.ts[i] < cut:
            i += 1
        if i:
            del self.ts[:i]
            del self.zs[:i]

    def arrays(self):
        return np.asarray(self.ts), np.asarray(self.zs)


class _SmoothedAlt(Filter):
    """Base for altitude smoothers: v from causal difference of smoothed h."""

    def _init_state(self):
        self._h = 0.0
        self._h_prev = None
        self._t_out_prev = None

    def _on_first(self, t, z):
        self._h = z
        self._h_prev = z
        self._t_out_prev = t

    def _smooth(self, t: float, z: float) -> float:
        raise NotImplementedError

    def _on_update(self, t, z, dt):
        h = self._smooth(t, z)
        span = t - self._t_out_prev
        if span > 0 and self._h_prev is not None:
            self._v = (h - self._h_prev) / span
        self._h_prev = h
        self._h = h
        self._t_out_prev = t
        return self._v


class A01SMA(_SmoothedAlt):
    """Trailing simple moving average, window in seconds."""

    name = "A01_SMA"

    def __init__(self, window_s: float = 1.0):
        self.window_s = float(window_s)
        super().__init__()

    def _init_state(self):
        super()._init_state()
        self.buf = TrailingBuffer(self.window_s)

    def _smooth(self, t, z):
        self.buf.push(t, z)
        return float(np.mean(self.buf.zs))

    def _config_repr(self):
        return f"window_s={self.window_s}"


class A02EMA(_SmoothedAlt):
    """Exponential moving average with time constant tau_s (variable-dt exact:
    alpha = 1 - exp(-dt/tau), so the parameterization is rate-independent)."""

    name = "A02_EMA"

    def __init__(self, tau_s: float = 1.0):
        self.tau_s = float(tau_s)
        super().__init__()

    def _on_first(self, t, z):
        super()._on_first(t, z)

    def _smooth(self, t, z):
        dt = t - self._t_out_prev
        a = 1.0 - np.exp(-dt / self.tau_s) if self.tau_s > 0 else 1.0
        return self._h + a * (z - self._h)

    def _config_repr(self):
        return f"tau_s={self.tau_s}"


class A03Holt(_SmoothedAlt):
    """Double exponential smoothing (Holt) with dt-scaled trend.
    level: l = alpha*z + (1-alpha)*(l + b*dt); trend: b = beta*(l-l_prev)/dt
    + (1-beta)*b. Estimate v = b [m/s]."""

    name = "A03_Holt"

    def __init__(self, alpha: float = 0.4, beta: float = 0.1):
        self.alpha = float(alpha)
        self.beta = float(beta)
        super().__init__()

    def _init_state(self):
        super()._init_state()
        self._l = None
        self._b = 0.0

    def _on_first(self, t, z):
        super()._on_first(t, z)
        self._l = z
        self._b = 0.0

    def _smooth(self, t, z):
        dt = t - self._t_out_prev
        l_pred = self._l + self._b * dt
        l_new = self.alpha * z + (1.0 - self.alpha) * l_pred
        self._b = self.beta * (l_new - self._l) / dt + (1.0 - self.beta) * self._b
        self._l = l_new
        return l_new

    def _on_update(self, t, z, dt):
        super()._on_update(t, z, dt)
        self._v = self._b
        return self._v

    def _config_repr(self):
        return f"alpha={self.alpha},beta={self.beta}"


class A04Median(_SmoothedAlt):
    """Trailing median filter, window in seconds."""

    name = "A04_Median"

    def __init__(self, window_s: float = 1.0):
        self.window_s = float(window_s)
        super().__init__()

    def _init_state(self):
        super()._init_state()
        self.buf = TrailingBuffer(self.window_s)

    def _smooth(self, t, z):
        self.buf.push(t, z)
        return float(np.median(self.buf.zs))

    def _config_repr(self):
        return f"window_s={self.window_s}"


class A05Hampel(_SmoothedAlt):
    """Hampel outlier filter: samples beyond n_sigma*MAD from the window
    median are counted as replaced (diagnostic); the filter OUTPUT is the
    trailing window median, so the velocity path is smoothed and spikes are
    fully absorbed. The newest sample after outlier replacement is kept in
    _last_clean for downstream adaptive filters (E06) that want the cleaned
    raw stream rather than the median."""

    name = "A05_Hampel"

    def __init__(self, window_s: float = 2.0, n_sigma: float = 3.0):
        self.window_s = float(window_s)
        self.n_sigma = float(n_sigma)
        super().__init__()

    def _init_state(self):
        super()._init_state()
        self.buf = TrailingBuffer(self.window_s)
        self.n_replaced = 0
        self._last_clean = None     # newest sample after outlier replacement

    def _smooth(self, t, z):
        self.buf.push(t, z)
        zs = np.asarray(self.buf.zs)
        med = float(np.median(zs))
        mad = float(np.median(np.abs(zs - med)) * 1.4826)   # consistent sigma
        zc = z
        if len(zs) >= 5 and mad > 0 and abs(z - med) > self.n_sigma * mad:
            self.n_replaced += 1
            zc = med
        self._last_clean = zc
        return med

    def _config_repr(self):
        return f"window_s={self.window_s},n_sigma={self.n_sigma}"


class A06RobustEMA(_SmoothedAlt):
    """A05 (Hampel) preprocessing feeding A02 (EMA): robust + smoothed."""

    name = "A06_RobustEMA"

    def __init__(self, window_s: float = 2.0, n_sigma: float = 3.0,
                 tau_s: float = 0.5):
        self.window_s = float(window_s)
        self.n_sigma = float(n_sigma)
        self.tau_s = float(tau_s)
        super().__init__()

    def _init_state(self):
        super()._init_state()
        self.buf = TrailingBuffer(self.window_s)
        self.n_replaced = 0

    def _smooth(self, t, z):
        self.buf.push(t, z)
        zs = np.asarray(self.buf.zs)
        med = np.median(zs)
        mad = np.median(np.abs(zs - med)) * 1.4826
        zr = z
        if len(zs) >= 5 and mad > 0 and abs(z - med) > self.n_sigma * mad:
            self.n_replaced += 1
            zr = float(med)
        dt = t - self._t_out_prev
        a = 1.0 - np.exp(-dt / self.tau_s) if self.tau_s > 0 else 1.0
        return self._h + a * (zr - self._h)

    def _config_repr(self):
        return (f"window_s={self.window_s},n_sigma={self.n_sigma},"
                f"tau_s={self.tau_s}")
