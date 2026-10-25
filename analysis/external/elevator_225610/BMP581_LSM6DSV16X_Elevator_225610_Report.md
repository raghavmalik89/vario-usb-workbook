# BMP581 + LSM6DSV16X — 2x Elevator Validation (2026-10-25, 22:56)

## Scope and recording
Input: `20261025_225610_idf_bmp581LSM6DS_elevator_2x_200s.csv` and same-named JSON, firmware `vario-idf 0.2.0`. Report prepared independently from the attached raw telemetry. The source name contains `200s` but the host recorded 180.33 seconds and the device timestamp span was **180.110 seconds**. The reference profile is floor **14 → 1 → 14 → 1 → 14**, two descents and two ascents.

## Gate 1 — Acquisition data integrity: PASS
- **No E error frames**, JSON `errors={}`; zero observed I²C A/B/MPU faults and recovery events in B diagnostics; zero sequence skips and zero malformed input lines.
- **18,012 IMU I frames**, 100.006 Hz; max intersample interval **11.922 ms**; **zero identical consecutive six-axis frames**, zero IMU gaps >15 ms.
- **7,205 BMP581 P frames**, 40.006 Hz; max interval **27.194 ms**; zero missed barometer conversions in B frames.
- 1,801 T frames (~10 Hz); 695 V frames; 36 five-second diagnostic B frames. No TX ring overflow; max high-water 1181 bytes; max sensor tick 6653 µs. All B windows report `vnan=0` and `vfault=0`.
- Host 180.33 s and device 180.11 s **agree closely** (contrast prior >10 s discrepancies); no evidence of a major USB backlog.
- No temporal basis to call any repeated periodic `#C` metadata a reset; those blocks are intentional keepalives.

## Gate 2 — Altitude and velocity profile
- BMP581 telemetry decoded **Pa = d1 / 64** from sidecar. Altitude is ISA pressure-derived; it is an apparent-altitude proxy, not independently surveyed height.
- Smoothed using **81-sample (~2.0 s), third-order Savitzky–Golay** to estimate pressure-derived altitude velocity. Motion start/stop timestamps are the crossing of ±0.30 m/s, not true mechanical elevator start/stop times; therefore apparent delays are relative comparisons only.
- Four full legs, height steps approximately ±39.2–39.5 m. Two descents stable approximately −1.73 m/s, two ascents +1.67 m/s. Return to the starting-floor measured height after two round-trips to within **-0.245 m**; slow ambient drift / pressure offset is present.

### Measured leg results
|   leg | direction   |   start_s |   stop_s |   duration_s |   plateau_mean_mps |   plateau_median_mps |   plateau_std_mps |   endpoint_height_m |
|------:|:------------|----------:|---------:|-------------:|-------------------:|---------------------:|------------------:|--------------------:|
|     1 | Descent     |     9.776 |   34.623 |       24.848 |             -1.738 |               -1.735 |             0.072 |             -39.397 |
|     2 | Ascent      |    51.651 |   76.926 |       25.275 |              1.67  |                1.667 |             0.072 |              39.236 |
|     3 | Descent     |    94.576 |  119.451 |       24.875 |             -1.736 |               -1.733 |             0.07  |             -39.419 |
|     4 | Ascent      |   136.451 |  161.701 |       25.25  |              1.669 |                1.671 |             0.068 |              39.335 |

### Stationary floor dwells
| floor      |   start_s |   end_s |   mean_h_m |   std_h_m |   mean_pa |   noise_pa |
|:-----------|----------:|--------:|-----------:|----------:|----------:|-----------:|
| 14 initial |         1 |       7 |    347.606 |    0.0324 |   97218.9 |     0.1869 |
| 1 first    |        40 |      48 |    308.21  |    0.0301 |   97677.4 |     0.2074 |
| 14 middle  |        82 |      89 |    347.446 |    0.0274 |   97220.8 |     0.1993 |
| 1 second   |       125 |     133 |    308.027 |    0.0283 |   97679.6 |     0.2193 |
| 14 final   |       170 |     179 |    347.362 |    0.0186 |   97221.8 |     0.1873 |

## Gate 3 — Five estimator virtual-audio performance
- Firmware declares `e0..e4 = D01, C03, S4, S5, FUS`, tone mapping `500 + 450*v`, audio hysteresis `au=0.20/0.05`.
- V frames contain `ev=1` ON, `ev=2` OFF, `ev=3` pitch changes. The large `val≈26300` on OFF is the **elapsed ON time in milliseconds**, not an anomalous 26 kHz pitch. ON episode times are reconstructed from event timestamps, not assuming evenly spaced audio updates.
- Two intended audio ON windows for every estimator, exclusively on ascents. **Zero extra ON episodes on descents or floor dwells** in this capture.
- D01 and C03 have identical start and stop timestamps to logged precision. S4/S5 are ~0.1–0.35 s later to turn ON and ~0.3 s later to turn OFF. **FUS starts ~0.75 s later and stays ON ~5–6 s longer after floor arrival** relative to D01/C03. This is a repeatable firmware estimator/configuration behaviour in this *clean acquisition* capture, rather than an observed I²C corruption event.

### Audio episode timing relative to pressure-derived motion threshold
| filter   |   ascent |    on_s |   off_s |   on_duration_s |   on_lag_to_pressure_threshold_s |   off_lag_to_pressure_threshold_s |
|:---------|---------:|--------:|--------:|----------------:|---------------------------------:|----------------------------------:|
| D01      |        1 |  52.001 |  78.301 |          26.3   |                            0.35  |                             1.375 |
| D01      |        2 | 136.901 | 163.323 |          26.423 |                            0.45  |                             1.623 |
| C03      |        1 |  52.001 |  78.301 |          26.3   |                            0.35  |                             1.375 |
| C03      |        2 | 136.901 | 163.323 |          26.423 |                            0.45  |                             1.623 |
| S4       |        1 |  52.151 |  78.626 |          26.475 |                            0.5   |                             1.7   |
| S4       |        2 | 137.023 | 163.626 |          26.602 |                            0.573 |                             1.925 |
| S5       |        1 |  52.151 |  78.551 |          26.4   |                            0.5   |                             1.625 |
| S5       |        2 | 137.051 | 163.651 |          26.6   |                            0.6   |                             1.95  |
| FUS      |        1 |  52.751 |  84.026 |          31.275 |                            1.1   |                             7.1   |
| FUS      |        2 | 137.626 | 168.801 |          31.175 |                            1.175 |                             7.1   |

### Tone-coded ascent plateau velocity (10 Hz sample-and-hold approximation)
- In each ascent, create a 10 Hz grid from 5 s after threshold crossing until 5 s before motion ends. Reconstruct last reported tone as hold-previous-value between `ev=1/3` tone events, within audio ON only. Convert to `v=(tone-500)/450` and compare with interpolated pressure-derived proxy. Descriptive data, **not true independent ground-truth algorithm RMSE**; pitch events are quantized/suppressed on small tone changes.

| filter   |   ascent |   n_0p1s_samples |   tone_derived_mean_mps |   pressure_ref_mean_mps |   mean_difference_mps |   MAE_mps |   tone_peak_mps |   tone_min_mps |
|:---------|---------:|-----------------:|------------------------:|------------------------:|----------------------:|----------:|----------------:|---------------:|
| D01      |        1 |              153 |                   1.667 |                   1.671 |                -0.004 |     0.072 |           1.753 |          1.587 |
| D01      |        2 |              153 |                   1.671 |                   1.668 |                 0.003 |     0.067 |           1.704 |          1.589 |
| C03      |        1 |              153 |                   1.66  |                   1.671 |                -0.011 |     0.068 |           1.713 |          1.589 |
| C03      |        2 |              153 |                   1.668 |                   1.668 |                 0     |     0.062 |           1.727 |          1.607 |
| S4       |        1 |              153 |                   1.663 |                   1.671 |                -0.008 |     0.062 |           1.722 |          1.609 |
| S4       |        2 |              153 |                   1.666 |                   1.668 |                -0.002 |     0.057 |           1.72  |          1.604 |
| S5       |        1 |              153 |                   1.664 |                   1.671 |                -0.007 |     0.071 |           1.738 |          1.618 |
| S5       |        2 |              153 |                   1.67  |                   1.668 |                 0.002 |     0.062 |           1.72  |          1.602 |
| FUS      |        1 |              153 |                   1.872 |                   1.671 |                 0.201 |     0.201 |           1.916 |          1.858 |
| FUS      |        2 |              153 |                   1.873 |                   1.668 |                 0.205 |     0.205 |           1.909 |          1.849 |

## Gate 4 — IMU evaluation
- At rest, six-axis output changes on every emitted IMU frame. The raw acceleration vector magnitude ranges from 0.9368 to 1.0653 g; no clipping seen at ±8g over this run.
- IMU body-frame acceleration projected onto the starting still-period specific-force axis shows clear acceleration/deceleration events at elevator transitions. This is a proxy: the projection assumes sensor orientation remains fixed.
- A rigorously timed algorithm latency benchmark requires an independent motion reference (elevator controller trigger, optical/position or logged floor event); pressure is a shared input to the barometric filters and therefore cannot serve as independent ground truth.

## Decision
**Acquisition PASS; elevator test accepted for estimator review.** The pressure/IMU sensors are reliable in this run. D01/C03 lead on alert timing; S4/S5 lag by hundreds of milliseconds in this recording; FUS is materially later and persists ~6s after ascent ends, despite no I²C defects. Investigate FUS estimator's stop-state / gravity compensation on this fixed, healthy dataset before increasing feature complexity. Keep Bus A at 100 kHz. Do not freeze a final algorithm until nuisance audio / flight-performance validation.

## Figures
- `elevator_225610_altitude_legs.png` — four floor-to-floor legs
- `elevator_225610_velocity_reference.png` — pressure-derived vertical velocity proxy
- `elevator_225610_audio_gates.png` — ON/OFF episodes
- `elevator_225610_tone_velocity_vs_pressure.png` — two ascents, tone velocity vs pressure proxy
- `elevator_225610_imu_acceleration.png` — projected IMU acceleration against pressure proxy

## Machine-readable results
- `elevator_225610_leg_metrics.csv`
- `elevator_225610_floor_dwell_metrics.csv`
- `elevator_225610_audio_events_summary.csv`
- `elevator_225610_tone_velocity_metrics.csv`
- `elevator_225610_diagnostics.csv`
