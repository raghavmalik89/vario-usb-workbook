"""Phase 4 shared evaluation core (WP-B). Used by scripts 12/13/16.

Design: the ESTIMATOR replay (expensive) is run once per (estimator, stream);
every AUDIO-POLICY evaluation reuses the precomputed (t, v) — estimator
tuning and audio-policy tuning are thereby fully separated, and the policy
grid search is cheap. All accounting is the corrected WP-A version: event
types, missed detections counted separately, exit censoring with truncation
flags, ON-time fraction during events.
"""
from pathlib import Path
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
P4 = json.loads((ROOT / "config" / "phase4.json").read_text("utf-8"))
CENSOR_S = 8.0


def estimator_params(name):
    """Frozen estimator params: Phase-4 config if present, else Phase-3
    frozen config (references), else class defaults."""
    est = P4.get("estimators", {}).get(name)
    if est is not None:
        return dict(est["params"])
    return dict(P3["architectures"].get(name, {}).get("params", {}))


def make_estimator(name):
    return REGISTRY[name](**estimator_params(name))


def run_estimator(name, st):
    f = make_estimator(name)
    t, v = replay.replay(f, t=st["t"], z=st["alt"])
    return f, t, v


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


def event_rows_from_v(name, st, split, t, v, events, v_ref, policy,
                      fault_flags=None):
    """Corrected WP-A per-event accounting for precomputed (t, v) under an
    explicit audio policy dict (lift_on/lift_off/hold_s/min_on_s/max_on_s/
    fault_veto)."""
    sm = audio.AudioStateMachine(lift_on=policy["lift_on"],
                                 lift_off=policy["lift_off"],
                                 hold_s=policy.get("hold_s", 0.0),
                                 min_on_s=policy.get("min_on_s", 0.0),
                                 max_on_s=policy.get("max_on_s", 0.0))
    faults = fault_flags if policy.get("fault_veto") else None
    states, tr = audio.apply_audio(t, v, sm, faults=faults)
    on_times = [tt for tt, s in tr if s == "on"]
    off_times = [tt for tt, s in tr if s == "off"]

    def state_at(tt):
        i = min(np.searchsorted(t, tt), len(t) - 1)
        return states[i]

    rows = []
    for (e0, e1) in events:
        kind, med = classify_event(t, v_ref, e0, e1)
        on_at_entry = state_at(e0) == "on"
        in_on = [tt for tt in on_times if e0 - 1e-9 <= tt <= e1 + 1e-9]
        missed = (not on_at_entry) and (not in_on)
        on_delay = (round(in_on[0] - e0, 3) if in_on else np.nan)
        window_ok = (e1 + CENSOR_S) <= t[-1]
        on_at_end = state_at(e1) == "on"
        truncated = int(not window_ok)
        if on_at_end and window_ok:
            offs = [tt for tt in off_times if e1 - 1e-9 <= tt <= e1 + CENSOR_S]
            exit_delay = round(offs[0] - e1, 3) if offs else np.nan
            censored = int(not offs)
        else:
            exit_delay, censored = np.nan, 0
        m = (t >= e0) & (t <= e1)
        on_frac = (float(np.mean([s == "on" for s in np.array(states)[m]]))
                   if m.any() else np.nan)
        mp = (t > e1) & (t <= e1 + 2.0)
        post_max_v = float(np.max(np.abs(v[mp]))) if mp.any() else np.nan
        rows.append(dict(filter=name, session=st["session"], sid=st["sid"],
                         split=split, kind=kind, t0=round(e0, 2),
                         t1=round(e1, 2), dur=round(e1 - e0, 2),
                         truncated=truncated, on_at_entry=int(on_at_entry),
                         missed=int(missed), on_delay_s=on_delay,
                         on_at_end=int(on_at_end), exit_delay_s=exit_delay,
                         censored=censored,
                         on_fraction=(round(on_frac, 3)
                                      if on_frac == on_frac else np.nan),
                         post_event_max_v=(round(post_max_v, 3)
                                           if post_max_v == post_max_v
                                           else np.nan)))
    return rows


def statics_audio_from_v(name, st, split, t, v, policy, fault_flags=None):
    """False-trigger accounting on a static stream under a policy."""
    dur = t[-1] - t[0]
    sm = audio.AudioStateMachine(lift_on=policy["lift_on"],
                                 lift_off=policy["lift_off"],
                                 hold_s=policy.get("hold_s", 0.0),
                                 min_on_s=policy.get("min_on_s", 0.0),
                                 max_on_s=policy.get("max_on_s", 0.0))
    faults = fault_flags if policy.get("fault_veto") else None
    states, tr = audio.apply_audio(t, v, sm, faults=faults)
    on_times = [tt for tt, s in tr if s == "on"]
    off_times = [tt for tt, s in tr if s == "off"]
    on_durs = [b - a for a, b in zip(on_times, off_times + [t[-1]])]
    return dict(filter=name, session=st["session"], sid=st["sid"], split=split,
                duration_s=round(dur, 2), n_on=len(on_times),
                on_per_hour=(round(len(on_times) / dur * 3600, 1)
                             if dur > 0 else 0.0),
                total_on_time_s=round(float(sum(on_durs)), 2),
                on_time_fraction=(round(float(sum(on_durs)) / dur, 4)
                                  if dur > 0 else 0.0))


class GenericFaultDetector:
    """Estimator-agnostic fault flag (WP-A stress test F): streak of raw
    samples deviating from the estimator's own prediction beyond a physical
    bound trips the flag; a clean streak clears it."""

    def __init__(self, v_plaus_max=8.0, margin_m=0.3, trip_n=5, clear_n=5):
        cfg = P4.get("safety_mechanisms", {}).get("fault_detector", {})
        self.v_plaus_max = float(cfg.get("v_plaus_max", v_plaus_max))
        self.margin_m = float(cfg.get("margin_m", margin_m))
        self.trip_n = int(cfg.get("trip_n", trip_n))
        self.clear_n = int(cfg.get("clear_n", clear_n))
        self.bad = 0
        self.good = 0
        self.flag = False

    def update(self, z, h_pred, dt):
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


def fault_flags_for(name, st):
    """Per-sample generic fault flags for a stream replay."""
    f = make_estimator(name)
    flags = np.zeros(len(st["t"]), dtype=bool)
    det = GenericFaultDetector()
    h_prev, v_prev, t_prev = None, 0.0, None
    for i, (zi, ti) in enumerate(zip(st["alt"], st["t"])):
        f.update(float(zi), float(ti))
        if t_prev is None:
            h_pred, dt = float(zi), 0.02
        else:
            dt = float(ti) - t_prev
            h_pred = h_prev + v_prev * dt
        flags[i] = det.update(float(zi), h_pred, max(dt, 1e-3))
        h_prev, v_prev, t_prev = f.get_altitude(), f.get_estimate(), float(ti)
    return flags


def write_csv(rows, path):
    path = Path(path)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    import csv
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})
