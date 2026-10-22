# Engineering Task: Empirical Variometer Filter Benchmark and Validation

## 1. Objective

Implement, run and compare multiple vertical-speed estimation filters using the **real datasets already collected for the Vario nRF PG Sensor / USB-C Instant Variometer project**.

The objective is to determine, from evidence, which algorithms and combinations offer the best practical balance of:

- Fast detection of increasing vertical speed / lift onset.
- Fast recognition of decreasing vertical speed / lift release.
- Low noise when the sensor is stationary or vertical speed is stable.
- Low false indications and oscillation around zero.
- Stable behavior during vibration, pressure disturbances and outliers.
- Reliable operation during irregular sampling, missing data and sensor anomalies.
- Feasibility for real-time execution on the ESP32-S3.

**Do not select a winner based on theoretical superiority or expectations.**

First establish what the recordings contain. Then implement the filters, replay the data, measure the outputs, and report what the evidence supports.

Do not invent sensor channels, reference measurements, ground-truth events, timestamps, sampling rates or performance results.

## 2. Inspect the available datasets first

Before implementing filters:

1. Locate and inventory every relevant recording.
2. Identify file formats, columns, units, timestamp sources and sensor identities.
3. Identify which recordings contain raw pressure, temperature, IMU acceleration, gyroscope, GPS, device-estimated climb rate, reference-vario output, or other signals.
4. Determine actual sample rates and their variability from timestamps.
5. Identify gaps, duplicate samples, out-of-order records, timestamp resets, saturation, suspicious values and incomplete sessions.
6. Identify stationary recordings, bench experiments, controlled vertical movements, flights and other session types **only where supported by metadata or evidence**.
7. Document whether an independent vertical-speed reference exists.

Produce `dataset_inventory.md` and `data_quality_report.md` before running comparisons.

**Critical:** Sensor sample timestamps and USB reception timestamps are not interchangeable. Use the closest available timestamp to physical measurement. Report timing limitations explicitly.

Never treat one filtered estimate as independent ground truth for another.

## 3. Establish reproducible baselines

Implement these baseline estimators:

- **B00:** Consecutive altitude difference divided by actual elapsed time.
- **B01:** Vertical speed from a trailing-window linear regression of altitude against timestamp.
- **B02:** A documented existing project estimator, if present.
- **B03:** Reference variometer output, if recorded, shown separately as a comparison signal.

Use the same documented pressure-to-altitude conversion for every eligible barometric algorithm. Record its assumptions and sensitivity to temperature and reference pressure.

Use actual timestamps for derivatives. Do not assume constant sampling intervals unless verified.

## 4. Implement individual candidate filters

Each algorithm must be implemented as a standalone, stateful module with:

- `reset()`
- `update(sample, timestamp)`
- `get_estimate()`
- Explicit configuration parameters
- Deterministic causal behavior
- Tests for irregular intervals and missing data

### Group A — Basic smoothing

- A01: Simple moving average (multiple trailing window lengths).
- A02: Exponential moving average (multiple time constants).
- A03: Double exponential smoothing.
- A04: Median filter (several odd window lengths).
- A05: Hampel outlier filter.
- A06: Robust preprocessing followed by EMA.

Test smoothing applied to altitude **and** smoothing applied to derived vertical speed where both are meaningful.

### Group B — Classical signal-processing filters

- B01: Causal first-order low-pass.
- B02: Causal second-order Butterworth low-pass.
- B03: Causal Bessel low-pass.
- B04: Causal Savitzky–Golay derivative using trailing samples only.
- B05: Sliding-window polynomial or linear least-squares slope estimator.

Test relevant cutoff frequencies, window lengths and polynomial orders. Reject configurations that are numerically unstable or physically inappropriate.

Do not use `filtfilt`, centered windows, future samples or post-hoc time shifting for real-time performance comparisons.

### Group C — Tracking filters

- C01: Alpha-beta filter.
- C02: Alpha-beta-gamma filter.
- C03: Constant-velocity tracking estimator with tunable process noise.
- C04: Constant-acceleration tracking estimator.

Use actual elapsed time in prediction and correction.

### Group D — Kalman estimators

- D01: Two-state Kalman filter: altitude and vertical speed.
- D02: Three-state Kalman filter: altitude, vertical speed and vertical acceleration.
- D03: Four-state vertical filter with a documented additional state, such as acceleration bias, **only if the model and measurements make it observable or meaningfully constrained**.
- D04: Adaptive measurement-noise Kalman filter.
- D05: Innovation-based process-noise adaptation.
- D06: Kalman filter with robust measurement gating.

For each filter document:

- State vector.
- State-transition equations.
- Measurement equations.
- Process and measurement covariance.
- Initialization.
- Observability limitations.
- Parameter search ranges.
- Numerical implementation.

Do not add states merely to make a filter more sophisticated.

### Group E — Adaptive and multi-timescale approaches

- E01: One Euro filter.
- E02: EMA with a data-dependent time constant.
- E03: Fast and slow parallel estimators.
- E04: Innovation-based blending between fast and slow estimators.
- E05: Change-detection-assisted estimator.
- E06: Robust preprocessing plus adaptive tracking.

Check whether adaptive schemes actually improve both response and noise, or merely produce spikes and chatter.

### Group F — Multiple-sensor estimators (conditional)

Implement these **only if the required raw channels exist**:

- F01: Two-barometer averaging after alignment and calibration.
- F02: Two-barometer noise-weighted fusion.
- F03: Two-barometer consistency checking with fault rejection.
- F04: IMU gravity-compensated vertical acceleration plus barometric altitude using a complementary filter.
- F05: IMU-assisted vertical Kalman filter with acceleration-bias estimation.
- F06: GPS/barometer complementary or Kalman fusion where GPS data quality permits.

Do not fabricate missing sensor streams.

For IMU fusion, explicitly document attitude estimation, gravity compensation, coordinate frames, synchronization and calibration uncertainty.

## 5. Build a consistent replay and evaluation framework

Create one common replay engine that feeds identical samples and timestamps to all eligible algorithms.

Requirements:

- All candidate filters process data chronologically.
- All implementations have access only to measurements available at that moment.
- Use identical session boundaries and warm-up rules.
- Record every estimate with its output timestamp.
- Preserve raw data unchanged.
- Support missing samples and variable time intervals.
- Keep training/tuning sessions separate from final validation sessions.
- Never tune parameters on the held-out validation recordings.

If resampling is necessary for a particular method, document the method and interpolation delay. Prefer evaluating at original timestamps where possible.

Do not compare algorithms using different datasets or different event definitions without making the distinction explicit.

## 6. Measure filter quality

### A. Stationary noise and stability

Where stationary recordings are verified, measure:

- Mean estimated vertical speed.
- Standard deviation and RMS.
- Median absolute deviation.
- 95th and 99th percentile absolute output.
- Peak excursions.
- Zero-crossing rate.
- Time spent above and below defined climb/sink thresholds.
- Frequency of false audio-trigger events under a common audio policy.

Plot time series, distributions and power spectra where useful.

### B. Response to vertical-speed changes

For recordings with a valid independent reference or reliably annotated events, measure:

- Lift-onset detection delay.
- Lift-release detection delay.
- Time to reach specified fractions of a change.
- Overshoot and undershoot.
- Settling time.
- Peak vertical-speed error.
- Response asymmetry between increasing and decreasing vertical speed.
- Missed events and spurious events.

**Do not label these as measured physical response times unless a defensible event reference exists.**

Where there is no independent reference, report descriptive comparisons and clearly state that true latency or accuracy cannot be established.

### C. Controlled input-response analysis

Run each algorithm on reproducible synthetic input sequences to characterize its mathematical response:

- Constant altitude.
- Constant climb rate.
- Step change in vertical speed.
- Short-duration lift pulse.
- Gradual acceleration and deceleration.
- Noise bursts.
- Pressure spikes.
- Timestamp jitter.
- Missing samples.

These tests are useful for comparing filter dynamics, but must be reported separately from real-data validation. They do **not** prove actual sensor or flight performance.

### D. Accuracy against independent reference

Only if a suitable reference exists:

- MAE and RMSE of vertical speed.
- Bias.
- Correlation.
- Residual distributions.
- Error during rapid changes.
- Error during steady climb or sink.
- Sensitivity to reference synchronization uncertainty.

Do not optimize time alignment separately for every filter in a way that hides real latency. If a common clock offset must be estimated, document how it was determined.

### E. Robustness

Measure behavior under:

- Timestamp irregularity.
- Data dropouts.
- Pressure spikes.
- Temperature changes.
- Vibration.
- Sensor disagreement, where applicable.
- Filter initialization and recovery.

### F. Real-time implementation feasibility

Estimate or benchmark:

- Memory requirements.
- Operations per update.
- Execution time on ESP32-S3, when hardware benchmarking is available.
- Maximum practical update frequency.
- Numerical stability.
- Configuration and calibration requirements.

Distinguish desktop execution timing from actual MCU timing.

## 7. Evaluate audio behavior separately

The final purpose is an instant variometer, not merely a smooth graph.

Implement a common, configurable audio-event policy for comparison:

- Climb threshold.
- Sink threshold.
- Hysteresis.
- Minimum event duration, if used.
- Onset and release handling.
- Silence/neutral behavior.

Run the same audio policy on all estimator outputs first, so filter quality is not confounded by different audio rules.

Then, as a separate experiment, test whether a dedicated fast onset/release path improves behavior.

Measure:

- Beep onset delay.
- Beep termination delay.
- False beep count.
- Missed lift events.
- Excessive beep toggling.
- Time spent signaling climb after a reference event ends, when reference is available.

Separate **algorithmic detection delay** from USB, Android scheduling and actual audio playback delay. Only claim end-to-end audio latency if that path was measured.

## 8. Parameter tuning and statistical fairness

Use a reproducible parameter-search procedure.

- Define parameter ranges before examining held-out validation results.
- Save all tested configurations and scores.
- Avoid optimizing a single metric at the expense of all others.
- Compare noise against response delay using Pareto plots.
- Show onset and release separately.
- Use the same training/validation split for all eligible methods.
- Where enough sessions exist, evaluate consistency across sessions.
- Calculate uncertainty using session-level resampling where statistically appropriate.
- Avoid treating thousands of adjacent sensor samples as independent experimental replicates.

If there are too few independent recordings for reliable validation, report that limitation rather than manufacturing confidence intervals.

## 9. Investigate three combined-filter architectures

The following are **three experimental candidates, not preselected winners**. Implement and test them, then revise or replace them if the measured results justify doing so.

### Combination 1 — Robust barometric tracking

**Pipeline:**

Raw barometric pressure → validated spike/outlier handling → altitude conversion → alpha-beta or trailing least-squares tracking → vertical-speed estimate → common audio logic.

Questions:

- Does robust preprocessing improve reliability?
- Can a simple tracker provide a better noise/response tradeoff than basic smoothing?
- Is the added complexity of Kalman filtering justified?

### Combination 2 — Robust adaptive Kalman estimation

**Pipeline:**

Raw pressure → validated measurement gating → altitude → 2-state or 3-state Kalman filter → innovation-based noise adaptation (if beneficial) → vertical-speed estimate → common audio logic.

Questions:

- Does an adaptive Kalman filter improve behavior across stationary and dynamic recordings?
- Is a 3-state model measurably better than a 2-state model?
- Does adaptation cause overshoot, instability or release delay?

### Combination 3 — Parallel fast/slow estimator with optional sensor fusion

**Pipeline:**

Raw available sensors → separate fast and slow estimators → evidence-based combination or switching → vertical-speed estimate → common audio logic.

Candidate fast branch: short-window regression, alpha-beta filter, or IMU-assisted estimator if real IMU data exists.

Candidate slow branch: stable barometric Kalman or low-pass estimator.

Questions:

- Does the fast branch detect onset and release earlier?
- Does the slow branch reduce noise without delaying transitions?
- Does switching or blending create artificial vertical-speed jumps?
- Do IMU or dual-barometer measurements provide measurable additional value?

If only one barometer is present, implement the barometer-only version. Do not imply multisensor validation occurred.

### Selection rule

After evaluating all individual filters and these combinations:

1. Identify the Pareto-efficient candidates.
2. Select the three strongest **distinct** architectures supported by the data.
3. Tune them using training data only.
4. Validate them on held-out recordings.
5. Report all three, including weaknesses and failure cases.

The final three may differ from the provisional combinations above.

## 10. Required plots and tables

Generate at minimum:

1. Raw sensor measurements and timestamp-quality plots.
2. Overlay of baseline and candidate vertical-speed estimates.
3. Zoomed plots around documented onset events.
4. Zoomed plots around documented release events.
5. Stationary noise distributions.
6. Noise-versus-onset-delay Pareto plot, where reference data permits.
7. Noise-versus-release-delay Pareto plot, where reference data permits.
8. False-trigger versus missed-trigger comparison, where event labels permit.
9. Parameter sensitivity heatmaps.
10. Cross-session consistency.
11. Robustness and dropout examples.
12. Three-finalist side-by-side comparisons.

Include numerical tables and units. Make plots readable without relying only on color.

## 11. Required code structure

Create a maintainable Python benchmarking package, for example:

```text
filter_benchmark/
  README.md
  requirements.txt
  config/
    dataset_manifest.yaml
    experiments.yaml
  src/
    load_data.py
    inspect_data.py
    time_alignment.py
    preprocessing.py
    altitude_conversion.py
    replay.py
    metrics.py
    events.py
    plotting.py
    filters/
      baseline.py
      smoothing.py
      robust.py
      classical.py
      tracking.py
      kalman.py
      adaptive.py
      fusion.py
      combinations.py
  scripts/
    01_inventory.py
    02_validate_data.py
    03_run_baselines.py
    04_run_individual_filters.py
    05_tune_parameters.py
    06_evaluate_combinations.py
    07_validate_finalists.py
    08_generate_report.py
  tests/
  results/
  reports/
```

These are proposed output paths, not assertions that these files already exist.

Every experiment must be reproducible from its configuration and dataset identifiers. Save software versions, random seeds where relevant, filter parameters, data exclusions and run metadata.

Prefer standard Python scientific libraries such as NumPy, SciPy, pandas, matplotlib and pytest. Implement custom stateful filters where necessary to guarantee causal streaming behavior.

## 12. Final report requirements

Produce `reports/VARIO_FILTER_COMPARATIVE_ANALYSIS.md` and an HTML or PDF version if the environment supports it.

Report structure:

1. **Executive summary** — measured findings, not speculation.
2. **Dataset inventory and limitations** — what was actually available.
3. **Data quality and timestamp integrity**.
4. **Algorithms and mathematical models**.
5. **Experiment design and validation protocol**.
6. **Individual filter results**.
7. **Noise versus responsiveness comparisons**.
8. **Lift onset and lift release analysis**.
9. **Robustness and failure analysis**.
10. **Audio-trigger analysis**.
11. **Three finalist combinations**.
12. **Held-out validation results**.
13. **Sensitivity to parameter tuning**.
14. **ESP32-S3 implementation considerations**.
15. **Unresolved questions and required additional measurements**.
16. **Appendix: all tested configurations and raw metrics**.

For every important finding, identify the supporting recording, experiment and figure.

Use explicit evidence labels:

- **Measured:** directly established by recorded data or executed tests.
- **Calculated:** derived from measurements using documented formulas.
- **Simulated:** established only through synthetic inputs.
- **Hypothesis:** plausible but not validated.
- **Unavailable:** cannot be evaluated with the existing recordings.

## 13. Final deliverables

- Working, tested Python scripts.
- Dataset inventory and quality report.
- Saved per-sample outputs for every tested filter.
- Machine-readable results tables (CSV or Parquet).
- Complete plots and comparison figures.
- Parameter-search results.
- Three validated finalist architectures, if the data permits validation.
- Full comparative engineering report.
- Reproducible commands to rerun all experiments.

## 14. Non-negotiable rules

**No fabricated data. No invented reference signal. No undocumented assumptions. No cherry-picked recordings. No future-sample filtering presented as real time. No selecting the winner before seeing the measurements.**

Do not silently discard difficult recordings or poor-performing configurations.

Do not confuse smoothness with accuracy, correlation with low latency, or synthetic response with measured physical response.

If the current dataset cannot establish which filter is best, state exactly why and identify the smallest additional bench experiment needed to resolve the uncertainty.

**Start with dataset discovery and data-quality analysis. Do not jump directly to writing the final report or recommending a filter.**
