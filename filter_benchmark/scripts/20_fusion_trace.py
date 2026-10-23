"""Diagnostic: instrument the fused replay on static sid0 — find the
divergence mechanism. Dumps per-5-s statistics of a_down, accel_bias,
innovation, P00, v, and gating.

Repro:  python -u scripts/20_fusion_trace.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import attitude
import imu_io
from fusion import BaroImuFusion

DATA = ROOT.parent / "analysis" / "data"
G0 = 9.80665
Q = 10.0
R = 0.04207


def main():
    csv = DATA / "20261023_110700_t007_benchstatic.csv"
    imu = imu_io.imu_stream(csv)
    t_im, a_body, gyro = imu["t_s"], imu["accel"], imu["gyro"]
    an = np.linalg.norm(a_body, axis=1)
    m = (an >= 8.5) & (an <= 11.5)
    g_cal = float(np.median(an[m]))
    a_cal = a_body * (G0 / g_cal)
    gb = imu_io.gyro_bias_rad_s(imu)
    q0 = attitude.quat_from_accel_tilt(a_cal[0])
    quats = attitude.estimate_attitude(t_im, a_cal, gyro - gb, q0=q0)

    # altitude (reuse script 17's d2-filtered path)
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "s17", ROOT / "scripts" / "17_real_imu_fusion.py")
    s17 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s17)
    t_b, alt, _, _ = s17.altitude_stream_d2filt(csv, 0)
    t_b = t_b - t_b[0]

    class Trace(BaroImuFusion):
        def update_baro(self, z, t):
            self._last_innov = np.nan
            if self._x is not None and self._P is not None and self._t_baro is not None:
                dt = t - self._t_baro
                if dt > 0:
                    x0 = self._x.copy()
                    P0 = self._P.copy()
                    self._propagate(t)
                    from filters.kalman import cv_model
                    Fm, H, Qm, r = cv_model(dt, self.q, self.r)
                    Pp = Fm @ P0 @ Fm.T + Qm
                    y = z - (H @ self._x)[0]
                    self._last_innov = y
                    self._last_sig = float(np.sqrt(Pp[0, 0] + r))
            return super().update_baro(z, t)

    f = Trace(q=Q, r=R)
    n_b, n_i = len(t_b), len(t_im)
    ib = ii = 0
    rows = []
    while ib < n_b or ii < n_i:
        if ii < n_i and (ib >= n_b or t_im[ii] <= t_b[ib]):
            f.update_imu(a_cal[ii], t_im[ii], quat=quats[ii])
            ii += 1
        else:
            v = f.update_baro(alt[ib], t_b[ib])
            rows.append(dict(t=t_b[ib], v=v,
                             a_down=f._a_down,
                             bias=np.linalg.norm(f.accel_bias),
                             innov=getattr(f, "_last_innov", np.nan),
                             sig=getattr(f, "_last_sig", np.nan),
                             P00=None if f._P is None else f._P[0, 0],
                             P11=None if f._P is None else f._P[1, 1],
                             gated=f.n_gated))
            ib += 1
    tr = pd.DataFrame(rows)
    tr["gate_mult"] = np.abs(tr.innov) / tr.sig
    print(f"g_cal={g_cal:.3f}  total gated={tr.gated.iloc[-1]} / {len(tr)}")
    for w0 in range(0, int(tr.t.max()) - 4, 5):
        w = tr[(tr.t >= w0) & (tr.t < w0 + 5)]
        if len(w) < 50:
            continue
        print(f"t={w0:3d}-{w0+5:<3d}s v_rms={np.sqrt((w.v**2).mean()):7.3f} "
              f"a_down_mean={w.a_down.mean():7.4f} a_down_std={w.a_down.std():6.3f} "
              f"bias={w.bias.max():6.3f} innov_med={w.innov.median():7.3f} "
              f"innov_p95={w.innov.abs().quantile(.95):6.2f} "
              f"gate_mult_p50={w.gate_mult.median():6.2f} "
              f"P00_med={w.P00.median():7.4f} P11_med={w.P11.median():7.5f}")


if __name__ == "__main__":
    main()
