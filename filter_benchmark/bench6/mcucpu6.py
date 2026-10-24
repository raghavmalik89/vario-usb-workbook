"""Bench 6 - on-target MCU CPU for the firmware estimator bank (build of
record = post-p0fix), from the B-line telemetry streamed during the clean
captures (real 240 MHz ESP32-S3, real baro+IMU pipeline; no synthetic loop
timing).

B-line semantics (verified against raw notes):
  * post-p0fix lines carry 9 "avg/max" pairs in eid order 0..8; eid 9
    (sid1 FUS) is absent - the IMU-side cost is not charged to the FUS
    B-line entry (DEF-009). One boot-time line still shows a 2676 us max
    spike (startup gain refit, decaying).
  * pre-p0fix lines carry 7-8 pairs with the C03 refit-storm entry first
    (~1330/2676 us - the DEF-002 era, fixed before the p0fix build); that
    format is kept here as historical evidence only, not per-estimator rows.

Writes results/610_mcu_cpu.csv. Repro: python -u mcucpu6.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BENCH6_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH6_DIR))
sys.path.insert(0, str(BENCH6_DIR.parent / "src"))
import datasets as ds  # noqa: E402
import streams  # noqa: E402

RES = BENCH6_DIR / "results"
rows = []

# ---- current build (post-p0fix): eid-order pairs, eid 9 missing (DEF-009)
post = [s for s in ds.SCORING
        if ds.FILES[s]["firmware"].startswith("post-p0fix")]
for stem in post:
    lines = [p for p in streams.bline_cpu(stem) if len(p) >= 9]
    for eid in range(9):
        avgs = [p[eid][0] for p in lines]
        maxs = [p[eid][1] for p in lines]
        rows.append(dict(
            session=stem[9:15], era="post-p0fix (build of record)",
            sid=eid // 5, estimator=ds.EST_NAMES[eid % 5],
            avg_us_med=round(float(np.median(avgs)), 1),
            max_us_med=round(float(np.median(maxs)), 1),
            max_us_p95=round(float(np.percentile(maxs, 95)), 1),
            n_lines=len(lines)))

# ---- historical: pre-p0fix storm entry (DEF-002 evidence)
for stem in [s for s in ds.SCORING
             if ds.FILES[s]["firmware"].startswith("pre-p0fix")]:
    lines = streams.bline_cpu(stem)
    storms = [p[0] for p in lines if p]
    rows.append(dict(
        session=stem[9:15], era="pre-p0fix (DEF-002 historical)",
        sid="", estimator="C03 (refit storm, first B-line pair)",
        avg_us_med=round(float(np.median([s[0] for s in storms])), 1),
        max_us_med=round(float(np.median([s[1] for s in storms])), 1),
        max_us_p95=round(float(np.percentile([s[1] for s in storms], 95)), 1),
        n_lines=len(lines)))

df = pd.DataFrame(rows)
df.to_csv(RES / "610_mcu_cpu.csv", index=False)
print(df.to_string())
print("\nwrote", RES / "610_mcu_cpu.csv")
