"""Diagnostic: Madgwick az-residual vs TIME on real static IMU.

Script 17's madgwick_rest_az_err averages only t<=3 s — the initial
convergence transient from q0=identity to the rig's ~6.3 deg tilt. Measure
|a_z residual| in consecutive 5 s windows over the whole session, plus a
long-run tilt estimate, to distinguish 'slow but converges' from 'never
converges / convention bug'.

Repro:  python -u scripts/19_madgwick_debug.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import attitude
import imu_io
from fusion import gravity_compensate

DATA = ROOT.parent / "analysis" / "data"
G0 = 9.80665


def run(csv_path):
    imu = imu_io.imu_stream(csv_path)
    t, a, g = imu["t_s"], imu["accel"], imu["gyro"]
    a_norm = np.linalg.norm(a, axis=1)
    mask = (a_norm >= 8.5) & (a_norm <= 11.5)
    g_cal = float(np.median(a_norm[mask])) if mask.sum() > 100 else float(np.median(a_norm))
    a_cal = a * (G0 / g_cal)
    gb = imu_io.gyro_bias_rad_s(imu)
    gyro_c = g - gb
    m0 = t <= 3.0
    tilt_deg = np.degrees(np.arccos(np.clip(
        np.mean(a_cal[m0], axis=0)[0] / np.mean(a_norm[m0]), -1, 1)))
    print(f"{Path(csv_path).name}: g_cal={g_cal:.3f}  "
          f"gyro bias mdps={np.linalg.norm(gb) * 180e3 / np.pi:.1f}")
    print(f"  rest accel mean (first 3 s, cal): "
          f"{np.mean(a_cal[m0], axis=0).round(3)}  tilt={tilt_deg:.2f} deg")

    for beta in (0.3, 1.0):
        quats = attitude.estimate_attitude(t, a_cal, gyro_c, beta=beta)
        az = np.array([gravity_compensate(a_cal[i], quats[i]) for i in range(len(t))])
        print(f"  beta={beta}: |az| mean in 5 s windows:")
        for w0 in range(0, int(t[-1]) - 4, 5):
            m = (t >= w0) & (t < w0 + 5)
            if m.sum() > 50:
                print(f"    t={w0:3d}-{w0 + 5:<3d}s  mean|az|={np.mean(np.abs(az[m])):6.3f}  "
                      f"std={np.std(az[m]):6.3f} m/s^2")
    return t, a_cal, gyro_c


if __name__ == "__main__":
    csv = DATA / "20261023_110700_t007_benchstatic.csv"
    t, a_cal, gyro_c = run(csv)

    # synthetic control: same tilt, same noise level, zero gyro bias
    rng = np.random.default_rng(0)
    tilt = np.radians(6.3)
    Rsyn = np.array([[1, 0, 0], [0, np.cos(tilt), -np.sin(tilt)],
                     [0, np.sin(tilt), np.cos(tilt)]])
    n = len(t)
    a_syn = (Rsyn.T @ (np.array([0, 0, -G0])[:, None] * np.ones((1, n)))).T
    a_syn += rng.normal(0, 0.05, a_syn.shape)
    g_syn = rng.normal(0, 0.001, (n, 3))
    quats = attitude.estimate_attitude(t, a_syn, g_syn, beta=0.3)
    az = np.array([gravity_compensate(a_syn[i], quats[i]) for i in range(n)])
    print("\nsynthetic tilted-start control: |az| in 5 s windows")
    for w0 in range(0, int(t[-1]) - 4, 5):
        m = (t >= w0) & (t < w0 + 5)
        if m.sum() > 50:
            print(f"    t={w0:3d}-{w0 + 5:<3d}s  mean|az|={np.mean(np.abs(az[m])):6.3f}")
