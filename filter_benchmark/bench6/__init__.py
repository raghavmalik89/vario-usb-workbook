"""Bench 6 — ESP-IDF-era comprehensive filter benchmark (2026-10-24).

A fresh comparative study over the complete filter architecture trade space on
the clean ESP-IDF recordings, deliberately NOT a confirmation exercise of the
Phases 2-5 rankings. Built for reuse: when the BMP581 + LSM6DSV16X captures
arrive, register them in datasets.py and re-run run6.py / figures6.py.

Methodology highlights (full detail in reports/phase6_espidf_benchmark.md):
  * altitude reconstructed from RAW d1/d2 against the FIXED ISA reference
    101325 Pa (the DEF-001 correction). The moving-p0 and session-mean
    conventions remain available as explicit options for reproducibility of
    earlier phases only.
  * both barometers replayed as independent streams (per-sid evaluation);
  * physical MCU timestamps as the single time base (absolute-vs-relative
    mixing burned us twice before);
  * frozen configurations evaluated first (config6.json); any tuning is a
    separate, leakage-controlled pass (tune6.py, train/validation split);
  * estimator output and virtual-audio behaviour measured separately
    (audio.py state machine under the common lift_on=0.20/lift_off=0.05
    policy, matching the firmware);
  * elevator legs are a CONTROLLED-MOTION REFERENCE (derived, descriptive
    proxy) — no ground-truth subsecond response is claimed anywhere.

Modules:
  datasets.py   capture registry (roles, splits, quality verdicts)
  streams.py    corrected stream reconstruction + references + V/B frames
  candidates.py the full candidate set (frozen configs, provenance)
  metrics6.py   estimator + audio metrics
  run6.py       frozen-pass runner -> results/6x_*.csv
  tune6.py      separate tuning pass (train/validation, no leakage)
  figures6.py   figure generation -> figs/
  report6.py    report assembly -> reports/
"""
