"""Generate figures for the false-lift / ESP-IDF validation report."""
import csv, json, sys
import numpy as np
sys.path.insert(0, 'analysis')
from common import compensate_ms5611, get_prom
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

D01_Q, D01_R = 1.0, 0.035
RUN1 = '20261023_221124_idf_elevator_2x.csv'
RUN2 = '20261023_221420_idf_elevator_2x.csv'

def load(fn, sid=0):
    with open('analysis/data/' + fn.replace('.csv', '.json')) as f:
        meta = json.load(f)
    P = {'t': [], 'd1': [], 't2': [], 'd2': []}
    V = []
    with open('analysis/data/' + fn) as f:
        next(f)
        for r in csv.reader(f):
            if len(r) < 6 or not r[0].isdigit():
                continue
            t = int(r[1]) / 1e6
            if r[2] == 'P' and r[3] == str(sid) and r[4] != '':
                P['t'].append(t); P['d1'].append(int(r[4]))
            elif r[2] == 'T' and r[3] == str(sid) and r[5] != '':
                P['t2'].append(t); P['d2'].append(int(r[5]))
            elif r[2] == 'V' and len(r) > 13 and r[12] != '':
                V.append((t, int(r[12]), int(r[13]),
                          float(r[14]) if len(r) > 14 and r[14] else 0.0))
    t = np.array(P['t']); d1 = np.array(P['d1'], dtype=float)
    t2 = np.array(P['t2']); d2 = np.array(P[sid if False else 'd2'], dtype=float) if False else np.array(P['d2'], dtype=float)
    d2z = d2[np.searchsorted(t2, t, side='right') - 1]
    pa, _ = compensate_ms5611(d1, d2z, get_prom(meta, sid))
    return t, pa, V

class D01:
    def __init__(self):
        self.init = False; self.p00 = 10.0; self.p01 = 0.0; self.p11 = 10.0
    def update(self, q, r, z, t):
        if not self.init:
            self.init = True; self.t_prev = t; self.h = z; self.v = 0.0
            return 0.0
        dt = t - self.t_prev
        if dt <= 0.0:
            return self.v
        self.t_prev = t
        xp0 = self.h + self.v * dt
        q00 = q * dt**4 / 4; q01 = q * dt**3 / 2; q11 = q * dt * dt
        pp00 = self.p00 + 2*dt*self.p01 + dt*dt*self.p11 + q00
        pp01 = self.p01 + dt*self.p11 + q01
        pp11 = self.p11 + q11
        S = pp00 + r
        k0 = pp00 / S; k1 = pp01 / S
        y = z - xp0
        self.h = xp0 + k0 * y; self.v = self.v + k1 * y
        self.p00 = pp00 - k0 * pp00; self.p01 = pp01 - k0 * pp01
        self.p11 = pp11 - k1 * pp01
        return self.v

def replay_d01(t, alt):
    f = D01()
    return np.array([f.update(D01_Q, D01_R, z, tt) for z, tt in zip(alt, t)])

# ---------- fig 1: run overviews ----------
for fn, tag, legs, stops in [
    (RUN1, 'run1', [(9.9, 33.8), (51.5, 76.1), (95.0, 118.9), (136.7, 161.2)],
     [40.9, 83.2, 126.0]),
    (RUN2, 'run2', [(8.6, 32.5), (50.0, 74.7), (92.8, 116.7), (134.7, 159.1)],
     [39.6, 81.8, 123.8])]:
    t, pa, V = load(fn, 0)
    t0 = t[0]
    t1, pa1, _ = load(fn, 1)
    alt0 = 44330.0 * (1.0 - (pa / 101325.0) ** 0.1902945)
    alt1 = 44330.0 * (1.0 - (pa1 / 101325.0) ** 0.1902945)
    fig, ax = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True)
    for (a, b) in legs:
        ax[0].axvspan(a, b, color='green', alpha=0.08)
    for s in stops:
        ax[0].axvline(s, color='red', ls='--', alpha=0.6)
    ax[0].plot(t - t0, alt0, lw=0.7, label='baro sid0 (fixed-ref compensated)')
    ax[0].plot(t1 - t0, alt1, lw=0.7, alpha=0.7, label='baro sid1')
    ax[0].set_ylabel('compensated altitude (m)')
    ax[0].legend(fontsize=8, loc='upper right'); ax[0].grid(alpha=0.3)
    ax[0].set_title(tag + ': 1>14>1>14 elevator (green = travel legs, red dash = stops)')
    names = {0: 'D01', 1: 'C03', 2: 'S4', 3: 'S5', 4: 'FUS'}
    bins = np.arange(0, (t[-1] - t0) + 5, 5)
    for eid in range(5):
        ts = [tt - t0 for tt, e, ev, vv in V if e == eid and ev == 1]
        h, _ = np.histogram(ts, bins=bins)
        ax[1].plot(bins[:-1] + 2.5, h, label=names[eid], lw=1.2)
    ax[1].set_ylabel('audio ON events / 5 s')
    ax[1].set_xlabel('t (s since stream start)')
    ax[1].legend(ncol=5, fontsize=8); ax[1].grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig('analysis/results/fig1_elevator_' + tag + '.png', dpi=140)
    plt.close()

# ---------- fig 2: p0 mechanism (run1 sid0) ----------
t, pa, V = load(RUN1, 0)
t0 = t[0]
p0run = np.cumsum(pa) / np.arange(1, len(pa) + 1)
p0run = np.where(np.arange(len(pa)) < 2000, p0run, p0run[1999])
alt_mov = 44330.0 * (1.0 - np.power(pa / p0run, 0.1903))
alt_fix = 44330.0 * (1.0 - (pa / 101325.0) ** 0.1902945)
tr = t - t0
fig, ax = plt.subplots(2, 1, figsize=(13, 8))
ax[0].plot(tr, pa / 1000, lw=0.8, label='measured pressure p(t)')
ax[0].plot(tr, p0run / 1000, lw=1.6, color='r',
           label='p0 = running mean of first 2000 samples (firmware ref)')
ax[0].axvline(50.0, color='k', ls=':', alpha=0.7, label='p0 freezes (sample 2000)')
ax[0].set_ylabel('pressure (kPa)')
ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)
ax[0].set_title('Moving reference: p0 climbs toward lower-floor pressure during the first descent')
ax[1].plot(tr, alt_fix, lw=0.9, label='altitude vs fixed 101325 Pa (true profile)')
ax[1].plot(tr, alt_mov, lw=0.9, color='r', alpha=0.85,
           label='altitude vs moving p0 (what estimators consumed)')
a1, b1 = 40.9 - 7.1, 58.6 - 7.1
ax[1].axvspan(a1, b1, color='orange', alpha=0.15)
ax[1].annotate('floor-1 dwell: true alt flat,\nmoving-ref alt climbs ~+0.45 m/s',
               xy=(49, 384), xytext=(60, 397), fontsize=8,
               arrowprops=dict(arrowstyle='->', color='k'))
ax[1].set_ylabel('altitude (m)'); ax[1].set_xlabel('t (s since stream start)')
ax[1].legend(fontsize=8, loc='lower left'); ax[1].grid(alpha=0.3)
plt.tight_layout()
plt.savefig('analysis/results/fig2_p0_mechanism.png', dpi=140)
plt.close()

# ---------- fig 3: dwell-1 zoom ----------
v_mov = replay_d01(t, alt_mov)
v_fix = replay_d01(t, alt_fix)
tones = np.array([(tt, (vv - 500) / 450) for tt, e, ev, vv in V
                  if e == 0 and ev in (1, 3)])
fig, ax = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
a, b = a1 - 3, b1 + 3
m = (tr >= a) & (tr <= b)
ax[0].plot(tr[m], alt_fix[m], lw=1.0, label='true altitude (fixed ref)')
ax[0].plot(tr[m], alt_mov[m], lw=1.0, color='r', alpha=0.8,
           label='firmware input (moving ref)')
ax[0].set_ylabel('altitude (m)'); ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)
ax[0].set_title('run1 floor-1 dwell (elevator stopped, IMU quiet at 1 g)')
ax[1].plot(tr[m], v_mov[m], lw=1.2, color='r', alpha=0.8,
           label='D01 replay on moving-ref input')
ax[1].plot(tr[m], v_fix[m], lw=1.2, color='g',
           label='D01 replay on fixed-ref input (post-fix behaviour)')
mt = (tones[:, 0] - t0 >= a) & (tones[:, 0] - t0 <= b)
ax[1].plot(tones[mt, 0] - t0, tones[mt, 1], 'o', ms=4, color='k',
           label='MCU tone-implied v (D01 sid0)')
ax[1].axhline(0.20, color='gray', ls='--', lw=0.8)
ax[1].axhline(0.05, color='gray', ls=':', lw=0.8)
ax[1].text(a + 0.4, 0.23, 'lift_on +0.20', fontsize=7, color='gray')
ax[1].text(a + 0.4, 0.065, 'lift_off +0.05', fontsize=7, color='gray')
ax[1].set_ylabel('estimated vertical velocity (m/s)')
ax[1].set_xlabel('t (s since stream start)')
ax[1].legend(fontsize=8, loc='upper right'); ax[1].grid(alpha=0.3)
plt.tight_layout()
plt.savefig('analysis/results/fig3_false_lift_dwell.png', dpi=140)
plt.close()

# ---------- fig 4: ON-time before/after ----------
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
labels = ['run1', 'run2']
false_old = [16.5, 17.5]; false_new = [0.0, 1.2]
tot_old = [74.6, 72.0]; tot_new = [54.9, 52.9]
x = np.arange(2); w = 0.35
ax[0].bar(x - w/2, false_old, w, label='moving p0 (old)')
ax[0].bar(x + w/2, false_new, w, label='fixed 101325 Pa (fix)')
ax[0].set_xticks(x); ax[0].set_xticklabels(labels)
ax[0].set_ylabel('false-lift ON-time at floor-1 dwell (s)')
ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3, axis='y')
ax[1].bar(x - w/2, tot_old, w, label='moving p0 (old)')
ax[1].bar(x + w/2, tot_new, w, label='fixed 101325 Pa (fix)')
ax[1].set_xticks(x); ax[1].set_xticklabels(labels)
ax[1].set_ylabel('total audio ON-time per run (s)')
ax[1].legend(fontsize=8); ax[1].grid(alpha=0.3, axis='y')
ax[0].set_title('False lift removed (audio policy replay)')
ax[1].set_title('Genuine lift preserved (~49 s ascent per run)')
plt.tight_layout()
plt.savefig('analysis/results/fig4_on_time.png', dpi=140)
plt.close()

# ---------- fig 5: CPU before/after ----------
old_cpu = {'D01': 52, 'C03': 1330, 'S4': 94, 'S5': 74, 'FUS': 45}
new_cpu = {'D01': 52, 'C03': 38, 'S4': 105, 'S5': 98, 'FUS': 75}
fig, ax = plt.subplots(figsize=(9, 4.2))
keys = list(old_cpu); x = np.arange(len(keys)); w = 0.35
ax.bar(x - w/2, [old_cpu[k] for k in keys], w,
       label='before fix (elevator run1 B-lines)')
ax.bar(x + w/2, [new_cpu[k] for k in keys], w,
       label='after fix (idf_p0fix_static B-lines)')
ax.set_yscale('log')
for i, k in enumerate(keys):
    ax.text(i - w/2, old_cpu[k] * 1.12, str(old_cpu[k]), ha='center', fontsize=8)
    ax.text(i + w/2, new_cpu[k] * 1.12, str(new_cpu[k]), ha='center', fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(keys)
ax.set_ylabel('per-update CPU (us, avg, log scale)')
ax.set_title('Per-estimator update cost on ESP32-S3 @ 240 MHz (C03: 1330 -> 38 us)')
ax.legend(fontsize=8); ax.grid(alpha=0.3, axis='y')
plt.tight_layout()
plt.savefig('analysis/results/fig5_cpu.png', dpi=140)
plt.close()

# ---------- fig 6: bench validation capture ----------
fn = '20261023_234521_idf_p0fix_static.csv'
t, pa, V = load(fn, 0)
t0 = t[0]
alt = 44330.0 * (1.0 - (pa / 101325.0) ** 0.1902945)
fig, ax = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
ax[0].plot(t - t0, alt, lw=0.7)
ax[0].set_ylabel('compensated altitude (m)'); ax[0].grid(alpha=0.3)
ax[0].set_title('idf_p0fix_static: 75 s stationary, fixed reference (0 seq drops, 0 bad frames)')
bins = np.arange(0, (t[-1] - t0) + 5, 5)
names = {0: 'D01', 1: 'C03', 2: 'S4', 3: 'S5', 4: 'FUS'}
for eid in range(5):
    ts = [tt - t0 for tt, e, ev, vv in V if e == eid and ev == 1]
    h, _ = np.histogram(ts, bins=bins)
    ax[1].plot(bins[:-1] + 2.5, h, label=names[eid], lw=1.2)
ax[1].set_ylabel('audio ON events / 5 s'); ax[1].set_xlabel('t (s)')
ax[1].legend(ncol=5, fontsize=8); ax[1].grid(alpha=0.3)
ax[1].set_title('Short threshold blips (1-3 s) only; no sustained false lift; no 50 s window')
plt.tight_layout()
plt.savefig('analysis/results/fig6_bench_validation.png', dpi=140)
plt.close()
print('figures saved')
