#!/usr/bin/env python3
"""
01_noise_floor.py — T-001 baseline: stationary noise characterisation.

Measures, per barometer:
  - raw ADC (d1) noise and effective resolution
  - compensated pressure noise (Pa) and RMS noise expressed as cm of altitude
  - Allan deviation over tau list (short-term stability)
  - achieved sample rate + gap statistics

Usage:
    python 01_noise_floor.py '*t001*'          # all barometers in newest t001 run
    python 01_noise_floor.py run.csv --sid 0
"""
import sys

import matplotlib.pyplot as plt
import numpy as np

from common import (OUT_DIR, altitude_m, find_run, load_run, pressure_series,
                    run_name, savefig)


def allan_dev(x, dt_s, taus):
    """Overlapping Allan deviation of series x sampled at dt_s."""
    out = []
    n = len(x)
    for tau in taus:
        m = max(int(round(tau / dt_s)), 1)
        if m * 2 >= n:
            out.append(np.nan)
            continue
        d = x[2 * m:] - 2 * x[m:n - m] + x[:n - 2 * m]
        out.append(np.sqrt(np.mean(d * d)) / (2 * tau))
    return np.array(out)


def analyse(csv_path, sid):
    df, meta = load_run(csv_path)
    t, p, temp = pressure_series(df, meta, sid)
    dt = np.median(np.diff(t))
    rate = 1.0 / dt

    # detrend (remove slow drift + mean) for noise metrics
    detrend = p - np.polyval(np.polyfit(t, p, 2), t)
    sigma_pa = detrend.std()
    # altitude noise: d(alt)/d(p) = k*(44330-alt)/p  (k=0.1903); ~8.3 cm/Pa at sea level
    cm_rms = sigma_pa * (44330.0 - altitude_m(p.mean())) * 0.1903 / p.mean() * 100

    d1 = df[(df.type == "P") & (df.sid == sid)].d1.dropna().values
    adc_lsb = np.std(d1 - np.polyval(np.polyfit(np.arange(len(d1)), d1, 2),
                                    np.arange(len(d1))))

    p_frames = df[(df.type == "P") & (df.sid == sid)]
    expected = p_frames.seq.max() - p_frames.seq.min() + 1
    gaps = expected - len(p_frames)

    taus = np.array([1, 2, 5, 10, 30, 60, 120])
    adev = allan_dev(p - p.mean(), dt, taus) if len(p) > 500 else None

    print(f"--- sid={sid} ---")
    print(f"  samples      : {len(p)}  rate {rate:.1f} Hz (median dt {dt*1e3:.2f} ms)")
    print(f"  seq gaps     : {gaps} missing P frames")
    print(f"  pressure     : mean {p.mean():.1f} Pa  ({p.mean()/100:.3f} hPa)")
    print(f"  temperature  : mean {temp.mean():.2f} C")
    print(f"  noise (detrended over 60 s win):")
    print(f"      {sigma_pa:.2f} Pa RMS  ->  {cm_rms:.2f} cm altitude RMS")
    print(f"  raw d1 noise : {adc_lsb:.1f} LSB")
    return dict(sid=sid, t=t, p=p, temp=temp, detrend=detrend, sigma_pa=sigma_pa,
                cm_rms=cm_rms, adev=adev, taus=taus, rate=rate)


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*.csv"
    sids = [int(a.split("=")[1]) for a in sys.argv if a.startswith("--sid=")] or None

    csv_path = find_run(pattern)
    print(f"Run: {csv_path.name}")
    df, meta = load_run(csv_path)
    if sids is None:
        sids = sorted(df[df.type == "P"].sid.dropna().unique().astype(int))

    results = [analyse(csv_path, s) for s in sids]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    fig.suptitle(f"Noise floor — {run_name(csv_path)}")
    for r in results:
        lab = f"sid {r['sid']}  ({r['sigma_pa']:.1f} Pa, {r['cm_rms']:.1f} cm)"
        axes[0, 0].plot(r["t"], r["p"], lw=0.6, label=lab)
        axes[0, 1].plot(r["t"][: min(len(r["t"]), 3000)],
                        r["detrend"][: min(len(r["t"]), 3000)], lw=0.6,
                        label=f"sid {r['sid']}")
        axes[1, 0].hist(r["detrend"], bins=80, alpha=0.5, label=f"sid {r['sid']}")
        if r["adev"] is not None:
            axes[1, 1].loglog(r["taus"], r["adev"], "o-", label=f"sid {r['sid']}")
    axes[0, 0].set(xlabel="t [s]", ylabel="pressure [Pa]", title="raw pressure")
    axes[0, 1].set(xlabel="t [s]", ylabel="Δp [Pa]", title="detrended detail")
    axes[1, 0].set(xlabel="Δp [Pa]", ylabel="count", title="noise histogram")
    axes[1, 1].set(xlabel="tau [s]", ylabel="Allan dev [Pa]",
                   title="Allan deviation")
    for ax in axes.flat:
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    savefig(fig, f"01_noise_floor_{run_name(csv_path)}.png")

    print("\nVerdict thresholds (bench targets):")
    for r in results:
        tag = "OK " if r["cm_rms"] < 10 else ("marginal" if r["cm_rms"] < 25 else "NOISY")
        print(f"  sid {r['sid']}: {r['cm_rms']:6.1f} cm RMS -> {tag}  "
              f"(target < 10 cm = BMP581-class; MS5611 OSR4096 typically 5–15 cm)")


if __name__ == "__main__":
    main()
