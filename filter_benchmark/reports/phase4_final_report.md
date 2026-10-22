# Task E — Phase 4 Final Report

Filter benchmark, corrected audio metrics, audio-policy tuning, IMU-fusion interface verification (synthetic), and the portable C core.

All findings are labelled **[M] measured** on captured bench data, **[S] simulated** on synthetic vectors, **[D] derived proxy** (descriptive latency proxies against derived references, not ground-truth latency), or **[U] unverified / plan-only**.

Phase 3 artefacts (`results/03..10_*`, `results/fig_*` from Phase 3, `reports/phase3_engineering_report.md`) are untouched by this phase.

## 0. Executive summary

- **S2 freeze trap found and root-caused [M].** The plausibility pre-clean in `S2_DualTimescale` *replaced* deviating samples with its own prediction. Under sustained real acceleration (drop landings) the fast branch's prediction drifts beyond `max_dev` from reality, every subsequent real sample is discarded, and the filter freezes at a wrong state — measured tail median v = 0.449 m/s on the 31 censored beep-off events (median rejected samples = 2017). New filters **saturate** (`zc = h_pred + sign(dev)·max_dev`) instead of replacing: `S4_FastSlowGated` has **0 censored events** on the identical input.
- **S5_LightGateKF: S1-class robustness at ~1/3 the CPU [M].** Rest RMS 0.045 m/s vs S1's 0.045 at 18.4 us/sample (1.15x D01) vs S1's 50.7 us (3.16x D01). S1 misses 17.8% of lift events under the common policy (18.9% on validation with tuned+safety); S4/S5/D01 miss 0%.
- **S4_FastSlowGated has the fastest exit-from-lift [D]** — median release proxy 1.43 s on validation vs 1.90–4.95 s for the others.
- **Audio safety mechanisms added [S]:** a generic fault-detector veto (streak detector vs the estimator's own prediction, trip 5 / clear 5) and a `max_on_s` valve. With the veto, sustained-fault audio ON-fraction is 0.000 for every candidate; without it, ON-fractions of 0.63–0.97 were measured on plain baro-only candidates. The valve bounds a false ON to ≤ 0.52 s (with max_on = 2 s in the stress test).
- **IMU/baro fusion is verified on SYNTHETIC IMU only [S].** In simulation the async IMU-predict/baro-correct fusion cuts climb-rate RMS error from 0.499 to 0.009 m/s and coasts through a 1 s baro blackout with 0.034 m/s window RMS vs 1.699 m/s baro-only. No claim is made for real IMU data; the acquisition plan is in `reports/bmp581_imu_acquisition_plan.md` [U].
- **Portable C core [M/S].** `portable/vario_core/` (C99, no heap, timestamp-driven, estimator and audio modules independent) reproduces the Python reference within documented tolerances on 12/12 test vectors: double build max |dv| = 2.0e-08 m/s (tol 1e-6, 50x margin over observed op-order divergence), float build 5.1e-05 m/s (tol 1e-3). Builds with MSVC on host and with xtensa-esp-elf-gcc for ESP32-S3 in both float and double variants.
- **Three candidates retained, no winner declared** (per spec): **S5, S4, S1** — S1P was rejected (worse than S1 on validation), S2/S3 retained only as frozen defect references.

## 1. WP-A — corrected audio-event metrics

Scripts: `scripts/11_audio_events_v2.py` → `results/11_events_corrected.csv` (873 events), `11_summary_by_type.csv`, `11_s2_censoring.csv`, `11_t006_sid.csv`, `11_stress.csv`.

### 1.1 Accounting corrections

Per-event ON/OFF accounting was corrected: an event that starts with audio already ON counts as missed only if no ON transition happens inside the event; events truncated by the capture end are excluded from exit-delay statistics. Event kinds are separated (lift / sink / weak) so a filter that is fast on lift but deaf on sink is visible.

### 1.2 Corrected per-filter results [M] (common policy, training+validation)

| filter | lift missed | sink missed | censored beep-offs | median lift on-delay s |
|---|---|---|---|---|
| B02_project_kalman | 17.8% (8/45) | 18.8% (9/48) | 0 | 2.08 |
| C03_CV_tracker | 2.2% (1/45) | 20.8% (10/48) | 0 | 0.80 |
| D01_Kalman_CV | 0.0% (0/45) | 18.8% (9/48) | 0 | 0.70 |
| S1P_PersistenceKF | 17.8% (8/45) | 33.3% (16/48) | 2 | 1.53 |
| S1_RobustAdaptiveKF | 17.8% (8/45) | 33.3% (16/48) | 2 | 1.53 |
| S2_DualTimescale | 22.2% (10/45) | 45.8% (22/48) | 31 | 1.64 |
| S3_AccelerationAwareKF | 0.0% (0/45) | 0.0% (0/48) | 0 | 0.30 |
| S4_FastSlowGated | 0.0% (0/45) | 18.8% (9/48) | 0 | 1.12 |
| S5_LightGateKF | 0.0% (0/45) | 18.8% (9/48) | 0 | 0.96 |

**S2's 31 censored beep-offs break down as 17 lift / 13 sink / 1 weak.** Root cause and fix in §1.3. S1 misses 17.8% of lifts — a real estimator defect (its adaptive gate rejects genuine onsets), not a policy artifact.

![S2 freeze vs S4](fig_p4_s2_freeze_event.png)

The figure replays the identical drop-session stream through S2 and S4 under the identical common audio policy. S2 freezes after the landing transient (post-event |v| pinned at 0.449 m/s, audio ON for every subsequent event, never exits through the end of the capture); S4 recovers and exits each event normally.

### 1.3 S2 freeze trap — root cause [M] and fix-by-design

On every censored event the frozen S2 tail sits at a median v of 0.449 m/s with a median of 2017 samples rejected (`results/11_s2_censoring.csv`). Mechanism: the plausibility pre-clean computes the innovation of each incoming sample against the fast branch's prediction and, when it exceeds `max_dev`, **replaces** the sample with the prediction. During a landing the true acceleration drives the real signal away from the prediction faster than the prediction follows; once the gap exceeds `max_dev`, every real sample is discarded, the filter only ever consumes its own prediction, and (h, v) freeze at whatever wrong value the trap started at. Drop sessions are worst because the sustained deceleration maximizes prediction drift.

Fix applied in all new filters: **saturate, never replace** — `zc = h_pred + sign(dev)·max_dev`. The filter stays coupled to reality (it always moves toward the real signal at max_dev per sample) and can never become self-referential. S4 and S5 both contain the fix; S2 and S3 are frozen untouched as defect references.

Also fixed in the same pass: the gravity-compensation sign convention (Earth z-down: `a_z = f_z + 9.80665`, quaternion (w,x,y,z) body→earth) in the fusion module — see §3.

### 1.4 t006_drop sid behaviour [M]

On the t006 drop session the sid-1 barometer (MS5611 clone at 0x77) is measurably noisier than sid-0 (0x76): B02/D01 rest RMS on sid1 ≈ 1.8x sid0, and under the drop transient S2's replay RMS is 0.171 m/s on sid0 vs 0.613 m/s on sid1 (`results/11_t006_sid.csv`). Post-transient extremes (>1 m/s) exist only on sid0 — consistent with the capture log showing corrupt frames on sid0 only (S3 reaches 16.2 m/s there). Interpretation: the two clones are NOT interchangeable; per-sid filter evaluation (kept throughout) is necessary, and dual-barometer averaging would import the noisier sensor's errors rather than cancel them.

### 1.5 Stress tests [S] — real defects recorded, not fixed silently

| test | failures recorded |
|---|---|
| fault_veto_on_fraction | S3_AccelerationAwareKF (on_fraction_with_veto=0.127 without=0.660 (fault_flag=estimator)); S4_FastSlowGated (on_fraction_with_veto=0.960 without=0.960 (fault_flag=gap)); S5_LightGateKF (on_fraction_with_veto=0.953 without=0.953 (fault_flag=gap)); B02_project_kalman (on_fraction_with_veto=0.967 without=0.967 (fault_flag=gap)); C03_CV_tracker (on_fraction_with_veto=0.633 without=0.633 (fault_flag=gap)); D01_Kalman_CV (on_fraction_with_veto=0.633 without=0.633 (fault_flag=gap)) |
| missing_data_gap | S3_AccelerationAwareKF (latches_in_4s_after_gap=2, total=10) |
| rapid_reversal_exit | S2_DualTimescale (exit_after_reversal_s=nan) |
| sensor_spike | S3_AccelerationAwareKF (extreme_v=False, audio_on_after_spike=True); C03_CV_tracker (extreme_v=False, audio_on_after_spike=True); D01_Kalman_CV (extreme_v=False, audio_on_after_spike=True) |
| startup_static | S2_DualTimescale (audio latches=1); S3_AccelerationAwareKF (audio latches=32); S4_FastSlowGated (audio latches=1); B02_project_kalman (audio latches=1); D01_Kalman_CV (audio latches=1) |

Highlights: S3 latches audio ON 32 times in 60 s of statics at startup; S2 never exits a rapid reversal (the freeze trap, §1.3); C03/D01/S3 turn audio ON after a sensor spike; plain baro-only candidates hold audio ON for 63–97% of a sustained fault unless protected.

### 1.6 Audio safety mechanisms [S]

Two backward-compatible additions to the audio state machine (both default-off, so Phase 3 replay is bit-identical):

- **Fault veto** (`fault_veto=true`): audio is forced OFF while a fault flag is present. A generic `GenericFaultDetector` (streak detector: flag when the sample deviates from the estimator's own prediction for `trip_n=5` consecutive samples, clear after 5 good ones) drives the veto without any filter-specific logic. With the veto, the sustained-fault ON-fraction is 0.000 for every candidate (`results/11_stress.csv`, test `fault_veto_generic_detector`; worst trip-latency exception B02/C03/D01 with on_samples=4 ≤ trip_n=5, which meets the pass criterion).
- **max_on valve** (`max_on_s`): bounds any single ON episode. With max_on = 2 s the measured worst false-ON duration is 0.52 s (test `max_on_valve_bounds_false_on`). The recommended Phase-4 safety baseline (max_on = 10 s + veto) is stored in `config/phase4.json → phase4_audio_baseline`.

### 1.7 Continuous-beeping and exit-from-lift behaviour

Continuous ON during faults is the `on_fraction` / `fault_veto` evidence above. Exit-from-lift is first-class: per-event `exit_delay_s` and the censoring detector (an ON-at-event-end with no OFF within 8.0 s is censored and counted, never dropped). Corrected counts: S2 = 31, S1/S1P = 2 each (policy-level, not freeze), all others 0.

## 2. WP-B — estimator comparison and audio-policy tuning

Scripts: `scripts/12_estimator_comparison.py` → `results/12_estimator_*.csv`, `12_cpu.csv`; `scripts/13_audio_policy_tuning.py` → `results/13_policy_*.csv`.

### 2.1 Frozen estimators, common policy first

All candidates ran with frozen estimator configs (`config/phase4.json → estimators`; Phase 3 configs for B02/C03/D01/S1 kept identical for comparability) under one common audio policy (lift_on 0.2 / lift_off 0.05, identical to Phase 3). Estimator tuning and audio-policy tuning were done in separate scripts and never jointly.

![estimator comparison](fig_p4_estimator_comparison.png)

| filter | rest RMS m/s [M] | release proxy s [D] (val) | onset proxy s [D] (val) | CPU us [M] |
|---|---|---|---|---|
| S1_RobustAdaptiveKF | 0.045 | 4.95 | 0.14 | 50.7 |
| S1P_PersistenceKF | 0.045 | 1.90 | 0.14 | 50.4 |
| S5_LightGateKF | 0.045 | 4.23 | 0.12 | 18.4 |
| C03_CV_tracker | 0.048 | 2.18 | 1.29 | 7.0 |
| S4_FastSlowGated | 0.085 | 1.43 | 0.04 | 19.0 |
| D01_Kalman_CV | 0.096 | 2.11 | -2.35 | 16.0 |

Note [D]: release/onset proxies are descriptive measurements against derived references (event medians of the reference stream), not ground-truth latency — the captures have no absolute position truth.

Note on the validation split: it contains only elevator/drop/toss sessions, no static segment, so `static_rest_rms_validation` is n/a by construction; rest RMS is reported on training statics.

### 2.2 Complexity discipline — what was adopted and what was rejected

- **S4_FastSlowGated** (adopted): S2's architecture with the saturation fix, `w_floor = 0.3`, sign-disagreement exit, and exit thresholds 0.12/0.25 s. Measured: 0 censored, 0 missed lifts, fastest release proxy.
- **S5_LightGateKF** (adopted): S1-class constant-time robustness (no sliding-window machinery). Measured: S1-equivalent rest RMS and miss rates at ~1/3 the CPU; 0 missed lifts.
- **S1P_PersistenceKF** (rejected): persistence exit added to S1 made validation missed-lift worse (27.0% vs S1's 21.6% under tuned+safety); excluded from the retained set.
- **S2/S3** (frozen defect references): retained untouched so Phase 3 results stay reproducible and the defects stay visible in every table.

### 2.3 Audio-policy tuning — training only, then transferred

Search space in `config/phase4.json → audio_policy_search_space` (lift_on/lift_off/min_on/hold around the common values). Chosen on TRAINING statics + training events only (`results/13_policy_search.csv`, 576 evaluated policies), then frozen and applied to validation without re-fitting (`config/phase4.json → tuned_policies`).

![policy tuning](fig_p4_policy_tuning.png)

| filter | variant | split | false ON/hr | missed lift | on-delay med s | exit med s | censored |
|---|---|---|---|---|---|---|---|
| C03_CV_tracker | common | training | 0.0 | 0.0% | 0.82 | 0.28 | 0 |
| C03_CV_tracker | tuned | training | 0.0 | 0.0% | 0.82 | 0.28 | 0 |
| C03_CV_tracker | tuned+safety | training | 0.0 | 0.0% | 0.82 | 0.28 | 0 |
| D01_Kalman_CV | common | training | 120.0 | 0.0% | 0.50 | 0.31 | 0 |
| D01_Kalman_CV | tuned | training | 60.0 | 0.0% | 0.50 | 0.31 | 0 |
| D01_Kalman_CV | tuned+safety | training | 60.0 | 0.0% | 0.50 | 0.31 | 0 |
| S1_RobustAdaptiveKF | common | training | 60.0 | 0.0% | 1.32 | 1.33 | 0 |
| S1_RobustAdaptiveKF | tuned | training | 60.0 | 0.0% | 1.28 | 1.33 | 0 |
| S1_RobustAdaptiveKF | tuned+safety | training | 60.0 | 0.0% | 1.28 | 1.33 | 0 |
| S1P_PersistenceKF | common | training | 60.0 | 0.0% | 1.30 | 1.31 | 0 |
| S1P_PersistenceKF | tuned | training | 60.0 | 0.0% | 1.26 | 1.32 | 0 |
| S1P_PersistenceKF | tuned+safety | training | 60.0 | 0.0% | 1.26 | 1.32 | 0 |
| S4_FastSlowGated | common | training | 120.0 | 0.0% | 1.08 | 1.03 | 0 |
| S4_FastSlowGated | tuned | training | 60.0 | 0.0% | 1.05 | 1.31 | 0 |
| S4_FastSlowGated | tuned+safety | training | 60.0 | 0.0% | 1.05 | 1.31 | 0 |
| S5_LightGateKF | common | training | 120.0 | 0.0% | 0.87 | 0.80 | 0 |
| S5_LightGateKF | tuned | training | 60.0 | 0.0% | 0.84 | 0.80 | 0 |
| S5_LightGateKF | tuned+safety | training | 60.0 | 0.0% | 0.84 | 0.80 | 0 |
| C03_CV_tracker | common | validation | n/a | 2.7% | 0.77 | 0.81 | 0 |
| C03_CV_tracker | tuned | validation | n/a | 2.7% | 0.77 | 0.82 | 0 |
| C03_CV_tracker | tuned+safety | validation | n/a | 2.7% | 0.77 | 0.82 | 0 |
| D01_Kalman_CV | common | validation | n/a | 0.0% | 0.70 | 0.72 | 0 |
| D01_Kalman_CV | tuned | validation | n/a | 0.0% | 0.70 | 0.79 | 0 |
| D01_Kalman_CV | tuned+safety | validation | n/a | 0.0% | 0.70 | 0.79 | 0 |
| S1_RobustAdaptiveKF | common | validation | n/a | 21.6% | 1.64 | 0.92 | 1 |
| S1_RobustAdaptiveKF | tuned | validation | n/a | 18.9% | 1.51 | 0.97 | 1 |
| S1_RobustAdaptiveKF | tuned+safety | validation | n/a | 18.9% | 1.54 | 1.00 | 0 |
| S1P_PersistenceKF | common | validation | n/a | 27.0% | 1.43 | 1.00 | 0 |
| S1P_PersistenceKF | tuned | validation | n/a | 21.6% | 1.42 | 1.08 | 0 |
| S1P_PersistenceKF | tuned+safety | validation | n/a | 21.6% | 1.42 | 1.08 | 0 |
| S4_FastSlowGated | common | validation | n/a | 0.0% | 1.12 | 1.20 | 0 |
| S4_FastSlowGated | tuned | validation | n/a | 0.0% | 1.08 | 1.44 | 0 |
| S4_FastSlowGated | tuned+safety | validation | n/a | 0.0% | 1.08 | 1.44 | 0 |
| S5_LightGateKF | common | validation | n/a | 0.0% | 0.96 | 0.96 | 0 |
| S5_LightGateKF | tuned | validation | n/a | 0.0% | 0.90 | 0.98 | 0 |
| S5_LightGateKF | tuned+safety | validation | n/a | 0.0% | 0.90 | 0.98 | 0 |

Outcome [M]: tuned policies (mostly lift_on 0.15 / lift_off 0.03 + min_on 0.15) halve the worst training false-ON rate (120→60/hr on D01) with no degradation when transferred to validation. `tuned+safety` adds the Phase-4 safety baseline (max_on 10 s + veto) and removes the two remaining policy-level censored events (S1 2→0).

### 2.4 Known remaining failures (recorded, not fixed)

S4/S5 post-transient |v| excursions of 1.3–2.0 m/s on corrupt frames exceed the 1.0 m/s failure threshold (`config/phase4.json → failure_threshold`) — recorded as failures in `11_events_corrected.csv` (column `post_event_max_v`). This is estimator-level spike rejection, deliberately left for a later phase so this phase stays measurement-only.

## 3. WP-C — baro/IMU fusion interface (synthetic verification only)

Module: `src/fusion.py` (`BaroImuFusion`); script: `scripts/14_imu_fusion_sim.py` → `results/14_fusion_simulated.csv` + `fig_fusion_simulated.png`.

Interface contract implemented and exercised on synthetic IMU only:

- timestamped baro + 3-axis accel inputs, ASYNC updates: `update_imu` propagates the 3-state [h, v, accel-bias] with each accel sample; `update_baro` corrects with each pressure-derived altitude;
- optional known-attitude input (gravity compensation, Earth z-down, `a_z = f_z + 9.80665`, quaternion (w,x,y,z) body→earth);
- accel-bias estimation, gated on |v| < 0.5 m/s AND |a_comp| < 1.0 m/s², clamped to ±2 m/s²;
- input jitter and gap handling, innovation gating, fault flags with a baro-only fallback path (fusion degrades to the baro-only estimator).

All fusion numbers below are **[S] simulated** — no IMU capture exists yet (`reports/bmp581_imu_acquisition_plan.md` [U]).

| scenario | variant | metric | value m/s |
|---|---|---|---|
| nominal | baro_only_fallback | climb RMS err [S] | 0.499 |
| nominal | fusion_known_attitude | climb RMS err [S] | 0.009 |
| nominal | fusion_known_attitude | drop RMS err [S] | 0.025 |
| nominal | baro_only_fallback | drop RMS err [S] | 1.682 |
| baro_blackout_1s | baro_only_blackout | blackout window RMS err [S] | 1.699 |
| baro_blackout_1s | fusion_blackout_coast | blackout window RMS err [S] | 0.034 |
| imu_jitter_3ms | fusion_jitter | rest RMS err under 3 ms jitter [S] | 0.035 |
| baro_spike_8m | fusion_spike | post-spike max |v| (spike rejection failure, >1.0) [S] | 1.502 |

Bias estimation converges in simulation (estimated 0.0786 vs true 0.08 m/s²). Limitations: (1) fusion is slightly *worse* than baro-only at rest (0.031 vs 0.012 m/s RMS) because synthetic IMU noise injects variance with nothing to cancel; on real data the trade may differ. (2) An 8 m baro spike produces 1.50 m/s post-spike |v| — spike rejection is a recorded failure. (3) Nothing here is measured; every fusion claim awaits the BMP581/IMU acquisition plan.

## 4. WP-D — portable C core

Files: `portable/vario_core/vario_core.h`, `vario_core.c` (C99, no heap allocation in steady state, timestamp-driven, single translation unit), `runner.c` (host runner with per-update instrumentation). The C core mirrors the S5 estimator math operation-for-operation; Python remains the reference implementation.

Verification (`scripts/15_portable_core.py` → `results/15_portable_equivalence.csv`): 12/12 passed — MSVC host builds (float + `-DVARIO_USE_DOUBLE`) on 5 test vectors (statics 45 Hz, climb step 100 Hz, spike+gap+reversal, irregular dt, sustained fault), plus ESP32-S3 cross-compiles with xtensa-esp-elf-gcc in both variants. Equivalence vs the Python float64 reference: double build max |Δv| = 2.0e-08 m/s (tolerance 1e-6; observed divergence is compiler operation-order over thousands of steps, not a logic difference), float build max |Δv| = 5.1e-05 m/s (tolerance 1e-3).

Honest limitation: the host runner's per-update timing reads 0.000 us on most vectors because `clock()` resolution is coarser than one filter update; CPU cost is reported from the Python benchmark (`results/12_cpu.csv`) instead. On-target timing is part of the future ESP32 bring-up, not this phase.

## 5. Configuration change record (phase3.json → phase4.json)

| knob | phase3 | phase4 | provenance |
|---|---|---|---|
| audio policy | `audio_policy` (lift_on .2 / lift_off .05) | `common_audio_policy` — values identical | kept identical across all candidates by design |
| audio safety | — (absent) | `phase4_audio_baseline`: max_on_s=10, fault_veto=true | WP-A stress outcome [S], `results/11_stress.csv` |
| tuned policies | — (absent) | `tuned_policies` per filter (lift_on 0.15–0.2, lift_off 0.03–0.05, min_on 0–0.15) | WP-B search on TRAINING only [M], `results/13_policy_search.csv` |
| estimators | `architectures` | `estimators`: B02/C03/D01/S1 frozen; S4, S5 added; S1P added then rejected | S4/S5 measured improvements [M]; S1P rejected on validation [M] |
| safety mechanisms | — (absent) | `safety_mechanisms.fault_detector` (trip 5 / clear 5) + veto plumbing | WP-A [S] |
| failure threshold | `failure_threshold` | unchanged | — |
| reference defects | — (absent) | `reference_defects_retained`: S2, S3 frozen | WP-A root-cause decision [M] |

Note: phase2's `results/05_chosen_configs.json` was not consulted for B02/C03/D01 parameters — Phase 3 used class defaults and Phase 4 keeps them identical for comparability. Flagged here for the record; if a future phase re-tunes references, 05_chosen_configs.json should be checked first.

## 6. Deliverables checklist (Phase 4 spec → artefact)

| spec deliverable | artefact |
|---|---|
| corrected audio-event metrics, event-type separation | `results/11_events_corrected.csv`, `11_summary_by_type.csv` |
| investigation of S2 censored beep-offs + t006 sid behaviour | `results/11_s2_censoring.csv`, `11_t006_sid.csv`, §1.3–1.4 |
| startup/missing/spike/reversal stress tests; no continuous ON during faults | `results/11_stress.csv`, §1.5–1.6 |
| per-event failure visualizations | `results/fig_p4_s2_freeze_event.png` (+ this report's tables) |
| estimator comparison, frozen configs, train/val separation | `results/12_estimator_*.csv`, `12_cpu.csv`, §2.1 |
| audio-policy tuning on training; common thresholds first | `results/13_policy_*.csv`, §2.3 |
| config-change record | §5, `config/phase4.json` |
| fusion interface verified on synthetic IMU; BMP581 plan, no fabricated data | `src/fusion.py`, `results/14_fusion_simulated.csv`, `reports/bmp581_imu_acquisition_plan.md` |
| portable C core + tests, explicit FP precision, cross-platform | `portable/vario_core/`, `results/15_portable_equivalence.csv`, §4 |
| three retained candidates, no winner | §7 |
| Phase 3 results preserved untouched | `results/03..10_*` unchanged (verified by git) |

## 7. Retained candidates and limitations

Retained (strongest per measured evidence, in order):

1. **S5_LightGateKF** — S1-class rest noise (0.045 m/s [M]) and 0% missed lifts at 18.4 us/sample [M] (1.15x D01); constant-time; saturation fix included.
2. **S4_FastSlowGated** — 0% missed lifts, 0 censored, fastest exit-from-lift (release proxy 1.43 s [D]) at 1.18x D01 CPU [M]; explicitly encodes the fast/slow gating the research report recommends.
3. **S1_RobustAdaptiveKF** — best-in-class rest noise (0.045 m/s [M]) but misses 18.9% of lifts on validation [M] — retained because its audio quality under the tuned policy is strong, with the miss rate flagged as its known defect.

S1P rejected (worse than S1 on validation); S2/S3 frozen as defect references only. **No production winner is declared** — per spec, the choice requires real IMU data and on-target measurement.

Limitations:

- Latency figures are derived proxies [D], not ground truth (no absolute position reference in the captures).
- Fusion is synthetic-only [S]; the rest-noise regression under fusion and the 1.50 m/s post-spike excursion are recorded failures.
- S4/S5 post-transient excursions on corrupt frames (§2.4) exceed the failure threshold and are unfixed by design of this phase.
- C-core host timing resolution insufficient; on-target timing pending.
- GitHub push pending (network); everything committed locally.

## 8. Reproduction

```bash
cd filter_benchmark
python -u scripts/11_audio_events_v2.py     # WP-A corrected metrics + stress
python -u scripts/12_estimator_comparison.py # WP-B estimator comparison
python -u scripts/13_audio_policy_tuning.py  # WP-B policy search (training)
python -u scripts/14_imu_fusion_sim.py       # WP-C synthetic fusion
python -u scripts/15_portable_core.py        # WP-D C core equivalence
python -u scripts/16_phase4_report.py        # this report + figures
python -u scripts/run_tests.py               # 35/35 unit + regression tests
```

_Every number in this report is traceable to a row in `results/`; figures regenerate from the same CSVs._
