# Firmware Archive — vario_idf (ESP-IDF) — MS5611×2 + MPU6050 generation

**Label:** `vario_idf_MS5611x2_MPU6050_p0fix_r8e79e68_20261023`

**Purpose:** Preserved known-good firmware for the current sensor set
(2× MS5611 GY-63 clones + MPU6050 on ESP32-S3 @ 240 MHz). Use this binary
later as the **A/B reference** when the BMP581 + LSM6DSV16X breakouts arrive:
flash this image to compare new-sensor captures against the Bench-6 baseline
without rebuilding, then flash the sensor-integration build.

## Provenance

- **Source commit:** `8e79e68c897846fa1681a94c464863c9cc9c4d07`
  ("False-lift root cause (moving p0 reference): fixed ISA ref, C03 gain
  cache, B-buffer; elevator evidence, replay proofs, bench validation,
  report + defect register + history"), 2026-10-24 00:02 +0800
- **Built:** 2026-10-23 23:49 (idf.py build, esp-idf/vario)
- **Flashed and bench-validated:** captures `20261023_234521_idf_p0fix_static`
  and `20261023_234944_idf_bbuf_check` (analysis/data/)

## SHA-256

| File | SHA-256 |
|---|---|
| vario_idf.bin | 8f3a1cdea8d71f23b1f8373835f6ecca46dd1d2ca92d1588040a1a87caf9ae51 |
| bootloader.bin | 75d8896f913500fe4dff0d4dc20b01bf0cf4ec61453e9ab512dbbd64fabd256f |
| partition-table.bin | 7f00b6c042a89b15b0cac534f82ed988caf29278ff5700b0c511eb1b5bb7c820 |

## Configuration snapshot (esp-idf/vario/main/config.h @ 8e79e68)

- Baro: 2× MS5611 clones, 40 Hz + 10 Hz temp (N+4 read pipeline), foam-covered
- IMU: MPU6050 @ 100 Hz
- Estimator bank (eid = sid*5 + est): D01 Kalman-CV, C03 CV-tracker,
  S4 FastSlow-gated, S5 LightGate-KF, FUS baro+IMU (Madgwick)
- Virtual audio policy: lift_on +0.20 / lift_off +0.05 m/s,
  tone v = (f−500)/450, f ∈ [400, 3500] Hz (note: **asymmetric** clamp,
  descents saturate at −0.22 m/s implied)
- CPU B-lines streamed per estimator (avg/max µs)

## Known defects in this build (do not "fix" retroactively — document instead)

- **DEF-011:** `baro_proc.c::compensate_pa` returns pressure in the
  firmware's 10× common.py scale; with the post-p0fix fixed 101325 Pa
  reference this scales velocities by exactly 1.5498 and absolute altitude
  is garbage (−25.7 km). Relative/velocity behaviour is self-consistent;
  Bench-6 equivalence replays must use `reference='isa_fw10'`.
- **DEF-010:** boot d2 seed (prom[5]·256, 20 °C) causes a capture-start
  altitude step → startup audio flap in the first ~seconds; decaying.
- **DEF-009:** FUS IMU-side CPU not charged to the FUS B-line entry.

## Flash-back command

```bat
cmd //c "tools\idf.bat -C esp-idf/vario -p COM5 flash"   :: from a checkout @ 8e79e68
:: or direct esptool using flasher_args.json in this directory
```
