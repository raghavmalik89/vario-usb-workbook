"""Phase 5 — real-IMU fusion validation.

Replays the Phase-4 BaroImuFusion on t007 captures (dual MS5611 + MPU6050
@ 200 Hz) with attitude from the Madgwick 6-DOF estimator, and compares
against the same filter in baro-only mode on identical baro input. This is
the real-data counterpart of script 14 (which was synthetic-only).

Runs on whatever *t007* captures exist in analysis/data; with none present
it writes an empty status table and exits 0 (captures are the operator's
step).

Repro:  python -u scripts/17_real_imu_fusion.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import attitude
import imu_io
import loader
import p4_eval as P4E
import replay
from fusion import BaroImuFusion

RES = ROOT / "results"
G0 = 9.80665


def rest_mask_barotimes(t_baro, t_imu, accel_norm, lo=0.9 * G0, hi=1.1 * G0):
    n_im = np.interp(t_baro, t_imu, accel_norm)
    return (n_im >= lo) & (n_im <= hi)


def replay_fused(t_baro, alt, t_imu, accel, quats):
    """Interleaved asynchronous replay. Returns (v at baro times, filter)."""
    f = BaroImuFusion()
    v = np.empty(len(t_baro))
    ib = ii = 0
    while ib < len(t_baro) or ii < len(t_imu):
        if ii < len(t_imu) and (ib >= len(t_baro) or t_imu[ii] <= t_baro[ib]):
            f.update_imu(accel[ii], t_imu[ii], quat=quats[ii])
            ii += 1
        else:
            v[ib] = f.update_baro(alt[ib], t_baro[ib])
            ib += 1
    return v, f


def replay_baro_only(t_baro, alt):
    f = BaroImuFusion()
    v = np.empty(len(t_baro))
    for i in range(len(t_baro)):
        v[i] = f.update_baro(alt[i], t_baro[i])
    return v, f


def analyse_session(csv_path):
    imu = imu_io.imu_stream(csv_path)
    if imu is None:
        return None
    t_im, a_body, gyro = imu["t_s"], imu["accel"], imu["gyro"]

    # gyro bias from the capture-start rest window (operator procedure)
    gb = imu_io.gyro_bias_rad_s(imu)
    gyro_c = gyro - gb

    quats = attitude.estimate_attitude(t_im, a_body, gyro_c)

    a_norm = np.linalg.norm(a_body, axis=1)
    rest0 = t_im <= 3.0

    # sanity: Madgwick gravity residual at rest (should be ~0 if attitude ok)
    from fusion import gravity_compensate
    az_rest = np.array([gravity_compensate(a_body[i], quats[i])
                        for i in np.where(rest0)[0]])

    rows = []
    trace0 = None
    for sid in (0, 1):
        try:
            t_b, alt, _ = replay.altitude_stream(csv_path, sid)
        except Exception:
            continue
        if len(t_b) < 50:
            continue
        t_b = np.asarray(t_b, dtype=float)
        alt = np.asarray(alt, dtype=float)

        v_f, f_f = replay_fused(t_b, alt, t_im, a_body, quats)
        v_b, _ = replay_baro_only(t_b, alt)
        if sid == 0:
            trace0 = dict(t_im=t_im, a_norm=a_norm, t_b=t_b, v_b=v_b, v_f=v_f)

        rm = rest_mask_barotimes(t_b, t_im, a_norm)

        def vrms(x, m):
            return float(np.sqrt(np.mean(x[m] ** 2))) if m.any() else np.nan

        rows.append(dict(
            session=Path(csv_path).stem, sid=sid,
            n_imu=len(t_im), imu_rate_hz=round(1.0 / np.median(np.diff(t_im)), 1),
            rest_a_mean=round(float(np.mean(a_norm[rest0])), 3),
            rest_a_std=round(float(np.std(a_norm[rest0])), 3),
            gyro_bias_mdps=round(float(np.linalg.norm(gb) / np.pi * 180e3), 1),
            madgwick_rest_az_err=round(float(np.mean(np.abs(az_rest))), 3),
            v_rms_baro_only=round(vrms(v_b, np.ones(len(t_b), bool)), 4),
            v_rms_fusion=round(vrms(v_f, np.ones(len(t_b), bool)), 4),
            v_rms_rest_baro_only=round(vrms(v_b, rm), 4),
            v_rms_rest_fusion=round(vrms(v_f, rm), 4),
            max_abs_v_baro_only=round(float(np.max(np.abs(v_b))), 3),
            max_abs_v_fusion=round(float(np.max(np.abs(v_f))), 3),
            accel_bias_norm_final=round(float(np.linalg.norm(f_f.accel_bias)), 4),
            n_gated=int(f_f.n_gated), fault=bool(f_f.fault),
            n_baro=len(t_b),
        ))
    if not rows:
        return None
    return rows, trace0


def main():
    RES.mkdir(exist_ok=True)
    files = sorted(loader.data_files())
    t007 = [f for f in files if "t007" in f.stem]
    all_rows, fig_data = [], {}

    for f in t007:
        out = analyse_session(f)
        if out is None:
            print(f"skip {f.name}: no IMU stream")
            continue
        rows, trace = out
        all_rows.extend(rows)
        fig_data[f.stem] = trace
        for r in rows:
            print("  ", {k: r[k] for k in
                         ("session", "sid", "v_rms_rest_baro_only",
                          "v_rms_rest_fusion", "max_abs_v_fusion")})

    df = pd.DataFrame(all_rows)
    out_csv = RES / "17_real_imu_fusion.csv"
    df.to_csv(out_csv, index=False)
    print(f"\n{len(df)} rows -> {out_csv}")

    # figure: one static + one motion session, baro-only vs fused v
    def pick(pred):
        for stem, tr in fig_data.items():
            if pred(stem) and tr is not None:
                return stem, tr
        return None, None

    s_stem, s_tr = pick(lambda s: "static" in s.lower() or "bench" in s.lower())
    m_stem, m_tr = pick(lambda s: any(k in s.lower()
                                      for k in ("drop", "toss", "move", "elevator")))
    if s_stem is None:
        s_stem, s_tr = m_stem, m_tr
    if m_stem is None:
        m_stem, m_tr = s_stem, s_tr
    if s_tr is not None:
        fig, axes = plt.subplots(2, 1, figsize=(12, 7))
        for ax, stem, tr in ((axes[0], s_stem, s_tr), (axes[1], m_stem, m_tr)):
            ax.plot(tr["t_b"], tr["v_b"], lw=0.8, color="#888888",
                    label="baro-only")
            ax.plot(tr["t_b"], tr["v_f"], lw=0.8, color="#C44E52",
                    label="baro+IMU fusion")
            ax.axhline(0, color="k", lw=0.4, alpha=0.4)
            ax.set_ylabel("v (m/s)")
            ax.set_title(f"{stem} sid-replay  [M]")
            ax.grid(alpha=0.3)
            ax.legend(fontsize=8)
        axes[1].set_xlabel("t (s)")
        fig.suptitle("Phase 5: real-IMU fusion vs baro-only on t007 captures")
        fig.tight_layout()
        fig.savefig(RES / "fig_p5_real_fusion.png", dpi=140)
        plt.close(fig)
        print("figure: fig_p5_real_fusion.png")

    if df.empty:
        print("no t007 captures yet — flash t007 firmware, capture, re-run.")


if __name__ == "__main__":
    main()
