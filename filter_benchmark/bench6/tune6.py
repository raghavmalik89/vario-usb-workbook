"""Bench 6 — leakage-controlled tuning pass (SEPARATE from the frozen run).

The frozen evaluation (run6.py) ships as-shipped configs only. This pass asks
a narrower question: within four families of the firmware bank, does a
grid move trade any metric worth making? Selection uses the TRAIN split
(elevator run1 + handtest3) ONLY; every configuration is then REPORTED on the
VALIDATION split (elevator run2 + p0fix/bbuf statics) so overfitting is
visible, not hidden. Nothing selected here is frozen — outputs are labelled
`tuned=True` and the frozen results remain the benchmark of record.

Grids (labelled, small, honest):
  D01_Kalman_CV / C03_CV_tracker : q in {0.3,1,3,10} x r in {0.02,0.035,0.07}
  S5_LightGateKF                 : q in {0.1,0.3,1,3} (rest of P4_S5 frozen)
  S4_FastSlowGated               : tau_fast_s in {0.2,0.35,0.5}

Train composite (each term relative to the family's frozen config, median
over sids; lower is better):
  |elevator leg bias|, elevator leg rms, dwell false-ON seconds,
  handtest onset, handtest static-silence false-ON/hr, handtest static rms.

Writes results/67_tuning_train.csv, 68_tuning_validation.csv,
69_tuning_selection.csv.
Repro: python -u tune6.py
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
from candidates import CANDIDATES, P4_S4, P4_S5  # noqa: E402
from filters.kalman import D01KalmanCV  # noqa: E402
from filters.tracking import C03CVTracker  # noqa: E402
from filters.stacked import STACKED  # noqa: E402

RES = BENCH6_DIR / "results"
RES.mkdir(exist_ok=True)

TRAIN_STEMS = ["20261023_221124_idf_elevator_2x", "20261023_215709_idf_handtest3"]
VAL_STEMS = ["20261023_221420_idf_elevator_2x",
             "20261023_234521_idf_p0fix_static", "20261023_234944_idf_bbuf_check"]


def make_grid():
    """(family, label, params-dict, factory) rows; frozen first per family."""
    rows = []

    def fam_qr(family, cls, extra=None):
        base = dict(extra or {})
        for q in (0.3, 1.0, 3.0, 10.0):
            for r in (0.02, 0.035, 0.07):
                params = dict(base, q=q, r=r)
                rows.append((family, f"q={q} r={r}", params,
                             lambda c=cls, p=params: c(**p)))

    fam_qr("D01_Kalman_CV", D01KalmanCV)
    fam_qr("C03_CV_tracker", C03CVTracker)
    for q in (0.1, 0.3, 1.0, 3.0):
        params = dict(P4_S5, q=q)
        rows.append(("S5_LightGateKF", f"q={q}", params,
                     lambda c=STACKED["S5_LightGateKF"], p=params: c(**p)))
    for tau in (0.2, 0.35, 0.5):
        params = dict(P4_S4, tau_fast_s=tau)
        rows.append(("S4_FastSlowGated", f"tau_fast={tau}", params,
                     lambda c=STACKED["S4_FastSlowGated"], p=params: c(**p)))
    return rows


def score_session(stem, sid, t, alt, factory, legs=None, events=None,
                  v_ref=None, slow_blocks=None):
    f = factory()
    v = np.array([f.update(float(z), float(tt)) for z, tt in zip(alt, t)])
    classes = ds.FILES[stem]["classes"]
    row = dict(session=stem[9:15], sid=sid)
    if "elevator" in classes:
        m, _, _ = metrics6.elevator_metrics(t, v, legs)
        am, _, _ = metrics6.elevator_metrics(
            t, v, legs, audio_sm=metrics6.AudioStateMachine(
                metrics6.LIFT_ON, metrics6.LIFT_OFF))
        row.update(elev_bias=m["bias_med"], elev_rms=m["rms_med"],
                   rise_s=m["rise_med_s"], exit_s=m["exit_med_s"],
                   dwell_false_on_s=am["dwell_false_on_s"],
                   missed_lifts=am["missed_lifts"])
    elif "handtest" in classes:
        m, _, _ = metrics6.handtest_metrics(
            t, v, events, v_ref,
            audio_sm=metrics6.AudioStateMachine(metrics6.LIFT_ON,
                                                metrics6.LIFT_OFF),
            slow_blocks=slow_blocks)
        row.update(onset_s=m["onset_med_s"],
                   static_rms=m["static_rms"],
                   static_false_per_hr=m["static_false_on_per_hr"],
                   toss_settle_s=m["toss_settle_med_s"],
                   slow_bias=m.get("slow_bias_med"),
                   audio_on_frac_outside=m.get("audio_on_frac_outside"))
    elif "static" in classes:
        m = metrics6.static_metrics(t, v)
        row.update(rest_rms=m["rest_rms"],
                   rest_false_per_hr=m.get("false_on_per_hr"))
    return row


def main():
    grid = make_grid()
    train_rows, val_rows = [], []
    for stem in TRAIN_STEMS + VAL_STEMS:
        is_train = stem in TRAIN_STEMS
        classes = ds.FILES[stem]["classes"]
        for sid in (0, 1):
            t, alt, _ = streams.baro_stream(stem, sid, reference="isa")
            legs = events = v_ref = slow_blocks = None
            if "elevator" in classes:
                legs = streams.detect_legs(t, alt)
            if "handtest" in classes:
                events, v_ref = streams.derive_events(t, alt)
                slow_blocks, _ = streams.detect_slow_blocks(t, alt)
            for family, label, params, factory in grid:
                row = score_session(stem, sid, t, alt, factory, legs,
                                    events, v_ref, slow_blocks)
                row.update(family=family, config=label, tuned=True,
                           params=str(params))
                (train_rows if is_train else val_rows).append(row)
            print(f"{stem[9:15]} sid{sid}: {len(grid)} configs scored",
                  flush=True)

    tr = pd.DataFrame(train_rows)
    va = pd.DataFrame(val_rows)
    tr.to_csv(RES / "67_tuning_train.csv", index=False)
    va.to_csv(RES / "68_tuning_validation.csv", index=False)
    print(f"wrote 67 ({len(tr)} rows), 68 ({len(va)} rows)")

    # ---- composite on TRAIN only, relative to the frozen config of family --
    COMP = [("elev_bias", True), ("elev_rms", True), ("dwell_false_on_s", True),
            ("onset_s", True), ("static_false_per_hr", True),
            ("static_rms", True)]
    sel_rows = []
    for family, g in tr.groupby("family"):
        g = g.copy()
        # frozen reference row = config containing the frozen parameters
        frozen_label = {"D01_Kalman_CV": "q=1.0 r=0.035",
                        "C03_CV_tracker": "q=1.0 r=0.035",
                        "S5_LightGateKF": "q=0.3",
                        "S4_FastSlowGated": "tau_fast=0.35"}[family]
        ref = g[g.config == frozen_label]
        terms = []
        for col, _ in COMP:
            if col not in g or g[col].notna().sum() == 0:
                continue
            base = ref[col].abs().median()
            if not np.isfinite(base) or base == 0:
                base = g[col].abs().median()
            med = g.groupby("config")[col].apply(
                lambda s: s.abs().median())
            terms.append((med / base).clip(lower=0.0))
        comp = sum(terms) / len(terms)
        comp = comp.sort_values()
        for cfg, score in comp.items():
            sel_rows.append(dict(family=family, config=cfg,
                                 train_composite=round(float(score), 4),
                                 frozen=(cfg == frozen_label)))
    sel = pd.DataFrame(sel_rows)
    sel.to_csv(RES / "69_tuning_selection.csv", index=False)
    print(f"wrote 69_tuning_selection.csv ({len(sel)} rows)")
    print(sel.groupby("family").head(3).to_string())


if __name__ == "__main__":
    main()
