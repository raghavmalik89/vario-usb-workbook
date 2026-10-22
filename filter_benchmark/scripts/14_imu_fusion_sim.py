"""Script 14 — Phase 4 WP-C: baro/IMU fusion verification on SYNTHETIC
streams (SIMULATED — labelled as such everywhere; no capture contains IMU
data, so no real fusion improvement is claimed).

Scenarios (seeded, reproducible):
  1. nominal: static -> climb 1.5 m/s -> static -> drop -2.5 m/s -> static
     baro-only fusion vs baro+IMU (known attitude) vs baro+IMU with bias
     estimation. Truth is known because the generator made it.
  2. baro blackout 1 s mid-climb: IMU coast vs baro-only drift.
  3. timestamp jitter +/-3 ms on IMU stamps.
  4. baro spike rejection under fusion.

Outputs:
  results/14_fusion_simulated.csv   per-scenario metrics
  results/fig_fusion_simulated.png  truth vs baro-only vs fused (nominal)
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import ROOT  # noqa: E402
import p4_eval as P4E  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
from fusion import BaroImuFusion  # noqa: E402

G = 9.80665


def make_profile(t):
    """True vertical velocity profile with PHYSICAL 0.3 s ramps (a step
    profile would give gradient spikes of hundreds of m/s^2 — a generator
    artifact, not flyable motion)."""
    v = np.zeros_like(t)
    ramp = 0.3

    def seg(t0, dur, vpeak):
        m = (t >= t0) & (t < t0 + ramp)
        v[m] += vpeak * (t[m] - t0) / ramp
        m = (t >= t0 + ramp) & (t < t0 + dur)
        v[m] += vpeak
        m = (t >= t0 + dur) & (t < t0 + dur + ramp)
        v[m] += vpeak * (1 - (t[m] - t0 - dur) / ramp)

    seg(10.0, 7.4, 1.5)       # climb 1.5 m/s (10-18 s with ramps)
    seg(22.85, 1.4, -2.5)     # drop -2.5 m/s (22.85-24.55 s with ramps)
    z = np.cumsum(v) * np.median(np.diff(t))
    return z, v


def simulate_sensors(t, v_true, z_true, rng, baro_noise=0.03, imu_noise=0.05,
                     bias=(0.05, -0.03, 0.08), jitter_s=0.0, blackout=None):
    """Baro alt stream + IMU specific-force stream for the profile.
    Identity attitude (sensor level, z-down Earth frame)."""
    dt = np.median(np.diff(t))
    a_true = np.gradient(v_true, t)          # true vertical accel
    baro = z_true + rng.normal(0, baro_noise, len(t))
    if blackout is not None:                 # baro blackout interval
        b0, b1 = blackout
        keep = (t < b0) | (t >= b1)
        baro = baro[keep]
        t_baro = t[keep]
    else:
        keep = np.ones(len(t), dtype=bool)
        t_baro = t
    # IMU at 100 Hz specific force: f_z = a_z - g  (z-down)
    f_z = a_true - G + rng.normal(0, imu_noise, len(t)) + bias[2]
    f_x = rng.normal(0, imu_noise, len(t)) + bias[0]
    f_y = rng.normal(0, imu_noise, len(t)) + bias[1]
    t_imu = t.copy()
    if jitter_s > 0:
        t_imu = t + rng.uniform(-jitter_s, jitter_s, len(t))
        t_imu = np.maximum.accumulate(t_imu)
    return t_baro, baro, t_imu, np.stack([f_x, f_y, f_z], axis=1), keep


def run_fusion(t_baro, baro, t_imu, f_imu, use_imu=True, estimate_bias=True,
               quat=None):
    fus = BaroImuFusion()
    bias = np.zeros(3) if estimate_bias else None
    v_out = np.empty(len(t_baro))
    j = 0
    for i in range(len(t_baro)):
        tb = t_baro[i]
        if use_imu:
            while j < len(t_imu) and t_imu[j] <= tb:
                fus.update_imu(f_imu[j], float(t_imu[j]), quat=quat)
                j += 1
        v_out[i] = fus.update_baro(float(baro[i]), float(tb))
    return v_out, fus


def phase_metrics(t_baro, v_est, v_true):
    """RMS error per phase + climb tracking error (SIMULATED ground truth)."""
    out = {}
    for name, m in (("static1", t_baro < 10), ("climb", (t_baro >= 10) & (t_baro < 18)),
                    ("static2", (t_baro >= 18) & (t_baro < 23)),
                    ("drop", (t_baro >= 23) & (t_baro < 25)),
                    ("static3", t_baro >= 25)):
        if m.any():
            err = v_est[m] - v_true[m]
            out[f"{name}_rms_err"] = round(float(np.sqrt(np.mean(err ** 2))), 4)
            out[f"{name}_max_abs_err"] = round(float(np.max(np.abs(err))), 4)
    return out


def main():
    rng = np.random.default_rng(20261022)
    t = np.arange(0, 30.0, 0.01)             # baro at 100 Hz
    z_true, v_true = make_profile(t)
    rows = []

    # scenario 1: nominal
    t_baro, baro, t_imu, f, _ = simulate_sensors(t, v_true, z_true, rng)
    q_id = (1.0, 0.0, 0.0, 0.0)
    for label, use_imu, est_bias, quat in (
            ("baro_only_fallback", False, False, None),
            ("fusion_known_attitude", True, False, q_id),
            ("fusion_bias_estimation", True, True, q_id)):
        v_est, fus = run_fusion(t_baro, baro, t_imu, f, use_imu=use_imu,
                                estimate_bias=est_bias, quat=quat)
        row = dict(scenario="nominal", variant=label, simulated=1, **(
            phase_metrics(t_baro, v_est, v_true)))
        if est_bias:
            row["bias_est_z_final"] = round(float(fus.accel_bias[2]), 4)
        rows.append(row)
        if label == "baro_only_fallback":
            v_baro_only = v_est
        if label == "fusion_bias_estimation":
            v_fused = v_est

    # scenario 2: baro blackout 22.8-23.8 s (spanning the drop ONSET, where
    # velocity CHANGES — constant-velocity gaps are trivially predicted by
    # a baro-only filter, so that case is not the interesting one)
    t_b, baro_b, t_i, f_b, keep_b = simulate_sensors(t, v_true, z_true, rng,
                                                     blackout=(22.8, 23.8))
    v_true_b = v_true[keep_b]
    for label, use_imu in (("baro_only_blackout", False),
                           ("fusion_blackout_coast", True)):
        v_est, _ = run_fusion(t_b, baro_b, t_i, f_b, use_imu=use_imu,
                              quat=q_id)
        m = (t_b >= 22.8) & (t_b < 25.5)      # blackout + recovery window
        err = v_est[m] - v_true_b[m]
        rows.append(dict(scenario="baro_blackout_1s", variant=label,
                         simulated=1,
                         blackout_window_rms_err=round(
                             float(np.sqrt(np.mean(err ** 2))), 4),
                         blackout_window_max_abs_err=round(
                             float(np.max(np.abs(err))), 4)))

    # scenario 3: timestamp jitter on IMU
    t_baro3, baro3, t_imu3, f3, _ = simulate_sensors(t, v_true, z_true, rng,
                                                     jitter_s=0.003)
    v_est, _ = run_fusion(t_baro3, baro3, t_imu3, f3, quat=q_id)
    rows.append(dict(scenario="imu_jitter_3ms", variant="fusion_jitter",
                     simulated=1, **phase_metrics(t_baro3, v_est, v_true)))

    # scenario 4: baro spike under fusion
    baro4 = baro.copy()
    baro4[np.searchsorted(t_baro, 15.0)] += 8.0   # 8 m spike
    v_est, _ = run_fusion(t_baro, baro4, t_imu, f, quat=q_id)
    m = (t_baro >= 15.0) & (t_baro <= 17.0)
    rows.append(dict(scenario="baro_spike_8m", variant="fusion_spike",
                     simulated=1,
                     post_spike_max_abs_v=round(
                         float(np.max(np.abs(v_est[m]))), 4)))

    P4E.write_csv(rows, ROOT / "results" / "14_fusion_simulated.csv")

    # figure: truth vs baro-only vs fused (nominal)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(t, v_true, "k--", lw=1.5, label="true v (Simulated)")
    ax.plot(t_baro, v_baro_only, lw=0.9, alpha=0.8,
            label="baro-only fallback (Simulated)")
    ax.plot(t_baro, v_fused, lw=0.9, alpha=0.8,
            label="baro+IMU fusion (Simulated)")
    ax.axhline(0.2, color="r", ls=":", lw=0.8)
    ax.axhline(-0.2, color="r", ls=":", lw=0.8)
    ax.set_xlabel("t [s]"); ax.set_ylabel("vertical speed [m/s]")
    ax.set_title("Fusion verification on SYNTHETIC stream (SIMULATED — no "
                 "real IMU capture exists)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(ROOT / "results" / "fig_fusion_simulated.png", dpi=140)
    print(f"wrote {len(rows)} scenario rows + fig_fusion_simulated.png")


if __name__ == "__main__":
    main()
