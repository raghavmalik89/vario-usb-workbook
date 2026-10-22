# HANDOVER REPORT — Vario USB bench rig (ESP32-S3)

**Date:** 2026-10-22 · **Repo:** github.com/raghavmalik89/vario-usb-workbook (branch `main`)
**Purpose of this document:** full state transfer to a fresh chat session. Read this first,
then `docs/design_considerations.md`, then the two research PDFs in `docs/`.

---

## 1. Project state in one paragraph

Bench rig is fully operational end-to-end: ESP32-S3 + 2× MS5611 (GY-63) + MPU6050 (GY-521),
Arduino firmware speaking serial protocol v1 over USB-CDC @921600, Python capture + analysis
pipeline, all results git-committed. Tests T-000…T-008 are done (bring-up, noise floor, dual-baro,
elevator + step-drop motion, estimator replay). Key measured facts: single-MS5611 noise floor
≈ **19 cm / 2.2 Pa RMS @ OSR4096, 45 Hz**; raw sensing latency **~10–30 ms**; causal-0.3 s-filter
onset cue **133 ms** on a 1 m drop (beats the <150 ms target, baro-only); **release/ring-down
0.9–1.0 s is the weak number**; dual-barometer averaging gain only **1.13× vs ideal 1.41×**
(noise correlated +0.65 in a shared environment); naive IMU fusion **diverges on impulses**,
spike-gated fusion is good on ramps (185 ms onset) but noisier at rest. Next phase: estimator +
audio firmware per the research architecture (below), OSR2048/high-rate experiment, release-latency
test.

## 2. Hardware as-built (verified on bench — docs/test_rig_schematic.md §6b)

| Module | Bus | Address | Notes |
|---|---|---|---|
| GY-63 #1 (MS5611) | A — Wire, SDA=GPIO4, SCL=GPIO5 | **0x76** | clone has CSB pulled low (not 0x77!) |
| GY-521 (MPU6050) | A — same bus | **0x69** | AD0 tied 3V3; WHO_AM_I=0x68 = genuine |
| GY-63 #2 (MS5611) | B — Wire1, SDA=GPIO6, SCL=GPIO7 | 0x77 | the "unit under test", sid=1 |
| (GY-63 #3 optional) | C — bit-banged GPIO15/16 | — | not wired; only needed for 3-sensor study |

Quirks: rig is mounted **X-up** (ax ≈ +1.02 g, az ≈ 0.08 g — do NOT assume az is vertical;
04_filter_replay auto-picks the gravity axis). MPU6050 clone gyro bias **−37.5 dps on X**
(accel fine, ±0.03 g). PROM[0]: 0x0878 (A), 0x0884 (B) — both alive. IMU INT (GPIO10) wired,
unused. Power everything from 3V3.

Protocol sids: sid 0 = Bus A baro, sid 1 = Bus B baro (docs/serial_protocol.md).

## 3. Firmware inventory (arduino/ — compile-checked, all flashed & run)

| Sketch | Version | Role |
|---|---|---|
| i2c_scan_test | — | T-000 wiring bring-up (scans A/B/C incl. bit-bang bus C) |
| t001_baro_stream | 0.1.3 | baro-only stream. **Historical** — boot-only meta, known limitation noted in header |
| t002_baro_imu_stream | **0.2.2** | baro sid=1 + MPU6050 200 Hz I-frames. T-002/T-004 firmware. Has meta-on-attach |
| t003_dual_baro_stream | **0.3.1** | dual MS5611 lockstep (45 Hz P + 5 Hz T each). T-003 firmware |

All firmware: protocol v1, boot legend + health check (#C,dev= / #C,health=), #K PROM dump,
raw frames only (no filtering on MCU), deadline-based non-blocking state machine,
**meta-on-attach with 2.5 s delay** (see lessons). IMU: ±2 g, ±250 dps, DLPF 44 Hz, SMPLRT_DIV=4.

## 4. Capture & analysis workflow (works, but read the quirks)

```
python tools/capture.py --port COM5 --label <label> --duration <s>   # writes analysis/data/<ts>_<label>.csv + .json
python analysis/01_noise_floor.py '*t001*'          # stationary only
python analysis/02_step_response.py '*elevator*' --sid=1
python analysis/04_filter_replay.py '*step_drop*' --sid=1
python analysis/03_dual_sensor_compare.py '*t003*'
```
Sidecar (`*.json`) carries firmware/#K/#C meta — the offline compensator REQUIRES `prom_<sid>`;
never analyze a run without it. t001-era sidecars were hand-patched (provenance noted inside);
all t002+ runs are native.

**Operational lessons (learned the hard way):**
1. **Serial Monitor locks COM5** ("Access is denied") — close it before capture; kill `serial-monitor.exe` process if stuck (IDE itself keeps running).
2. **Opening a CDC port does NOT reset the S3** — a board already running has already emitted boot meta. Firmware re-emits #H/#K/#C 2.5 s after a new host attaches; capture.py's 2 s flush window therefore no longer eats it. Emergency recovery of meta from a live board: toggle DTR off/on, read for a few s (script pattern in git history / `t003_meta_grab.txt`).
3. `find_run(pattern)` picks the NEWEST glob match — label runs distinctly (`t004_step_drop`, not a reused label; one capture was mislabeled and renamed after).
4. `arduino-cli` is at `"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"`, core esp32 3.1.3, fqbn `esp32:esp32:esp32s3`. IDE settings need USB CDC On Boot = Enabled.
5. Git: repo root = this folder (Kimi Workbook/Vario USB). `USB_C_Instant_Vario/` is its OWN repo — excluded. Commit identity is placeholder `raghav.malik@local` (no global git identity on machine). GitHub was unreachable from this machine at times (push may need retry).

## 5. Measured evidence (all in analysis/data/, plots in analysis/output/)

| Test | Result |
|---|---|
| T-000 scan | addresses as in §2; all three devices alive |
| T-001 noise floor (×3 runs: open air, sealed box) | **2.13–2.24 Pa RMS → 18.4–19.3 cm** altitude RMS @45 Hz OSR4096; raw d1 noise 129→86 LSB sealed (some environmental component) but compensated noise unchanged → sensor-intrinsic floor; ~2× datasheet typical (clone quality). 0 drops, 0 errors every run |
| T-002 IMU stream | 200.0 Hz, p5/p95 jitter 4.999/5.001 ms; baro unaffected by IMU (bus isolation works); accel self-check X-up |
| T-003 dual baro | single σ ≈2.2 Pa each; pair averaged **1.95 Pa = 1.13× gain (ideal 1.41×)**; **corr +0.65** → common-mode environment dominates; static offset between units 87 Pa (~7 m, within ±1.5 mbar spec) |
| T-004 elevator (14→1→14) | Δh = **39.2 m both directions** (13 floors × 3.02 m — chain validated); v_eff 1.74 m/s; rest vario noise **0.024 m/s** (target 0.15); 10–90% "rise" 18.8 s = ride duration (ramp, not step — metric N/A); script's whole-run IMU-onset latency was an artifact, fixed (windowed detector) |
| T-004 step drop (~1 m ×4 onto cloth) | raw pressure visible **4–34 ms** after release (sensing is instant); free-fall durations match ½gt² (0.41 s ≈ 0.83 m ✓); drops were too rapid for vario to settle between → cue latency measured on synthetic 1 m drop with causal filters: **111/133/178 ms** for 0.2/0.3/0.5 s windows — all beat Skytraxx 0.5 s |
| T-008 replay (04_filter_replay.py) | A) LPF+deriv: rest 0.55 m/s — diagnostic-only baseline. B) baro-only CV-Kalman: rest 0.034–0.046 (elevator), onset 0.9–1.6 s ramp / bounded on drops with 0.9–1.0 s release ring-down. C) fusion: **185 ms onset on ramps** (5–8× faster than B) but **diverges on catch spikes** (10.5 m/s peaks); spike-gating (>3 m/s²) restores boundedness. **Fusion verdict: conditional** |

## 6. Decisions the evidence currently supports

- **ADR-002 (dual baro): NO as a latency/noise strategy** — gain 1.13× in a shared environment;
  research PDF independently ranks IMU fusion > better single baro > dual averaging. Dual sensors
  still useful for fault detection/port A-B testing later.
- **ADR-006 (baro-only filtering): sufficient for prototype targets** — 133 ms onset, 0.024 m/s
  rest noise, with a causal 0.3 s window. 2-state [h,v] KF = the essential fallback/baseline.
- **ADR-011 (IMU): value is real on ramps (185 ms) but requires** spike rejection + bias tracking
  + attitude/gravity compensation. Naive fusion is dangerous on impulses. Clone MPU6050 gyro bias
  −37.5 dps confirms calibration burden.
- **Product sensor: BMP581/BMP585** (research: ×8 = 0.30 Pa/155 Hz primary, ×16 = 0.21 Pa/87 Hz
  second config, internal IIR BYPASS — its coefficient-7 IIR alone costs ~198 ms).
- **Release latency is the first-class work item** (handoff PDF's principal recommendation;
  our 0.9–1.0 s ring-down proves it locally). Audio must be an interruptible state machine
  (STOP cuts a beep immediately, 5–15 ms fade; strong-lift immediate trigger; release confirm
  20–50 ms; stale-data → silence).
- **Thresholds to start from** (research): lift-on +0.20, lift-off +0.05, strong-lift +0.5 m/s,
  weak-lift arming 40–80 ms. Report onset/release PER SIGNAL STRENGTH (+0.2 vs +2.0 m/s).
- **Report estimator-vs-audio chain separately** — sensor/estimator, USB, app, audible
  (mic-measured) — don't blame the filter for audio-path delay.

## 7. Target architecture (from docs/Instant Variometer Filter Design.pdf — 33 pp, read it)

```
IMU ──► attitude estimator (Mahony/comp or quaternion EKF) ──► Earth-Z accel
baro ──► FAST linear 3-state KF [h, v, accel bias]  (predict every IMU sample,
         async baro correction — never force equal rates, never hold IMU samples)
FAST v ─► confidence + audio state machine ──► USB events ──► phone
SLOW baro-only [h,v] KF ──► confidence/veto ONLY (never averaged into fast output)
```
Also: complementary baro/IMU filter as transparent baseline ("if the KF can't beat a tuned
complementary filter on the same data, distrust the KF"); UKF only if replay proves a linear
model deficiency. Q/R from MEASUREMENT (our stationary runs give R directly). Timestamp each
physical sample and use measured Δt. MS5611 OSR2048 (4.1 ms, 1.8 Pa, ~100 Hz) experiment is
explicitly recommended over assuming max OSR wins. Open-source references: har-in-air
ESP32_IMU_BARO_GPS_VARIO (500 Hz IMU logs + notebooks), Kalmanfilter_altimeter_vario
([h,v,bias]), juangallostra/AltitudeEstimation (Lee two-stage). Papers: Sabatini & Genovese 2014,
Lee 2016, Brzozowski 2018.

## 8. Analysis pipeline — known limitations (do not re-derive these)

- `01_noise_floor.py`: "50.0 Hz rate" and "300 missing P frames" are cosmetic (interleaved T
  frames); cm-RMS sensitivity formula FIXED (was 120× off — use git history to see why).
- `02_step_response.py`: 10–90% rise is meaningless on ramps (elevator); IMU-latency detector is
  windowed (fixed; was tripping on handling bumps). `altitude_m` kwarg is `p0_pa`.
- `04_filter_replay.py`: rewritten for event-relative metrics; rest mask from |v_ref|<0.05;
  **event detection has edge artifacts at run boundaries — trim ≥2 s**; Kalman auto-r is rough —
  treat q_v/r as sweep knobs; `evaluate()` onset is measured vs the 1-s-smoothed reference
  crossing, so fast estimators show negative onset on sharp events — compare like with like.
- Centered smoothing (gaussian 'same') looks AHEAD — it underestimates latency. Use causal
  filters for latency claims.
- MS5611 compensation ground truth = analysis/common.py `compensate_ms5611` (final scale /2^15
  in Pa — a hand-derivation with /2^6 is WRONG by ~500×).

## 9. Next steps (priority order)

1. **Release-latency test** (defined input, per research T-002): lift-then-stop cycles, measure
   90–10% fall + time-to-lift-off-threshold. Currently our weakest metric.
2. **OSR2048 @ ~100 Hz firmware experiment** (t004 variant): does lower conversion latency beat
   noisier samples for final velocity estimate? Research explicitly recommends this A/B.
3. **Estimator firmware** (new phase, ESP-IDF or Arduino): complementary baseline + 3-state fused
   KF with spike gating + async updates; replay-tune q's against EXISTING captures first
   (04_filter_replay harness), then port winner to firmware. Audio state machine after estimator.
4. **har-in-air dataset**: download their 500 Hz/50 Hz recordings, run our estimators on them
   before trusting bench-only tuning.
5. **BMP581/BMP585 dev board** purchase for the sensor A/B (×8 vs ×16).
6. Environmental artefact tests (research T-004 list): port airflow, touch spikes, tilt-without-
   displacement, USB congestion — several map to tests already listed in design_considerations.md §5.

## 10. Test-numbering collision warning

OURS (this repo, firmware/README.md): T-000 scan, T-001 noise, T-002 IMU stream, T-003 dual baro,
T-004 disturbance (elevator/drop). THE RESEARCH PDF uses its own T-001…T-005 (noise / pressure
dynamics / motion+IMU / artefacts / audio). When planning "T-005", say which scheme you mean —
suggest renaming research-derived tests to R-1…R-5.

## 11. Commits

- `0ad534a` T-000..T-004 state (firmware, captures, docs)
- `4435657` T-008 replay rewrite + design_considerations.md (+ handoff PDF)
- next: this report + Instant Variometer Filter Design.pdf (pending push — GitHub connectivity
  was intermittent from this machine; retry `git push`).
