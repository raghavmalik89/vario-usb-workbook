"""Hand/shake-regime audio analysis for BMP581+LSM6DSV16X handtest1_120s.
Extracts per-estimator virtual-audio episodes from V frames, masking stats,
and a timeline figure. Writes:
  analysis/output/handshake_lsm_audio_summary.csv
  analysis/output/handshake_lsm_masking.csv
  analysis/output/fig_handshake_audio_timeline.png
"""
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

CSV = 'analysis/data/20261025_223041_idf_bmp581LSM6DS_handtest1_120s.csv'
EST = ['D01', 'C03', 'S4', 'S5', 'FUS']
LSB_G = 4096.0

t0 = None
v_rows = []       # (t_s, eid, ev, val)
e_times = []      # E1/E2 times
stale_runs = []   # (start_s, end_s) consecutive identical accel > 5 frames
i_raw_prev = None
stale_start = None
n_i = 0
with open(CSV, newline='') as f:
    for r in csv.DictReader(f):
        try:
            t = int(r['t_us'])
        except (ValueError, TypeError):
            continue
        if t0 is None:
            t0 = t
        t = (t - t0) / 1e6
        ty = r['type']
        if ty == 'V':
            try:
                v_rows.append((t, int(r['eid']), int(r['ev']), int(float(r['val']))))
            except (ValueError, TypeError):
                pass
        elif ty == 'E':
            e_times.append((t, r['sid']))
        elif ty == 'I':
            n_i += 1
            try:
                cur = (int(r['ax']), int(r['ay']), int(r['az']))
            except (ValueError, TypeError):
                continue
            if cur == i_raw_prev:
                if stale_start is None:
                    stale_start = t
            else:
                if stale_start is not None and t - stale_start > 0.05:
                    stale_runs.append((stale_start, t))
                stale_start = None
            i_raw_prev = cur

# episodes per estimator
eps = {e: [] for e in range(5)}
open_ep = {}
for t, eid, ev, val in v_rows:
    est = eid % 5
    if ev == 1:
        open_ep[est] = [t, None, val, val]   # on_t, off_t, peak_tone, last_tone
    elif ev == 3 and est in open_ep:
        open_ep[est][3] = val
        open_ep[est][2] = max(open_ep[est][2], val)
    elif ev == 2 and est in open_ep:
        open_ep[est][1] = t
        eps[est].append(open_ep.pop(est))
for est, ep in open_ep.items():
    ep[1] = None
    eps[est].append(ep)

# masking windows for IMU-dependent (FUS) evaluation: E frames +-0.5 s + stale runs +0.5 s margin
mask = []
for t, _ in e_times:
    mask.append((max(0, t - 0.5), t + 0.5))
for a, b in stale_runs:
    mask.append((max(0, a - 0.5), b + 0.5))
mask.sort()
merged = []
for a, b in mask:
    if merged and a <= merged[-1][1]:
        merged[-1][1] = max(merged[-1][1], b)
    else:
        merged.append([a, b])
mask_s = sum(b - a for a, b in merged)

rows = []
for e in range(5):
    ep = eps[e]
    durs = [b - a for a, b, _, _ in ep if b is not None]
    peaks = [(pk - 500) / 450 for _, _, pk, _ in ep]
    startup = sum(1 for a, _, _, _ in ep if a < 10.0)
    rows.append({
        'estimator': EST[e], 'episodes': len(ep),
        'startup_episodes_t0_10s': startup,
        'total_on_s': f'{sum(durs):.2f}',
        'mean_dur_s': f'{(sum(durs)/len(durs)) if durs else 0:.2f}',
        'max_dur_s': f'{max(durs) if durs else 0:.2f}',
        'brief_lt_1p5s': sum(1 for d in durs if d < 1.5),
        'tone_peak_mps': f'{max(peaks) if peaks else 0:.2f}',
        'tone_mean_peak_mps': f'{(sum(peaks)/len(peaks)) if peaks else 0:.2f}',
    })

with open('analysis/output/handshake_lsm_audio_summary.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
with open('analysis/output/handshake_lsm_masking.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['capture', 'E_frames', 'stale_runs_gt50ms', 'masked_intervals',
                'masked_s', 'mask_pct', 'I_frames'])
    w.writerow(['20261025_223041_handtest1_120s', len(e_times), len(stale_runs),
                len(merged), f'{mask_s:.2f}', f'{100*mask_s/120:.2f}', n_i])
for r in rows:
    print(r)
print('masking: E', len(e_times), 'stale_runs', len(stale_runs),
      'masked_s', round(mask_s, 2), f'({100*mask_s/120:.1f}%)')

# timeline figure: ON episodes per estimator
fig, ax = plt.subplots(figsize=(11, 3.4))
for e in range(5):
    for a, b, pk, _ in eps[e]:
        ax.plot([a, b if b is not None else 120], [e, e], lw=7,
                solid_capstyle='butt', color=f'C{e}')
ax.set_yticks(range(5))
ax.set_yticklabels(EST)
ax.set_xlabel('device time (s)')
ax.set_xlim(0, 120)
ax.set_title('handtest1_120s — audio ON episodes (V frames), BMP581 + LSM6DSV16X')
ax.grid(axis='x', alpha=0.3)
fig.tight_layout()
fig.savefig('analysis/output/fig_handshake_audio_timeline.png', dpi=150)
print('figure written')
