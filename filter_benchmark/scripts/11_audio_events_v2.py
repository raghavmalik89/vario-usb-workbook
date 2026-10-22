"""Script 11 — Phase 4 WP-A: corrected audio-event evaluation.

Fixes the Phase 3 accounting defects and adds the missing analyses:
  1. Event-type separation: positive lift / sink / transient / weak events
     (classified from the DERIVED reference stream — still a proxy).
  2. Correct ON/OFF accounting: audio already ON at entry, never activated
     (MISSED — no longer coded as beep_off = 0.0), exit delay, censoring,
     ON-time fraction DURING the event, all reported separately.
  3. S2 censoring investigation: per censored event, post-event estimate
     statistics + rejection counters to test the freeze-trap hypothesis.
  4. t006_drop sensor-dependent behaviour: per-sid noise, corrupt frames
     and post-transient extremes.
  5. Stress tests (seeded synthetic, SIMULATED): startup, missing data,
     sensor spike, rapid reversal — pass/fail criteria per test.
  6. Continuous-ON prevention: audio state machine with the estimator fault
     veto vs without, on a sustained sensor-fault stream.

Phase 3 files are NOT touched; everything new lands in results/11_*.
"""
from pathlib import Path
import csv
import json
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import ROOT, derive_events, replay, streams  # noqa: E402
import audio  # noqa: E402
import synth  # noqa: E402
from filters import FILTERS  # noqa: E402
from filters.stacked import STACKED  # noqa: E402

REGISTRY = dict(FILTERS)
REGISTRY.update(STACKED)
P3 = json.loads((ROOT / "config" / "phase3.json").read_text("utf-8"))
POLICY = P3["audio_policy"]
CENSOR_S = 8.0

# Phase 3 frozen set + Phase 4 candidates (S1P/S4/S5 defaults = frozen
# design defaults pending WP-B tuning; S2/S3 retained as references)
FILTERS_EVAL = ["S1_RobustAdaptiveKF", "S2_DualTimescale",
                "S3_AccelerationAwareKF", "S1P_PersistenceKF",
                "S4_FastSlowGated", "S5_LightGateKF",
                "B02_project_kalman", "C03_CV_tracker", "D01_Kalman_CV"]


def write_csv(rows, path):
    path = Path(path)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})


def classify_event(t, v_ref, e0, e1):
    m = (t >= e0) & (t <= e1)
    med = float(np.median(v_ref[m])) if m.any() else 0.0
    dur = e1 - e0
    if dur < 1.0:
        kind = "transient"
    elif med > 0.2:
        kind = "lift"
    elif med < -0.2:
        kind = "sink"
    else:
        kind = "weak"
    return kind, med


def run_filter(name, st):
    ov = dict(P3["architectures"].get(name, {}).get("params", {}))
    f = REGISTRY[name](**ov)
    t, v = replay.replay(f, t=st["t"], z=st["alt"])
    return f, t, v


def audio_states(t, v):
    sm = audio.AudioStateMachine(lift_on=POLICY["lift_on"],
                                 lift_off=POLICY["lift_off"])
    states, tr = audio.apply_audio(t, v, sm)
    return states, tr


def event_rows_for_stream(name, st, split):
    """Corrected per-event accounting for one filter on one motion stream."""
    events, v_ref = derive_events(st["t"], st["alt"])
    f, t, v = run_filter(name, st)
    states, tr = audio_states(t, v)
    on_times = [tt for tt, s in tr if s == "on"]
    off_times = [tt for tt, s in tr if s == "off"]

    def state_at(tt):
        i = np.searchsorted(t, tt)
        i = min(i, len(t) - 1)
        return states[i]

    rows = []
    for (e0, e1) in events:
        kind, med = classify_event(st["t"], v_ref, e0, e1)
        on_at_entry = state_at(e0) == "on"
        # detection: first ON inside the event window
        in_on = [tt for tt in on_times if e0 - 1e-9 <= tt <= e1 + 1e-9]
        missed = (not on_at_entry) and (not in_on)
        on_delay = (round(in_on[0] - e0, 3) if in_on else np.nan)
        # exit: audio ON at event end -> first OFF after e1 (censored);
        # events whose +8 s window exceeds the recording are flagged
        # TRUNCATED (unverifiable), not censored
        window_ok = (e1 + CENSOR_S) <= st["t"][-1]
        on_at_end = state_at(e1) == "on"
        truncated = int(not window_ok)
        if on_at_end and window_ok:
            offs = [tt for tt in off_times if e1 - 1e-9 <= tt <= e1 + CENSOR_S]
            exit_delay = round(offs[0] - e1, 3) if offs else np.nan
            censored = int(not offs)
        else:
            exit_delay, censored = np.nan, 0
        # ON-time fraction DURING the event
        m = (t >= e0) & (t <= e1)
        on_frac = (float(np.mean([s == "on" for s in np.array(states)[m]]))
                   if m.any() else np.nan)
        # post-event estimate extreme (failure evidence, spec section 5)
        mp = (t > e1) & (t <= e1 + 2.0)
        post_max_v = float(np.max(np.abs(v[mp]))) if mp.any() else np.nan
        rows.append(dict(filter=name, session=st["session"], sid=st["sid"],
                         split=split, kind=kind, ref_med_v=round(med, 3),
                         t0=round(e0, 2), t1=round(e1, 2),
                         dur=round(e1 - e0, 2), truncated=truncated,
                         on_at_entry=int(on_at_entry), missed=int(missed),
                         on_delay_s=on_delay, on_at_end=int(on_at_end),
                         exit_delay_s=exit_delay, censored=censored,
                         on_fraction=round(on_frac, 3) if on_frac == on_frac
                         else np.nan,
                         post_event_max_v=round(post_max_v, 3)
                         if post_max_v == post_max_v else np.nan))
    return rows, f, t, v


def corrected_evaluation():
    rows = []
    for split in ("training", "validation"):
        for st in streams(split):
            if st["kind"] != "motion":
                continue
            for name in FILTERS_EVAL:
                r, _, _, _ = event_rows_for_stream(name, st, split)
                rows.extend(r)
            print(f"  {split}: {st['session']} sid{st['sid']} done", flush=True)
    write_csv(rows, ROOT / "results" / "11_events_corrected.csv")
    return rows


def summarize(rows):
    """Per filter x event-type summary of the corrected metrics."""
    out = []
    for (name, kind), g in group_sorted(rows, ("filter", "kind")):
        n = len(g)
        missed = g["missed"].astype(float)
        cens = g["censored"].astype(float)
        od = g["on_delay_s"].dropna()
        ex = g["exit_delay_s"].dropna()
        out.append(dict(filter=name, kind=kind, n_events=n,
                        missed=int(missed.sum()),
                        missed_rate=round(float(missed.mean()), 3),
                        median_on_delay_s=(round(float(od.median()), 3)
                                           if len(od) else np.nan),
                        n_censored=int(cens.sum()),
                        median_exit_delay_s=(round(float(ex.median()), 3)
                                             if len(ex) else np.nan),
                        median_on_fraction=round(float(g["on_fraction"]
                                                       .median()), 3),
                        max_post_event_v=round(float(g["post_event_max_v"]
                                                     .max()), 3)))
    write_csv(out, ROOT / "results" / "11_summary_by_type.csv")
    return out


def group_sorted(rows, keys):
    import pandas as pd
    df = pd.DataFrame(rows)
    df = df.sort_values(list(keys))
    for k in keys:
        df[k] = df[k].astype(str)
    for _, g in df.groupby(list(keys), sort=True):
        yield tuple(g[k].iloc[0] for k in keys), g


def investigate_s2(rows):
    """Censoring root-cause test: censored S2 events should show the freeze
    signature (post-event |v| far from rest, heavy sample rejection);
    S4 on the same events should not."""
    import pandas as pd
    df = pd.DataFrame(rows)
    cen = df[(df["filter"] == "S2_DualTimescale") & (df["censored"] == 1)]
    out = []
    for _, r in cen.iterrows():
        st = next(s for s in list(streams("training")) + list(streams("validation"))
                  if s["session"] == r["session"] and s["sid"] == r["sid"])
        for name in ("S2_DualTimescale", "S4_FastSlowGated"):
            f, t, v = run_filter(name, st)
            m = (t >= r["t1"]) & (t <= min(r["t1"] + CENSOR_S, t[-1]))
            tail = (t >= r["t1"] + CENSOR_S - 2.0) & (t <= r["t1"] + CENSOR_S)
            out.append(dict(event=f"{r['session']}#sid{r['sid']}@{r['t0']}",
                            filter=name, kind=r["kind"],
                            post_max_v=(round(float(np.max(np.abs(v[m]))), 3)
                                        if m.any() else np.nan),
                            tail_med_v=(round(float(np.median(v[tail])), 3)
                                        if tail.any() else np.nan),
                            n_rejected=int(getattr(f, "n_rejected", -1)),
                            post_window_above_lift_off=int(
                                np.any(np.abs(v[m]) > POLICY["lift_off"])
                                if m.any() else 0)))
    write_csv(out, ROOT / "results" / "11_s2_censoring.csv")
    return out


def investigate_t006_sids():
    """Per-sid behaviour on the 90 Hz t006 sessions (noise, corrupt frames,
    post-transient extremes)."""
    out = []
    for split in ("training", "validation"):
        for st in streams(split):
            if not st["session"].startswith("20261022_163"):
                continue
            base = dict(session=st["session"], sid=st["sid"], split=split,
                        kind=st["kind"], rate_hz=st["rate"],
                        n_corrupt=st["diag"].n_corrupt,
                        n_seq_gaps=st["diag"].n_seq_gaps)
            for name in FILTERS_EVAL:
                f, t, v = run_filter(name, st)
                row = dict(base, filter=name,
                           rms=round(float(np.sqrt(np.mean(v ** 2))), 4))
                for tc in st["diag"].corrupt_t:
                    m = (t >= tc) & (t <= tc + 2.0)
                    if m.any():
                        row[f"post_transient_max_v"] = round(
                            max(row.get("post_transient_max_v", 0),
                                float(np.max(np.abs(v[m])))), 3)
                out.append(row)
    write_csv(out, ROOT / "results" / "11_t006_sid.csv")
    return out


# --------------------------------------------------------------------------
# Stress tests (seeded synthetic — SIMULATED, filter mathematics only)
# --------------------------------------------------------------------------
def stress_tests():
    rng = np.random.default_rng(1234)
    rows = []

    def record(filt, test, passed, detail, sim=True):
        rows.append(dict(filter=filt, test=test,
                         result="pass" if passed else "FAIL",
                         detail=detail, simulated=int(sim)))

    # A. startup: 60 s static from cold start; no audio latches at all
    t = np.arange(0, 60.0, 1 / 50)
    z = synth.constant_altitude(t, rng=rng, noise_m=0.05)
    for name in FILTERS_EVAL:
        f, tt, v = run_filter(name, dict(t=t, alt=z))
        states, tr = audio_states(tt, v)
        n_on = sum(1 for _, s in tr if s == "on")
        record(name, "startup_static", n_on == 0, f"audio latches={n_on}")

    # B. missing data: 2 s gap in the middle of a 30 s static stream
    t2 = t[t < 15.0]
    t2 = np.concatenate([t2, t2[-1] + 2.0 + (t[t < 13.0])])
    z2 = synth.constant_altitude(t2, rng=rng, noise_m=0.05)
    for name in FILTERS_EVAL:
        f, tt, v = run_filter(name, dict(t=t2, alt=z2))
        states, tr = audio_states(tt, v)
        gap_t = t2[np.searchsorted(t2, 15.0)]
        after = [x for x, s in tr if s == "on" and gap_t < x <= gap_t + 4.0]
        n_on = sum(1 for _, s in tr if s == "on")
        record(name, "missing_data_gap", len(after) <= 1,
               f"latches_in_4s_after_gap={len(after)}, total={n_on}")

    # C. sensor spike: three 5 m single-sample spikes on static
    for name in FILTERS_EVAL:
        zs = z.copy()
        for ts_ in (10.0, 25.0, 40.0):
            zs[np.searchsorted(t, ts_)] += 5.0
        f, tt, v = run_filter(name, dict(t=t, alt=zs))
        states, tr = audio_states(tt, v)
        ok_v, ok_audio = True, True
        for ts_ in (10.0, 25.0, 40.0):
            m = (tt >= ts_) & (tt <= ts_ + 2.0)
            if np.max(np.abs(v[m])) >= 1.0:
                ok_v = False
            bad = [x for x, s in tr if s == "on"
                   and ts_ - 0.05 <= x <= ts_ + 2.0]
            if bad:
                ok_audio = False
        record(name, "sensor_spike", ok_v and ok_audio,
               f"extreme_v={not ok_v}, audio_on_after_spike={not ok_audio}")

    # D. rapid reversal: lift pulse ends, sink pulse begins immediately
    tr_ = np.arange(0, 16.0, 1 / 50)
    zr = (synth.lift_pulse(tr_, v=1.5, t_on=3.0, dur=1.0, ramp=0.15)
          + synth.lift_pulse(tr_, v=-2.5, t_on=4.15, dur=1.0, ramp=0.15)
          + rng.normal(0, 0.03, len(tr_)))
    lift_end = 4.15
    for name in FILTERS_EVAL:
        f, tt, v = run_filter(name, dict(t=tr_, alt=zr))
        states, trn = audio_states(tt, v)
        offs = [x for x, s in trn if s == "off" and lift_end <= x <= lift_end + 3.0]
        exit_s = round(offs[0] - lift_end, 3) if offs else np.nan
        record(name, "rapid_reversal_exit", bool(offs) and exit_s < 3.0,
               f"exit_after_reversal_s={exit_s}")

    # E. sustained sensor fault: 30 m offset for 3 s; audio WITH the
    #    estimator-fault veto must never be ON during the fault
    tf = np.arange(0, 20.0, 1 / 50)
    zf = synth.constant_altitude(tf, rng=rng, noise_m=0.05)
    zf[(tf >= 8.0) & (tf < 11.0)] += 30.0
    fault_m = (tf >= 8.0) & (tf < 11.0)
    for name in FILTERS_EVAL:
        ov = dict(P3["architectures"].get(name, {}).get("params", {}))
        f = REGISTRY[name](**ov)
        vv = np.array([f.update(float(zi), float(ti))
                       for zi, ti in zip(zf, tf)])
        faults = np.zeros(len(tf), dtype=bool)
        if hasattr(f, "_fault"):            # S3-style fault latch
            # replay capturing the flag per sample
            f2 = REGISTRY[name](**ov)
            flags = []
            for zi, ti in zip(zf, tf):
                f2.update(float(zi), float(ti))
                flags.append(bool(getattr(f2, "_fault", False)
                                  or getattr(f2, "fault", False)))
            faults = np.array(flags)
        else:                                # gap-based fault proxy
            dt = np.diff(tf, prepend=tf[0])
            faults = dt > 3 * np.median(dt)
        sm = audio.AudioStateMachine()
        states, trn = audio.apply_audio(tf, vv, sm, faults=faults)
        on_during_fault = sum(
            1 for i in range(len(tf)) if states[i] == "on" and fault_m[i])
        sm2 = audio.AudioStateMachine()
        states2, _ = audio.apply_audio(tf, vv, sm2)
        on_during_fault_noveto = sum(
            1 for i in range(len(tf)) if states2[i] == "on" and fault_m[i])
        frac = on_during_fault / fault_m.sum()
        frac_nv = on_during_fault_noveto / fault_m.sum()
        record(name, "fault_veto_on_fraction", frac == 0.0,
               f"on_fraction_with_veto={frac:.3f} "
               f"without={frac_nv:.3f} "
               f"(fault_flag={'estimator' if hasattr(f, '_fault') else 'gap'})")

    # F. GENERIC driver-level fault detector (works with ANY estimator):
    #    consecutive plausibility violations vs the estimator's own
    #    prediction trip a fault latch; fed to the audio veto
    class GenericFaultDetector:
        """Estimator-agnostic fault flag: streak of samples whose raw
        altitude deviates from the estimator's own prediction by more
        than a physical bound -> fault; clears after a clean streak."""

        def __init__(self, v_plaus_max=8.0, margin_m=0.3, trip_n=5,
                     clear_n=5):
            self.v_plaus_max = v_plaus_max
            self.margin_m = margin_m
            self.trip_n = trip_n
            self.clear_n = clear_n
            self.bad = 0
            self.good = 0
            self.flag = False

        def update(self, z, t, h_pred, dt):
            if abs(z - h_pred) > self.v_plaus_max * dt + self.margin_m:
                self.bad += 1
                self.good = 0
                if self.bad >= self.trip_n:
                    self.flag = True
            else:
                self.good += 1
                self.bad = 0
                if self.good >= self.clear_n:
                    self.flag = False
            return self.flag

    for name in FILTERS_EVAL:
        ov = dict(P3["architectures"].get(name, {}).get("params", {}))
        f = REGISTRY[name](**ov)
        det = GenericFaultDetector()
        vv = np.empty(len(tf))
        faults = np.zeros(len(tf), dtype=bool)
        h_prev, v_prev, t_prev = None, 0.0, None
        for i, (zi, ti) in enumerate(zip(zf, tf)):
            vv[i] = f.update(float(zi), float(ti))
            if t_prev is None:
                h_pred, dt = float(zi), 0.02
            else:
                dt = float(ti) - t_prev
                h_pred = h_prev + v_prev * dt
            faults[i] = det.update(float(zi), ti, h_pred, max(dt, 1e-3))
            h_prev, v_prev, t_prev = f.get_altitude(), vv[i], float(ti)
        sm = audio.AudioStateMachine()
        states, _ = audio.apply_audio(tf, vv, sm, faults=faults)
        on_during_fault = sum(
            1 for i in range(len(tf)) if states[i] == "on" and fault_m[i])
        frac = on_during_fault / fault_m.sum()
        # trip latency: the detector needs trip_n bad samples to flag; ON
        # transitions within that window are detector latency, not failure
        record(name, "fault_veto_generic_detector",
               on_during_fault <= det.trip_n,
               f"on_samples_with_generic_veto={on_during_fault} "
               f"(trip_n={det.trip_n}, fault_samples={int(fault_m.sum())})")

    # G. max_on safety valve on the spike stream: even when a spike rings
    #    the audio ON (C03/D01/S3), a max_on_s valve bounds the false ON
    for name in FILTERS_EVAL:
        zs = synth.constant_altitude(tf, rng=rng, noise_m=0.05)
        for ts_ in (5.0, 10.0, 15.0):
            zs[np.searchsorted(tf, ts_)] += 5.0
        f, tt, v = run_filter(name, dict(t=tf, alt=zs))
        sm = audio.AudioStateMachine(max_on_s=2.0)
        states, trn = audio.apply_audio(tt, v, sm)
        longest = 0.0
        ons = [x for x, s in trn if s == "on"]
        offs = [x for x, s in trn if s == "off"]
        for a, b in zip(ons, offs + [tt[-1]]):
            longest = max(longest, b - a)
        ok = longest <= 2.05
        record(name, "max_on_valve_bounds_false_on", ok,
               f"longest_on_episode_s={longest:.2f} (valve 2.0)")
    write_csv(rows, ROOT / "results" / "11_stress.csv")
    return rows


def main():
    rows = corrected_evaluation()
    summarize(rows)
    investigate_s2(rows)
    investigate_t006_sids()
    stress_tests()
    n_fail = 0
    print("WP-A evaluation complete:")
    for f in ("11_events_corrected.csv", "11_summary_by_type.csv",
              "11_s2_censoring.csv", "11_t006_sid.csv", "11_stress.csv"):
        p = ROOT / "results" / f
        n = sum(1 for _ in p.open("rb")) - 1
        print(f"  results/{f}: {n} rows")


if __name__ == "__main__":
    main()
