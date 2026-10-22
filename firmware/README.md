# firmware/ — ESP32-S3 test-rig firmware

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
