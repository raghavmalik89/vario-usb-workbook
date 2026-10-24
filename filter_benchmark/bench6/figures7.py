"""Bench 7 figures — reads results/*.csv and results/traces7/*.npz only.

  figs7/71_elevator_aligned.png  altitude + velocity traces (5 firmware est)
                                 + MCU virtual-audio ON bands
  figs7/72_handtest_aligned.png  same layout for the hand test incl. slow block
  figs7/73_noise_latency.png     static noise vs elevator onset latency,
                                 Pareto front, S2 freeze flagged
  figs7/74_audio_cost.png        false/missed audio trade + cost-vs-performance
  figs7/75_sensor_compare.png    BMP581 vs MS5611 (Bench 6) paired bars

Repro:  python figures7.py   (from filter_benchmark/bench6/)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BENCH6_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH6_DIR))
FIGS = BENCH6_DIR / "figs7"
FIGS.mkdir(exist_ok=True)
RES = BENCH6_DIR / "results"

FW5 = ["D01_Kalman_CV", "C03_CV_tracker", "S4_FastSlowGated", "S5_LightGateKF", "FUS"]
FW_COLORS = dict(zip(FW5, ["#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#ff7f0e"]))
STEMS = dict(
    static="20261024_231354_idf_bmp581_static",
    hand="20261024_233753_idf_bmp581_handtest1",
    elev="20261024_235054_idf_bmp581_elevator_2x",
)


def load_trace(kind):
    stem = STEMS[kind]
    z = np.load(RES / "traces7" / f"{stem}_sid0.npz", allow_pickle=True)
    return {k: z[k] for k in z.files}


def audio_bands(t, v):
    """ON bands (t_on, t_off) via the frozen audio policy."""
    sys.path.insert(0, str(BENCH6_DIR / ".." / "src"))
    from audio import AudioStateMachine, apply_audio
    sm = AudioStateMachine(0.20, 0.05)
    states, _ = apply_audio(t, v, sm)
    bands, on = [], None
    for tt, s in zip(t, states):
        if s == "on" and on is None:
            on = tt
        elif s == "off" and on is not None:
            bands.append((on, tt)); on = None
    if on is not None:
        bands.append((on, t[-1]))
    return bands


def aligned_panel(ax_v, ax_a, tr, title):
    t, alt = tr["t"], tr["alt"]
    ax_v.plot(t, tr.get("v_ref", np.zeros_like(t)), color="k", lw=0.9, alpha=0.55,
              label="reference proxy (1 s smoother)")
    for i, name in enumerate(FW5):
        v = tr[f"v::{name}"]
        c = FW_COLORS[name]
        ax_v.plot(t, v, color=c, lw=1.0, label=name.split("_")[0])
        for j, (a, b) in enumerate(audio_bands(t, v)):
            ax_a.axvspan(a, b, ymin=1 - (i + 1) / 5, ymax=1 - i / 5, color=c, alpha=0.85)
        ax_a.axhline(1 - i / 5, color="0.7", lw=0.4)
    ax_a.set_yticks([1 - (i + 0.5) / 5 for i in range(5)])
    ax_a.set_yticklabels([n.split("_")[0] for n in FW5])
    ax_a.set_ylim(0, 1)
    ax_a.set_xlim(t[0], t[-1])
    ax_v.axhline(0.20, color="k", ls=":", lw=0.7)
    ax_v.axhline(0.05, color="k", ls=":", lw=0.7)
    ax_v.set_ylabel("vertical velocity (m/s)")
    ax_v.legend(loc="upper right", fontsize=7, ncol=3)
    ax_v.set_title(title, fontsize=10)
    ax_a.set_xlabel("device time (s)")
    ax_a.set_ylabel("audio ON")


def fig71_72():
    for kind, fname, ttl in [
        ("elev", "71_elevator_aligned.png",
         "BMP581 elevator — altitude, estimator velocities, MCU-equivalent audio policy"),
        ("hand", "72_handtest_aligned.png",
         "BMP581 handtest — altitude, estimator velocities, audio policy")]:
        tr = load_trace(kind)
        fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(11, 8), sharex=True,
                                         gridspec_kw=dict(height_ratios=[1, 2, 1.1]))
        t, alt = tr["t"], tr["alt"]
        a1.plot(t, alt, lw=0.8, color="0.2")
        a1.set_ylabel("altitude (m)")
        a1.set_title(ttl, fontsize=10)
        if "legs" in tr:
            for (a, b, v, _) in tr["legs"]:
                a1.axvspan(a, b, color="0.85", alpha=0.7)
                a1.text((a + b) / 2, a1.get_ylim()[1], f"{v:+.2f}", fontsize=7, ha="center")
        if "slow_blocks" in tr:
            for (a, b) in tr["slow_blocks"]:
                a1.axvspan(a, b, color="#ffeeba", alpha=0.8)
        aligned_panel(a2, a3, tr, "")
        fig.tight_layout()
        fig.savefig(FIGS / fname, dpi=140)
        plt.close(fig)
        print("wrote", FIGS / fname)


def pareto_front(x, y):
    """indices of the (min-x, min-y) Pareto front"""
    idx = np.argsort(x)
    front, best = [], np.inf
    for i in idx:
        if y[i] < best:
            front.append(i); best = y[i]
    return np.array(front)


def fig73_74():
    s = pd.read_csv(RES / "70_static.csv")
    e = pd.read_csv(RES / "71_elevator_summary.csv")
    m = s.merge(e, on="candidate", suffixes=("_s", "_e"))
    # note: 'rise_med_s' is the native column name in 71 (median rise),
    # NOT a merge suffix; 'rest_rms' exists only in 70.
    ok = m.dropna(subset=["rest_rms", "rise_med_s"])

    fig, ax = plt.subplots(figsize=(8.5, 6))
    defect = m.candidate.eq("S2_DualTimescale")
    ax.scatter(ok.rest_rms, ok.rise_med_s, s=28, color="0.4", label="candidate")
    ax.scatter(ok.rest_rms[ok.candidate.isin(FW5)], ok.rise_med_s[ok.candidate.isin(FW5)],
               s=60, color=[FW_COLORS[c] for c in ok.candidate[ok.candidate.isin(FW5)]],
               label="firmware bank", zorder=5)
    f = pareto_front(ok.rest_rms.values, ok.rise_med_s.values)
    ax.plot(ok.rest_rms.values[f], ok.rise_med_s.values[f], "k--", lw=0.8, alpha=0.6)
    for _, r in ok.iterrows():
        if r.candidate in FW5 or r.candidate.startswith(("S", "FUS", "D01", "C03")):
            ax.annotate(r.candidate.split("_")[0], (r.rest_rms, r.rise_med_s),
                        fontsize=7, xytext=(3, 3), textcoords="offset points")
    if defect.any():
        r = m[defect].iloc[0]
        ax.annotate("S2 freeze defect (F1)", (r.rest_rms, r.rise_med_s),
                    fontsize=8, color="red", xytext=(-90, 6), textcoords="offset points",
                    arrowprops=dict(arrowstyle="->", color="red", lw=0.8))
    ax.set_xscale("log")
    ax.set_xlabel("stationary velocity noise  RMS (m/s)  [70_static]")
    ax.set_ylabel("median lift-onset rise time (s)  [71_elevator]")
    ax.set_title("Bench 7 (BMP581): noise vs responsiveness — Pareto front dashed")
    ax.legend(fontsize=8); ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(FIGS / "73_noise_latency.png", dpi=140); plt.close(fig)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.2))
    ok2 = m.dropna(subset=["audio_dwell_false_on_s", "audio_missed_lifts"])
    false_audio = ok2.audio_dwell_false_on_s + ok2.audio_descent_spurious_on_s.fillna(0)
    a1.scatter(false_audio, ok2.audio_missed_lifts, s=28, color="0.4")
    sel = ok2.candidate.isin(FW5)
    a1.scatter(false_audio[sel], ok2.audio_missed_lifts[sel], s=60,
               color=[FW_COLORS[c] for c in ok2.candidate[sel]], zorder=5)
    for _, r in ok2[sel].iterrows():
        a1.annotate(r.candidate.split("_")[0],
                    (false_audio[r.name], r.audio_missed_lifts), fontsize=7,
                    xytext=(3, 3), textcoords="offset points")
    a1.set_xlabel("false audio (s): dwell false-ON + descent spurious")
    a1.set_ylabel("missed lifts (of 2 ascents)")
    a1.set_title("Elevator audio correctness trade")
    a1.grid(alpha=0.25); a1.set_yticks([0, 1, 2])
    f = pareto_front(false_audio.values, ok2.audio_missed_lifts.values)
    a1.plot(false_audio.values[f], ok2.audio_missed_lifts.values[f], "k--", lw=0.8, alpha=0.6)

    a2.scatter(m.cpu_us_per_update_s, m.rest_rms, s=28, color="0.4")
    sel2 = m.candidate.isin(FW5)
    a2.scatter(m.cpu_us_per_update_s[sel2], m.rest_rms[sel2], s=60,
               color=[FW_COLORS[c] for c in m.candidate[sel2]], zorder=5)
    for _, r in m[sel2].iterrows():
        a2.annotate(r.candidate.split("_")[0], (r.cpu_us_per_update_s, r.rest_rms),
                    fontsize=7, xytext=(3, 3), textcoords="offset points")
    f = pareto_front(m.cpu_us_per_update_s.values, m.rest_rms.values)
    a2.plot(m.cpu_us_per_update_s.values[f], m.rest_rms.values[f], "k--", lw=0.8, alpha=0.6)
    a2.set_xscale("log"); a2.set_yscale("log")
    a2.set_xlabel("host compute (µs/update)")
    a2.set_ylabel("stationary velocity noise RMS (m/s)")
    a2.set_title("Cost vs performance — Pareto front dashed")
    a2.grid(alpha=0.25, which="both")
    fig.tight_layout(); fig.savefig(FIGS / "74_audio_cost.png", dpi=140); plt.close(fig)
    print("wrote 73 / 74")


def fig75():
    s6 = pd.read_csv(RES / "60_static.csv")
    e6 = pd.read_csv(RES / "61_elevator_summary.csv")
    s7 = pd.read_csv(RES / "70_static.csv")
    e7 = pd.read_csv(RES / "71_elevator_summary.csv")
    m6 = s6.merge(e6, on="candidate", suffixes=("_s", "_e"))
    m7 = s7.merge(e7, on="candidate", suffixes=("_s", "_e"))
    # bench6 has several static sessions per candidate -> average per candidate
    m6 = m6.groupby("candidate", as_index=False).mean(numeric_only=True)
    m7 = m7.groupby("candidate", as_index=False).mean(numeric_only=True)
    cands = [c for c in FW5 if c in set(m6.candidate) & set(m7.candidate)]
    metrics = [("rest_rms", "stationary noise RMS (m/s)", True),
               ("rise_med_s", "lift-onset rise (s)", False),
               ("audio_dwell_false_on_s", "elevator false audio (s)", False)]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.2))
    x = np.arange(len(cands))
    for ax, (col, ttl, logy) in zip(axes, metrics):
        v6, v7 = m6.set_index("candidate").loc[cands, col], m7.set_index("candidate").loc[cands, col]
        b1 = ax.bar(x - 0.2, v6, 0.38, label="MS5611 (Bench 6)", color="0.55")
        b2 = ax.bar(x + 0.2, v7, 0.38, label="BMP581 (Bench 7)", color="#d62728")
        ax.set_xticks(x); ax.set_xticklabels([c.split("_")[0] for c in cands], fontsize=8)
        ax.set_title(ttl, fontsize=9)
        if logy:
            ax.set_yscale("log")
            # log-bar autoscale pins the floor near the BMP581 min and
            # squashes the interesting differences — pin a readable floor
            lo = min(v6.min(), v7.min()) * 0.4
            hi = max(v6.max(), v7.max()) * 1.4
            ax.set_ylim(lo, hi)
        ax.grid(alpha=0.25, axis="y"); ax.legend(fontsize=7)
    fig.suptitle("Frozen-config comparison across sensors (same candidate configs, "
                 "different days/conditions — indicative, not controlled)", fontsize=10)
    fig.tight_layout(); fig.savefig(FIGS / "75_sensor_compare.png", dpi=140); plt.close(fig)
    print("wrote 75")


if __name__ == "__main__":
    fig71_72()
    fig73_74()
    fig75()
