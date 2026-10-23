# Vario USB — Defect Register

Format: ID, status (OPEN / FIXED / VERIFIED / WONTFIX / PARKED), first/last seen,
affected component, evidence, resolution, verification level.

Verification levels:
- **replay** — validated by offline simulation against captured data
- **bench** — validated on the physical rig (stationary capture)
- **dynamic** — validated during controlled motion (elevator/hand tests)
- **flight** — validated in real flight (none yet; no defect is closed on flight evidence)

---

## DEF-001 — Moving altitude reference manufactures false lift
- **Status:** FIXED + verified (replay, bench)
- **Found:** 2026-10-23, elevator runs `20261023_221124` / `20261023_221420` (pre-fix firmware)
- **Component:** `esp-idf/vario/main/baro_proc.c` (`baro_proc_altitude`)
- **Symptom:** at the floor-1 dwell after the first descent, all 5 estimators on both
  barometers beeped false lift (+0.28/+0.45/+0.66 m/s p10/p50/p90, up to 17 s continuous)
  while true altitude was flat to ±0.1 m. 16.5–17.5 s false-lift ON-time per run.
- **Root cause:** altitude was computed against p0 = **running mean of the first 2000
  pressure samples (~50 s at 40 Hz)**, frozen afterwards. Motion inside that window makes
  the reference move: ∂alt/∂p0 ≈ 0.084 m/Pa, dp0/dt ≈ +5 Pa/s while converging to the
  lower-floor pressure → sustained fake climb of +0.4–0.7 m/s. Convention came from the
  offline benchmark (p0 = mean(p[:2000])), safe only for static captures; masked by the
  "keep still 60 s" capture protocol.
- **Evidence:** firmware-exact offline replay reproduces MCU tone-implied velocity with
  bias −0.002 / −0.001 m/s (runs 1/2); fixed-reference replay gives −0.02 / +0.00 m/s and
  removes 16.5/17.5 s → 0.0/1.2 s of false-lift ON-time while preserving ~49 s/run of
  genuine ascent audio. Thermal (dT/dt), door/piston pressure-equalisation, estimator
  dynamics, and firmware processing hypotheses all ruled out with recorded evidence.
- **Fix:** fixed ISA reference 101325 Pa; p0 accumulator removed (−32 KB DRAM).
  Estimator velocity is invariant to constant offset → zero risk to genuine climb detection.
- **Verification:** replay (both elevator runs) + bench (`idf_p0fix_static`, 75 s: no
  sustained lift, no 50 s window, blips spread uniformly).
- **Report:** `docs/Vario_USB_FalseLift_ESP_IDF_Validation_Report.pdf` §5–§7.

## DEF-002 — C03 steady-state refit storm (CPU 1330 µs/update)
- **Status:** FIXED + verified (bench)
- **Found:** 2026-10-23, elevator run 1 B-line CPU accounting
- **Component:** `esp-idf/vario/main/estimators.c` (`c03_update` / `c03_refit`)
- **Symptom:** C03 cost 1330 µs avg / 2671 µs max per update on ESP32-S3 (25–50× other
  estimators).
- **Root cause:** baro sample dt is bimodal 20/40 ms (40 ms slot at every temperature
  conversion; 25% of samples). C03 refits its steady-state gains (200-iteration discrete
  Riccati) whenever dt drifts >2%; the 20↔40 ms ping-pong re-ran the refit on ~half of all
  updates.
- **Fix:** gain cache keyed by 1 ms-quantised dt (4 slots); each distinct dt refits once.
- **Verification:** bench — 1330 → 38 µs avg (max 2676 µs is the one-time first refit).
- **Note:** cache is compile-verified only for >2 distinct dt patterns beyond 20/40 ms;
  no such pattern observed to date.

## DEF-003 — B-line diagnostic truncation loses last estimator CPU pair
- **Status:** FIXED + verified (bench)
- **Found:** 2026-10-23 (data-dependent; present since B-lines introduced)
- **Component:** `esp-idf/vario/main/bench.c` (`bench_report`, buf[512])
- **Symptom:** when other fields grew (e.g. vmax=10904), the 10th `c=` pair (FUS sid1)
  fell off the 512-byte buffer.
- **Fix:** buf 512 → 768 bytes.
- **Verification:** bench — all 10 pairs present in every B-line (`idf_bbuf_check`).

## DEF-004 — GY-63 clones clock out zeros while converting (d1=0 / partial ADC)
- **Status:** FIXED + verified (dynamic)
- **Found:** 2026-10-23 (idf dynamic captures, ~33% of reads with zero I2C errors)
- **Component:** MS5611 read pipeline (`main.c`)
- **Root cause:** clones ACK and shift out zeros/partial ADC during conversion instead of
  NAKing; "OSR2048" conversion actually exceeds 10 ms.
- **Fix:** read pipeline N+2 → N+4 ticks (≥20 ms window). abad=0 on all captures since.
- **Verification:** dynamic (elevator runs, handtest3) + bench.

## DEF-005 — NaN from unseeded temperature poisons running pressure mean
- **Status:** FIXED + verified (bench)
- **Found:** 2026-10-23 (silent-audio investigation)
- **Component:** `baro_proc.c` + estimator feed gating
- **Root cause:** at boot d2=0 → compensation explodes negative → NaN poisoned the p0
  running mean permanently; audio died silently.
- **Fix:** NaN-guarded compensation return; NaN-gated `bank_feed_baro`; s_d2 seeded to
  prom[5]·256; estimator feeds held until first real T frame per sid (`s_t_seen`).
- **Verification:** bench (von counters, vnan=0 since).

## DEF-006 — MS5611 clones fail init after power-up / rewiring
- **Status:** FIXED + verified (bench)
- **Component:** `ms5611_init`
- **Fix:** reset + PROM read retried up to 4×.
- **Verification:** bench (boot health lines status=ok).

## DEF-007 — Clone temperature coefficient (dT/dt → fake altitude rate)
- **Status:** OPEN (mitigated; root fix pending BMP581)
- **Found:** 2026-10-22 (handtest2: ~90 m phantom descent over 5 °C cooling, pre-foam)
- **Component:** sensor hardware (GY-63 clone MS5611s)
- **Mitigation:** 25 mm sensor spacing + foam isolation: sid0 detrended noise 388 → 90
  LSB (4.3×); thermal transients strongly damped.
- **Residual:** small dwell wobble (~+0.2 m/s median, short events) observed in both
  elevator runs; present with fixed reference too (not DEF-001). Characterisation
  incomplete — may be second-order tempco through the foam.
- **Planned fix:** BMP581 breakout (ordered) + keep MS5611 path for comparison.

## DEF-008 — USB Serial/JTAG host stalls; esp_timer races ~70× during stalls
- **Status:** PARKED (workaround documented)
- **Found:** 2026-10-23 (multiple captures)
- **Workaround:** restart MCU before each capture; watch live line counter, cancel and
  restart if drops climb. Ring buffer (240 KB) rides short stalls.
- **Impact:** long stalls lose data; clock racing corrupts dt within affected segments
  only; clean segments unaffected.

## DEF-009 — FUS IMU-side propagation CPU not charged to any estimator eid
- **Status:** OPEN (accounting gap only)
- **Component:** `estimators.c` (`bank_feed_imu` → `fus_feed_imu`, no `bench_cpu` call)
- **Impact:** FUS CPU (eid 4/9) is baro-side only; total FUS cost underestimated in B-lines.

## DEF-010 — Startup audio flapping / transient (first seconds after stream start)
- **Status:** OPEN (expected behaviour, documented)
- **Found:** all captures
- **Notes:** estimators initialise on first baro sample; brief tone flapping in the first
  seconds. Distinct from DEF-001 (which was systematic for 50 s, now gone). Mitigated by
  keeping the board still at capture start; min-on-time/hold audio policy tuning deferred
  to the audio-benchmark phase.
