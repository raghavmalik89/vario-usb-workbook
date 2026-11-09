"""Flight benchmark figures for LOG00001(2).CSV — 5 requested plots.

Loads replayed series from analysis/flight/replay_series.npz (produced by
flight_analysis.py) and metrics from flight_metrics.json. Output:
reports/flight/fig1..fig5 .png
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports' / 'flight'
OUT.mkdir(parents=True, exist_ok=True)

d = np.load(ROOT / 'analysis' / 'flight' / 'replay_series.npz')
M = json.load(open(ROOT / 'analysis' / 'flight' / 'flight_metrics.json'))

t_b, z, v_ref = d['t_b'], d['z'], d['v_ref']
FILTERS = ['C03', 'D01', 'S4', 'S5']
v = {k: d[f'v_{k}'] for k in FILTERS}
t_v, v_rec = d['t_v'], d['v_rec']
quiet, trans = d['quiet'], d['trans']
HYST_ON, HYST_OFF = 0.20, 0.05

C = {'C03': '#d62728', 'D01': '#ff9896', 'S4': '#1f77b4', 'S5': '#2ca02c'}
plt.rcParams.update({'font.size': 9, 'axes.grid': True, 'grid.alpha': 0.3})


def audio_episodes(vv, t):
    on, eps = False, []
    for i in range(len(vv)):
        if not on and vv[i] > HYST_ON:
            on, s = True, t[i]
        elif on and vv[i] < HYST_OFF:
            on = False
            eps.append((s, t[i]))
    if on:
        eps.append((s, t[-1]))
    return eps


# ---------- fig 1: overview (altitude + velocity history) ----------
fig, ax = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
ax[0].plot(t_b, z, lw=0.7, color='k')
ax[0].set_ylabel('Altitude ISA (m)')
ax[0].set_title('LOG00001 flight overview — altitude and vertical speed')
ax[1].plot(t_b, v_ref, lw=0.6, color='0.6', label='pressure-derived ref (SG, aligned)')
for k in FILTERS:
    ax[1].plot(t_b, v[k], lw=0.7, color=C[k], label=k)
ax[1].axhline(HYST_ON, color='r', ls='--', lw=0.7)
ax[1].axhline(-HYST_ON, color='r', ls='--', lw=0.7)
ax[1].set_ylabel('Vertical speed (m/s)')
ax[1].set_xlabel('Time (s)')
ax[1].legend(loc='upper right', ncol=5, fontsize=8)
fig.tight_layout()
fig.savefig(OUT / 'fig1_overview.png', dpi=150)
plt.close(fig)

# ---------- fig 2: all four filters overlaid ----------
fig, ax = plt.subplots(figsize=(11, 4.2))
ax.plot(t_b, v_ref, lw=0.6, color='0.75', label='ref')
for k in FILTERS:
    ax.plot(t_b, v[k], lw=0.8, color=C[k], label=k)
ax.set_xlabel('Time (s)')
ax.set_ylabel('Vertical speed (m/s)')
ax.set_title('Four frozen filters replayed on identical BMP581 pressure (full flight)')
ax.legend(loc='upper right', ncol=5, fontsize=8)
fig.tight_layout()
fig.savefig(OUT / 'fig2_overlay.png', dpi=150)
plt.close(fig)

# ---------- fig 3: zoomed climb/sink transitions ----------
tw = M['transition_windows']
# pick three representative windows: longest, an early short one, a mid one
order = sorted(range(len(tw)), key=lambda i: -(tw[i][1] - tw[i][0]))
picks = sorted([order[0], order[len(order) // 3], order[2 * len(order) // 3]])
fig, axes = plt.subplots(len(picks), 1, figsize=(11, 3.2 * len(picks)), sharex=False)
for ax, pi in zip(np.atleast_1d(axes), picks):
    a, b = tw[pi]
    m = (t_b >= a - 10) & (t_b <= b + 10)
    ax.plot(t_b[m], v_ref[m], lw=1.0, color='0.6', label='ref')
    for k in FILTERS:
        ax.plot(t_b[m], v[k][m], lw=1.0, color=C[k], label=k)
    ax.axhline(HYST_ON, color='r', ls='--', lw=0.6)
    ax.axhline(-HYST_ON, color='r', ls='--', lw=0.6)
    ax.axvspan(a, b, color='orange', alpha=0.15)
    ax.set_ylabel('v (m/s)')
    ax.set_title(f'transition window {a:.1f}–{b:.1f} s (shaded)')
axes = np.atleast_1d(axes)
axes[-1].set_xlabel('Time (s)')
axes[0].legend(loc='upper right', ncol=5, fontsize=8)
fig.suptitle('Zoomed climb/sink transitions (shaded = |ref| > 0.5 m/s sustained ≥ 3 s)')
fig.tight_layout(rect=(0, 0, 1, 0.96))
fig.savefig(OUT / 'fig3_transitions.png', dpi=150)
plt.close(fig)

# ---------- fig 4: quiet-segment noise ----------
q_idx = np.concatenate([np.arange(a, b) for a, b in quiet])
q_idx = q_idx[q_idx > int(30 / np.median(np.diff(t_b)))]
fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
m = (t_b >= t_b[q_idx].min() - 5) & (t_b <= t_b[q_idx].max() + 5)
ax[0].plot(t_b[m], v_ref[m], lw=0.8, color='0.6', label='ref')
for k in FILTERS:
    ax[0].plot(t_b[m], v[k][m], lw=0.8, color=C[k], label=k)
ax[0].axhline(HYST_ON, color='r', ls='--', lw=0.7)
ax[0].axhline(-HYST_ON, color='r', ls='--', lw=0.7)
ax[0].set_xlabel('Time (s)')
ax[0].set_ylabel('v (m/s)')
ax[0].set_title('Quiet segment (landing rollout, 37 s total)')
ax[0].legend(fontsize=8)
bins = np.linspace(-0.35, 0.35, 71)
for k in FILTERS:
    ax[1].hist(v[k][q_idx], bins=bins, histtype='step', color=C[k],
               label=f'{k} RMS={M["metrics"][k]["quiet_RMS_ms"]*1000:.0f} mm/s')
ax[1].set_xlabel('Vertical speed (m/s)')
ax[1].set_ylabel('Samples')
ax[1].set_title('Velocity distribution in quiet segments (n = %d samples)' % len(q_idx))
ax[1].legend(fontsize=8)
fig.tight_layout()
fig.savefig(OUT / 'fig4_quiet.png', dpi=150)
plt.close(fig)

# ---------- fig 5: audio-trigger timing ----------
fig, ax = plt.subplots(figsize=(11, 4.8))
ax.plot(t_b, v_ref, lw=0.5, color='0.8', label='ref')
ax.plot(t_v, v_rec, lw=0.7, color='0.4', ls=':', label='recorded C03 (device)')
rows = [('recorded C03', None, '0.2')] + [(k, k, C[k]) for k in FILTERS]
for r, (name, key, col) in enumerate(rows):
    eps = M['audio_recorded_C03'] if key is None else M['audio_episodes'][key]
    for (a, b) in eps:
        ax.barh(r, b - a, left=a, height=0.7, color=col, edgecolor='none')
ax.axhline(HYST_ON, color='r', ls='--', lw=0.6)
ax.set_yticks(range(len(rows)))
ax.set_yticklabels([r[0] for r in rows])
ax.set_xlabel('Time (s)')
ax.set_ylabel('Audio ON episodes (+0.20 / −0.05 m/s hysteresis)')
ax.set_title('Audio-trigger episodes per filter (bars = ON; top row = device-recorded C03)')
ax.legend(loc='upper right', fontsize=8)
fig.tight_layout()
fig.savefig(OUT / 'fig5_audio.png', dpi=150)
plt.close(fig)

print('figures written to', OUT)
for p in sorted(OUT.glob('fig*.png')):
    print(' ', p.name, p.stat().st_size, 'bytes')
