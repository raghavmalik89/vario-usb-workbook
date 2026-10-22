"""Script 04 — demonstration run: every standalone filter (Groups A-E +
baselines) at DEFAULT configuration on every session/stream of both splits.

Purpose (Phase 2, spec + user mandate): demonstrate that all filters run
correctly on real captures and produce comparable metrics. NO tuning, NO
winner selection here. Per-stream diagnostics (corrupt frames, seq gaps)
are carried into the results for auditability.

Outputs results/04_individual_default.csv
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import FILTERS, ROOT, run_set, write_csv  # noqa: E402


def main():
    names = {name: {} for name in FILTERS}
    rows = []
    for split in ("training", "validation"):
        rows.extend(run_set(names, split, "04_individual"))
    write_csv(rows, ROOT / "results" / "04_individual_default.csv")


if __name__ == "__main__":
    main()
