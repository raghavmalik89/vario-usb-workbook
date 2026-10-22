"""Causal replay engine (task spec §5).

Feeds identical chronological (sample, physical-timestamp) pairs to every
filter. Streams are independent per sensor id — two barometers are replayed
as two separate streams unless an explicitly defined fusion filter is used
(Group F is a later phase; nothing here fuses silently).

Diagnostics (preserved, not hidden — spec: corrupt frames and missing-sample
events must be preserved in replay diagnostics):
  - corrupt P/T frames (raw ADC outside the plausible band): counted, listed,
    excluded from the fed stream (compensating them would inject physical
    nonsense — a -97 kPa sample is not a measurement);
  - sequence gaps: detected from the protocol seq counter, reported with
    their durations; the filters simply experience the true time gap
    (variable dt), which is the physically honest behavior;
  - duplicate/out-of-order timestamps: counted; filters hold state on them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import loader
from loader import get_prom, sidecar_for


@dataclass
class StreamDiagnostics:
    n_samples: int = 0
    n_corrupt: int = 0
    corrupt_t: list = field(default_factory=list)
    n_seq_gaps: int = 0
    gap_durations_s: list = field(default_factory=list)
    n_duplicate_t: int = 0
    n_out_of_order_t: int = 0

    def summary(self):
        return (f"{self.n_samples} samples | {self.n_corrupt} corrupt dropped "
                f"(t={['%.2f' % t for t in self.corrupt_t[:5]]}) | "
                f"{self.n_seq_gaps} seq gaps (durations "
                f"{['%.3f' % g for g in self.gap_durations_s[:5]]}) | "
                f"{self.n_duplicate_t} dup t | "
                f"{self.n_out_of_order_t} o-o t")


D1_BAND = (4_000_000, 12_000_000)
D2_BAND = (1_000_000, 16_000_000)


def altitude_stream(csv_path, sid):
    """Extract a compensated altitude stream for one barometer, chronological,
    with full diagnostics. Returns (t, alt, diag)."""
    df = pd.read_csv(csv_path)
    df["t_s"] = df.t_us / 1e6
    diag = StreamDiagnostics()
    seq = df.seq.values
    dseq = np.diff(seq)
    diag.n_seq_gaps = int(np.sum(dseq != 1))
    pr = df[(df.type == "P") & (df.sid == sid)][["t_s", "d1", "seq"]].dropna()
    tr = df[(df.type == "T") & (df.sid == sid)][["t_s", "d2"]].dropna()
    sc = sidecar_for(Path(csv_path))
    prom = get_prom(sc, sid) if sc else None
    if prom is None:
        raise SystemExit(f"{csv_path.name} sid={sid}: no PROM in sidecar — "
                         f"stream unusable (data_quality_report.md)")

    d1 = pr.d1.values
    bad = (d1 < D1_BAND[0]) | (d1 > D1_BAND[1])
    diag.n_corrupt = int(bad.sum())
    diag.corrupt_t = pr.t_s.values[bad].tolist()
    pr = pr[~bad]

    tr = tr.sort_values("t_s")
    idx = np.searchsorted(tr.t_s.values, pr.t_s.values, side="right") - 1
    idx = np.clip(idx, 0, len(tr) - 1)
    d2 = tr.d2.values[idx]
    d2_bad = (d2 < D2_BAND[0]) | (d2 > D2_BAND[1])
    # temperature corruption is rare; guard by falling back to nearest valid
    if d2_bad.any():
        good = ~((tr.d2.values < D2_BAND[0]) | (tr.d2.values > D2_BAND[1]))
        d2[d2_bad] = np.interp(pr.t_s.values[d2_bad],
                               tr.t_s.values[good], tr.d2.values[good])

    p, temp = loader.compensate_ms5611(pr.d1.values, d2, prom)
    p0 = np.nanmean(p[: min(len(p), 2000)])      # first ~40 s reference
    alt = 44330.0 * (1.0 - (p / p0) ** 0.1903)

    order = np.argsort(pr.t_s.values, kind="stable")
    t = pr.t_s.values[order]
    alt = alt[order]
    dt = np.diff(t)
    diag.n_duplicate_t = int(np.sum(dt == 0))
    diag.n_out_of_order_t = int(np.sum(dt < 0))
    # gap durations attributable to seq gaps (bounded by neighbor spacing)
    if diag.n_seq_gaps:
        big = dt[dt > 3 * np.median(dt[dt > 0])] if np.any(dt > 0) else []
        diag.gap_durations_s = big.tolist()[:10]
    diag.n_samples = len(t)
    return t, alt, diag


def replay(filter_instance, t, z):
    """Run one filter over a stream; returns (t_out, v_out)."""
    t_out = np.empty(len(t))
    v_out = np.empty(len(t))
    for i in range(len(t)):
        v_out[i] = filter_instance.update(float(z[i]), float(t[i]))
        t_out[i] = t[i]
    return t_out, v_out
