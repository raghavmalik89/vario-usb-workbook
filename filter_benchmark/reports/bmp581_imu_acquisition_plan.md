# BMP581 and IMU Acquisition Plan (Phase 4 WP-C deliverable)

**Status: PLAN ONLY.** No BMP581 recordings exist; nothing in this document
is measured data. Every number below is a datasheet-derived *planning
estimate* (marked ⌀) or a hypothesis to be tested (marked ?). Fabricating
recordings or substituting theoretical noise for measurements is explicitly
out of bounds — the Phase-2..4 benchmark data policy applies unchanged.

## 1. Why BMP581

The research review (docs/Instant Variometer Filter Design.pdf) flagged two
MS5611-class weaknesses the BMP581 addresses on paper: much lower noise
floor (datasheet ⌀ 0.08 Pa RMS @ highest OSR ≈ ⌀7 mm altitude-equivalent
vs MS5611 ⌀10-24 mm depending on OSR) and faster conversion times enabling
genuinely higher ODR. Both claims are *unverified for our clones* — the
MS5611s we bench are GY-63 clones whose measured noise (rest RMS after
estimation ≈ 0.04–0.11 m/s at 45–90 Hz) and latency are what Phase 2/3
actually measured. The BMP581 matrix below exists to produce the same
*measured* numbers for a BMP581 before any fusion/filter decision cites it.

## 2. BMP581 hardware preconditions

- [ ] Module acquired with **IIR filter bypassed or documented** — the
      research review measured that BMP58x internal IIR (coefficient 7)
      alone costs ~198 ms of group delay; any IIR setting must be recorded
      per run, never left at an unknown default.
- [ ] Wiring plan: I2C on Bus B (GPIO6/7) or Bus A (GPIO4/5) of the
      existing t005 rig; address 0x46/0x47 (check AS pin). Third baro slot
      on the rig currently holds the never-detected GY-63 #3 — replace it.
- [ ] Firmware: extend the t005 streamer with a `#C,dev=?,type=bmp581`
      health line and `P,<seq>,<t_us>,<sid>,<raw>` frames using the
      BMP581's 24-bit pressure register, temperature-compensated per
      datasheet formula (⌀ to be validated against MS5611 colocated
      readings — the two sensors must agree on static altitude within
      ⌀±0.5 m before any noise comparison is meaningful).

## 3. BMP581 test matrix

Each cell is one capture, ≥120 s, rig stationary on the bench first
(statics), then repeated in the elevator for dynamic characterisation.
Naming: `bmp581_<rate>hz_<osr>_iir<iir>_<statics|elevator>`.

| # | ODR [Hz] | OSR (pressure) | IIR coeff | Purpose | Primary metrics |
|---|----------|----------------|-----------|---------|-----------------|
| 1 | 10 | x64 | off | lowest-noise reference floor | rest noise PSD, RMS |
| 2 | 50 | x32 | off | Phase-2-comparable rate | rest RMS vs MS5611 @50 Hz |
| 3 | 50 | x64 | off | OSR effect at fixed rate | OSR A/B at same ODR |
| 4 | 100 | x16 | off | research-PDF OSR2048@100 Hz analogue | rest RMS, latency proxy |
| 5 | 100 | x32 | off | rate×OSR trade-off corner | rest RMS, latency proxy |
| 6 | 100 | x64 | off | max quality @100 Hz | rest RMS, latency proxy |
| 7 | 200 | x8 | off | high-rate low-OSR corner | rest RMS, latency proxy |
| 8 | 200 | x16 | off | high-rate mid-OSR | rest RMS, latency proxy |
| 9 | 50 | x32 | 2 | IIR effect, weakest setting | group-delay estimate |
| 10 | 50 | x32 | 7 | IIR effect, the research-flagged coeff | group-delay estimate (expect ~198 ms per review — verify) |
| 11 | 100 | x32 | 4 | IIR at high rate | delay/noise trade-off |
| 12 | 50 | x16 | off | low-OSR floor at usable rate | rest RMS |

**Latency protocol (?):** elevator-door-open steps give a repeatable input
edge; cross-correlate the BMP581-derived altitude step against the MS5611
sid on the same rig (same physical event, two sensors) to get a *relative*
response delay. Absolute latency remains a derived proxy — same caveat as
all Phase 2–4 onset numbers.

**Noise protocol:** 120 s statics per cell; report raw-pressure altitude
RMS, 1-s smoothed derivative RMS (the metrics.reference_v pipeline), and
lag-1 autocorrelation of increments (the noise-COLOUR diagnostic Phase 3
needed to exonerate 45 vs 90 Hz — record it up front this time).

## 4. IMU acquisition plan (MPU6050 — already on the rig, never streamed)

The MPU6050 is probed at health-check (WHO_AM_I 0x68 @ 0x69) but no capture
contains IMU data. Phase 4 WP-C verified the fusion interface on synthetic
streams only (results/14_fusion_simulated.csv, all SIMULATED). To convert
the fusion interface from simulated to measured:

- [ ] Firmware: add IMU frames to the t005 streamer — proposal:
      `I,<seq>,<t_us>,<ax>,<ay>,<az>,<gx>,<gy>,<gz>` at 100 Hz (MPU6050
      DLPF 42 Hz, accel ±4 g, gyro ±500 °/s — settings recorded per run).
      500 Hz IMU is unnecessary for baro fusion at 50–100 Hz; 100 Hz with
      DLPF gives clean anti-aliased samples and halves the bandwidth cost.
      (har-in-air logs at 500 Hz IMU / 50 Hz baro if higher rate is wanted
      later — protocol-compatible extension.)
- [ ] Sync: IMU and baro timestamps from the same micros() clock; record
      worst-case jitter between the two interrupt paths (measure, don't
      assume).
- [ ] Captures to repeat from the existing set (same motions, now with IMU):
      1. benchstatics (bias estimation convergence — the WP-C rest gate
         needs long stationary data),
      2. elevator_2x (climb tracking — the scenario where SIMULATED fusion
         showed 50× lower velocity error; the real claim waits for data),
      3. drop + ControledMove (transient/fault gating under real accel).
- [ ] Analysis ready: `src/fusion.py` BaroImuFusion accepts the stream
      shape directly (timestamped baro + timestamped body accel + optional
      quat; gyro-based attitude estimation is OUT of scope for MPU6050
      unless a Madgwick/Mahony port is added — the X-up mounting from the
      handover means a static tilt table capture can substitute for
      attitude in early runs).

## 5. Acceptance gates (measured, not assumed)

1. BMP581 vs MS5611 colocated statics agree within ⌀±0.5 m — else
   calibration/formula error, matrix invalid.
2. Each matrix cell produces rest-RMS AND increment lag-1 autocorrelation
   before any filter conclusion cites it.
3. IMU captures pass the same data-quality gate as baro captures
   (scripts/02_validate_data.py extended for I-frames).
4. Fusion results on real IMU data get their own results CSV and report
   section; until then, results/14_* stays labelled SIMULATED.
