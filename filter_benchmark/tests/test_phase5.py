"""Phase 5 tests: Madgwick attitude estimator + t007 IMU loader."""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import attitude  # noqa: E402
import imu_io  # noqa: E402
from fusion import gravity_compensate  # noqa: E402

G0 = 9.80665


class TestMadgwick:
    def test_static_accel_vertical_converges(self):
        # rig at rest, body X pointing up (as-built X-up mounting): accel
        # reads +g on x. The estimator must find an attitude where the
        # Earth-Z specific force is ~0 after convergence.
        n = 2000
        t = np.arange(n) * 0.005
        a = np.tile([G0, 0.0, 0.0], (n, 1))
        w = np.zeros((n, 3))
        q = attitude.estimate_attitude(t, a, w)
        az = np.array([gravity_compensate(a[i], q[i]) for i in range(n)])
        assert abs(np.mean(az[-500:])) < 0.05, np.mean(az[-500:])

    def test_pure_gyro_rotation_keeps_vertical(self):
        # rotating about the vertical (body X) axis must not leak into the
        # vertical accel channel
        n = 2000
        t = np.arange(n) * 0.005
        a = np.tile([G0, 0.0, 0.0], (n, 1))
        w = np.zeros((n, 3))
        w[:, 0] = 1.0  # 1 rad/s about body x
        q = attitude.estimate_attitude(t, a, w)
        az = np.array([gravity_compensate(a[i], q[i]) for i in range(n)])
        assert abs(np.mean(az[-500:])) < 0.1, np.mean(az[-500:])

    def test_tilt_then_hold_recovers_pitch(self):
        # 90 deg pitch about y for 2 s, then back: filter follows and returns
        n = 2400
        t = np.arange(n) * 0.005
        a = np.zeros((n, 3))
        a[:, 0] = G0
        # body z picks up gravity when pitched 90 deg about y
        seg = slice(400, 1600)
        a[seg, 0] = 0.0
        a[seg, 2] = G0
        w = np.zeros((n, 3))
        q = attitude.estimate_attitude(t, a, w)
        az_mid = gravity_compensate(a[1000], q[1000])
        az_end = np.mean([gravity_compensate(a[i], q[i])
                          for i in range(2000, 2400)])
        assert abs(az_mid) < 0.2, az_mid       # gravity removed while tilted
        assert abs(az_end) < 0.1, az_end       # recovered after return

    def test_free_fall_does_not_explode(self):
        n = 500
        t = np.arange(n) * 0.005
        a = np.zeros((n, 3))  # |a| ~ 0 during free fall
        w = np.zeros((n, 3))
        q = attitude.estimate_attitude(t, a, w)
        assert np.all(np.isfinite(q))
        assert np.allclose(np.linalg.norm(q, axis=1), 1.0, atol=1e-9)


class TestImuIo:
    def _make_capture(self, tmp, imu_on=True):
        csv = tmp / "20261023_000000_t007_teststatic.csv"
        hdr = "seq,t_us,type,sid,d1,d2,ax,ay,az,gx,gy,gz"
        lines = [hdr]
        seq = 0
        for i in range(400):
            t_us = i * 5000
            v = 4096 if i > 50 else 0
            lines.append(f"{seq},{t_us},I,,,,{v},0,0,10,-20,5")
            seq += 1
            if i % 10 == 0:
                lines.append(f"{seq},{t_us},P,0,8000000,,,,,,,")
                seq += 1
        csv.write_text("\n".join(lines) + "\n")
        cfg = "osr=2048,p_hz=90,t_hz=10,sensors=2,imu=%s,i_hz=200,a_lsb_per_g=4096,g_lsb_per_dps=65.5" % (
            "on" if imu_on else "off")
        side = {"label": "t007_teststatic",
                "device": {"firmware": "vario-bench-t007 0.7.0", "config": cfg}}
        csv.with_suffix(".json").write_text(json.dumps(side))
        return csv

    def test_scales_from_meta_not_hardcoded(self):
        with tempfile.TemporaryDirectory() as d:
            csv = self._make_capture(Path(d))
            imu = imu_io.imu_stream(csv)
            assert imu is not None
            # 4096 counts/g with a_lsb_per_g=4096 -> exactly 1 g on x
            assert abs(np.mean(imu["accel"][:, 0][100:200]) - G0) < 1e-9
            # gyro: 10 counts @ 65.5 LSB/dps = 0.15267 dps in rad/s
            expect = 10 / 65.5 * np.pi / 180.0
            assert abs(np.mean(imu["gyro"][:, 0]) - expect) < 1e-12

    def test_meta_scales_actually_used(self):
        # a sensor swap changes ONLY the meta: 2048 LSB/g doubles the accel
        with tempfile.TemporaryDirectory() as d:
            csv = self._make_capture(Path(d))
            side = json.loads(csv.with_suffix(".json").read_text())
            side["device"]["config"] = side["device"]["config"].replace(
                "a_lsb_per_g=4096", "a_lsb_per_g=2048")
            csv.with_suffix(".json").write_text(json.dumps(side))
            imu = imu_io.imu_stream(csv)
            assert abs(np.mean(imu["accel"][:, 0][100:200]) - 2 * G0) < 1e-9

    def test_imu_off_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            csv = self._make_capture(Path(d), imu_on=False)
            assert imu_io.imu_stream(csv) is None


class TestTiltInit:
    def test_exact_at_rest_any_orientation(self):
        # shortest-arc init must remove gravity EXACTLY (to float precision)
        # for any static orientation — az(0) ~ 0 by construction.
        rng = np.random.default_rng(7)
        for _ in range(20):
            a = rng.normal(0, 1, 3)
            a = a / np.linalg.norm(a) * G0
            q0 = attitude.quat_from_accel_tilt(a)
            assert abs(gravity_compensate(a, q0)) < 1e-9
            assert abs(np.linalg.norm(q0) - 1.0) < 1e-12

    def test_zero_accel_falls_back_to_identity(self):
        q0 = attitude.quat_from_accel_tilt([0, 0, 0])
        assert np.allclose(q0, [1, 0, 0, 0])

    def test_warm_start_removes_convergence_transient(self):
        # tilted rig at rest: identity start leaks gravity into az for ~5 s;
        # tilt init must be clean from sample 0 (the [M] t007 failure mode).
        n = 1000
        t = np.arange(n) * 0.005
        tilt = np.radians(6.3)
        R = np.array([[1, 0, 0], [0, np.cos(tilt), -np.sin(tilt)],
                      [0, np.sin(tilt), np.cos(tilt)]])
        a = (R.T @ (np.array([0, 0, -G0])[:, None] * np.ones((1, n)))).T
        w = np.zeros((n, 3))
        q_cold = attitude.estimate_attitude(t, a, w)
        q_warm = attitude.estimate_attitude(
            t, a, w, q0=attitude.quat_from_accel_tilt(a[0]))
        head = slice(0, 200)   # first second
        az_cold = np.mean(np.abs([gravity_compensate(a[i], q_cold[i])
                                  for i in range(*head.indices(n))]))
        az_warm = np.mean(np.abs([gravity_compensate(a[i], q_warm[i])
                                  for i in range(*head.indices(n))]))
        assert az_warm < 0.02, az_warm
        assert az_warm < 0.1 * az_cold, (az_warm, az_cold)


class TestFaultRecovery:
    def test_persistent_outlier_reinitializes_and_reacquires(self):
        # 12 samples offset by +50 m = persistent loss of track: the filter
        # must declare fault, reinit from the measurement, and track again
        # once truth returns (pre-Phase-5 behavior: flag only, coast forever).
        from fusion import BaroImuFusion
        f = BaroImuFusion(q=10.0, r=0.042)
        t = np.arange(400) * 0.011
        h = 0.5 * np.sin(0.1 * t)
        v = np.empty(len(t))
        for i, tt in enumerate(t):
            v[i] = f.update_baro(h[i] + (50.0 if 200 <= i < 212 else 0.0), tt)
        assert f.n_reinit >= 1, f.n_reinit
        assert np.all(np.isfinite(v))
        # after the burst, h must reacquire truth (v finite, no runaway)
        assert abs(v[-1]) < 1.0, v[-1]
        assert not f.fault

    def test_isolated_spike_is_gated_not_fatal(self):
        from fusion import BaroImuFusion
        f = BaroImuFusion(q=10.0, r=0.042)
        t = np.arange(400) * 0.011
        h = 0.5 * np.sin(0.1 * t)
        h[200] += 50.0                    # one-sample glitch
        v = np.empty(len(t))
        for i, tt in enumerate(t):
            v[i] = f.update_baro(h[i], tt)
        assert f.n_reinit == 0
        assert f.n_gated >= 1             # the glitch was rejected
        assert abs(v[-1]) < 1.0           # state survived
