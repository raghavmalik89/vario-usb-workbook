"""Filter registry — every standalone filter/baseline in the benchmark.

Each entry: name -> factory(**overrides) -> Filter instance. Default
configs live here (explicit, reproducible from CLI invocations).
"""
from .baselines import B00Diff, B01Regression, B02_project_estimator
from .classical import B01LowPass1, B02Butter2, B03Bessel2, B04SavGol, B05LSSlope
from .adaptive import (E01OneEuro, E02AdaptiveEMA, E03FastSlowSwitch,
                       E04InnovationBlend, E05ChangeDetect, E06RobustAdaptive)
from .kalman import (D01KalmanCV, D02KalmanCA, D04KalmanAdaptiveR,
                     D05KalmanAdaptQ, D06KalmanGated)
from .smoothing import A01SMA, A02EMA, A03Holt, A04Median, A05Hampel, A06RobustEMA
from .tracking import C01AlphaBeta, C02AlphaBetaGamma, C03CVTracker, C04CATracker

# D03 deferred: [h,v,a,bias] is unobservable with baro-only measurements
# (spec: no states added for sophistication). Evaluated only in the fusion
# phase with an IMU channel.

FILTERS = {
    # baselines (spec §3)
    "B00_diff": lambda **kw: B00Diff(),
    "B01_regression": lambda **kw: B01Regression(**kw),
    "B02_project_kalman": lambda **kw: B02_project_estimator(),
    # Group A — smoothing
    "A01_SMA": lambda **kw: A01SMA(**kw),
    "A02_EMA": lambda **kw: A02EMA(**kw),
    "A03_Holt": lambda **kw: A03Holt(**kw),
    "A04_Median": lambda **kw: A04Median(**kw),
    "A05_Hampel": lambda **kw: A05Hampel(**kw),
    "A06_RobustEMA": lambda **kw: A06RobustEMA(**kw),
    # Group B — classical
    "B01_LP1": lambda **kw: B01LowPass1(**kw),
    "B02_Butter2": lambda **kw: B02Butter2(**kw),
    "B03_Bessel2": lambda **kw: B03Bessel2(**kw),
    "B04_SavGol": lambda **kw: B04SavGol(**kw),
    "B05_LS_slope": lambda **kw: B05LSSlope(**kw),
    # Group C — tracking
    "C01_AlphaBeta": lambda **kw: C01AlphaBeta(**kw),
    "C02_AlphaBetaGamma": lambda **kw: C02AlphaBetaGamma(**kw),
    "C03_CV_tracker": lambda **kw: C03CVTracker(**kw),
    "C04_CA_tracker": lambda **kw: C04CATracker(**kw),
    # Group D — Kalman
    "D01_Kalman_CV": lambda **kw: D01KalmanCV(**kw),
    "D02_Kalman_CA": lambda **kw: D02KalmanCA(**kw),
    "D04_Kalman_adaptR": lambda **kw: D04KalmanAdaptiveR(**kw),
    "D05_Kalman_adaptQ": lambda **kw: D05KalmanAdaptQ(**kw),
    "D06_Kalman_gated": lambda **kw: D06KalmanGated(**kw),
    # Group E — adaptive / multi-timescale
    "E01_OneEuro": lambda **kw: E01OneEuro(**kw),
    "E02_AdaptiveEMA": lambda **kw: E02AdaptiveEMA(**kw),
    "E03_FastSlow": lambda **kw: E03FastSlowSwitch(**kw),
    "E04_InnovationBlend": lambda **kw: E04InnovationBlend(**kw),
    "E05_ChangeDetect": lambda **kw: E05ChangeDetect(**kw),
    "E06_RobustAdapt": lambda **kw: E06RobustAdaptive(**kw),
}

# reference vario baseline is unavailable by construction (spec §3 B03);
# every results table carries an explicit N/A row for it.
UNAVAILABLE = {"B03_reference_vario":
               "no recording contains a reference vario output"}
