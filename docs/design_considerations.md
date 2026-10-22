# Design Considerations — vario estimator, audio, and IMU fusion

**Sources:** `USB Dongle Handoff.pdf` (vario failure-mode research, 7 pp) +
measured evidence from this bench rig (T-001…T-008 runs, see `analysis/data/`).
Status: considerations to keep in mind — not committed decisions.

## 1. Latency is a chain, and only part of it is the sensor/filter

The handoff identifies **three stacked delays**: estimator onset, estimator
*release* (filter keeps reporting climb after it ended), and the **audio
scheduler** (a scheduled beep continues after the estimate dropped — BlueFly
documents this explicitly; a faster barometer does not fix it).

Design direction from the handoff:
- **Interruptible audio scheduler**: lift-end must be able to cut the current
  tone immediately (or with a few-ms amplitude ramp against clicks).
- **Asymmetric audio**: fast onset on credible lift, fast release on lift end,
  hysteresis / confidence gating against chatter.
- Use the estimator's timestamped climb rate for audio directly — no further
  app-side smoothing (double filtering = double lag; XCTrack/Skydrop reports).

**Bench evidence:**
- Raw barometric sensing latency: **~10–30 ms** (step-drop test, T-004).
  Sensing is not the bottleneck; filtering is.
- Causal 0.3 s moving-average filter: **0.3 m/s cue at 133 ms** on a 1 m drop —
  already meets the <150 ms prototype target, baro-only.
- Release is the weak number: baro-only Kalman ring-down measured at
  **0.9–1.0 s** after impulsive events. Treat exit-from-lift as a first-class
  requirement with its own acceptance test (handoff's principal recommendation).

## 2. IMU fusion: promising on ramps, dangerous on impulses (ADR-011)

| | Elevator ramp | Step drop (impulsive) |
|---|---|---|
| Baro-only CV-Kalman | onset 0.9–1.6 s, rest 0.034 m/s | rest 0.25–0.64 m/s (ring-down) |
| Fusion, naive | onset **185 ms**, rest 0.049 m/s | **diverges** (10.5 m/s peaks, 3.7 m/s rest) |
| Fusion, spike-gated | onset **185 ms** | bounded, but noisier than baro-only |

- Fusion buys ~5–8× onset improvement on ramp motion — real value.
- Naive fusion **integrates catch impacts into velocity** and runs away;
  production fusion needs spike rejection plus bias tracking.
- Corroboration from the handoff: XCTrack developers report phone-IMU fusion
  experiments were unsuccessful; Kalmanfilter_altimeter_vario documents
  bias drift with environment. Our own clone MPU6050 shows **−37.5 dps gyro
  bias** — mounting and calibration dominate fusion quality.
- XC Tracer TEC note: vertical motion ≠ rising air (pitch/speedbar energy
  exchange). Our IMU cannot fix that without airspeed — product-scope note.

## 3. Architecture hypothesis to test (from handoff)

Timestamped raw P+IMU → **two estimators** (responsive + stable) →
**confidence-aware audio state machine** (fast trigger, fast release,
hysteresis, stale-data handling) → low-latency USB audio.
Test against a simpler well-tuned single estimator before committing.

## 4. Prototype performance targets (adopted from handoff §6)

| Metric | Target | Bench status |
|---|---|---|
| Pressure acquisition | 50–100 Hz | **45 Hz** OSR4096 ✓ (OSR1024 path → 100 Hz possible) |
| IMU acquisition | 200 Hz | **200 Hz** ✓ (200.0 Hz, ±1 µs jitter) |
| Estimator update | ≥100 Hz | 100 Hz replay ✓ |
| Onset latency (defined input) | <150 ms | **133 ms** baro-only, 1 m drop ✓ |
| Release latency (defined input) | <150 ms | ✗ 0.9–1.0 s measured — work item |
| Audio release after decision | <30 ms | not built yet |
| USB sample loss | 0 nominal | **0** across all runs (one t=0 transient) |
| False-beep rate | baseline first | rest noise **0.024 m/s** RMS @0.5 s smooth |

Report onset/release per signal strength (e.g. +0.2 vs +2.0 m/s) — a single
universal response number hides the trade-off.

## 5. Failure modes to test on this rig (handoff §5 → future tests)

- Pressure port vs wind/suction (blow across port at constant altitude)
- Phone/USB heat → slow drift (USB-powered warm vs cold comparison)
- Mechanical spikes (tap housing while recording)
- IMU tilt → false vertical accel (rotate without changing altitude)
- Gyro/accel bias vs temperature (long stationary logs)
- Sink→lift transition overshoot (replay + real)
- USB congestion → stale samples (already guarded by seq gaps)
- Sensor disagreement (disconnect one sensor, inject offsets)
