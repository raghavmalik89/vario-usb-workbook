# Phase A capture checklist — R-1 three-sensor bench set (2026-10-22)

**Goal:** per-unit clone-quality statistics, full 3×3 noise-correlation matrix,
and the spatial-decorrelation answer (does moving GY-63 #3 out of the shared
chamber drop corr below the +0.65 measured in T-003?).

**Firmware:** `arduino/t005_triple_stream/t005_triple_stream.ino` (v0.5.0,
compile-checked). Three sids: 0 = Bus A (0x76), 1 = Bus B (0x77),
2 = Bus C bit-bang (address auto-probed 0x77→0x76, reported in health check).
45 Hz P + 5 Hz T per sensor. IMU health-checked only, not streamed.

---

## 0. Pre-flight (learned the hard way — do these)

1. **Close the Arduino Serial Monitor.** It locks COM5 ("Access is denied").
   If a capture fails with access denied, kill `serial-monitor.exe` in Task
   Manager (the IDE itself can stay open).
2. Flash t005 (IDE: USB CDC On Boot = Enabled), or:
   ```
   "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" upload -p COM5 --fqbn esp32:esp32:esp32s3 arduino/t005_triple_stream
   ```
3. **Verify the stream before any real capture** (this is the wiring check):
   ```
   python tools/capture.py --port COM5 --label t005_preflight --duration 15
   ```
   Then confirm the sidecar has THREE PROM sets:
   ```
   python -c "import json; d=json.load(open('analysis/data/<timestamp>_t005_preflight.json')); print([k for k in d['device'] if 'prom' in k])"
   ```
   Must print `prom_0, prom_1, prom_2` (exact key list, e.g. `['prom_0',
   'prom_1', 'prom_2']`). Also check the capture printed `#C,health=ok`
   with zero or near-zero `E` frames. **If `prom_2` is missing:** bus C
   isn't talking — reseat GY-63 #3 (GPIO15=SDA, GPIO16=SCL, 3V3, GND) and
   run `arduino/i2c_scan_test` to see which address answers on Bus C.

## 1. Captures (in order, distinct labels — never reuse a label)

| # | Label | Duration | Procedure |
|---|-------|----------|-----------|
| 1 | `t005_static_60s` | 60 s | Rig sitting still on the desk. Hands off, no touching, doors closed. All three sensors in their normal positions. |
| 2 | `t005_spatial_60s` | 60 s | Move **GY-63 #3 (sid 2)** out of the shared enclosure — on a dupont lead, ~0.5 m away from the rig, same room, sitting still. Note the placement in the log message if you like; the label says it. |
| 3 | `t005_spatial_back_60s` | 60 s | Put #3 back where it was (same as capture 1 geometry). Confirms the decorrelation effect is spatial, not drift. |
| 4 | `t005_elevator_f14` | ~100 s | Ride floor 14→1→14 holding the rig still. Same protocol as T-004. |
| 5 | `t005_step_drop` | ~30 s | Four ~1 m drops onto a cloth, a few seconds apart. Same protocol as T-004. |

Between captures: don't reset the board, just run capture.py again — the
meta-on-attach re-emits #H/#K/#C 2.5 s after each attach.

## 2. Analysis (run by the assistant, or yourself)

```
python analysis/03_dual_sensor_compare.py '*t005_static*'        # clone quality + 3x3 matrix
python analysis/03_dual_sensor_compare.py '*t005_spatial*'        # does corr(sid2, others) drop?
python analysis/03_dual_sensor_compare.py '*t005_spatial_back*'   # control
python analysis/04_filter_replay.py '*t005_elevator*' --sid=0     # per-unit motion replay
python analysis/04_filter_replay.py '*t005_step_drop*' --sid=0    # (repeat for sid 1, 2)
```

Note: t005 has no IMU frames, so estimator C (Kalman + accel) is skipped for
these runs — that's expected; fusion replay continues on the t002-family
captures. Use sid 0/1/2 reruns of the elevator/drop to compare unit behavior
under motion (catch spikes, ring-down).

## 3. What we expect to learn

- **Capture 1:** which physical unit is quietest (research ranks "one better
  sensor" above any multi-sensor averaging) + the full correlation matrix.
- **Captures 2 vs 3:** if corr(sid2, sid0/1) falls well below +0.65 when #3
  leaves the shared chamber → port placement matters, dual averaging gains
  are recoverable with separated ports. If it stays high → common-mode is
  room-scale (pressure drafts, HVAC), settle it for good.
- **Captures 4–5:** per-unit impulse behavior — does the same drop look
  identical on all three units, and does any unit show anomalies (the clone
  quality question under motion, feeding ADR-011).
