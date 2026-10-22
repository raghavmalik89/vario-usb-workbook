# Engineering Task E — Phase 2: benchmark demonstration report

All numbers are **Measured** on the bench captures (task spec evidence labels: Measured / Calculated / Simulated / Hypothesis / Unavailable). Event onsets/releases are **descriptive proxy** measurements against *derived* reference intervals (1-s Gaussian-smoothed barometric derivative; event entry at |v|>0.15 m/s = 3x the statics p99, strong-motion gate max|v|>=0.5 inside each event, 1-s gap merging) — **not ground-truth latency**. Onset proxies are noise-adaptive DETECTION times: first exceedance of max(0.3, 5x the filter's own pre-event baseline), so noisy filters are not credited with impossible onsets. The reference vario baseline B03 is **Unavailable** in every recording (no reference-vario output stream exists in the data).

Phase 2 mandate: demonstrate that every baseline and standalone filter runs correctly and produces comparable metrics. **No winner is selected.** Per-filter tuning was fit on training sessions only and reported against held-out validation sessions.

## 1. Verification status

| check | result |
|---|---|
| unit tests (contract, irregular dt, missing samples, recovery, rate equivalence, audio latches, config round-trip) | 11/11 pass |
| filters registered | 29 |
| baseline rows (B00-B02, all sessions) | 70 |
| individual-filter rows (defaults, both splits) | 667 |
| corrupt frames preserved in diagnostics (not hidden) | 87 |

## 2. Baselines B00-B03 (spec §3)

| filter | static rest RMS [m/s] (median) | motion RMS [m/s] | onset proxy [s] | release proxy [s] | false latches |
|---|---|---|---|---|---|
| B00_diff | 9.140 | 11.630 | -2.905 | 7.940 | 1 |
| B01_regression | 0.159 | 1.277 | -1.965 | 4.765 | 7 |
| B02_project_kalman | 0.096 | 0.563 | -0.100 | 4.885 | 1 |
| B03_reference_vario | n/a — **Unavailable**: no recording contains a reference-vario output stream | | | | |

## 3. Standalone filters at default configs (Groups A-E)

Medians across sessions of each split half. Full per-session data: `results/04_individual_default.csv`.

| filter | static RMS [m/s] | false latches | motion RMS [m/s] | onset proxy [s] | release proxy [s] |
|---|---|---|---|---|---|
| B00_diff | 9.140 | 1 | 11.630 | -2.905 | 7.940 |
| B01_regression | 0.159 | 7 | 1.277 | -1.965 | 4.765 |
| B02_project_kalman | 0.096 | 1 | 0.563 | -0.100 | 4.885 |
| A01_SMA | 0.254 | 1 | 1.336 | -1.785 | 5.980 |
| A02_EMA | 0.190 | 1 | 0.810 | -1.040 | 7.920 |
| A03_Holt | 0.601 | 1 | 1.772 | -1.320 | 7.945 |
| A04_Median | 0.404 | 4 | 2.373 | -5.150 | 6.670 |
| A05_Hampel | 0.282 | 18 | 1.660 | -5.860 | 7.780 |
| A06_RobustEMA | 0.372 | 1 | 1.170 | -1.180 | 7.940 |
| B01_LP1 | 0.364 | 1 | 1.197 | -2.290 | 7.920 |
| B02_Butter2 | 2.551 | 1 | 4.626 | -3.290 | 5.680 |
| B03_Bessel2 | 3.417 | 1 | 5.304 | -3.245 | n/a |
| B04_SavGol | 0.489 | 1 | 2.752 | -3.340 | 7.190 |
| B05_LS_slope | 0.159 | 7 | 1.277 | -1.965 | 4.765 |
| C01_AlphaBeta | 0.026 | 0 | 0.671 | 1.225 | 5.740 |
| C02_AlphaBetaGamma | 0.021 | 0 | 0.538 | 1.375 | 4.670 |
| C03_CV_tracker | 0.048 | 1 | 1.130 | 0.045 | 2.605 |
| C04_CA_tracker | 0.468 | 1 | 3.069 | -3.760 | 7.160 |
| D01_Kalman_CV | 0.101 | 1 | 1.132 | -0.310 | 2.945 |
| D02_Kalman_CA | 0.481 | 1 | 2.972 | -3.685 | 7.165 |
| D04_Kalman_adaptR | 0.118 | 3 | 0.628 | -0.240 | 4.660 |
| D05_Kalman_adaptQ | 0.100 | 1 | 1.246 | -0.680 | 2.132 |
| D06_Kalman_gated | 0.101 | 1 | 0.916 | -0.125 | 3.830 |
| E01_OneEuro | 2.011 | 1 | 4.366 | -5.260 | 7.980 |
| E02_AdaptiveEMA | 1.687 | 1 | 2.783 | -2.130 | 7.960 |
| E03_FastSlow | 0.905 | 1 | 1.892 | -1.410 | 7.980 |
| E04_InnovationBlend | 0.457 | 1 | 1.685 | -0.820 | 7.980 |
| E05_ChangeDetect | 0.904 | 1 | 1.892 | -1.410 | 7.980 |
| E06_RobustAdapt | 0.118 | 3 | 0.583 | 0.030 | 4.700 |

Plots: `results/fig_noise_vs_onset.png` (rest-noise vs onset-proxy scatter), `results/fig_trace_elevator.png` (velocity traces on the elevator capture, default configs, grey bands = derived reference events, dashed lines = audio lift-on threshold ±0.20 m/s).

## 4. Per-filter tuning (training sessions) and held-out validation

Rank-based score within each filter (static RMS, motion RMS, onset proxy, false latches — lower is better; weights 1.0/0.5/1.0/0.5). Every tested configuration is preserved in `results/05_tuning_train.csv` (nothing discarded).

| filter | chosen config (train) | train score | val onset proxy: default→tuned [s] | val motion RMS: default→tuned |
|---|---|---|---|
| A01_SMA | window_s=3.0 | 2.0 | -2.240 → -2.140 | 1.231 → 0.670 |
| A02_EMA | tau_s=1.6 | 1.5 | -1.020 → -1.020 | 0.848 → 0.575 |
| A03_Holt | alpha=0.2,beta=0.05 | 1.5 | -3.530 → -1.140 | 1.441 → 1.184 |
| A04_Median | window_s=2.0 | 1.8 | -5.550 → -5.880 | 1.738 → 1.679 |
| A05_Hampel | window_s=2.0,n_sigma=2.5 | 1.3 | -5.880 → -5.880 | 1.679 → 1.679 |
| A06_RobustEMA | window_s=2.0,n_sigma=3.0,tau_s=1.0 | 2.0 | -1.180 → -1.860 | 1.194 → 0.759 |
| B01_LP1 | tau_s=1.6 | 1.5 | -2.220 → -1.020 | 1.192 → 0.573 |
| B02_Butter2 | cutoff_hz=0.8 | 1.5 | -3.660 → -3.730 | 6.070 → 5.440 |
| B03_Bessel2 | cutoff_hz=0.5 | 1.8 | -3.940 → -3.940 | 5.971 → 5.971 |
| B04_SavGol | window_s=2.5,order=2 | 2.0 | -3.940 → -2.390 | 1.846 → 1.538 |
| B05_LS_slope | window_s=1.6,order=1 | 2.2 | -1.860 → -0.460 | 1.191 → 1.128 |
| B01_regression | window_s=1.5 | 2.2 | -1.860 → -0.380 | 1.191 → 1.134 |
| C01_AlphaBeta | tau_s=0.6 | 2.3 | 1.835 → 1.980 | 0.788 → 0.630 |
| C02_AlphaBetaGamma | tau_s=1.2 | 1.7 | 1.970 → -0.240 | 0.630 → 0.224 |
| C03_CV_tracker | q=0.3,r=0.035 | 2.5 | -1.205 → 1.975 | 1.129 → 0.934 |
| C04_CA_tracker | q=0.3,r=0.012 | 3.7 | -3.820 → -3.820 | 1.938 → 1.921 |
| D01_Kalman_CV | q=0.3,r=0.1 | 3.7 | -3.035 → -1.220 | 1.131 → 0.753 |
| D02_Kalman_CA | q=1.0,r=0.012 | 3.7 | -3.840 → -3.740 | 1.882 → 2.034 |
| D04_Kalman_adaptR | q=0.5,r=0.035,window_s=3.0 | 1.3 | -1.295 → -2.260 | 0.702 → 0.558 |
| D05_Kalman_adaptQ | q=0.5,r=0.035,window_s=2.0 | 1.5 | -0.680 → -0.280 | 1.140 → 1.131 |
| D06_Kalman_gated | q=1.0,r=0.035,gate_sigma=3.5 | 1.7 | -2.845 → -2.895 | 1.086 → 1.115 |
| E01_OneEuro | min_cutoff_hz=0.3,beta=0.5 | 1.7 | -5.280 → -5.400 | 4.366 → 3.240 |
| E02_AdaptiveEMA | tau0_s=1.5,v0=0.7,tau_min_s=0.1 | 1.5 | -3.760 → -5.810 | 2.718 → 2.618 |
| E03_FastSlow | tau_fast_s=0.1,tau_slow_s=1.0,thresh=0.3,switch_hold_s=1.0 | 3.0 | -3.640 → -3.440 | 1.811 → 2.753 |
| E04_InnovationBlend | tau_fast_s=0.35,tau_slow_s=1.0,blend_c=0.05 | 3.2 | -3.270 → -3.160 | 1.640 → 1.217 |
| E05_ChangeDetect | tau_fast_s=0.35,tau_slow_s=1.0,cusum_threshold_m=0.5,alarm_hold_s=1.5 | 2.2 | -3.640 → -3.250 | 1.811 → 1.324 |
| E06_RobustAdapt | window_s=2.0,n_sigma=2.5,q=0.5 | 2.0 | -2.170 → -2.170 | 0.650 → 0.532 |

## 5. Rate comparison: 45 Hz vs (nominal) 100 Hz

t006 firmware streams pressure at a measured **90 Hz** (OSR2048, 10 ms tick: 9 P-frames + 1 T-frame per sensor per 10 ms). Compared using seconds-based parameterizations only (A03 Holt is excluded: its alpha/beta are per-sample, not physical). `results/06_rate_comparison.csv`, `results/fig_rate_static_rms.png`.

| filter | static rest RMS 45 Hz [m/s] | static rest RMS 90 Hz [m/s] | ratio 90/45 |
|---|---|---|---|
| B01_regression | 0.1592 | 0.1550 | 0.97 |
| A01_SMA | 0.2499 | 0.3957 | 1.58 |
| A02_EMA | 0.1904 | 0.1748 | 0.92 |
| A04_Median | 0.3927 | 0.5512 | 1.40 |
| A05_Hampel | 0.2817 | 0.3973 | 1.41 |
| A06_RobustEMA | 0.3775 | 0.3425 | 0.91 |
| B01_LP1 | 0.3690 | 0.3439 | 0.93 |
| B02_Butter2 | 2.5426 | 3.7278 | 1.47 |
| B03_Bessel2 | 3.4022 | 5.1817 | 1.52 |
| B04_SavGol | 0.4886 | 0.5753 | 1.18 |
| B05_LS_slope | 0.1592 | 0.1550 | 0.97 |
| C01_AlphaBeta | 0.0261 | 0.0246 | 0.94 |
| C03_CV_tracker | 0.0475 | 0.0564 | 1.19 |
| C04_CA_tracker | 0.4684 | 0.4560 | 0.97 |
| D01_Kalman_CV | 0.1007 | 0.0870 | 0.86 |
| D02_Kalman_CA | 0.4691 | 0.5025 | 1.07 |
| D04_Kalman_adaptR | 0.1221 | 0.0967 | 0.79 |
| D06_Kalman_gated | 0.1007 | 0.0869 | 0.86 |

## 6. Limitations

- **Derived references are proxies.** Onset/release numbers describe timing against a smoothed-derivative reference, not physical latency; no capture contains truth-tagged events. (Measured methodology, Calculated numbers.)
- **Few independent sessions.** 9 training + 5 validation sessions, multiple sids per session are NOT independent samples (shared chamber/ride). No confidence intervals are claimed anywhere; medians are descriptive.
- **Elevator exists only at 45 Hz** (and one 90 Hz elevator was never captured), so the rate comparison rests on statics, controlled moves and drops.
- **Motion classes are coarse**: drop/toss/elevator/controlled-move cover the flight-relevant envelope only partially; no real thermal lift capture exists yet (planned).
- **B03 reference vario: Unavailable** in all recordings.
- Audio-policy evaluation so far uses latch counting at the research PDF's starting thresholds (lift-on 0.20 / lift-off 0.05 m/s); continuous-beeping and exit-from-lift behaviour are first-class metrics in Phase 3's combination evaluation, as mandated.
- IMU channels are not part of Phase 2 baro-only streams; the XCTracer-inspired fusion candidate enters in Phase 3 where the IMU capture path is validated.

## 7. Reproducibility

```
python scripts/run_tests.py            # 11/11
python scripts/03_run_baselines.py
python scripts/04_run_individual_filters.py
python scripts/05_tune_parameters.py A B C D E   # or all at once
python scripts/06_make_report.py
```

Every filter config in every CSV round-trips to a constructor call (enforced by a dedicated unit test).
