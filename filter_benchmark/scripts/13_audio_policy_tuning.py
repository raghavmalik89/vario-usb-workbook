"""Script 13 — Phase 4 WP-B: audio-policy tuning on TRAINING data only,
then frozen evaluation on VALIDATION.

Separation of concerns (spec): estimator configs were frozen in
config/phase4.json BEFORE this script; this script tunes ONLY the audio
policy per candidate, on the training split, under the selection rule fixed
in config/phase4.json (audio_policy_search_space.selection_rule). Chosen
policies are written back to config/phase4.json (tuned_policies) and frozen;
validation numbers are reported, never used for selection.

Grid: lift_on {0.15,0.20,0.25,0.30} x lift_off {0.03,0.05,0.08,0.10} x
hold_s {0,0.2,0.4} x min_on_s {0,0.15} = 96 policies per candidate.
Estimator replays are computed ONCE per stream (p4_eval); only the cheap
audio state machine re-runs per policy.

Outputs:
  results/13_policy_search.csv      every (candidate, policy) training score
  results/13_policy_comparison.csv  common vs tuned (+safety) on BOTH splits
  config/phase4.json                gains 'tuned_policies' (frozen)
"""
from pathlib import Path
import itertools
import json
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import ROOT, derive_events, streams  # noqa: E402
import p4_eval as P4E  # noqa: E402

NAMES = ["C03_CV_tracker", "D01_Kalman_CV", "S1_RobustAdaptiveKF",
         "S1P_PersistenceKF", "S4_FastSlowGated", "S5_LightGateKF"]


def collect_streams(split):
    """Replay every estimator ONCE per stream; cache (t, v), events, flags."""
    cache = {}
    for st in streams(split):
        events = v_ref = None
        if st["kind"] == "motion":
            events, v_ref = derive_events(st["t"], st["alt"])
        for name in NAMES:
            f, t, v = P4E.run_estimator(name, st)
            flags = (P4E.fault_flags_for(name, st)
                     if st["kind"] == "static" else None)
            cache[(name, st["session"], st["sid"])] = dict(
                st=st, t=t, v=v, events=events, v_ref=v_ref, flags=flags)
        print(f"  {split}: {st['session']} sid{st['sid']} replayed",
              flush=True)
    return cache


def policy_metrics(cache, policy):
    """Aggregate corrected audio metrics for one policy across the cache."""
    stat_rates, lift_rows = [], []
    for (name, sess, sid), c in cache.items():
        st = c["st"]
        if st["kind"] == "static":
            r = P4E.statics_audio_from_v(name, st, st.get("split", ""),
                                         c["t"], c["v"], policy,
                                         fault_flags=c["flags"])
            stat_rates.append(r["on_per_hour"])
        else:
            rows = P4E.event_rows_from_v(name, st, "", c["t"], c["v"],
                                         c["events"], c["v_ref"], policy)
            lift_rows.extend([r for r in rows if r["kind"] == "lift"])
    import pandas as pd
    lf = pd.DataFrame(lift_rows)
    miss = lf["missed"].mean() if len(lf) else np.nan
    od = lf["on_delay_s"].dropna()
    ex = lf["exit_delay_s"].dropna()
    return dict(false_on_per_hr=float(np.median(stat_rates)) if stat_rates
                else np.nan,
                missed_lift_rate=round(float(miss), 4) if miss == miss else np.nan,
                on_delay_med=round(float(od.median()), 3) if len(od) else np.nan,
                exit_med=round(float(ex.median()), 3) if len(ex) else np.nan,
                n_censored=int(lf["censored"].sum()) if len(lf) else 0)


def main():
    train = collect_streams("training")
    # tag splits for reporting
    for c in train.values():
        c["st"] = dict(c["st"], split="training")

    grid = P4E.P4["audio_policy_search_space"]
    policies = [dict(lift_on=lo, lift_off=lf_, hold_s=h, min_on_s=m)
                for lo, lf_, h, m in itertools.product(
                    grid["lift_on"], grid["lift_off"], grid["hold_s"],
                    grid["min_on_s"])]

    search_rows = []
    chosen = {}
    for name in NAMES:
        sub = {k: v for k, v in train.items() if k[0] == name}
        # common-policy baseline on training (constraint reference)
        base = policy_metrics(sub, P4E.P4["common_audio_policy"])
        scored = []
        for pol in policies:
            m = policy_metrics(sub, pol)
            feasible = (m["missed_lift_rate"] <= base["missed_lift_rate"] + 1e-9
                        and m["on_delay_med"] <= base["on_delay_med"] + 0.5
                        and (m["exit_med"] == m["exit_med"])
                        and m["exit_med"] <= 8.0)
            scored.append((pol, m, feasible))
            search_rows.append(dict(
                filter=name, feasible=int(feasible),
                false_on_per_hr=m["false_on_per_hr"],
                missed_lift_rate=m["missed_lift_rate"],
                on_delay_med=m["on_delay_med"], exit_med=m["exit_med"],
                n_censored=m["n_censored"], **pol))
        feas = [s for s in scored if s[2]]
        if feas:
            best = min(feas, key=lambda s: s[1]["false_on_per_hr"])
        else:
            best = min(scored, key=lambda s: s[1]["false_on_per_hr"])
            print(f"  WARNING {name}: no feasible policy; took lowest "
                  f"false-rate infeasible option", flush=True)
        chosen[name] = dict(best[0])
        chosen[name]["safety"] = dict(P4E.P4["phase4_audio_baseline"])
        print(f"  {name}: baseline fph={base['false_on_per_hr']:.1f} "
              f"missed={base['missed_lift_rate']:.3f} -> chosen {best[0]} "
              f"fph={best[1]['false_on_per_hr']:.1f}", flush=True)
    P4E.write_csv(search_rows, ROOT / "results" / "13_policy_search.csv")

    # freeze chosen policies into phase4.json (selection used TRAINING only)
    cfg = json.loads((ROOT / "config" / "phase4.json").read_text("utf-8"))
    cfg["tuned_policies"] = chosen
    cfg["tuned_policies_comment"] = (
        "chosen on the TRAINING split by the fixed selection rule; frozen "
        "before validation evaluation; validation numbers in "
        "results/13_policy_comparison.csv were NOT used for selection")
    (ROOT / "config" / "phase4.json").write_text(
        json.dumps(cfg, indent=2), "utf-8")

    # frozen evaluation on BOTH splits: common vs tuned (+safety)
    val = collect_streams("validation")
    for c in val.values():
        c["st"] = dict(c["st"], split="validation")

    def eval_split(cache, split):
        rows = []
        for name in NAMES:
            sub = {k: v for k, v in cache.items() if k[0] == name}
            tuned = {k: v for k, v in chosen[name].items() if k != "safety"}
            safe = {"max_on_s": chosen[name]["safety"]["max_on_s"],
                    "fault_veto": chosen[name]["safety"]["fault_veto"]}
            for label, pol in (("common", P4E.P4["common_audio_policy"]),
                               ("tuned", tuned),
                               ("tuned+safety", {**tuned, **safe})):
                m = policy_metrics(sub, pol)
                rows.append(dict(filter=name, variant=label, split=split,
                                 **m))
        return rows

    rows = eval_split(train, "training") + eval_split(val, "validation")
    P4E.write_csv(rows, ROOT / "results" / "13_policy_comparison.csv")
    print(f"search rows {len(search_rows)}, comparison rows {len(rows)}")


if __name__ == "__main__":
    main()
