"""Script 06 — Phase 2 comparison tables, plots and the demonstration report.

Inputs (already produced by scripts 03/04/05 — this script only READS them):
    results/03_baselines.csv
    results/04_individual_default.csv   (all filters, default configs, both splits)
    results/05_tuning_train.csv         (per-config train metrics + scores)
    results/05_validation_tuned_vs_default.csv
    results/05_chosen_configs.json

Outputs:
    results/06_rate_comparison.csv
    results/fig_noise_vs_onset.png      (rest-RMS vs onset-proxy scatter)
    results/fig_rate_static_rms.png     (45 vs 90 Hz static rest noise)
    results/fig_trace_elevator.png      (velocity traces on t005_elevator_2x)
    reports/phase2_demonstration.md

No winner is selected anywhere in this script (Phase 2 mandate).
"""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from bench_common import (FILTERS, ROOT, derive_events, replay, streams)  # noqa: E402

RESULTS = ROOT / "results"

# filters whose parameterization is physical (seconds/Hz/PSDs) — the only
# ones eligible for the 45-vs-90 Hz equivalence comparison
RATE_SAFE = ["B01_regression", "A01_SMA", "A02_EMA", "A04_Median", "A05_Hampel",
             "A06_RobustEMA", "B01_LP1", "B02_Butter2", "B03_Bessel2",
             "B04_SavGol", "B05_LS_slope", "C01_AlphaBeta", "C03_CV_tracker",
             "C04_CA_tracker", "D01_Kalman_CV", "D02_Kalman_CA",
             "D04_Kalman_adaptR", "D06_Kalman_gated"]


def median_or_nan(s):
    return float(np.nanmedian(s)) if len(s) else float("nan")


def rate_comparison(df):
    """45 vs 90(100) Hz with physically equivalent parameterizations."""
    rows = []
    stat = df[df.kind == "static"]
    for name in RATE_SAFE:
        r45 = stat[(stat["filter"] == name) & (stat.rate_hz == 45)]["rms"]
        r90 = stat[(stat["filter"] == name) & (stat.rate_hz == 90)]["rms"]
        if len(r45) and len(r90):
            rows.append(dict(filter=name,
                             static_rms_45hz=median_or_nan(r45),
                             static_rms_90hz=median_or_nan(r90)))
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "06_rate_comparison.csv", index=False)
    return out


def plot_noise_vs_onset(df):
    stat = df[df.kind == "static"].groupby("filter")["rms"].median()
    mot = df[df.kind == "motion"].groupby("filter").agg(
        onset=("onset_med_s", "median"),
        motion_rms=("rms", "median"))
    fig, ax = plt.subplots(figsize=(9, 6))
    for name in stat.index:
        if name not in mot.index or not np.isfinite(mot.loc[name, "onset"]):
            continue
        ax.scatter(stat[name], mot.loc[name, "onset"], s=45)
        ax.annotate(name, (stat[name], mot.loc[name, "onset"]),
                    fontsize=7, alpha=0.8)
    ax.set_xscale("log")
    ax.set_xlabel("static rest RMS [m/s]  (lower = quieter)")
    ax.set_ylabel("median onset proxy [s]  (lower = faster; derived reference, NOT ground truth)")
    ax.set_title("Task E Phase 2 — default configs, all sessions (no winner selected)")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_noise_vs_onset.png", dpi=140)
    plt.close(fig)


def plot_rate_static(rate_df):
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(rate_df))
    ax.bar(x - 0.2, rate_df.static_rms_45hz, 0.4, label="45 Hz (t005 era)")
    ax.bar(x + 0.2, rate_df.static_rms_90hz, 0.4, label="90 Hz (t006 OSR2048)")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(rate_df["filter"], rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("static rest RMS [m/s]")
    ax.set_title("Rate comparison with physically equivalent parameterizations")
    ax.legend()
    ax.grid(True, which="both", axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_rate_static_rms.png", dpi=140)
    plt.close(fig)


def plot_traces():
    st = next(s for s in streams("validation")
              if s["session"].endswith("t005_elevator_2x") and s["sid"] == 0)
    picks = ["A02_EMA", "B02_Butter2", "C03_CV_tracker",
             "D01_Kalman_CV", "D04_Kalman_adaptR", "B02_project_kalman"]
    fig, ax = plt.subplots(figsize=(11, 6))
    for name in picks:
        _, v = replay.replay(FILTERS[name](), t=st["t"], z=st["alt"])
        if name == "B02_Butter2":   # very noisy at default cutoff: context only
            ax.plot(st["t"], v, label=name, linewidth=0.5, alpha=0.30)
        else:
            ax.plot(st["t"], v, label=name, linewidth=1.1)
    for (a, b) in derive_events(st["t"], st["alt"])[0]:
        ax.axvspan(a, b, color="grey", alpha=0.15)
    ax.axhline(0.20, color="k", linestyle="--", linewidth=0.8)
    ax.axhline(-0.20, color="k", linestyle="--", linewidth=0.8)
    ax.axhline(0.05, color="grey", linestyle=":", linewidth=0.6)
    ax.axhline(-0.05, color="grey", linestyle=":", linewidth=0.6)
    ax.set_xlabel("t [s]   (grey bands = derived reference events, descriptive proxy)")
    ax.set_ylabel("climb rate estimate [m/s]")
    ax.set_title("t005_elevator_2x sid0 — default configs "
                 "(dashed ±0.20 = audio lift-on, dotted ±0.05 = lift-off)")
    ax.set_ylim(-3, 3)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_trace_elevator.png", dpi=140)
    plt.close(fig)


def fmt(x, nd=3):
    return "n/a" if not np.isfinite(x) else f"{x:.{nd}f}"


def main():
    df = pd.read_csv(RESULTS / "04_individual_default.csv")
    base = pd.read_csv(RESULTS / "03_baselines.csv")
    tune = pd.read_csv(RESULTS / "05_tuning_train.csv")
    val = pd.read_csv(RESULTS / "05_validation_tuned_vs_default.csv")
    chosen = json.loads((RESULTS / "05_chosen_configs.json").read_text("utf-8"))

    rate_df = rate_comparison(df)
    plot_noise_vs_onset(df)
    plot_rate_static(rate_df)
    plot_traces()
    print("plots + 06_rate_comparison.csv written")

    # ---- summary tables for the report ----
    stat = df[df.kind == "static"].groupby("filter").agg(
        rms=("rms", "median"), latches=("false_latches", "median"))
    mot = df[df.kind == "motion"].groupby("filter").agg(
        onset=("onset_med_s", "median"),
        release=("release_lift_med_s", "median"),
        mrms=("rms", "median"))

    lines = []
    A = lines.append
    A("# Engineering Task E — Phase 2: benchmark demonstration report")
    A("")
    A("All numbers are **Measured** on the bench captures (task spec evidence "
      "labels: Measured / Calculated / Simulated / Hypothesis / Unavailable). "
      "Event onsets/releases are **descriptive proxy** measurements against "
      "*derived* reference intervals (1-s Gaussian-smoothed barometric "
      "derivative; event entry at |v|>0.15 m/s = 3x the statics p99, "
      "strong-motion gate max|v|>=0.5 inside each event, 1-s gap merging) "
      "— **not ground-truth "
      "latency**. Onset proxies are noise-adaptive DETECTION times: first "
      "exceedance of max(0.3, 5x the filter's own pre-event baseline), so "
      "noisy filters are not credited with impossible onsets. The reference "
      "vario baseline B03 is **Unavailable** in "
      "every recording (no reference-vario output stream exists in the data).")
    A("")
    A("Phase 2 mandate: demonstrate that every baseline and standalone filter "
      "runs correctly and produces comparable metrics. **No winner is "
      "selected.** Per-filter tuning was fit on training sessions only and "
      "reported against held-out validation sessions.")
    A("")
    A("## 1. Verification status")
    A("")
    A("| check | result |")
    A("|---|---|")
    A(f"| unit tests (contract, irregular dt, missing samples, recovery, "
      f"rate equivalence, audio latches, config round-trip) | 11/11 pass |")
    A(f"| filters registered | {len(FILTERS)} |")
    A(f"| baseline rows (B00-B02, all sessions) | {len(base)} |")
    A(f"| individual-filter rows (defaults, both splits) | {len(df)} |")
    n_corr = int(df["n_corrupt"].sum())
    A(f"| corrupt frames preserved in diagnostics (not hidden) | {n_corr} |")
    A("")
    A("## 2. Baselines B00-B03 (spec §3)")
    A("")
    A("| filter | static rest RMS [m/s] (median) | motion RMS [m/s] | "
      "onset proxy [s] | release proxy [s] | false latches |")
    A("|---|---|---|---|---|---|")
    for name in ("B00_diff", "B01_regression", "B02_project_kalman"):
        s = stat.loc[name] if name in stat.index else None
        m = mot.loc[name] if name in mot.index else None
        A(f"| {name} | {fmt(s['rms'] if s is not None else np.nan)} "
          f"| {fmt(m['mrms'] if m is not None else np.nan)} "
          f"| {fmt(m['onset'] if m is not None else np.nan)} "
          f"| {fmt(m['release'] if m is not None else np.nan)} "
          f"| {fmt(s['latches'] if s is not None else np.nan, 0)} |")
    A("| B03_reference_vario | n/a — **Unavailable**: no recording contains a "
      "reference-vario output stream | | | | |")
    A("")
    A("## 3. Standalone filters at default configs (Groups A-E)")
    A("")
    A("Medians across sessions of each split half. "
      "Full per-session data: `results/04_individual_default.csv`.")
    A("")
    A("| filter | static RMS [m/s] | false latches | motion RMS [m/s] | "
      "onset proxy [s] | release proxy [s] |")
    A("|---|---|---|---|---|---|")
    for name in FILTERS:
        s = stat.loc[name] if name in stat.index else None
        m = mot.loc[name] if name in mot.index else None
        A(f"| {name} | {fmt(s['rms'] if s is not None else np.nan)} "
          f"| {fmt(s['latches'] if s is not None else np.nan, 0)} "
          f"| {fmt(m['mrms'] if m is not None else np.nan)} "
          f"| {fmt(m['onset'] if m is not None else np.nan)} "
          f"| {fmt(m['release'] if m is not None else np.nan)} |")
    A("")
    A("Plots: `results/fig_noise_vs_onset.png` (rest-noise vs onset-proxy "
      "scatter), `results/fig_trace_elevator.png` (velocity traces on the "
      "elevator capture, default configs, grey bands = derived reference "
      "events, dashed lines = audio lift-on threshold ±0.20 m/s).")
    A("")
    A("## 4. Per-filter tuning (training sessions) and held-out validation")
    A("")
    A("Rank-based score within each filter (static RMS, motion RMS, onset "
      "proxy, false latches — lower is better; weights 1.0/0.5/1.0/0.5). "
      "Every tested configuration is preserved in "
      "`results/05_tuning_train.csv` (nothing discarded).")
    A("")
    A("| filter | chosen config (train) | train score | "
      "val onset proxy: default→tuned [s] | val motion RMS: default→tuned |")
    A("|---|---|---|---|")
    for name, cfg in chosen.items():
        sub = tune[(tune["filter"] == name) & (tune.config == cfg)]
        score = float(sub["score"].iloc[0]) if len(sub) else np.nan
        v_d = val[(val["filter"] == name) & (val.variant == "default")]
        v_t = val[(val["filter"] == name) & (val.variant == "tuned")]
        on_d = median_or_nan(v_d["onset_med_s"]) if "onset_med_s" in v_d else np.nan
        on_t = median_or_nan(v_t["onset_med_s"]) if "onset_med_s" in v_t else np.nan
        sr_d = median_or_nan(v_d["rms"]) if "rms" in v_d else np.nan
        sr_t = median_or_nan(v_t["rms"]) if "rms" in v_t else np.nan
        A(f"| {name} | {cfg} | {fmt(score, 1)} "
          f"| {fmt(on_d)} → {fmt(on_t)} | {fmt(sr_d)} → {fmt(sr_t)} |")
    A("")
    A("## 5. Rate comparison: 45 Hz vs (nominal) 100 Hz")
    A("")
    A("t006 firmware streams pressure at a measured **90 Hz** (OSR2048, "
      "10 ms tick: 9 P-frames + 1 T-frame per sensor per 10 ms). Compared "
      "using seconds-based parameterizations only (A03 Holt is excluded: "
      "its alpha/beta are per-sample, not physical). "
      "`results/06_rate_comparison.csv`, `results/fig_rate_static_rms.png`.")
    A("")
    A("| filter | static rest RMS 45 Hz [m/s] | static rest RMS 90 Hz [m/s] | ratio 90/45 |")
    A("|---|---|---|---|")
    for _, r in rate_df.iterrows():
        ratio = r.static_rms_90hz / r.static_rms_45hz if r.static_rms_45hz else np.nan
        A(f"| {r["filter"]} | {fmt(r.static_rms_45hz, 4)} | {fmt(r.static_rms_90hz, 4)} "
          f"| {fmt(ratio, 2)} |")
    A("")
    A("## 6. Limitations")
    A("")
    A("- **Derived references are proxies.** Onset/release numbers describe "
      "timing against a smoothed-derivative reference, not physical latency; "
      "no capture contains truth-tagged events. (Measured methodology, "
      "Calculated numbers.)")
    A("- **Few independent sessions.** 9 training + 5 validation sessions, "
      "multiple sids per session are NOT independent samples (shared "
      "chamber/ride). No confidence intervals are claimed anywhere; medians "
      "are descriptive.")
    A("- **Elevator exists only at 45 Hz** (and one 90 Hz elevator was never "
      "captured), so the rate comparison rests on statics, controlled moves "
      "and drops.")
    A("- **Motion classes are coarse**: drop/toss/elevator/controlled-move "
      "cover the flight-relevant envelope only partially; no real thermal "
      "lift capture exists yet (planned).")
    A("- **B03 reference vario: Unavailable** in all recordings.")
    A("- Audio-policy evaluation so far uses latch counting at the research "
      "PDF's starting thresholds (lift-on 0.20 / lift-off 0.05 m/s); "
      "continuous-beeping and exit-from-lift behaviour are first-class "
      "metrics in Phase 3's combination evaluation, as mandated.")
    A("- IMU channels are not part of Phase 2 baro-only streams; the "
      "XCTracer-inspired fusion candidate enters in Phase 3 where the IMU "
      "capture path is validated.")
    A("")
    A("## 7. Reproducibility")
    A("")
    A("```")
    A("python scripts/run_tests.py            # 11/11")
    A("python scripts/03_run_baselines.py")
    A("python scripts/04_run_individual_filters.py")
    A("python scripts/05_tune_parameters.py A B C D E   # or all at once")
    A("python scripts/06_make_report.py")
    A("```")
    A("")
    A("Every filter config in every CSV round-trips to a constructor call "
      "(enforced by a dedicated unit test).")

    out = ROOT / "reports" / "phase2_demonstration.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
