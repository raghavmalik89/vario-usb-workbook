# filter_benchmark — Empirical Variometer Filter Benchmark

Implements `docs/engineering_task_e_filter_benchmark.md` (Engineering Task E):
evidence-driven comparison of vertical-speed estimators on the real Vario USB
bench-rig recordings. **No winners before measurements.**

## Datasets

All recordings live in `../analysis/data/` (CSV + JSON sidecar, protocol v1 —
see `../docs/serial_protocol.md`). Compensation and loading reuse
`../analysis/common.py` (the PROM/temperature merge is subtle; do not
re-derive it — see HANDOVER §8).

Manifest: `config/dataset_manifest.json` (regenerate with
`scripts/01_inventory.py`).

## Phasing (per task spec §2: inventory and data quality FIRST)

- **Phase 1 (done first, mandated):** dataset inventory + data quality report.
  `scripts/01_inventory.py`, `scripts/02_validate_data.py` →
  `reports/dataset_inventory.md`, `reports/data_quality_report.md`.
- **Phase 2:** baselines (B00–B03) + individual filters (Groups A–F) behind a
  common causal replay engine.
- **Phase 3:** the three combination architectures, common audio policy,
  tuning/validation split, finalist report.

## Rules that are easy to break (from the task spec, §14)

- Causal only: no `filtfilt`, no centered windows, no future samples in any
  real-time comparison.
- Sensor `t_us` (physical sample time) is the only valid timestamp for
  derivatives; USB reception order is not evidence of sample order beyond the
  per-frame `t_us`.
- Never use one filtered estimate as ground truth for another. Our event
  references are derived from a 1-s-smoothed baro signal and are labeled as
  such — "descriptive comparison", not measured physical latency.
- Report what the data CANNOT establish. Missing channels (GPS, reference
  vario) are marked **Unavailable**, not silently ignored.

## Reproducing

```
python scripts/01_inventory.py
python scripts/02_validate_data.py
```

(scripts add `../analysis` to sys.path for the shared compensation code)
