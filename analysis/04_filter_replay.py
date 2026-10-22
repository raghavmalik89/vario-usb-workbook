#!/usr/bin/env python3
"""
04_filter_replay.py — T-008/T-005 replay harness (ADR-006 evidence).

Runs one recorded dataset through candidate vario estimators offline:
  A) LPF + derivative          — trivial baseline, shows why filtering matters
  B) CV-Kalman, baro-only      — 2-state [altitude, climb-rate] (ADR-006 baseline)
  C) CV-Kalman + accel fusion  — IMU-assisted (ADR-011 evidence: is fusion worth it?)

Reports for each: climb-rate noise at rest (false-cue metric), response time on
the biggest step, and plots all estimates together.

Usage:
    python 04_filter_replay.py '*elevator*' --sid 0
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
        # analytic derivative of the EMA: d(y)/dt = a * (x - y_prev) / dt
        v[i] = a * (alt[i] - alt_f[i - 1]) / dt
    return alt_f, v


def cv_kalman(t, z, q_h=0.05, q_v=0.5, r=None, u=None):
    """2-state constant-velocity Kalman. z = altitude [m], u = accel [m/s^2] or None.

    Process model: h' = v, v' = u + w. Tuned here for baro noise levels —
    treat q_*/r as the knobs this harness exists to sweep.
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


def metrics(t, v, label):
    rest = np.abs(v) < np.percentile(np.abs(v), 60)  # dominant-quantile = rest-ish
    v_rms = np.sqrt(np.mean(v[rest] ** 2))
    ai = np.argmax(np.abs(v))
    print(f"  {label:<28} rest |v| {v_rms:.3f} m/s RMS, "
          f"peak {v[ai]:+.2f} m/s @ {t[ai]:.1f}s")
    return v_rms


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*.csv"
    sid = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--sid=")), 0))
    csv_path = find_run(pattern)
    print(f"Run: {csv_path.name}  sid={sid}")
    df, meta = load_run(csv_path)
    t, p, _ = pressure_series(df, meta, sid)
    p0 = p[: max(int(10 / np.median(np.diff(t))), 100)].mean() if t[-1] > 10 else p.mean()
    alt = altitude_m(p, p0=p0)

    tu, altu = resample_uniform(t, alt)
    dt = np.median(np.diff(tu))

    print("Estimator comparison on identical data:")
    _, v_a = lpf_derivative(tu, altu, cutoff_hz=0.5)
    h_b, v_b = cv_kalman(tu, altu)

    u = None
    imu = df[df.type == "I"].dropna(subset=["ax"])
    has_imu = len(imu) > 100
    if has_imu:
        # accel magnitude minus gravity, projected to "vertical-ish": use az deviation
        az = np.interp(tu, imu.t_s.values, imu.az.values.astype(float))
        az_g = np.median(az[: int(3 / dt)])           # rest bias incl. orientation
        u = (az - az_g) * G_STD / 16384.0             # raw LSB -> m/s^2
        h_c, v_c = cv_kalman(tu, altu, u=u)
        metrics(tu, v_a, "A) LPF 0.5Hz + derivative")
        metrics(tu, v_b, "B) CV-Kalman baro-only")
        metrics(tu, v_c, "C) CV-Kalman + accel")

        # onset-lead: accel crosses 0.5 m/s^2 before baro-derived v crosses 0.3 m/s
        a_onset = tu[np.argmax(np.abs(u) > 0.5)] if np.any(np.abs(u) > 0.5) else None
        v_onset = tu[np.argmax(np.abs(v_b) > 0.3)] if np.any(np.abs(v_b) > 0.3) else None
        if a_onset is not None and v_onset is not None:
            print(f"\nFusion lead: accel onset {a_onset:.2f}s, baro-Kalman onset "
                  f"{v_onset:.2f}s -> IMU lead {1000*(v_onset-a_onset):+.0f} ms")
            print("(negative = accel reacts first, i.e. fusion value)")
    else:
        metrics(tu, v_a, "A) LPF 0.5Hz + derivative")
        metrics(tu, v_b, "B) CV-Kalman baro-only")
        print("no IMU in run — estimator C skipped")

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(f"Estimator replay — {run_name(csv_path)} (sid {sid})")
    axes[0].plot(tu, altu, lw=0.4, color="#95a5a6", label="baro altitude (raw)")
    axes[0].plot(tu, h_b, lw=1.0, color="#1a5276", label="Kalman alt (B)")
    axes[0].set_ylabel("altitude [m]")
    axes[1].plot(tu, v_a, lw=0.7, color="#95a5a6", label="A) LPF+deriv")
    axes[1].plot(tu, v_b, lw=0.9, color="#1e8449", label="B) CV-Kalman baro")
    if has_imu:
        axes[1].plot(tu, v_c, lw=0.9, color="#c0392b", label="C) Kalman + accel")
    axes[1].set(xlabel="t [s]", ylabel="climb rate [m/s]")
    for ax in axes.flat:
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    savefig(fig, f"04_filter_replay_{run_name(csv_path)}.png")


if __name__ == "__main__":
    main()
