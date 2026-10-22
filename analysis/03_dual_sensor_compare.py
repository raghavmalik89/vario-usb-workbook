#!/usr/bin/env python3
"""
03_dual_sensor_compare.py — T-003: two barometers, correlation & averaging gain.

For the two (or three) barometers in one run, measures:
  - per-sensor pressure noise (detrended RMS)
  - residual cross-correlation between sensors (shared vs independent noise)
    as a full N×N matrix (R-1: spatial decorrelation is a per-PAIR question)
  - actual averaging gain vs the sqrt(N) ideal
  - any static offset between sensors

This is the evidence file for ADR-002 (dual barometer: worth it or not).

Usage:
    python 03_dual_sensor_compare.py '*t003*'          # auto-detect sids
    python 03_dual_sensor_compare.py run.csv --sids 0,1
"""
import sys

import matplotlib.pyplot as plt
import numpy as np

from common import find_run, load_run, pressure_series, run_name, savefig


def detrend(t, y, order=2):
    return y - np.polyval(np.polyfit(t, y, order), t)


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "*.csv"
    arg = next((a.split("=")[1] for a in sys.argv if a.startswith("--sids=")), None)
    csv_path = find_run(pattern)
    print(f"Run: {csv_path.name}")
    df, meta = load_run(csv_path)

    sids = ([int(s) for s in arg.split(",")] if arg
            else sorted(df[df.type == "P"].sid.dropna().unique().astype(int)))
    if len(sids) < 2:
        raise SystemExit("Need >=2 barometers with P frames in this run.")

    series = {}
    for s in sids:
        t, p, _ = pressure_series(df, meta, s)
        series[s] = (t, p)
        print(f"sid {s}: {len(p)} samples, mean {p.mean():.1f} Pa")

    ref_t, ref_p = series[sids[0]]
    ref_d = detrend(ref_t, ref_p)

    fig, axes = plt.subplots(len(sids) + 1, 1, figsize=(12, 3 * (len(sids) + 1)),
                             sharex=True)
    fig.suptitle(f"Dual-barometer comparison — {run_name(csv_path)}")
    if len(sids) == 1:
        axes = [axes]
    sigmas = {}
    for ax, (s, (t, p)) in zip(axes, series.items()):
        ax.plot(t, p - p.mean(), lw=0.5, label=f"sid {s} (mean subtracted)")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax.set_ylabel("Δp [Pa]")
        sigmas[s] = detrend(t, p).std()

    # align others to ref by timestamp interpolation, compute correlations
    print("\nPairwise vs sid", sids[0], "(detrended residuals):")
    residuals = {sids[0]: ref_d}
    cors = []
    for s in sids[1:]:
        t, p = series[s]
        p_on_ref = np.interp(ref_t, t, p)
        d = detrend(ref_t, p_on_ref)
        residuals[s] = d
        # static offset after low-order detrend
        offset = (p_on_ref - np.polyval(np.polyfit(ref_t, p_on_ref, 2), ref_t)).mean() \
            - ref_d.mean()
        cor = np.corrcoef(ref_d, d)[0, 1]
        cors.append(cor)
        print(f"  sid {s}: σ={d.std():6.2f} Pa  corr={cor:+.2f}  offset≈{offset:+.2f} Pa")

    # full N×N correlation matrix — every pair aligned to the ref timeline
    print("\nCorrelation matrix (detrended residuals, all pairs):")
    print("          " + "".join(f"sid {s:^7}" for s in sids))
    for si in sids:
        ti, pi = series[si]
        di = detrend(ref_t, np.interp(ref_t, ti, pi))
        row = f"  sid {si}  "
        for sj in sids:
            tj, pj = series[sj]
            dj = detrend(ref_t, np.interp(ref_t, tj, pj))
            row += f"   {np.corrcoef(di, dj)[0, 1]:+.2f}   "
        print(row)

    # averaging gain: mean of residuals
    stacked = np.vstack([residuals[s] for s in sids])
    avg = stacked.mean(axis=0)
    sigma_avg = avg.std()
    sigma_mean_ind = np.mean(list(sigmas.values()))
    ideal = sigma_mean_ind / np.sqrt(len(sids))
    print(f"\nAverage of {len(sids)} sensors:")
    print(f"  σ_avg = {sigma_avg:.2f} Pa   ideal sqrt({len(sids)}) prediction "
          f"= {ideal:.2f} Pa")
    if sigma_avg < 0.9 * ideal:
        print("  -> averaging beats ideal: noise was anti-correlated (unlikely)")
    elif sigma_avg < sigma_mean_ind * 0.85:
        gain = sigma_mean_ind / sigma_avg
        print(f"  -> real averaging gain {gain:.2f}x "
              f"(ideal {np.sqrt(len(sids)):.2f}x) — dual barometer helps")
    else:
        print("  -> little gain: noise is mostly correlated (shared airflow/"
              "chamber) — evidence AGAINST dual-baro value in one chamber")

    axes[-1].plot(ref_t, avg, lw=0.5, color="#7d3c98",
                  label=f"average σ={sigma_avg:.2f} Pa")
    axes[-1].set(xlabel="t [s]", ylabel="Δp [Pa]")
    axes[-1].legend(fontsize=8)
    axes[-1].grid(alpha=0.3)
    fig.tight_layout()
    savefig(fig, f"03_dual_compare_{run_name(csv_path)}.png")


if __name__ == "__main__":
    main()
