"""Bench 6 metrics — estimator output and virtual audio, evaluated SEPARATELY.

Estimator metrics are computed on the raw velocity stream v(t). Audio metrics
come from running the COMMON policy state machine (src/audio.py:
lift_on=0.20, lift_off=0.05, no hold/min_on — exactly the firmware AU_*)
over that stream. No estimator-side audio logic is ever measured as filter
performance.

All elevator timings are DESCRIPTIVE PROXIES against derived leg references
(detect_legs) — the elevator is a controlled-motion reference, not ground
truth; subsecond response claims are not made.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

BENCH6_DIR = Path(__file__).resolve().parent
BENCH_ROOT = BENCH6_DIR.parents[0]
SRC = BENCH_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import metrics as src_metrics  # noqa: E402
from audio import AudioStateMachine  # noqa: E402

LIFT_ON, LIFT_OFF = 0.20, 0.05
STARTUP_SKIP_S = 10.0          # DEF-010: startup audio flapping excluded


# --------------------------------------------------------------- statics ----
def static_metrics(t, v, skip_s=STARTUP_SKIP_S):
    m = t >= (t[0] + skip_s)
    tv, vv = t[m], v[m]
    if len(vv) < 100:
        return {}
    dur = tv[-1] - tv[0]
    out = dict(
        rest_rms=float(np.sqrt(np.mean(vv ** 2))),
        rest_mad=float(np.median(np.abs(vv - np.median(vv))) * 1.4826),
        rest_p95_abs=float(np.percentile(np.abs(vv), 95)),
        rest_p99_abs=float(np.percentile(np.abs(vv), 99)),
        rest_peak_abs=float(np.max(np.abs(vv))),
        rest_bias=float(np.mean(vv)),
        zero_crossings_per_s=float(np.sum(np.diff(np.signbit(vv)) != 0) / dur),
        rest_dur_s=float(dur),
    )
    out.update(audio_metrics(tv, vv))
    return out


# ------------------------------------------------------------- elevator -----
def _sustained_below(t, v, t_from, thr, hold_s, window_s=8.0, sustain_s=1.0):
    """First time after t_from where |v| <= thr and stays so for sustain_s.
    Searched within [t_from, t_from+window_s]. Proxy, not ground truth."""
    i0 = np.searchsorted(t, t_from)
    i1 = np.searchsorted(t, t_from + window_s)
    tw, vw = t[i0:i1], v[i0:i1]
    if not len(vw):
        return np.nan
    below = np.abs(vw) <= thr
    k = max(1, int(round(sustain_s / (np.median(np.diff(t)) if len(t) > 1 else 0.02))))
    for i in range(len(vw)):
        if below[i] and (i + k > len(vw) or below[i:i + k].all()):
            return float(tw[i] - t_from)
    return np.nan


def elevator_metrics(t, v, legs, audio_sm=None):
    """Per-leg tracking + audio, and dwell false-activation. Returns
    (summary dict, per_leg list, dwell dict)."""
    per_leg = []
    for (t0, t1, v_leg, dH) in legs:
        sgn = np.sign(v_leg)
        pm = (t >= t0 + 2.0) & (t <= t1 - 2.0)
        vv = v[pm]
        tv = t[pm]
        bias = float(np.median(vv - v_leg)) if len(vv) else np.nan
        rms = float(np.sqrt(np.mean((vv - v_leg) ** 2))) if len(vv) else np.nan
        # rise proxy: first crossing of 0.5*v_leg after t0 (sign-aware)
        i0 = np.searchsorted(t, t0 - 1.0)
        i1 = np.searchsorted(t, t0 + 8.0)
        rise = np.nan
        win = v[i0:i1] * sgn >= 0.5 * abs(v_leg)
        if win.any():
            rise = float(t[i0 + np.where(win)[0][0]] - t0)
        # exit proxy: sustained |v| <= lift_off after t1
        exit_s = _sustained_below(t, v, t1, LIFT_OFF, 0, sustain_s=1.0)
        # overshoot on plateau (signed along leg direction)
        over = float(np.max(vv * sgn - abs(v_leg))) if len(vv) else np.nan
        # audio over the leg + 8 s tail
        ia = np.searchsorted(t, t0)
        ib = np.searchsorted(t, t1 + 8.0)
        on_frac = on_time = np.nan
        if audio_sm is not None and ib > ia:
            states, _ = run_audio(audio_sm, t[ia:ib], v[ia:ib])
            on_frac = float(np.mean(np.array(states) == "on"))
            on_time = float(np.sum(np.array(states) == "on") *
                            np.median(np.diff(t[ia:ib])))
        per_leg.append(dict(t0=t0, t1=t1, v_leg=v_leg, dH=dH, kind="ascent" if v_leg > 0 else "descent",
                            bias=bias, rms=rms, rise_s=rise, exit_s=exit_s,
                            overshoot=over, audio_on_frac=on_frac,
                            audio_on_s=on_time))
    asc = [l for l in per_leg if l["kind"] == "ascent"]
    desc = [l for l in per_leg if l["kind"] == "descent"]

    # dwells: complement of legs within the leg span
    dwell = dict(dwell_false_on_s=0.0, dwell_latches=0, dwell_dur_s=0.0)
    if legs:
        span0, span1 = legs[0][0], legs[-1][1]
        cuts = [span0] + [x for leg in legs for x in (leg[0], leg[1])] + [span1]
        segs = [(cuts[i], cuts[i + 1]) for i in range(0, len(cuts) - 1, 2)]
        for (a, b) in segs:
            if b - a < 3.0:
                continue
            ia = np.searchsorted(t, a)
            ib = np.searchsorted(t, b)
            if audio_sm is not None and ib > ia:
                states, trans = run_audio(audio_sm, t[ia:ib], v[ia:ib])
                on = np.array(states) == "on"
                dwell["dwell_false_on_s"] += float(on.sum() * np.median(np.diff(t[ia:ib])))
                dwell["dwell_latches"] += sum(1 for _, s in trans if s == "on")
                dwell["dwell_dur_s"] += float(b - a)
    def _med(key, lst):
        xs = [l[key] for l in lst if l[key] == l[key]]
        return float(np.median(xs)) if xs else float("nan")

    out = dict(
        n_legs=len(legs),
        bias_med=_med("bias", per_leg),
        rms_med=_med("rms", per_leg),
        bias_ascent_med=_med("bias", asc),
        bias_descent_med=_med("bias", desc),
        rise_med_s=_med("rise_s", per_leg),
        exit_med_s=_med("exit_s", per_leg),
        overshoot_med=_med("overshoot", per_leg),
        ascent_on_frac_med=_med("audio_on_frac", asc),
        missed_lifts=int(sum(1 for l in asc if (l["audio_on_frac"] == l["audio_on_frac"]) and l["audio_on_frac"] < 0.5)) if asc else 0,
        descent_spurious_on_s=float(np.nansum([l["audio_on_s"] for l in desc])) if desc else 0.0,
    )
    out.update(dwell)
    return out, per_leg, dwell


# ------------------------------------------------------------- handtest -----
def handtest_metrics(t, v, events, v_ref, audio_sm=None,
                     static_until=None, slow_blocks=None):
    em = src_metrics.event_metrics(t, v, v_ref, events)
    out = dict(n_events=len(events),
               onset_med_s=em["onset_med_s"],
               release_med_s=em["release_med_s"],
               fall_90_10_med_s=em["fall_90_10_med_s"])
    # motion rms inside events
    m = np.zeros(len(t), bool)
    for (a, b) in events:
        m |= (t >= a) & (t <= b)
    out["motion_rms"] = float(np.sqrt(np.mean(v[m] ** 2))) if m.any() else np.nan
    # slow sustained-motion blocks (thermalling-relevant regime)
    if slow_blocks:
        blk = []
        for (a, b) in slow_blocks:
            m = (t >= a) & (t <= b)
            if m.sum() < 20:
                continue
            row = dict(t0=a, t1=b, dur=b - a,
                       ref_v_med=float(np.median(v_ref[m])),
                       est_v_med=float(np.median(v[m])),
                       bias=float(np.median(v[m] - v_ref[m])))
            if audio_sm is not None:
                states, _ = run_audio(audio_sm, t[m], v[m])
                row["audio_on_frac"] = float(np.mean(np.array(states) == "on"))
            blk.append(row)
        out["n_slow_blocks"] = len(blk)
        xs = [b["bias"] for b in blk]
        out["slow_bias_med"] = float(np.median(xs)) if xs else np.nan
        xs = [b["audio_on_frac"] for b in blk if "audio_on_frac" in b]
        out["slow_audio_on_frac_med"] = float(np.median(xs)) if xs else np.nan
        out["_slow_blocks"] = blk
    # static-silence portion: after startup skip, before the first slow block
    # (or first event) — whichever comes first
    if static_until is None:
        cands = [bb[0] for bb in (slow_blocks or []) if bb[0] > STARTUP_SKIP_S]
        cands += [a for (a, b) in events if a > STARTUP_SKIP_S]
        static_until = min(cands) if cands else t[-1]
    su = static_until
    smask = (t >= t[0] + STARTUP_SKIP_S) & (t < su)
    sv = v[smask]
    st = t[smask]
    if len(sv) > 100:
        out["static_rms"] = float(np.sqrt(np.mean(sv ** 2)))
        out["static_false_on_per_hr"] = audio_false_rate(st, sv)[0]
    else:
        out["static_rms"] = np.nan
        out["static_false_on_per_hr"] = np.nan
    # toss recovery: strong events (peak_ref > 3 m/s)
    rec = []
    for p in em["per_event"]:
        if p["peak_ref"] > 3.0:
            settle = _sustained_below(t, v, p["t1"], 0.3, 0,
                                      window_s=10.0, sustain_s=2.0)
            i0 = np.searchsorted(t, p["t1"])
            i1 = np.searchsorted(t, p["t1"] + 5.0)
            peak_after = float(np.max(np.abs(v[i0:i1]))) if i1 > i0 else np.nan
            rec.append(dict(settle_s=settle, peak_after=peak_after,
                            peak_ref=p["peak_ref"]))
    out["n_toss"] = len(rec)
    out["toss_settle_med_s"] = float(np.median([r["settle_s"] for r in rec])) if rec else np.nan
    out["toss_peak_after_med"] = float(np.median([r["peak_after"] for r in rec])) if rec else np.nan
    if audio_sm is not None:
        states, _ = run_audio(audio_sm, t, v)
        states = np.array(states) == "on"
        on_in = dur_in = 0.0
        mm_all = np.zeros(len(t), bool)
        for (a, b) in events:
            mm = (t >= a) & (t <= b)
            on_in += float(states[mm].sum())
            dur_in += float(mm.sum())
            mm_all |= mm | ((t > b) & (t <= b + 8.0))
        on_out = float(states[~mm_all].sum())
        dur_out = float((~mm_all).sum())
        out["audio_on_frac_events"] = on_in / dur_in if dur_in else np.nan
        out["audio_on_frac_outside"] = on_out / dur_out if dur_out else np.nan
    return out, em["per_event"], rec


# ----------------------------------------------------------------- audio ----
def run_audio(sm: AudioStateMachine, t, v):
    states, trans = [], []
    sm.reset()
    for i in range(len(t)):
        states.append(sm.update(float(t[i]), float(v[i])))
    return states, list(sm.transitions)


def audio_metrics(t, v, sm=None):
    """False-activation under the common policy on a (static) stream."""
    sm = sm or AudioStateMachine(LIFT_ON, LIFT_OFF)
    states, trans = run_audio(sm, t, v)
    dur = t[-1] - t[0]
    on = np.array(states) == "on"
    rate, eps = audio_false_rate(t, v, states=states, trans=trans)
    return dict(false_on_per_hr=rate, on_fraction=float(on.mean()),
                n_on_events=int(sum(1 for _, s in trans if s == "on")),
                audio_dur_s=float(dur))


def audio_false_rate(t, v, states=None, trans=None):
    """ON-latches per hour with min 0.5 s separation."""
    if states is None:
        sm = AudioStateMachine(LIFT_ON, LIFT_OFF)
        states, trans = run_audio(sm, t, v)
    dur = t[-1] - t[0]
    ons = [tt for tt, s in trans if s == "on"]
    if not ons:
        return 0.0, []
    eps = [ons[0]]
    for tt in ons[1:]:
        if tt - eps[-1] >= 0.5:
            eps.append(tt)
    return float(len(eps) / (dur / 3600.0)), eps
