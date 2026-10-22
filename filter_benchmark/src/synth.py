"""Synthetic input sequences (task spec §6C) — reproducible, seeded.

Used by tests and by the synthetic characterization runs. These characterize
filter MATHEMATICS only; they never prove sensor or flight performance.
"""
from __future__ import annotations

import numpy as np


def constant_altitude(t, h0=0.0, rng=None, noise_m=0.0):
    z = np.full_like(t, h0)
    if noise_m and rng is not None:
        z += rng.normal(0, noise_m, len(t))
    return z


def constant_climb(t, v=1.0, h0=0.0, rng=None, noise_m=0.0):
    z = h0 + v * t
    if noise_m and rng is not None:
        z += rng.normal(0, noise_m, len(t))
    return z


def step_velocity(t, v0=0.0, v1=1.0, t_step=5.0, h0=0.0, rng=None, noise_m=0.0):
    v = np.where(t >= t_step, v1, v0)
    z = h0 + np.cumsum(v) * np.median(np.diff(t))
    if noise_m and rng is not None:
        z += rng.normal(0, noise_m, len(t))
    return z


def lift_pulse(t, v=1.0, t_on=5.0, dur=2.0, h0=0.0, ramp=0.2):
    """Short-duration lift pulse with linear ramps (the release-latency case)."""
    dt = np.median(np.diff(t))
    z = np.zeros_like(t)
    phase, rem = 0, 0.0
    for i, ti in enumerate(t):
        if ti < t_on or ti > t_on + dur + 2 * ramp:
            vel = 0.0
        elif ti < t_on + ramp:
            vel = v * (ti - t_on) / ramp
        elif ti < t_on + ramp + dur:
            vel = v
        else:
            vel = v * max(0.0, 1 - (ti - t_on - ramp - dur) / ramp)
        rem += vel * dt
        z[i] = h0 + rem
    return z


def noise_burst(t, t_burst=5.0, dur=1.0, sigma=0.5, rng=None):
    z = np.zeros_like(t)
    m = (t >= t_burst) & (t < t_burst + dur)
    z[m] += (rng.normal(0, sigma, int(m.sum())) if rng is not None else 0)
    return z


def pressure_spike(t, t_spike=5.0, magnitude_m=5.0, width_s=0.05):
    """Positive altitude spike (drop-like pressure event)."""
    z = np.zeros_like(t)
    m = (t >= t_spike) & (t < t_spike + width_s)
    z[m] += magnitude_m
    return z


def irregular_timestamps(t, jitter_s=0.002, rng=None):
    t2 = t + rng.uniform(-jitter_s, jitter_s, len(t))
    return np.maximum.accumulate(t2)


def missing_samples(t, drop_every=50, rng=None):
    keep = np.ones(len(t), dtype=bool)
    keep[::drop_every] = False
    return t[keep]
