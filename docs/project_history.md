# Vario USB — Project History

Chronological engineering log. Companion documents: `HANDOVER.md` (state transfer),
`defect_register.md` (defects), `Vario_USB_Engineering_Report_Phases_1-5.pdf` (offline
filter benchmark), `Vario_USB_Technical_Paper.pdf` (research manuscript),
`Vario_USB_FalseLift_ESP_IDF_Validation_Report.pdf` (ESP-IDF validation + false-lift
root cause — this entry's report).

---

## 2026-10-22 — Offline filter benchmark (Task E, Phases 1–4) + t005/t007/t008 captures
- Built the causal replay benchmark: baselines B00–B03, 29 standalone filters in groups
  A–E, whole-session tuning/validation separation, 45 vs 90 Hz comparisons, portable C
  core (`filter_benchmark/portable/vario_core`).
- Bench captures T-005 (controlled moves, drops, tosses), T-007 (dual-baro + 200 Hz IMU),
  T-008 (quiet-house static) ingested; research PDF on vario filter design integrated
  (validates IMU fusion > dual-barometer averaging; specifies 3-state KF architecture).
- Delivered engineering report + research-style technical paper (commit c21ca8e).

## 2026-10-23 (day) — ESP-IDF hardware validation begins
- User directive: ESP-IDF (not Arduino) in a separate `esp-idf/vario/` tree; existing
  MS5611 + MPU6050 hardware; virtual audio via timestamped USB-serial events; competing
  estimators side-by-side, no selection.
- Firmware built from scratch: async MS5611 driver, MPU6050 + Madgwick attitude, estimator
  bank (D01/C03/S4/S5/FUS), audio state machine, TX ring, B-line bench accounting.
- Debug war (fixed same day, in order): clone CRC4 quirk (`c ^ 0x0F`); d1=0/partial-ADC
  frames → N+4 read pipeline (DEF-004); NaN poisoning from unseeded d2 (DEF-005); flaky
  clone init retries (DEF-006); TX ring 48→240 KB; I2C address auto-probe (bus A rework
  now answers 0x68/0x77 — sid↔module identity tracked via PROM[0]).
- Captures: idf_static_50hz, idf_elevator_2x (first attempt, dropouts), idf_handtest ×2,
  idf_probe_test; sensor respacing to 25 mm; foam added over sensors (sid0 noise 388→90
  LSB, 4.3× quieter; user-predicted heat retention confirmed small and stabilising).

## 2026-10-23 (evening) — Elevator runs + false-lift investigation (major)
- Two clean elevator runs (`221124`, `221420`): four legs each, 1↔14 floors (38.2 m,
  2.94 m/floor) at ±1.55–1.60 m/s, reproducible to 0.1 m/s; ascents tracked (implied v
  median +1.64 D01, +1.83 FUS), descents correctly silent under lift-only policy.
- **Anomaly:** 15–17 s of false-lift audio at the floor-1 dwell with flat ±0.1 m raw
  altitude — a genuine paradox.
- **Root cause (proven):** firmware altitude reference p0 was a *running mean of the
  first 2000 pressure samples* (~50 s window) — during any in-window motion the reference
  itself moves (∂alt/∂p0 ≈ 0.084 m/Pa; dp0/dt ≈ +5 Pa/s at the dwell) manufacturing
  +0.45 m/s fake climb. Firmware-exact offline replay matched MCU-reported velocity to
  −0.002 m/s. Temperature, door/piston pressure, estimator-dynamics, and firmware-bug
  hypotheses all ruled out with recorded evidence. (DEF-001)
- **Design decision (evidence-based):** IMU-based suppression rejected — the IMU was
  silent (1 g) during the artifact, so an accel-consistency veto would veto genuine
  thermals (violates the no-stationary-veto constraint). Correct suppression class:
  physically unmoving reference.
- **Fixes flashed + bench-validated:**
  1. Fixed ISA reference 101325 Pa, moving-p0 accumulator removed (−32 KB DRAM) —
     replay-verified (false-lift ON 16.5/17.5 s → 0.0/1.2 s; genuine ~49 s ascent audio
     preserved) + MCU-verified (`idf_p0fix_static`, 75 s silent of sustained lift).
  2. C03 Riccati refit storm fixed via per-dt gain cache: 1330→38 µs avg (35×)
     (DEF-002, MCU-verified).
  3. B-line buffer 512→768: all 10 estimator CPU pairs reported (DEF-003, MCU-verified).
- **Deliverables this commit:** `docs/Vario_USB_FalseLift_ESP_IDF_Validation_Report.pdf`
  (10 pp, 7 figures, full evidence trail), `docs/defect_register.md` (10 defects),
  this history, firmware source, analysis scripts + figures, raw captures.

## Open threads (next sessions)
- Formal MCU-vs-Python replay equivalence check on the fixed reference (queued).
- BMP581 + LSM6DSV16X integration (breakouts ordered) — retire clone tempco class
  (DEF-007); architecture is sensor-independent.
- Real-flight capture; elevator remains a proxy.
- Audio policy tuning (min-on-time, exit-from-lift) against benchmark; estimator
  selection still explicitly frozen.
