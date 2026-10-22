"""Shared helpers for Vario USB bench analysis.

Loads capture runs (CSV + JSON sidecar from tools/capture.py) and provides
MS5611 compensation, altitude conversion, and plotting utilities.

All analysis scripts import this module:

    from common import load_run, compensate, altitude
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"
OUT_DIR = Path(__file__).resolve().parent / "output"
OUT_DIR.mkdir(exist_ok=True)


def find_run(pattern: str):
    """Find a capture CSV by glob pattern, e.g. find_run('*t001*')."""
    hits = sorted(DATA_DIR.glob(pattern))
    hits = [h for h in hits if h.suffix == ".csv"]
    if not hits:
        raise SystemExit(f"No CSV matching '{pattern}' in {DATA_DIR}")
    if len(hits) > 1:
        print(f"Multiple matches, using newest: {hits[-1].name}")
    return hits[-1]


def load_run(csv_path):
    """Return (df, meta). df has parsed columns; t_us converted to seconds."""
    df = pd.read_csv(csv_path)
    meta = {}
    sidecar = csv_path.with_suffix(".json")
    if sidecar.exists():
        meta = json.loads(sidecar.read_text())
    df["t_s"] = (df["t_us"] - df["t_us"].iloc[0]) / 1e6
    return df, meta


def get_prom(meta: dict, sid: int):
    """Pull PROM words [c1..c6] for barometer sid from capture sidecar."""
    raw = meta.get("device", {}).get(f"prom_{sid}")
    if raw is None:
        raise KeyError(f"No PROM calibration for sid={sid} in sidecar. "
                       f"Firmware must emit #K lines (docs/serial_protocol.md).")
    return [float(v) for v in str(raw).split(",")]


def compensate_ms5611(d1, d2, prom):
    """Raw ADC -> (pressure Pa, temperature degC). Vectorized, numpy in/out.

    Standard MS5611 second-order compensation (TE Connectivity datasheet).
    """
    c1, c2, c3, c4, c5, c6 = prom
    d1 = np.asarray(d1, dtype=np.float64)
    d2 = np.asarray(d2, dtype=np.float64)
    dt = d2 - c5 * 256.0
    temp = 2000.0 + dt * c6 / 2**23
    off = c2 * 2**16 + (c4 * dt) / 2**7
    sens = c1 * 2**15 + (c3 * dt) / 2**8
    # second-order correction at low temperature
    t2 = np.zeros_like(dt)
    off2 = np.zeros_like(dt)
    sens2 = np.zeros_like(dt)
    cold = temp < 2000.0
    tc = temp[cold]
    dtc = dt[cold]
    t2[cold] = dtc * dtc / 2**31
    off2[cold] = 5.0 * (tc - 2000.0) ** 2 / 2.0
    sens2[cold] = off2[cold] / 2.0
    very_cold = temp < -1500.0
    tv = temp[very_cold]
    off2[very_cold] += 7.0 * (tv + 1500.0) ** 2
    sens2[very_cold] += 11.0 * (tv + 1500.0) ** 2 / 2.0
    temp = temp - t2
    off = off - off2
    sens = sens - sens2
    p = (d1 * sens / 2**21 - off) / 2**15          # 0.01 mbar
    return p * 10.0 / 1000.0 * 100.0, temp / 100.0  # Pa, degC


def altitude_m(p_pa, p0_pa=101325.0):
    """Barometric altitude (ISA troposphere approximation)."""
    return 44330.0 * (1.0 - (np.asarray(p_pa) / p0_pa) ** 0.1903)


def pressure_series(df, meta, sid=0):
    """Extract compensated (t_s, p_pa, temp_c) for one barometer."""
    pr = df[(df.type == "P") & (df.sid == sid)][["t_s", "d1"]].dropna()
    tr = df[(df.type == "T") & (df.sid == sid)][["t_s", "d2"]].dropna()
    if pr.empty:
        raise SystemExit(f"No P frames for sid={sid} in this run.")
    prom = get_prom(meta, sid)
    # merge each pressure sample with the most recent temperature sample
    tr = tr.sort_values("t_s")
    idx = np.searchsorted(tr.t_s.values, pr.t_s.values, side="right") - 1
    idx = np.clip(idx, 0, len(tr) - 1)
    d2 = tr.d2.values[idx]
    p, temp = compensate_ms5611(pr.d1.values, d2, prom)
    return pr.t_s.values, p, temp


def savefig(fig, name):
    out = OUT_DIR / name
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")
    return out


def run_name(csv_path):
    return re.sub(r"^\d{8}_\d{6}_", "", Path(csv_path).stem)
