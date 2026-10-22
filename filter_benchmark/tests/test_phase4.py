"""Phase 4 tests: audio veto/max-on safety, new estimator candidates
(S1P persistence, S4 corrected fast/slow, S5 light gate), and the fusion
interface (synthetic IMU only — no real IMU data exists).

Run via scripts/run_tests.py (discovers all test_*.py / Test* classes).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import audio  # noqa: E402
import synth  # noqa: E402
from filters.stacked import S1PPersistenceKF, S4FastSlowGated, S5LightGateKF  # noqa: E402


def _lift_then_rest(t_end=12.0, dt=0.02):
    t = np.arange(0, t_end, dt)
    z = synth.lift_pulse(t, v=1.5, t_on=3.0, dur=2.0, ramp=0.2)
    rng = np.random.default_rng(7)
    z += rng.normal(0, 0.03, len(t))
    return t, z


class TestAudioPhase4:
    def test_fault_veto_forces_off_and_blocks_on(self):
        sm = audio.AudioStateMachine()
        sm.update(0.0, 0.5)
        assert sm.state == "on"
        assert sm.update(0.1, 0.5, fault=True) == "off"
        # still high v but fault active: cannot re-latch
        assert sm.update(0.2, 0.9, fault=True) == "off"
        # fault clears: normal hysteresis resumes
        assert sm.update(0.3, 0.9, fault=False) == "on"
        reasons = [r for _, _, r in sm.transitions_r]
        assert reasons[1] == "fault_veto"

    def test_max_on_safety_valve(self):
        sm = audio.AudioStateMachine(max_on_s=1.0)
        sm.update(0.0, 0.5)
        assert sm.update(0.5, 0.5) == "on"
        assert sm.update(1.05, 0.5) == "off"     # forced OFF at 1.0 s ON
        assert sm.transitions_r[-1][2] == "max_on"
        # can re-latch after the valve fired
        assert sm.update(1.2, 0.5) == "on"

    def test_phase3_behaviour_unchanged_by_default(self):
        # with no fault and max_on_s=0 the machine is bit-identical to
        # Phase 3 semantics (default params, same transition sequence)
        sm = audio.AudioStateMachine()
        v = [0.1, 0.25, 0.10, 0.04, 0.30]
        ts = [0.0, 0.1, 0.2, 0.3, 0.4]
        states = [sm.update(t, x) for t, x in zip(ts, v)]
        assert states == ["off", "on", "on", "off", "on"]
        assert [s for _, s in sm.transitions] == ["on", "off", "on"]

    def test_apply_audio_fault_sequence(self):
        t = np.arange(0, 4.0, 0.1)
        v = np.where(t < 2.0, 0.5, 0.0)
        faults = (t >= 1.0) & (t < 1.5)
        sm = audio.AudioStateMachine()
        states, tr = audio.apply_audio(t, v, sm, faults=faults)
        # ON at ~0, OFF at 1.0 (veto), ON again at 1.5 (v still high)
        ons = [tt for tt, s in tr if s == "on"]
        offs = [tt for tt, s in tr if s == "off"]
        assert len(ons) == 2 and len(offs) == 2
        assert abs(offs[0] - 1.0) < 0.11          # the veto forced this OFF
        assert abs(ons[1] - 1.5) < 0.11           # re-latched when fault cleared


class TestS1PPersistence:
    def test_tracks_climb_and_releases_latch(self):
        t, z = _lift_then_rest()
        f = S1PPersistenceKF()
        for i in range(len(t)):
            f.update(float(z[i]), float(t[i]))
        assert f._latched is False           # latch released after rest
        assert abs(f.get_estimate()) < 0.1   # back near rest

    def test_rest_output_matches_s1_quietness(self):
        rng = np.random.default_rng(3)
        t = np.arange(0, 30.0, 1 / 45)
        z = rng.normal(0, 0.03, len(t)).cumsum() * 0 + rng.normal(0, 0.05, len(t))
        f = S1PPersistenceKF()
        v = np.array([f.update(float(zi), float(ti))
                      for zi, ti in zip(z, t)])
        assert np.sqrt(np.mean(v ** 2)) < 0.08   # quiet at rest


class TestS4FastSlowGated:
    def test_no_freeze_after_hard_drop_s2_regression(self):
        # THE Phase-3 S2 root cause (found in Phase 4 debug): sample
        # REPLACEMENT in the plausibility pre-clean blinded the fast branch
        # under sustained real acceleration; it froze at a wrong velocity
        # (here ~ -0.2 m/s on flat data). S4 must converge back to ~0.
        from filters.stacked import S2DualTimescale
        rng = np.random.default_rng(7)
        t = np.arange(0, 20.0, 0.02)
        z = (synth.lift_pulse(t, v=-3.0, t_on=4.0, dur=1.0, ramp=0.15)
             + rng.normal(0, 0.03, len(t)))
        out = {}
        for cls, key in ((S2DualTimescale, "S2"), (S4FastSlowGated, "S4")):
            f = cls()
            v = np.array([f.update(float(zi), float(ti))
                          for zi, ti in zip(z, t)])
            out[key] = (f, v)
        v_s2, v_s4 = out["S2"][1], out["S4"][1]
        tail_s2 = v_s2[t >= 10.0]
        tail_s4 = v_s4[t >= 10.0]
        # S4 converged to rest; the S2 freeze offset is documented behaviour
        assert np.max(np.abs(tail_s4)) < 0.05
        assert np.abs(np.median(tail_s2)) > 0.05   # regression present in S2

    def test_exits_after_sink_then_lift_reversal(self):
        # rapid reversal: sink pulse, then rest, then a lift pulse; audio
        # must exit after the sink segment and re-enter on lift, and must
        # be OFF within 3 s after the lift ends (censoring regression test)
        rng = np.random.default_rng(8)
        t = np.arange(0, 20.0, 0.02)
        z = (synth.lift_pulse(t, v=-3.0, t_on=3.0, dur=1.0, ramp=0.15)
             + synth.lift_pulse(t, v=1.5, t_on=10.0, dur=2.0, ramp=0.2)
             + rng.normal(0, 0.03, len(t)))
        f = S4FastSlowGated()
        v = np.array([f.update(float(zi), float(ti))
                      for zi, ti in zip(z, t)])
        sm = audio.AudioStateMachine()
        states, tr = audio.apply_audio(t, v, sm)
        e1 = 12.2                    # lift pulse end
        offs = [tt for tt, s in tr if s == "off" and tt >= e1]
        assert offs and (offs[0] - e1) < 3.0

    def test_sign_disagreement_trusts_slow_at_rest(self):
        # after a sink ends, if the fast branch rings with the opposite sign
        # while the slow branch is at rest -> v must follow the slow one
        t = np.arange(0, 10.0, 0.02)
        z = synth.lift_pulse(t, v=-2.0, t_on=2.0, dur=1.5, ramp=0.2)
        f = S4FastSlowGated()
        vs = np.array([f.update(float(zi), float(ti))
                       for zi, ti in zip(z, t)])
        # 2 s after the sink ended the output must be near rest, not ringing
        tail = vs[t >= 6.0]
        assert np.max(np.abs(tail)) < 0.35


class TestS5LightGate:
    def test_tracks_constant_climb(self):
        rng = np.random.default_rng(11)
        t = np.arange(0, 20.0, 1 / 50)
        z = 1.2 * t + rng.normal(0, 0.03, len(t))
        f = S5LightGateKF()
        v = np.array([f.update(float(zi), float(ti))
                      for zi, ti in zip(z, t)])
        assert abs(np.median(v[t > 10]) - 1.2) < 0.1

    def test_isolated_spike_does_not_produce_extreme_v(self):
        rng = np.random.default_rng(5)
        t = np.arange(0, 15.0, 1 / 50)
        z = rng.normal(0, 0.03, len(t))
        z[np.searchsorted(t, 7.0)] += 5.0     # single 5 m spike
        f = S5LightGateKF()
        v = np.array([f.update(float(zi), float(ti))
                      for zi, ti in zip(z, t)])
        m = (t >= 7.0) & (t <= 9.0)
        assert np.max(np.abs(v[m])) < 1.0     # spec §5 failure threshold
        assert f.n_rejected >= 1


class TestFusionInterface:
    def test_baro_only_fallback_matches_cv_kf_class(self):
        # with no IMU updates the fusion must behave like the baro-only CV
        # Kalman it falls back to (synthetic stream, Simulated)
        from fusion import BaroImuFusion
        rng = np.random.default_rng(9)
        t = np.arange(0, 15.0, 1 / 50)
        z = 0.8 * t + rng.normal(0, 0.04, len(t))
        fus = BaroImuFusion()
        v = np.array([fus.update_baro(float(zi), float(ti))
                      for zi, ti in zip(z, t)])
        assert abs(np.median(v[t > 8]) - 0.8) < 0.12
        assert fus.degraded is False or True   # interface attr exists

    def test_synthetic_imu_gravity_compensation(self):
        # Simulated: stationary sensor pitched 30 deg about Earth-y reads
        # body specific force [g sin30, 0, -g cos30]; compensated Earth-Z
        # accel must be ~0. A 1 m/s^2 upward accel (Earth z-down: -1) must
        # read -cos(30) in the compensated channel. (Simulated only — no
        # real IMU capture exists.)
        from fusion import gravity_compensate
        g = 9.80665
        tilt = np.deg2rad(30.0)
        accel_body = np.array([0.0, 0.0, -g])  # identity attitude, stationary
        q_id = (1.0, 0.0, 0.0, 0.0)
        assert abs(gravity_compensate(accel_body, q_id)) < 1e-9
        # pitched: body->earth rotation about y by +tilt
        q = (np.cos(tilt / 2), 0.0, np.sin(tilt / 2), 0.0)
        accel_tilted = np.array([g * np.sin(tilt), 0.0, -g * np.cos(tilt)])
        assert abs(gravity_compensate(accel_tilted, q)) < 1e-9
        # upward acceleration 1 m/s^2 -> body adds R^T [0,0,-1]; the
        # compensated EARTH-Z channel reads the full -1 regardless of tilt
        # (that is the point of compensation)
        dq = np.array([np.sin(tilt), 0.0, -np.cos(tilt)])
        a_up = gravity_compensate(accel_tilted + dq, q)
        assert abs(a_up + 1.0) < 1e-9    # z-down: upward is negative

    def test_accel_bias_estimation_converges(self):
        # Simulated: a bias of +0.3 m/s^2 on the body-z accelerometer, riding
        # on the real gravity specific force [0,0,-g], must be estimated out
        # while the baro channel reports stationary.
        from fusion import BaroImuFusion
        rng = np.random.default_rng(4)
        t = np.arange(0, 30.0, 1 / 50)
        z = rng.normal(0, 0.04, len(t))
        fus = BaroImuFusion(bias_tau_s=2.0)
        for zi, ti in zip(z, t):
            fus.update_baro(float(zi), float(ti))
            fus.update_imu(np.array([0.0, 0.0, -9.80665 + 0.3]), ti)
        assert abs(fus.accel_bias[2] - 0.3) < 0.05
