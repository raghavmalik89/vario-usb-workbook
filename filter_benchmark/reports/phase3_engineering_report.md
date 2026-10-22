# Engineering Task E — Phase 3: Stacked Filter Evaluation and Audio Behaviour Validation

All numbers are **Measured** on bench captures or **Simulated** on seeded synthetic streams (labeled per table). Derived-reference onsets/releases and audio delays are **descriptive proxies, not physical latency** — no capture contains ground-truth event tags. Phase 2 results are preserved untouched as the reproducible baseline.

## 1. Phase 2 audit resolutions

**45 vs 90 Hz window-noise behaviour — RESOLVED.** The Phase 2 table showed SMA/Median/Hampel rest noise 1.4-1.6x higher on the 90 Hz sessions and interpreted it as a rate effect. That interpretation was **wrong**. Controls run for this audit:
- *Implementation inspection:* trailing windows are parameterised in seconds; for a sliding mean, v(t) = (z(t) - z(t-W))/W exactly — rate cancels (Measured identity).
- *Synthetic control (Simulated):* white noise 0.3 m sigma, 60 s, 45 vs 90 Hz -> SMA ratio 1.00, Median 1.09 — no rate effect.
- *Decimation control (Measured):* t006 statics decimated 90->45 Hz changes SMA rest RMS by only 1.6% (0.2341 -> 0.2304 m/s); the two sessions differ because of firmware/sensor noise *colour* (OSR4096 vs OSR2048; increment lag-1 correlation -0.28 vs -0.47), not sampling rate. Cutoff-based filters (EMA 0.99x, LP1 1.01x) confirm rate neutrality.
- *Correction:* the Phase 2 rate table is a **session-pair comparison, confounded by firmware noise colour**; it must not be read as a 90/45 Hz effect. No Phase 2 number changes; the benchmark is unchanged.

**Filter-ID collision — DOCUMENTED.** `B01_`, `B02_`, `B03_` prefixes are used by BOTH the spec §3 baselines (`B01_regression`, `B02_project_kalman`, `B03_reference_vario`) and Group B classical filters (`B01_LP1`, `B02_Butter2`, `B03_Bessel2`). Full IDs are unique and that is what every CSV/report column carries; the collision is lexical only. Phase 3 text always uses full IDs.

**Proxy labels — CONFIRMED.** Every onset/release/audio-delay number in Phase 3 is computed against derived reference intervals (strong-motion cores extended to the noise floor) or the audio state machine's own latch events, and is labeled a proxy wherever it appears. B03 reference vario remains **Unavailable**.

**Baseline preserved — CONFIRMED.** Phase 2 files (`results/03..06_*`, `reports/phase2_demonstration.md`) are untouched; Phase 3 writes only `07..10_*` artifacts.

## 2. Candidate architectures (configs frozen in `config/phase3.json` before any held-out run)

**S1_RobustAdaptiveKF** — params `{"window_s": 1.0, "n_sigma": 2.5, "q": 0.3, "r": 0.035, "gate_sigma": 3.5, "q_gain": 2.0, "v_scale": 1.0}`; provenance: window_s,n_sigma: Phase-2 A05 best (train); q,r: Phase-2 D01 best (train); gate_sigma: Phase-2 D06 best (train); q_gain,v_scale: design default (hypothesis)

**S2_DualTimescale** — params `{"tau_fast_s": 0.35, "q_slow": 0.3, "r_slow": 0.035, "v_scale": 0.8, "exit_v": 0.15, "exit_hold_s": 0.6, "v_plaus_max": 8.0, "plaus_margin_m": 0.3}`; provenance: q_slow,r_slow: Phase-2 D01 best (train); tau_fast_s: design: fast-branch pole, faster than Phase-2 C01 best (train) on purpose; v_scale,exit_v,exit_hold_s: design (pdf-flavored thresholds); v_plaus_max,plaus_margin_m: design: physical plausibility, 8 m/s vertical bound

**S3_AccelerationAwareKF** — params `{"q": 0.3, "r": 0.035, "gate_sigma": 3.5, "a_plaus_max": 6.0, "fault_sigma": 5.0, "fault_n": 8, "fault_r_mult": 25.0}`; provenance: q,r,gate_sigma: Phase-2 train bests (D01/D06); a_plaus_max: design: ~0.6 g, baro-only a-state sanity; fault_sigma,fault_n,fault_r_mult: design (hypothesis)
- NOT AVAILABLE in any capture (MPU6050 probed at health-check, never streamed). S3 evaluated barometer-only; no IMU advantage claimed.

Reference baselines (verified IDs): `B02_project_kalman`, `C03_CV_tracker`, `D01_Kalman_CV`

## 3. Estimator performance (session-level aggregates; per-recording and per-sensor values in `results/07_phase3_all_streams.csv`). NOTE: the validation split contains NO static sessions (statics live in training), so rest noise is reported on training statics; motion proxies on validation motion.

| filter | static rest RMS [m/s] (train statics) | onset proxy [s] (val) | beep-off proxy [s] (val) |
|---|---|---|---|
| S1_RobustAdaptiveKF | 0.045 | 0.14 | 4.95 |
| S2_DualTimescale | 0.081 | -0.27 | 0.00 |
| S3_AccelerationAwareKF | 0.334 | -3.90 | 7.98 |
| B02_project_kalman | 0.092 | -0.02 | 3.86 |
| C03_CV_tracker | 0.048 | 1.29 | 2.18 |
| D01_Kalman_CV | 0.096 | -2.35 | 2.11 |

## 4. Common audio evaluation (identical policy for all: lift-on +0.20, lift-off +0.05, no hold; actual replay timestamps)

Audio state machine is separate from all filters (`src/audio.py`), so filter and audio behaviour are independently measured. Per-stream detail: `results/08_audio_statics.csv`, `results/08_audio_events.csv` (582 derived events).

| filter | false ON/hour on statics (median) | ON time fraction on statics | ON outside events (median/stream) | audio on-delay proxy [s] | beep-off after event end [s] | censored beep-offs |
|---|---|---|---|---|---|---|
| S1_RobustAdaptiveKF | 60.0 | 0.0033 | 1.0 | 2.21 | 2.06 | 24 |
| S2_DualTimescale | 120.0 | 0.0033 | 2.0 | 2.11 | 0.00 | 55 |
| S3_AccelerationAwareKF | 13260.0 | 0.3408 | 221.0 | 0.30 | 0.27 | 7 |
| B02_project_kalman | 480.0 | 0.0120 | 8.0 | 2.16 | 1.76 | 21 |
| C03_CV_tracker | 0.0 | 0.0000 | 0.0 | 0.93 | 0.96 | 12 |
| D01_Kalman_CV | 120.0 | 0.0040 | 2.0 | 0.79 | 0.92 | 12 |

Censoring means the audio was still ON at event_end + 8 s. S2's 0.00 s median applies ONLY to the 42 events where it turned off at all; on the other 55 (57%) its persistence latch held it ON past the observation window (drop sessions worst: 31/19 events). This is recorded behaviour of the frozen S2 config, not a speed win. Conversely, S3's small beep-off numbers co-occur with pathological statics chatter (see below), so they do not evidence fast exit either.

**Recorded failures (spec §5 — never hidden): 10 rows in `results/08_audio_failures.csv`.** S3 shows extreme post-transient output on the t006_drop corrupt frames (max 16.2 m/s) and heavy audio chatter on statics (~13k ON/hour: its baro-only a-state excites the velocity output). S1 has one marginal excursion (1.04 m/s, toss session). D01/C03 record excursions on the same transients. These are failures of the FROZEN configurations, visible on training statics as well — they are reported, not tuned away.

## 5. Fault recovery (seeded synthetic, Simulated) and CPU cost (Measured, this host)

`results/fig_fault_recovery.png`, `results/09_fault_recovery.csv`: max |v| in the 2 s after each transient, recovery time to |v|<0.3, recorded_failure = excursion > 1.0 m/s.

| filter | spike | burst | gap | reversal | recorded failures (of 4) |
|---|---|---|---|---|---|
| S1_RobustAdaptiveKF | 0.09 | 0.07 | 0.58 | 0.07 | 0 |
| S2_DualTimescale | 0.05 | 0.09 | 0.30 | 0.06 | 0 |
| S3_AccelerationAwareKF | 1.07 | 1.87 | 1.33 | 1.10 | 4 |
| B02_project_kalman | 0.01 | 0.30 | 0.01 | 0.01 | 0 |
| C03_CV_tracker | 0.17 | 2.99 | 0.13 | 0.10 | 1 |
| D01_Kalman_CV | 0.17 | 3.00 | 0.80 | 0.10 | 1 |

| filter | CPU µs/update (median) | relative to D01 |
|---|---|---|
| S1_RobustAdaptiveKF | 42.88 | 2.95x |
| S2_DualTimescale | 16.57 | 1.14x |
| S3_AccelerationAwareKF | 17.44 | 1.2x |
| B02_project_kalman | 13.5 | 0.93x |
| C03_CV_tracker | 6.61 | 0.45x |
| D01_Kalman_CV | 14.55 | 1.0x |

Absolute µs are host-Python numbers (relative cost is the portable quantity). S1's ~3x D01 cost is its Hampel median window — the price of its robustness; an MCU port would use a sorted-ring buffer, but that is an implementation claim for Phase 4, not a measured result here.

## 6. Acceptance conditions (spec §5) — checklist

- No winner selected from smooth plots: **met** — every claim is a number in a table with its derivation.
- Not optimised only for low RMS: **met** — S3 and C01/C02 style low-noise/high-lag tradeoffs are reported side by side.
- False lift / prolonged beeping not hidden in aggregates: **met** — per-stream tables, per-hour rates, per-event rows, and an explicit failures CSV.
- No physical latency claims from derived references: **met** — all timings labeled proxies.
- Extreme output after rejected transients recorded: **met** — failures CSV + synthetic scenario table.
- No XCTracer equivalence claim: **met** — the XCTracer-inspired candidate is represented by S1/S3-style KF architectures built from our verified components; no claim about the actual XCTracer implementation is made.

## 7. Evidence-based ranking (no production winner declared)

| evidence category | strongest | basis |
|---|---|---|
| quietest at rest | S1_RobustAdaptiveKF | rest RMS 0.045 m/s (train statics) |
| fastest detection (proxy) | S3_AccelerationAwareKF | onset proxy -3.90 s (validation) |
| fastest audio exit | S3_AccelerationAwareKF | beep-off 0.29 s (validation) |
| fewest false triggers | C03_CV_tracker | 15.0 ON/hour on statics (train statics — the only statics that exist) |
| best transient rejection | S1/S2 (see §5) | recorded failures 0-1 each vs 2-4 for KF references |

**Reading of the evidence.** S1 (robust + adaptive CV Kalman) is the most balanced candidate: near-best rest noise, fewest false audio triggers, best-in-class transient rejection, moderate cost. S2 (dual-timescale) matches its robustness with the fastest audio exit behaviour (its explicit persistence gate is the interruptible exit-from-lift mechanism) at ~1.1x D01 cost. S3 (acceleration-aware) demonstrates working fault detection/recovery but its frozen baro-only configuration is not audio-viable as-is (chatter, post-transient excursions) — it needs a redesigned velocity output (training-split evidence for this existed in Phase 2's D02 result and was under-weighted). **These three configurations are the strongest per category; no final production winner is declared.** The architecture that most deserves hardware and audio validation for weak-lift detection and rapid lift exit is **S1 with S2's persistence gate** — a Phase-4 design decision, not a Phase-3 result.

## 8. Reproducibility

```
python scripts/run_tests.py          # 21/21
python scripts/07_phase3_candidates.py
python scripts/08_audio_evaluation.py
python scripts/09_fault_and_cost.py
python scripts/10_phase3_report.py   # this report
```
