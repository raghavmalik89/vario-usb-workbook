"""Static validation for the LSM6DSV16X bring-up captures.

Usage: python analysis/lsm_bringup_check.py <csv> [more csv ...]
Checks: E-frame distribution, I-stream rate, sample freshness, gravity
magnitude, gyro stability, baro pressure/altitude sanity.
"""
import csv
import math
import sys


def _sd(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))

LSB_G = 4096.0
LSB_DPS = 65.5

for path in sys.argv[1:]:
    t0 = None
    e_ts = []
    i_ts, i_raw = [], []
    p_raw = []
    n_bad = 0
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            typ = row['type']
            try:
                t = int(row['t_us']) / 1e6
            except ValueError:
                n_bad += 1
                continue
            if t0 is None:
                t0 = t
            t -= t0
            if typ == 'E':
                e_ts.append(t)
            elif typ == 'I':
                i_ts.append(t)
                i_raw.append(tuple(int(row[k]) for k in ('ax', 'ay', 'az', 'gx', 'gy', 'gz')))
            elif typ == 'P':
                try:
                    p_raw.append((t, int(row['d1'])))
                except ValueError:
                    n_bad += 1

    dur = (i_ts[-1] if i_ts else 0)
    print(f'== {path}')
    print(f'  duration {dur:.1f}s   I frames {len(i_ts)}  P frames {len(p_raw)}  bad {n_bad}')
    print(f'  E frames: {len(e_ts)}', end='')
    if e_ts:
        buckets = [0] * 6
        for t in e_ts:
            b = min(int(t // 5), 5)
            buckets[b] += 1
        print('  per-5s:', buckets, ' first:', f'{e_ts[0]:.2f}s', ' last:', f'{e_ts[-1]:.2f}s')
    else:
        print()

    # I stream rate per 5 s window
    if i_ts:
        rates = []
        for w in range(0, int(dur) // 5):
            n = sum(1 for t in i_ts if w * 5 <= t < (w + 1) * 5)
            rates.append(f'{n/5:.0f}')
        print('  I rate per-5s (Hz):', ' '.join(rates))

    # freshness: fraction of consecutive identical accel vectors (stale reuse)
    if i_raw:
        same = sum(1 for a, b in zip(i_raw, i_raw[1:]) if a == b)
        print(f'  stale repeats: {same}/{len(i_raw)-1} ({100*same/max(1,len(i_raw)-1):.1f}%)')

    # gravity + gyro stats on raw counts
    if i_raw:
        import math
        n0 = min(200, len(i_raw) // 10)
        mag = [math.sqrt(sum(c * c for c in r[:3])) / LSB_G for r in i_raw[n0:]]
        am = sum(mag) / len(mag)
        av = sum((x - am) ** 2 for x in mag) / len(mag)
        gm = [sum(abs(c) for c in r[3:]) / LSB_DPS for r in i_raw[n0:]]
        gmean = sum(gm) / len(gm)
        ax = sum(r[0] for r in i_raw[n0:]) / len(i_raw[n0:]) / LSB_G
        ay = sum(r[1] for r in i_raw[n0:]) / len(i_raw[n0:]) / LSB_G
        az = sum(r[2] for r in i_raw[n0:]) / len(i_raw[n0:]) / LSB_G
        print(f'  |a| = {am:.4f} +/- {math.sqrt(av):.4f} g   a=({ax:.3f},{ay:.3f},{az:.3f}) g')
        print(f'  |gyro| mean {gmean:.3f} dps  (per-axis std dps: ' +
              ' '.join(f'{_sd([r[k] for r in i_raw[n0:]])/LSB_DPS:.3f}'
                       for k in range(3, 6)) + ')')

    if p_raw:
        n0 = min(100, len(p_raw) // 10)
        pa = [p / 64.0 for _, p in p_raw[n0:]]  # scale=pa_x64
        pm = sum(pa) / len(pa)
        pv = math.sqrt(sum((x - pm) ** 2 for x in pa) / len(pa))
        alt = 44330.0 * (1.0 - (pm / 101325.0) ** 0.1903)
        print(f'  baro: {pm:.1f} Pa RMS noise {pv:.2f} Pa  (~{pm/100:.3f} hPa, alt ~{alt:.0f} m)')
    print()
