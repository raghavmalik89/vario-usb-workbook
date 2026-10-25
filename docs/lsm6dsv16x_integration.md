# LSM6DSV16X Integration Report — 2026-10-25

**Scope:** replace the MPU6050 with the LSM6DSV16X (Bus A, GPIO4/5, 0x6B) in the
ESP-IDF vario firmware using ST's official platform-independent driver. BMP581
path, estimator bank, virtual audio, and USB telemetry untouched. No filter
benchmark in this phase.

**Status:** INTEGRATED AND VALIDATED (static bring-up). Firmware builds clean,
flashes, and streams baro 40 Hz + IMU ~85–93 Hz with 0 sequence drops and 0 bad
lines. Three known issues documented below (DEF-017/018/019); none block the
upcoming Bench 8 comparison.

---

## 1. Sensor configuration (as flashed)

| Parameter | Value | Notes |
|---|---|---|
| Part / WHO_AM_I | LSM6DSV16X @ 0x6B / 0x70 | probed, verified |
| Driver | `lsm6dsv16x_reg.{c,h}` from STMicroelectronics/lsm6dsv16x-pid, **unmodified** | platform via `stmdev_ctx_t` callbacks |
| Accel FS / Gyro FS | ±8 g / ±500 dps | 4096 LSB/g, 65.5 LSB/dps — identical scale to MPU6050, meta constants unchanged |
| ODR both axes | 240 Hz | nearest ≥ the 200 Hz target; see §5 (120 Hz empirically worse) |
| BDU | on | block-data-update, no register tearing |
| Host stream | I frames at ~100 Hz (every 2nd 5 ms tick) | fresh-sample gated; stale reuse of last fresh sample |
| Attitude/fusion feed | on every fresh sample | |

## 2. Measured acquisition (static validation, `..._bringup9`)

- **Baro (BMP581, untouched):** 39.9 Hz, P frames 1198/30 s, 96694 Pa,
  RMS noise 0.23 Pa (~1.9 cm). Perfect.
- **IMU stream:** 2584 I frames/30 s (~86 Hz this run; 92–96 Hz on other runs),
  stale repeats 4.3% (fusion/attitude consume fresh samples only).
- **Accel:** mean (−0.023, −0.020, −0.998) g — **gravity now on −Z** (the MPU-era
  mount had gravity on +X). Mounting orientation changed; Madgwick attitude
  self-adapts, but cross-era IMU comparisons must account for the axis change.
  |a| = 0.9989 ± 0.0007 g.
- **Gyro:** per-axis noise 0.033 dps (vs MPU6050's ~0.4–0.9 dps on this rig) —
  roughly a 15–25× improvement; bias < 0.1 dps.
- **Telemetry integrity:** 0 seq drops, 0 bad lines, all 30 s.

## 3. Changes made

| File | Change |
|---|---|
| `esp-idf/vario/main/lsm6dsv16x_reg.{c,h}` | NEW — ST official driver, copied unmodified |
| `esp-idf/vario/main/imu_lsm6dsv16x.{c,h}` | NEW — wrapper: ctx adapters, init (probe+config+readback), fresh-gated burst read |
| `esp-idf/vario/main/main.c` | sens_task calls `lsm_imu_read`; stale reuse via `s_raw_prev`; probe 0x6A→0x6B fallback; meta `type=lsm6dsv16x`, `odr=240hz`; E frames carry `last_err` code |
| `esp-idf/vario/main/config.h` | MPU_* scale constants renamed `IMU_A_LSB_PER_G=4096`, `IMU_G_LSB_PER_DPS=65.5` (same values) |
| `esp-idf/vario/main/CMakeLists.txt` | `mpu6050.c` → `lsm6dsv16x_reg.c` + `imu_lsm6dsv16x.c` (mpu6050.c/h left in tree, unreferenced) |
| `analysis/lsm_bringup_check.py` | NEW — reusable static-validation script (rates, E-codes, freshness, gravity, gyro, baro) |

Wrapper design points:
- **Single 14-byte burst** `0x20..0x2D` (temp, gyro, accel are contiguous, IF_INC
  on) instead of three separate ST calls — halves collision chances per sample
  and removes inter-block tearing.
- **Bounded retry** (3 attempts, 2 ms spacing) on every ST call: at 240 Hz the
  part NACKs stretches of transactions; the retry span covers one conversion
  period. Cost only on already-failing ticks.
- **Init hardening:** probe retry (5×5 ms), full reconfigure after
  `i2c_master_bus_reset()` on first failure (DEF-018).

## 4. Bring-up iteration history (30 s static captures)

| Run | Config | E frames/30 s | I rate | stale | Notes |
|---|---|---|---|---|---|
| bringup1 | no retry, 3 calls, 240 Hz | 2094 | 65 Hz | 0% | NACK storm |
| bringup2 | retry 1 ms, 3 calls | 630 | 90 Hz | 0.4% | |
| bringup3 | retry 2 ms, burst | **444** | 93 Hz | 1.9% | best run |
| bringup4/5 | 120 Hz exp. | — | — | — | init wedge (halt) |
| bringup6 | 120 Hz | 905 | 85 Hz | 11.7% | 120 Hz **worse** — reverted |
| bringup7/8 | 240 Hz restored | — | — | — | init wedge (halt) |
| bringup9 | + bus-reset recovery | 802 | 86 Hz | 4.3% | valid; run variance ±2× |

## 5. Key findings

1. **The NACK issue is not conversion-collision.** The collision model predicted
   120 Hz would halve NACKs; measured it doubled them. The residual failure rate
   also varies ~2× between identical runs (444 vs 802). Behavior matches a
   marginal electrical path (hand-installed breakout: check SDA/SCL joints and
   pull-up placement when convenient) rather than a firmware or driver defect.
   The retry+burst mitigations cut the worst case 5× (2094→~400–800).
2. **Post-reset init wedge (~50% of resets):** after an MCU reset the sensor can
   go deaf mid-init (NACKs everything, sometimes returns garbage WHO_AM_I).
   `i2c_master_bus_reset()` + full reconfigure was added; bringup9 booted with
   it. If the rig reports `health_fail_halt`, power-cycle the USB (only a
   power-cycle clears an internally-wedged front-end).
3. **CTRL readback values in the meta are unreliable** (0x07/0x07/0x00 observed
   vs expected 0x78/0x78/0x44) while runtime behavior proves the configuration
   (240 Hz fresh samples, correct scales, |a| ≈ 0.999 g). Do not trust the
   ctrl1/2/3 meta fields until re-investigated; treat them as advisory only.
4. **Data quality is a large step up from MPU6050:** gyro noise 0.033 dps vs
   ~0.5 dps, accel ±0.0007 g stability, 100% sensible magnitudes.

## 6. Reproduce

```
cmd //c "tools\idf.bat -C esp-idf/vario build"
cmd //c "tools\idf.bat -C esp-idf/vario -p COM5 flash"     # after clean build only
python tools/capture.py --port COM5 --label idf_lsm6dsv_check --duration 30
python analysis/lsm_bringup_check.py analysis/data/<capture>.csv
```

## 7. Unresolved issues (see defect register)

- **DEF-017** — residual IMU I2C NACKs (~15–27/s E frames, 2× run variance);
  mitigated, root cause suspected hardware. E frames are telemetry-only; data
  path uses stale-reuse so no estimator input is lost silently.
- **DEF-018** — intermittent post-reset init wedge; bus-reset recovery added,
  power-cycle is the final fallback.
- **DEF-019** — CTRL1/2/3 readback in meta contradicts verified runtime config.

## 8. Next steps (not in this scope)

- Bench 8 filter comparison on BMP581 captures (previous task queue), then
  dynamic captures (hand + elevator) with this IMU, then the cross-sensor
  estimator re-benchmark. Do not change estimator algorithms/parameters before
  the frozen-config comparison is done.
