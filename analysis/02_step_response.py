#!/usr/bin/env python3
"""
02_step_response.py — T-004 elevator/step response characterisation.

Finds the largest motion segment in the run, then reports:
  - 10–90 % rise time and effective vertical speed
  - detection latency: time from IMU accel onset (if IMU present) to the
    pressure-based climb-rate estimate crossing a threshold
  - climb-rate estimate noise at rest (false-cue metric)

Usage:
    python 02_step_response.py '*elevator*'
    python 02_step_response.py run.csv --sid 0 --threshold 0.3
"""
import sys

import matplotlib.pyplot as plt
import numpy as np

from common import altitude_m, find_run, load_run, pressure_series, run_name, savefig


def climb_rate(t, alt, smooth_s=0.5):
    """Savitzky-free simple approach: gaussian-smooth alt, then gradient."""
    n = max(int(smooth_s / np.median(np.diff(t))) | 1, 3)
    k = np.exp(-0.5 * ((np.arange(-3 * n, 3 * n + 1)) / n) ** 2)
    k /= k.sum()
    alt_s = np.convolve(alt, k, mode="same")
    v = np.gradient(alt_s, t)
    return v, alt_s


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*.csv"
    sid = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--sid=")), 0))
    thresh = float(next((a.split("=")[1] for a in sys.argv
                         if a.startswith("--threshold=")), 0.3))

    csv_path = find_run(pattern)
    print(f"Run: {csv_path.name}  sid={sid}  threshold={thresh} m/s")
    df, meta = load_run(csv_path)
    t, p, _ = pressure_series(df, meta, sid)
    alt = altitude_m(p, p0_pa=p[: int(10 * len(p) / t[-1])].mean() if t[-1] > 20
                     else p.mean())
    v, alt_s = climb_rate(t, alt)

    # ---- locate biggest motion segment (auto) ----
    ai = np.argmax(np.abs(v))
    rest = np.abs(v) < 0.05
    rest_frac = rest.mean()
    print(f"rest fraction |v|<0.05: {rest_frac:.0%}")

    # rise time around peak motion: window where |v| > 50% of peak
    half = np.abs(v) > 0.5 * np.abs(v[ai])
    # longest contiguous run of 'half'
    d = np.diff(half.astype(int))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    t10 = float("nan")
    segment_found = False
    if len(starts) and len(ends):
        if ends[0] < starts[0]:
            ends = ends[1:]
        seg = max(zip(starts, ends[: len(starts)]), key=lambda se: se[1] - se[0])
        i0, i1 = seg
        segment_found = True
        lvl0 = np.median(alt[max(i0 - 200, 0): i0])
        lvl1 = np.median(alt[i1: i1 + 200]) if i1 + 200 < len(alt) \
            else np.median(alt[i0:i1])
        step = abs(lvl1 - lvl0)
        v_eff = step / (t[i1] - t[i0]) if i1 > i0 else 0
        # 10-90% crossing times
        lo, hi = min(lvl0, lvl1), max(lvl0, lvl1)
        up = lvl1 > lvl0
        seg_alt = alt_s[i0:i1]
        c10 = np.where((seg_alt > lo + 0.1 * step) if up
                       else (seg_alt < hi - 0.1 * step))[0]
        c90 = np.where((seg_alt > lo + 0.9 * step) if up
                       else (seg_alt < hi - 0.9 * step))[0]
        t10 = t[i0 + c10[0]] if len(c10) else np.nan
        t90 = t[i0 + c90[0]] if len(c90) else np.nan
        print(f"step segment: t={t[i0]:.1f}..{t[i1]:.1f}s  "
              f"Δh={step:.1f} m  v_eff={v_eff:.2f} m/s")
        print(f"10-90% rise: {t10:.2f} -> {t90:.2f} s  "
              f"(rise time {1000*(t90-t10):.0f} ms)" if not np.isnan(t10)
              else "10-90% rise: not resolved")
    else:
        print("no clear step detected — was this a stationary run?")

    # ---- IMU onset latency (if IMU data present) ----
    imu = df[df.type == "I"].dropna(subset=["ax", "ay", "az"])
    if len(imu) > 100 and segment_found and not np.isnan(t10):
        # Ride start = first |a| deviation from the rest level just before the
        # detected segment. Searching the whole run is wrong: handling bumps
        # in the first seconds trip a low threshold and produce garbage latency
        # (learned on the t004 elevator run).
        a = np.sqrt(imu.ax ** 2 + imu.ay ** 2 + imu.az ** 2).values
        rest_med = np.median(a[imu.t_s.values < min(10, imu.t_s.max())])
        dev = np.abs(a - rest_med)
        win = (imu.t_s.values > t[i0] - 6) & (imu.t_s.values < t[i0] + 1)
        j = np.where(win & (dev > 1000))[0]   # 1000 LSB ~ 0.06 g
        if len(j):
            onset = imu.t_s.iloc[j[0]]
            print(f"IMU ride-start jolt at {onset:.2f} s -> 10% pressure response "
                  f"{1000*(t10-onset):.0f} ms (filter-limited, not sensing)")
        else:
            print("no IMU jolt before the step segment — soft ramp (elevator)?")
    elif len(imu) <= 100:
        print("no IMU data in run — latency vs IMU skipped")

    # ---- vario estimate noise at rest ----
    if rest_frac > 0.1:
        v_rest = v[rest]
        v_rms = np.sqrt(np.mean(v_rest ** 2))
        print(f"rest |v| noise: {v_rms:.3f} m/s RMS "
              f"({'OK' if v_rms < 0.15 else 'noisy'} — false-cue metric, "
              f"target < 0.15 m/s)")

    # ---- plot ----
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    fig.suptitle(f"Step response — {run_name(csv_path)} (sid {sid})")
    axes[0].plot(t, alt, lw=0.5, color="#95a5a6", label="raw altitude")
    axes[0].plot(t, alt_s, lw=1.2, color="#1a5276", label="smoothed")
    axes[0].set_ylabel("altitude [m]")
    axes[0].legend(fontsize=8)
    axes[1].plot(t, v, lw=0.8, color="#1e8449")
    axes[1].axhline(thresh, color="#c0392b", ls="--", lw=0.8)
    axes[1].axhline(-thresh, color="#c0392b", ls="--", lw=0.8)
    axes[1].set(xlabel="t [s]", ylabel="climb rate [m/s]")
    for ax in axes.flat:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    savefig(fig, f"02_step_response_{run_name(csv_path)}.png")


if __name__ == "__main__":
    main()
