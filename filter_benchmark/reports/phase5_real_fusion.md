# Phase 5 — Real-IMU fusion on t007 captures: findings report

Date: 2026-10-23. Captures: six t007 sessions (firmware 0.7.0, dual MS5611
OSR2048 @ 90 Hz P / 10 Hz T + MPU6050 @ 200 Hz), captured by Raghav
2026-10-23 11:07–11:44. Processing: `scripts/17_real_imu_fusion.py`
(baro-only vs baro+IMU `BaroImuFusion`), diagnostics `18_noise_decompose.py`,
`19_madgwick_debug.py`, `20_fusion_trace.py`. Test suite 47/47
(`scripts/run_tests.py`). **No final estimator is selected or frozen in this
phase** — per Raghav, that decision waits for more hardware comparisons.

---

## 1. Data-quality verdict (t007)

Full machine-generated table: `reports/data_quality_report.md` (21 runs,
10 clean). t007 specifics:

- **benchstatic: flawless.** 0 seq gaps, 0 corrupt, 0 error frames,
  200.1 Hz IMU, 90 Hz P per sid. The periodic 20 ms P spacing is by design
  (every 10th tick converts temperature) — not a defect.
- **Motion sessions (drop, drop2, toss, ControledMove2, elevator_2x):
  usable with caveats.** 3–12 whole-loop freeze events per session,
  0.32–0.66 s each. Every freeze hits P0, P1 and the IMU **simultaneously**
  (event counts match exactly; max-gap times agree within ~15 ms), which
  pins the cause to whole-loop blockage (USB/serial backpressure), not I2C
  or a single sensor. Frozen-time share ≈ 3.5–9% of session time (IMU
  basis). A handful of corrupt P/T frames and 2–3 NAK error frames per
  session are handled by the existing band filters.
- **Drop/toss impacts saturate the ±8 g accel** for 0.3–0.8% of IMU samples
  (noted, acceptable — impacts are exactly where clipping is expected).
- **Iteration names (drop2, ControledMove2) are fine** — no collision with
  earlier t005/t006 sessions.
- Silver lining: the freezes are accidental **blackout-coast test
  intervals** — the filters experience genuine 0.3–0.65 s measurement
  silence with correct physical timestamps.

## 2. Processing findings

### 2.1 Noise decomposition — the pressure ADC dominates (script 18)

Per-sample lag-1 noise of the compensated altitude stream on benchstatic:

| contribution | sid0 | sid1 |
|---|---|---|
| total (d1, d2 raw) | 2.61 Pa (0.214 m) | 2.93 Pa (0.241 m) |
| d1 alone (d2 held const) | 2.58 Pa | 2.89 Pa |
| d2 alone (d1 held const) | ~0.2–0.5 Pa | ~0.2–0.5 Pa |

**The pressure ADC d1 (~112 counts/sample ≈ 2.6 Pa) is the dominant noise;
the clone's noisy temperature channel d2 contributes almost nothing.**
Median-filtering d2 over ±2.5 s before compensation changes total noise by
<2% (kept anyway — physically right, costs nothing). This **refutes the
previous session's working hypothesis** that d2 was a major noise injector;
script 18 is the evidence. Consequence: all earlier phases' altitude
streams carried this same d1 noise — their tuned q/r absorbed it, and the
1-s-detrended altitude noise on t007 static is 0.43–0.45 m.

**Also measured: the office "static" is not pressure-static.** True
altitude wanders −8.3…+0.9 m over the 59 s bench session (HVAC/draft,
≈1 hPa). Any absolute rest-v target is meaningless on these captures;
rest metrics must be drift-removed (high-passed), stated where used.

### 2.2 Clone calibration [M]

- **Gravity scale**: this MPU6050 clone reads |a| = 10.055 m/s² at rest
  (**+2.5% scale error**). The scale factor is a per-device constant —
  `g_cal` is taken from the clean static session and applied to all
  sessions. Per-session estimates are fragile: slow controlled hand motion
  keeps |a| inside any plausible band and poisoned ControledMove2's
  estimate to 9.567.
- **Gyro offset**: ≈51.7 °/s norm (mostly x) — large but stable; removed
  by the capture-start rest-window subtraction, residual negligible.

### 2.3 Madgwick attitude: healthy — the "failure" was a metric artifact (script 19)

- From identity q0 the estimator needs ~5 s to acquire the rig's ~6.3°
  tilt; from t=5 s onward the rest gravity residual is **0.011 m/s²** on
  real data (synthetic controls pass exactly). Convention is correct.
- Script 17's original `madgwick_rest_az_err` averaged only t≤3 s — i.e.
  it measured the convergence transient, not steady-state error. Fixed to
  a post-convergence window.
- **But that transient was not harmless** (script 20): the leaked
  ~2.2 m/s² mean vertical accel over the first 5 s integrated the fused
  KF's v to 14 m/s; the innovation gate then rejected every measurement
  for the rest of the session (freeze-by-gating), while `fault` was only a
  display flag and the filter coasted forever. Two fixes, both now in
  `src/`:

  1. **`attitude.quat_from_accel_tilt`** — exact shortest-arc warm start
     from the first accel sample (az(0) ≈ 0.02 m/s², no transient; the
     roll/pitch trig forms were tried first and are convention-treacherous
     on this X-up rig — both plain and conjugated left 0.2–0.6 m/s²
     residual; shortest-arc is exact by construction).
  2. **`BaroImuFusion` fault recovery** — 8 consecutive >5σ innovations
     now mean a declared loss-of-track: reinit state from the measurement
     (`[z, 0]`, P=I, counted in `n_reinit`). Previously the flag latched
     and the filter coasted with runaway v permanently. Isolated spikes
     are still gated without reinit (tests cover both).

### 2.4 Baro-only KF tuning: r honest, q plateau (script 17 sweep)

- **r = 0.042 m²** (σ=0.205 m), measured [M] on static, both sids — the
  Phase-4 synthetic default r=0.035 was coincidentally close but for the
  wrong reason; the honest value now comes from the decomposed d1 noise.
- **q sweep {0.3…100} on static is a flat plateau** (drift-removed rest
  v-RMS 0.407–0.447 m/s, spread 10% < noise): the metric has no power to
  discriminate q on static data. q≤1 permanently latched the innovation
  gate pre-recovery and still reinit-cycles on motion (veto: 11 reinit in
  34 s on drop). **Exploratory operating point q = 10** (mid-range,
  motion-vetted) — a judgment call, explicitly not a frozen selection.
- Rest v-RMS (drift-removed) at q=10: 0.35–0.76 m/s on static; honest
  tracking of a genuinely drifting room pressure.

### 2.5 Baro+IMU fusion vs baro-only on real captures (q=10, warm start, fault recovery)

Rest-v RMS [m/s] (mask: |a|∈[0.9g,1.1g]; elevator rest segments only):

| session | baro-only | fusion | fusion verdict |
|---|---|---|---|
| benchstatic | 0.35–0.76 | 0.35–0.76 | **identical** — IMU path adds nothing at rest, hurts nothing |
| elevator_2x | 1.33 | 1.39 | equal; max\|v\| slightly better (3.1 vs 3.5) |
| ControledMove2 | 1.14–1.19 | 1.43–1.47 | slightly worse (attitude error 3.4 m/s² mean\|az\|) |
| drop / drop2 / toss | 1.08–1.64 | 1.80–3.00 | **clearly worse**; max\|v\| 8.7–11.7 vs 3.6–5.8 |

**The fusion bottleneck is attitude quality under rotation, not the KF.**
During tumble the 6-DOF Madgwick (no mag, beta=0.3) accumulates
6.5–10.3 m/s² mean gravity residual — fake vertical acceleration injected
straight into the propagation. During gentle motion (elevator: 0.14 m/s²)
fusion matches baro-only. No permanent divergence remains anywhere
(worst case 42 reinit on toss, always recovering).

## 3. Limitations

1. **Attitude under high rotation is the known weak point** — expected for
   6-DOF without magnetometer. Candidate mitigations (to evaluate, not
   decided): adaptive beta (trust accel when |a|≈g and gyro quiet), IMU
   fusion gating on |az| residual or gyro rate, or 9-DOF hardware.
2. **q is an exploratory value**; the static plateau cannot discriminate.
   Motion-session multi-objective tuning (rest noise vs event latency vs
   reinit rate) is the next tuning step.
3. **Office statics are draft-dominated** — future static captures should
   be short (≤20 s) for noise metrics, or taken in a pressure-quiet room.
4. Sample freezes (USB backpressure) mean the MCU-side pacing still needs
   attention for long sessions; harmless for this analysis (timestamps are
   physical, gaps are handled), but it caps capture fidelity.
5. Impact saturation (±8 g) limits drop/toss accel fidelity; a ±16 g
   variant would help if impact dynamics matter for tuning.

## 4. Repro

```
python scripts/02_validate_data.py            # quality report (21 runs)
python -u scripts/17_real_imu_fusion.py       # sweep + fusion table + fig
python -u scripts/18_noise_decompose.py       # d1/d2 noise decomposition
python -u scripts/19_madgwick_debug.py        # az-vs-time convergence
python -u scripts/20_fusion_trace.py          # fused-filter state trace
python -u scripts/run_tests.py                # 47/47
```

Artifacts: `results/17_real_imu_fusion.csv`, `results/17_q_sweep_static.csv`,
`results/fig_p5_real_fusion.png`, `reports/data_quality_report.md`.
