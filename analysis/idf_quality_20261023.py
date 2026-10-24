"""Quality analysis for the 4 ESP-IDF dynamic captures (2026-10-23).

Reports per file: line counts, seq-drop count, E-code counts, t_us jump
locations, V-audio event counts (post-warmup), I-spacing uniformity, P/T rates.
"""
import csv, json, sys, os
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

FILES = [
    "20261023_155750_idf_elevator_2x.csv",
    "20261023_160532_idf_drop.csv",
    "20261023_160637_idf_toss.csv",
    "20261023_161106_idf_handcontrolled.csv",
]

def analyze(fn):
    path = os.path.join(DATA, fn)
    n = Counter()
    seq_drops = []
    last_seq = None
    t_prev = None
    jumps = []          # (row_idx, seq, dt_s)
    i_gaps = []         # dt_us between consecutive I frames
    last_i_t = None
    p_t = defaultdict(list)
    v_events = []       # (seq, t_us, sid_col, ev, val)
    e_codes = Counter()
    first_data_seq = None
    bad = 0

    with open(path, newline="") as f:
        rd = csv.reader(f)
        for row in rd:
            if not row or not row[0]:
                bad += 1
                continue
            if row[0] == "#" or row[0].startswith("#"):
                n["comment"] += 1
                continue
            try:
                seq = int(row[0]); t = int(row[1]); typ = row[2]
            except Exception:
                bad += 1
                continue
            n[typ] += 1
            n["total"] += 1
            if first_data_seq is None and typ in ("P", "T", "I"):
                first_data_seq = seq
            if last_seq is not None and seq != last_seq + 1:
                seq_drops.append((seq, seq - last_seq - 1))
            last_seq = seq
            if t_prev is not None:
                dt = (t - t_prev) / 1e6
                if dt > 0.05:
                    jumps.append((n["total"], seq, dt))
            t_prev = t
            if typ == "I":
                if last_i_t is not None:
                    i_gaps.append(t - last_i_t)
                last_i_t = t
            elif typ == "P":
                p_t[row[3]].append(t)
            elif typ == "E":
                e_codes[row[4] if len(row) > 4 else "?"] += 1
            elif typ == "V":
                v_events.append((seq, t, row[3], row[4] if len(row) > 4 else "", row[5] if len(row) > 5 else ""))
            elif typ == "B":
                pass

    # I spacing stats
    def stats(xs):
        if not xs: return None
        xs = sorted(xs)
        n_ = len(xs)
        med = xs[n_ // 2]
        return dict(n=n_, min=xs[0], med=med, p95=xs[int(n_ * 0.95)], max=xs[-1])

    # seq-drop clustering: bucket by seq into 500-wide bins
    bins = Counter()
    for s, cnt in seq_drops:
        bins[s // 500 * 500] += cnt
    top_bins = bins.most_common(8)

    # P rate per sid (device time span / count)
    p_rates = {}
    for sid, ts in p_t.items():
        if len(ts) > 10:
            span = (ts[-1] - ts[0]) / 1e6
            p_rates[sid] = round(len(ts) / span, 1) if span > 0 else None

    print("=" * 72)
    print(fn)
    print(f"  total data lines: {n['total']}  (P={n['P']} T={n['T']} I={n['I']} E={n['E']} V={n['V']} B={n['B']} bad={bad})")
    dropped = sum(c for _, c in seq_drops)
    print(f"  seq drops: {dropped} gaps in {len(seq_drops)} bursts  | E codes: {dict(e_codes)}")
    print(f"  t_us jumps >50 ms:")
    for idx, seq, dt in jumps:
        print(f"    row#{idx} seq={seq}  dt=+{dt:.3f} s")
    print(f"  I spacing (us): {stats(i_gaps)}")
    print(f"  P rate Hz/sid: {p_rates}")
    print(f"  V audio events: {len(v_events)}")
    if v_events:
        for ev in v_events[:30]:
            print(f"    seq={ev[0]} t={ev[1]/1e6:.2f}s sid_col={ev[2]} ev={ev[3]} val={ev[4]}")
    print(f"  drop clustering (seq/500 bin -> dropped frames): {top_bins}")

    # sidecar errors
    jpath = path[:-4] + ".json"
    if os.path.exists(jpath):
        with open(jpath) as f:
            meta = json.load(f)
        errs = meta.get("errors", {})
        print(f"  sidecar errors: {errs if errs else 'none'}")
    print()

for fn in FILES:
    analyze(fn)
