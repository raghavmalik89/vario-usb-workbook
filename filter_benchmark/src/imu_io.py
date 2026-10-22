"""Loader for t007 (baro + IMU) captures.

Sensor-independence contract: physical units come from the #C meta line of
the capture sidecar (a_lsb_per_g, g_lsb_per_dps), NOT from part-number
assumptions. A future IMU with different full scales only changes its
firmware #C line; this module is untouched.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import loader

G0 = 9.80665
DEG = np.pi / 180.0


def _kv(meta_config_str):
    """Parse the '#C,key=value,...' string stored in the sidecar."""
    out = {}
    for tok in str(meta_config_str or "").split(","):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def config_for(csv_path):
    sc = loader.sidecar_for(csv_path)
    if not sc or "device" not in sc:
        return {}
    return _kv(sc["device"].get("config", ""))


def imu_stream(csv_path):
    """Return dict(t_s, accel (N,3) m/s^2 body, gyro (N,3) rad/s body,
    counts (N,6) raw, cfg) for the I frames of a capture, or None if the
    capture has no IMU rows."""
    df = pd.read_csv(csv_path, index_col=False)
    imu = df[df["type"] == "I"].dropna(subset=["ax", "ay", "az"])
    if imu.empty:
        return None
    cfg = config_for(csv_path)
    if cfg.get("imu") == "off":
        return None
    a_lsb = float(cfg.get("a_lsb_per_g", 4096.0))
    g_lsb = float(cfg.get("g_lsb_per_dps", 65.5))
    t_us = imu["t_us"].to_numpy(dtype=float)
    t = (t_us - t_us[0]) * 1e-6
    counts = imu[["ax", "ay", "az", "gx", "gy", "gz"]].to_numpy(dtype=float)
    accel = counts[:, 0:3] / a_lsb * G0
    gyro = counts[:, 3:6] / g_lsb * DEG
    return dict(t_s=t, accel=accel, gyro=gyro, counts=counts, cfg=cfg)


def gyro_bias_rad_s(imu, window_s=3.0):
    """Median gyro rate over the first window_s — the rig is at rest when a
    capture starts (operator procedure), so this is a bias estimate, not a
    motion artifact."""
    m = imu["t_s"] <= window_s
    if m.sum() < 10:
        m = imu["t_s"] <= imu["t_s"][-1] * 0.1
    return np.median(imu["gyro"][m], axis=0)
