"""Shared infrastructure for Phase 2 benchmark runs (scripts 03/04/05).

Everything is driven from config/experiments.json so a run is reproducible:
    python scripts/04_run_individual_filters.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import replay  # noqa: E402
import metrics  # noqa: E402
from filters import FILTERS  # noqa: E402
from metrics import event_metrics, stationary_metrics  # noqa: E402

CONFIG = json.loads((ROOT / "config" / "experiments.json").read_text())
DATA = (ROOT / CONFIG["data_dir"]).resolve()


def streams(split):
    """Yield (session, sid, kind, rate_hz, t, alt, diag) for a config split."""
    for sess in CONFIG[split]:
        csv = DATA / (sess["file"] + ".csv")
        for sid in sess["sids"]:
            t, alt, diag = replay.altitude_stream(csv, sid)
            yield dict(session=sess["file"], sid=sid, kind=sess["kind"],
                       rate=sess["rate_hz"], t=t, alt=alt, diag=diag)


def derive_events(t, alt):
    """Derived strong-motion reference intervals (config event_reference).
    Fixed documented method (metrics.reference_v): 1-s Gaussian-smoothed
    barometric derivative; intervals at config thresholds. DESCRIPTIVE PROXY
    - not ground truth; every onset/release number is a proxy measurement."""
    ref = CONFIG["event_reference"]
    v_ref, _ = metrics.reference_v(t, alt)
    # strong-motion CORES first (0.5 crossing is unambiguous even with
    # hand-held approach motion), then extend each core to the true entry:
    # last time |v_ref| was at the noise floor (0.05, below statics p99)
    cores = metrics.detect_events(t, v_ref, on=ref["core_on"],
                                  off=ref["core_off"], min_dur=0.15,
                                  gap=ref["min_gap_s"])
    floor = ref["floor"]
    out = []
    for (a, b) in cores:
        ia = np.searchsorted(t, a)
        ib = np.searchsorted(t, b)
        below = np.where(np.abs(v_ref[:ia]) <= floor)[0]
        ext_a = t[below[-1]] if len(below) else t[0]
        below_b = np.where(np.abs(v_ref[ib:]) <= floor)[0]
        ext_b = t[ib + below_b[0]] if len(below_b) else t[-1]
        if ext_b - ext_a >= ref["min_dur_s"]:
            out.append((float(ext_a), float(ext_b)))
    # merge overlaps (extension can bridge adjacent cores)
    out.sort()
    merged = []
    for e in out:
        if merged and e[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e[1]))
        else:
            merged.append(e)
    return merged, v_ref


def run_filter_on_stream(name, overrides, st):
    """Replay one filter on one stream; return metrics dict."""
    f = FILTERS[name](**overrides)
    t, v = replay.replay(f, t=st["t"], z=st["alt"])
    row = dict(filter=name, config=f._config_repr(), session=st["session"],
               sid=st["sid"], kind=st["kind"], rate_hz=st["rate"],
               n_samples=st["diag"].n_samples, n_corrupt=st["diag"].n_corrupt,
               n_seq_gaps=st["diag"].n_seq_gaps)
    if st["kind"] == "static":
        row.update(stationary_metrics(v, t))
    else:
        events, v_ref = derive_events(st["t"], st["alt"])
        row["n_events"] = len(events)
        row.update(event_metrics(t, v, v_ref, events))
        row["rms"] = float(np.sqrt(np.mean(v ** 2)))
        row["false_latches"] = stationary_metrics(v, t)["false_latches"]
    return row


def run_set(names_overrides, split, label):
    """Run {name: overrides} over a split; return list of metric rows."""
    rows = []
    for st in streams(split):
        for name, ov in names_overrides.items():
            rows.append(run_filter_on_stream(name, ov, st))
        print(f"  {label}: {st['session']} sid{st['sid']} done", flush=True)
    return rows


def write_csv(rows, path):
    import csv
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})
    print(f"wrote {path} ({len(rows)} rows)")
