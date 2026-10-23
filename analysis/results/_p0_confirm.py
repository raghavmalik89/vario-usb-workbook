"""Confirm root cause of false lift: firmware p0 = running mean of first
2000 pressure samples is a MOVING altitude reference for the first ~50 s.

Simulate firmware-exact chain: p(t) from logged d1/d2 -> p0 running mean
(first 2000 fed samples, then frozen) -> alt_fw -> firmware-exact D01.
Compare v_fw against tone-implied v (eid0 = D01 sid0) in every phase.
"""
import csv, json, sys
import numpy as np
sys.path.insert(0, 'analysis')
from common import compensate_ms5611, get_prom

D01_Q, D01_R = 1.0, 0.035

def load(fn):
    with open('analysis/data/' + fn.replace('.csv', '.json')) as f:
        meta = json.load(f)
    P = {0: {'t': [], 'd1': [], 't2': [], 'd2': []},
         1: {'t': [], 'd1': [], 't2': [], 'd2': []}}
    V = []
    with open('analysis/data/' + fn) as f:
        next(f)
        for r in csv.reader(f):
            if len(r) < 6 or not r[0].isdigit():
                continue
            t = int(r[1]) / 1e6
            if r[2] == 'P' and r[3] != '' and r[4] != '':
                sid = int(r[3]); P[sid]['t'].append(t); P[sid]['d1'].append(int(r[4]))
            elif r[2] == 'T' and r[3] != '' and r[5] != '':
                sid = int(r[3]); P[sid]['t2'].append(t); P[sid]['d2'].append(int(r[5]))
            elif r[2] == 'V' and len(r) > 13 and r[12] != '':
                V.append((t, int(r[12]), int(r[13]),
                          float(r[14]) if len(r) > 14 and r[14] else 0.0))
    return P, V, meta

def firmware_alt(t, d1, d2z, meta, sid):
    """Exact baro_proc_altitude semantics: p0 = running mean of first 2000."""
    pa, _ = compensate_ms5611(d1, d2z, get_prom(meta, sid))
    p0 = np.cumsum(pa) / np.arange(1, len(pa) + 1)
    p0f = np.where(np.arange(len(pa)) < 2000, p0, p0[1999])  # frozen after 2000
    return 44330.0 * (1.0 - np.power(pa / p0f, 0.1903))

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

RUNS = [
    ('20261023_221124_idf_elevator_2x.csv', 'run1', 7.113,
     [(40.9, 58.6, 'dwell@1 after D1'), (83.2, 102.1, 'dwell@14 after A2'),
      (126.0, 143.8, 'dwell@1 after D3')]),
    ('20261023_221420_idf_elevator_2x.csv', 'run2', 7.049,
     [(39.6, 57.1, 'dwell@1 after D1'), (81.8, 100.0, 'dwell@14 after A2'),
      (123.8, 141.6, 'dwell@1 after D3')]),
]

for fn, tag, t0, dwells in RUNS:
    P, V, meta = load(fn)
    sid = 0
    t = np.array(P[sid]['t']); d1 = np.array(P[sid]['d1'], dtype=float)
    t2 = np.array(P[sid]['t2']); d2 = np.array(P[sid]['d2'], dtype=float)
    d2z = d2[np.searchsorted(t2, t, side='right') - 1]
    alt_fw = firmware_alt(t, d1, d2z, meta, sid)
    # p0-ready time
    i2000 = min(1999, len(t) - 1)
    print(f'== {tag}: p0 freezes at t={t[i2000]:.1f}s (2000th sample) ==')
    f = D01()
    v_fw = np.array([f.update(D01_Q, D01_R, z, tt) for z, tt in zip(alt_fw, t)])
    # fixed-reference replay for contrast
    pa, _ = compensate_ms5611(d1, d2z, get_prom(meta, sid))
    alt_fix = 44330.0 * (1.0 - (pa / 101325.0) ** 0.1902945)
    f2 = D01()
    v_fix = np.array([f2.update(D01_Q, D01_R, z, tt) for z, tt in zip(alt_fix, t)])
    # compare against tones (eid 0), per dwell
    tones = np.array([(tt, (val - 500) / 450) for tt, e, ev, val in V
                      if e == 0 and ev in (1, 3)])
    for a, b, name in dwells:
        m = (t >= a) & (t <= b)
        mt = (tones[:, 0] >= a) & (tones[:, 0] <= b)
        vi = tones[mt, 1] if mt.sum() else np.array([])
        # nearest v_fw samples to tone times
        idx = np.searchsorted(t, tones[mt, 0]).clip(1, len(t) - 1) if mt.sum() else []
        vf = v_fw[idx] if mt.sum() else np.array([])
        vx = v_fix[idx] if mt.sum() else np.array([])
        print(f'  {name} ({a:.0f}-{b:.0f}s):')
        print(f'    tones: n={len(vi)} implied p10/p50/p90 = '
              f'{np.percentile(vi,10):+.2f}/{np.percentile(vi,50):+.2f}/{np.percentile(vi,90):+.2f}' if len(vi) else '    tones: none')
        if len(vi):
            print(f'    v_fw  (p0 running mean): p10/p50/p90 = '
                  f'{np.percentile(vf,10):+.2f}/{np.percentile(vf,50):+.2f}/{np.percentile(vf,90):+.2f}, '
                  f'bias vs implied = {np.mean(vf - vi):+.3f}')
            print(f'    v_fix (fixed 101325 Pa): p10/p50/p90 = '
                  f'{np.percentile(vx,10):+.2f}/{np.percentile(vx,50):+.2f}/{np.percentile(vx,90):+.2f}, '
                  f'bias vs implied = {np.mean(vx - vi):+.3f}')
    # also overall matched comparison for v_fw
    idx = np.searchsorted(t, tones[:, 0]).clip(1, len(t) - 1)
    ok = np.abs(t[idx] - tones[:, 0]) < 0.03
    e_fw = v_fw[idx[ok]] - tones[ok, 1]
    e_fix = v_fix[idx[ok]] - tones[ok, 1]
    print(f'  ALL tones: n={ok.sum()}  bias v_fw={e_fw.mean():+.3f} p95|e|={np.percentile(np.abs(e_fw),95):.3f}'
          f' | bias v_fix={e_fix.mean():+.3f} p95|e|={np.percentile(np.abs(e_fix),95):.3f}')
