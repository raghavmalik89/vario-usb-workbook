# firmware/ — ESP32-S3 test-rig firmware

> **STATUS (2026-10-22):** the plan below is historical — actual firmware
> lives in `../arduino/` and speaks protocol v1: `i2c_scan_test` (T-000),
> `t001_baro_stream` 0.1.3, `t002_baro_imu_stream` 0.2.2,
> `t003_dual_baro_stream` 0.3.1, `t005_triple_stream` 0.5.0 (R-1 3-sensor
> set). Inventory with roles: `../docs/HANDOVER.md` §3.
> **Test numbering:** ours are T-000…; research-PDF-derived tests are
> R-1…R-5 (collision warning: `../docs/HANDOVER.md` §10).

Not written yet. When it is, it must speak **serial protocol v1** exactly:
see `../docs/serial_protocol.md`. The capture script and all analysis assume it.

Target bring-up order (from TEST_PLAN):

1. `scan` — I²C bus scan tool: report every address found on buses A/B/C.
2. T-001 firmware — one MS5611 @ OSR4096, P/T frames + `#K` calibration dump.
3. T-002 — add MPU6050 at 200 Hz `I` frames.
4. T-003 — add MS5611 #2 (bus B) and #3 (bus C, bit-banged).
5. T-004 — same firmware, disturbance runs.

Suggested stack: ESP-IDF with `esp_timer` periodic sampling + USB-CDC
(`tinyusb`) for output. Arduino core + `Serial` is acceptable for T-001
only — the 921600 baud CDC link will be the first thing the noise-floor
script validates whether it was a good idea.
