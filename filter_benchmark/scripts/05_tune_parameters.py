"""Script 05 — per-filter parameter search on TRAINING sessions only, then
evaluation of the chosen config on the HELD-OUT validation split.

Mandate compliance:
- every knob is seconds-based / physical where the filter allows it, so a
  configuration means the same thing at 45 Hz and 90 Hz;
- ALL tested configurations are saved with their metrics (nothing hidden);
- scoring is rank-based within each filter (no unit mixing, no winner
  selection across filters — Phase 2 only demonstrates per-filter tuning);
- validation numbers come from streams no tuning saw.

Usage:
    python scripts/05_tune_parameters.py            # all groups
    python scripts/05_tune_parameters.py A B        # only groups A and B
"""
import json
from pathlib import Path
import itertools
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import (FILTERS, ROOT, derive_events,  # noqa: E402
                          replay, run_filter_on_stream, streams, write_csv)

# ---------------------------------------------------------------- grids
# All values are physical (seconds, Hz, PSDs) — rate-independent meaning.
GRIDS = {
    "A01_SMA":        [dict(window_s=w) for w in (0.5, 1.0, 2.0, 3.0)],
    "A02_EMA":        [dict(tau_s=t) for t in (0.3, 0.6, 1.0, 1.6)],
    "A03_Holt":       [dict(alpha=a, beta=b) for a, b in
                       ((0.2, 0.05), (0.35, 0.1), (0.5, 0.15), (0.7, 0.2))],
    "A04_Median":     [dict(window_s=w) for w in (0.5, 1.0, 2.0, 3.0)],
    "A05_Hampel":     [dict(window_s=w, n_sigma=s) for w, s in
                       itertools.product((1.0, 2.0), (2.5, 3.5))],
    "A06_RobustEMA":  [dict(window_s=w, tau_s=t) for w, t in
                       ((1.0, 0.5), (2.0, 0.5), (2.0, 1.0), (3.0, 1.0))],
    "B01_LP1":        [dict(tau_s=t) for t in (0.3, 0.6, 1.0, 1.6)],
    "B02_Butter2":    [dict(cutoff_hz=f) for f in (0.2, 0.35, 0.5, 0.8)],
    "B03_Bessel2":    [dict(cutoff_hz=f) for f in (0.2, 0.35, 0.5, 0.8)],
    "B04_SavGol":     [dict(window_s=w) for w in (0.7, 1.0, 1.6, 2.5)],
    "B05_LS_slope":   [dict(window_s=w) for w in (0.7, 1.0, 1.6, 2.5)],
    "B01_regression": [dict(window_s=w) for w in (0.7, 1.0, 1.5, 2.0)],
    "C01_AlphaBeta":  [dict(tau_s=t) for t in (0.3, 0.6, 1.0, 1.6)],
    "C02_AlphaBetaGamma": [dict(tau_s=t) for t in (0.4, 0.8, 1.2, 1.8)],
    "C03_CV_tracker": [dict(q=q, r=r) for q, r in
                       itertools.product((0.3, 1.0, 3.0), (0.012, 0.035, 0.1))],
    "C04_CA_tracker": [dict(q=q, r=r) for q, r in
                       itertools.product((0.3, 1.0, 3.0), (0.012, 0.035, 0.1))],
    "D01_Kalman_CV":  [dict(q=q, r=r) for q, r in
                       itertools.product((0.3, 1.0, 3.0), (0.012, 0.035, 0.1))],
    "D02_Kalman_CA":  [dict(q=q, r=r) for q, r in
                       itertools.product((0.3, 1.0, 3.0), (0.012, 0.035, 0.1))],
    "D04_Kalman_adaptR": [dict(q=q, window_s=w) for q, w in
                          itertools.product((0.5, 1.0, 2.0), (3.0, 6.0))],
    "D05_Kalman_adaptQ": [dict(q=q, window_s=w) for q, w in
                          itertools.product((0.5, 1.0, 2.0), (2.0, 4.0))],
    "D06_Kalman_gated":  [dict(gate_sigma=g) for g in (2.5, 3.5, 5.0)],
    "E01_OneEuro":    [dict(min_cutoff_hz=f, beta=b) for f, b in
                       itertools.product((0.3, 0.5, 0.8), (0.5, 1.5))],
    "E02_AdaptiveEMA": [dict(tau0_s=t, v0=v) for t, v in
                        ((0.8, 0.3), (0.8, 0.7), (1.5, 0.3), (1.5, 0.7))],
    "E03_FastSlow":   [dict(tau_fast_s=tf, tau_slow_s=ts) for tf, ts in
                       itertools.product((0.1, 0.2, 0.35), (1.0, 2.0))],
    "E04_InnovationBlend": [dict(tau_fast_s=tf, tau_slow_s=ts) for tf, ts in
                            itertools.product((0.1, 0.2, 0.35), (1.0, 2.0))],
    "E05_ChangeDetect": [dict(tau_fast_s=tf, tau_slow_s=ts) for tf, ts in
                         itertools.product((0.1, 0.2, 0.35), (1.0, 2.0))],
    "E06_RobustAdapt": [dict(n_sigma=s, q=q) for s, q in
                        itertools.product((2.5, 3.5), (0.5, 1.5))],
}
# frozen legacy / trivial baselines: not tuned (B00 has no knobs, B02_project
# is the frozen legacy estimator reproduced from analysis/04_filter_replay.py)

GROUP_OF = {n: n[0] for n in GRIDS}


def write_csv_merged(rows, path, names):
    """Write rows to CSV, replacing any existing rows for the same filters
    (so per-group invocations accumulate instead of overwriting)."""
    path = Path(path)
    if path.exists():
        old = pd.read_csv(path)
        old = old[~old["filter"].isin(names)]
        rows = pd.concat([old, pd.DataFrame(rows)],
                         ignore_index=True).to_dict("records")
    write_csv(rows, path)


def rank_score(rows, keys_weights):
    """Average of per-metric ranks across configs of ONE filter.
    keys_weights: [(metric_key, weight, ascending)]"""
    score = np.zeros(len(rows))
    for key, w, asc in keys_weights:
        vals = np.array([r[key] for r in rows], dtype=float)
        ok = np.isfinite(vals)
        order = np.argsort(np.where(ok, vals, np.inf if asc else -np.inf),
                           kind="stable")
        ranks = np.empty(len(rows))
        ranks[order] = np.arange(1, len(rows) + 1)
        score = score + w * ranks
    return score / sum(w for _, w, _ in keys_weights)


def main():
    groups = sys.argv[1:] or sorted({GROUP_OF[n] for n in GRIDS})
    names = [n for n in GRIDS if GROUP_OF[n] in groups]
    print(f"tuning {len(names)} filters, groups {groups}")

    train = list(streams("training"))
    # precompute derived events once per motion stream
    for st in train:
        if st["kind"] == "motion":
            st["events"], st["v_ref"] = derive_events(st["t"], st["alt"])

    tune_rows, chosen = [], {}
    for name in names:
        for ov in GRIDS[name]:
            cfg_rows = []
            for st in train:
                if st["kind"] == "motion":
                    f = FILTERS[name](**ov)
                    t, v = replay.replay(f, t=st["t"], z=st["alt"])
                    import metrics as M
                    em = M.event_metrics(t, v, st["v_ref"], st["events"])
                    sm = M.stationary_metrics(v, t)
                    cfg_rows.append(dict(
                        filter=name, config=f._config_repr(),
                        session=st["session"], sid=st["sid"],
                        rate_hz=st["rate"], split="training",
                        static_rms=np.nan, motion_rms=float(np.sqrt(np.mean(v**2))),
                        onset_med_s=em["onset_med_s"],
                        release_lift_med_s=em["release_lift_med_s"],
                        false_latches=sm["false_latches"]))
                else:
                    r = run_filter_on_stream(name, ov, st)
                    cfg_rows.append(dict(
                        filter=name, config=r["config"], session=st["session"],
                        sid=st["sid"], rate_hz=st["rate"], split="training",
                        static_rms=r["rms"], motion_rms=np.nan,
                        onset_med_s=np.nan, release_lift_med_s=np.nan,
                        false_latches=r["false_latches"]))
            # aggregate per config (median across streams of each metric)
            agg = dict(filter=name,
                       config=cfg_rows[0]["config"], split="training")
            for key in ("static_rms", "motion_rms", "onset_med_s",
                        "release_lift_med_s", "false_latches"):
                vals = [r[key] for r in cfg_rows
                        if np.isfinite(r[key]) or key == "false_latches"]
                nums = [x for x in vals
                        if x == x] if key != "false_latches" else vals
                agg[key] = float(np.median(nums)) if nums else np.nan
            tune_rows.append(agg)
        # rank within this filter's configs
        cfg_names = [r["config"] for r in tune_rows if r["filter"] == name]
        sub = [r for r in tune_rows if r["filter"] == name]
        sc = rank_score(sub, [("static_rms", 1.0, True),
                              ("motion_rms", 0.5, True),
                              ("onset_med_s", 1.0, True),
                              ("false_latches", 0.5, True)])
        for r, s in zip(sub, sc):
            r["score"] = float(s)
        best = min(sub, key=lambda r: r["score"])
        chosen[name] = best["config"]
        print(f"  {name}: {len(sub)} configs, best={best['config']} "
              f"(score {best['score']:.1f})", flush=True)

    write_csv_merged(tune_rows, ROOT / "results" / "05_tuning_train.csv", names)

    # held-out validation: default config vs chosen config
    def parse(cfgstr):
        """'q=1.0,r=0.035' -> {q: 1.0, r: 0.035} (grid values are numeric)."""
        if not cfgstr:
            return {}
        return {k.strip(): float(v) for k, v in
                (pair.split("=") for pair in cfgstr.split(","))}

    val_rows = []
    for st in streams("validation"):
        for name in names:
            for tag, cfgstr in (("default", None), ("tuned", chosen[name])):
                r = run_filter_on_stream(name, parse(cfgstr), st)
                r["variant"] = tag
                val_rows.append(r)
        print(f"  validation: {st['session']} sid{st['sid']} done", flush=True)
    write_csv_merged(val_rows, ROOT / "results" / "05_validation_tuned_vs_default.csv",
                     names)

    cfg_path = ROOT / "results" / "05_chosen_configs.json"
    all_chosen = {}
    if cfg_path.exists():
        all_chosen = json.loads(cfg_path.read_text(encoding="utf-8"))
    all_chosen.update(chosen)
    cfg_path.write_text(json.dumps(all_chosen, indent=2), encoding="utf-8")
    print("wrote 05_chosen_configs.json")


if __name__ == "__main__":
    main()
