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


def estimate_r_baro(alt, t_b, window_s=1.0):
    """Measurement-noise variance of the compensated altitude stream [M]:
    std of residuals from per-window linear detrending over quiet data."""
    resid = []
    t0 = t_b[0]
    while t0 < t_b[-1]:
        m = (t_b >= t0) & (t_b < t0 + window_s)
        if m.sum() > 10:
            c = np.polyfit(t_b[m], alt[m], 1)
            resid.extend((alt[m] - np.polyval(c, t_b[m])).tolist())
        t0 += window_s
    r = float(np.var(resid)) if resid else np.nan
    return r


def altitude_stream_d2filt(csv_path, sid, med_window_s=5.0):
    """Altitude stream with the clone's noisy temperature channel tamed.

    Root cause established on benchstatic [M]: these GY-63 clones emit d2
    (temperature ADC) step-to-step noise of ~196 counts (~0.64 degC per
    100 ms step), and compensation is sensitive to it (dp/dd2 ~ 0.0068
    Pa/count), injecting ~2 Pa (~0.17 m) of mean-reverting junk into every
    altitude sample. Real temperature moves in minutes, so the merged d2 is
    median-filtered over +/- med_window_s/2 before compensation.

    Same merge/compensate math as replay.altitude_stream (do NOT touch
    common.py — Phase-3 comparability), but returns both the raw-d2 altitude
    (alt_raw, for the before/after noise report) and the filtered one.
    Returns (t, alt_filt, alt_raw, noise_report).
    """
    df = pd.read_csv(csv_path, index_col=False)   # pandas 3: index_col=False!
    df["t_s"] = df.t_us / 1e6
    pr = df[(df.type == "P") & (df.sid == sid)][["t_s", "d1"]].dropna()
    tr = df[(df.type == "T") & (df.sid == sid)][["t_s", "d2"]].dropna()
    sc = loader.sidecar_for(Path(csv_path))
    prom = loader.get_prom(sc, sid) if sc else None
    if prom is None:
        raise SystemExit(f"{Path(csv_path).name} sid={sid}: no PROM in sidecar")
    d1 = pr.d1.values.astype(float)
    bad = (d1 < replay.D1_BAND[0]) | (d1 > replay.D1_BAND[1])
    pr = pr[~bad]
    d1 = pr.d1.values.astype(float)
    tr = tr.sort_values("t_s")
    t_p = pr.t_s.values
    idx = np.searchsorted(tr.t_s.values, t_p, side="right") - 1
    idx = np.clip(idx, 0, len(tr) - 1)
    d2 = tr.d2.values[idx].astype(float)
    d2_bad = (d2 < replay.D2_BAND[0]) | (d2 > replay.D2_BAND[1])
    if d2_bad.any():
        good = ~((tr.d2.values < replay.D2_BAND[0]) | (tr.d2.values > replay.D2_BAND[1]))
        d2[d2_bad] = np.interp(t_p[d2_bad], tr.t_s.values[good], tr.d2.values[good])

    half = med_window_s / 2.0
    d2_f = np.empty_like(d2)
    for i in range(len(d2)):
        m = (t_p >= t_p[i] - half) & (t_p <= t_p[i] + half)
        d2_f[i] = np.median(d2[m]) if m.any() else d2[i]

    p_raw, _ = loader.compensate_ms5611(d1, d2, prom)
    p_filt, _ = loader.compensate_ms5611(d1, d2_f, prom)
    n0 = min(len(p_filt), 2000)
    p0 = np.nanmean(p_filt[:n0])
    p0r = np.nanmean(p_raw[:n0])
    alt_filt = 44330.0 * (1.0 - (p_filt / p0) ** 0.1903)
    alt_raw = 44330.0 * (1.0 - (p_raw / p0r) ** 0.1903)

    order = np.argsort(t_p, kind="stable")
    t, alt_filt, alt_raw = t_p[order], alt_filt[order], alt_raw[order]
    # 1-s-detrended altitude noise, raw vs filtered [M]
    def hp_noise(alt):
        return np.sqrt(estimate_r_baro(alt, t))
    noise_report = dict(noise_raw_m=np.sqrt(hp_noise(alt_raw)),
                        noise_filt_m=np.sqrt(hp_noise(alt_filt)))
    return t, alt_filt, alt_raw, noise_report


def replay_fused(t_baro, alt, t_imu, accel, quats, q, r):
    """Interleaved asynchronous replay. Returns (v at baro times, filter)."""
    f = BaroImuFusion(q=q, r=r)
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


def replay_baro_only(t_baro, alt, q, r):
    f = BaroImuFusion(q=q, r=r)
    v = np.empty(len(t_baro))
    for i in range(len(t_baro)):
        v[i] = f.update_baro(alt[i], t_baro[i])
    return v, f


def analyse_session(csv_path, q, r, g_device=None):
    imu = imu_io.imu_stream(csv_path)
    if imu is None:
        return None
    t_im, a_body, gyro = imu["t_s"], imu["accel"], imu["gyro"]

    # Gravity-scale calibration [M]: this MPU6050 clone reads |a| = 10.055
    # m/s^2 at rest (+2.5% scale error). The scale factor is a PER-DEVICE
    # constant, so the clean static capture's value is applied to every
    # session. Per-session fallback: median of |a| over samples in [8.5, 11.5]
    # m/s^2 — but slow controlled hand motion keeps |a| inside that band with
    # orientation-dependent modulation, which poisoned ControledMove2's
    # per-session estimate to 9.567. Hence: static first, always.
    a_norm_raw = np.linalg.norm(a_body, axis=1)
    if g_device is not None:
        g_cal = float(g_device)
    else:
        cal_mask = (a_norm_raw >= 8.5) & (a_norm_raw <= 11.5)
        g_cal = (float(np.median(a_norm_raw[cal_mask])) if cal_mask.sum() > 100
                 else float(np.median(a_norm_raw)))
    a_cal = a_body * (G0 / g_cal)
    rest0 = t_im <= 3.0          # capture-start window (diagnostics only now)

    # gyro bias from the capture-start rest window (operator procedure)
    gb = imu_io.gyro_bias_rad_s(imu)
    gyro_c = gyro - gb

    # Warm-start attitude from the first sample's gravity direction [M]:
    # identity q0 leaks ~2.2 m/s^2 of gravity into a_down for ~5 s while
    # Madgwick acquires the rig's tilt — enough to run the fused KF away.
    q0 = attitude.quat_from_accel_tilt(a_cal[0])
    quats = attitude.estimate_attitude(t_im, a_cal, gyro_c, q0=q0)

    a_norm = np.linalg.norm(a_cal, axis=1)

    # sanity: Madgwick gravity residual AFTER the initial convergence
    # transient (script 19 [M]: from identity q0 the estimator needs ~5 s to
    # acquire the rig's ~6.3 deg tilt; from t=5 s onward |az| = 0.011 m/s^2).
    from fusion import gravity_compensate
    conv = t_im >= min(10.0, 0.2 * float(t_im[-1]))
    az_conv = np.array([gravity_compensate(a_cal[i], quats[i])
                        for i in np.where(conv)[0]])

    rows = []
    trace0 = None
    for sid in (0, 1):
        try:
            t_b, alt, alt_raw, d2rep = altitude_stream_d2filt(csv_path, sid)
        except Exception:
            continue
        if len(t_b) < 50:
            continue
        t_b = np.asarray(t_b, dtype=float) - float(t_b[0])   # zero-base, same as IMU
        alt = np.asarray(alt, dtype=float)

        v_f, f_f = replay_fused(t_b, alt, t_im, a_cal, quats, q, r)
        v_b, f_b = replay_baro_only(t_b, alt, q, r)
        if sid == 0:
            trace0 = dict(t_im=t_im, a_norm=a_norm, t_b=t_b, v_b=v_b, v_f=v_f)

        rm = rest_mask_barotimes(t_b, t_im, a_norm)

        def vrms(x, m):
            return float(np.sqrt(np.mean(x[m] ** 2))) if m.any() else np.nan

        rows.append(dict(
            session=Path(csv_path).stem, sid=sid,
            n_imu=len(t_im), imu_rate_hz=round(1.0 / np.median(np.diff(t_im)), 1),
            g_cal=round(g_cal, 3),
            rest_a_mean=round(float(np.mean(a_norm[rest0])), 3),
            rest_a_std=round(float(np.std(a_norm[rest0])), 3),
            gyro_bias_mdps=round(float(np.linalg.norm(gb) / np.pi * 180e3), 1),
            madgwick_rest_az_err=round(float(np.mean(np.abs(az_conv))), 3),
            alt_noise_raw_m=round(d2rep["noise_raw_m"], 4),
            alt_noise_filt_m=round(d2rep["noise_filt_m"], 4),
            r_est=round(r, 5), q_cfg=q,
            v_rms_baro_only=round(vrms(v_b, np.ones(len(t_b), bool)), 4),
            v_rms_fusion=round(vrms(v_f, np.ones(len(t_b), bool)), 4),
            v_rms_rest_baro_only=round(vrms(v_b, rm), 4),
            v_rms_rest_fusion=round(vrms(v_f, rm), 4),
            max_abs_v_baro_only=round(float(np.max(np.abs(v_b))), 3),
            max_abs_v_fusion=round(float(np.max(np.abs(v_f))), 3),
            accel_bias_norm_final=round(float(np.linalg.norm(f_f.accel_bias)), 4),
            n_gated_fusion=int(f_f.n_gated), fault_fusion=bool(f_f.fault),
            n_gated_baro_only=int(f_b.n_gated), fault_baro_only=bool(f_b.fault),
            n_reinit_fusion=int(f_f.n_reinit),
            n_reinit_baro_only=int(f_b.n_reinit),
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

    # Measurement-noise variance for the fusion KF, estimated [M] from the
    # benchstatic capture (both sids, median) on the D2-filtered altitude.
    # Noise decomposition (script 18 [M]): the pressure ADC d1 dominates at
    # 2.56-2.89 Pa lag-1 (0.21-0.24 m alt); the clone's noisy temperature
    # channel d2 contributes only ~0.2 Pa and median-filtering it changes
    # almost nothing (kept anyway — physically right, costs nothing).
    # r must reflect the d1 noise the KF actually absorbs; the Phase-4
    # synthetic default r=0.035 latched the innovation gate on every sample.
    r_estimates = []
    static_csvs = [f for f in t007 if "static" in f.stem.lower()]

    # Per-device gravity scale from the cleanest rest data available [M]
    # (see analyse_session — per-session estimates are fragile under motion).
    g_device = None
    for f in static_csvs:
        imu = imu_io.imu_stream(f)
        if imu is None:
            continue
        an = np.linalg.norm(imu["accel"], axis=1)
        m = (an >= 8.5) & (an <= 11.5)
        g_device = (float(np.median(an[m])) if m.sum() > 100
                    else float(np.median(an)))
        print(f"device g_cal from {f.stem}: {g_device:.3f} m/s^2 "
              f"(clone scale error {(g_device / G0 - 1) * 100:+.1f}%)")
        break

    for f in static_csvs:
        for sid in (0, 1):
            try:
                t_b, alt_f, alt_raw, rep = altitude_stream_d2filt(f, sid)
                r_estimates.append(estimate_r_baro(
                    np.asarray(alt_f, dtype=float), np.asarray(t_b, dtype=float)))
                print(f"  d2-filter noise {f.stem} sid{sid}: raw "
                      f"{rep['noise_raw_m']:.4f} m -> filt {rep['noise_filt_m']:.4f} m")
            except Exception:
                pass
    r = float(np.nanmedian(r_estimates)) if r_estimates else 0.035

    # Exploratory process-noise sweep (baro-only KF). Two selection criteria,
    # both needed because static alone cannot discriminate q [M]:
    #   (1) static rest hp v-RMS — flat plateau 0.2-0.6 m/s across q; room
    #       pressure drift leaks into the hp band and dominates the metric;
    #   (2) MOTION VETO: on drop/toss captures, small q collapses P, the
    #       innovation gate storms, and fault-recovery reinitializes every
    #       2-4 s — each reinit snapping v to 0 during the exact moments we
    #       care about. Reinit rate on a motion capture vetoes small q.
    # EXPLORATORY ONLY — final estimator selection stays deferred.
    q_candidates = [0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
    sweep_rows = []
    for f in static_csvs:
        for sid in (0, 1):
            try:
                t_b, alt_f, _, _ = altitude_stream_d2filt(f, sid)
            except Exception:
                continue
            t_b = np.asarray(t_b, dtype=float) - float(t_b[0])
            alt_f = np.asarray(alt_f, dtype=float)
            for qq in q_candidates:
                v, flt = replay_baro_only(t_b, alt_f, qq, r)
                vs = pd.Series(v)
                v_hp = (vs - vs.rolling(window=451, center=True,
                                        min_periods=1).mean()).values
                sweep_rows.append(dict(session=f.stem, sid=sid, q=qq,
                                       v_rms=float(np.sqrt(np.mean(v ** 2))),
                                       v_rms_hp=float(np.sqrt(np.mean(v_hp ** 2))),
                                       n_gated=int(flt.n_gated),
                                       n_reinit=int(flt.n_reinit),
                                       fault=bool(flt.fault)))
    # motion veto: reinit count on the first drop/toss/controlled-move capture
    motion_csv = next((f for f in t007 if any(k in f.stem.lower()
                                              for k in ("drop2", "drop", "toss",
                                                        "controlledmove"))), None)
    veto = {}
    if motion_csv is not None:
        try:
            t_b, alt_f, _, _ = altitude_stream_d2filt(motion_csv, 0)
            t_b = np.asarray(t_b, dtype=float) - float(t_b[0])
            alt_f = np.asarray(alt_f, dtype=float)
            for qq in q_candidates:
                _, flt = replay_baro_only(t_b, alt_f, qq, r)
                veto[qq] = int(flt.n_reinit)
        except Exception:
            veto = {}
    q = 10.0   # documented exploratory default if the sweep is unusable
    if sweep_rows:
        sw = pd.DataFrame(sweep_rows)
        sw.to_csv(RES / "17_q_sweep_static.csv", index=False)
        n_baro_ref = float(np.median([len(pd.read_csv(f, index_col=False))
                                      for f in static_csvs])) if static_csvs else 1.0
        healthy = sw[(sw.n_gated < 0.1 * n_baro_ref) & (sw.n_reinit <= 3)]
        g_all = sw.groupby("q")["v_rms_hp"].median()
        print(f"\nq sweep (static, baro-only, drift-removed rest v-RMS, m/s;"
              f" motion-veto reinit counts on {motion_csv.stem if motion_csv else 'n/a'}):")
        for qq, val in g_all.items():
            tag = ""
            if not len(healthy[healthy.q == qq]):
                tag = "   <- EXCLUDED (gating/reinit)"
            elif veto.get(qq, 0) > 10:
                tag = f"   <- VETOED (motion reinit={veto[qq]})"
            print(f"  q={qq:7.1f}  v_rms_hp={val:.4f}{tag}")
        eligible = [qq for qq in g_all.index
                    if len(healthy[healthy.q == qq]) and veto.get(qq, 0) <= 10]
        if eligible:
            g = g_all[eligible]
            spread = (g.max() - g.min()) / g.min()
            if spread < 0.20:
                # plateau: the metric has no statistical power to discriminate
                # q (room-drift leakage dominates) — argmin would be false
                # precision. Take the documented exploratory mid-value.
                q = 10.0
                print(f"-> static hp plateau (spread {spread * 100:.0f}% < 20%): "
                      f"no discrimination — exploratory q = 10.0 (mid-range, "
                      f"motion-vetted), plateau {g.min():.4f}-{g.max():.4f} m/s")
            else:
                q = float(g.idxmin())
                print(f"-> exploratory q = {q} (min static rest hp v-RMS = "
                      f"{g.min():.4f} m/s among motion-vetted configs)")
        else:
            print("-> all configs vetted/excluded; falling back to q = 10.0")
    print(f"r_est (altitude noise var) = {r:.5f} m^2  ({len(r_estimates)} estimates), q = {q}")

    for f in t007:
        out = analyse_session(f, q, r, g_device)
        if out is None:
            print(f"skip {f.name}: no IMU stream")
            continue
        rows, trace = out
        all_rows.extend(rows)
        fig_data[f.stem] = trace
        for row in rows:
            print("  ", {k: row[k] for k in
                         ("session", "sid", "g_cal", "madgwick_rest_az_err",
                          "alt_noise_raw_m", "alt_noise_filt_m",
                          "v_rms_rest_baro_only", "v_rms_rest_fusion",
                          "max_abs_v_baro_only", "max_abs_v_fusion",
                          "n_gated_fusion", "fault_fusion",
                          "n_gated_baro_only", "fault_baro_only",
                          "n_reinit_fusion", "n_reinit_baro_only")})

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
