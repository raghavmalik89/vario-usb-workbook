# Serial Protocol v1 — ESP32-S3 test rig → PC logger

Text protocol, one frame per line, terminated by `\n` (firmware may also emit `\r\n`
— the logger strips `\r`). No binary framing: human-readable, greppable, and fast
enough at 921600 baud for all planned rates (3 × baro @ 50–100 Hz + IMU @ 200 Hz
≈ 700 lines/s ≈ 45 kB/s ≈ 4 % of the link).

**Baud:** 921600, 8N1. **Clock:** `esp_timer_get_time()` (microseconds, wraps in
~292 000 years — treat as monotonic).

## Frame types

### Boot / meta (start with `#`, emitted once at startup)

| Frame | Fields | Meaning |
|-------|--------|---------|
| `#H` | `fw_name, fw_version` | banner. e.g. `#H,vario-bench,0.1.0` |
| `#K` | `sid, c1, c2, c3, c4, c5, c6` | MS5611 PROM calibration words for sensor `sid`. One per barometer. **The logger needs these — compensation happens offline.** |
| `#C` | `key=value, key=value, ...` | free-form config. Suggested keys: `osr=4096`, `p_hz=100`, `t_hz=10`, `i_hz=200`, `imu=on/off` |

### Data lines (no `#`)

```
P,<seq>,<t_us>,<sid>,<d1>
T,<seq>,<t_us>,<sid>,<d2>
I,<seq>,<t_us>,<ax>,<ay>,<az>,<gx>,<gy>,<gz>
E,<seq>,<t_us>,<code>
```

| Field | Type | Notes |
|-------|------|-------|
| `seq` | uint32 | **Global** monotonically increasing counter, +1 for every line emitted, all types. Gaps = dropped samples — this is how the logger detects loss. |
| `t_us` | uint64 | timestamp from `esp_timer_get_time()` at the moment the sample was read (not when the line was printed). |
| `sid` | 0–2 | barometer id: 0 = Bus A, 1 = Bus B, 2 = Bus C (soft). |
| `d1` | uint32 | MS5611 pressure ADC, **raw, uncompensated, 24-bit** (0 … 16777215). |
| `d2` | uint32 | MS5611 temperature ADC, raw, 24-bit. |
| `ax..gz` | int16 | MPU6050 raw accel / gyro counts (no scaling — do it offline). |

### Error codes (`E` line)

| code | meaning |
|------|---------|
| 1 | I²C NAK / device missing on a scheduled read |
| 2 | I²C timeout |
| 3 | buffer overflow (samples dropped by firmware — expect a `seq` gap after this) |

## Timing expectations (for firmware design)

- MS5611 OSR4096: pressure conversion ≈ 9.04 ms, temperature ≈ 9.04 ms → interleave
  at ~50 Hz pressure + 5–10 Hz temperature is realistic; OSR1024 ≈ 2.28 ms → ~100 Hz
  feasible. Log what you actually achieve via `#C`; the logger measures real rates.
- The 200 Hz IMU target is a *target*: if I²C + USB streaming can't sustain it, lower
  the rate and record the truth in `#C`. A stable 120 Hz beats a jittery 200 Hz.

## What the firmware must NOT do

- No filtering, no averaging, no compensation on the MCU. Raw ADC values only.
- No `printf` debugging to the same port mid-stream (breaks the CSV).
- No delays that block the sampling timer; if USB TX blocks, count the overflow and
  emit `E,…,3`.

## Worked example (startup → 3 data lines)

```
#H,vario-bench,0.1.0
#K,0,46372,43475,27885,21913,31071,28165
#K,1,46501,43510,27900,21890,31080,28100
#C,osr=4096,p_hz=50,t_hz=5,i_hz=200,imu=on
P,12,18423011,0,9086656
T,13,18425148,0,8384512
I,14,18426000,124,-36,15680,42,-17,9
```
