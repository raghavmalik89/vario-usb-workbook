"""Consolidated dataset-integrity table for the engineering validation report.
Writes analysis/output/report_dataset_integrity.csv with one row per capture:
duration, device span, rates, seq drops, bad lines, E1/E2/E3, IMU stale %.
"""
import csv
import glob
import json
import math
import os

LSB_G = 4096.0
rows_out = []
for csv_path in sorted(glob.glob('analysis/data/*.csv')):
    tag = os.path.basename(csv_path)[:-4]
    json_path = csv_path[:-4] + '.json'
    meta = {}
    if os.path.exists(json_path):
        meta = json.load(open(json_path))
    n = {'I': 0, 'P': 0, 'T': 0}
    e = {}
    i_raw = []
    t0 = t1 = None
    n_bad = 0
    try:
        with open(csv_path, newline='') as f:
            for r in csv.DictReader(f):
                ty = r['type']
                try:
                    t = int(r['t_us'])
                except (ValueError, TypeError):
                    n_bad += 1
                    continue
                if t0 is None:
                    t0 = t
                t1 = t
                if ty in n:
                    n[ty] += 1
                if ty == 'E':
                    e[r['sid']] = e.get(r['sid'], 0) + 1
                if ty == 'I':
                    try:
                        i_raw.append(tuple(int(r[k]) for k in ('ax', 'ay', 'az')))
                    except (ValueError, TypeError):
                        pass
    except Exception as ex:
        print(f'skip {tag}: {ex}')
        continue
    span = (t1 - t0) / 1e6 if t1 is not None else 0
    dur = meta.get('stats', {}).get('elapsed_s', '')
    drops = meta.get('stats', {}).get('seq_drops', '')
    bad = meta.get('stats', {}).get('bad_lines', '')
    stale = ''
    grav = ''
    if len(i_raw) > 100:
        same = sum(1 for a, b in zip(i_raw, i_raw[1:]) if a == b)
        stale = f'{100 * same / (len(i_raw) - 1):.2f}'
        mags = [math.sqrt(sum(c * c for c in r)) / LSB_G for r in i_raw[len(i_raw)//10:]]
        grav = f'{sum(mags)/len(mags):.4f}'
    rows_out.append([tag, f'{span:.1f}', dur, n['P'], n['I'], drops, bad,
                     e.get('1', 0), e.get('2', 0), e.get('3', 0), stale, grav])

os.makedirs('analysis/output', exist_ok=True)
with open('analysis/output/report_dataset_integrity.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['capture', 'device_span_s', 'host_elapsed_s', 'P_frames',
                'I_frames', 'seq_drops', 'bad_lines', 'E1', 'E2', 'E3',
                'imu_stale_pct', 'gravity_g'])
    w.writerows(rows_out)
print(f'{len(rows_out)} captures written')
for r in rows_out:
    if r[7] != '0' or r[8] != '0' or (r[10] not in ('', '0.00', '0.0', '0')):
        print('  flagged:', r[0], 'E1', r[7], 'E2', r[8], 'stale%', r[10])
