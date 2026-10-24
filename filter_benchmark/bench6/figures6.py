"""Bench 6 — comprehensive figure suite.

Reads ONLY the frozen-run artifacts (results/*.csv, results/traces/*.npz) plus
the MCU V-frames for overlays — never re-replays filters. Each figure is
self-contained; a failure in one does not abort the rest.

Outputs bench6/figs/figNN_*.png.
Repro: python -u figures6.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

BENCH6_DIR = Path(__file__).resolve().parent
BENCH_ROOT = BENCH6_DIR.parents[0]
SRC = BENCH_ROOT / "src"
for p in (str(SRC), str(BENCH6_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import datasets as ds  # noqa: E402
import streams  # noqa: E402
import metrics6  # noqa: E402
from candidates import CANDIDATES, GROUPS  # noqa: E402

RES = BENCH6_DIR / "results"
TRC = RES / "traces"
FIGS = BENCH6_DIR / "figs"
FIGS.mkdir(exist_ok=True)

R1 = "20261023_221124_idf_elevator_2x"
R2 = "20261023_221420_idf_elevator_2x"
HT = "20261023_215709_idf_handtest3"
ST = "20261023_234521_idf_p0fix_static"
BB = "20261023_234944_idf_bbuf_check"

CANDS = list(CANDIDATES.keys())
FAMILY = {n: fam for fam, names in GROUPS.items() for n in names}
FCOLOR = dict(baseline="0.45", smoothing="0.6", classical="#8c8c00",
              tracking="#1f77b4", kalman="#2ca02c", adaptive="#17becf",
              stacked="#d62728", fusion="#9467bd", defect="#ff7f0e")
BANK = ["D01_Kalman_CV", "C03_CV_tracker", "S4_FastSlowGated",
        "S5_LightGateKF", "FUS"]
plt.rcParams.update({"figure.dpi": 110, "font.size": 8.5,
                     "axes.grid": True, "grid.alpha": 0.3})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIGS / name, dpi=140)
    plt.close(fig)
    print("  wrote", name, flush=True)


def load_trc(stem, sid=0):
    d = np.load(TRC / f"{stem}_sid{sid}.npz", allow_pickle=True)
    return {k: d[k] for k in d.files}


def cand_keys(tr):
    return [k[3:] for k in tr if k.startswith("v::")]


def audio_strip(ax, t, v, t_range, color, label=None, sm=None):
    """Draw ON episodes of the virtual-audio policy as a horizontal bar."""
    sm = sm or metrics6.AudioStateMachine(metrics6.LIFT_ON, metrics6.LIFT_OFF)
    m = (t >= t_range[0]) & (t <= t_range[1])
    states, _ = metrics6.run_audio(sm, t[m], v[m])
    on = np.array(states) == "on"
    segs, start = [], None
    tt = t[m]
    for i, o in enumerate(on):
        if o and start is None:
            start = tt[i]
        elif not o and start is not None:
            segs.append((start, tt[i] - start))
            start = None
    if start is not None:
        segs.append((start, tt[-1] - start))
    ax.broken_barh(segs, (0, 1), facecolors=color, alpha=0.85, label=label)


def mcu_audio_strip(ax, stem, eid, t_range, color, label=None):
    t, e, ev, _ = streams.v_frames(stem)
    m = (e == eid) & (np.isin(ev, (1, 2)))
    t, ev = t[m], ev[m]
    segs, start = [], None
    for tt, ee in zip(t, ev):
        if ee == 1:
            start = tt
        elif ee == 2 and start is not None:
            segs.append((start, tt - start))
            start = None
    if start is not None:
        segs.append((start, t_range[1] - start))
    segs = [s for s in segs if s[0] < t_range[1] and s[0] + s[1] > t_range[0]]
    ax.broken_barh(segs, (0, 1), facecolors=color, alpha=0.85, label=label)


# ----------------------------------------------------------- F01 overview ---
def f01_overview():
    tr = load_trc(R1, 0)
    t, alt = tr["t"], tr["alt"]
    fig, axs = plt.subplots(4, 1, figsize=(11, 7.5), sharex=True,
                            height_ratios=[2.2, 1.4, 0.5, 0.5])
    axs[0].plot(t, alt, lw=0.8, color="k")
    for (a, b, v, dh) in tr["legs"]:
        axs[0].axvspan(a, b, color="orange", alpha=0.25)
        axs[0].text((a + b) / 2, alt.max() * 0.93,
                    f"{v:+.2f} m/s", ha="center", fontsize=8)
    axs[0].set_ylabel("altitude [m] (fixed ISA)")
    axs[0].set_title("Elevator run 1 — sid0 overview: altitude, reference & "
                     "estimator velocity, virtual-audio ON/OFF "
                     "(policy +0.20/+0.05 m/s)")
    vref = np.gradient(np.convolve(alt, np.ones(50) / 50, "same"), t)
    axs[1].plot(t, vref, lw=0.7, color="0.4", label="1 s boxcar reference")
    for n, c in zip(BANK, ["#2ca02c", "#1f77b4", "#d62728", "#8c564b",
                           "#9467bd"]):
        axs[1].plot(t, tr[f"v::{n}"], lw=0.7, label=n.split("_")[0], color=c)
    axs[1].set_ylabel("v [m/s]")
    axs[1].legend(ncol=6, fontsize=7, loc="upper right")
    axs[1].set_ylim(-3.2, 3.2)
    for ax, n, c in ((axs[2], "D01_Kalman_CV", "#2ca02c"),
                     (axs[3], "S5_LightGateKF", "#8c564b")):
        audio_strip(ax, t, tr[f"v::{n}"], (t[0], t[-1]), c)
        mcu_audio_strip(ax, R1, 0 * 5 + BANK.index(n), (t[0], t[-1]),
                        "0.2", label=None)
        ax.set_yticks([])
        ax.set_ylabel(n.split("_")[0], rotation=0, labelpad=22, fontsize=7)
        ax.set_ylim(0, 1)
    axs[2].set_title("replay-audio ON episodes (colored) vs MCU V-frames "
                     "(grey)", fontsize=7)
    axs[3].set_xlabel("t [s]")
    save(fig, "fig01_elevator_overview_run1.png")


# ------------------------------------------------------- F02 all traces -----
def f02_all_traces():
    tr = load_trc(R1, 0)
    t = tr["t"]
    names = cand_keys(tr)
    fig, axs = plt.subplots(8, 5, figsize=(15, 13), sharex=True)
    axs = axs.ravel()
    for ax, n in zip(axs, names):
        v = tr[f"v::{n}"]
        fam = FAMILY.get(n, "kalman")
        ax.plot(t, v, lw=0.5, color=FCOLOR.get(fam, "k"))
        ax.set_ylabel(n, fontsize=6.5, rotation=0, labelpad=34)
        ax.set_ylim(-3.2, 3.2)
        ax.axhline(0.2, color="r", lw=0.4, ls=":")
        ax.axhline(-0.2, color="r", lw=0.4, ls=":")
        for (a, b, _, _) in tr["legs"]:
            ax.axvspan(a, b, color="orange", alpha=0.15)
        ax.tick_params(labelsize=6)
    for ax in axs[len(names):]:
        ax.axis("off")
    axs[-1].set_xlim(0, 170)
    fig.suptitle("Bench 6 — every candidate velocity trace, elevator run 1 "
                 "sid0 (legs shaded; ±0.2 m/s audio threshold dotted)", y=0.995)
    save(fig, "fig02_velocity_traces_all_run1.png")


# ------------------------------------------------------------ F03 zooms -----
def f03_zooms():
    tr = load_trc(R1, 0)
    t = tr["t"]
    picks = ["D01_Kalman_CV", "C03_CV_tracker", "S4_FastSlowGated",
             "S5_LightGateKF", "FUS", "B02_Butter2", "C01_AlphaBeta",
             "E06_RobustAdapt"]
    zooms = [("transition INTO lift (A2 start)", 49.5, 58.0),
             ("exit from lift (A2 end / floor stop)", 73.0, 84.0),
             ("floor stop after D1 (dwell wobble)", 30.0, 42.0),
             ("stationary dwell between legs", 84.0, 96.0)]
    fig, axs = plt.subplots(4, 1, figsize=(11, 10))
    vref = np.gradient(np.convolve(tr["alt"], np.ones(50) / 50, "same"), t)
    for ax, (title, t0, t1) in zip(axs, zooms):
        m = (t >= t0) & (t <= t1)
        ax.plot(t[m], vref[m], lw=1.0, color="k", label="reference")
        for n in picks:
            fam = FAMILY.get(n, "kalman")
            ax.plot(t[m], tr[f"v::{n}"][m], lw=0.7,
                    color=FCOLOR.get(fam, "0.5"), alpha=0.9,
                    label=n.split("_")[0])
        ax.axhline(0.2, color="r", lw=0.5, ls="--")
        ax.axhline(-0.2, color="r", lw=0.5, ls="--")
        ax.set_title(title, fontsize=9)
        ax.set_ylim(-3, 3.4)
    axs[0].legend(ncol=9, fontsize=6.5, loc="lower right")
    axs[-1].set_xlabel("t [s]")
    fig.suptitle("Zoom panels — elevator run 1 sid0", y=0.997)
    save(fig, "fig03_zoom_panels_run1.png")


# -------------------------------------------------------- F04 run2 condensed
def f04_run2():
    tr = load_trc(R2, 0)
    t = tr["t"]
    fig, axs = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True)
    axs[0].plot(t, tr["alt"], lw=0.8, color="k")
    for (a, b, v, _) in tr["legs"]:
        axs[0].axvspan(a, b, color="orange", alpha=0.25)
    axs[0].set_ylabel("alt [m]")
    vref = np.gradient(np.convolve(tr["alt"], np.ones(50) / 50, "same"), t)
    axs[1].plot(t, vref, lw=0.7, color="0.4")
    for n, c in zip(BANK, ["#2ca02c", "#1f77b4", "#d62728", "#8c564b",
                           "#9467bd"]):
        axs[1].plot(t, tr[f"v::{n}"], lw=0.6, label=n.split("_")[0], color=c)
    axs[1].set_ylim(-3.2, 3.2)
    axs[1].set_ylabel("v [m/s]")
    axs[1].legend(ncol=6, fontsize=7)
    axs[1].set_xlabel("t [s] (validation run 2)")
    fig.suptitle("Elevator run 2 — validation split, sid0")
    save(fig, "fig04_run2_condensed.png")


# ---------------------------------------------------------- F05 leg bias ----
def f05_leg_bias():
    legs = pd.read_csv(RES / "611_elevator_legs.csv")
    legs = legs[legs.session.str.contains("221124")]
    order = (legs.groupby("candidate").rms.median().sort_values().index)
    fig, ax = plt.subplots(figsize=(11, 6.5))
    xs = np.arange(len(order))
    for i, n in enumerate(order):
        g = legs[legs.candidate == n]
        ax.scatter([i] * len(g), g.bias, s=14, alpha=0.55,
                   color=FCOLOR.get(FAMILY.get(n), "0.4"))
        ax.scatter([i], [g.bias.median()], marker="_", s=420, color="k",
                   linewidths=1.4)
    ax.set_xticks(xs)
    ax.set_xticklabels([n.split("_")[0] for n in order], rotation=70,
                       fontsize=6.5)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_ylabel("per-leg velocity bias [m/s] (median _ over legs/runs/sids)")
    ax.set_title("Elevator per-leg bias — run 1 (dots: legs × sids)")
    save(fig, "fig05_per_leg_bias.png")


# -------------------------------------------------------- F06 handtest ------
def f06_handtest():
    tr = load_trc(HT, 0)
    t = tr["t"]
    t_imu, a_cal, _, _ = streams.imu_stream(HT)
    an = np.linalg.norm(a_cal, axis=1) - 9.80665
    fig, axs = plt.subplots(5, 1, figsize=(11, 9), sharex=True,
                            height_ratios=[1.2, 0.9, 1.6, 0.55, 0.55])
    axs[0].plot(t, tr["alt"], lw=0.8, color="k")
    axs[0].set_ylabel("alt [m]")
    axs[0].set_title("handtest3 — static + slow moves + toss (sid0)")
    axs[1].plot(t_imu, an, lw=0.3, color="0.35")
    axs[1].set_ylabel("|a|-g [m/s²]")
    axs[1].set_ylim(-14, 14)
    vref = tr.get("v_ref")
    if vref is not None:
        axs[2].plot(t, vref, lw=0.9, color="k", label="event-window ref")
    for n, c in zip(BANK, ["#2ca02c", "#1f77b4", "#d62728", "#8c564b",
                           "#9467bd"]):
        axs[2].plot(t, tr[f"v::{n}"], lw=0.6, label=n.split("_")[0], color=c)
    for (a, b) in np.atleast_2d(tr["events"]):
        for ax in axs:
            ax.axvspan(a, b, color="skyblue", alpha=0.3)
    if "slow_blocks" in tr:
        for (a, b) in np.atleast_2d(tr["slow_blocks"]):
            axs[2].axvspan(a, b, color="green", alpha=0.18)
    axs[2].set_ylabel("v [m/s]")
    axs[2].set_ylim(-4.5, 4.5)
    axs[2].legend(ncol=6, fontsize=7, loc="upper right")
    for ax, n, c in ((axs[3], "D01_Kalman_CV", "#2ca02c"),
                     (axs[4], "S5_LightGateKF", "#8c564b")):
        audio_strip(ax, t, tr[f"v::{n}"], (t[0], t[-1]), c)
        mcu_audio_strip(ax, HT, 0 * 5 + BANK.index(n), (t[0], t[-1]), "0.25")
        ax.set_yticks([])
        ax.set_ylabel(n.split("_")[0], rotation=0, labelpad=22, fontsize=7)
    axs[4].set_xlabel("t [s]")
    save(fig, "fig06_handtest_panel.png")


# ------------------------------------------------------- F07 static violins -
def f07_static_violins():
    tr = load_trc(ST, 0)
    t = tr["t"]
    names = cand_keys(tr)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    data, colors, labels = [], [], []
    for n in names:
        v = tr[f"v::{n}"][t > 8.0]
        data.append(np.clip(v, -0.5, 0.5))
        colors.append(FCOLOR.get(FAMILY.get(n), "0.4"))
        labels.append(n.split("_")[0])
    vp = ax.violinplot(data, showextrema=False, widths=0.85)
    for b, c in zip(vp["bodies"], colors):
        b.set_facecolor(c)
        b.set_alpha(0.75)
    ax.set_xticks(np.arange(1, len(names) + 1))
    ax.set_xticklabels(labels, rotation=70, fontsize=6.5)
    ax.axhline(0.05, color="r", ls="--", lw=0.6)
    ax.axhline(-0.05, color="r", ls="--", lw=0.6)
    ax.set_ylabel("rest velocity distribution [m/s] (clipped ±0.5)")
    ax.set_title("Static silence — p0fix_static sid0, t>8 s (±0.05 lift_off "
                 "dashed)")
    save(fig, "fig07_static_violins.png")


# ------------------------------------------------------ F08-F10 scatters ----
def med_session(df, col, sessions=None):
    d = df if sessions is None else df[df.session.isin(sessions)]
    g = d.groupby("candidate")[col].median()
    return g


def f08_scatter_noise_onset():
    elev = pd.read_csv(RES / "61_elevator_summary.csv")
    stat = pd.read_csv(RES / "60_static.csv")
    hand = pd.read_csv(RES / "62_handtest.csv")
    rest = med_session(stat, "rest_rms")
    rise = med_session(elev[elev.session.str.contains("221124")], "rise_med_s")
    onset = med_session(hand, "onset_med_s")
    srms = med_session(hand, "static_rms")
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.6), sharey=False)
    for ax, (y, ylab, title) in zip(
            axs, [(rise, "elevator rise proxy [s]", "noise vs response "
                   "(elevator)"),
                  (onset, "handtest onset [s]", "noise vs response "
                   "(handtest)")]):
        for n in rest.index:
            if n not in y.index or not np.isfinite(y[n]):
                continue
            ax.scatter(rest[n], y[n], s=26,
                       color=FCOLOR.get(FAMILY.get(n), "0.4"))
            ax.annotate(n.split("_")[0], (rest[n], y[n]), fontsize=5.5,
                        textcoords="offset points", xytext=(3, 3))
        ax.set_xscale("log")
        ax.set_xlabel("static rest RMS [m/s] (median, log scale)")
        ax.set_ylabel(ylab)
        ax.set_title(title, fontsize=9)
    save(fig, "fig08_scatter_noise_vs_onset.png")


def f09_scatter_on_off():
    elev = pd.read_csv(RES / "61_elevator_summary.csv")
    r1 = elev[elev.session.str.contains("221124")]
    g = r1.groupby("candidate").agg(r=("rise_med_s", "median"),
                                    e=("exit_med_s", "median"))
    g = g.replace([np.inf, -np.inf], np.nan).dropna()
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    for n, row in g.iterrows():
        ax.scatter(row.r, row.e, s=30,
                   color=FCOLOR.get(FAMILY.get(n), "0.4"))
        ax.annotate(n.split("_")[0], (row.r, row.e), fontsize=6,
                    textcoords="offset points", xytext=(3, 3))
    ax.set_xlabel("lift-on delay (rise proxy) [s]")
    ax.set_ylabel("lift-off delay (exit proxy) [s]  — floor at ~6.8 s is the "
                  "dwell-wobble proxy limit [D]")
    ax.set_title("Audio-response asymmetry — elevator run 1 (medians)")
    save(fig, "fig09_scatter_lift_on_off_delay.png")


def f10_scatter_false_missed():
    elev = pd.read_csv(RES / "61_elevator_summary.csv")
    hand = pd.read_csv(RES / "62_handtest.csv")
    r1 = elev[elev.session.str.contains("221124")]
    g = r1.groupby("candidate").agg(false=("audio_dwell_false_on_s", "median"),
                                    missed=("audio_missed_lifts", "median"))
    h = hand.groupby("candidate").agg(
        outside=("audio_on_frac_outside", "median"),
        sfalse=("static_false_on_per_hr", "median"))
    fig, axs = plt.subplots(1, 2, figsize=(11.5, 4.8))
    ax = axs[0]
    for n, row in g.iterrows():
        ax.scatter(row.false, row.missed, s=30,
                   color=FCOLOR.get(FAMILY.get(n), "0.4"))
        ax.annotate(n.split("_")[0], (row.false, row.missed), fontsize=6,
                    textcoords="offset points", xytext=(3, 3))
    ax.set_xlabel("dwell false-ON [s/run] (elevator)")
    ax.set_ylabel("missed lifts (elevator)")
    ax.set_title("False activation vs missed lifts — elevator run 1")
    ax = axs[1]
    for n, row in h.iterrows():
        ax.scatter(row.sfalse, row.outside, s=30,
                   color=FCOLOR.get(FAMILY.get(n), "0.4"))
        ax.annotate(n.split("_")[0], (row.sfalse, row.outside), fontsize=6,
                    textcoords="offset points", xytext=(3, 3))
    ax.set_xscale("log")
    ax.set_xlabel("static false-ON [latches/hr] (handtest, log)")
    ax.set_ylabel("audio ON-fraction outside events (handtest)")
    ax.set_title("Stationary silence — handtest3")
    save(fig, "fig10_scatter_false_vs_missed.png")


# -------------------------------------------------------- F11 CPU vs perf ---
def f11_cpu():
    cpu = pd.read_csv(RES / "63_cpu_host.csv")
    elev = pd.read_csv(RES / "61_elevator_summary.csv")
    r1 = elev[elev.session.str.contains("221124")]
    perf = r1.groupby("candidate").rms_med.median()
    rest = pd.read_csv(RES / "60_static.csv").groupby(
        "candidate").rest_rms.median()
    g = cpu.set_index("candidate").join(perf.rename("elev_rms")).join(
        rest.rename("rest_rms"))
    fig, axs = plt.subplots(1, 2, figsize=(11.5, 4.8))
    for ax, col, ylab in ((axs[0], "elev_rms", "elevator leg RMS [m/s]"),
                          (axs[1], "rest_rms", "static rest RMS [m/s]")):
        for n, row in g.iterrows():
            ax.scatter(row.host_us_per_update, row[col], s=30,
                       color=FCOLOR.get(FAMILY.get(n), "0.4"))
            ax.annotate(n.split("_")[0], (row.host_us_per_update, row[col]),
                        fontsize=6, textcoords="offset points",
                        xytext=(3, 3))
        ax.set_xscale("log")
        ax.set_xlabel("host CPU [µs/update] (log)")
        ax.set_ylabel(ylab)
    axs[0].set_title("Computation cost vs tracking performance (host "
                     "reference; on-target B-lines in report)")
    save(fig, "fig11_cpu_vs_performance.png")


# ---------------------------------------------------------- F12 pareto ------
def pareto_front(x, y):
    idx = np.argsort(x.values)
    fx, fy, keep = [], [], []
    best = np.inf
    for i in idx:
        if y.values[i] < best:
            keep.append(i)
            best = y.values[i]
    return x.values[keep], y.values[keep]


def f12_pareto():
    elev = pd.read_csv(RES / "61_elevator_summary.csv")
    stat = pd.read_csv(RES / "60_static.csv")
    r1 = elev[elev.session.str.contains("221124")]
    g = r1.groupby("candidate").agg(rms=("rms_med", "median"),
                                    rise=("rise_med_s", "median"),
                                    exit=("exit_med_s", "median"),
                                    false=("audio_dwell_false_on_s",
                                           "median"))
    g = g.join(stat.groupby("candidate").rest_rms.median().rename("rest"))
    g = g.replace([np.inf, -np.inf], np.nan)
    fig, axs = plt.subplots(2, 2, figsize=(11.5, 8.6))
    panels = [("rest", "rise", "log", "rest RMS [m/s] (log)",
               "rise proxy [s]"),
              ("rest", "rms", "log", "rest RMS [m/s] (log)",
               "elevator leg RMS [m/s]"),
              ("rest", "false", "log", "rest RMS [m/s] (log)",
               "dwell false-ON [s/run]"),
              ("rise", "exit", "linear", "rise proxy [s]",
               "exit proxy [s]")]
    for ax, (cx, cy, sx, xl, yl) in zip(axs.ravel(), panels):
        d = g[[cx, cy]].dropna()
        for n, row in d.iterrows():
            ax.scatter(row[cx], row[cy], s=30,
                       color=FCOLOR.get(FAMILY.get(n), "0.4"))
            ax.annotate(n.split("_")[0], (row[cx], row[cy]), fontsize=6,
                        textcoords="offset points", xytext=(3, 3))
        if len(d) > 2:
            fx, fy = pareto_front(d[cx], d[cy])
            ax.plot(fx, fy, "k--", lw=0.9, alpha=0.7, label="Pareto front")
            ax.legend(fontsize=7)
        if sx == "log":
            ax.set_xscale("log")
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
    fig.suptitle("Pareto trade-space — frozen configurations (medians, run 1 "
                 "+ statics)")
    save(fig, "fig12_pareto_fronts.png")


# ------------------------------------------------- F13 MCU equiv money ------
def f13_equiv():
    import equiv6
    fig = plt.figure(figsize=(11.5, 9.5))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.15, 1.15, 1.0])
    # (a) post-fix static: replay vs MCU tones (formal equivalence)
    t, alt, _ = streams.baro_stream(ST, 0, reference="isa_fw10", seed_d2=True)
    v = equiv6.replay_candidate("D01_Kalman_CV", t, alt, ST)
    tt, vi = streams.mcu_tones(ST, 0)
    ax = fig.add_subplot(gs[0, :])
    ax.plot(t, v, lw=0.8, color="#2ca02c", label="Python replay (isa_fw10 "
            "chain)")
    ax.scatter(tt, vi, s=10, color="k", label="MCU V-frame tones", zorder=5)
    ax.set_ylim(-0.3, 0.3)
    ax.annotate("startup dive to -1.5e4 m/s clipped (DEF-010 seed step, "
                "amplified by the DEF-011 scale)", xy=(0.02, 0.07),
                xycoords="axes fraction", fontsize=7.5, color="0.25")
    ax.set_title("Formal MCU equivalence — p0fix_static sid0 D01 "
                 "(steady-state |bias| <= 0.3 mm/s, p95 = 1 mm/s, audio "
                 "transition agreement 100%)")
    ax.set_ylabel("v [m/s]")
    ax.legend(fontsize=7)
    ax.set_xlim(0, 20)
    # (b) pre-fix frozen era: S5 replay vs MCU on elevator run1 (dwell window
    # where tones are representable: firmware suppresses tone<400 Hz)
    t2, alt2, _ = streams.baro_stream(R1, 1, reference="moving_p0",
                                      seed_d2=True)
    v2 = equiv6.replay_candidate("S5_LightGateKF", t2, alt2, R1)
    tt2, vi2 = streams.mcu_tones(R1, 1 * 5 + 3)
    ax = fig.add_subplot(gs[1, :])
    m = (t2 >= 78) & (t2 <= 95)
    ax.plot(t2[m], v2[m], lw=0.8, color="#8c564b", label="Python replay "
            "(moving_p0 + seed)")
    mm = (tt2 >= 78) & (tt2 <= 95)
    ax.scatter(tt2[mm], vi2[mm], s=12, color="k", label="MCU tones", zorder=5)
    ax.set_title("Harness validation — elevator run1 sid1 S5, frozen-p0 era "
                 "dwell 78-95 s (era p95 = 1.1 mm/s). No MCU tones during "
                 "descents: firmware suppresses tone<400 Hz (implied "
                 "v < -0.22 m/s, asymmetric clamp)")
    ax.set_ylabel("v [m/s]")
    ax.legend(fontsize=7)
    # (c) DEF-011: raw altitude (absolute garbage) + relative noise scaling
    t3, alt3, _ = streams.baro_stream(ST, 0, reference="isa")
    _, alt3b, _ = streams.baro_stream(ST, 0, reference="isa_fw10")
    ax = fig.add_subplot(gs[2, 0])
    ax.plot(t3, alt3, lw=0.8, label="common-scale fixed ISA (correct)")
    ax.set_ylim(alt3.min() - 5, alt3.max() + 5)
    ax.annotate(f"firmware 10x-scale alt = {alt3b[0]:.0f} m (off scale)",
                xy=(0.03, 0.88), xycoords="axes fraction", fontsize=7.5,
                color="#d62728")
    ax.set_title("DEF-011 absolute altitude", fontsize=9)
    ax.set_ylabel("alt [m]")
    ax.set_xlabel("t [s]")
    ax.legend(fontsize=7)
    ax = fig.add_subplot(gs[2, 1])
    ax.plot(t3, alt3 - alt3[0], lw=0.7, label="common-scale d-alt")
    ax.plot(t3, alt3b - alt3b[0], lw=0.7, label="firmware-scale d-alt "
            "(velocities x1.5498)")
    ax.set_title("relative altitude / velocity scaling", fontsize=9)
    ax.set_ylabel("d-alt [m]")
    ax.set_xlabel("t [s]")
    ax.legend(fontsize=7)
    save(fig, "fig13_mcu_equivalence.png")


# ------------------------------------------------------- F14 failure modes --
def f14_failures():
    tr = load_trc(HT, 0)
    t = tr["t"]
    fig, axs = plt.subplots(2, 2, figsize=(11.5, 7.6))
    # (a) S2 freeze on toss
    ax = axs[0, 0]
    m = (t >= 140) & (t <= 175)
    if "v_ref" in tr:
        ax.plot(t[m], tr["v_ref"][m], lw=0.9, color="k", label="ref")
    if "v::S2_DualTimescale" in tr:
        ax.plot(t[m], tr["v::S2_DualTimescale"][m], lw=0.8, color="#ff7f0e",
                label="S2")
    if "v::S4_FastSlowGated" in tr:
        ax.plot(t[m], tr["v::S4_FastSlowGated"][m], lw=0.8, color="#d62728",
                label="S4")
    ax.set_title("Failure mode — stacked filters across the toss "
                 "(148.2–151.9 s)")
    ax.legend(fontsize=7)
    ax.set_ylabel("v [m/s]")
    # (b) startup flap on p0fix static
    ax = axs[0, 1]
    trs = load_trc(ST, 0)
    ts = trs["t"]
    m = ts < 8
    ax.plot(ts[m], trs["v::D01_Kalman_CV"][m], lw=0.8, color="#2ca02c",
            label="D01 replay")
    ttv, viv = streams.mcu_tones(ST, 0)
    mm = ttv < 8
    ax.scatter(ttv[mm], viv[mm], s=12, color="k", label="MCU tones")
    ax.axhline(6.67, color="r", ls="--", lw=0.6)
    ax.set_title("DEF-010 startup flap — d2 boot-seed step, tones clamp at "
                 "+6.67 m/s")
    ax.legend(fontsize=7)
    ax.set_ylabel("v [m/s]")
    # (c) S3 chatter static
    ax = axs[1, 0]
    m = (ts >= 10) & (ts <= 40)
    ax.plot(ts[m], trs["v::S3_AccelerationAwareKF"][m], lw=0.7,
            color="#d62728", label="S3")
    ax.plot(ts[m], trs["v::D01_Kalman_CV"][m], lw=0.7, color="#2ca02c",
            label="D01")
    ax.axhline(0.2, color="r", ls=":", lw=0.6)
    ax.set_title("Failure mode — S3 gate chatter vs D01 on static silence")
    ax.legend(fontsize=7)
    ax.set_ylabel("v [m/s]")
    ax.set_xlabel("t [s]")
    # (d) handtest slow blocks: FUS vs baro-only on slow sustained motion
    ax = axs[1, 1]
    m = (t >= 60) & (t <= 120)
    if "v_ref" in tr:
        ax.plot(t[m], tr["v_ref"][m], lw=0.9, color="k", label="ref")
    for n, c in (("D01_Kalman_CV", "#2ca02c"), ("FUS", "#9467bd"),
                 ("S5_LightGateKF", "#8c564b")):
        if f"v::{n}" in tr:
            ax.plot(t[m], tr[f"v::{n}"][m], lw=0.7, color=c,
                    label=n.split("_")[0])
    for (a, b) in np.atleast_2d(tr["slow_blocks"]):
        if b > 60 and a < 120:
            ax.axvspan(a, b, color="green", alpha=0.15)
    ax.set_title("Slow sustained blocks (66–69, 108–114 s) — thermalling "
                 "regime")
    ax.legend(fontsize=7)
    ax.set_ylabel("v [m/s]")
    ax.set_xlabel("t [s]")
    fig.suptitle("Failure-mode illustrations", y=0.995)
    save(fig, "fig14_failure_modes.png")


# -------------------------------------------------------- F15 rate control --
def f15_rate():
    df = pd.read_csv(RES / "66_rate_control.csv")
    fig, axs = plt.subplots(1, 3, figsize=(13.5, 4.2))
    for n, g in df.groupby("candidate"):
        gm = g.groupby("decimation")[["fs_eff_hz", "rms_med", "rise_med_s",
                                      "exit_med_s"]].median()
        c = FCOLOR.get(FAMILY.get(n), "0.4")
        axs[0].plot(gm.fs_eff_hz, gm.rms_med, "o-", ms=3, lw=0.8, color=c,
                    label=n.split("_")[0])
        axs[1].plot(gm.fs_eff_hz, gm.rise_med_s, "o-", ms=3, lw=0.8,
                    color=c)
        axs[2].plot(gm.fs_eff_hz, gm.exit_med_s, "o-", ms=3, lw=0.8,
                    color=c)
    axs[0].set_yscale("log")
    axs[0].set_ylabel("leg RMS [m/s] (log)")
    axs[1].set_ylabel("rise proxy [s]")
    axs[2].set_ylabel("exit proxy [s]")
    for ax in axs:
        ax.set_xlabel("effective sample rate [Hz]")
        ax.invert_xaxis()
    axs[0].legend(fontsize=6, ncol=2)
    fig.suptitle("Sampling-rate sensitivity control — seconds-parameterized "
                 "filters near-invariant; fixed-coefficient B02 does not "
                 "transfer across rates")
    save(fig, "fig15_rate_control.png")


# -------------------------------------------------------- F16 audio strips --
def f16_audio_strips():
    tr = load_trc(R1, 0)
    t = tr["t"]
    names = ["D01_Kalman_CV", "C03_CV_tracker", "S4_FastSlowGated",
             "S5_LightGateKF", "FUS", "C01_AlphaBeta", "B02_Butter2",
             "E06_RobustAdapt"]
    fig, axs = plt.subplots(len(names), 1, figsize=(12, 8), sharex=True)
    for ax, n in zip(axs, names):
        audio_strip(ax, t, tr[f"v::{n}"], (t[0], t[-1]),
                    FCOLOR.get(FAMILY.get(n), "0.4"))
        ax.set_yticks([])
        ax.set_ylabel(n.split("_")[0], rotation=0, labelpad=40, fontsize=7)
        ax.set_ylim(0, 1)
        for (a, b, v, _) in tr["legs"]:
            ax.axvspan(a, b, color="orange", alpha=0.12)
    axs[0].set_title("Replay virtual-audio ON episodes — elevator run 1 sid0 "
                     "(orange = travel legs)")
    axs[-1].set_xlabel("t [s]")
    save(fig, "fig16_audio_timeline_strips.png")


# ------------------------------------------------------ F17 ranking heatmap -
def f17_rankings():
    elev = pd.read_csv(RES / "61_elevator_summary.csv")
    stat = pd.read_csv(RES / "60_static.csv")
    hand = pd.read_csv(RES / "62_handtest.csv")
    r1 = elev[elev.session.str.contains("221124")]
    g = pd.DataFrame({
        "rest_rms": stat.groupby("candidate").rest_rms.median(),
        "elev_rms": r1.groupby("candidate").rms_med.median(),
        "rise": r1.groupby("candidate").rise_med_s.median(),
        "exit": r1.groupby("candidate").exit_med_s.median(),
        "dwell_false": r1.groupby("candidate").audio_dwell_false_on_s.median(),
        "onset": hand.groupby("candidate").onset_med_s.median(),
        "static_false": hand.groupby("candidate").static_false_on_per_hr.median(),
    }).replace([np.inf, -np.inf], np.nan)
    # rank-normalized composite: percentile rank per column (lower better)
    rk = g.rank(pct=True)
    comp = rk.mean(axis=1, skipna=True).sort_values()
    order = comp.index
    M = rk.loc[order].values
    fig, ax = plt.subplots(figsize=(9, 9))
    im = ax.imshow(M, aspect="auto", cmap="RdYlGn_r", vmin=0, vmax=1)
    ax.set_xticks(range(len(g.columns)))
    ax.set_xticklabels(g.columns, rotation=35, ha="right", fontsize=7)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([n.split("_")[0] for n in order], fontsize=6.5)
    for i in range(len(order)):
        for j in range(len(g.columns)):
            v = g.loc[order[i], g.columns[j]]
            if np.isfinite(v):
                ax.text(j, i, f"{v:.2g}", ha="center", va="center",
                        fontsize=5.5, color="k")
            else:
                ax.text(j, i, "n/a", ha="center", va="center", fontsize=5,
                        color="0.6")
    ax.set_title("Normalized metric ranks (green = better) + raw medians; "
                 "rows sorted by composite")
    fig.colorbar(im, ax=ax, shrink=0.5, label="percentile rank")
    save(fig, "fig17_ranking_heatmap.png")
    comp.rename("composite").to_csv(RES / "612_rank_composite.csv")
    print("  wrote 612_rank_composite.csv")


# ---------------------------------------------------------- F18 tuning ------
def f18_tuning():
    tr = pd.read_csv(RES / "67_tuning_train.csv")
    va = pd.read_csv(RES / "68_tuning_validation.csv")
    sel = pd.read_csv(RES / "69_tuning_selection.csv")
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6))
    ax = axs[0]
    fams = ["D01_Kalman_CV", "C03_CV_tracker", "S4_FastSlowGated",
            "S5_LightGateKF"]
    for fam in fams:
        s = sel[sel.family == fam].dropna(subset=["train_composite"]).sort_values("train_composite")
        ax.plot(s.train_composite, [fam] * len(s), "o", ms=4,
                color=FCOLOR.get(FAMILY.get(fam), "0.4"))
        fz = s[s.frozen]
        if len(fz):
            ax.scatter(fz.train_composite, [fam] * len(fz), marker="*", s=140,
                       color="k", zorder=5)
        for _, r in s.head(1).iterrows():
            ax.annotate(r.config, (r.train_composite, fam), fontsize=6,
                        textcoords="offset points", xytext=(4, 4))
    ax.set_xlabel("train composite (relative to frozen; lower = better)")
    ax.set_title("Selection on TRAIN only (★ = frozen as-shipped)")
    ax = axs[1]
    pairs = [("D01_Kalman_CV", "q=1.0 r=0.035", "q=0.3 r=0.035"),
             ("S4_FastSlowGated", "tau_fast=0.35", "tau_fast=0.5"),
             ("S5_LightGateKF", "q=0.3", "q=0.1")]
    for fam, fz, w in pairs:
        for split, df, mk in (("train", tr, "o"), ("val", va, "s")):
            col = "rest_rms" if "rest_rms" in df.columns else "static_rms"
            a = df[(df.family == fam) & (df.config == fz)][col].median()
            b = df[(df.family == fam) & (df.config == w)][col].median()
            if np.isfinite(a) and np.isfinite(b):
                ax.scatter([f"{fam.split('_')[0]}\n{split}"], [a],
                           color="0.55", marker=mk, s=55, label="frozen" if
                           mk == "o" and fam == pairs[0][0] else None)
                ax.scatter([f"{fam.split('_')[0]}\n{split}"], [b],
                           color="#d62728", marker=mk, s=55,
                           label="tuned" if mk == "o" and fam ==
                           pairs[0][0] else None)
    ax.set_ylabel("rest RMS [m/s]")
    ax.set_title("Frozen vs tuned on train / validation splits (rest RMS)")
    ax.legend(fontsize=7)
    fig.suptitle("Leakage-controlled tuning pass — NOT a freeze", y=1.02)
    save(fig, "fig18_tuning_train_val.png")


# --------------------------------------------------------------------- main --
def main():
    figs = [f01_overview, f02_all_traces, f03_zooms, f04_run2, f05_leg_bias,
            f06_handtest, f07_static_violins, f08_scatter_noise_onset,
            f09_scatter_on_off, f10_scatter_false_missed, f11_cpu, f12_pareto,
            f13_equiv, f14_failures, f15_rate, f16_audio_strips,
            f17_rankings, f18_tuning]
    for f in figs:
        try:
            print(f"[{f.__name__}]", flush=True)
            f()
        except Exception:
            print(f"  !! {f.__name__} FAILED")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
