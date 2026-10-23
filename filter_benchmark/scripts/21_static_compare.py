"""Phase 5b — cross-phase static comparison incl. the t008 quiet-house capture.

Compares every stationary bench capture across firmware generations:
  t005_benchstatic  OSR4096 @ 45 Hz P, no IMU   (firmware 0.5.3)
  t006_benchstatic  OSR2048 @ 90 Hz P, no IMU   (firmware 0.6.0)
  t007_benchstatic  OSR2048 @ 90 Hz P + IMU, OFFICE draft   (0.7.0)
  t008_quiet_static OSR2048 @ 90 Hz P + IMU, QUIET HOUSE    (0.7.0)

Per capture x sid: sample rates, 1-s-detrended altitude noise, lag-1
pressure-diff noise, drift range, lag-k structure function, overlapping
Allan deviation, baro-only KF (q=10, per-capture r [M]) rest v-RMS.
IMU metrics (g_cal scale error, gyro bias, tilt, Madgwick az residual,
rest accel noise) where an IMU stream exists (t007/t008).

Figures (results/fig_static_*.png):
  fig_static_drift.png      altitude relative to session mean vs t
  fig_static_structure.png  lag-k altitude-diff std (log-log)
  fig_static_allan.png      overlapping Allan deviation vs tau
  fig_static_kf.png         KF rest-v comparison bars

Repro:  python -u scripts/21_static_compare.py
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

import importlib.util
spec = importlib.util.spec_from_file_location(
    "s17", ROOT / "scripts" / "17_real_imu_fusion.py")
s17 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s17)

import imu_io  # noqa: E402
import attitude  # noqa: E402
from fusion import gravity_compensate, BaroImuFusion  # noqa: E402

DATA = ROOT.parent / "analysis" / "data"
RES = ROOT / "results"
G0 = 9.80665

# capture stem, display label, firmware tag, OSR, nominal P rate
CAPTURES = [
    ("20261022_162134_t005_benchstatic", "t005 office, OSR4096@45Hz", "0.5.3", 4096, 45.0),
    ("20261022_163251_t006_benchstatic", "t006 office, OSR2048@90Hz", "0.6.0", 2048, 90.0),
    ("20261023_110700_t007_benchstatic", "t007 office, OSR2048@90Hz+IMU", "0.7.0", 2048, 90.0),
    ("20261023_122655_t008_quiet_static", "t008 QUIET, OSR2048@90Hz+IMU", "0.7.0", 2048, 90.0),
]
COLORS = {"t005": "#4C72B0", "t006": "#55A868",
          "t007": "#C44E52", "t008": "#8172B2"}
Q_KF = 10.0


def adev(x, dt0, taus):
    """Overlapping Allan deviation of series x sampled at dt0."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = {}
    for tau in taus:
        m = max(1, int(round(tau / dt0)))
        if 2 * m >= n:
            out[tau] = np.nan
            continue
        d = x[2 * m:] - 2 * x[m:n - m] + x[:n - 2 * m]
        out[tau] = float(np.sqrt(0.5 * np.mean(d * d)))
    return out


def kf_rest_v(t_b, alt, q, r):
    f = BaroImuFusion(q=q, r=r)
    v = np.empty(len(t_b))
    for i in range(len(t_b)):
        v[i] = f.update_baro(float(alt[i]), float(t_b[i]))
    vs = pd.Series(v)
    v_hp = (vs - vs.rolling(window=int(5 * 90), center=True,
                            min_periods=1).mean()).values
    return float(np.sqrt(np.mean(v ** 2))), float(np.sqrt(np.mean(v_hp ** 2))), f


def main():
    RES.mkdir(exist_ok=True)
    rows, curves_drift, curves_struct, curves_allan = [], {}, {}, {}
    imu_rows = []

    for stem, label, fw, osr, p_nom in CAPTURES:
        csv = DATA / f"{stem}.csv"
        key = stem.split("_")[2][:4]          # t005/t006/t007/t008
        for sid in (0, 1):
            try:
                t_b, alt, alt_raw, rep = s17.altitude_stream_d2filt(csv, sid)
            except SystemExit:
                continue
            t_b = np.asarray(t_b, dtype=float)
            alt = np.asarray(alt, dtype=float)
            dt0 = float(np.median(np.diff(t_b)))
            # true average rate over the session span (the median interval
            # overestimates: every 10th tick converts T, making periodic
            # 20 ms P gaps at 90 nominal Hz)
            rate = len(t_b) / (t_b[-1] - t_b[0] + dt0)
            r_cap = s17.estimate_r_baro(alt, t_b)
            det_m = alt - np.nanmean(alt)
            # lag-k structure function (in metres)
            ks = [1, 2, 5, 10, 20, 50, 100, 200, 500]
            sf = {k: float(np.std(np.diff(alt, k))) for k in ks if k < len(alt)}
            ad = adev(alt, dt0, [0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0])
            v_rms, v_hp, flt = kf_rest_v(t_b - t_b[0], alt, Q_KF, r_cap)
            rows.append(dict(
                capture=key, label=label, firmware=fw, osr=osr, sid=sid,
                p_rate_hz=round(rate, 2), n_p=len(t_b),
                r_est_m2=round(r_cap, 5),
                alt_noise_detrend_m=round(float(rep["noise_filt_m"]), 4),
                alt_drift_range_m=round(float(np.nanmax(det_m) - np.nanmin(det_m)), 3),
                alt_drift_std_m=round(float(np.nanstd(det_m)), 3),
                adev_tau1s_m=round(ad[1.0], 4) if not np.isnan(ad.get(1.0, np.nan)) else np.nan,
                adev_tau10s_m=round(ad[10.0], 4) if not np.isnan(ad.get(10.0, np.nan)) else np.nan,
                kf_v_rms=round(v_rms, 4), kf_v_hp=round(v_hp, 4),
                kf_reinit=flt.n_reinit,
            ))
            curves_drift[(key, sid)] = (t_b - t_b[0], det_m)
            curves_struct[(key, sid)] = (np.array(list(sf.keys())) / rate,
                                         np.array(list(sf.values())))
            curves_allan[(key, sid)] = (np.array(list(ad.keys())),
                                        np.array(list(ad.values())))

        # IMU metrics where present
        imu = imu_io.imu_stream(csv)
        if imu is not None:
            t_im, a, g = imu["t_s"], imu["accel"], imu["gyro"]
            an = np.linalg.norm(a, axis=1)
            m = (an >= 8.5) & (an <= 11.5)
            g_cal = float(np.median(an[m])) if m.sum() > 100 else float(np.median(an))
            a_cal = a * (G0 / g_cal)
            gb = imu_io.gyro_bias_rad_s(imu)
            q0 = attitude.quat_from_accel_tilt(a_cal[0])
            quats = attitude.estimate_attitude(t_im, a_cal, g - gb, q0=q0)
            az = np.array([gravity_compensate(a_cal[i], quats[i])
                           for i in range(len(t_im))])
            rest = an >= 8.5
            ax_noise = np.std(a_cal[rest] - np.mean(a_cal[rest], axis=0), axis=0)
            imu_rows.append(dict(
                capture=key, label=label,
                imu_rate_hz=round(1.0 / np.median(np.diff(t_im)), 1),
                g_cal=round(g_cal, 4),
                scale_err_pct=round((g_cal / G0 - 1) * 100, 2),
                gyro_bias_mdps=round(float(np.linalg.norm(gb) * 180e3 / np.pi), 1),
                tilt_deg=round(float(np.degrees(np.arccos(np.clip(
                    np.mean(a_cal[rest], axis=0)[0] /
                    np.mean(an[rest]), -1, 1)))), 2),
                madgwick_az_median=round(float(np.median(np.abs(az[rest]))), 4),
                accel_noise_x_mps2=round(float(ax_noise[0]), 4),
                accel_noise_y_mps2=round(float(ax_noise[1]), 4),
                accel_noise_z_mps2=round(float(ax_noise[2]), 4),
            ))

    df = pd.DataFrame(rows)
    df.to_csv(RES / "21_static_compare.csv", index=False)
    pd.DataFrame(imu_rows).to_csv(RES / "21_static_imu.csv", index=False)
    print(df.to_string(index=False))
    if imu_rows:
        print()
        print(pd.DataFrame(imu_rows).to_string(index=False))

    # ---- figures -----------------------------------------------------------
    def color(key):
        return COLORS[key]

    # sid-averaged Allan/structure curves (both sids drawn faint underneath)
    def mean_curve(curves, key):
        arrs = [v for (k, _), v in curves.items() if k == key]
        taus = arrs[0][0]
        vals = np.nanmean(np.vstack([a[1] for a in arrs]), axis=0)
        spread = np.nanstd(np.vstack([a[1] for a in arrs]), axis=0)
        return taus, vals, spread

    fig, ax = plt.subplots(figsize=(9, 4.6))
    for (key, sid), (t, d) in curves_drift.items():
        if sid == 0:
            ax.plot(t, d, lw=0.9, color=color(key), alpha=0.9,
                    label=dict((c[0].split("_")[2][:4], c[1]) for c in CAPTURES)[key])
    ax.set_xlabel("t (s)")
    ax.set_ylabel("altitude - session mean (m)")
    ax.set_title("Static drift: office (t005/t006/t007) vs quiet house (t008), sid0")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(RES / "fig_static_drift.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5.2))
    for key in COLORS:
        for (k, sid), (tau, s) in curves_struct.items():
            if k == key:
                ax.loglog(tau, s, ".", color=color(key), alpha=0.35, ms=3)
        tau, s, sd = mean_curve(curves_struct, key)
        ax.loglog(tau, s, "-", lw=1.6, color=color(key), label=key.upper())
    ax.set_xlabel("lag (s)")
    ax.set_ylabel("std of altitude difference (m)")
    ax.set_title("Structure function (lag-k diff std), sid mean")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(RES / "fig_static_structure.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5.2))
    for key in COLORS:
        for (k, sid), (tau, a) in curves_allan.items():
            if k == key:
                ax.loglog(tau, a, ".", color=color(key), alpha=0.35, ms=3)
        tau, a, sd = mean_curve(curves_allan, key)
        ax.loglog(tau, a, "-", lw=1.6, color=color(key), label=key.upper())
    ax.set_xlabel(r"averaging time $\tau$ (s)")
    ax.set_ylabel(r"Allan deviation $\sigma(\tau)$ (m)")
    ax.set_title("Overlapping Allan deviation of compensated altitude, sid mean")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(RES / "fig_static_allan.png", dpi=180)
    plt.close(fig)

    piv = df[df.sid == 0].set_index("capture")
    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(len(piv))
    ax.bar(x - 0.2, piv.kf_v_rms, 0.38, label="KF rest v-RMS (all)", color="#4C72B0")
    ax.bar(x + 0.2, piv.kf_v_hp, 0.38, label="KF rest v-RMS (drift-removed)",
           color="#DD8452")
    ax.set_xticks(x)
    ax.set_xticklabels([l.split(",")[0] for l in piv.label], fontsize=8)
    ax.set_ylabel("v RMS (m/s)")
    ax.set_title(f"Baro-only KF at rest (q={Q_KF}, per-capture r), sid0")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(RES / "fig_static_kf.png", dpi=180)
    plt.close(fig)
    print("\nfigures: fig_static_drift/structure/allan/kf.png")


if __name__ == "__main__":
    main()
