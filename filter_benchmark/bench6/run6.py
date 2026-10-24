"""Bench 6 frozen-pass runner.

Evaluates EVERY candidate in candidates.CANDIDATES on every scoring stream
(datasets.SCORING x sids x {0,1}) with the corrected fixed-ISA reference, and
writes:

  results/60_static.csv           per candidate x static session x sid
  results/61_elevator_summary.csv per candidate x elevator run x sid
  results/611_elevator_legs.csv   per candidate x run x sid x leg (detail)
  results/62_handtest.csv         per candidate x sid
  results/63_cpu_host.csv         host us/update per candidate (relative cost)
  results/64_stream_quality.csv   measured per-stream health
  results/traces/{stem}_sid{N}.npz   replayed v(t) for every candidate
                                     (figures read these — no re-replay)

Fusion candidates replay on the interleaved baro/IMU timeline with Madgwick
attitude (warm-started). Everything is timestamp-driven: no assumed rates.

Repro:  python -u run6.py            (from filter_benchmark/bench6/)
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

BENCH6_DIR = Path(__file__).resolve().parent
BENCH_ROOT = BENCH6_DIR.parents[0]
SRC = BENCH_ROOT / "src"
for p in (str(SRC), str(BENCH6_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import datasets as ds  # noqa: E402
import streams  # noqa: E402
import metrics6  # noqa: E402
from candidates import CANDIDATES  # noqa: E402

RES = BENCH6_DIR / "results"
TRC = RES / "traces"
RES.mkdir(exist_ok=True)
TRC.mkdir(exist_ok=True)

CPU_REF_STREAM = ("20261023_221124_idf_elevator_2x", 0)   # longest clean stream


def replay_baro_only(fac, t, alt):
    f = fac()
    v = np.empty(len(t))
    t0 = time.perf_counter_ns()
    for i in range(len(t)):
        v[i] = f.update(float(alt[i]), float(t[i]))
    dt_us = (time.perf_counter_ns() - t0) / 1e3 / max(1, len(t))
    return v, dt_us, f


def replay_fusion(fac, t, alt, t_imu, a_cal, quats):
    from fusion import BaroImuFusion
    f = fac()
    assert isinstance(f, BaroImuFusion)
    v = np.empty(len(t))
    ib = ii = 0
    n = len(t)
    t0 = time.perf_counter_ns()
    while ib < n:
        # feed all IMU samples up to and including the current baro stamp
        while ii < len(t_imu) and t_imu[ii] <= t[ib]:
            f.update_imu(a_cal[ii], t_imu[ii], quat=quats[ii])
            ii += 1
        v[ib] = f.update_baro(float(alt[ib]), float(t[ib]))
        ib += 1
    dt_us = (time.perf_counter_ns() - t0) / 1e3 / max(1, n)
    return v, dt_us, f, ii


def main():
    names = list(CANDIDATES.keys())
    (static_rows, elev_rows, leg_rows, hand_rows, hblk_rows,
     qual_rows, cpu_rows) = [], [], [], [], [], [], []

    # ---- per-stream: reconstruct once, replay all candidates -------------
    for stem in ds.SCORING:
        info = ds.FILES[stem]
        classes = info["classes"]
        for sid in (0, 1):
            t, alt, diag = streams.baro_stream(stem, sid, reference="isa")
            qual_rows.append(dict(session=stem, sid=sid, **diag))
            print(f"[stream] {stem} sid{sid}: {diag['n_feed']} samples "
                  f"{diag['n_seq_gaps']} gaps {diag['n_corrupt']} corrupt",
                  flush=True)

            legs, events, v_ref, slow_blocks = None, None, None, None
            if "elevator" in classes:
                legs = streams.detect_legs(t, alt)
                print(f"  legs: {[(round(a,1), round(b,1), round(v,2)) for a,b,v,_ in legs]}")
            if "handtest" in classes:
                events, v_ref = streams.derive_events(t, alt)
                slow_blocks, _ = streams.detect_slow_blocks(t, alt)
                print(f"  events: {len(events)} "
                      f"{[(round(a,1), round(b,1)) for a,b in events[:8]]} | "
                      f"slow blocks: {[(round(a,1), round(b,1)) for a,b in slow_blocks]}")

            # fusion prerequisites (once per session)
            fusion_inputs = None
            need_fusion = any(CANDIDATES[c].get("requires_imu") for c in names)
            if need_fusion:
                quats, qinfo = streams.attitude_quats(stem)
                out = streams.imu_stream(stem)
                if out is None:
                    raise SystemExit(f"{stem}: fusion needs IMU, none found")
                t_imu, a_cal, _, iinfo = out
                fusion_inputs = (t_imu, a_cal, quats, qinfo)

            traces = dict(t=t, alt=alt)
            if v_ref is not None:
                traces["v_ref"] = v_ref
            if legs is not None:
                traces["legs"] = np.array(legs, dtype=float)
            if events is not None:
                traces["events"] = np.array(events, dtype=float)
            if slow_blocks is not None:
                traces["slow_blocks"] = np.array(slow_blocks, dtype=float)

            for name in names:
                spec = CANDIDATES[name]
                try:
                    if spec.get("requires_imu"):
                        t_imu, a_cal, quats, qinfo = fusion_inputs
                        v, dt_us, f, n_imu_fed = replay_fusion(
                            spec["factory"], t, alt, t_imu, a_cal, quats)
                        extra = dict(n_gated=int(f.n_gated),
                                     n_reinit=int(f.n_reinit),
                                     bias_norm=round(float(np.linalg.norm(f.accel_bias)), 4))
                    else:
                        v, dt_us, f = replay_baro_only(spec["factory"], t, alt)
                        extra = {}
                        for a in ("n_gated", "n_rejected", "n_faults", "n_reinit"):
                            if hasattr(f, a):
                                extra[a] = int(getattr(f, a))
                    traces[f"v::{name}"] = v
                except Exception:
                    print(f"  !! {name} FAILED on {stem} sid{sid}")
                    traceback.print_exc()
                    continue

                if (stem, sid) == CPU_REF_STREAM:
                    cpu_rows.append(dict(candidate=name, host_us_per_update=round(dt_us, 3),
                                         n_updates=len(t), **extra))

                row = dict(session=stem, sid=sid, candidate=name,
                           cpu_us_per_update=round(dt_us, 3), **extra)
                if "static" in classes:
                    m = metrics6.static_metrics(t, v)
                    static_rows.append({**row, **m})
                elif "elevator" in classes:
                    sm = None
                    m, per_leg, _ = metrics6.elevator_metrics(
                        t, v, legs, audio_sm=None)
                    # audio evaluated separately below (its own columns)
                    am, _, _ = metrics6.elevator_metrics(
                        t, v, legs, audio_sm=metrics6.AudioStateMachine(
                            metrics6.LIFT_ON, metrics6.LIFT_OFF))
                    for k, val in am.items():
                        if k.startswith(("dwell_", "ascent_on", "missed", "descent_")):
                            row["audio_" + k] = val
                    elev_rows.append({**row, **m})
                    for leg in per_leg:
                        leg_rows.append({**row, **leg})
                elif "handtest" in classes:
                    m, per_ev, rec = metrics6.handtest_metrics(
                        t, v, events, v_ref,
                        audio_sm=metrics6.AudioStateMachine(
                            metrics6.LIFT_ON, metrics6.LIFT_OFF),
                        slow_blocks=slow_blocks)
                    for blk in m.pop("_slow_blocks", []):
                        hblk_rows.append({**row, **blk})
                    hand_rows.append({**row, **m})
            np.savez_compressed(TRC / f"{stem}_sid{sid}.npz", **traces)
            print(f"  traces -> {TRC / (stem + '_sid' + str(sid) + '.npz')}",
                  flush=True)

    def w(df, name):
        p = RES / name
        df.to_csv(p, index=False)
        print(f"wrote {p} ({len(df)} rows)")

    if static_rows:
        w(pd.DataFrame(static_rows), "60_static.csv")
    if elev_rows:
        w(pd.DataFrame(elev_rows), "61_elevator_summary.csv")
    if leg_rows:
        w(pd.DataFrame(leg_rows), "611_elevator_legs.csv")
    if hand_rows:
        w(pd.DataFrame(hand_rows), "62_handtest.csv")
    if hblk_rows:
        w(pd.DataFrame(hblk_rows), "621_handtest_blocks.csv")
    w(pd.DataFrame(qual_rows), "64_stream_quality.csv")
    w(pd.DataFrame(cpu_rows), "63_cpu_host.csv")


if __name__ == "__main__":
    main()
