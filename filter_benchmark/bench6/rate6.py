"""Bench 6 — sampling-rate sensitivity control.

The ESP-IDF chain samples baro at 40 Hz (bimodal 20/40 ms for the slow
clones) with IMU at 100 Hz; the old Arduino captures were 45/90 Hz + 200 Hz.
Before ranking filters measured on this chain we must know which architectures
are sample-rate sensitive: seconds-parameterized filters (Kalman Q/R in
continuous units, tau-based smoothers, gate timers) should be near-invariant,
while fixed-coefficient IIR filters (Butterworth at a design rate) should
degrade measurably.

Protocol: decimate the CLEAN elevator streams (both runs, both sids) by 2 and
4, replay the frozen candidate set, score with the identical leg definitions
and metrics as the main run. This is a control experiment, not a ranking.

Writes results/66_rate_control.csv (+ per-leg rows 661_rate_control_legs.csv).
Repro: python -u rate6.py
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

CANDS = ["D01_Kalman_CV", "C03_CV_tracker", "S4_FastSlowGated",
         "S5_LightGateKF", "FUS", "B02_Butter2"]


def replay(name, t, alt, stem, t_imu=None, a_cal=None, quats=None):
    spec = CANDIDATES[name]
    f = spec["factory"]()
    if spec.get("requires_imu"):
        v = np.empty(len(t))
        ib = ii = 0
        while ib < len(t):
            while ii < len(t_imu) and t_imu[ii] <= t[ib]:
                f.update_imu(a_cal[ii], t_imu[ii], quat=quats[ii])
                ii += 1
            v[ib] = f.update_baro(float(alt[ib]), float(t[ib]))
            ib += 1
        return v
    return np.array([f.update(float(z), float(tt))
                     for z, tt in zip(alt, t)])


def main():
    rows, leg_rows = [], []
    for stem in ("20261023_221124_idf_elevator_2x",
                 "20261023_221420_idf_elevator_2x"):
        # legs from the full-rate fixed-ISA sid0 stream (reference method)
        t_full0, alt_full0, _ = streams.baro_stream(stem, 0, reference="isa")
        legs = streams.detect_legs(t_full0, alt_full0)
        for sid in (0, 1):
            t, alt, _ = streams.baro_stream(stem, sid, reference="isa")
            quats = a_cal = t_imu = None
            if any(CANDIDATES[c].get("requires_imu") for c in CANDS):
                quats, _ = streams.attitude_quats(stem)
                t_imu, a_cal, _, _ = streams.imu_stream(stem)
            for dec in (1, 2, 4):
                td, ad = t[::dec], alt[::dec]
                fs_eff = 1.0 / np.median(np.diff(td))
                ti = ai = qi = None
                if t_imu is not None:
                    ti, ai, qi = t_imu[::dec], a_cal[::dec], quats[::dec]
                for name in CANDS:
                    v = replay(name, td, ad, stem, ti, ai, qi)
                    summ, per_leg, dwell = metrics6.elevator_metrics(
                        td, v, legs, audio_sm=metrics6.AudioStateMachine(
                            metrics6.LIFT_ON, metrics6.LIFT_OFF))
                    rows.append(dict(
                        session=stem[9:15], sid=sid, decimation=dec,
                        fs_eff_hz=round(float(fs_eff), 2), candidate=name,
                        rms_med=round(summ["rms_med"], 4),
                        bias_med=round(summ["bias_med"], 4),
                        rise_med_s=summ["rise_med_s"],
                        exit_med_s=summ["exit_med_s"],
                        dwell_false_on_s=summ.get("dwell_false_on_s"),
                        missed_lifts=summ.get("missed_lifts")))
                    for L in per_leg:
                        leg_rows.append(dict(
                            session=stem[9:15], sid=sid, decimation=dec,
                            candidate=name, leg=f"{L['t0']:.0f}-{L['t1']:.0f}",
                            v_leg=L["v_leg"], bias=L["bias"], rms=L["rms"],
                            rise_s=L["rise_s"], exit_s=L["exit_s"]))
                print(f"{stem[9:15]} sid{sid} dec={dec} "
                      f"(fs={fs_eff:.1f} Hz) done", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(RES / "66_rate_control.csv", index=False)
    pd.DataFrame(leg_rows).to_csv(RES / "661_rate_control_legs.csv",
                                  index=False)
    print(f"wrote {RES / '66_rate_control.csv'} ({len(df)} rows), "
          f"661_rate_control_legs.csv ({len(leg_rows)} rows)")
    # quick pivot: full-rate median rms vs decimated, per candidate
    piv = df.groupby(["candidate", "decimation"])[
        ["rms_med", "rise_med_s", "exit_med_s"]].median().round(3)
    print(piv.to_string())


if __name__ == "__main__":
    main()
