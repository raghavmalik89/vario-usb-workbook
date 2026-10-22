"""Derived event references and metrics.

EVENTS ARE DERIVED, NOT GROUND TRUTH (spec §6B, user mandate): the reference
climb rate is a 1-s Gaussian-smoothed barometric derivative; event starts/
ends are threshold crossings of that smoothed signal. All onset/release
numbers computed against them are DESCRIPTIVE PROXY measurements — useful
for comparing filters ON THE SAME EVENTS, not measurable physical latencies.
This module never claims otherwise.
"""
from __future__ import annotations

import numpy as np

LIFT_ON = 0.20       # audio lift-on threshold [m/s]  (research recommendation)
LIFT_OFF = 0.05      # audio lift-off threshold [m/s]
EVENT_ON = 0.3       # strong-motion event detection threshold
EVENT_OFF = 0.05
EVENT_MIN_DUR = 0.4
EVENT_GAP = 1.0


def reference_v(t, alt, win_s=1.0):
    """1-s Gaussian-smoothed derivative of altitude — the DERIVED reference."""
    dt = np.median(np.diff(t))
    n = max(int(round(win_s / dt)), 3)
    k = np.exp(-0.5 * (np.arange(-3 * n, 3 * n + 1) / n) ** 2)
    k /= k.sum()
    alt_s = np.convolve(alt, k, mode="same")
    return np.gradient(alt_s, t), alt_s


def detect_events(t, v_ref, on=EVENT_ON, off=EVENT_OFF, min_dur=EVENT_MIN_DUR,
                  gap=EVENT_GAP):
    m = np.abs(v_ref) > on
    idx = np.where(m)[0]
    segs = []
    if not len(idx):
        return segs
    s = idx[0]
    prev = idx[0]
    for i in idx[1:]:
        if t[i] - t[prev] > gap:
            segs.append((s, prev))
            s = i
        prev = i
    segs.append((s, prev))
    return [(t[a], t[b]) for a, b in segs if t[b] - t[a] >= min_dur]


def stationary_metrics(v, t=None, lift_on=LIFT_ON, lift_off=LIFT_OFF,
                       min_separation_s=0.5):
    """Stationary-noise and false-trigger metrics (spec §6A).

    False-trigger count = number of lift latches (cross above lift_on, latch
    until below lift_off) under the COMMON audio policy, on the estimate
    itself — the spec's 'frequency of false audio-trigger events'.
    """
    out = dict(
        mean=float(np.mean(v)),
        std=float(np.std(v)),
        rms=float(np.sqrt(np.mean(v ** 2))),
        mad=float(np.median(np.abs(v - np.median(v))) * 1.4826),
        p95_abs=float(np.percentile(np.abs(v), 95)),
        p99_abs=float(np.percentile(np.abs(v), 99)),
        peak_abs=float(np.max(np.abs(v))),
        zero_crossings_per_s=None,
        time_above_lift_on=float(np.mean(np.abs(v) > lift_on)),
    )
    if t is not None and len(t) > 1:
        zc = np.sum(np.diff(np.signbit(v)) != 0)
        out["zero_crossings_per_s"] = float(zc / (t[-1] - t[0]))
    out["false_latches"] = count_latches(v, t, lift_on, lift_off,
                                         min_separation_s)
    return out


def count_latches(v, t, on, off, min_separation_s=0.5):
    """Audio-policy latch count with minimum separation (prevents counting
    a chattering burst as hundreds of events)."""
    above = np.abs(v) > on
    idx = np.where(above)[0]
    if not len(idx):
        return 0
    # latch ends: last index above 'off' after each start
    count = 0
    last_end_t = None
    i = 0
    while i < len(idx):
        j = idx[i]
        while j + 1 < len(v) and np.abs(v[j + 1]) > off:
            j += 1
        start_t = t[idx[i]] if t is not None else idx[i]
        if last_end_t is None or (start_t - last_end_t) >= min_separation_s:
            count += 1
        last_end_t = t[j] if t is not None else j
        nxt = np.where(idx > j)[0]
        if not len(nxt):
            break
        i = nxt[0]
    return count


def event_metrics(t, v_est, v_ref, events, lift_off=LIFT_OFF, lift_on=LIFT_ON):
    """Event-relative proxy metrics with audio-hysteresis semantics
    (window: event start - 6 s .. event end + 8 s; the wide margins keep
    onsets/releases uncensored for slow filters on long events). Returns dict
    of medians + per-event lists. All values are DESCRIPTIVE PROXIES against
    the derived reference intervals, never ground-truth latencies."""
    per = []
    for (e0, e1) in events:
        # onset: first time the estimate exceeds max(EVENT_ON, 5x its own
        # pre-event baseline) — a noise-adaptive DETECTION proxy, so a
        # filter whose rest noise already exceeds 0.3 m/s is not credited
        # with an impossibly early onset. Baseline from [e0-3, e0-0.5] s.
        b0 = np.searchsorted(t, e0 - 3.0)
        b1 = np.searchsorted(t, e0 - 0.5)
        base = np.median(np.abs(v_est[b0:b1])) if b1 > b0 else 0.0
        thr = max(EVENT_ON, 5.0 * base)
        i0 = np.searchsorted(t, e0 - 6.0)
        i1 = np.searchsorted(t, e1 + 1)
        win = np.abs(v_est[i0:i1]) > thr
        onset = rel = np.nan
        if win.any():
            j = np.where(win)[0]
            onset = t[i0 + j[0]] - e0
            rel = t[i0 + j[-1]] - e1
        # release with audio hysteresis: first drop below lift_off with no
        # re-crossing of lift_on within the window (proxy semantics)
        w0 = np.searchsorted(t, e0)
        w1 = np.searchsorted(t, e1 + 8.0)
        tw, vw = t[w0:w1], v_est[w0:w1]
        rel5 = fall = np.nan
        if len(vw):
            k1 = np.searchsorted(tw, e1)
            above_on = np.abs(vw[k1:]) > lift_on
            below = np.where(np.abs(vw[k1:]) <= lift_off)[0]
            for k in below:
                if not above_on[k:].any():
                    rel5 = tw[k1 + k] - e1
                    break
            ipk = int(np.argmax(np.abs(vw)))
            peak = abs(vw[ipk])
            if peak >= 0.1:
                tail = np.abs(vw[ipk:])
                b90 = np.where(tail <= 0.9 * peak)[0]
                b10 = np.where(tail <= 0.1 * peak)[0]
                if len(b90) and len(b10):
                    fall = tw[ipk + b10[0]] - tw[ipk + b90[0]]
        ev = (t >= e0) & (t <= e1)
        pk_ref = float(np.max(np.abs(v_ref[ev]))) if ev.any() else np.nan
        per_event = dict(t0=e0, t1=e1, peak_ref=pk_ref, onset=onset,
                         onset_thr=thr, baseline=base,
                         release=rel, release_lift=rel5, fall_90_10=fall)
        per.append(per_event)

    def med(key):
        xs = [p[key] for p in per if p[key] == p[key]]
        return float(np.median(xs)) if xs else float("nan")

    return dict(per_event=per,
                onset_med_s=med("onset"),
                release_med_s=med("release"),
                release_lift_med_s=med("release_lift"),
                fall_90_10_med_s=med("fall_90_10"))
