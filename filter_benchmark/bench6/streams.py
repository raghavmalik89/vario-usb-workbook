"""Corrected stream reconstruction for Bench 6.

THE reference defect (DEF-001) is corrected here: altitude is always computed
against the FIXED ISA sea-level pressure 101325 Pa unless the caller
explicitly asks for a historical convention ('session_mean' reproduces the
Phase 2-5 offline convention p0=mean(p[:2000]); 'moving_p0' reproduces the
pre-fix firmware semantics and exists ONLY for the harness cross-check).
Velocity is invariant to a constant reference offset; the moving reference is
physically wrong under in-window motion and must never be used for scoring.

Single time base: every frame type (P/T/I/V/B) is stamped from the physical
MCU esp_timer value, zero-based ONCE on the capture's first frame. No mixing
of absolute and relative timestamps anywhere in bench6.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BENCH6_DIR = Path(__file__).resolve().parent
BENCH_ROOT = BENCH6_DIR.parents[0]
SRC = BENCH_ROOT / "src"
ANALYSIS = BENCH_ROOT.parent / "analysis"
for p in (str(SRC), str(ANALYSIS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import loader  # noqa: E402  (analysis/ on path: compensate_ms5611 et al.)
from common import altitude_m, compensate_ms5611, get_prom  # noqa: E402

import datasets as ds  # noqa: E402  (bench6 package)

P0_ISA_PA = 101325.0
D1_BAND = (4_000_000, 12_000_000)      # raw ADC plausibility (replay.py)
D2_BAND = (1_000_000, 16_000_000)

ISA_ALT = lambda p: altitude_m(p, P0_ISA_PA)

CACHE_DIR = BENCH6_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# fixed documented event-reference constants (bench_common.derive_events,
# experiments.json event_reference) — reimplemented locally so bench6 does
# not depend on the Phase 2 config file.
EV_CORE_ON, EV_CORE_OFF, EV_FLOOR = 0.4, 0.25, 0.05
EV_MIN_DUR_S, EV_MIN_GAP_S = 0.3, 1.0


# ---------------------------------------------------------------- loading ---
def load_frames(stem: str) -> pd.DataFrame:
    """All frames of a capture, physical t_s zero-based on the first frame."""
    df = pd.read_csv(ds.csv_for(stem))
    t0 = df.t_us.iloc[0]
    df["t_s"] = (df.t_us - t0) / 1e6
    return df


def _diag(df, sid):
    """Stream-health diagnostics, measured not assumed."""
    pr = df[(df.type == "P") & (df.sid == sid)]
    d1 = pr.d1.values
    bad = int(((d1 < D1_BAND[0]) | (d1 > D1_BAND[1])).sum())
    seq = df.seq.values
    g = np.where(np.diff(seq) != 1)[0]
    gaps = [float((df.t_us.iloc[i + 1] - df.t_us.iloc[i]) / 1e6) for i in g]
    t = pr.t_s.values
    dt = np.diff(t)
    return dict(n_p=int(len(pr)), n_corrupt=bad, n_seq_gaps=int(len(g)),
                gap_durs_s=gaps, n_dup_t=int((dt == 0).sum()),
                n_ooo_t=int((dt < 0).sum()),
                median_dt_s=float(np.median(dt)) if len(dt) else np.nan)


def baro_stream(stem: str, sid: int, reference: str = "isa",
                seed_d2: bool = False):
    """Compensated altitude stream for one barometer.

    reference: 'isa'        fixed 101325 Pa (DEF-001 correction — DEFAULT)
               'isa_fw10'    firmware-defect scale: fixed 101325 Pa against
                             pressure in the firmware's 10x common.py scale
                             (DEF-011) — equivalence replays ONLY
               'session_mean'  mean(p[:min(2000,N)]) — Phase 2-5 offline
                               convention, kept for backward comparability
               'moving_p0'     running mean of first 2000 then frozen —
                               pre-fix firmware semantics, harness check ONLY
    seed_d2: emulate the firmware boot seed (s_d2 = prom[5]*256, dt=0/20 C)
             for P frames before the first real T frame. The firmware's
             estimators and (pre-fix) p0 accumulator consumed the seeded
             compensation first, so the first real T frame produces a step
             in their input that a real-T-merged offline stream lacks.
    Returns (t, alt, diag).
    """
    df = load_frames(stem)
    meta = json.loads(ds.sidecar_for(stem).read_text())
    prom = get_prom(meta, sid)
    pr = df[(df.type == "P") & (df.sid == sid)][["t_s", "d1"]].dropna()
    tr = df[(df.type == "T") & (df.sid == sid)][["t_s", "d2"]].dropna()
    diag = _diag(df, sid)
    d1 = pr.d1.values.astype(float)
    bad = (d1 < D1_BAND[0]) | (d1 > D1_BAND[1])
    diag["n_feed"] = int((~bad).sum())
    pr, d1 = pr[~bad], d1[~bad]
    tr = tr.sort_values("t_s")
    idx = np.searchsorted(tr.t_s.values, pr.t_s.values, side="right") - 1
    idx = np.clip(idx, 0, len(tr) - 1)
    d2 = tr.d2.values[idx].astype(float)
    if seed_d2:
        # pre-first-T samples: firmware compensates with the boot seed
        seed = float(prom[5]) * 256.0
        pre = pr.t_s.values < tr.t_s.values[0]
        d2[pre] = seed
    d2_bad = (d2 < D2_BAND[0]) | (d2 > D2_BAND[1])
    if d2_bad.any():
        good = ~((tr.d2.values < D2_BAND[0]) | (tr.d2.values > D2_BAND[1]))
        d2[d2_bad] = np.interp(pr.t_s.values[d2_bad],
                               tr.t_s.values[good], tr.d2.values[good])
    p, temp = compensate_ms5611(d1, d2, prom)
    if reference == "isa":
        alt = ISA_ALT(p)
    elif reference == "isa_fw10":
        alt = 44330.0 * (1.0 - (10.0 * p / P0_ISA_PA) ** 0.1903)
    elif reference == "session_mean":
        p0 = np.nanmean(p[: min(len(p), 2000)])
        alt = altitude_m(p, p0)
    elif reference == "moving_p0":
        p0r = np.cumsum(p) / np.arange(1, len(p) + 1)
        p0f = np.where(np.arange(len(p)) < 2000, p0r, p0r[1999])
        alt = altitude_m(p, p0f)
    else:
        raise ValueError(f"unknown reference {reference!r}")
    order = np.argsort(pr.t_s.values, kind="stable")
    t = pr.t_s.values[order]
    alt = alt[order]
    diag["t_first"] = float(t[0])
    diag["t_last"] = float(t[-1])
    return t, alt, diag


# ----------------------------------------------------------------- IMU ------
_G_CAL = None  # per-device constant, derived from the cleanest static (lazy)


def device_g_cal() -> float:
    """MPU6050 clone gravity-scale constant [M] from the cleanest static
    (p0fix_static), same discipline as Phase 5 (per-device, never per-session
    on motion captures)."""
    global _G_CAL
    if _G_CAL is None:
        import imu_io
        imu = imu_io.imu_stream(str(ds.csv_for("20261023_234521_idf_p0fix_static")))
        a_norm = np.linalg.norm(imu["accel"], axis=1)
        m = (a_norm >= 8.5) & (a_norm <= 11.5)
        _G_CAL = float(np.median(a_norm[m])) if m.sum() > 100 else \
            float(np.median(a_norm))
    return _G_CAL


def imu_stream(stem: str):
    """Calibrated IMU stream: (t, accel_cal, gyro_bias_subtracted, info).

    g_cal: per-device constant (device_g_cal); gyro bias: capture-start rest
    window (operator procedure), per capture.
    """
    import imu_io
    imu = imu_io.imu_stream(str(ds.csv_for(stem)))
    if imu is None:
        return None
    g = device_g_cal()
    a_cal = imu["accel"] * (9.80665 / g)
    gb = imu_io.gyro_bias_rad_s(imu)
    info = dict(g_cal=g, gyro_bias_rad_s=gb,
                rate_hz=1.0 / np.median(np.diff(imu["t_s"])))
    return imu["t_s"], a_cal, imu["gyro"] - gb, info


def attitude_quats(stem: str, beta: float = 0.3):
    """Madgwick attitude stream with exact shortest-arc warm start (Phase-5
    fix). Cached per stem+beta in bench6/cache/."""
    import attitude
    tag = f"{stem}_b{beta}".replace("/", "_")
    cf = CACHE_DIR / (tag + ".npz")
    if cf.exists():
        z = np.load(cf, allow_pickle=True)
        return z["quats"], dict(z["info"].item()) if "info" in z else {}
    out = imu_stream(stem)
    if out is None:
        return None, {}
    t, a_cal, gyro_c, info = out
    q0 = attitude.quat_from_accel_tilt(a_cal[0])
    quats = attitude.estimate_attitude(t, a_cal, gyro_c, q0=q0, beta=beta)
    info = dict(info)
    from fusion import gravity_compensate
    n = min(len(t), 1000 * 10)
    az = np.array([gravity_compensate(a_cal[i], quats[i]) for i in range(n)])
    info["madgwick_warmstart_abs_az_first10s"] = float(np.mean(np.abs(az)))
    np.savez_compressed(cf, quats=quats, info=np.array(info, dtype=object))
    return quats, info


# ------------------------------------------------------- firmware V / B -----
def v_frames(stem: str):
    """Virtual-audio frames: (t, eid, ev, val). ev: 1=ON(tone Hz), 2=OFF(ms),
    3=TONE(tone Hz); implied v = (tone-500)/450 (config.h AU_TONE_*)."""
    df = load_frames(stem)
    v = df[df.type == "V"][["t_s", "eid", "ev", "val"]].dropna()
    return v.t_s.values, v.eid.values.astype(int), \
        v.ev.values.astype(int), v.val.values.astype(float)


def mcu_tones(stem, eid):
    """(t, implied_v) of ON/TONE events for one estimator id."""
    t, e, ev, val = v_frames(stem)
    m = (e == eid) & (np.isin(ev, (1, 3)))
    return t[m], (val[m] - 500.0) / 450.0


def mcu_episodes(stem, eid):
    """ON->OFF episodes for one eid: (t_on, t_off, peak_implied_v, dur_s)."""
    t, e, ev, val = v_frames(stem)
    m = e == eid
    t, ev, val = t[m], ev[m], val[m]
    eps, on = [], None
    for tt, eev, vv in zip(t, ev, val):
        if eev == 1:
            on = (tt, (vv - 500.0) / 450.0, (vv - 500.0) / 450.0)
        elif eev == 3 and on is not None:
            on = (on[0], max(on[1], (vv - 500.0) / 450.0), on[2])
        elif eev == 2 and on is not None:
            eps.append((on[0], tt, on[1], tt - on[0]))
            on = None
    return eps


def bline_cpu(stem):
    """Per-B-line estimator CPU pairs avg/max [us] in eid order 0..9."""
    df = load_frames(stem)
    out = []
    pat = __import__("re").compile(r"^(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)$")
    for note in df[df.type == "B"].note.dropna():
        # estimator pairs are bare "avg/max" tokens (the leading "c=<n>" is a
        # cycle counter with no slash); collect all slash tokens in order
        pairs = []
        for tok in str(note).split(";"):
            m = pat.match(tok.strip())
            if m:
                pairs.append((float(m.group(1)), float(m.group(2))))
        if pairs:
            out.append(pairs)
    return out


# ---------------------------------------------------- derived references ----
def reference_v(t, alt, win_s=1.0):
    """1-s Gaussian-smoothed barometric derivative — the DERIVED reference
    (src/metrics.py kernel, fixed documented method). Descriptive proxy, not
    ground truth. Duplicate timestamps are collapsed first (they would
    divide-by-zero np.gradient and manufacture infinite reference velocities).

    DEF-014: np.convolve(mode="same") zero-pads, so the raw method's smoothed
    altitude ramps from ~50 % of true value over the first/last ~3*win_s of
    the stream, manufacturing phantom reference velocity at both boundaries
    (the old "startup event" in handtest3 was this artifact, and the tail
    artifact contaminated the end-of-capture toss). Fixed here by dividing by
    the effective window weight (standard edge normalisation); the archived
    Phase 2-5 src/metrics.py is intentionally left frozen."""
    dt = np.median(np.diff(t))
    n = max(int(round(win_s / dt)), 3)
    k = np.exp(-0.5 * (np.arange(-3 * n, 3 * n + 1) / n) ** 2)
    tu, inv, counts = np.unique(t, return_inverse=True, return_counts=True)
    if len(tu) != len(t):
        alt_u = np.zeros(len(tu))
        np.add.at(alt_u, inv, alt)
        alt_u /= counts
    else:
        tu, alt_u = t, alt
    alt_s = np.convolve(alt_u, k, mode="same") / np.convolve(
        np.ones_like(alt_u), k, mode="same")
    return np.gradient(alt_s, tu)[inv], alt_s[inv]


# Second fixed documented reference for slow sustained motion (thermalling-
# relevant): blocks where the 1-s-smoothed derivative exceeds 0.15 m/s
# sustained for >= 5 s. Same constants for every session, every sensor set.
SLOW_ON, SLOW_MIN_DUR_S, SLOW_GAP_S = 0.15, 3.0, 4.0


def detect_slow_blocks(t, alt):
    """Slow sustained-motion blocks [(t0, t1)] + the reference velocity."""
    v_ref, _ = reference_v(t, alt)
    import metrics
    blocks = metrics.detect_events(t, v_ref, on=SLOW_ON, off=SLOW_ON * 0.6,
                                   min_dur=SLOW_MIN_DUR_S, gap=SLOW_GAP_S)
    return blocks, v_ref


def detect_legs(t, alt, thr=0.5, min_dur_s=2.0, smooth_s=1.0):
    """Elevator travel legs from sid0 fixed-reference altitude — the proven
    method from the false-lift investigation (1-s boxcar on a 20 Hz uniform
    resample, |v|>thr sustained >= min_dur_s). Returns
    [(t0, t1, v_leg, dH_m)] where v_leg/dH are measured on the plateau."""
    dt_u = 0.05
    tu = np.arange(t[0], t[-1], dt_u)
    au = np.interp(tu, t, alt)
    k = max(1, int(round(smooth_s / dt_u)))
    as_ = np.convolve(au, np.ones(k) / k, mode="same")
    v = np.gradient(as_, tu)
    vs = np.convolve(v, np.ones(k) / k, mode="same")
    inleg = np.abs(vs) > thr
    legs = []
    i = 0
    while i < len(tu):
        if inleg[i]:
            j = i
            while j < len(tu) and inleg[j]:
                j += 1
            if tu[j - 1] - tu[i] > min_dur_s:
                i0 = np.searchsorted(tu, tu[i] + 2.0)
                i1 = np.searchsorted(tu, tu[j - 1] - 2.0)
                v_leg = float(np.mean(vs[i0:i1])) if i1 > i0 else float(vs[i:j].mean())
                legs.append((float(tu[i]), float(tu[j - 1]), v_leg,
                             float(as_[j - 1] - as_[i])))
            i = j
        else:
            i += 1
    return legs


def derive_events(t, alt):
    """Derived strong-motion event intervals (handtest) — fixed documented
    method (bench_common.derive_events): cores at 0.4/0.25 extended to the
    0.05 noise floor."""
    v_ref, _ = reference_v(t, alt)
    cores = _detect_cores(t, v_ref, on=EV_CORE_ON, off=EV_CORE_OFF,
                          min_dur=0.15, gap=EV_MIN_GAP_S)
    out = []
    for (a, b) in cores:
        ia = np.searchsorted(t, a)
        ib = np.searchsorted(t, b)
        below = np.where(np.abs(v_ref[:ia]) <= EV_FLOOR)[0]
        ext_a = t[below[-1]] if len(below) else t[0]
        below_b = np.where(np.abs(v_ref[ib:]) <= EV_FLOOR)[0]
        ext_b = t[ib + below_b[0]] if len(below_b) else t[-1]
        if ext_b - ext_a >= EV_MIN_DUR_S:
            out.append((float(ext_a), float(ext_b)))
    out.sort()
    merged = []
    for e in out:
        if merged and e[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e[1]))
        else:
            merged.append(e)
    return merged, v_ref


def _detect_cores(t, v, on, off, min_dur, gap):
    import metrics
    return metrics.detect_events(t, v, on=on, off=off, min_dur=min_dur,
                                 gap=gap)
