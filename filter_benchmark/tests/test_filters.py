"""Numerical tests for the filter library (spec §4: tests for irregular
intervals and missing data; user mandate: initialization, missing samples,
recovery). Run: pytest tests/ -q
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import synth  # noqa: E402
from filters import FILTERS  # noqa: E402


def run_stream(f, t, z):
    out = np.empty(len(t))
    for i in range(len(t)):
        out[i] = f.update(float(z[i]), float(t[i]))
    return out


def make_filters():
    return {name: factory() for name, factory in FILTERS.items()}


class TestContract:
    def test_all_filters_run_constant_climb_without_nan(self):
        t = np.arange(0, 10, 0.01)
        z = synth.constant_climb(t, v=1.0)
        for name, f in make_filters().items():
            v = run_stream(f, t, z)
            tail = v[len(v) // 2:]
            assert np.all(np.isfinite(v)), f"{name} produced non-finite output"
            assert abs(np.mean(tail) - 1.0) < 0.15, \
                f"{name} failed to track 1 m/s climb (mean {np.mean(tail):.3f})"

    def test_reset_restores_initial_state(self):
        t = np.arange(0, 10, 0.01)
        for name, f in make_filters().items():
            f2 = FILTERS[name]()
            run_stream(f, t, synth.constant_climb(t, v=2.0))
            f.reset()
            run_stream(f2, t, synth.constant_climb(t, v=0.0))
            run_stream(f, t, synth.constant_climb(t, v=0.0))
            a = run_stream(f, t[:500], synth.constant_climb(t[:500], v=0.0))
            b = run_stream(f2, t[:500], synth.constant_climb(t[:500], v=0.0))
            assert np.allclose(a, b, atol=1e-9), f"{name} reset() not clean"

    def test_initialization_first_sample_gives_zero_velocity(self):
        t = np.arange(0, 1, 0.01)
        for name, f in make_filters().items():
            f.reset()
            v0 = f.update(100.0, t[0])     # altitude ~100 m equivalent
            assert v0 == v0 and abs(v0) < 1e-9, f"{name} bad first sample"


class TestIrregularSampling:
    def test_irregular_timestamps_stay_finite(self):
        rng = np.random.default_rng(7)
        t = synth.irregular_timestamps(np.arange(0, 10, 0.01), 0.004, rng)
        z = synth.constant_climb(t, v=1.0) + rng.normal(0, 0.05, len(t))
        for name, f in make_filters().items():
            v = run_stream(f, t, z)
            tail = v[len(v) // 2:]
            assert np.all(np.isfinite(v)), f"{name} NaN under jitter"
            assert abs(np.mean(tail) - 1.0) < 0.25, \
                f"{name} lost track under jitter ({np.mean(tail):.3f})"

    def test_missing_samples_gap_recovery(self):
        rng = np.random.default_rng(11)
        t_full = np.arange(0, 10, 0.01)
        t = synth.missing_samples(t_full, drop_every=37)
        z = synth.constant_climb(t, v=1.0) + rng.normal(0, 0.05, len(t))
        for name, f in make_filters().items():
            v = run_stream(f, t, z)
            tail = v[int(len(v) * 0.8):]
            assert np.all(np.isfinite(v)), f"{name} NaN after missing samples"
            assert abs(np.mean(tail) - 1.0) < 0.25, \
                f"{name} did not recover after gaps ({np.mean(tail):.3f})"

    def test_duplicate_and_out_of_order_timestamps(self):
        t = np.arange(0, 5, 0.01)
        t2 = t.copy()
        t2[100] = t2[99]                    # duplicate
        t2[200] = t2[199] - 0.005           # out of order
        t2 = np.maximum.accumulate(np.where(np.arange(len(t2)) == 200, t2[199], t2))
        z = synth.constant_climb(t2, v=1.0)
        for name, f in make_filters().items():
            v = run_stream(f, t2, z)
            assert np.all(np.isfinite(v)), f"{name} NaN on dup/o-o t"


class TestPhysics:
    def test_rate_equivalence_45_vs_100_hz(self):
        """Physically equivalent parameterizations must behave alike across
        rates (user mandate). EMA tau=0.5 s at 10 ms vs 22.2 ms dt."""
        for name in ("A02_EMA", "B01_LP1", "C01_AlphaBeta"):
            t100 = np.arange(0, 10, 0.01)
            t45 = np.arange(0, 10, 1 / 45.0)
            z100 = synth.step_velocity(t100, v1=1.0, t_step=5.0)
            z45 = synth.step_velocity(t45, v1=1.0, t_step=5.0)
            v100 = run_stream(FILTERS[name](), t100, z100)
            v45 = run_stream(FILTERS[name](), t45, z45)
            # 63% response time after the step must agree within 30%
            def t63(tt, vv):
                m = tt > 5.0
                base = np.mean(vv[(tt > 3) & (tt < 5)])
                tgt = base + 0.63 * (1.0 - base)
                idx = np.where(m & (vv >= tgt))[0]
                return tt[idx[0]] - 5.0 if len(idx) else np.nan
            a, b = t63(t100, v100), t63(t45, v45)
            assert a == a and b == b, f"{name}: no 63% crossing found"
            assert abs(a - b) / max(a, b, 1e-9) < 0.3, \
                f"{name} rate-dependent: t63 100Hz={a:.3f}s 45Hz={b:.3f}s"

    def test_hampel_rejects_spike(self):
        rng = np.random.default_rng(3)
        t = np.arange(0, 10, 0.01)
        z = rng.normal(0, 0.05, len(t))
        z[500] += 3.0                          # isolated 3 m spike
        f = FILTERS["A05_Hampel"](window_s=1.0, n_sigma=3.0)
        v = run_stream(f, t, z)
        # spike must not propagate as a sustained velocity excursion
        m = (t > 5.2) & (t < 6.0)
        assert np.max(np.abs(v[m])) < 0.5, \
            f"spike propagated: max |v| after = {np.max(np.abs(v[m])):.2f}"

    def test_kalman_cv_converges_on_constant_velocity(self):
        rng = np.random.default_rng(5)
        t = np.arange(0, 20, 0.02)
        z = synth.constant_climb(t, v=1.5) + rng.normal(0, 0.15, len(t))
        f = FILTERS["D01_Kalman_CV"]()
        v = run_stream(f, t, z)
        assert abs(np.mean(v[-500:]) - 1.5) < 0.05


class TestAudioPolicy:
    def test_latch_count_stationary_is_low(self):
        from metrics import count_latches
        rng = np.random.default_rng(9)
        v = rng.normal(0, 0.06, 6000)          # 60 s at 100 Hz, rest-like
        t = np.arange(len(v)) * 0.01
        assert count_latches(v, t, 0.20, 0.05) <= 3


class TestConfigReprRoundTrip:
    def test_repr_keys_match_constructor_kwargs(self):
        """Every key in _config_repr() must be an accepted constructor kwarg
        with a numeric value, so 'config' strings in results CSVs can be
        re-parsed to reproduce the exact filter (benchmark reproducibility)."""
        import inspect
        for name, factory in FILTERS.items():
            f = factory()
            cls = type(f)
            params = inspect.signature(cls.__init__).parameters
            cfg = f._config_repr()
            if not cfg.strip():
                continue                       # knob-less filter (B00_diff)
            for pair in cfg.split(","):
                k, _, v = pair.partition("=")
                k = k.strip()
                assert k in params, \
                    f"{name}: repr key '{k}' not a constructor param"
                if v.strip() in ("True", "False"):
                    FILTERS[name](**{k: v.strip() == "True"})
                else:
                    float(v)   # all benchmark knobs are numeric
                    FILTERS[name](**{k: float(v)})
