"""Script 09 — Phase 3 fault recovery (synthetic, seeded, reproducible) and
CPU cost measurement.

Fault scenarios (each on a 60 s quiet base at 100 Hz, seeded rng):
    A: isolated 1-sample spike (+5 m altitude equivalent)
    B: 0.4 s sustained burst (+3 m)          -- fault-like disturbance
    C: 0.5 s data gap (missing samples)
    D: rapid reversal square wave (+-2 m/s, 1 s period, 6 cycles)
Metrics per scenario: max |v| in the 2 s AFTER the transient ends, recovery
time (|v| back under 0.3 m/s), recorded failures (spec §5: never hidden).

CPU cost: median microseconds per update over 3 replays of a 60 s @ 100 Hz
stream, per candidate (same machine, same process; relative cost is the
quantity that matters).

Outputs:
    results/09_fault_recovery.csv
    results/09_cpu_cost.csv
    results/fig_fault_recovery.png
"""
from pathlib import Path
import json
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import ROOT, replay  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from filters import FILTERS  # noqa: E402
from filters.stacked import STACKED  # noqa: E402

REGISTRY = dict(FILTERS)
REGISTRY.update(STACKED)
P3 = json.loads((ROOT / "config" / "phase3.json").read_text("utf-8"))
NAMES = list(P3["architectures"]) + P3["reference_baselines"]


def build_scenario(kind, t, rng):
    z = rng.normal(0, 0.25, len(t))            # quiet base, 0.25 m noise
    if kind == "spike":
        z[int(30.0 / 0.01)] += 5.0
        t_end = 30.0
    elif kind == "burst":
        i0, i1 = int(30.0 / 0.01), int(30.4 / 0.01)
        z[i0:i1] += 3.0
        t_end = 30.4
    elif kind == "gap":
        i0, i1 = int(30.0 / 0.01), int(30.5 / 0.01)
        z = np.concatenate([z[:i0], z[i1:]])
        t_end = 30.5
    elif kind == "reversal":
        i0 = int(30.0 / 0.01)
        for k in range(600):
            z[i0 + k] += 2.0 * 0.01 if (k // 50) % 2 == 0 else -2.0 * 0.01
        t_end = 36.0
    return z, t_end


def main():
    t = np.arange(0, 60, 0.01)
    rows, traces = [], {}
    for kind in ("spike", "burst", "gap", "reversal"):
        for name in NAMES:
            ov = dict(P3["architectures"].get(name, {}).get("params", {}))
            rng = np.random.default_rng(1234)
            z, t_end = build_scenario(kind, t, rng)
            tt = t if kind != "gap" else np.delete(t, np.arange(int(30.0 / 0.01), int(30.5 / 0.01)))
            f = REGISTRY[name](**ov)
            t0 = time.perf_counter()
            _, v = replay.replay(f, t=tt, z=z)
            cpu_s = time.perf_counter() - t0
            m = (tt >= t_end) & (tt <= t_end + 2.0)
            after = np.abs(v[m])
            mx = float(after.max()) if len(after) else np.nan
            below = np.where(after <= 0.3)[0]
            rec = float(tt[m][below[0]] - t_end) if len(below) else np.nan
            rows.append(dict(scenario=kind, filter=name,
                             max_abs_v_after=round(mx, 3),
                             recovery_s=(round(rec, 3) if rec == rec else "n/a"),
                             recorded_failure=int(mx > 1.0),
                             cpu_us_per_sample=round(cpu_s / len(tt) * 1e6, 2)))
            traces[(kind, name)] = (tt, v)
        print(f"  scenario {kind} done", flush=True)

    # CPU cost on clean stream, 3 replays, median
    cpu_rows = []
    rng = np.random.default_rng(7)
    z = rng.normal(0, 0.25, len(t))
    for name in NAMES:
        ov = dict(P3["architectures"].get(name, {}).get("params", {}))
        ts = []
        for _ in range(3):
            f = REGISTRY[name](**ov)
            t0 = time.perf_counter()
            replay.replay(f, t=t, z=z)
            ts.append((time.perf_counter() - t0) / len(t) * 1e6)
        cpu_rows.append(dict(filter=name, cpu_us_per_sample_median=round(float(np.median(ts)), 2),
                             rel_to_D01=round(float(np.median(ts)), 2)))
    d01 = next(r["cpu_us_per_sample_median"] for r in cpu_rows
               if r["filter"] == "D01_Kalman_CV")
    for r in cpu_rows:
        r["rel_to_D01"] = round(r["cpu_us_per_sample_median"] / d01, 2)

    import csv
    for rows_, fname in ((rows, "09_fault_recovery.csv"),
                         (cpu_rows, "09_cpu_cost.csv")):
        out = ROOT / "results" / fname
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows_[0]))
            w.writeheader()
            w.writerows(rows_)
        print(f"wrote {out}")

    # failure-case visualisation: 4 scenarios x traces for S1/S3/D01
    fig, axes = plt.subplots(4, 1, figsize=(11, 12), sharex=False)
    picks = ["S1_RobustAdaptiveKF", "S3_AccelerationAwareKF", "D01_Kalman_CV"]
    for ax, kind in zip(axes, ("spike", "burst", "gap", "reversal")):
        for name in picks:
            tt, v = traces[(kind, name)]
            ax.plot(tt, v, label=name, linewidth=0.8)
        ax.axhline(1.0, color="r", linestyle="--", linewidth=0.7)
        ax.axhline(-1.0, color="r", linestyle="--", linewidth=0.7)
        ax.axvline({"spike": 30.0, "burst": 30.4, "gap": 30.5, "reversal": 36.0}[kind],
                   color="k", linestyle=":", linewidth=0.8)
        ax.set_ylim(-6, 6)
        ax.set_ylabel("v [m/s]")
        ax.set_title(f"scenario: {kind} (dotted = transient end; dashed = failure threshold ±1 m/s)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    axes[-1].set_xlabel("t [s]")
    fig.tight_layout()
    fig.savefig(ROOT / "results" / "fig_fault_recovery.png", dpi=140)
    print("wrote fig_fault_recovery.png")


if __name__ == "__main__":
    main()
