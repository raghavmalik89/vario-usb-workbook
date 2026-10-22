"""Script 15 — Phase 4 WP-D: generate portable-core test vectors from the
Python reference and verify the C implementation against them.

Vectors (seeded synthetic — SIMULATED):
  v1_statics_45hz.csv        60 s static, 45 Hz, MS5611-like noise
  v2_climb_step_100hz.csv    static -> 1.5 m/s climb step, 100 Hz
  v3_spike_gap_reversal.csv  spikes + 1 s gap + lift->sink reversal, 50 Hz
  v4_irregular_dt.csv        +/-3 ms timestamp jitter on a climb, 100 Hz
  v5_sustained_fault.csv     30 m offset for 3 s (fault-detector exercise)

For each vector the Python reference (S5_LightGateKF + audio SM + generic
fault detector, wired exactly like the C runner) produces expected outputs.

Build + run (host):      python scripts/15_portable_core.py
Cross-check only:        python scripts/15_portable_core.py --xtensa  (compile-only)
Outputs: portable/vario_core/test_vectors/*.csv, results/15_portable_equivalence.csv
"""
from pathlib import Path
import csv
import json
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import ROOT  # noqa: E402
import p4_eval as P4E  # noqa: E402
import audio  # noqa: E402

HERE = ROOT / "portable" / "vario_core"
VEC = HERE / "test_vectors"
BUILD = HERE / "build"

EST_PARAMS = dict(P4E.P4["estimators"]["S5_LightGateKF"]["params"])
AUDIO_CFG = dict(P4E.P4["phase4_audio_baseline"])
FLT_CFG = dict(P4E.P4["safety_mechanisms"]["fault_detector"])

TOL_DOUBLE = 1e-6      # double build vs Python float64 reference; observed max |dv| over
                       # 6000-step vectors is 2e-8 due to op-order divergence (C double is
                       # IEEE-754 double but the compiler may reassociate differently than
                       # CPython), so 1e-9 was tighter than physics allows. 1e-6 keeps 50x
                       # margin over the worst measured divergence.
TOL_FLOAT = 1e-3       # float build vs Python float64 reference (documented)


def gen_vectors():
    """Create input vectors + Python-reference expected outputs."""
    VEC.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(4242)
    specs = {}

    t = np.arange(0, 60.0, 1 / 45)
    specs["v1_statics_45hz"] = (t, rng.normal(0, 0.05, len(t)))

    t = np.arange(0, 30.0, 1 / 100)
    v = np.where(t >= 10, 1.5, 0.0)
    specs["v2_climb_step_100hz"] = (t, np.cumsum(v) * 0.01)

    t = np.arange(0, 25.0, 1 / 50)
    z = (P4E.synth.lift_pulse(t, v=1.5, t_on=5.0, dur=2.0, ramp=0.2)
         + P4E.synth.lift_pulse(t, v=-2.5, t_on=9.0, dur=1.0, ramp=0.15)
         + rng.normal(0, 0.04, len(t)))
    z[np.searchsorted(t, 15.0)] += 5.0
    z[np.searchsorted(t, 18.0)] -= 5.0
    keep = ~((t > 12.0) & (t < 13.0))
    specs["v3_spike_gap_reversal"] = (t[keep], z[keep])

    t = np.arange(0, 20.0, 1 / 100)
    tj = np.maximum.accumulate(t + rng.uniform(-0.003, 0.003, len(t)))
    v = np.where(t >= 5, 1.2, 0.0)
    specs["v4_irregular_dt"] = (tj, np.cumsum(v) * 0.01)

    t = np.arange(0, 20.0, 1 / 50)
    z = rng.normal(0, 0.05, len(t))
    z[(t >= 8.0) & (t < 11.0)] += 30.0
    specs["v5_sustained_fault"] = (t, z)

    made = []
    for name, (t, z) in specs.items():
        inp = VEC / f"{name}.csv"
        with inp.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["t_s", "z_m"])
            for ti, zi in zip(t, z):
                w.writerow([f"{ti:.9g}", f"{zi:.9g}"])
        # Python reference outputs (same wiring as the C runner)
        rows = python_reference(t, z)
        exp = VEC / f"{name}_expected.csv"
        with exp.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["t_s", "v", "state", "fault"])
            w.writerows(rows)
        made.append(name)
    return made


def python_reference(t, z):
    from filters.stacked import STACKED
    f = STACKED["S5_LightGateKF"](**EST_PARAMS)
    sm = audio.AudioStateMachine(lift_on=AUDIO_CFG["lift_on"],
                                 lift_off=AUDIO_CFG["lift_off"],
                                 hold_s=AUDIO_CFG["hold_s"],
                                 min_on_s=AUDIO_CFG["min_on_s"],
                                 max_on_s=AUDIO_CFG["max_on_s"])
    det = P4E.GenericFaultDetector()
    rows = []
    h_prev = v_prev = t_prev = None
    for ti, zi in zip(t, z):
        v = f.update(float(zi), float(ti))
        if t_prev is None:
            h_pred, dt = float(zi), 0.02
        else:
            dt = float(ti) - t_prev
            h_pred = h_prev + v_prev * dt
        fault = det.update(float(zi), h_pred, max(dt, 1e-3))
        state = sm.update(float(ti), float(v), fault=fault)
        rows.append([f"{ti:.9g}", f"{float(v):.9g}",
                     1 if state == "on" else 0, 1 if fault else 0])
        h_prev, v_prev, t_prev = f.get_altitude(), float(v), float(ti)
    return rows


def read_out(path):
    with open(path, newline="") as fh:
        r = csv.DictReader(fh)
        return [(float(x["t_s"]), float(x["v"]), int(x["state"]),
                 int(x["fault"])) for x in r]


def compare(vector, out_csv, tol):
    exp = read_out(VEC / f"{vector}_expected.csv")
    got = read_out(out_csv)
    assert len(exp) == len(got), f"{vector}: length mismatch {len(exp)} vs {len(got)}"
    max_dv = max(abs(e[1] - g[1]) for e, g in zip(exp, got))
    state_mismatch = sum(1 for e, g in zip(exp, got) if e[2] != g[2])
    fault_mismatch = sum(1 for e, g in zip(exp, got) if e[3] != g[3])
    return max_dv, state_mismatch, fault_mismatch


MSVC_VARS = ("C:\\Program Files (x86)\\Microsoft Visual Studio\\18\\"
             "BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat")
XTENSA_GCC = (Path.home() / "AppData/Local/Arduino15/packages/esp32/tools/"
              "esp-x32/2405/bin/xtensa-esp-elf-gcc.exe")


def sh(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def build_host():
    BUILD.mkdir(exist_ok=True)
    src_c = str(HERE / "vario_core.c")
    src_runner = str(HERE / "runner.c")
    # write a helper .bat in a space-free temp dir: invoking vcvars64 +
    # cl through cmd /c argument quoting is fragile, a real batch file
    # sidesteps it entirely
    import tempfile
    for variant, flags in (("double", ["/DVARIO_USE_DOUBLE"]), ("float", [])):
        exe = BUILD / f"runner_{variant}.exe"
        bat = Path(tempfile.gettempdir()) / f"vario_build_{variant}.bat"
        bat.write_text(
            f'@call "{MSVC_VARS}" >nul\r\n'
            f'@cd /d "{BUILD}"\r\n'
            f'@cl /nologo /O2 /W3 {" ".join(flags)} /Fe{exe.name} '
            f'"{src_c}" "{src_runner}"\r\n'
            f'@del /q "{BUILD}\\*.obj"\r\n',
            "ascii")
        r = subprocess.run(["cmd", "/c", str(bat)], capture_output=True,
                           text=True, cwd=BUILD)
        if r.returncode != 0 or not exe.exists():
            print(r.stdout)
            print(r.stderr)
            raise SystemExit(f"MSVC build failed for {variant}")
        print(f"built {exe}")


def run_host(vectors):
    rows = []
    for variant, tol in (("double", TOL_DOUBLE), ("float", TOL_FLOAT)):
        exe = BUILD / f"runner_{variant}.exe"
        for name in vectors:
            out = BUILD / f"{name}_{variant}_out.csv"
            r = sh([str(exe), str(VEC / f"{name}.csv"), str(out)],
                   cwd=ROOT)
            print(f"  [{variant}] {name}: {r.stderr.strip()}")
            max_dv, sm, fm = compare(name, out, tol)
            ok = max_dv <= tol and sm == 0 and fm == 0
            rows.append(dict(build=variant, vector=name, max_abs_dv=max_dv,
                             tol=tol, state_mismatch=sm, fault_mismatch=fm,
                             passed=int(ok)))
    return rows


def build_xtensa():
    """Compile-only cross-check under the real ESP32-S3 toolchain."""
    if not XTENSA_GCC.exists():
        print(f"xtensa gcc not found at {XTENSA_GCC} — skipped")
        return []
    rows = []
    for variant, flags in (("double", ["-DVARIO_USE_DOUBLE"]),
                           ("float", [])):
        obj = BUILD / f"vario_core_xtensa_{variant}.o"
        r = sh([str(XTENSA_GCC), "-c", "-O2", "-Wall", "-std=c99",
                "-mlongcalls", *flags,
                "-o", str(obj),
                str(HERE / "vario_core.c")])
        ok = r.returncode == 0 and obj.exists()
        if not ok:
            print(r.stdout, r.stderr)
        rows.append(dict(build=f"xtensa_esp32s3_{variant}", vector="(compile)",
                         max_abs_dv="", tol="", state_mismatch="",
                         fault_mismatch="",
                         passed=int(ok)))
        print(f"xtensa {variant}: {'OK' if ok else 'FAIL'}")
    return rows


def main():
    vectors = gen_vectors()
    print(f"generated {len(vectors)} vectors")
    rows = []
    if "--xtensa" in sys.argv:
        BUILD.mkdir(exist_ok=True)
        rows += build_xtensa()
    else:
        build_host()
        rows += run_host(vectors)
        BUILD.mkdir(exist_ok=True)
        rows += build_xtensa()
    P4E.write_csv(rows, ROOT / "results" / "15_portable_equivalence.csv")
    n_pass = sum(r["passed"] for r in rows)
    print(f"equivalence: {n_pass}/{len(rows)} passed")
    for r in rows:
        print(" ", r)


if __name__ == "__main__":
    main()
