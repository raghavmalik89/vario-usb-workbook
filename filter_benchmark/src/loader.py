"""Shared loading helpers for the filter benchmark.

All barometric compensation goes through ../analysis/common.py — the PROM /
temperature-merge path is subtle and has a documented history of
hand-derivation errors (HANDOVER §8). Do not re-implement it here.
"""
import json
import sys
from pathlib import Path

import numpy as np

BENCH_ROOT = Path(__file__).resolve().parents[2]          # filter_benchmark/..
ANALYSIS_DIR = BENCH_ROOT / "analysis"
DATA_DIR = ANALYSIS_DIR / "data"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

from common import compensate_ms5611, find_run, get_prom, load_run  # noqa: E402,F401


def data_files():
    return sorted(DATA_DIR.glob("*.csv"))


def sidecar_for(csv_path):
    p = Path(csv_path).with_suffix(".json")
    return json.loads(p.read_text()) if p.exists() else None


# Session classification from the capture label — evidence-limited: this is
# metadata from the operator's naming, nothing more. The task spec forbids
# inventing session types; "other" means "not classifiable from the label".
SESSION_RULES = [
    ("preflight", ["preflight"]),
    ("static_bench", ["static", "bench"]),
    ("elevator", ["elevator"]),
    ("step_drop", ["drop"]),
    ("toss_catch", ["toss"]),
    ("controlled_move", ["controled", "controlled", "move"]),
    ("dual_static", ["t003"]),
]


def classify(label):
    low = label.lower()
    for kind, keys in SESSION_RULES:
        if any(k in low for k in keys):
            return kind
    if "t001" in low or "t002" in low:
        return "static_bench"
    return "other"


def rate_stats(t_s):
    """Median dt [s], effective rate [Hz], p95 |dt - median| jitter [s]."""
    if len(t_s) < 2:
        return dict(median_dt_s=np.nan, rate_hz=np.nan, p95_jitter_s=np.nan)
    d = np.diff(np.asarray(t_s, dtype=float))
    d = d[d > 0]                     # tolerate duplicate/out-of-order at edges
    if len(d) == 0:
        return dict(median_dt_s=np.nan, rate_hz=np.nan, p95_jitter_s=np.nan)
    med = float(np.median(d))
    return dict(median_dt_s=med,
                rate_hz=(1.0 / med) if med > 0 else np.nan,
                p95_jitter_s=float(np.percentile(np.abs(d - med), 95)))
