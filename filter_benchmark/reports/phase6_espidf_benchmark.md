# Bench 6 — ESP-IDF Filter Architecture Benchmark (Phase 6)

**Status:** complete frozen-configuration study + controls; **no estimator selected or frozen**.
**Hardware:** 2× MS5611 GY-63 clones (foam-covered, 25 mm apart) + MPU6050, ESP32-S3 @ 240 MHz, ESP-IDF firmware (`esp-idf/vario`, commit `8e79e68`).
**Chain:** baro 40 Hz + 10 Hz temp (N+4 clone read pipeline), IMU 100 Hz.
**Repro:** `filter_benchmark/bench6/` — `run6.py` → `equiv6.py` → `rate6.py` → `tune6.py` → `mcucpu6.py` → `figures6.py`. To re-run on the BMP581/LSM6DSV16X captures: register the new stems in `datasets.py` and re-run the same pipeline.

---

## 1. Objective

Re-evaluate the entire filter trade space on the clean ESP-IDF captures: 29 standalone filters, stacked S1–S5, CV/Kalman references, IMU-fusion candidates (37 candidates total). This is a fresh comparative study with corrected stream reconstruction — not an exercise to confirm previous rankings.

## 2. Datasets and quality

| Capture | Role | Split | Quality verdict |
|---|---|---|---|
| `20261023_221124_idf_elevator_2x` | elevator run 1 (4 legs, ±38.2 m, −1.72/+1.66 m/s) | train | CLEAN: 0 seq gaps, 0 corrupt |
| `20261023_221420_idf_elevator_2x` | elevator run 2 (same profile) | **validation** | CLEAN: 3 single-frame (20 ms) gaps |
| `20261023_215709_idf_handtest3` | static + gentle slow moves; the "toss" in the first analysis was a reference artifact (DEF-014, §3.5) | train | GOOD: 7 single-frame gaps |
| `20261023_234521_idf_p0fix_static` | static, 75.3 s | **validation** | CLEAN: 0 gaps |
| `20261023_234944_idf_bbuf_check` | static, 20.2 s | **validation** | CLEAN: 0 gaps |
| `20261023_221109_idf_elevator_2x` | — | excluded | ABORTED: USB-stall dropouts (DEF-008), 18 s |
| `20261023_215027_idf_foam_static` | — | excluded | CORRUPTED: 3703 P-seq gaps, ~74 s baro data in 366 s wall span, 6192 dup IMU ts |

Fault datasets are retained as documented fault-test data (`datasets.py` registry) but excluded from scoring. Both barometers are evaluated independently throughout (the two clones are known to differ; per-sid evaluation is deliberate, `results/64_stream_quality.csv`).

Legs (detected by the proven 1-s boxcar method on sid0 fixed-ISA altitude): run 1 — D1 9.9–33.8 s (−1.72 m/s), A2 51.6–76.2 s (+1.66), D3 95.0–119.0 s (−1.72), A4 136.8–161.3 s (+1.66); run 2 agrees to ±0.1 s. Handtest: under the corrected reference (§3.5) there are **no strong events** — the previously reported startup (0–3.8 s) and toss (148.2–151.9 s) were DEF-014 boundary artifacts, which the IMU refutes (|a|−g ≤ 0.17 m/s² and baro ±0.5 m at 144–152 s). Genuine slow blocks: 66–69.2 s and 107.9–114.3 s.

## 3. Methodology

### 3.1 Stream reconstruction (DEF-001 corrected)

All scoring uses `reference='isa'`: fixed 101325 Pa, compensation `analysis/common.py::compensate_ms5611` (firmware-exact transcription; per-capture PROM sidecars). The Phase 2–5 moving/session-mean reference (`p0 = mean(p[:2000])`) is retired for scoring — it is the DEF-001 defect. Duplicate timestamps are collapsed; absolute-vs-relative timestamp mixing eliminated (both previously bit us).

### 3.2 Era-correct chains for MCU equivalence

The firmware-era-specific reconstruction defects found in this study (Section 4) require two era-specific chains, used **only** for MCU equivalence, never for scoring:

- pre-p0fix captures (elevator runs, handtest3): `reference='moving_p0'` + `seed_d2=True` (firmware boot seed `d2 = prom[5]·256`, 20 °C, until first T frame).
- post-p0fix captures (p0fix_static, bbuf_check): `reference='isa_fw10'` + `seed_d2=True` — the fixed 101325 Pa reference in common-line units against the firmware's 10× pressure scale (DEF-011), scaling velocities by exactly 10^0.1903 = 1.5498.

### 3.3 Metrics and proxies

- **Static:** rest RMS/MAD/p99 of v, audio false-latch rate (policy +0.20 / +0.05 m/s).
- **Elevator:** per-leg median bias and RMS on the leg plateaus (|v_ref| > 0.5 m/s sustained ≥ 2 s), rise proxy (first crossing of 0.5·v_leg after leg start), exit proxy (sustained |v| ≤ 0.05 after leg end), overshoot. **The exit proxy is floored at ≈ 6.8 s for the whole KF family** by dwell wobble after floor stops — it is a dwell-stability proxy, not a lift-off measurement **[D]**.
- **Handtest:** slow-block bias (thermalling regime) and static-silence RMS / false-latch rate. Event-relative metrics (onset, release, toss recovery) were retired with DEF-014 — there are no events to score against.
- **Virtual audio** is scored separately from estimator output: ON-fraction in/outside events, missed lifts (ascent with ON-fraction < 0.5), dwell false-ON seconds, using the timestamped policy state machine (`metrics6.run_audio`).
- Elevator travel is a controlled-motion reference, not ground truth: no subsecond ground-truth response claims are made; rise/exit are labelled proxies **[D]**.

### 3.4 Controls

1. **Frozen configurations first** — every candidate runs its as-shipped config (registry defaults frozen since Phase 2; stacked configs frozen since Phases 3/4; firmware bank matches `config.h`).
2. **Tuning is a separate, leakage-controlled pass** — selection on train only, all configurations reported on validation (`tune6.py`, Section 8). Nothing tuned is frozen.
3. **Rate control** — decimation experiment (Section 6) before trusting cross-chain comparisons.
4. **MCU equivalence** before trusting any replay-vs-firmware comparison (Section 4).

### 3.5 DEF-014 — reference-smoother boundary artifact (post-commit correction)

The ±3 s Gaussian reference smoother behind the handtest event metrics (`np.convolve(..., mode="same")`) was zero-padded: the smoothed altitude ramps from ~50 % of true value over the first/last ~3 s of a stream, manufacturing phantom reference velocity at both boundaries. On handtest3 this created two fictitious "events" (startup 0–3.8 s; toss 148.2–151.9 s with a fictitious ≈ 4 m/s peak) and two fictitious slow blocks. Physical checks refute them: at 144–152 s the IMU |a|−g peaks at 0.17 m/s² and baro altitude moves ±0.5 m — **there was no toss**; the whole-session altitude span (10–140 s) is 3.36 m of gentle hand motion. Fix: the smoother now normalizes by the effective window weight (`bench6/streams.py::reference_v`); the archived Phase 2–5 `src/metrics.py` remains frozen as the historical artifact and is not used by bench 6 scoring. Impact: handtest onset/toss metrics are void; **elevator, static, MCU-equivalence, rate-control and CPU results are unaffected** (they never used the defective smoother). The composite ranking is re-computed with slow-block |bias| replacing the phantom onset metric (§9).

## 4. MCU-vs-Python replay equivalence (the queued formal check)

**Formal equivalence (post-p0fix era, Part B): PASS for D01.** On `p0fix_static` both sids: steady-state (t ≥ 8 s) tone-velocity bias ≤ 0.3 mm/s, p95 |error| = 1.0 mm/s, audio ON/OFF transition agreement 100% (24 and 37 transitions). C03 agrees to p95 71–105 mm/s (its gain-cache/refit quantization). S4/S5/FUS produce 0 steady audio transitions on static captures — nothing to score (honest vacuous result, not a pass).

**Harness validation (pre-p0fix era, Part A):** with the `moving_p0`+seed chain, D01/C03/FUS/S4/S5 reproduce MCU tones to p95 1.0–60 mm/s in the **frozen-p0 era (t ≥ 50 s) of every capture**. Three findings bound the rest:

1. **DEF-011 (new, major):** `baro_proc.c::compensate_pa` returns `p01mbar·10` — 10× the common.py pressure scale. Under the moving-p0 firmware the ratio cancelled (pre-p0fix MCU tones are true-scale); the p0fix hardcoded 101325 Pa (common-line units) against the still-10× pressure, so post-fix firmware velocities are scaled by exactly 1.5498 and absolute altitude is garbage (−23 725 m). Self-consistent within the firmware, so bench captures remain valid; replay equivalence must use `isa_fw10`.
2. **DEF-010 mechanism:** the boot d2 seed produces a capture-start altitude step → startup audio flap (tones clamp at +6.67 m/s) decaying over the first seconds; amplified to −1.5×10⁴ m/s transient by the DEF-011 scale. `seed_d2=True` reproduces it; startup (t < 8 s) is always reported separately, never hidden inside steady-state.
3. **Gate-decision chaos in the moving-p0 window (t < 50 s, pre-p0fix captures only):** S4/S5 (and to a lesser extent C03/FUS) replay tones diverge from MCU by seconds during the first legs. D01 — the plain Kalman inside both stacks — matches to ~1 mm/s *everywhere*, so the raw reconstruction is right; the divergence lives in discontinuous gate latches that amplify sub-LSB reconstruction micro-differences while the defective moving reference was active. It affects only the old-firmware equivalence bookkeeping, not any scoring (which uses fixed-ISA), and it disappears with the frozen reference.
4. **Asymmetric tone clamp (new observation):** implied v = (f−500)/450 with f clamped to [400, 3500] Hz represents v ∈ [−0.22, +6.67] m/s. The firmware **suppresses tones below 400 Hz**, so descents faster than −0.22 m/s emit no V-frames at all. MCU tone streams are blind to strong sink; replay audio metrics are the authoritative comparison for sink behaviour.

`results/65_mcu_equiv.csv`, log `65_mcu_equiv.log`, figure `fig13_mcu_equivalence.png`.

## 5. Frozen-configuration results

### 5.1 Static silence (rest velocity RMS, m/s — median over sessions/sids)

| 2016–2026 Phase 3/4 (45 Hz quiet house) | | Bench 6 (50 Hz foam, post-fix streams) | |
|---|---|---|---|
| B02_project_kalman 0.096 | | **B02_project_kalman 0.0165** | |
| C02_AlphaBetaGamma 0.021 | | C02_AlphaBetaGamma 0.0217 | |
| C01_AlphaBeta 0.026 | | C01_AlphaBeta 0.0282 | |
| S1_RobustAdaptiveKF 0.044 | | S1/S1P 0.0346 | |
| S5_LightGateKF 0.045 [M] | | FUS 0.0362 | |
| — | | S5 0.0369 / S4 0.0371 / S2 0.0373 | |
| C03_CV_tracker 0.048 | | C03 0.0485 | |
| D01_Kalman_CV 0.101 | | D01 0.0567 | |
| B02_Butter2 2.55 | | B02_Butter2 1.49 (see §6) | |

Audio false-latch on statics: 0 latches/h for the whole bank except the known chatterers — A03_Holt ~5615, S3 ~4450, FUS_Q10 ~2273, E06 111, D04 55 ON/h; S3 chatters on gate re-entry (fig14c). The unadaptive baselines (B00, E01–E03) chatter at 6400–6700/h and are out of the running on audio grounds alone.

### 5.2 Elevator controlled motion (run 1 medians over sids)

| candidate | leg RMS | leg bias | rise [D] | exit [D] | dwell false-ON s/run | missed |
|---|---|---|---|---|---|---|
| C03_CV_tracker | 0.089 | −0.006 | 1.27 | 6.53 | 2.18 | 0 |
| S2_DualTimescale | 0.091 | −0.005 | 1.34 | 4.44 | 2.01 | 0 |
| S4_FastSlowGated | 0.091 | −0.006 | 1.34 | 6.07 | 2.15 | 0 |
| E06_RobustAdapt | 0.092 | −0.005 | **1.18** | 6.80 | 2.33 | 0 |
| D01_Kalman_CV | 0.093 | −0.005 | 1.26 | 6.80 | 2.27 | 0 |
| S5_LightGateKF | 0.098 | −0.005 | 1.31 | 6.28 | 2.13 | 0 |
| S1_RobustAdaptiveKF | 0.097 | −0.005 | 1.30 | 5.18 | 1.97 | 0 |
| C01_AlphaBeta | 0.106 | −0.004 | 1.67 | **3.30** | 2.21 | 0 |
| C02_AlphaBetaGamma | 0.130 | −0.006 | 1.89 | 3.01 | 2.37 | 0 |
| FUS | 0.241 | −0.028 | 1.77 | 6.81 | 4.95 | 0 |
| B02_Butter2 | 1.489 | −0.006 | n/m | 6.91 | 19.9 | 0 |

Sustained climb and sustained descent track equally well for the whole viable family (|bias| ≤ 0.006 m/s on ±1.7 m/s legs; A03_Holt is the outlier at +0.183). Per-leg bias detail in fig05; leg-by-leg rows in `611_elevator_legs.csv`. **No filter missed any lift in either run** — elevator discrimination is saturated; discrimination power comes from handtest (§5.3) and static silence.

### 5.3 Handtest3 (gentle moves, slow blocks — no strong events)

- **Event metrics: void.** Under the corrected reference there are no events (DEF-014); the onset/release/toss figures from the first analysis are withdrawn. The IMU independently confirms no strong motion at 144–152 s (|a|−g ≤ 0.17 m/s²).
- **Slow sustained blocks (66–69 s, ref +0.25 m/s; 107.9–114.3 s, ref −0.17 m/s)** — the discriminative handtest metric. Median slow-block bias: B02 −0.014, C03 −0.030, E06 −0.032, D01 −0.037 m/s (tight tracking); C01 −0.064; S4 −0.116, S5 −0.121, FUS −0.182; **S2 +0.32 and S1 +0.63 m/s — both report positive climb through a slow *descent*** (S1: +0.44/+0.83 m/s against −0.17 m/s reference, with audio ON 0.60–0.72 of the block — a slow-descent false-lift; fig14a).
- **Static-silence false latches** (8–66 s window): bank ≈ 310–350/h except S2 18/h, S1 166/h, FUS 629/h; B02 277/h. Inflated by the short window and operator micro-movements before block starts; treat as relative ranking only.

### 5.4 Virtual-audio behaviour (separate from estimator output)

- Dwell false-ON between legs: 2.0–2.4 s/run across the viable family (FUS 4.95). This is the post-p0fix residual of the DEF-001/007 false-lift mechanism (Phase-era dwell false-lift was ~16.5 s/run on the defective reference).
- Audio ON-fraction over the handtest session (event windows void under DEF-014, so this is a session-wide figure): bank ≈ 0.14–0.16; S2 0.33 (freeze-trap keeps audio ON after motion). Session aggregates hide block-local behaviour — S1 is 0.16 session-wide but 0.60–0.72 **inside** the slow-descent block — which is exactly why estimator output and virtual audio are judged separately.
- Replay-vs-MCU ON/OFF agreement on elevator run 1 (frozen era): D01 84%, S4 43–75%, S5 33–62% within a ±30 ms window — dominated by transition timing near the asymmetric tone clamp, not by state disagreement (see fig01 strips).

## 6. Sampling-rate control (`rate6.py`)

Decimating the clean streams 2:1 (≈25/20 Hz) and 4:1 (10 Hz):

- **Seconds-parameterized filters (D01, C03, S4, S5, FUS) are near-invariant:** leg RMS 0.09→0.13–0.14 at 10 Hz, rise unchanged within ±0.1 s, exit +0.4–1.1 s (inside the dwell-wobble floor).
- **B02_Butter2 (fixed-coefficient, designed for the old ~10 Hz chain) does not transfer:** leg RMS 1.49 m/s at 50 Hz vs 0.32 at 10 Hz — its Phase 2–5 coefficients are wrong for the ESP-IDF rate. B02 is excluded from cross-chain comparisons.
- The ESP-IDF chain (50 Hz effective baro median, bimodal 20/40 ms; 100 Hz IMU) vs old Arduino (45/90 Hz, 200 Hz IMU) is therefore a non-issue for the Kalman/tracker/stacked families.

`results/66_rate_control.csv`, `661_rate_control_legs.csv`, fig15.

## 7. CPU cost

**On-target (B-line telemetry, post-p0fix build of record, 240 MHz ESP32-S3, medians):**

| estimator | sid0 avg/max µs | sid1 avg/max µs | budget (5000 µs tick) |
|---|---|---|---|
| D01 | 36/44 | 27/37 | 0.7 % |
| FUS | 33/37 | — | 0.7 % (baro side; IMU side uncharged — DEF-009) |
| S5 | 77/80 | 59/88 | 1.6 % |
| S4 | 97/101 | 69/82 | 2.0 % |
| C03 | 105/132 | 78/102 | 2.6 % |

Pre-p0fix B-lines carry the C03 refit-storm entry (~1329/2671 µs) as historical DEF-002 evidence; the fix is confirmed in the current build. Host-side relative costs for all 37 candidates: `63_cpu_host.csv`, fig11. **Efficiency is not a differentiator for any candidate under consideration** (worst case 2.6 % of tick).

## 8. Leakage-controlled tuning pass (`tune6.py`) — NOT a freeze

Grids: D01/C03 q∈{0.3,1,3,10}×r∈{0.02,0.035,0.07}; S5 q∈{0.1,0.3,1,3}; S4 tau_fast∈{0.2,0.35,0.5}. Composite (rest RMS + |leg bias| + false latches + handtest static terms; the phantom onset term auto-dropped after DEF-014) selected on **train only**; every configuration reported on validation:

| family | train pick | validation effect (vs frozen) |
|---|---|---|
| D01 | q=0.3 | rest RMS 0.057→0.028, exit 6.8→3.8 s, rise 1.19→1.70 s (real noise/latency trade) |
| S5 | q=0.1 | rest RMS 0.037→0.025, exit 5.7→3.7 s, rise 1.33→1.65 s |
| S4 | tau_fast=0.5 | mixed: exit better 5.0→4.5 s, rise/rms worse — not recommended |
| C03 | **frozen best** | all alternatives ≥ +18 % composite |

The train picks transfer to validation (no leakage signature). `67/68/69_*.csv`, fig18.

## 9. Rankings vs Phases 2–5

Composite rank (7 metrics, percentile-normalized, `612_rank_composite.csv`): **C03, C01, B02_project_kalman, E06, S2** top-5; S4 7th, S1 8th, D01 9th, S5 12th, FUS 21st (FUS_Q10 20th). This is the **corrected** composite — slow-block |bias| replaces the phantom onset metric (DEF-014). The first-analysis top-5 (C03, C01, S2, S1, S4) was partly an artifact of scoring filters against fictitious events while ignoring their real slow-block tracking error; S1 and S4 drop out of the top-5 on corrected scoring. Per-metric leaders: rest noise — B02_project_kalman/C02/C01; response — E06 (rise 1.18 s); exit — C02/C01 (but see dwell-wobble floor); slow-block tracking — B02/E06/C03/D01 (|bias| ≤ 0.04 m/s).

**Interpretation flag — S2 is 5th on the composite despite its known freeze-trap architecture defect (§10, documented since Phases 3/4).** The composite rewards its low static chatter, and its slow-block error (+0.32 m/s, descent block) is not weighted heavily enough to offset that; ranking position is not endorsement. Treat S2 as a defect reference, not a candidate.

What changed since Phase 4/5, and why:

1. **D01's rest floor improved 0.101 → 0.057 m/s** — the old number was measured on the defective moving/session-mean reference, not on D01 itself. On corrected streams D01 is mid-pack, not bottom.
2. **S5 (Phase-4 favourite) is no longer the stand-out:** 0.045 → 0.037 rest RMS is real, but the S1/S4/S5 cluster is tighter (0.035–0.037) and S5's slow-block bias (−0.12 m/s) is mid-pack. Phase 4's synthetic/event-replay "fastest exit" claim for S4 does not transfer to the dwell-wobble-floored elevator proxy — cross-phase exit numbers are not comparable by construction.
3. **S1's defect is now quantified, not shifted:** +0.63 m/s slow-descent bias with audio ON 0.60–0.72 inside the block — a slow-descent false-lift in exactly the regime a vario must get right (thermalling). The first analysis saw only its slow phantom onset (0.23 s); corrected scoring exposes the real failure.
4. **C03 rises to the composite top** — its Phase-2/3 weaknesses (CPU refit storm, fixed in DEF-002; false-lift sensitivity, fixed in DEF-001) were firmware-era artefacts. On corrected streams it is the best joint (noise, response, robustness, 2.6 % tick) point. This is exactly the "fresh study, not confirmation" outcome the task asked for.
5. **FUS shows no measurable benefit on these captures** (elev rms 0.24 vs 0.09 baro-only, dwell false 4.95 s, slow-block bias −0.18 m/s): quiet-building data has no vibration for IMU-aiding to cancel. The fusion value proposition remains open until real-flight/vibration data (BMP581/LSM6DSV16X phase).
6. **B02_Butter2's collapse is a rate artefact** (§6), not a filter verdict.

## 10. Failure modes (fig14)

- **S1 slow-descent false-lift (surfaced by the DEF-014 correction):** slow block 107.9–114.3 s (ref −0.17 m/s) → S1 outputs +0.44/+0.83 m/s, audio ON 0.60–0.72 of the block. The first analysis saw only a slow phantom onset; corrected scoring exposes this as the dominant S1 defect. S2 shares the symptom more mildly (+0.32 m/s block bias).
- **S2 freeze-trap** — documented architecture defect since Phases 3/4; retained as the defect reference. It appears 5th on the corrected composite regardless (§9 interpretation flag) — do not read that as rehabilitation.
- **S3 gate chatter** on static silence.
- **Startup flap** (DEF-010) at every capture start — audio valve should suppress; first seconds excluded from scoring.
- **DEF-011 scale** — post-p0fix firmware velocities ×1.5498, absolute altitude garbage; affects MCU-side absolute reporting only. **Gate: DEF-011 must be fixed before any further physical validation or absolute-altitude comparison** (§13).
- **Asymmetric tone clamp** — MCU tones blind below −0.22 m/s.

## 11. Limitations

- No subsecond ground truth on the elevator: rise/exit are labelled proxies **[D]**; exit is floored at ~6.8 s by dwell wobble.
- Handtest "static" window contains operator micro-movements; false-latch rates are relative rankings.
- Post-p0fix dynamic captures don't exist yet: S4/S5/FUS MCU audio equivalence could not be scored on transitions (vacuous, not failed).
- Handtest3 contains no strong events under the corrected reference (DEF-014): event-relative response latency is not measurable on the current capture set; a dedicated dynamic hand-capture (or the new-sensor phase) is needed to score abrupt-motion recovery.
- Fusion evaluation is baro-reference-bound; IMU-aiding value is not measurable on these captures.
- The two MS5611 clones differ (sid1 noisier); conclusions hold per-sid (all medians reported over both).
- Composite rankings are metric-set-sensitive: swapping the phantom onset term for slow-block |bias| (DEF-014 correction) moved S1/S4 out of the top-5. The per-metric tables (§5, `60/61/62/611_*.csv`) are the primary evidence; the composite is a summary, not a verdict.

## 12. Reproducibility

```
cd filter_benchmark/bench6
python -u run6.py        # frozen evaluation -> results/60-64*.csv + traces/
python -u equiv6.py      # MCU equivalence   -> results/65*.csv/.log
python -u rate6.py       # rate control      -> results/66*.csv
python -u tune6.py       # tuning pass       -> results/67-69*.csv
python -u mcucpu6.py     # on-target CPU     -> results/610_mcu_cpu.csv
python -u figures6.py    # figures           -> figs/fig01..fig18.png
```

## 13. Next phase (BMP581 + LSM6DSV16X)

Add the new captures to `datasets.py` (registry is the only sensor-specific file), re-run the pipeline, compare against this baseline. The archived reference firmware for the current sensor set is preserved at `esp-idf/firmware_archive/vario_idf_MS5611x2_MPU6050_p0fix_r8e79e68_20261023/` (binaries + SHA-256 + README) for A/B flashing; it is frozen and must not be modified.

**Hard gate — DEF-011 before further physical validation:** the 10× pressure-scale defect (velocities ×1.5498, absolute altitude garbage) must be corrected in the sensor-integration build before any further physical validation campaign, any absolute-altitude comparison, or any cross-sensor benchmark. The `isa_fw10` replay chain exists precisely to keep current-era equivalence measurable until then.

**Deferred:** the top-5 MCU efficiency benchmark (running C01/B02/E06/S2 on-target) is deferred until the BMP581/LSM6DSV16X arrive; existing MCU timing (§7, worst case 2.6 % of tick) shows processing performance is not the present bottleneck.
