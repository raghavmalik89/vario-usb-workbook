"""Bench 6 candidate set — every filter evaluated, with frozen configs and
explicit provenance. NOTHING here is tuned on the Bench-6 validation split:
defaults are the as-shipped registry configs (frozen since Phase 2), stacked
architectures are the Phase 3/4 frozen configs, and the firmware bank matches
esp-idf/vario/main/config.h exactly.

Fusion candidates are marked requires_imu and replayed on the interleaved
baro/IMU timeline (streams.attitude_quats + fusion.BaroImuFusion).
"""
from __future__ import annotations

import sys
from pathlib import Path

BENCH6_DIR = Path(__file__).resolve().parent
BENCH_ROOT = BENCH6_DIR.parents[0]
SRC = BENCH_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from filters import FILTERS                      # noqa: E402  29 standalone
from filters.stacked import STACKED              # noqa: E402  S1,S2,S3,S1P,S4,S5
from fusion import BaroImuFusion                 # noqa: E402

P3 = dict(window_s=1.0, n_sigma=2.5, q=0.3, r=0.035,
          gate_sigma=3.5, q_gain=2.0, v_scale=1.0)
P4_S1P = dict(window_s=1.0, n_sigma=2.5, q=0.3, r=0.035, gate_sigma=3.5,
              q_gain=2.0, v_scale=0.8, exit_v=0.12, exit_hold_s=0.2)
P3_S2 = dict(tau_fast_s=0.35, q_slow=0.3, r_slow=0.035, v_scale=0.8,
             exit_v=0.15, exit_hold_s=0.6, v_plaus_max=8.0,
             plaus_margin_m=0.3)
P3_S3 = dict(q=0.3, r=0.035, gate_sigma=3.5, a_plaus_max=6.0,
             fault_sigma=5.0, fault_n=8, fault_r_mult=25.0)
P4_S4 = dict(tau_fast_s=0.35, q_slow=0.3, r_slow=0.035, v_scale=0.8,
             exit_v=0.12, exit_hold_s=0.25, w_floor=0.3, v_plaus_max=8.0,
             plaus_margin_m=0.3)
P4_S5 = dict(q=0.3, r=0.035, gate_sigma=3.5, q_gain=2.0, v_scale=1.0,
             v_plaus_max=8.0, plaus_margin_m=0.3)
# firmware bank (esp-idf/vario/main/config.h) — S4/S5 identical to P4 frozen;
# D01/C03 identical to registry defaults (q=1.0, r=0.035).
FW_FUS = dict(q=0.3, r=0.035, gate_sigma=3.5, imu_timeout_s=0.25,
              orient_timeout_s=1.0, bias_tau_s=3.0, rest_v_max=0.5,
              rest_window_s=1.0, bias_abs_max=2.0)
FUS_Q10 = dict(FW_FUS, q=10.0)   # Phase-5 exploratory operating point


def _standalone():
    out = {}
    for name, fac in FILTERS.items():
        out[name] = dict(factory=lambda f=fac, **kw: f(**kw),
                         provenance="registry default (frozen since Phase 2)")
    return out


def _stacked(name, params, provenance, defect=False):
    cls = STACKED[name]
    return dict(factory=lambda c=cls, p=params: c(**p),
                provenance=provenance, defect_ref=defect)


def fusion_factory(params):
    def make():
        return BaroImuFusion(**params)
    return make


CANDIDATES = {}
CANDIDATES.update(_standalone())
CANDIDATES.update({
    "S1_RobustAdaptiveKF": _stacked(
        "S1_RobustAdaptiveKF", P3,
        "Phase-3 frozen config (config/phase3.json)"),
    "S1P_PersistenceKF": _stacked(
        "S1P_PersistenceKF", P4_S1P,
        "Phase-4 frozen config (config/phase4.json)"),
    "S2_DualTimescale": _stacked(
        "S2_DualTimescale", P3_S2,
        "Phase-3 frozen config — DEFECT REFERENCE (freeze trap F1)",
        defect=True),
    "S3_AccelerationAwareKF": _stacked(
        "S3_AccelerationAwareKF", P3_S3,
        "Phase-3 frozen config — DEFECT REFERENCE (audio chatter F7)",
        defect=True),
    "S4_FastSlowGated": _stacked(
        "S4_FastSlowGated", P4_S4,
        "Phase-4 frozen config == firmware EST_S4 (config.h)"),
    "S5_LightGateKF": _stacked(
        "S5_LightGateKF", P4_S5,
        "Phase-4 frozen config == firmware EST_S5 (config.h / vario_core)"),
    "FUS": dict(factory=fusion_factory(FW_FUS), requires_imu=True,
                provenance="firmware EST_FUS frozen config (config.h)"),
    "FUS_Q10": dict(factory=fusion_factory(FUS_Q10), requires_imu=True,
                    provenance="Phase-5 exploratory q=10 (labelled, not "
                               "a firmware config)"),
})

FIRMWARE_BANK = ["D01_Kalman_CV", "C03_CV_tracker", "S4_FastSlowGated",
                 "S5_LightGateKF", "FUS"]

# display order for reports/figures
GROUPS = {
    "baseline": ["B00_diff", "B01_regression", "B02_project_kalman"],
    "smoothing": ["A01_SMA", "A02_EMA", "A03_Holt", "A04_Median",
                  "A05_Hampel", "A06_RobustEMA"],
    "classical": ["B01_LP1", "B02_Butter2", "B03_Bessel2", "B04_SavGol",
                  "B05_LS_slope"],
    "tracking": ["C01_AlphaBeta", "C02_AlphaBetaGamma", "C03_CV_tracker",
                 "C04_CA_tracker"],
    "kalman": ["D01_Kalman_CV", "D02_Kalman_CA", "D04_Kalman_adaptR",
               "D05_Kalman_adaptQ", "D06_Kalman_gated"],
    "adaptive": ["E01_OneEuro", "E02_AdaptiveEMA", "E03_FastSlow",
                 "E04_InnovationBlend", "E05_ChangeDetect",
                 "E06_RobustAdapt"],
    "stacked": ["S1_RobustAdaptiveKF", "S1P_PersistenceKF", "S2_DualTimescale",
                "S3_AccelerationAwareKF", "S4_FastSlowGated",
                "S5_LightGateKF"],
    "fusion": ["FUS", "FUS_Q10"],
}
