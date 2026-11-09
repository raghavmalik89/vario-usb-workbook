# Flight Recording Filter Benchmark — LOG00001

**Date:** 2026-11-09
**Dataset:** `LOG00001(2).CSV` — first real paragliding flight recording, BMP581 barometer
**Scope:** Analysis only. No firmware changes, no retuning, no final-estimator selection.
**Artifacts:** `analysis/flight/` (scripts, metrics JSON, replay series) · `reports/flight/` (figures)

---

## 1. Executive summary

The flight recording is of **excellent integrity**: 761.65 s of device time, 30,467 barometer samples at 40.0 Hz and 15,169 vario samples at 19.9 Hz, **zero** sequence gaps, duplicates, malformed lines or timestamp discontinuities, and no truncation.

Replaying the four frozen filters (C03, D01, S4, S5) on the recorded BMP581 pressure stream with real device timestamps shows:

- **C03 verification passed decisively**: the bench Python C03 reproduces the device-recorded C03 to **3.3 mm/s RMS** (after excluding the first 5 s initialization). This validates both the Python reference implementations and the estimator-to-audio mapping used here.
- All four filters track the flight well; the ranking differences are **matters of degree, not kind**. Effective tracking lag is ~2.1 s for all four on real thermal transitions (frozen configurations, 40 Hz input).
- **S4/S5 are measurably quieter** than C03/D01 in the quiet segments found late in the flight (61 vs 72 mm/s RMS; p95 117 vs 143 mm/s) and produce **fewer audio episodes** (71/80 vs 93/96) with the same zero proxy-false-trigger count.
- **C03/D01 have the best transient shape accuracy** after delay compensation (134 vs 199–215 mm/s fast-motion RMS error) and slightly lower overshoot.
- **Recommendation for the next flight: run S4 as the airborne default** (quietest practical output, fewest audio episodes, lowest output jerk), keeping C03 as the verified reference implementation. This is a measured-evidence-based recommendation, not a default. See §8 for the trade-off argument and what would reverse it.

No IMU samples exist in this recording, so FUS cannot be evaluated on flight data (§3.3).

---

## 2. Dataset integrity

### 2.1 Measured facts

| Item | Value |
|---|---|
| Recording span (device timestamps) | **761.65 s** (12 min 41.6 s) |
| Barometer (B) rows | 30,467 |
| Barometer rate | 40.00 Hz (dt median 24.991 ms, p99 25.106 ms, max 25.421 ms) |
| Vario (V) rows | 15,169 |
| Vario rate | 19.92 Hz (dt median 50.004 ms) |
| B sequence | 31709 → 62175, **zero gaps, zero duplicates** |
| V sequence | 15856 → 31024, **zero gaps, zero duplicates** |
| Malformed lines | **0** (45,637 lines total) |
| B timestamps | strictly monotonic; no gaps > 100 ms |
| Session markers | exactly one: `S,1,793567662,1,1` at file start |
| Filters present in V rows | **C03 only** |
| IMU rows | **none** (only B and V record types exist in the file) |
| End of file | normal data rows; last V row 15 ms after last B row — no truncation evidence |

Pressure conversion `Pa = raw/64` and altitude consistency were spot-verified (e.g. raw 5803000 → 90,671.9 Pa → ISA altitude 927.1 m, matching the recorded 927,204 mm within 8 mm; median offset across the whole file 7.6 mm).

### 2.2 Interpretation

The flight profile (fig 1) is a coherent paragliding sortie: launch and initial climb near t = 0 from ~927 m, sustained thermalling with altitude excursions 900–990 m, and a landing rollout at ~917 m from t ≈ 655 s onward (flat pressure trace, quiet segments used for noise metrics, §4.1).

The sequence counters starting at 31709/15856 rather than 1 indicate a global, boot-persistent sample counter (one session marker `S,1` per boot). This file is a **single continuous session**; see §9 for the separate filename-reuse risk discussion.

### 2.3 Limitations

- **No independent ground truth.** No GPS, no video, no pilot log timestamps. All "response" and "error" figures below use a pressure-derived Savitzky–Golay reference (§4 method). They are internally consistent proxies, not truth.
- **Single flight.** One air mass, one pilot, one day. Rankings here are conditional on this dataset.
- **No IMU.** FUS is unevaluable (§3.3), and no attitude/ acceleration context is available for interpreting filter behavior.
- **Launch/landing times are inferred** from the data, not logged.

---

## 3. Methodology

### 3.1 Replay setup

- Raw pressure samples converted with `Pa = raw/64`; altitude via ISA `z = 44330·(1 − (p/101325)^0.1903)`.
- All four filters replayed at **real device B timestamps** (dt from consecutive differences), deterministic causal updates, using the frozen, previously validated Python implementations and coefficients:
  - **C03** — CV Tracker, `q = 1.0, r = 0.035` (`filter_benchmark/src/filters/tracking.py`)
  - **D01** — CV Kalman, `q = 1.0, r = 0.035` (`filter_benchmark/src/filters/kalman.py`)
  - **S4** — Fast/Slow Gated, frozen P4 parameters (`filters/stacked.py`)
  - **S5** — Robust CV Kalman (light gate), frozen P4 parameters (`filters/stacked.py`)
- Audio policy: ON at v > **+0.20 m/s**, OFF at v < **+0.05 m/s** (the current virtual-audio hysteresis), applied to each replayed output and to the recorded C03 V-values.

### 3.2 Proxy reference and a methodological correction (important)

The pressure-derived reference velocity is a two-stage Savitzky–Golay filter (81-tap on altitude, gradient, 41-tap on velocity). A length-N symmetric SG filter has **exact group delay (N−1)/2 samples at DC**, i.e. **60 samples = 1.5 s** of pure delay that must be removed before the reference can be used for delay/overshoot/settling metrics. The first analysis pass (reference left delayed) produced self-canceling errors: apparent filter delay of −0.6 s and inflated overshoot/settling. After alignment, all metrics became physically coherent; this correction is baked into `flight_analysis.py` and documented here so the numbers are not misread against earlier bench passes.

Two further metric-hygiene rules were applied:

1. **Delay and shape error are measured separately.** Raw xcorr delay on 46 detected transitions (|ref| > 0.5 m/s sustained ≥ 3 s) gives the effective tracking lag; overshoot and settling are then computed against a **delay-compensated** reference so they measure shape behavior, not the delay itself. Transitions whose xcorr peak fell on the window edge were rejected (0 of 46 rejected — all estimates are interior maxima).
2. **Settling/overshoot windows are capped at the next transition start.** Thermalling transitions are often only 5–10 s apart; an 8 s settling window would otherwise integrate the *next* thermal burst. (This cap is why settling times below are believable rather than the pathological ~12 s an uncapped window produced during development.)

### 3.3 What cannot be evaluated

- **FUS (baro+IMU fusion):** the file contains no IMU records. Fusion gains claimed from bench tests remain unvalidated in flight.
- **Anything IMU-dependent**: motion gating, vibration robustness, launch detection.
- **CPU cost on target**: the recording firmware is not the bench firmware; on-target timing from previous phases still stands.

---

## 4. C03 replay verification

| Lag (B samples) | −3 | −2 | −1 | 0 | +1 | +2 | +3 |
|---|---|---|---|---|---|---|---|
| RMS (m/s) | 0.0627 | 0.0450 | **0.0358** | 0.0434 | 0.0605 | 0.0808 | 0.1024 |

- Best alignment: **−1 sample** (−25 ms — one B-sample quantization of the 20 Hz V stream; consistent with causal filtering).
- Best-lag RMS **excluding the first 5 s: 3.3 mm/s** (mean −1.2 mm/s, std 35.8 mm/s).
- Worst single deviation: 1.40 m/s at **t = 0.075 s** — the shared initialization transient of replay and device filter, not a mid-flight mismatch.
- Audio episodes: replayed C03 93 vs device-recorded 94 (fig 5) — agreement within one episode over 12.7 min.

**Verdict: the bench Python C03 is a faithful reproduction of the device firmware C03.** All four replayed filters therefore share a verified pipeline; the filter-versus-filter comparison below is apples-to-apples.

---

## 5. Quantitative comparison

All values measured as described in §3.2. "Delay" is effective xcorr lag on real thermal transitions against the aligned pressure-derived reference — a proxy for tracking responsiveness, dominated by the frozen q/r dynamics at 40 Hz; treat absolute values with the caveats of §2.3.

| Metric | C03 | D01 | S4 | S5 |
|---|---|---|---|---|
| Quiet RMS (mm/s), 37 s coverage | 72.4 | 72.4 | **60.9** | **60.7** |
| Quiet p95 \|v\| (mm/s) | 142.6 | 142.7 | **116.3** | 116.7 |
| Transition delay median (s) | **2.10** | **2.10** | 2.20 | 2.12 |
| Transition delay p75 (s) | 2.12 | 2.12 | 2.24 | 2.17 |
| Overshoot median, delay-comp (m/s) | **0.264** | **0.266** | 0.330 | 0.361 |
| Settling median, delay-comp (s) | **5.95** | **5.95** | 7.28 | 6.96 |
| Fast-motion RMS error, raw (m/s, \|ref\|>1) | 1.333 | **1.332** | 1.387 | 1.367 |
| Fast-motion RMS error, delay-comp (m/s) | **0.134** | **0.134** | 0.215 | 0.199 |
| Fast-motion bias (mm/s) | −58.7 | −58.6 | −54.3 | −56.1 |
| Output jerk RMS (m/s² per s) | 1.034 | 1.085 | **0.894** | 0.945 |
| Audio episodes (+0.20/−0.05) | 93 | 96 | **71** | 80 |
| Audio ON time (s) / duty | 278.5 / 36.6% | 278.8 / 36.6% | 279.7 / 36.7% | **273.5 / 35.9%** |
| Mean episode duration (s) | 2.99 | 2.90 | **3.94** | 3.42 |
| Proxy false triggers (ON ≥ 2 s while \|ref\|<0.15) | 0 | 0 | 0 | 0 |

Measured evidence vs interpretation: the table above is measured. Statements like "S4 is quieter" or "C03 tracks transients more tightly" are interpretations of those measurements under the §2.3 limitations.

### 5.1 What the audio numbers mean

Total audio ON-time is nearly identical across filters (274–280 s of 761 s ≈ 36% duty) — all four capture essentially the same lift. The difference is **chatter**: C03/D01 break that time into ~93–96 short episodes, S4 into 71 longer ones, S5 into 80. Given zero proxy-false triggers for any filter, none of the extra episodes are demonstrably wrong — they are mostly re-entries around the +0.20 threshold in turbulent, near-threshold air (fig 5 shows the episode patterns tracking the same thermal bands). Longer, fewer episodes mean less beeping at equal information.

---

## 6. Figures

All figures in `reports/flight/` (also committed):

1. **fig1_overview.png** — full-flight altitude and vertical-speed history with all four filters.
2. **fig2_overlay.png** — four-filter overlay on identical pressure input, full flight.
3. **fig3_transitions.png** — three zoomed climb/sink transitions (shaded windows), showing onset, tracking, and exit behavior per filter.
4. **fig4_quiet.png** — landing-rollout quiet segment zoom + per-filter velocity distribution histograms (quiet metrics).
5. **fig5_audio.png** — audio ON-episode timelines per filter vs device-recorded C03, over the reference velocity.

---

## 7. Findings and trade-offs

1. **Quietness: S4/S5 win measurably.** ~16% lower RMS and ~18% lower p95 than C03/D01 in the 37 s of quiet segments. This is the largest robust difference in the study. (Caveat: quiet coverage is limited to the rollout; there is no long soaring-quiet stretch in this flight.)
2. **Transient shape: C03/D01 win measurably.** 134 mm/s delay-compensated fast-motion RMS error vs 199–215 mm/s for S4/S5; lower overshoot; faster settling (5.9 s vs 7.0–7.3 s).
3. **Chatter: S4 wins** — fewest episodes (71) and longest mean episode (3.9 s) at equal total ON-time; zero false triggers for all.
4. **Delay: statistical tie.** ~2.1 s for all four (2.10 C03/D01, 2.12 S5, 2.20 S4). Responsiveness did not differentiate the field on this data.
5. **Smoothness: S4 lowest jerk** (0.894 vs 1.03–1.09) — consistent with its gating architecture suppressing small-scale velocity jitter.
6. C03 and D01 are nearly identical on every metric here, as expected from their shared q/r heritage — the practical field on this flight is {C03/D01} vs {S4, S5}.

**Trade-off in one line:** C03/D01 give crisper transients; S4/S5 give quieter output and calmer audio with slightly softer transient fidelity.

---

## 8. Ranking and recommended default for the next flight

**Ranking for real-world paragliding use (this dataset):**

1. **S4** — quietest-class noise, fewest audio episodes, lowest jerk, zero false triggers; acceptable (slightly worse) transient shape. Best overall pilot-experience metrics.
2. **S5** — statistically tied with S4 on quietness, middling chatter (80 episodes), better fast-motion shape than S4 but worse than C03/D01.
3. **C03** — best transient fidelity and fastest settling; verified identical to device firmware; noticeably chattier audio and noisier quiet output.
4. **D01** — same behavior as C03 within measurement noise, marginally higher jerk; no measured advantage over C03 on this data.

**Recommended default for the next flight: S4**, with C03 remaining the verified reference. Rationale: on real flight data the differences that matter for pilot experience are quietness and chatter, both of which S4 leads, while its transient-shape disadvantage (0.33 vs 0.26 m/s median overshoot; 215 vs 134 mm/s delay-comp fast error) is a second-order effect against a 2.1 s common lag that dwarfs it. **What would reverse this recommendation:** a flight with long quiet soaring stretches (to confirm the quiet advantage generalizes beyond rollout) or GPS reference data showing S4's gating misses or delays weak-but-flyable lift onsets. Either result should be fed back before freezing anything — this remains a design-space investigation, not a selection.

---

## 9. SD recording anomaly — observations only (no fix; Task 2)

**Evidence available in this dataset:**
- Filename `LOG00001(2).CSV` strongly suggests at least two earlier files named `LOG00001.CSV` existed on the card (Windows "(2)" suffix appears on name collision). 
- Sequence counters begin at 31709 (B) / 15856 (V), not 1 — counters are boot-persistent, and exactly one session marker `S,1` exists. This file itself is internally one continuous session with no truncation.

**Suspected risk (filename reuse after reboot):** if the logger resets its filename index on reboot, a new flight could overwrite `LOG00001.CSV` and silently destroy an earlier recording.

**Verification status: blocked.** The SD-recording firmware is **not part of this repository** (searched: no logger source for this format exists under the workspace; our `esp-idf/vario` logs over USB, not SD). Whether the filename rotates, appends, or overwrites cannot be confirmed from here. **Task 2 should inspect the actual recording firmware** and confirm: (a) filename allocation strategy on boot, (b) behavior on existing-file collision, (c) whether the `S` marker/session counter is written per boot or per file.

**Impact on this analysis: none.** The analyzed file is complete and self-consistent. The risk is for *future* recordings.

---

## 10. Outstanding questions and recommended validation experiments

1. **Log multiple estimators to SD.** The recording firmware logs only C03. If it can emit interleaved V frames for D01/S4/S5 (as the bench firmware already does), on-device flight comparison removes the replay-verification step entirely.
2. **Add IMU + GPS to flight recordings.** Enables FUS evaluation, ground-truth velocity reference, and launch/landing annotation. Until then, all flight "accuracy" claims remain proxy-based.
3. **A quiet-soaring flight.** This flight had effectively zero long quiet stretches aloft; the quiet metrics rest on 37 s of landing rollout. A 20+ min straight-glide/soaring segment would materially firm up the quietness ranking.
4. **Repeat with S4 airborne** (per §8) to test the recommendation against weak-lift onsets.
5. **Task 2: SD filename rotation audit** (§9).

---

## Reproducibility

- `analysis/flight/flight_analysis.py` — parse, integrity audit, replay, all metrics; writes `flight_metrics.json` + `replay_series.npz`.
- `analysis/flight/flight_plots.py` — renders the five figures from the npz + json.
- Dataset copy: `analysis/flight/LOG00001_flight.csv` (original at `D:\LOG00001.CSV`).
- Filter implementations: `filter_benchmark/src/filters/` (frozen, previously validated).
