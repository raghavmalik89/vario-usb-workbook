"""Publication-quality graph for the LinkedIn article
'Flying the Breadboard - From Prototype to Real Flight Data'.

Segment chosen: final approach and landing (t ~ 588-668 s): a strong sink
burst (-4 m/s), recovery, flare and quiet rollout - demonstrating both
responsiveness (steep transient) and smoothness (quiet segment) differences.

Output: reports/flight/linkedin_flying_the_breadboard.png (300 dpi) + .svg
Data: analysis/flight/replay_series.npz (from flight_analysis.py)
"""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports' / 'flight'

d = np.load(ROOT / 'analysis' / 'flight' / 'replay_series.npz')
t_b, v_ref = d['t_b'], d['v_ref']
FILTERS = ['C03', 'D01', 'S4', 'S5']
v = {k: d[f'v_{k}'] for k in FILTERS}

T0, T1 = 588.0, 668.0
m = (t_b >= T0) & (t_b <= T1)

# ---- style ----
plt.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 11,
    'axes.edgecolor': '#444444',
    'axes.linewidth': 0.9,
    'axes.grid': True,
    'grid.color': '#d9d9d9',
    'grid.linewidth': 0.6,
    'xtick.color': '#444444',
    'ytick.color': '#444444',
    'figure.facecolor': 'white',
})
C = {'C03': '#C0392B', 'D01': '#E67E22', 'S4': '#2471A3', 'S5': '#1E8449'}

fig, ax = plt.subplots(figsize=(11.5, 6.2), dpi=300)

ax.plot(t_b[m], v_ref[m], lw=1.1, color='#7F8C8D', ls=(0, (4, 2)),
        label='Pressure-derived reference (Savitzky–Golay)', zorder=2)
LW = {'C03': 1.7, 'D01': 1.4, 'S4': 1.7, 'S5': 1.7}
for k in FILTERS:
    ax.plot(t_b[m], v[k][m], lw=LW[k], color=C[k],
            label=f'{k}', zorder=3)

ax.axhline(0.20, color='#C0392B', lw=0.7, ls=':', alpha=0.55)
ax.axhline(0.05, color='#C0392B', lw=0.7, ls=':', alpha=0.30)
ax.annotate('audio ON threshold +0.20 m/s', xy=(T1 - 0.4, 0.20),
            xytext=(T1 - 8.5, 0.62), fontsize=8.5, color='#922B21',
            arrowprops=dict(arrowstyle='-', color='#922B21', lw=0.6))

ax.set_xlim(T0, T1)
ax.set_ylim(-4.6, 4.9)
ax.set_xlabel('Time (s)', fontsize=12)
ax.set_ylabel('Vertical speed (m/s)', fontsize=12)
ax.set_title('Flying the Breadboard — From Prototype to Real Flight Data',
             fontsize=14.5, fontweight='bold', pad=14)
ax.text((T0 + T1) / 2, 1.045, '',
        transform=ax.transAxes)
fig.text(0.5, 0.905,
         'Four variometer filters replayed offline on recorded BMP581 barometer data — '
         'final approach, landing and rollout of a paragliding flight',
         ha='center', fontsize=10.5, color='#555555')
leg = ax.legend(loc='upper right', frameon=True, framealpha=0.95,
                edgecolor='#cccccc', fontsize=9.5, ncol=1)
fig.text(0.995, 0.012,
         'Recorded flight data · offline replay · frozen filter configurations · '
         'Vario USB project',
         ha='right', fontsize=8, color='#999999')

fig.tight_layout(rect=(0, 0.02, 1, 0.90))
fig.savefig(OUT / 'linkedin_flying_the_breadboard.png', dpi=300)
fig.savefig(OUT / 'linkedin_flying_the_breadboard.svg')
print('wrote', OUT / 'linkedin_flying_the_breadboard.png')
print('wrote', OUT / 'linkedin_flying_the_breadboard.svg')
