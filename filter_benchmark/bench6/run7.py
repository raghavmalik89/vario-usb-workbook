"""Bench 7 runner — BMP581 datasets against the FROZEN Bench 6 candidate set.

Reuses everything from bench6 (streams, metrics, candidates, replay loops
imported from run6) and adds the two Bench-7-specific checks:

  73_mcu_equiv.csv        python-replay audio episodes vs MCU V-frame episodes
                          for the five firmware estimators (eid = sid*5+est),
                          per capture: per-episode d(t_on), d(t_off), d(peak_v)
  74_d01c03_identity.csv  numerical identity check D01_Kalman_CV vs
                          C03_CV_tracker (their MCU V frames are byte-identical
                          in the BMP581 captures — this verifies whether the
                          equivalence is mathematical, not a wiring bug)

Nothing is tuned here: every candidate is the frozen registry config from
candidates.py.  DEF-011/DEF-014 semantics are respected by streams.baro_stream
(reference='isa' default) and metrics6.

Repro:  python -u run7.py     (from filter_benchmark/bench6/)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BENCH6_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH6_DIR))

import datasets as ds  # noqa: E402
import streams  # noqa: E402
import metrics6  # noqa: E402
from candidates import CANDIDATES, FIRMWARE_BANK  # noqa: E402
from run6 import replay_baro_only, replay_fusion  # noqa: E402

RES = BENCH6_DIR / "results"
TRC = RES / "traces7"
TRC.mkdir(parents=True, exist_ok=True)

# Bench 7 scoring set: the three BMP581 captures (sid0 only — single barometer)
STEMS = [k for k in ds.SCORING if "bmp581" in k and "bringup" not in k]
SIDS = (0,)

EST_INDEX = {n: i for i, n in ds.EST_NAMES.items()}          # name -> est idx
NAME_OF_EST = {v: k for k, v in EST_INDEX.items()}           # idx -> name
FW_NAME = {"D01_Kalman_CV": "D01", "C03_CV_tracker": "C03",
           "S4_FastSlowGated": "S4", "S5_LightGateKF": "S5", "FUS": "FUS"}


def python_episodes(t, v):
    """ON/OFF episodes from the frozen default audio policy."""
    sm = metrics6.AudioStateMachine(metrics6.LIFT_ON, metrics6.LIFT_OFF)
    states, trans = metrics6.run_audio(sm, t, v)
    eps, on = [], None
    for tt, st in zip(t, states):
        if st == "on" and on is None:
            on = tt
        elif st == "off" and on is not None:
            eps.append((on, tt))
            on = None
    if on is not None:
        eps.append((on, t[-1]))
    return eps


def mcu_equiv_rows(stem, sid, traces, t):
    """Compare replayed python audio with the MCU V frames per estimator."""
    rows = []
    for cand in FIRMWARE_BANK:
        est = EST_INDEX[FW_NAME[cand]]
        eid = sid * ds.N_EST + est
        mcu = streams.mcu_episodes(stem, eid)
        py = python_episodes(t, traces[f"v::{cand}"])
        n = max(len(mcu), len(py))
        for i in range(n):
            m = mcu[i] if i < len(mcu) else (np.nan, np.nan, np.nan, np.nan)
            p = py[i] if i < len(py) else (np.nan, np.nan)
            rows.append(dict(
                session=stem, sid=sid, candidate=cand, episode=i,
                n_mcu=len(mcu), n_py=len(py),
                mcu_t_on=m[0], py_t_on=p[0],
                dt_on=abs(m[0] - p[0]) if i < len(mcu) and i < len(py) else np.nan,
                mcu_t_off=m[1], py_t_off=p[1],
                dt_off=abs(m[1] - p[1]) if i < len(mcu) and i < len(py) else np.nan,
                mcu_peak_v=m[2], mcu_dur_s=m[3],
                match=(i < len(mcu) and i < len(py)
                       and abs(m[0] - p[0]) < 0.5 and abs(m[1] - p[1]) < 0.5)))
    return rows


def identity_rows(stem, sid, traces, t):
    a = traces.get("v::D01_Kalman_CV")
    b = traces.get("v::C03_CV_tracker")
    if a is None or b is None:
        return []
    dv = np.abs(a - b)
    ep_a, ep_b = python_episodes(t, a), python_episodes(t, b)
    return [dict(session=stem, sid=sid,
                   max_abs_dv=float(dv.max()), mean_abs_dv=float(dv.mean()),
                   n_ep_d01=len(ep_a), n_ep_c03=len(ep_b),
                   episodes_identical=(ep_a == ep_b),
                   v_d01_rms=float(np.sqrt(np.mean(a ** 2))),
                   v_c03_rms=float(np.sqrt(np.mean(b ** 2))))]


def main():
    names = list(CANDIDATES.keys())
    (static_rows, elev_rows, leg_rows, hand_rows, hblk_rows, qual_rows,
     equiv_rows, ident_rows) = [], [], [], [], [], [], [], []

    for stem in STEMS:
        info = ds.FILES[stem]
        classes = info["classes"]
        for sid in SIDS:
            t, alt, diag = streams.baro_stream(stem, sid, reference="isa")
            diag["sensor"] = "bmp581"
            qual_rows.append(dict(session=stem, sid=sid, **diag))
            print(f"[stream] {stem} sid{sid}: {diag['n_feed']} samples "
                  f"{diag['n_seq_gaps']} gaps {diag['n_corrupt']} corrupt",
                  flush=True)

            legs = events = v_ref = slow_blocks = None
            if "elevator" in classes:
                legs = streams.detect_legs(t, alt)
                print(f"  legs: {[(round(a,1), round(b,1), round(v,2)) for a,b,v,_ in legs]}")
            if "handtest" in classes:
                events, v_ref = streams.derive_events(t, alt)
                slow_blocks, _ = streams.detect_slow_blocks(t, alt)
                print(f"  events: {len(events)} | "
                      f"slow blocks: {[(round(a,1), round(b,1)) for a,b in slow_blocks]}")

            fusion_inputs = None
            if any(CANDIDATES[c].get("requires_imu") for c in names):
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
                        v, dt_us, f, n_imu = replay_fusion(
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
                    import traceback
                    traceback.print_exc()
                    continue

                row = dict(session=stem, sid=sid, candidate=name,
                           cpu_us_per_update=round(dt_us, 3), **extra)
                if "static" in classes:
                    m = metrics6.static_metrics(t, v)
                    am = metrics6.audio_metrics(t, v)
                    static_rows.append({**row, **m, **{f"audio_{k}": val for k, val in am.items()}})
                elif "elevator" in classes:
                    m, per_leg, _ = metrics6.elevator_metrics(t, v, legs, audio_sm=None)
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

            equiv_rows.extend(mcu_equiv_rows(stem, sid, traces, t))
            ident_rows.extend(identity_rows(stem, sid, traces, t))
            np.savez_compressed(TRC / f"{stem}_sid{sid}.npz", **traces)
            print(f"  traces -> {TRC / (stem + '_sid' + str(sid) + '.npz')}",
                  flush=True)

    def w(df, name):
        p = RES / name
        df.to_csv(p, index=False)
        print(f"wrote {p} ({len(df)} rows)")

    if static_rows:
        w(pd.DataFrame(static_rows), "70_static.csv")
    if elev_rows:
        w(pd.DataFrame(elev_rows), "71_elevator_summary.csv")
    if leg_rows:
        w(pd.DataFrame(leg_rows), "711_elevator_legs.csv")
    if hand_rows:
        w(pd.DataFrame(hand_rows), "72_handtest.csv")
    if hblk_rows:
        w(pd.DataFrame(hblk_rows), "721_handtest_blocks.csv")
    w(pd.DataFrame(qual_rows), "75_stream_quality.csv")
    w(pd.DataFrame(equiv_rows), "73_mcu_equiv.csv")
    w(pd.DataFrame(ident_rows), "74_d01c03_identity.csv")


if __name__ == "__main__":
    main()
