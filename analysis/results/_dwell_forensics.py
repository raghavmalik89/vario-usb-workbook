"""Forensic analysis of false-lift audio at elevator stops.

Reconciles: raw d1/d2, compensated altitude, IMU vertical accel,
offline firmware-exact D01 replay, and tone-implied v, time-aligned
around each elevator stop. Run 1 + Run 2.
"""
import csv, json, sys
import numpy as np
sys.path.insert(0, 'analysis')
from common import compensate_ms5611, get_prom

FN1 = '20261023_221124_idf_elevator_2x.csv'
FN2 = '20261023_221420_idf_elevator_2x.csv'
D01_Q, D01_R = 1.0, 0.035

def load(fn):
    with open('analysis/data/' + fn.replace('.csv', '.json')) as f:
        meta = json.load(f)
    P = {0: {'t': [], 'd1': [], 't2': [], 'd2': []},
         1: {'t': [], 'd1': [], 't2': [], 'd2': []}}
    IMU = {'t': [], 'ax': [], 'ay': [], 'az': []}
    V = []
    with open('analysis/data/' + fn) as f:
        next(f)
        for r in csv.reader(f):
            if len(r) < 6 or not r[0].isdigit():
                continue
            t = int(r[1]) / 1e6
            if r[2] == 'P' and r[3] != '' and r[4] != '':
                sid = int(r[3])
                P[sid]['t'].append(t); P[sid]['d1'].append(int(r[4]))
            elif r[2] == 'T' and r[3] != '' and r[5] != '':
                sid = int(r[3])
                P[sid]['t2'].append(t); P[sid]['d2'].append(int(r[5]))
            elif r[2] == 'I' and len(r) > 11 and r[6] != '':
                IMU['t'].append(t)
                for k, i in (('ax', 6), ('ay', 7), ('az', 8)):
                    IMU[k].append(float(r[i]))
            elif r[2] == 'V' and len(r) > 13 and r[12] != '':
                V.append((t, int(r[12]), int(r[13]),
                          float(r[14]) if len(r) > 14 and r[14] else 0.0))
    out = {}
    for sid in (0, 1):
        t = np.array(P[sid]['t']); d1 = np.array(P[sid]['d1'], dtype=float)
        t2 = np.array(P[sid]['t2']); d2 = np.array(P[sid]['d2'], dtype=float)
        d2z = d2[np.searchsorted(t2, t, side='right') - 1]
        pa, te = compensate_ms5611(d1, d2z, get_prom(meta, sid))
        alt = 44330.0 * (1.0 - (pa / 101325.0) ** 0.1902945)
        c5 = get_prom(meta, sid)[4]
        dt_adc = d2 - c5 * 256.0                      # temperature channel, raw ADC
        # dT at pressure times (ZOH), converted to 0.01C units like MS5611
        temp = 2000.0 + (d2z - c5 * 256.0) * get_prom(meta, sid)[5] / 2**23
        out[sid] = dict(t=t, d1=d1, alt=alt, temp=temp)
    for k in IMU:
        IMU[k] = np.array(IMU[k])
    return out, IMU, V

# ---- firmware-exact D01 (transcribed from estimators.c, doubles) ----
class D01:
    def __init__(self):
        self.init = False
        self.p00 = 10.0; self.p01 = 0.0; self.p11 = 10.0  # d01_reset: P = eye(2)*10
    def update(self, q, r, z, t):
        if not self.init:
            self.init = True; self.t_prev = t; self.h = z; self.v = 0.0
            return 0.0
        dt = t - self.t_prev
        if dt <= 0.0:
            return self.v
        self.t_prev = t
        xp0 = self.h + self.v * dt
        q00 = q * dt**4 / 4.0; q01 = q * dt**3 / 2.0; q11 = q * dt * dt
        pp00 = self.p00 + 2*dt*self.p01 + dt*dt*self.p11 + q00
        pp01 = self.p01 + dt*self.p11 + q01
        pp11 = self.p11 + q11
        y = z - xp0
        S = pp00 + r
        k0 = pp00 / S; k1 = pp01 / S
        self.h = xp0 + k0 * y
        self.v = self.v + k1 * y
        self.p00 = pp00 - k0 * pp00
        self.p01 = pp01 - k0 * pp01
        self.p11 = pp11 - k1 * pp01
        return self.v

def analyze(fn, stops, tag):
    data, imu, V = load(fn)
    print(f'########## {tag} {fn} ##########')
    t0 = data[0]['t'][0]
    # D01 replay per sid
    replay = {}
    for sid in (0, 1):
        f = D01()
        # check d01_reset for initial P; firmware uses d01_reset -> inspect later
        vs = np.array([f.update(D01_Q, D01_R, z, t) for z, t in
                       zip(data[sid]['alt'], data[sid]['t'])])
        replay[sid] = vs
    # compare replayed D01 sid0 to tone-implied v (eid 0) over whole run
    tones = [(t, (val - 500) / 450) for t, e, ev, val in V if e == 0 and ev in (1, 3)]
    if tones:
        tt = np.array([x[0] for x in tones]); vv = np.array([x[1] for x in tones])
        # nearest replay sample within 30 ms
        rt = data[0]['t']; rv = replay[0]
        idx = np.searchsorted(rt, tt).clip(1, len(rt) - 1)
        near = np.where(np.abs(rt[idx] - tt) < 0.03)[0]
        err = vv[near] - rv[idx[near]]
        print(f'D01 sid0: {len(tones)} tone samples, {len(near)} matched, '
              f'replay-vs-implied: bias={err.mean():+.3f} m/s, '
              f'std={err.std():.3f}, |err| p95={np.percentile(np.abs(err),95):.3f}')
    for stop_t, name in stops:
        print(f'\n--- stop {name} at t={stop_t:.1f}s (window {stop_t-6:.0f}..{stop_t+18:.0f}) ---')
        a, b = stop_t - 6, stop_t + 18
        m = (data[0]['t'] >= a) & (data[0]['t'] <= b)
        t = data[0]['t'][m]; alt0 = data[0]['alt'][m]; alt1 = data[1]['alt'][m]
        d1 = data[0]['d1'][m]; temp = data[0]['temp'][m]
        rv = replay[0][m]
        mi = (imu['t'] >= a) & (imu['t'] <= b)
        # 1 s bins for IMU ax mean
        print('  t     alt0    alt1     dH/dt   D01v   d1(M)  T(C)   ax_mean  az_mean')
        for ts in np.arange(a, b, 2.0):
            mm = (t >= ts) & (t < ts + 2)
            if mm.sum() < 5:
                continue
            mim = (imu['t'] >= ts) & (imu['t'] < ts + 2)
            axm = imu['ax'][mim].mean() if mim.sum() else np.nan
            azm = imu['az'][mim].mean() if mim.sum() else np.nan
            dh = (alt0[mm][-1] - alt0[mm][0]) / (t[mm][-1] - t[mm][0])
            print(f'  {ts:6.1f} {alt0[mm].mean():7.2f} {alt1[mm].mean():7.2f} '
                  f'{dh:+6.2f} {rv[mm].mean():+6.2f} {d1[mm].mean()/1e6:6.3f} '
                  f'{temp[mm].mean()/100:6.2f} {axm:+7.3f} {azm:+7.3f}')
    return data, imu, V, replay

# stops in ABSOLUTE time (t0 ~= 7.11s); from leg analysis run1/run2
STOPS1 = [(40.9, 'floor-1 after descent-1'), (83.2, 'floor-14 after ascent-2'),
          (126.0, 'floor-1 after descent-3')]
STOPS2 = [(39.6, 'floor-1 after descent-1'), (81.8, 'floor-14 after ascent-2'),
          (123.8, 'floor-1 after descent-3')]

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

for fn, stops, tag in ((FN1, STOPS1, 'run1'), (FN2, STOPS2, 'run2')):
    data, imu, V, replay = analyze(fn, stops, tag)
    # zoom figure around first stop
    st = stops[0][0]
    a, b = st - 8, st + 25
    fig, ax = plt.subplots(4, 1, figsize=(14, 11), sharex=True)
    for sid in (0, 1):
        m = (data[sid]['t'] >= a) & (data[sid]['t'] <= b)
        ax[0].plot(data[sid]['t'][m], data[sid]['alt'][m], lw=0.8, label=f'alt sid{sid}')
        ax[2].plot(data[sid]['t'][m], data[sid]['d1'][m] / 1e6, lw=0.6, label=f'd1 sid{sid}')
        ax[3].plot(data[sid]['t'][m], data[sid]['temp'][m] / 100, lw=0.8,
                   label=f'T sid{sid}')
    m0 = (data[0]['t'] >= a) & (data[0]['t'] <= b)
    ax[1].plot(data[0]['t'][m0], replay[0][m0], lw=1.0, color='k', label='D01 replay v (sid0)')
    tones = [(t, (val - 500) / 450) for t, e, ev, val in V if e == 0 and ev in (1, 3)]
    for tt, vv in tones:
        if a <= tt <= b:
            ax[1].plot(tt, vv, 'rv', ms=4)
    mi = (imu['t'] >= a) & (imu['t'] <= b)
    ax1b = ax[1].twinx()
    ax1b.plot(imu['t'][mi], imu['ax'][mi], color='tab:green', lw=0.5, alpha=0.6)
    ax1b.set_ylabel('ax (m/s2)', color='tab:green')
    for x in (st,):
        for axx in ax:
            axx.axvline(x, color='r', ls='--', alpha=0.5)
    ax[0].set_ylabel('comp. altitude (m)')
    ax[1].set_ylabel('v (m/s)')
    ax[2].set_ylabel('d1 raw (M LSB)')
    ax[3].set_ylabel('T (C)')
    ax[3].set_xlabel('t (s, absolute)')
    for axx in ax:
        axx.grid(alpha=0.3); axx.legend(fontsize=8, loc='upper left')
    ax[0].set_title(f'{tag}: first stop (dashed red = detected leg end)')
    plt.tight_layout()
    plt.savefig(f'analysis/results/dwell_{tag}.png', dpi=110)
    plt.close()
print('\nplots saved: analysis/results/dwell_run1.png, dwell_run2.png')
