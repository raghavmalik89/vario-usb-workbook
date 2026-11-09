"""Flight recording analysis + four-filter replay for LOG00001.

Pipeline:
  1. Parse S/B/V rows; full integrity audit (seq, dt, malformed, markers).
  2. Replay C03/D01/S4/S5 from raw BMP581 pressure at real device timestamps
     using the frozen bench implementations + firmware configs (no tuning).
  3. Verify replayed C03 against the recorded C03 V rows.
  4. Metrics: static RMS, response delay, overshoot, settling, audio episodes,
     stability, transient tracking — pressure-proxy references labelled as such.
  5. Figures -> reports/flight/*.png ; machine-readable CSVs -> analysis/flight/.

Analysis-only: no firmware changes.
"""
import csv
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'filter_benchmark' / 'src'
sys.path.insert(0, str(SRC))
from filters.tracking import C03CVTracker          # noqa: E402
from filters.kalman import D01KalmanCV             # noqa: E402
from filters.stacked import STACKED                # noqa: E402

CSV = Path(__file__).parent / 'LOG00001_flight.csv'
OUTFIG = ROOT / 'reports' / 'flight'
OUTCSV = Path(__file__).parent
OUTFIG.mkdir(parents=True, exist_ok=True)

# frozen firmware configs (filter_benchmark/bench6/candidates.py)
P4_S4 = dict(tau_fast_s=0.35, q_slow=0.3, r_slow=0.035, v_scale=0.8,
             exit_v=0.12, exit_hold_s=0.25, w_floor=0.3, v_plaus_max=8.0,
             plaus_margin_m=0.3)
P4_S5 = dict(q=0.3, r=0.035, gate_sigma=3.5, q_gain=2.0, v_scale=1.0,
             v_plaus_max=8.0, plaus_margin_m=0.3)

HYST_ON, HYST_OFF = 0.20, 0.05

# ---------------- 1. parse + integrity ----------------
rows_s, b_seq, b_ts, b_p, b_t = [], [], [], [], []
v_seq, v_ts, v_flt, v_v, v_h = [], [], [], [], []
malformed = 0
nlines = 0
with open(CSV) as f:
    for line in f:
        nlines += 1
        parts = line.rstrip('\n').split(',')
        try:
            if parts[0] == 'S':
                rows_s.append(parts)
            elif parts[0] == 'B':
                b_seq.append(int(parts[1])); b_ts.append(int(parts[2]))
                b_p.append(int(parts[3])); b_t.append(int(parts[4]))
            elif parts[0] == 'V':
                v_seq.append(int(parts[1])); v_ts.append(int(parts[2]))
                v_flt.append(parts[3])
                v_v.append(int(parts[4])); v_h.append(int(parts[5]))
            else:
                malformed += 1
        except (ValueError, IndexError):
            malformed += 1

b_ts = np.array(b_ts); b_p = np.array(b_p); b_seq = np.array(b_seq)
v_ts = np.array(v_ts); v_v = np.array(v_v); v_h = np.array(v_h)

integrity = {}
integrity['lines'] = nlines
integrity['malformed'] = malformed
integrity['markers_S'] = rows_s
integrity['filters_in_V'] = sorted(set(v_flt))
integrity['n_B'] = len(b_ts)
integrity['n_V'] = len(v_ts)
integrity['span_s'] = (b_ts[-1] - b_ts[0]) / 1e6
integrity['B_seq_gaps'] = int(np.sum(np.diff(b_seq) != 1))
integrity['B_seq_dups'] = int(len(b_seq) - len(np.unique(b_seq)))
dtb = np.diff(b_ts) / 1000.0  # ms
integrity['B_dt_median_ms'] = float(np.median(dtb))
integrity['B_dt_p99_ms'] = float(np.percentile(dtb, 99))
integrity['B_dt_max_ms'] = float(np.max(dtb))
integrity['B_dt_outliers_gt100ms'] = int(np.sum(dtb > 100))
integrity['B_ts_monotonic'] = bool(np.all(dtb > 0))
integrity['B_rate_hz'] = len(b_ts) / integrity['span_s']
integrity['V_seq_gaps'] = int(np.sum(np.diff(v_seq) != 1))
dtv = np.diff(v_ts) / 1000.0
integrity['V_dt_median_ms'] = float(np.median(dtv))
integrity['V_rate_hz'] = len(v_ts) / integrity['span_s']
integrity['has_IMU'] = False
integrity['last_B_ts'] = int(b_ts[-1])
integrity['last_V_ts'] = int(v_ts[-1])
integrity['ends_V_after_last_B_ms'] = int((v_ts[-1] - b_ts[-1]) / 1000)
print(json.dumps(integrity, indent=1))

# ---------------- 2. replay ----------------
t0 = b_ts[0]
t_b = (b_ts - t0) / 1e6                      # seconds
pa = b_p / 64.0                            # BMP581 on-chip scale
ALT = lambda p: 44330.0 * (1.0 - (p / 101325.0) ** 0.1903)
z = ALT(pa)

filters = {
    'C03': C03CVTracker(q=1.0, r=0.035),
    'D01': D01KalmanCV(q=1.0, r=0.035),
    'S4': STACKED['S4_FastSlowGated'](**P4_S4),
    'S5': STACKED['S5_LightGateKF'](**P4_S5),
}
v_rep = {k: np.zeros_like(t_b) for k in filters}
for i in range(len(t_b)):
    for k, f in filters.items():
        v_rep[k][i] = f.update(z[i], t_b[i])

# recorded C03 (mm/s -> m/s) at V times
t_v = (v_ts - t0) / 1e6
v_rec = v_v / 1000.0
h_rec = v_h / 1000.0

# recorded-vs-replay altitude convention offset
h_isa_v = ALT(pa[np.clip(np.searchsorted(b_ts, v_ts), 0, len(b_ts) - 1)])
alt_offset = float(np.median(h_rec - h_isa_v))

# C03 verification: nearest-sample + best-lag comparison
def compare(lag_samples):
    idx = np.clip(np.searchsorted(b_ts, v_ts) + lag_samples, 0, len(b_ts) - 1)
    d = v_rep['C03'][idx] - v_rec
    return float(np.mean(d)), float(np.std(d)), float(np.max(np.abs(d))), float(np.sqrt(np.mean(d ** 2)))

verif = {'alt_offset_m': alt_offset}
best = None
for lag in range(-3, 4):
    m, s, mx, rms = compare(lag)
    verif[f'lag_{lag:+d}'] = dict(mean=m, std=s, max=mx, rms=rms)
    if best is None or rms < best[1]:
        best = (lag, rms)
verif['best_lag_samples'] = best[0]
# locate the worst deviation at best lag (for honest reporting of mismatch source)
_idx = np.clip(np.searchsorted(b_ts, v_ts) + best[0], 0, len(b_ts) - 1)
_d = np.abs(v_rep['C03'][_idx] - v_rec)
verif['worst_dev_t_s'] = float(t_v[int(np.argmax(_d))])
verif['worst_dev_mps'] = float(np.max(_d))
_keep = t_v > 5.0
verif['rms_excl_init_s'] = float(np.sqrt(np.mean(_d[_keep] ** 2)))
print('C03 verify:', json.dumps(verif, indent=1))

# ---------------- 3. pressure-derived reference ----------------
def sg_smooth(x, win, poly=3):
    """Savitzky-Golay (same convention as previous phases)."""
    half = win // 2
    xp = np.pad(x, half, mode='edge')
    out = np.zeros_like(x)
    for i in range(len(x)):
        seg = xp[i:i + win]
        c = np.polyfit(np.arange(win) * 0.0 + np.linspace(-half, half, win), seg, poly)
        out[i] = np.polyval(c, 0.0)
    return out

# faster: use numpy convolve-based SG via polynomial design matrix
def sg(x, win=81, poly=3):
    half = win // 2
    k = np.arange(-half, half + 1)
    A = np.vander(k, poly + 1, increasing=True)
    coef = np.linalg.pinv(A)[0]          # evaluate at 0 -> first row
    xp = np.pad(x, half, mode='edge')
    return np.convolve(xp, coef[::-1], mode='valid')

dt_b = np.median(np.diff(t_b))
v_ref_full = np.gradient(sg(z, 81), dt_b)
# light extra smoothing for stable reference velocity
v_ref_s = sg(v_ref_full, 41)
# SG group delay is exactly (N-1)/2 samples per stage at DC: 40 + 20 = 60 samples
# (1.5 s @ 40 Hz). Shift the reference EARLIER so it aligns with true motion,
# otherwise all delay/overshoot/settling metrics are contaminated.
SG_LAG = 60
v_ref = np.empty_like(v_ref_s)
v_ref[:-SG_LAG] = v_ref_s[SG_LAG:]
v_ref[-SG_LAG:] = v_ref_s[-1]

# ---------------- 4. metrics ----------------
# quiet segments: |v_ref| < 0.15 sustained >= 5 s (a real flight rarely has
# 8 s of <0.10 m/s; relaxation documented in the report)
quiet_mask = np.abs(v_ref) < 0.15
segs = []
i = 0
while i < len(t_b):
    if quiet_mask[i]:
        j = i
        while j < len(t_b) and quiet_mask[j]:
            j += 1
        if t_b[j - 1] - t_b[i] >= 5.0:
            segs.append((i, j))
        i = j
    else:
        i += 1
print('quiet segs (t_start,t_end):', [(round(t_b[a],1), round(t_b[b-1],1)) for a,b in segs])

metrics = {}
for k in filters:
    v = v_rep[k]
    q_idx = np.concatenate([np.arange(a, b) for a, b in segs]) if segs else np.array([], int)
    # exclude first 30 s (initialization) from quiet stats
    q_idx = q_idx[q_idx > int(30 / dt_b)]
    metrics[k] = {}
    metrics[k]['quiet_RMS_ms'] = float(np.sqrt(np.mean(v[q_idx] ** 2))) if len(q_idx) else None
    metrics[k]['quiet_p95_abs_ms'] = float(np.percentile(np.abs(v[q_idx]), 95)) if len(q_idx) else None
    metrics[k]['quiet_coverage_s'] = float(len(q_idx) * dt_b)

# transitions: |v_ref| crossing 0.5 m/s with sustained motion > 3 s
def find_transitions(thr=0.5, min_dur=3.0):
    above = np.abs(v_ref) > thr
    ev = []
    i = 0
    while i < len(t_b):
        if above[i]:
            j = i
            while j < len(t_b) and above[j]:
                j += 1
            if t_b[j - 1] - t_b[i] >= min_dur:
                ev.append((i, j))
            i = j
        else:
            i += 1
    return ev

trans = find_transitions()
# Response delay per transition: xcorr lag of filter vs aligned reference.
# np.correlate(y, x) argmax lag L means x[n] ~= y[n+L]; with x = filter,
# y = reference, L = -d where d = filter delay (positive d = filter slower).
# Transitions whose xcorr peak lands on the window edge are flagged invalid
# (adjacent events corrupt the estimate in a dense flight trace).
def resp_delay(v, i0, i1, win=6.0):
    w = int(win / dt_b)
    a = max(0, i0 - w)
    b = min(len(v), i1 + w)
    x = v[a:b] - np.mean(v[a:b])
    y = v_ref[a:b] - np.mean(v_ref[a:b])
    xc = np.correlate(y, x, mode='full')
    lags = np.arange(-len(x) + 1, len(x))
    sel = (lags >= -w) & (lags <= w)
    sub_xc = xc[sel]
    sub_lags = lags[sel]
    pk = int(np.argmax(sub_xc))
    valid = 0 < pk < len(sub_xc) - 1
    return float(-sub_lags[pk] * dt_b), bool(valid)

delays, overshoots, settles, n_valid = {}, {}, {}, {}
for k in filters:
    v = v_rep[k]
    dl, ov, st = [], [], []
    for (i0, i1) in trans:
        d, ok = resp_delay(v, i0, i1)
        if ok:
            dl.append(d)
    d_k = float(np.median(dl)) if dl else 0.0
    n_valid[k] = len(dl)
    # delay-compensated reference: shift truth LATER by the filter's delay so
    # overshoot/settling measure SHAPE error, not the delay itself
    d_samp = int(round(d_k / dt_b))
    v_ref_d = np.empty_like(v_ref)
    v_ref_d[d_samp:] = v_ref[:-d_samp] if d_samp else v_ref
    if d_samp:
        v_ref_d[:d_samp] = v_ref[0]
    for ti, (i0, i1) in enumerate(trans):
        # cap windows at the NEXT transition start: dense thermalling events
        # would otherwise contaminate overshoot/settling with the next burst
        i_next = trans[ti + 1][0] if ti + 1 < len(trans) else len(v)
        s0 = min(i0 + d_samp, len(v) - 1)
        seg = slice(s0, min(i_next, i0 + d_samp + int(5 / dt_b), len(v)))
        if seg.stop > seg.start:
            ov.append(float(np.max(np.abs(v[seg] - v_ref_d[seg]))))
        # settling: last time |v - v_ref_d| > 0.15 within [i0+d, i1+d+8s]
        end = min(len(v), i_next, i1 + d_samp + int(8 / dt_b))
        err = np.abs(v[s0:end] - v_ref_d[s0:end]) > 0.15
        if not err.any():
            st.append(0.0)
        else:
            st.append(float((np.max(np.where(err)[0])) * dt_b))
    delays[k] = dl
    overshoots[k] = ov
    settles[k] = st

# audio episodes per filter (hysteresis policy)
def audio_episodes(v, t):
    on = False
    eps = []
    for i in range(len(v)):
        if not on and v[i] > HYST_ON:
            on = True
            s = t[i]
        elif on and v[i] < HYST_OFF:
            on = False
            eps.append((s, t[i]))
    if on:
        eps.append((s, t[-1]))
    return eps

audio = {k: audio_episodes(v_rep[k], t_b) for k in filters}
# recorded C03 audio (from V rows: value1 mm/s through same policy)
rec_eps = audio_episodes(v_rec, t_v)

# proxy false-trigger analysis: audio ON while |v_ref| < 0.15 sustained
def proxy_false(eps, min_s=2.0):
    bad = []
    for (a, b) in eps:
        i0 = np.searchsorted(t_b, a)
        i1 = np.searchsorted(t_b, b)
        if i1 <= i0:
            continue
        run = 0.0
        for i in range(i0, i1):
            if abs(v_ref[i]) < 0.15:
                run += dt_b
                if run >= min_s:
                    bad.append((a, b))
                    break
            else:
                run = 0.0
    return bad

false_triggers = {k: proxy_false(audio[k]) for k in filters}
false_rec = proxy_false(rec_eps)

# stability: RMS of dv/dt (jerk) overall and in quiet
stab = {}
for k in filters:
    dv = np.diff(v_rep[k]) / np.diff(t_b)
    stab[k] = dict(jerk_rms=float(np.sqrt(np.mean(dv ** 2))))

# transient tracking: RMS error where |v_ref|>1.0, raw (delay-inclusive) and
# delay-compensated (shape accuracy) versions
fast = np.abs(v_ref) > 1.0
for k in filters:
    if fast.any():
        e = v_rep[k][fast] - v_ref[fast]
        metrics[k]['fast_RMS_error_ms'] = float(np.sqrt(np.mean(e ** 2)))
        metrics[k]['fast_bias_ms'] = float(np.mean(e))
        d_samp = int(round((float(np.median(delays[k])) if delays[k] else 0.0) / dt_b))
        v_ref_d = np.empty_like(v_ref)
        if d_samp:
            v_ref_d[d_samp:] = v_ref[:-d_samp]
            v_ref_d[:d_samp] = v_ref[0]
        else:
            v_ref_d[:] = v_ref
        e2 = v_rep[k][fast] - v_ref_d[fast]
        metrics[k]['fast_RMS_delaycomp_ms'] = float(np.sqrt(np.mean(e2 ** 2)))
    metrics[k]['delay_med_s'] = float(np.median(delays[k])) if delays[k] else None
    metrics[k]['delay_p75_s'] = float(np.percentile(delays[k], 75)) if len(delays[k]) > 3 else None
    metrics[k]['delay_n_valid'] = int(n_valid[k])
    metrics[k]['overshoot_med_ms'] = float(np.median(overshoots[k])) if overshoots[k] else None
    metrics[k]['settle_med_s'] = float(np.median(settles[k])) if settles[k] else None
    metrics[k]['audio_episodes'] = len(audio[k])
    metrics[k]['audio_on_s'] = float(sum(b - a for a, b in audio[k]))
    metrics[k]['audio_mean_dur_s'] = float(np.mean([b - a for a, b in audio[k]])) if audio[k] else 0.0
    metrics[k]['proxy_false_episodes'] = len(false_triggers[k])

summary = dict(integrity=integrity, c03_verify=verif,
               n_transitions=len(trans),
               transition_windows=[[float(t_b[a]), float(t_b[b])] for a, b in trans],
               quiet_segments=[[float(t_b[a]), float(t_b[b])] for a, b in segs],
               metrics=metrics, stability=stab,
               audio_episodes={k: [[float(a), float(b)] for a, b in audio[k]] for k in filters},
               audio_recorded_C03=[[float(a), float(b)] for a, b in rec_eps],
               proxy_false={k: [[float(a), float(b)] for a, b in false_triggers[k]] for k in filters},
               proxy_false_recorded=[[float(a), float(b)] for a, b in false_rec])
with open(OUTCSV / 'flight_metrics.json', 'w') as f:
    json.dump(summary, f, indent=1)

# persist replayed time series for the plotting script (no recompute needed)
np.savez_compressed(
    OUTCSV / 'replay_series.npz',
    t_b=t_b, z=z, v_ref=v_ref,
    **{f'v_{k}': v_rep[k] for k in filters},
    t_v=t_v, v_rec=v_rec, h_rec=h_rec,
    quiet=np.array([(a, b) for a, b in segs], dtype=int),
    trans=np.array([(a, b) for a, b in trans], dtype=int),
)
print('transitions:', len(trans), [[round(float(t_b[a]),1), round(float(t_b[b]),1)] for a,b in trans])
for k in filters:
    print(k, json.dumps(metrics[k]))
print('stability', json.dumps(stab))
print('recorded C03 audio eps:', len(rec_eps))
