"""Phase 5c — fusion validation on the t008 quiet-house capture.

Runs the same fused vs baro-only replay as script 17, but on t008 only,
with r estimated from t008's own quiet static (drift-leakage-free:
r ~ 0.029 m^2 vs 0.042 office). Confirms on fresh data that the Phase-5
fixes (exact tilt warm start, fault recovery, device g_cal) behave: at
rest on a quiet static the fused path must equal baro-only.

EXPLORATORY — no estimator selection or freeze.

Repro:  python -u scripts/22_t008_fusion.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "s17", ROOT / "scripts" / "17_real_imu_fusion.py")
s17 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s17)

import loader  # noqa: E402

RES = ROOT / "results"


def main():
    files = sorted(loader.data_files())
    t008 = [f for f in files if "t008" in f.stem]
    assert t008, "no t008 captures found"

    # r from t008 static only
    r_est = []
    for f in t008:
        if "static" not in f.stem.lower():
            continue
        for sid in (0, 1):
            t_b, alt_f, _, rep = s17.altitude_stream_d2filt(f, sid)
            r_est.append(s17.estimate_r_baro(
                np.asarray(alt_f, dtype=float), np.asarray(t_b, dtype=float)))
            print(f"r-est {f.stem} sid{sid}: {r_est[-1]:.5f} m^2 "
                  f"(detrended noise {rep['noise_filt_m']:.4f} m)")
    r = float(np.median(r_est))
    q = 10.0
    print(f"-> r = {r:.5f} m^2, q = {q} (exploratory, matches script 17)")

    all_rows = []
    for f in t008:
        out = s17.analyse_session(f, q, r, g_device=None)
        if out is None:
            print(f"skip {f.name}: no IMU stream")
            continue
        rows, _trace = out
        all_rows.extend(rows)
        for row in rows:
            print("  ", {k: row[k] for k in
                         ("session", "sid", "g_cal", "madgwick_rest_az_err",
                          "v_rms_rest_baro_only", "v_rms_rest_fusion",
                          "max_abs_v_baro_only", "max_abs_v_fusion",
                          "n_gated_fusion", "n_reinit_fusion")})
    if all_rows:
        import pandas as pd
        df = pd.DataFrame(all_rows)
        df.to_csv(RES / "22_t008_fusion.csv", index=False)
        print(f"\n{len(df)} rows -> {RES / '22_t008_fusion.csv'}")


if __name__ == "__main__":
    main()
