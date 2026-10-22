# Vario USB — bench analysis pipeline

Offline analysis for the ESP32-S3 test rig. Firmware speaks protocol v1
(see `../docs/serial_protocol.md`); `tools/capture.py` writes runs here.

## Layout

```
analysis/
├── data/          capture.py writes <timestamp>_<label>.csv + .json here
├── output/        plots from the scripts below
├── common.py      run loading, MS5611 compensation, altitude math
├── 01_noise_floor.py        T-001 stationary noise + Allan deviation
├── 02_step_response.py      T-004 elevator/step latency + rise time
├── 03_dual_sensor_compare.py  T-003 dual-barometer correlation & averaging gain
└── 04_filter_replay.py      T-008 replay: LPF vs CV-Kalman vs accel-fused (ADR-006/011)
```

## Setup

```
pip install -r requirements.txt
```

## Workflow

1. **Capture** (run from repo root or anywhere):
   ```
   python ../tools/capture.py --auto --label t001_bench_60s --duration 60
   ```
2. **Analyse** — every script takes a glob for the run, newest match wins:
   ```
   python 01_noise_floor.py '*t001*'
   python 02_step_response.py '*elevator*'
   python 03_dual_sensor_compare.py '*t003*'
   python 04_filter_replay.py '*elevator*'
   ```
   Plots land in `output/`; key numbers print to stdout — paste those into the
   dev log, don't just keep PNGs.

## What each test answers

| Script | Question | Decision it feeds |
|--------|----------|-------------------|
| 01 | How quiet is one barometer, really? | OSR choice; is MS5611 noise acceptable as BMP581 stand-in? |
| 02 | How fast does a lift/sink cue actually arrive? | Latency budget vs Skytraxx 0.5 s claim |
| 03 | Does averaging two barometers help? | ADR-002 (dual baro worth $2.6?) |
| 04 | Is IMU fusion worth populating an IMU? | ADR-011; estimator choice per ADR-006 |

## Verdict thresholds (initial, adjust with evidence)

- Noise floor < 10 cm altitude RMS = BMP581-class; MS5611 OSR4096 typically 5–15 cm.
- Rest climb-rate noise < 0.15 m/s RMS = no false cues at rest.
- Step detection: aim < 1 s from motion onset to reliable 0.3 m/s estimate.
