# Bench 7 — BMP581 Filter Benchmark Report

**Date:** 2026-10-25 · **Firmware:** `vario-idf 0.2.0` (r4103c86, BMP581 build) · **Pipeline:** `filter_benchmark/bench6/run7.py`, `figures7.py`
**Status:** engineering study — **no estimator is selected or frozen.**

---

## 1. Objective and scope

Re-evaluate the frozen filter trade space on the first BMP581 dataset and compare
against the corrected Bench 6 MS5611 baseline. The same 37 candidates (29
standalone + 6 stacked + 2 IMU fusion) run with **byte-identical frozen
configurations**; nothing was tuned. All known defects are respected by
construction: fixed-ISA reference (DEF-001), exact `common.py` scale transcription
(DEF-011, fixed in firmware this phase), corrected reference-smoother event
derivation (DEF-014), S2 retained as a labelled defect reference (freeze trap F1).

## 2. Datasets and experimental conditions

| Capture | Class | Duration (device) | Integrity |
|---|---|---|---|
| `20261024_231354_idf_bmp581_static` | static | 90.0 s | 0 gaps, 0 bad lines, f = 0.996 |
| `20261024_233753_idf_bmp581_handtest1` | handtest | 151.1 s | 0 gaps, 0 bad lines, f = 1.005 |
| `20261024_235054_idf_bmp581_elevator_2x` | elevator | 191.7 s | 0 seq gaps, 1 bad line, f = 1.110 (DEF-015) |

Operator-documented elevator conditions (part of the methodology): late-night
with the elevator effectively unused; rig near the cabin centre, away from
direct airflow and the laptop; route 14 → 1 → 14 → 1 → 14; deliberate settling
period before stopping the recording.

**DEF-015 (root-caused):** the host-side elapsed time of the elevator capture
(172.74 s) is ~19 s shorter than the device-timestamp span (191.69 s). Evidence
— (a) same-build static/handtest captures show f ≈ 1.00, exonerating the device
clock; (b) the file is internally perfect (every seq exactly +1, no gaps, no
backward jumps); (c) the USB TX ring high-water hit ≈ 101 KB (vs 0.6–1.1 KB in
the other captures; ring capacity 240 KB). Conclusion: the Windows host suspended
(USB selective suspend / sleep) for ~19 s while the operator was away; the
firmware kept streaming into the ring and the backlog drained on resume. **All
analysis uses device timestamps, which are intact.** An additional operator-settling
period explains the longer real duration but not the f-ratio by itself.

Sensor path: BMP581 on I²C bus B @ 0x47 (chipid 0x50, rev 0x32), OSR ×16/×2,
ODR 40 Hz, IIR bypass; on-chip compensation — `pressure_Pa = raw24/64`,
`temp_C = raw24/65536` (no PROM; DEF-010 d2-seed step does not exist for this
part). MPU6050 on bus A; IMU streamed at 100 Hz (200 Hz internal consumption —
by design, USB-bandwidth cap). One `bad line` in the elevator capture is a
capture-side artifact; seq accounting shows zero loss.

## 3. Stream integrity and sensor noise (measured, not assumed)

- Pressure sampling: 40.0 Hz, inter-frame dt exactly 25 ms on all captures.
- Static pressure noise ≈ **0.18–0.22 Pa RMS** (1.5–1.9 cm altitude) after a
  1 s local baseline removal — consistent with the operator's independent review.
- Static **velocity** noise at estimator outputs (70_static): best baro-only
  S1P/S2/S4/S5 ≈ 6.3–6.5 mm/s RMS; D01/C03 8.4 mm/s (their R=0.035 dominates
  sensor noise); FUS 6.7 mm/s; S3 37 mm/s (defect reference).
- **No candidate produced a single false audio ON in the 90 s static**
  (audio_false_on_per_hr = 0 for all 37) — the cleanest static result to date.

## 4. MCU ↔ Python equivalence, and the D01/C03 identity question

`73_mcu_equiv.csv` — python-replay audio episodes vs MCU V-frame episodes:

| Estimator | elevator episodes (MCU/py) | handtest episodes | max \|Δt_on\| | max \|Δt_off\| |
|---|---|---|---|---|
| D01 | 2 / 2 | 16 / 16 | 0.000 s | 0.000 s |
| C03 | 2 / 2 | 16 / 16 | 0.025 s | 0.025 s |
| S4 | 2 / 2 | 16 / 16 | 0.000 s | 0.000–0.075 s |
| S5 | 2 / 2 | 16 / 16 | 0.000 s | 0.000 s |
| FUS | **4 / 4** | **19 / 19** | 0.075 s | 0.100 s |

All MCU episodes are reproduced by the python replay within one to four baro
samples. FUS genuinely produces **two extra early ON episodes** (start-up
attitude/bias convergence, t ≈ 5–12 s) and matches them in replay — an estimator
behaviour, not a protocol artifact.

`74_d01c03_identity.csv` — the firmware pipelines are structurally independent
(separate structs, update functions, audio state), and the replay confirms the
identical MCU output is **mathematical, not a wiring bug**:

| Session | mean \|Δv\| (m/s) | max \|Δv\| (m/s) | episodes identical |
|---|---|---|---|
| static | 0.000 365 | 0.087 | yes (0 = 0) |
| handtest | 0.000 461 | 0.134 | same count; boundaries differ by ≤ 25 ms during fast hand moves |
| elevator | 0.000 151 | 0.151 | yes (2 = 2) |

C03 is the steady-state-gain CV tracker of the same model D01's time-varying
Kalman converges to; once gains settle (seconds), both are algebraically
near-identical, so identical threshold-crossing audio is expected. Divergence
only appears as sub-0.13 m/s wiggles during abrupt hand motion. **Consequence:
D01 and C03 are one architecture for ranking purposes; C03 delivers it at
55 µs/update vs D01's 131 µs (host replay cost) — there is no reason to carry
both into a final design.**

## 5. Elevator results (`71_elevator_summary`, `711_elevator_legs`, fig 71/73/74)

Four legs detected on the sid0 fixed-ISA altitude: −1.72, +1.67, −1.72, +1.67 m/s
(39–40 m per leg). The late-night elevator ran ~11% faster than the Bench 6
runs — a condition difference, accounted for in all comparisons (device-time
velocities only).

**Velocity accuracy during sustained motion** (median over legs):

| Candidate | rise_med (s) | exit_med (s) | RMS (m/s) | ascent bias (m/s) | descent bias (m/s) |
|---|---|---|---|---|---|
| C03 | 1.26 | 3.89 | 0.068 | +0.001 | −0.008 |
| D01 | 1.26 | 3.89 | 0.068 | +0.001 | −0.008 |
| S1P | 1.31 | **2.11** | 0.068 | +0.001 | −0.006 |
| S4 | 1.36 | **2.11** | 0.072 | +0.001 | −0.008 |
| S5 | 1.36 | 3.08 | 0.069 | +0.001 | −0.007 |
| S2 (defect ref) | 1.36 | 2.11 | 0.072 | +0.001 | −0.008 |
| S3 (defect ref) | 0.53 | 6.61 | 0.139 | −0.001 | +0.016 |
| FUS | **1.80** | **7.44** | **0.243** | **+0.201** | **−0.250** |
| FUS_Q10 | 1.14 | 4.43 | 0.105 | +0.061 | −0.091 |

- **Audio correctness: every baro-only candidate missed 0 lifts and produced 0
  false audio seconds** (no dwell false-ON, no descent spurious ON, silent at
  both floor-1 stops). Confirms the operator's independent review.
- **FUS is systematically worse here, measurably:** ~+0.20/−0.25 m/s sustained
  bias (12–14% overshoot), 3.6× higher leg RMS, slowest rise, 7.4 s median exit
  (vs 2.1 s for the best), plus the two start-up false ONs and ON-extensions of
  ~5–6 s after each top-floor stop. FUS_Q10 (labelled exploratory, Phase 5)
  improves every column but remains worse than all baro-only candidates on this
  motion profile.
- Onset "rise" and exit times are **pressure-derived latency proxies** measured
  against the 1 s reference smoother — not ground truth. The reference itself has
  a measurable group delay; relative ordering between candidates is meaningful,
  absolute sub-second response is not claimed.

## 6. Handtest results (`72_handtest`, fig 72)

17 detected events; one long slow block (61.9–129.8 s) — the thermalling-regime
proxy that exposed S1 historically.

| Candidate | onset_med (s) | release_med (s) | slow-block audio ON frac | slow bias (m/s) | static_rms in-test |
|---|---|---|---|---|---|
| D01/C03 | 2.10 | 1.00 | 0.431 | +0.031 | 0.0057 |
| S1P | −0.91 | 0.33 | 0.146 | −0.097 | 0.0036 |
| S4 | 2.20 | 0.58 | 0.438 | −0.015 | 0.0037 |
| S5 | 2.25 | 0.43 | 0.426 | +0.011 | 0.0037 |
| S2 (**freeze F1**) | 2.20 | 0.55 | **0.934** | **+0.706** | 0.0037 |
| S3 | 1.82 | 1.00 | 0.400 | −0.111 | 0.0328 |
| FUS | 1.60 | 1.00 | 0.445 | +0.088 | 0.0038 |

- **S2's freeze defect reproduces on the BMP581 rig**: slow-block bias +0.71 m/s
  with audio stuck ON 93% of the block (fall-time metric undefined — frozen).
  S2 stays excluded from any ranking; the defect is sensor-independent
  (architectural), as suspected.
- S1P's anticipatory onset (−0.91 s) is the persistence smoother leading the
  reference — a methodology-visible bias, not an error; its in-motion RMS is the
  lowest of all (0.342 m/s vs 0.92 for D01).
- S4/S5 equal or beat D01/C03 on every handtest column at ~1.2× the CPU cost.
- Recovery after abrupt movement is clean for all non-defect candidates; FUS
  settles fine after warm-up but shows the largest motion RMS (1.80 m/s).

## 7. Cross-sensor comparison (fig 75)

Same frozen configs, different days/conditions — **indicative, not controlled**:

- **Stationary noise (estimator-output RMS):** BMP581 improves every
  candidate ~6×: D01 0.0575 → 0.0084 m/s, C03 0.0492 → 0.0084, S4 0.0380 →
  0.0065, S5 0.0375 → 0.0065, FUS 0.0369 → 0.0067. The relative ordering is
  unchanged (S4/S5/S1P quietest), but the gated designs' advantage shrinks in
  relative terms because D01/C03's assumed R=0.035 dominates less over the
  much-lower sensor noise. Tuning-relevant for later phases: optimal Q/R for
  a BMP581 front-end differ from the MS5611-clone era.
- **Static false audio:** MS5611 D01 flapped (76 false ON/h); on BMP581 **all
  37 candidates score exactly 0** — the clone noise was the driver, not the
  estimator.
- **Onset rise:** essentially unchanged across sensors (~1.26–1.36 s).
- **False audio:** comparable for baro-only candidates; FUS accumulates more on
  the BMP581 elevator (7.5 s vs 5.1 s) — its extra start-up episodes add to the
  delayed-OFF behaviour.

## 8. Does IMU fusion provide a measurable advantage? (this rig, this data)

**No advantage was measured on any scored column; measurable disadvantages
were.** Against baro-only candidates on identical inputs FUS shows: higher
sustained-motion bias (+0.20/−0.25 m/s), 3.6× leg RMS, slowest onset and
exit, start-up false ONs, and ~9× the host replay cost (505 vs 55 µs). The
MPU6050's 100 Hz class IMU and the Madgwick attitude chain add latency and
convergence transients without improving on a well-gated baro-only estimator in
controlled vertical motion. This verdict is bounded: strong turbulence, launch
dynamics and car/ground vibration are untested, and the LSM6DSV16X (with its
much lower noise and higher rate) has not been evaluated. Keep fusion candidates
open.

## 9. Changes vs Bench 6 ranking

1. Absolute noise levels dropped ~6× across the board (clone-limited →
   estimator-limited regime); relative ordering of the leaders is unchanged
   (S4/S5/S1P quietest at 6.3–6.5 mm/s, D01/C03 8.4 mm/s) and no leader is
   dethroned on behaviour columns. The regime change matters for future Q/R
   tuning more than for ranking.
2. FUS's relative position worsens measurably (Bench 6 already flagged its
   exit-delay; the BMP581 run quantifies its sustained-motion bias).
3. D01 ≡ C03 established as one architecture — a structural simplification of
   the trade space, not a behaviour change.
4. S2 freeze confirmed sensor-independent; S3 remains the worst non-defect-free
   stacked design (high noise, 6.6 s exit).

## 10. Limitations

- No flight data; all latencies are pressure-derived proxies against a smoothed
  reference. No sub-second ground truth is claimed anywhere.
- Single elevator, single evening, faster cabin than Bench 6; single handtest.
- BMP581 ran without the second barometer (no cross-baro redundancy check).
- The elevator capture's wall-clock segment durations are unreliable (DEF-015);
  device-time analysis is unaffected.
- MCU CPU numbers for this build exist only from B-lines of these captures;
  the deferred top-5 MCU efficiency benchmark remains future work.

## 11. Reproduction

```bash
# from filter_benchmark/bench6/
python -u run7.py          # streams -> metrics -> results/7*.csv + traces7/
python figures7.py         # figs7/71..75
```

Registry additions in `datasets.py` are the only sensor-specific step; the
runner skips absent sids, so the same scripts accept future LSM6DSV16X captures.

## 12. Phase gate

- MCU top-5 efficiency benchmark: **deferred** (operator decision; processing is
  not the current bottleneck).
- LSM6DSV16X integration + real-flight recording: future stages.
- **No estimator was selected or frozen in this phase.**
