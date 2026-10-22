#!/usr/bin/env python3
"""
04_filter_replay.py — T-008 replay harness (ADR-006/ADR-011 evidence).

Runs one recorded dataset through candidate vario estimators offline:
  A) LPF + derivative          — trivial baseline, shows why filtering matters
  B) CV-Kalman, baro-only      — 2-state [altitude, climb-rate] (ADR-006 baseline)
  C) CV-Kalman + accel fusion  — IMU-assisted (ADR-011: is fusion worth it?)

Metrics (all event-relative, not whole-run statistics — a run full of
motion makes percentile-based "rest" definitions meaningless, which is the
hard lesson baked into this design):
  - rest |v| RMS on TRUE rest samples (1-s-smoothed |v| < 0.05 everywhere)
  - per motion event (auto-detected |v| > 0.3 regions):
      onset latency  = est |v| first > 0.3  minus  event start
      release latency = est |v| last  > 0.3  minus  event end
  - overshoot: max |v| during event vs reference (smoothed-baru v)

Usage:
    python 04_filter_replay.py '*elevator*' --sid=1
    python 04_filter_replay.py '*step_drop*' --sid=1
"""
import sys

import matplotlib.pyplot as plt
import numpy as np

from common import altitude_m, find_run, load_run, pressure_series, run_name, savefig

G_STD = 9.80665


def resample_uniform(t, y, dt=0.01):
    tu = np.arange(t[0], t[-1], dt)
    return tu, np.interp(tu, t, y)


def lpf_derivative(t, alt, cutoff_hz=0.5):
    """Exponential LPF on altitude, analytic derivative of the filter."""
    dt = np.median(np.diff(t))
    rc = 1.0 / (2 * np.pi * cutoff_hz)
    a = dt / (rc + dt)
    alt_f = np.empty_like(alt)
    v = np.empty_like(alt)
    alt_f[0] = alt[0]
    v[0] = 0.0
    for i in range(1, len(alt)):
        alt_f[i] = alt_f[i - 1] + a * (alt[i] - alt_f[i - 1])
        v[i] = a * (alt[i] - alt_f[i - 1]) / dt
    return alt_f, v


def cv_kalman(t, z, q_h=0.05, q_v=0.5, r=None, u=None):
    """2-state constant-velocity Kalman. z = altitude [m], u = accel [m/s^2] or None.

    Process model: h' = v, v' = u + w. Treat q_*/r as the knobs this harness
    exists to sweep; defaults are a sane starting point for bench baro noise.
    """
    n = len(z)
    dt = np.median(np.diff(t))
    x = np.zeros((n, 2))
    P = np.eye(2) * 10.0
    F = np.array([[1, dt], [0, 1]])
    B = np.array([0.5 * dt ** 2, dt])
    Q = np.array([[q_h * dt ** 3 / 3, q_h * dt ** 2 / 2],
                  [q_h * dt ** 2 / 2, q_h * dt]])
    Q[1, 1] += q_v * dt
    if r is None:
        r = max(np.var(np.diff(z)) / (2 * dt ** 2), 0.01)  # rough auto-tune
    for i in range(1, n):
        xp = F @ x[i - 1] + (B * u[i - 1] if u is not None else 0)
        Pp = F @ P @ F.T + Q
        y = z[i] - xp[0]
        S = Pp[0, 0] + r
        K = Pp[:, 0] / S
        x[i] = xp + K * y
        P = (np.eye(2) - np.outer(K, [1, 0])) @ Pp
    return x[:, 0], x[:, 1]


def detect_events(t, v_ref, on=0.3, off=0.05, min_dur=0.4, gap=1.0):
    """Motion events from a reference climb-rate series.

    "on" where |v|>on, fill gaps < gap s, keep segments >= min_dur.
    Returns list of (t_start, t_end).
    """
    m = np.abs(v_ref) > on
    idx = np.where(m)[0]
    segs = []
    if not len(idx):
        return segs
    s = idx[0]
    prev = idx[0]
    for i in idx[1:]:
        if t[i] - t[prev] > gap:
            segs.append((s, prev))
            s = i
        prev = i
    segs.append((s, prev))
    return [(t[a], t[b]) for a, b in segs if t[b] - t[a] >= min_dur]


def smooth_v(t, alt, win_s=1.0):
    n = max(int(round(win_s / np.median(np.diff(t)))), 3)
    k = np.exp(-0.5 * (np.arange(-3 * n, 3 * n + 1) / n) ** 2)
    k /= k.sum()
    alt_s = np.convolve(alt, k, mode="same")
    return np.gradient(alt_s, t), alt_s


def evaluate(t, v_est, events, rest_mask, label):
    """Event-relative metrics for one estimator's climb-rate series."""
    v_rms = np.sqrt(np.mean(v_est[rest_mask] ** 2)) if rest_mask.any() else float("nan")
    lats, rels, peaks = [], [], []
    for (e0, e1) in events:
        i0 = np.searchsorted(t, e0 - 3.0)
        i1 = np.searchsorted(t, e1 + 1)
        win = np.abs(v_est[i0:i1]) > 0.3
        if not win.any():
            lats.append(np.nan)
            rels.append(np.nan)
        else:
            j = np.where(win)[0]
            lats.append(t[i0 + j[0]] - e0)
            rels.append(t[i0 + j[-1]] - e1)
        ev = (t >= e0) & (t <= e1)
        peaks.append(np.abs(v_est[ev]).max() if ev.any() else np.nan)
    def med(x):
        x = [v for v in x if v == v]
        return np.median(x) if x else float("nan")
    print(f"  {label:<26} rest {v_rms:.3f} m/s RMS | "
          f"onset {med(lats)*1000 if med(lats)==med(lats) else float('nan'):6.0f} ms | "
          f"release {med(rels)*1000 if med(rels)==med(rels) else float('nan'):6.0f} ms | "
          f"peak {med(peaks):.2f} m/s")
    return dict(label=label, v=v_est, v_rms=v_rms, lats=lats, rels=rels, peaks=peaks)


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*.csv"
    sid = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--sid=")), 0))
    csv_path = find_run(pattern)
    print(f"Run: {csv_path.name}  sid={sid}")
    df, meta = load_run(csv_path)
    t, p, _ = pressure_series(df, meta, sid)
    p0 = p[: max(int(10 / np.median(np.diff(t))), 100)].mean() if t[-1] > 10 else p.mean()
    alt = altitude_m(p, p0_pa=p0)

    tu, altu = resample_uniform(t, alt)
    dt = np.median(np.diff(tu))

    # reference climb rate (1 s smooth) for event detection + rest mask
    v_ref, _ = smooth_v(tu, altu, win_s=1.0)
    rest_mask = np.abs(v_ref) < 0.05
    events = detect_events(tu, v_ref)
    print(f"rest samples: {rest_mask.mean():.0%} | motion events: "
          f"{[(f'{a:.1f}', f'{b:.1f}') for a, b in events]}")

    print("Estimator comparison on identical data:")
    _, v_a = lpf_derivative(tu, altu, cutoff_hz=0.5)
    h_b, v_b = cv_kalman(tu, altu)
    results = [evaluate(tu, v_a, events, rest_mask, "A) LPF 0.5Hz + derivative")]
    results.append(evaluate(tu, v_b, events, rest_mask, "B) CV-Kalman baro-only"))

    u = None
    imu = df[df.type == "I"].dropna(subset=["ax"])
    has_imu = len(imu) > 100
    if has_imu:
        # Vertical accel = deviation of the accel axis closest to gravity
        # (auto-picked from rest means — the bench rig is mounted X-up, so a
        # hardcoded az would feed a HORIZONTAL axis into the fusion channel).
        n3 = max(int(3 / max(imu.t_s.diff().median(), 1e-3)), 10)
        rest_means = {c: np.median(imu[c].values[:n3]) for c in ("ax", "ay", "az")}
        vaxis = max(rest_means, key=lambda c: abs(rest_means[c]))
        a_raw = np.interp(tu, imu.t_s.values, imu[vaxis].values.astype(float))
        a_g = rest_means[vaxis]
        u = (a_raw - a_g) * G_STD / 16384.0
        print(f"IMU vertical axis: {vaxis} (rest {a_g:.0f} LSB = {a_g/16384:.3f} g)")
        h_c, v_c = cv_kalman(tu, altu, u=u)
        results.append(evaluate(tu, v_c, events, rest_mask, "C) Kalman + accel"))
    else:
        print("no IMU in run — estimator C skipped")

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(f"Estimator replay — {run_name(csv_path)} (sid {sid})")
    axes[0].plot(tu, altu, lw=0.4, color="#95a5a6", label="baro altitude (raw)")
    axes[0].plot(tu, h_b, lw=1.0, color="#1a5276", label="Kalman alt (B)")
    axes[0].set_ylabel("altitude [m]")
    axes[1].plot(tu, v_ref, lw=0.5, color="#d5d8dc", label="reference v (1s smooth)")
    axes[1].plot(tu, v_a, lw=0.7, color="#95a5a6", label="A) LPF+deriv")
    axes[1].plot(tu, v_b, lw=0.9, color="#1e8449", label="B) CV-Kalman baro")
    if has_imu:
        axes[1].plot(tu, v_c, lw=0.9, color="#c0392b", label="C) Kalman + accel")
    for e0, e1 in events:
        for ax in axes:
            ax.axvspan(e0, e1, color="#f9e79f", alpha=0.4)
    axes[1].set(xlabel="t [s]", ylabel="climb rate [m/s]")
    for ax in axes.flat:
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    savefig(fig, f"04_filter_replay_{run_name(csv_path)}.png")


if __name__ == "__main__":
    main()
