"""Script 12 — Phase 4 WP-B: estimator comparison under the COMMON audio
policy, on training AND validation splits.

Candidates: references C03 / D01 / S1 (frozen Phase-3 configs) and the
Phase-4 candidates S1P / S4 / S5 (frozen design configs from
config/phase4.json). S2/S3 are NOT re-run here — their Phase-3 frozen
defects are recorded and retained as references (WP-A corrected accounting
already covers them in results/11_*).

Outputs:
  results/12_estimator_streams.csv   per-stream estimator metrics (both splits)
  results/12_estimator_summary.csv   session-level aggregates per split
  results/12_audio_common_policy.csv corrected event accounting @ common policy
  results/12_cpu.csv                 CPU cost, same methodology as script 09
"""
from pathlib import Path
import json
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import ROOT, derive_events, metrics, streams  # noqa: E402
import p4_eval as P4E  # noqa: E402

NAMES = ["C03_CV_tracker", "D01_Kalman_CV", "S1_RobustAdaptiveKF",
         "S1P_PersistenceKF", "S4_FastSlowGated", "S5_LightGateKF"]


def main():
    est_rows, ev_rows = [], []
    for split in ("training", "validation"):
        for st in streams(split):
            events = v_ref = None
            if st["kind"] == "motion":
                events, v_ref = derive_events(st["t"], st["alt"])
            for name in NAMES:
                f, t, v = P4E.run_estimator(name, st)
                # estimator metrics (same machinery as Phase 2/3)
                row = dict(filter=name,
                           config=f._config_repr(), session=st["session"],
                           sid=st["sid"], kind=st["kind"], rate_hz=st["rate"],
                           split=split,
                           n_corrupt=st["diag"].n_corrupt,
                           n_seq_gaps=st["diag"].n_seq_gaps)
                if st["kind"] == "static":
                    row.update(metrics.stationary_metrics(v, t))
                else:
                    row["n_events"] = len(events)
                    row.update(metrics.event_metrics(t, v, v_ref, events))
                    row["rms"] = float(np.sqrt(np.mean(v ** 2)))
                est_rows.append(row)
                # corrected audio accounting under the COMMON policy
                if st["kind"] == "motion":
                    ev_rows.extend(P4E.event_rows_from_v(
                        name, st, split, t, v, events, v_ref,
                        P4E.P4["common_audio_policy"]))
            print(f"  {split}: {st['session']} sid{st['sid']} done",
                  flush=True)
    P4E.write_csv(est_rows, ROOT / "results" / "12_estimator_streams.csv")
    P4E.write_csv(ev_rows, ROOT / "results" / "12_audio_common_policy.csv")

    # session-level aggregation (per-session mean across sids, then median
    # across sessions — the documented Phase 3 aggregation, kept identical)
    import pandas as pd
    df = pd.DataFrame(est_rows)

    def session_level(metric, kind):
        d = df[(df.kind == kind)]
        per = d.groupby(["split", "session", "filter"])[metric].mean()
        out = {}
        for split in ("training", "validation"):
            try:
                out[split] = per[split].groupby("filter").median()
            except KeyError:
                out[split] = pd.Series(dtype=float)
        return out

    summ = []
    for n in NAMES:
        r = dict(filter=n)
        for metric, kind, key in (("rms", "static", "static_rest_rms"),
                                  ("onset_med_s", "motion", "onset_proxy"),
                                  ("release_lift_med_s", "motion",
                                   "release_proxy")):
            sl = session_level(metric, kind)
            for split in ("training", "validation"):
                r[f"{key}_{split}"] = (round(float(sl[split].get(n, np.nan)), 4)
                                       if n in sl[split].index else np.nan)
        summ.append(r)
    P4E.write_csv(summ, ROOT / "results" / "12_estimator_summary.csv")

    # CPU cost — identical methodology to script 09 (clean sigma=0.25 m
    # stream, 3 replays, median, relative to D01)
    rng = np.random.default_rng(7)
    t = np.arange(0, 60.0, 0.01)
    z = rng.normal(0, 0.25, len(t))
    cpu_rows = []
    for name in NAMES:
        ts = []
        for _ in range(3):
            f = P4E.make_estimator(name)
            t0 = time.perf_counter()
            for i in range(len(t)):
                f.update(float(z[i]), float(t[i]))
            ts.append((time.perf_counter() - t0) / len(t) * 1e6)
        cpu_rows.append(dict(filter=name,
                             cpu_us_per_sample=round(float(np.median(ts)), 2)))
    d01 = next(r["cpu_us_per_sample"] for r in cpu_rows
               if r["filter"] == "D01_Kalman_CV")
    for r in cpu_rows:
        r["rel_to_D01"] = round(r["cpu_us_per_sample"] / d01, 2)
    P4E.write_csv(cpu_rows, ROOT / "results" / "12_cpu.csv")
    print(f"estimator rows {len(est_rows)}, event rows {len(ev_rows)}, "
          f"cpu rows {len(cpu_rows)}")


if __name__ == "__main__":
    main()
