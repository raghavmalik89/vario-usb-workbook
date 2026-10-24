"""Bench 6 — formal MCU-vs-Python replay equivalence (the task queued since
the false-lift investigation), with the firmware-exact reconstruction chain.

Two firmware-era-specific input chains are required, both identified during
this benchmark (see defect register DEF-010/DEF-011 and the Bench-6 report):

  elevator/handtest era (pre-p0fix):  reference='moving_p0', seed_d2=True
      the moving p0 cancelled the firmware's 10x pressure scale, so MCU
      velocities are common-scale; the d2 boot seed shaped the startup
      transient the estimators consumed.
  post-p0fix era:                     reference='isa_fw10', seed_d2=True
      the fixed 101325 Pa reference is in COMMON-LINE units while
      compensate_pa still returns 10x common.py scale (DEF-011), scaling
      velocities by exactly 10^0.1903 = 1.5498.

Part A (harness validation): with the era-correct chain the replay MUST
reproduce the MCU tones everywhere except the documented startup flap
(DEF-010) — this re-proves the previous session's -0.002 m/s dwell result
and extends it to all five estimators, both sids, all tones t>=8 s.

Part B (formal equivalence, the queued task): post-fix captures, all five
estimators, tone-implied velocity agreement AND audio ON/OFF transition
agreement. Startup flap (t<8 s) reported separately, never hidden.

Writes results/65_mcu_equiv.csv.
Repro: python -u equiv6.py
"""
from __future__ import annotations

import sys
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
RES.mkdir(exist_ok=True)

MATCH_WIN_S = 0.03
STARTUP_S = 8.0
BANK = ["D01_Kalman_CV", "C03_CV_tracker", "S4_FastSlowGated",
        "S5_LightGateKF", "FUS"]


def replay_candidate(name, t, alt, stem):
    spec = CANDIDATES[name]
    if spec.get("requires_imu"):
        f = spec["factory"]()
        quats, _ = streams.attitude_quats(stem)
        t_imu, a_cal, _, _ = streams.imu_stream(stem)
        v = np.empty(len(t))
        ib = ii = 0
        while ib < len(t):
            while ii < len(t_imu) and t_imu[ii] <= t[ib]:
                f.update_imu(a_cal[ii], t_imu[ii], quat=quats[ii])
                ii += 1
            v[ib] = f.update_baro(float(alt[ib]), float(t[ib]))
            ib += 1
        return v
    f = spec["factory"]()
    return np.array([f.update(float(z), float(tt))
                     for z, tt in zip(alt, t)])


def compare_run(stem, reference, part):
    rows = []
    for sid in (0, 1):
        t, alt, _ = streams.baro_stream(stem, sid, reference=reference,
                                        seed_d2=True)
        for est_idx, name in enumerate(BANK):
            eid = sid * ds.N_EST + est_idx
            v = replay_candidate(name, t, alt, stem)
            tt, vi = streams.mcu_tones(stem, eid)
            idx = np.searchsorted(t, tt).clip(1, len(t) - 1)
            ok = np.abs(t[idx] - tt) < MATCH_WIN_S
            segs = [("startup_t<8s", ok & (tt < STARTUP_S)),
                    ("steady_t>=8s", ok & (tt >= STARTUP_S))]
            if reference == "moving_p0":
                # pre-fix era: p0 froze at t=50 s; report the frozen era
                # separately - gate chaos lives in the moving window
                segs.append(("frozen_t>=50s", ok & (tt >= 50.0)))
            for seg, m in segs:
                e = v[idx[m]] - vi[m]
                # audio ON/OFF agreement over the same segment
                sm = metrics6.AudioStateMachine(metrics6.LIFT_ON,
                                                metrics6.LIFT_OFF)
                i0 = np.searchsorted(t, 0.0 if seg.startswith("startup")
                                     else STARTUP_S)
                states, trans = metrics6.run_audio(sm, t[i0:], v[i0:])
                rep_onoff = [(a, b) for a, b in trans]
                tv, e2, ev2, _ = streams.v_frames(stem)
                mm = (e2 == eid) & np.isin(ev2, (1, 2))
                if seg.startswith("startup"):
                    mm &= tv < STARTUP_S
                else:
                    mm &= tv >= STARTUP_S
                mcu_onoff = [(a, "on" if b == 1 else "off")
                             for a, b in zip(tv[mm], ev2[mm])]
                n_agree = sum(bool([r for r in rep_onoff
                                    if abs(r[0] - a) < MATCH_WIN_S
                                    and r[1] == s])
                              for a, s in mcu_onoff)
                agree = n_agree / max(1, len(mcu_onoff))
                rows.append(dict(
                    part=part, session=stem, sid=sid, estimator=name,
                    segment=seg, reference=reference, n_tones=int(m.sum()),
                    vel_bias_mms=round(float(e.mean() * 1000), 1) if len(e) else np.nan,
                    p95_abs_ms=round(float(np.percentile(np.abs(e), 95) * 1000), 1) if len(e) else np.nan,
                    rms_ms=round(float(np.sqrt(np.mean(e ** 2)) * 1000), 1) if len(e) else np.nan,
                    audio_transition_agree=round(float(agree), 4),
                    n_mcu_transitions=len(mcu_onoff)))
                print(f"  [{part[:5]}] {stem[9:15]} sid{sid} {name:16s} {seg}: "
                      f"n={m.sum():4d} bias={e.mean()*1000 if len(e) else float('nan'):+7.1f} ms "
                      f"p95|e|={np.percentile(np.abs(e),95)*1000 if len(e) else float('nan'):6.1f} ms "
                      f"audio agree={agree:.2%}", flush=True)
    return rows


def main():
    rows = []
    print("== Part A: harness validation, pre-p0fix era chain "
          "(moving_p0 + seed) ==")
    for stem in ("20261023_221124_idf_elevator_2x",
                 "20261023_221420_idf_elevator_2x",
                 "20261023_215709_idf_handtest3"):
        rows += compare_run(stem, "moving_p0", "A_pre_p0fix_era_chain")
    print("== Part B: formal equivalence, post-p0fix era chain "
          "(isa_fw10 + seed, DEF-011 scale) ==")
    for stem in ("20261023_234521_idf_p0fix_static",
                 "20261023_234944_idf_bbuf_check"):
        rows += compare_run(stem, "isa_fw10", "B_post_p0fix_era_chain")
    df = pd.DataFrame(rows)
    df.to_csv(RES / "65_mcu_equiv.csv", index=False)
    print(f"wrote {RES / '65_mcu_equiv.csv'} ({len(df)} rows)")
    piv = df[df.segment == "steady_t>=8s"]
    print("\n== steady-state summary (t>=8s) ==")
    for part in piv.part.unique():
        sub = piv[piv.part == part]
        print(f"{part}: vel bias {sub.vel_bias_mms.mean():+.1f} mm/s, "
              f"p95|e| {sub.p95_abs_ms.mean():.1f} mm/s, "
              f"audio agree {sub.audio_transition_agree.mean():.2%}, "
              f"n_tones {sub.n_tones.sum()}")


if __name__ == "__main__":
    main()
