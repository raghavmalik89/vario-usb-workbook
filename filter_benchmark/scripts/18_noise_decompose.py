"""Diagnostic: decompose static-capture altitude noise by channel.

Earlier session concluded: d1 noise ~2.4 Pa, d2 noise ~1.3 Pa (via dp/dd2).
But median-filtering d2 over +/-2.5 s did NOT reduce compensated altitude
noise (0.426 -> 0.441 m). That contradiction means the noise model is wrong
somewhere. Decompose directly:

  p(d1 raw, d2 raw)        total
  p(d1 raw, d2 median)     d1 + compensation cross-terms
  p(d1 const, d2 raw)      d2 contribution alone
  p(d1 raw, d2 const)      d1 contribution alone

Repro:  python -u scripts/18_noise_decompose.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import loader
import replay

DATA = ROOT.parent / "analysis" / "data"
G0 = 9.80665


def main():
    csv = DATA / "20261023_110700_t007_benchstatic.csv"
    df = pd.read_csv(csv, index_col=False)
    df["t_s"] = df.t_us / 1e6
    sc = loader.sidecar_for(csv)
    for sid in (0, 1):
        prom = loader.get_prom(sc, sid)
        pr = df[(df.type == "P") & (df.sid == sid)][["t_s", "d1"]].dropna()
        tr = df[(df.type == "T") & (df.sid == sid)][["t_s", "d2"]].dropna()
        d1 = pr.d1.values.astype(float)
        bad = (d1 < replay.D1_BAND[0]) | (d1 > replay.D1_BAND[1])
        pr, d1 = pr[~bad], d1[~bad]
        t_p = pr.t_s.values
        tr = tr.sort_values("t_s")
        idx = np.searchsorted(tr.t_s.values, t_p, side="right") - 1
        idx = np.clip(idx, 0, len(tr) - 1)
        d2 = tr.d2.values[idx].astype(float)

        # median-filter d2 (same 5 s window as script 17)
        half = 2.5
        d2_f = np.empty_like(d2)
        for i in range(len(d2)):
            m = (t_p >= t_p[i] - half) & (t_p <= t_p[i] + half)
            d2_f[i] = np.median(d2[m]) if m.any() else d2[i]

        def p_of(a1, a2):
            p, _ = loader.compensate_ms5611(a1, a2, prom)
            return p

        def dp_std(p):
            d = np.diff(p)
            # robust: also trimmed
            return float(np.std(d)), float(np.std(d[np.abs(d) < 5 * np.std(d)]))

        variants = {
            "total (d1,d2 raw)": (d1, d2),
            "d2 median 5s": (d1, d2_f),
            "d1 const, d2 raw": (np.full_like(d1, np.median(d1)), d2),
            "d1 raw, d2 const": (d1, np.full_like(d2, np.median(d2))),
            "d1 const, d2 const": (np.full_like(d1, np.median(d1)),
                                   np.full_like(d2, np.median(d2))),
        }
        print(f"\nsid{sid}  prom={prom}  n_P={len(d1)}")
        print(f"  d1 diff std = {np.std(np.diff(d1)):.1f} counts")
        print(f"  d2(diff of merged) std = {np.std(np.diff(d2)):.1f} counts; "
              f"median-filt d2 diff std = {np.std(np.diff(d2_f)):.1f}")
        for name, (a1, a2) in variants.items():
            s_all, s_trim = dp_std(p_of(a1, a2))
            print(f"  {name:22s} dp lag-1 std = {s_all:7.3f} Pa "
                  f"(trimmed {s_trim:7.3f}) = {s_trim / 12.0:6.3f} m alt")

        # d2 raw structure: unique-level histogram of diffs of T frames
        d2t = tr.d2.values.astype(float)
        dd = np.diff(d2t)
        vals, cnts = np.unique(dd, return_counts=True)
        top = np.argsort(cnts)[-8:][::-1]
        print("  T-frame d2 diff histogram (top):")
        for i in top:
            print(f"    dd2={vals[i]:8.0f}  x{cnts[i]}")
        # altitude slow drift
        p = p_of(d1, d2_f)
        alt = 44330.0 * (1.0 - (p / np.nanmean(p[:2000])) ** 0.1903)
        print(f"  alt drift over session: min {np.min(alt):.3f} max {np.max(alt):.3f} m;"
              f" std {np.std(alt):.3f} m")


if __name__ == "__main__":
    main()
