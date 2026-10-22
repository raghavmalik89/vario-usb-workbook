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
  - R-2 release metrics (research T-002, per event):
      rel@lift-off = est |v| last > +0.05 m/s  minus  event end
                     (the lift-off threshold — the number that matters for
                     "how long after leaving lift does the vario shut up")
      fall 90->10  = time for est |v| to decay from 90% to 10% of its
                     in-window peak after the peak (ring-down sharpness)
  - per-signal-strength table: events binned by reference peak
    (weak <0.6 / mid 0.6-1.5 / strong >=1.5 m/s) — research requires
    onset/release to be reported PER STRENGTH, not just overall medians
  - overshoot: max |v| during event vs reference (smoothed-baru v)

Usage:
    python 04_filter_replay.py '*elevator*' --sid=1
    python 04_filter_replay.py '*step_drop*' --sid=1
    python 04_filter_replay.py '*t005_elevator*' --sid=0 --off=0.05

Caveat (from T-008, still true): onset/release are measured against the
1-s-smoothed reference crossings, so fast estimators can show negative
onset on sharp events. Compare like with like; trust the RELATIVE ordering
between estimators on the same events, not the absolute sign.
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


def evaluate(t, v_est, events, rest_mask, label, v_ref=None, rel_off=0.05):
    """Event-relative metrics for one estimator's climb-rate series.

    Per event (see module docstring for definitions):
      onset / release at the 0.3 strong-motion threshold (existing T-008),
      rel_off at the lift-off threshold (R-2), fall 90->10 ring-down time
      (R-2).  Everything is stored per-event so main() can bin by the
      reference peak (signal strength).
    """
    v_rms = np.sqrt(np.mean(v_est[rest_mask] ** 2)) if rest_mask.any() else float("nan")
    per_event = []
    for (e0, e1) in events:
        # onset / release at the 0.3 "strong motion" threshold (existing window)
        i0 = np.searchsorted(t, e0 - 3.0)
        i1 = np.searchsorted(t, e1 + 1)
        win = np.abs(v_est[i0:i1]) > 0.3
        onset = rel = float("nan")
        if win.any():
            j = np.where(win)[0]
            onset = t[i0 + j[0]] - e0
            rel = t[i0 + j[-1]] - e1
        # R-2 release window: event end + 2 s of ring-down, lift-off threshold
        w0 = np.searchsorted(t, e0)
        w1 = np.searchsorted(t, e1 + 2.0)
        tw = t[w0:w1]
        vw = v_est[w0:w1]
        rel5 = fall = float("nan")
        if len(vw):
            above = np.where(np.abs(vw) > rel_off)[0]
            if len(above):
                rel5 = tw[above[-1]] - e1
            ipk = int(np.argmax(np.abs(vw)))
            peak = abs(vw[ipk])
            if peak >= 0.1:
                tail = np.abs(vw[ipk:])
                b90 = np.where(tail <= 0.9 * peak)[0]
                b10 = np.where(tail <= 0.1 * peak)[0]
                if len(b90) and len(b10):
                    fall = tw[ipk + b10[0]] - tw[ipk + b90[0]]
        ev = (t >= e0) & (t <= e1)
        pk_est = np.abs(v_est[ev]).max() if ev.any() else float("nan")
        pk_ref = float("nan")
        if v_ref is not None and ev.any():
            pk_ref = np.abs(v_ref[ev]).max()
        per_event.append(dict(t0=e0, t1=e1, peak_ref=pk_ref, onset=onset,
                              rel=rel, rel_off=rel5, fall=fall, peak=pk_est))

    def med(key):
        xs = [p[key] for p in per_event if p[key] == p[key]]
        return np.median(xs) if xs else float("nan")

    def ms(v):
        return f"{v * 1000:6.0f}" if v == v else "   nan"

    print(f"  {label:<26} rest {v_rms:.3f} m/s RMS | "
          f"onset {ms(med('onset'))} ms | release {ms(med('rel'))} ms | "
          f"rel@0.05 {ms(med('rel_off'))} ms | fall90-10 {ms(med('fall'))} ms | "
          f"peak {med('peak'):.2f} m/s")
    return dict(label=label, v=v_est, v_rms=v_rms, per_event=per_event)


STRENGTH_BINS = [(0.6, "weak (<0.6)"), (1.5, "mid (0.6-1.5)"),
                 (float("inf"), "strong (>=1.5)")]


def strength_bin(peak):
    if peak != peak:
        return None
    for lim, name in STRENGTH_BINS:
        if peak < lim:
            return name
    return None


def print_strength_table(results):
    """Onset / rel@lift-off / fall per signal strength (research requirement).

    One row per estimator, columns per metric, cells ordered
    weak / mid / strong.
    """
    print("\nPer signal strength (events binned by reference peak), ms:")
    print(f"    {'estimator':<26} | {'metric':<12} | "
          f"{'weak (<0.6)':>12} | {'mid (0.6-1.5)':>12} | {'strong (>=1.5)':>12}")
    for r in results:
        first = True
        for key, title in (("onset", "onset"), ("rel_off", "rel@0.05"),
                           ("fall", "fall90-10")):
            cells = []
            for _, bname in STRENGTH_BINS:
                xs = [p[key] for p in r["per_event"]
                      if strength_bin(p["peak_ref"]) == bname and p[key] == p[key]]
                cells.append(f"{np.median(xs) * 1000:12.0f}" if xs else f"{'nan':>12}")
            print(f"    {(r['label'] if first else ''):<26} | {title:<12} | "
                  + " | ".join(cells))
            first = False


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*.csv"
    sid = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--sid=")), 0))
    rel_off = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--off=")),
                         0.05))
    csv_path = find_run(pattern)
    print(f"Run: {csv_path.name}  sid={sid}  lift-off threshold={rel_off} m/s")
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
    results = [evaluate(tu, v_a, events, rest_mask, "A) LPF 0.5Hz + derivative",
                        v_ref=v_ref, rel_off=rel_off)]
    results.append(evaluate(tu, v_b, events, rest_mask, "B) CV-Kalman baro-only",
                            v_ref=v_ref, rel_off=rel_off))

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
        results.append(evaluate(tu, v_c, events, rest_mask, "C) Kalman + accel",
                                v_ref=v_ref, rel_off=rel_off))
    else:
        print("no IMU in run — estimator C skipped")

    print_strength_table(results)

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
