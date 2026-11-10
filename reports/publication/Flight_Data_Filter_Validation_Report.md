# From Flight Data to Filter Decisions

**A corrected, evidence-based comparison of four frozen variometer filters on
the first real paragliding flight recording (LOG00001, workbook commit `53907ab`).**

*R. Malik · Vario project engineering report · November 2026*
*Companion article: **A Flying Breadboard — A Product Development Story***
*(why and how this recording exists). All numbers below are measured on the
committed dataset and reproducible from `analysis/flight/flight_analysis.py`.*

---

## 1. Executive summary

The first real paragliding flight recording from the project's temporary
breadboard logger is of **excellent integrity**: 761.65 s of device time,
30,467 barometer samples at 40.0 Hz and 15,169 vario samples at 19.9 Hz, with
zero sequence gaps, duplicates, malformed lines or timestamp discontinuities.

Replaying the four frozen filters (C03, D01, S4, S5) on the recorded pressure
stream with real device timestamps shows:

- **The bench pipeline is flight-faithful.** The bench Python C03 reproduces the
  device-recorded C03 to **3.3 mm/s RMS** — the filter-versus-filter comparison
  is apples-to-apples.
- **Effective tracking lag is 0.57–0.70 s** on real thermal transitions. This
  revision corrects an erroneous ~2.1 s figure published in the first version
  of the analysis (§5.3).
- All four filters track the flight well; the differences are **matters of
  degree, not kind**. S4/S5 are measurably quieter (60 vs 67 mm/s RMS, 114 vs
  137 mm/s p95 in quiet segments) and chatter less (71/80 vs 93/96 audio
  episodes); C03/D01 have measurably better transient shape after
  delay compensation (134 vs 197–211 mm/s fast-motion RMS error) and slightly
  lower overshoot.
- On this dataset the evidence supports **S4 as the airborne default for the
  next flight**, with C03 retained as the verified reference. This is a
  measured-evidence-based recommendation, not a universal verdict — and it states
  exactly what evidence would reverse it (§9).

## 2. Recording setup and sensor configuration

The recording was made by the temporary ESP32-S3 flight logger described in the
companion article: a Waveshare ESP32-S3-LCD-1.9 board with a BMP581 barometric
breakout, logging to microSD during a paragliding flight.

Sensor configuration (as validated during bring-up and unchanged for the
flight):

- **BMP581** on the shared I²C bus at 0x47 (chip ID 0x50), oversampling
  ×16 pressure / ×2 temperature, ODR 40 Hz, on-chip IIR bypass, cadence read;
  on-chip compensated output `Pa = raw24/64`.
- One **session marker** (`S,1`) at file start; boot-persistent sequence
  counters; record types `B` (barometer) and `V` (vario).
- Recording firmware logged the **C03 estimator only** in V frames; D01, S4 and
  S5 are evaluated by offline replay on the recorded B stream (§4).
- **No IMU data** exists in this recording (§8).

Pressure-to-altitude conversion throughout is the ISA model

  z = 44330 · (1 − (p / 101325)^0.1903)   [m, p in Pa]

spot-verified against the logger's own altitude field (e.g. raw 5,803,000 →
90,671.9 Pa → 927.1 m, matching the recorded 927,204 mm within 8 mm; median
offset across the file 7.6 mm).

## 3. Measurement integrity

| Item | Value |
|---|---|
| Recording span (device timestamps) | **761.65 s** (12 min 41.6 s) |
| Barometer (B) rows | **30,467** |
| Barometer rate | **40.00 Hz** (dt median 24.991 ms, p99 25.106 ms, max 25.421 ms) |
| Vario (V) rows | 15,169 |
| Vario rate | 19.92 Hz (dt median 50.004 ms) |
| B / V sequence integrity | **zero gaps, zero duplicates** |
| Malformed lines | **0** of 45,637 |
| B timestamps | strictly monotonic; no gaps > 100 ms |
| Session markers | exactly one (`S,1,793567662,1,1`) — one continuous session |
| Filters in V rows | C03 only |
| IMU rows | none |
| End of file | normal data rows; last V row 15 ms after last B row — no truncation |

The profile is a coherent paragliding sortie (fig. 1): launch and initial climb
near t = 0 from ~927 m, sustained thermalling with altitude excursions between
900 and 990 m, and a landing rollout at ~917 m from t ≈ 655 s onward — the flat
quiet tail used for the noise metrics of §6.

*Recording-side observation (no impact on this analysis):* the filename
`LOG00001(2).CSV` and the non-zero boot counters suggest filename reuse across
reboots; whether the SD firmware rotates, appends or overwrites on collision
could not be confirmed from this repository. The analyzed file itself is
complete and self-consistent; a filename-allocation audit is queued for the
recording-firmware owner.

## 4. Methodology: replay, reference, and metric hygiene

**Replay.** All four filters were replayed on the recorded B stream at real
device timestamps (dt from consecutive differences), deterministic causal
updates, using the frozen, previously validated Python implementations:

- **C03** — CV Tracker, `q = 1.0, r = 0.035`
- **D01** — CV Kalman, `q = 1.0, r = 0.035`
- **S4** — Fast/Slow gated architecture, frozen P4 parameters
- **S5** — robust CV Kalman (light gate), frozen P4 parameters

Audio policy: ON at v > +0.20 m/s, OFF at v < +0.05 m/s (the current
virtual-audio hysteresis), applied identically to each replayed output and to
the device-recorded C03.

**Reference.** The pressure-derived reference velocity is a two-stage
Savitzky–Golay filter (81-tap on altitude → gradient → 41-tap on velocity).
The SG window is symmetric about its centre, so the filter is **zero-phase** and
the reference is already time-aligned.

**Pipeline verification.** Replaying C03 and aligning against the device's own
V values gives best agreement at −1 B-sample (−25 ms — one 20 Hz V-sample
quantization, consistent with causal filtering) with **3.3 mm/s RMS** excluding
the first 5 s (shared initialization transient; worst single deviation 1.40 m/s
at t = 0.075 s). Audio episodes: 93 replayed vs 94 recorded — agreement within
one episode over 12.7 minutes. The bench Python C03 is a faithful reproduction of
the device firmware C03.

**Metric hygiene** — two rules that keep the numbers honest:

1. **Delay and shape error are measured separately.** Raw cross-correlation lag
   on detected transitions (|ref| > 0.5 m/s sustained ≥ 3 s; 46 detected, 44
   retained after rejecting windows whose xcorr peak fell on the edge) gives the
   effective tracking lag; overshoot and settling are then computed against a
   **delay-compensated** reference so they measure shape, not delay.
2. **Settling/overshoot windows are capped at the next transition start** —
   thermalling transitions are often only 5–10 s apart, and an uncapped 8 s
   window would integrate the next thermal burst.

## 5. Quantitative comparison

All values measured as described above. "Delay" is the effective cross-correlation
lag on real thermal transitions against the aligned pressure-derived reference —
a proxy for tracking responsiveness. Treat absolute values with the caveats of
§8.

| Metric | C03 | D01 | S4 | S5 |
|---|---:|---:|---:|---:|
| Quiet RMS (mm/s), 37 s coverage | 67.2 | 67.1 | **59.8** | **59.5** |
| Quiet p95 \|v\| (mm/s) | 137.4 | 137.1 | **113.9** | **112.9** |
| Transition delay median (s) | **0.600** | **0.575** | 0.700 | 0.625 |
| Transition delay p75 (s) | 0.625 | 0.625 | 0.750 | 0.675 |
| Overshoot median, delay-comp (m/s) | **0.277** | 0.290 | 0.349 | 0.361 |
| Settling median, delay-comp (s) | **7.98** | 8.27 | 9.46 | 9.71 |
| Fast-motion RMS error, raw (m/s, \|ref\|>1) | 0.642 | **0.640** | 0.732 | 0.703 |
| Fast-motion RMS error, delay-comp (m/s) | **0.134** | 0.145 | 0.197 | 0.211 |
| Fast-motion bias (mm/s) | 2.2 | 2.2 | −5.9 | −5.8 |
| Output jerk RMS (m/s² per s) | 1.034 | 1.085 | **0.894** | 0.945 |
| Audio episodes (+0.20 / −0.05) | 93 | 96 | **71** | 80 |
| Audio ON time (s) / duty | 278.5 / 36.6% | 278.8 / 36.6% | 279.7 / 36.7% | **273.5 / 35.9%** |
| Mean episode duration (s) | 2.99 | 2.90 | **3.94** | 3.42 |
| Proxy false triggers (ON ≥ 2 s while \|ref\| < 0.15) | 0 | 0 | 0 | 0 |

### 5.1 Reading the table

- **Quietness (fig. 5):** S4/S5 are ~16% lower in RMS and ~18% lower in p95
  than C03/D01 in the quiet segments. This is the largest robust difference in
  the study — but the quiet coverage is 37 s of landing rollout only; there is
  no long quiet-soaring stretch in this flight.
- **Transient shape (fig. 3):** C03/D01 win the delay-compensated
  fast-motion error (134–145 vs 197–211 mm/s), overshoot (0.28–0.29 vs
  0.35–0.36 m/s) and settling (8.0–8.3 vs 9.5–9.7 s).
- **Chatter (fig. 4):** total audio ON-time is nearly identical across filters
  (274–280 s of 761 s ≈ 36% duty) — all four capture essentially the same lift.
  The difference is how that time is broken up: C03/D01 produce 93–96 short
  episodes, S4 71 longer ones, S5 80. With zero proxy false triggers for every
  filter, the extra episodes are mostly re-entries around the +0.20 threshold
  in turbulent, near-threshold air — not demonstrably wrong, but audible.
- **Delay:** all four respond in ~0.6–0.7 s. C03/D01 are marginally faster
  (0.58–0.60 s) than S5 (0.63 s) and S4 (0.70 s). Proportionally the spread is
  larger than it first appears (S4 ~17% slower than D01), but in absolute terms
  all four sit in the same responsiveness class.
- **Smoothness:** S4 has the lowest output jerk (0.894 vs 1.03–1.09), consistent
  with its gating architecture suppressing small-scale velocity jitter.
- C03 and D01 are nearly identical on every metric, as expected from their
  shared q/r heritage — the practical field on this flight is {C03/D01} vs
  {S4, S5}.

### 5.2 The responsiveness–smoothness trade-off in one line

C03/D01 give crisper transients; S4/S5 give quieter output and calmer audio with
slightly softer transient fidelity. Neither class is wrong; they weight the same
measured trade differently.

### 5.3 Corrected response-lag methodology — why ~2.1 s was wrong

The first published version of this analysis reported an effective lag of
~2.1 s. **That value was invalid**, for a subtle and instructive reason.

The pressure-derived reference uses a **centred (symmetric) Savitzky–Golay
filter**. A symmetric SG filter is zero-phase: it has no group delay to
correct. The erroneous run applied a "group-delay correction" of
`SG_LAG = 60` samples — a rule that holds for *causal/trailing* windows, not
for a centred one — shifting the reference 1.5 s **beyond** truth. Every
delay-conflated metric inherited exactly that 1.5 s inflation: filters appeared
to lag ~2.1 s when the true lag was ~0.6 s, a discrepancy confirmed
independently by cross-correlation.

This revision removes the shift (and the corrected script carries a comment
recording the mistake so it is not reintroduced). The shape-only metrics —
delay-compensated overshoot, settling and fast-motion error — were essentially
unaffected, as they should be. **The corrected lag of 0.57–0.70 s is a
pressure-derived, internally consistent estimate of effective tracking
responsiveness.** It is not an independently verified physical response time:
with no independent vertical-speed ground truth (§8), it should be read as
"how far each filter trails the best pressure-only estimate of truth", not as
truth itself.

### 5.4 Audio threshold behaviour

The +0.20 / −0.05 m/s hysteresis policy behaves on flight data exactly as
designed in the virtual-audio bench work, and the flight data makes its
character visible: in turbulent air near threshold, output hovering around
+0.20 m/s produces clusters of short re-entry episodes (C03/D01) versus fewer,
longer sustained episodes (S4's gating extends mean episode length to 3.9 s).
Episode patterns track the same thermal bands across all four filters (fig. 4),
total ON-time is equal, and the proxy false-trigger screen (ON ≥ 2 s while the
reference is below 0.15 m/s in magnitude) finds **zero** violations for every
filter. The practical interpretation: the threshold itself is not generating
false lift indications on this flight; the design lever that remains is how
calmly the threshold is approached, which is a filter property, not a policy
property.

## 6. Figures

1. **fig. 1 — Flight overview** (`fig1_overview.png`): full-flight altitude and
   vertical-speed history with all four filters and the audio thresholds.
2. **fig. 2 — Four-filter overlay** (`fig2_overlay.png`): all four filters on
   identical BMP581 pressure input, full flight.
3. **fig. 3 — Zoomed transitions** (`fig3_transitions.png`): three climb/sink
   transition windows showing onset, tracking and exit behaviour per filter.
4. **fig. 4 — Audio episodes** (`fig5_audio.png`): per-filter ON-episode
   timelines versus device-recorded C03, over the reference velocity.
5. **fig. 5 — Quiet segments** (`fig4_quiet.png`): landing-rollout zoom plus
   per-filter velocity-distribution histograms (quiet metrics).

## 7. Ranking on this dataset, and the recommended default

**For real-world paragliding use, conditional on this single flight:**

1. **S4** — quietest-class noise, fewest audio episodes, lowest jerk, zero
   proxy false triggers; costs are real but bounded (+0.1 s onset delay,
   +0.07 m/s median overshoot, +0.06–0.13 m/s delay-compensated fast-motion
   error). Best overall pilot-experience metrics.
2. **S5** — statistically tied with S4 on quietness; middling chatter; better
   fast-motion shape than S4 but worse than C03/D01.
3. **C03** — best transient fidelity and fastest settling; verified identical
   to device firmware; noticeably chattier audio and noisier quiet output.
4. **D01** — same behaviour as C03 within measurement noise; no measured
   advantage over C03 on this data.

**Recommended default for the next flight: S4**, with C03 retained as the
verified reference implementation. A pilot prioritizing crisp lift onset over
audio calm would rationally pick C03 instead — both choices are defensible on
this data.

**What would reverse this recommendation:** (a) a flight with long quiet
soaring stretches confirming or refuting that the quiet advantage generalizes
beyond landing rollout; or (b) GPS reference data showing S4's gating misses or
delays weak-but-flyable lift onsets. Either result feeds back before anything is
frozen — this remains a design-space investigation, not a selection.

## 8. Limitations

- **No independent ground truth.** No GPS, video or pilot-log timestamps. All
  response/error figures use the pressure-derived SG reference — internally
  consistent proxies, not truth. The corrected lag in particular must not be
  cited as an independently verified physical response time.
- **Single flight.** One air mass, one pilot, one day. Rankings are conditional
  on this dataset.
- **No IMU data.** FUS (baro+IMU fusion) is unevaluable on flight data, and no
  attitude/acceleration context exists for interpreting filter behaviour; all
  fusion gains from bench tests remain unvalidated in flight.
- **Limited quiet coverage.** The quiet metrics rest on 37 s of landing
  rollout; there is no long soaring-quiet stretch in this flight.
- **Launch/landing times are inferred** from the data, not logged.
- **Replay scope.** D01/S4/S5 were evaluated by offline replay; the recording
  firmware logged C03 only. On-target CPU/timing for the other estimators stands
  from previous bench phases.
- **Recording-firmware filename behaviour** unverified (§3 observation).

## 9. Next validation experiments

1. **Log multiple estimators to SD** — interleaved V frames for D01/S4/S5
   remove the replay-verification step entirely and give on-device comparison.
2. **Add IMU + GPS** to flight recordings — enables FUS evaluation, an
   independent velocity reference, and launch/landing annotation.
3. **A quiet-soaring flight** — 20+ minutes of straight-glide/soaring to firm
   up the quietness ranking beyond rollout data.
4. **Repeat with S4 airborne** to test the §7 recommendation against
   weak-lift onsets.
5. **SD filename-rotation audit** of the recording firmware (§3).

## Reproducibility

- Dataset copy: `analysis/flight/LOG00001_flight.csv`
- Analysis: `analysis/flight/flight_analysis.py` → `flight_metrics.json` +
  `replay_series.npz`; figures: `analysis/flight/flight_plots.py` → `reports/flight/`
- Filter implementations: `filter_benchmark/src/filters/` (frozen, previously
  validated); workbook revision: commit `53907ab` (corrected reference alignment)
- Recording hardware and flight context: companion article *A Flying
  Breadboard* and the `ESP32-S3-Display-DataLogger` repository.
