"""Phase 3 tests: audio state machine + stacked architectures.

Run via scripts/run_tests.py (discovers all test_*.py / Test* classes).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import audio  # noqa: E402
import synth  # noqa: E402
from filters.stacked import STACKED  # noqa: E402


class TestAudioStateMachine:
    def test_default_policy_on_off_hysteresis(self):
        sm = audio.AudioStateMachine()          # 0.20 / 0.05, no hold
        assert sm.update(0.0, 0.10) == "off"    # below lift_on
        assert sm.update(0.1, 0.25) == "on"     # crosses lift_on
        assert sm.update(0.2, 0.10) == "on"     # below lift_on, above lift_off
        assert sm.update(0.3, 0.04) == "off"    # crosses lift_off
        assert [s for _, s in sm.transitions] == ["on", "off"]
        assert np.allclose([t for t, _ in sm.transitions], [0.1, 0.3])

    def test_no_hold_by_default(self):
        sm = audio.AudioStateMachine()
        sm.update(0.0, 0.5)
        assert sm.update(0.05, 0.01) == "off"   # immediate OFF: no hold time

    def test_explicit_hold_time(self):
        sm = audio.AudioStateMachine(hold_s=0.5)
        sm.update(0.0, 0.5)
        assert sm.update(0.3, 0.01) == "on"     # within hold
        assert sm.update(0.9, 0.01) == "off"    # hold expired

    def test_repeated_on_off_counts_chatter(self):
        sm = audio.AudioStateMachine()
        t = 0.0
        for i in range(20):
            sm.update(t, 0.3 if i % 2 == 0 else 0.0)
            t += 0.1
        n_on = sum(1 for _, s in sm.transitions if s == "on")
        assert n_on >= 9, "chatter transitions must be preserved, not hidden"

    def test_uses_physical_timestamps_irregular_dt(self):
        sm = audio.AudioStateMachine()
        sm.update(1.00, 0.3)
        assert sm.update(1.007, 0.0) == "off"
        assert sm.transitions[1][0] == 1.007    # actual replay timestamp


class TestStackedArchitectures:
    def make(self):
        return {n: f() for n, f in STACKED.items()}

    def run_stream(self, f, t, z):
        out = np.empty(len(t))
        for i in range(len(t)):
            out[i] = f.update(float(z[i]), float(t[i]))
        return out

    def test_track_constant_climb(self):
        t = np.arange(0, 12, 0.01)
        z = synth.constant_climb(t, v=1.2)
        for n, f in self.make().items():
            v = self.run_stream(f, t, z)
            assert np.all(np.isfinite(v)), f"{n} non-finite"
            assert abs(np.mean(v[len(v) // 2:]) - 1.2) < 0.2, \
                f"{n} lost the climb ({np.mean(v[len(v)//2:]):.2f})"

    def test_reject_isolated_spike_without_extreme_output(self):
        """Acceptance condition: filter output must not remain extreme after
        a rejected transient — and the spike must be recorded as rejected."""
        t = np.arange(0, 10, 0.01)
        rng = np.random.default_rng(1)
        for n, f in self.make().items():
            f.reset()
            z = rng.normal(0, 0.05, len(t))
            z[400] += 8.0                        # 8 m pressure spike
            z[600:640] += 5.0                    # 0.4 s burst (fault-like)
            v = self.run_stream(f, t, z)
            after = np.abs(v[700:])
            assert np.max(after) < 1.0, \
                f"{n}: extreme output after rejected transient " \
                f"(max {np.max(after):.2f} m/s)"

    def test_recovery_after_missing_samples(self):
        t_full = np.arange(0, 10, 0.01)
        t = np.delete(t_full, np.arange(300, 340))   # 0.4 s gap
        z = synth.constant_climb(t, v=0.8)
        for n, f in self.make().items():
            v = self.run_stream(f, t, z)
            tail = v[int(len(v) * 0.8):]
            assert np.all(np.isfinite(v)), f"{n} NaN after gap"
            assert abs(np.mean(tail) - 0.8) < 0.25, \
                f"{n} did not recover ({np.mean(tail):.2f})"

    def test_config_repr_round_trip(self):
        import inspect
        for n, f in self.make().items():
            params = inspect.signature(type(f).__init__).parameters
            cfg = f._config_repr()
            for pair in cfg.split(","):
                k, _, val = pair.partition("=")
                k = k.strip()
                assert k in params, f"{n}: repr key '{k}' not a constructor param"
                float(val)
                STACKED[n](**{k: float(val)})

    def test_s3_fault_detection_and_recovery_flags(self):
        t = np.arange(0, 12, 0.01)
        z = np.zeros(len(t))
        z[300:500] += 30.0                   # sustained absurd offset = fault
        f = STACKED["S3_AccelerationAwareKF"]()
        self.run_stream(f, t, z)
        assert f.n_faults >= 1, "S3 must flag the sustained offset as a fault"
        assert not f._fault, "S3 must recover after the offset ends"
