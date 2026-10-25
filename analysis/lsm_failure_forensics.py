"""Failure-signature analysis for the ~25 s IMU acquisition failure.
Usage: python analysis/lsm_failure_forensics.py <csv>
"""
import csv
import sys
from collections import defaultdict

path = sys.argv[1]
rows = []
with open(path, newline='') as f:
    for row in csv.DictReader(f):
        try:
            rows.append((int(row['t_us']), row['type'], row))
        except ValueError:
            pass
rows.sort()
t0 = rows[0][0]
T = [(t - t0) / 1e6 for t, _, _ in rows]

e1 = [T[i] for i, (_, ty, r) in enumerate(rows) if ty == 'E' and r['sid'] == '1']
e2 = [T[i] for i, (_, ty, r) in enumerate(rows) if ty == 'E' and r['sid'] == '2']
i_t = [T[i] for i, (_, ty, _) in enumerate(rows) if ty == 'I']
p_t = [T[i] for i, (_, ty, _) in enumerate(rows) if ty == 'P']
b_rows = [(T[i], r) for i, (_, ty, r) in enumerate(rows) if ty == 'B']

print(f'frames: total {len(rows)}  I {len(i_t)}  P {len(p_t)}  E1 {len(e1)}  E2 {len(e2)}')
print(f'device span: {T[-1]:.1f} s')

# E1 onset and rate before failure
if e1:
    print(f'first E1 at {e1[0]:.2f} s;  E1 count in 0-10s: {sum(1 for t in e1 if t < 10)}, '
          f'10-20s: {sum(1 for t in e1 if 10 <= t < 20)}, 20-25s: {sum(1 for t in e1 if 20 <= t < 25)}, '
          f'>25s: {sum(1 for t in e1 if t >= 25)}')
    # gaps between consecutive E1 bursts
    gaps = [b - a for a, b in zip(e1, e1[1:])]
    gaps.sort()
    print(f'E1 inter-arrival: min {gaps[0]*1000:.1f} ms, median {gaps[len(gaps)//2]*1000:.1f} ms, max {gaps[-1]*1000:.1f} ms')

# I frame rate around the failure
if i_t:
    for lo, hi in [(5, 10), (20, 25), (25, 30), (30, 40), (40, 60), (60, 90)]:
        n = sum(1 for t in i_t if lo <= t < hi)
        print(f'  I rate {lo}-{hi}s: {n/(hi-lo):.1f} Hz')
    last_i = i_t[-1]
    print(f'last I frame at {last_i:.2f} s; I frames after 25.15s: {sum(1 for t in i_t if t > 25.15)}')

# P cadence before/after
if p_t:
    for lo, hi in [(5, 20), (25, 60), (60, 110)]:
        seg = [b - a for a, b in zip(p_t, p_t[1:]) if lo <= a < hi and b < hi]
        if seg:
            seg_ms = sorted(s * 1000 for s in seg)
            print(f'  P dt {lo}-{hi}s: median {seg_ms[len(seg_ms)//2]:.1f} ms, '
                  f'p90 {seg_ms[int(len(seg_ms)*0.9)]:.1f} ms, n={len(seg)}')

# B frame diagnostics: print all columns of the last few B rows and first few
if b_rows:
    print('--- B frame columns:', [k for k in b_rows[0][1].keys()])
    print('first B row:', {k: v for k, v in b_rows[0][1].items() if v})
    print('last B row:', {k: v for k, v in b_rows[-1][1].items() if v})
    # try to find i2c error counters: dump distinct numeric notes
    vals = defaultdict(list)
    for t, r in b_rows:
        for k, v in r.items():
            if k in ('note', 'd1', 'd2', 'ev', 'eid') and v:
                vals[k].append((t, v))
    for k, lst in vals.items():
        print(f'  B col {k}: first={lst[0]} last={lst[-1]} n={len(lst)}')
