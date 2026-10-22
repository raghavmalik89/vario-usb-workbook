"""Script 03 — run spec-mandated baselines B00-B02 on all sessions.

B03 (reference vario) is UNAVAILABLE by construction: no recording
contains a reference-vario output stream. Emitted as an explicit N/A row.

Outputs results/03_baselines.csv over BOTH splits (demonstration only —
no winner selection in Phase 2).
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import CONFIG, ROOT, run_set, write_csv  # noqa: E402


def main():
    names = {"B00_diff": {}, "B01_regression": {}, "B02_project_kalman": {}}
    rows = []
    for split in ("training", "validation"):
        rows.extend(run_set(names, split, "03_baselines"))
    # explicit unavailable row for B03 (spec §3)
    rows.append(dict(filter="B03_reference_vario", config="N/A",
                     session="(all)", sid="", kind="", rate_hz="",
                     note=CONFIG.get("b03_note",
                                     "no recording contains a reference "
                                     "vario output stream")))
    out = ROOT / "results" / "03_baselines.csv"
    write_csv(rows, out)


if __name__ == "__main__":
    main()
