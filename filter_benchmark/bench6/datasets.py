"""Bench 6 capture registry.

Every capture used by the study is declared here ONCE with its role, split and
quality verdict, so the dataset decisions are explicit and auditable. To run
the same benchmark on the BMP581/LSM6DSV16X captures later: add their stems
here (new files dict entries + DATASETS rows) and re-run the pipeline —
nothing else in bench6 hard-codes the sensor set.

Quality verdicts come from measured inspection (sequence gaps, frame bands,
stream-rate integrity), not from operator labels.
"""
from __future__ import annotations

from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]      # filter_benchmark/
WORKBOOK_ROOT = BENCH_ROOT.parent
DATA_DIR = WORKBOOK_ROOT / "analysis" / "data"

EST_NAMES = {0: "D01", 1: "C03", 2: "S4", 3: "S5", 4: "FUS"}   # eid % 5
N_EST = 5

# file stem -> metadata
FILES = {
    "20261023_221124_idf_elevator_2x": dict(
        label="elevator run 1", classes=("elevator",), split="train",
        quality="CLEAN: 0 seq gaps, 0 corrupt frames, abad=0 (B-lines)",
        firmware="pre-p0fix (moving reference in MCU V frames — use only for "
                 "the moving-p0 harness cross-check)"),
    "20261023_221420_idf_elevator_2x": dict(
        label="elevator run 2", classes=("elevator",), split="validation",
        quality="CLEAN: 3 single-frame (20 ms) seq gaps, 0 corrupt frames",
        firmware="pre-p0fix (V frames moving-reference)"),
    "20261023_215709_idf_handtest3": dict(
        label="handtest3", classes=("handtest",), split="train",
        quality="GOOD: 7 single-frame (20 ms) seq gaps, 0 corrupt frames",
        firmware="pre-p0fix (V frames moving-reference)"),
    "20261023_234521_idf_p0fix_static": dict(
        label="p0fix static", classes=("static",), split="validation",
        quality="CLEAN: 0 seq gaps, 0 corrupt frames, 75.3 s",
        firmware="post-p0fix — the fixed-reference MCU equivalence set"),
    "20261023_234944_idf_bbuf_check": dict(
        label="bbuf check static", classes=("static",), split="validation",
        quality="CLEAN: 0 seq gaps, 20.2 s (diagnostic capture, doubles as a "
                "short independent static)",
        firmware="post-p0fix — the fixed-reference MCU equivalence set"),
    # ---- excluded from scoring; retained as documented fault-test data ----
    "20261023_221109_idf_elevator_2x": dict(
        label="elevator aborted", classes=("elevator",), split="excluded",
        quality="ABORTED: USB-stall dropouts (DEF-008), 18 s only",
        firmware="pre-p0fix",
        fault_role="abort/dropout fault-test dataset"),
    "20261023_215027_idf_foam_static": dict(
        label="foam static", classes=("static",), split="excluded",
        quality="CORRUPTED: USB-stall fragmentation (DEF-008) — 3703 P-frame "
                "seq gaps over a 366.6 s wall span containing only ~74 s of "
                "baro data; 6192 duplicate IMU timestamps. Unusable for "
                "scoring.",
        firmware="pre-p0fix",
        fault_role="USB-stall fragmentation fault-test dataset"),
}

# scoring datasets (everything not excluded), in a stable order
SCORING = [k for k, v in FILES.items() if v["split"] != "excluded"]
TRAIN = [k for k in SCORING if FILES[k]["split"] == "train"]
VALIDATION = [k for k in SCORING if FILES[k]["split"] == "validation"]


def csv_for(stem: str) -> Path:
    return DATA_DIR / (stem + ".csv")


def sidecar_for(stem: str) -> Path:
    return DATA_DIR / (stem + ".json")
