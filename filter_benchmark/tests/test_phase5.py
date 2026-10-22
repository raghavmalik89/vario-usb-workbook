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
