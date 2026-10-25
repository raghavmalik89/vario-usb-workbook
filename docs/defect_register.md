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
- **Mechanism (2026-10-24, Bench 6):** firmware boots with d2 seeded at
  prom[5]·256 (20 °C) until the first T frame; the compensation step at that
  frame produces the capture-start altitude step that rings the estimators
  (tones clamp at +6.67 m/s; amplified to −1.5e4 m/s transient under
  DEF-011). Reproduced in replay by `seed_d2=True` (bench6 streams); startup
  (t < 8 s) excluded from all scoring and reported separately.

## DEF-011 — `compensate_pa` returns 10× pressure scale; post-p0fix velocities ×1.5498, absolute altitude garbage
- **Status:** OPEN (masked for a firmware generation; must fix in the BMP581 integration build)
- **Found:** 2026-10-24 (Bench 6 MCU-equivalence, `filter_benchmark/bench6/equiv6.py`)
- **Component:** `esp-idf/vario/main/baro_proc.c::compensate_pa` returns `p01mbar*10.0`
  while the Python reference (`analysis/common.py`) returns `p*1.0` — a 10× scale
  deviation.
- **Masking history:** under the moving-p0 firmware (pre-DEF-001-fix) the ratio p/p0
  cancelled the scale, so all pre-p0fix MCU tone streams are true-scale and valid.
  The p0fix hardcoded 101325 Pa (common-line units) against the still-10× pressure,
  so post-fix firmware scales velocities by exactly 10^0.1903 = 1.5498 and reports
  absolute altitude ≈ −23 725 m.
- **Impact:** post-p0fix MCU-side absolute altitude is garbage; velocity-shaped
  behaviour is self-consistent (×1.5498). Bench captures remain valid for
  velocity/audio analysis; replay equivalence must use `reference='isa_fw10'`.
- **Evidence:** `filter_benchmark/bench6/results/65_mcu_equiv.csv`,
  `fig13_mcu_equivalence.png`; archived build README
  `esp-idf/firmware_archive/vario_idf_MS5611x2_MPU6050_p0fix_r8e79e68_20261023/`.
- **Planned fix:** single scale constant in the sensor-integration build
  (BMP581/LSM6DSV16X); re-run `equiv6.py` with the common-scale chain.

## DEF-012 — Virtual-audio tone channel asymmetric: descents < −0.22 m/s emit no V-frames
- **Status:** DOCUMENTED (design constraint, not a bug per se)
- **Found:** 2026-10-24 (Bench 6 equivalence tone inspection)
- **Detail:** implied v = (f−500)/450 with f clamped to [400, 3500] Hz represents
  v ∈ [−0.22, +6.67] m/s; the firmware suppresses tones below 400 Hz. MCU tone
  streams are blind to strong sink; sink audio behaviour must be scored from
  replay audio state machines, not MCU tones.

## DEF-013 — Pre-p0fix gate-decision chaos: S4/S5 (mildly C03/FUS) replay tones diverge from MCU in the moving-p0 window
- **Status:** CLOSED (root-caused to era; does not affect scoring)
- **Found:** 2026-10-24 (`equiv6.py` Part A, t = 8–50 s of pre-p0fix captures only)
- **Detail:** D01 (the plain Kalman inside both stacks) matches MCU tones to ~1 mm/s
  everywhere, so the raw reconstruction is exact; the divergence lives in
  discontinuous gate latches amplifying sub-LSB reconstruction micro-differences
  while the defective moving reference was active. Frozen-p0 era (t ≥ 50 s) matches
  to p95 1.0–60 mm/s for all five estimators on all captures.
- **Impact:** old-firmware equivalence bookkeeping only; all scoring uses fixed-ISA
  streams and is unaffected.

### DEF-010 update (2026-10-24) — mechanism identified — the firmware boots with
  d2 seeded at prom[5]·256 (20 °C) until the first T frame; the compensation step
  at that frame produces the capture-start altitude step that rings the estimators
  (tones clamp at +6.67 m/s; amplified to −1.5×10⁴ m/s transient under DEF-011).
  Reproduced in replay by `seed_d2=True`; startup (t < 8 s) is excluded from all
  scoring and reported separately.

## DEF-014 — Reference-smoother boundary artifact: phantom handtest events (startup "event", "toss")
- **Status:** FIXED in `filter_benchmark/bench6/streams.py::reference_v` (2026-10-24, post-Bench-6-commit correction); archived Phase 2–5 `src/metrics.py` intentionally left frozen as the historical artifact
- **Found:** 2026-10-24 (post-commit report verification, Bench 6)
- **Detail:** the ±3 s Gaussian reference smoother behind handtest event metrics used `np.convolve(alt, k, mode="same")` with zero padding. The smoothed altitude ramps from ~50 % of true value over the first/last ~3 s of a stream, manufacturing phantom reference velocity at both boundaries. On handtest3 this created two fictitious events (startup 0–3.8 s; toss 148.2–151.9 s with a fictitious ≈ 4 m/s peak) and two fictitious slow blocks.
- **Physical refutation:** at 144–152 s IMU |a|−g peaks at 0.17 m/s² and baro altitude moves ±0.5 m — no toss occurred; whole-session altitude span (10–140 s) is 3.36 m of gentle hand motion.
- **Impact:** handtest onset/release/toss metrics void (withdrawn from the Phase 6 report); composite ranking re-computed with slow-block |bias| replacing the phantom onset term — top-5 changes from (C03, C01, S2, S1, S4) to (C03, C01, B02_project_kalman, E06, S2), exposing S1's real +0.63 m/s slow-descent false-lift. Elevator, static, MCU-equivalence, rate-control and CPU results unaffected (never used the defective smoother).
- **Fix:** smoother now normalizes by the effective window weight (`np.convolve(alt,k,"same")/np.convolve(ones,k,"same")`). Verified: v_ref head/tail ≈ 0.003–0.009 m/s, zero events, slow blocks unchanged.
- **Lesson:** any boundary-windowed smoother used for reference derivation must be weight-normalized; event metrics near stream edges are suspect by construction.

## DEF-011 process gate (2026-10-24) — REQUIREMENT before further physical validation
- DEF-011 (10× pressure scale, velocities ×1.5498, absolute altitude garbage) must be
  corrected in the sensor-integration build **before any further physical validation
  campaign, any absolute-altitude comparison, or any cross-sensor benchmark**.
  Existing bench captures remain valid for velocity/audio analysis via the `isa_fw10`
  replay chain until the fix lands.

## DEF-015 — Elevator capture host-elapsed (172.74 s) vs device-timestamp span (191.69 s) discrepancy
- **Status:** ROOT-CAUSED (host-side suspension during capture; device clock exonerated)
- **Found:** 2026-10-24 (BMP581 elevator capture `20261024_235054_idf_bmp581_elevator_2x`)
- **Component:** capture environment (Windows host USB/power management), not firmware.
- **Evidence:**
  - Same-build captures: static f=0.996, handtest f=1.005 (f = device span /
    host elapsed) — the device clock is intact; only the elevator capture shows f=1.110.
  - The file is internally perfect: 0 seq gaps, every seq exactly +1, max inter-frame
    device dt 10 ms, no backward jumps, no burst-flush signature in device time.
  - USB TX ring high-water ≈ **101 KB** in the elevator capture vs 0.6–1.1 KB in the
    static/hand tests (ring capacity 240 KB). ~101 KB ≈ 15–45 s of buffered stream.
  - Host-side `time.monotonic()` elapsed (172.74 s) is ≈ 19 s shorter than the device
    span, matching the buffered backlog: the host (or its USB stack) suspended for
    ~19 s while the user was away from the laptop in the elevator; the firmware kept
    streaming into the ring and the backlog drained on resume.
- **Impact:** device timestamps remain the only reliable clock for this capture;
  wall-clock durations of capture segments are not trustworthy. Cross-capture
  comparisons must use device-time velocities (which are intact). The late-night
  elevator was also genuinely ~11% faster than the Bench 6 runs (±1.66–1.74 vs
  ±1.55–1.60 m/s device-time) — this is a condition difference, not a clock error.
- **Mitigation for future captures:** disable USB selective suspend / keep the laptop
  awake during elevator runs; check sidecar `stats.elapsed_s` against the device span
  immediately after capture (flag |f−1| > 2%).

## DEF-016 — BMP581 STATUS.drdy is not cleared by data-register reads
- **Status:** FIXED (cadence read); fault dataset retained
- **Found:** 2026-10-24 (BMP581 bring-up `20261024_225226_idf_bmp581_bringup`)
- **Component:** `esp-idf/vario/main/main.c::bmp581_service` (original drdy-poll design)
- **Detail:** polling STATUS (0x28) bit0 on every 5 ms tick re-asserted continuously:
  200 reads/s emitted against only ~40 unique register values/s (bit-identical 6-byte
  repeats). Register writes were verified correct via readback (osr_cfg=0x61,
  odr_cfg=0xc5), so the part was converting at the programmed 40 Hz while the flag
  behaved level-style. The Bosch reference driver never polls STATUS; it burst-reads
  data directly.
- **Fix:** fixed 25 ms cadence read (every 5th 5 ms tick) matching the programmed
  ODR; verified 40.0 Hz, dt exactly 25 ms, 98% fresh values (bringup2 capture).
- **Fault dataset:** `20261024_225226_idf_bmp581_bringup` retained.
- **Note:** every BMP581 P frame carries its own fresh temperature (on-chip
  compensation) — the DEF-010 d2-seed boot step does not exist for this part.

## DEF-017 — LSM6DSV16X residual I2C NACKs on IMU read path
- **Status:** MITIGATED (retry + burst read); root cause suspected hardware
- **Found:** 2026-10-25 (`20261025_121517_idf_lsm6dsv_bringup`)
- **Component:** `esp-idf/vario/main/imu_lsm6dsv16x.c` (wrapper) — transactions NACKed by the sensor
- **Detail:** ~70 E frames/s at first bring-up. Mitigations: bounded retry
  (3 attempts, 2 ms spacing) + single 14-byte burst (0x20..0x2D) instead of 3
  separate register-block reads → worst case cut 5× (2094→444 E/30 s, bringup3).
  Residual ~15–27/s with ~2× run variance (444 vs 802 on identical config).
  A 120 Hz ODR experiment made it *worse* (905/30 s, stale 11.7%), disproving
  the conversion-collision model. Failure pattern (bursty NACKs, garbage WHO_AM_I
  0x44 in one run, strong run-to-run variance) points at a marginal electrical
  path on the hand-installed breakout (joints/pull-ups), not firmware.
- **Impact:** I-stream drops to ~85–93 Hz (target 100); stale-reuse feeds the
  last fresh sample so estimators never receive silently-corrupt IMU data;
  E frames are telemetry noise for analysis scripts to ignore/filter.
- **Action:** check SDA/SCL solder joints and pull-up placement on the breakout
  when convenient; do not chase further in firmware.

## DEF-018 — LSM6DSV16X intermittent init wedge after MCU reset
- **Status:** MITIGATED (`i2c_master_bus_reset()` + full reconfigure); power-cycle is fallback
- **Found:** 2026-10-25 (`20261025_122844/123018/123416/123522` bringup4/5/7/8)
- **Component:** sensor I2C front-end state retained across MCU reset
- **Detail:** ~50% of reset/boot cycles the sensor NACKs all init transactions
  (sometimes returning garbage WHO_AM_I=0x44) and never recovers within the
  session → `health_fail_halt`. Fix: on init failure, `i2c_master_bus_reset()`
  (IDF SCL bit-bang recovery) + 20 ms + full reconfigure, then declare missing.
  bringup9 booted with the recovery in place. An internally-wedged front-end
  still requires a USB power-cycle.
- **Operational note:** if a capture starts with `health_fail_halt`, power-cycle
  the board (EN/RTS reset does not power-cycle the sensor rail).

## DEF-019 — LSM6DSV16X CTRL1/2 readback in meta contradicts verified runtime config
- **Status:** OPEN (cosmetic; readback untrusted)
- **Found:** 2026-10-25 (all bringup captures)
- **Component:** `imu_lsm6dsv16x.c` config readback latched into `#C` meta
- **Detail:** meta reports ctrl1=0x07, ctrl2=0x07/0x00, ctrl3=0x44/0x00 across
  runs, vs expected 0x78/0x78/0x44 for 240 Hz + ±8g/±500dps + BDU. Runtime
  behavior proves the configuration landed (240 Hz fresh samples, 4096 LSB/g
  scale confirmed by |a|=0.9989 g, gyro live). Register addresses verified
  against the ST header. Readback path is unreliable — likely the same NACK
  phenomenon (DEF-017) returning stale/shifted bytes during a deaf window.
- **Impact:** none on data; do not use the ctrl meta fields as config evidence.

## DEF-020 — ROOT CAUSE of DEF-017/018: bus A at 400 kHz with only weak internal pull-ups; runtime wedge at ~25 s
- **Status:** FIXED (bus A lowered to 100 kHz + runtime recovery FSM); verified 60 s + 90 s at zero IMU errors
- **Found:** 2026-10-25 (`20261025_131550_idf_bmp581LSM6DS_static0`, 90 s static)
- **Component:** IMU I2C electrical layer — LSM6DSV16X breakout has no onboard
  pull-ups; firmware relied on `enable_internal_pullup` (~45 kOhm) on GPIO4/5.
- **Root cause:** at 400 kHz the bus RC rise time (weak pull-up + jumper
  capacitance) is far outside I2C fast-mode timing. The ACK bit is sampled
  during a still-rising edge -> master reads NACK on healthy transactions
  ("quick NACKs", DEF-017); repeated error-path transactions desync the ESP32
  I2C FSM / the slave front-end until the link goes permanently deaf
  (DEF-018 wedge — now observed at runtime, not only at boot). Progressive
  failure culminating at ~25 s in the user's captures matches thermal drift of
  the marginal timing; run-to-run variance (some runs healthy for 30+ s at
  identical firmware) matches noise/crosstalk dependence.
- **Collateral damage, verified in counters:** each failing poll burned
  3 attempts + 2x2 ms delays, stretching the shared 5 ms sens tick to ~6.4 ms;
  the BMP581 cadence (every 5th tick) slipped 25 -> 32 ms exactly (5 x 6.4).
  Not a bus conflict — pure task-time contention. After deafness: i2c_mpu and
  i2slow counters saturated at 1000/5 s window.
- **Fix:** (1) `I2C_FREQ_HZ_A = 100000` for bus A only (BMP581 bus B stays at
  400 kHz with its own breakout pull-ups). 100 kHz tolerates the weak pull-up
  RC with large margin; IMU burst costs ~1.4 ms, 2.4% of the tick budget.
  (2) Runtime recovery FSM in `lsm_imu_read`: 200 ms of solid failure ->
  DEGRADED (one cheap probe per 100 ms, E code 1 throttled to 10/s), bus reset
  + full reconfigure every 2 s (E code 3), instant exit on first good probe.
  Prevents the tick-stretch collateral even for future wedges.
- **Verified:** `20261025_163348_idf_lsm6dsv_fixcheck60s` — 0 E frames,
  100.0 Hz I stream in every 5 s window, 0.0% stale, baro 39.95 Hz steady;
  `20261025_163515_idf_lsm6dsv_fixcheck90s` — 0 E frames, 100.0 Hz throughout,
  0.0% stale, baro 40 Hz, imu_rec=0 (FSM never needed). Compare: static0 had
  15318 E1 + 193 E2, IMU dead after 25.15 s, baro at 31.25 Hz.
- **Hardware recommendation:** add external ~2.2 kOhm pull-ups on GPIO4/SDA and
  GPIO5/SCL (breakout or inline) if 400 kHz is ever needed back; at 100 kHz
  none are required. DEF-017/018 symptoms should be considered fully explained
  by this defect; the recovery FSM is retained as insurance.
- **Note:** device-vs-host span discrepancy in static0 (119.3 vs 90.2 s) is the
  known host-side USB backlog class (DEF-015/elevator finding, ring_hw 136 KB):
  host paused ~29 s and drained the backlog. Acquisition itself is intact when
  device-time cadence is used.
