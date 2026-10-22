"""6-DOF IMU attitude estimation (Madgwick gradient-descent, IMU variant).

Sensor-independent: takes physical-units accel (m/s^2) and gyro (rad/s),
returns quaternion (w, x, y, z) rotating BODY -> EARTH. No magnetometer, so
yaw is unobservable and drifts — harmless for vario work because Earth-Z
specific force depends only on roll/pitch.

Reference: Madgwick, "An efficient orientation filter for inertial and
inertial/magnetic sensor arrays", 2010 (IMU update).

Implementation note: the objective is built from EXACT quaternion rotation
(q^-1 ⊗ g ⊗ q) and the Jacobian from central differences on the
unit-quaternion manifold. A closed-form expanded objective once shipped
here with a mis-transcribed z-component (1−q0²−q1²+q2²+q3² instead of
1−2q1²−2q2²) and converged to a bogus steady state that looked plausible in
casual checks — exact rotation + numeric Jacobian is slower but immune to
transcription errors. Offline analysis only; if this ever moves to the
portable C core, derive the analytic Jacobian from the exact form and
re-verify against the test suite.
"""
from __future__ import annotations

import numpy as np

G0 = 9.80665

_GRAV = np.array([0.0, 0.0, 0.0, 1.0])   # earth-down as a pure quaternion
_EPS = 1e-5


def _conj(q):
    """Quaternion conjugate (inverse for a unit quaternion)."""
    q = np.asarray(q, dtype=float)
    out = q.copy()
    out[1:] *= -1.0
    return out


def _qmul(a, b):
    """Hamilton product a ⊗ b, (w, x, y, z) convention."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ])


def _grav_pred_body(q):
    """Predicted gravity direction in BODY coords: q^-1 ⊗ (0,0,1) ⊗ q."""
    p = _qmul(_conj(q), _GRAV)
    p = _qmul(p, q)
    return p[1:]


def madgwick_update(q, accel_body, omega, dt, beta=0.3, accel_sign=-1.0):
    """One Madgwick IMU update.

    q: (w, x, y, z) BODY->EARTH quaternion; a new normalized array is returned.
    accel_body: 3-axis specific force, any consistent units (normalized inside).
    omega: gyro rates rad/s.
    dt: sample interval s.
    beta: gradient-step gain, rad/s scale (~proportional to gyro noise; 0.3 is
    a good MPU6050 starting point — 0.08 converges too slowly from a large
    initial tilt).
    accel_sign: the accelerometer measures SPECIFIC FORCE (−gravity) while the
    objective matches the predicted gravity direction against the measurement;
    -1 means 'measured accel is opposite to gravity' (the physical
    convention, verified by the unit tests).
    """
    q = np.asarray(q, dtype=float)
    a = np.asarray(accel_body, dtype=float)
    an = np.linalg.norm(a)
    if an < 1e-9:
        # free fall: no accel reference, pure gyro propagation
        g = np.asarray(omega, dtype=float)
        qdot = 0.5 * _qmul(q, np.array([0.0, g[0], g[1], g[2]]))
        qn = q + qdot * dt
        return qn / np.linalg.norm(qn)
    a_dir = accel_sign * a / an
    gx, gy, gz = (float(v) for v in omega)

    f = _grav_pred_body(q) - a_dir

    def pred_shifted(j, h):
        qj = q.copy()
        qj[j] += h
        qj /= np.linalg.norm(qj)
        return _grav_pred_body(qj)

    J = np.empty((3, 4))
    for j in range(4):
        J[:, j] = (pred_shifted(j, _EPS) - pred_shifted(j, -_EPS)) / (2 * _EPS)
    step = J.T @ f
    n = np.linalg.norm(step)
    if n > 1e-12:
        step = step / n

    qdot = 0.5 * _qmul(q, np.array([0.0, gx, gy, gz])) - beta * step
    qn = q + qdot * dt
    return qn / np.linalg.norm(qn)


def estimate_attitude(t_s, accel_body, omega, beta=0.3, q0=(1.0, 0.0, 0.0, 0.0)):
    """Run the filter over sample arrays. Returns (N, 4) quaternions in the
    BODY->EARTH convention required by fusion.gravity_compensate.

    t_s: physical timestamps [s] (monotone; intervals derived from them —
    jitter and small gaps are absorbed, large gaps just propagate with gyro).
    """
    t = np.asarray(t_s, dtype=float)
    a = np.asarray(accel_body, dtype=float)
    w = np.asarray(omega, dtype=float)
    n = len(t)
    out = np.empty((n, 4))
    q = np.asarray(q0, dtype=float)
    q = q / np.linalg.norm(q)
    out[0] = q
    for i in range(1, n):
        dt = t[i] - t[i - 1]
        if dt <= 0:
            out[i] = out[i - 1]
            continue
        # clamp pathological gaps: propagate, don't explode the gradient step
        q = madgwick_update(q, a[i], w[i], min(dt, 0.1), beta=beta)
        out[i] = q
    return out


def accel_vertical_body_frame(quat):
    """Earth-Z unit axis expressed in body coords (for gravity compensation
    without building the full rotation matrix)."""
    w, x, y, z = quat
    return np.array([2 * (x * z - w * y), 2 * (y * z + w * x),
                     1 - 2 * (x * x + y * y)])
