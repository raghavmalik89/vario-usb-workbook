"""Baselines B00–B03 (task spec §3).

B00: consecutive altitude difference / actual elapsed time.
B01: trailing-window linear regression slope of altitude vs time.
B02: the documented existing project estimator — the 2-state CV Kalman as
    implemented in analysis/04_filter_replay.py (cv_kalman), reproduced here
    via D01 with the legacy q_h/q_v parameterization and auto-R. This is the
    ADR-006/ADR-011 baseline the whole bench history compares against.
B03: reference variometer output — UNAVAILABLE: no recording contains a
    reference vario channel. Recorded as an explicit unavailable row in
    every results table; never fabricated.
"""
from __future__ import annotations

import numpy as np

from .base import Filter
from .classical import B05LSSlope
from .kalman import D01KalmanCV
from .smoothing import TrailingBuffer


class B00Diff(Filter):
    """v = (z_k - z_{k-1}) / (t_k - t_{k-1}) on actual elapsed time."""
    name = "B00_diff"

    def _init_state(self):
        self._h = 0.0
        self._z_prev = None

    def _on_first(self, t, z):
        self._h = z
        self._z_prev = z

    def _on_update(self, t, z, dt):
        v = (z - self._z_prev) / dt
        self._z_prev = z
        self._h = z
        return v


class B01Regression(Filter):
    """Trailing least-squares line slope over window_s (spec §3 B01)."""
    name = "B01_regression"

    def __init__(self, window_s: float = 1.0):
        self.window_s = float(window_s)
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
        if len(zs) < 3:
            return self._v
        # slope of line fit, evaluated with t relative to window end for
        # numerical conditioning
        u = ts - ts[-1]
        A = np.vstack([u, np.ones_like(u)]).T
        coef, *_ = np.linalg.lstsq(A, zs, rcond=None)
        self._h = z
        return float(coef[0])

    def _config_repr(self):
        return f"window_s={self.window_s}"


def B02_project_estimator():
    """Factory: the exact T-008 project estimator (04_filter_replay.cv_kalman
    defaults: q_h=0.05, q_v=0.5, auto-R over first samples)."""
    return D01KalmanCV(q_h=0.05, q_v=0.5, auto_r=True, warmup_s=3.0)


class B03ReferenceVario:
    """Placeholder documenting the UNAVAILABLE reference-vario channel.
    Any attempt to use it raises — B03 is reported as a row of N/A in every
    table, per spec (do not fabricate missing channels)."""
    name = "B03_reference_vario_UNAVAILABLE"

    def __init__(self):
        raise NotImplementedError(
            "B03 unavailable: no recording contains a reference vario output "
            "(dataset_inventory.md, reference_channels). Do not fabricate.")
