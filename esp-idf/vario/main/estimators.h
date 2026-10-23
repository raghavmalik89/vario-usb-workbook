/* estimators.h — per-sid estimator bank: the competing architectures run
 * side by side on the MCU, all fed identical compensated altitude samples
 * (and, for fusion, the shared attitude-quaternion stream).
 *
 * Parity contract: every algorithm is a step-for-step port of its Python
 * reference in filter_benchmark/src (D01 filters/kalman.py, C03
 * filters/tracking.py steady_state_gains, S4 filters/stacked.py
 * S4FastSlowGated, S5 = portable vario_core, FUS fusion.py + attitude.py),
 * in double precision. The hardware-vs-model comparison replays the same
 * capture through the Python bank with the same configs.
 *
 * eid = sid * N_EST + {0:D01, 1:C03, 2:S4, 3:S5, 4:FUS}.
 */
#ifndef ESTIMATORS_H
#define ESTIMATORS_H

#ifdef __cplusplus
extern "C" {
#endif

/* One IMU sample: updates the SHARED Madgwick attitude (called once per
 * sample, not per bank), then propagates each fusion instance. */
void attitude_feed(const double a_body_m_s2[3], const double g_rad_s[3],
                   double t_s);
void bank_feed_imu(int sid, const double a_body_m_s2[3], double t_s);

/* One baro altitude sample [m] at physical time t [s] for one sid:
 * updates all five estimators and drives the virtual-audio state machines
 * (V frames are emitted here on ON/OFF/tone-change). */
void bank_feed_baro(int sid, double alt_m, double t_s);

double bank_velocity(int sid, int which);   /* current v estimate [m/s] */

/* Per-B-window audio-path diagnostics, consumed+reset by the B report:
 * ON transitions, fault vetoes, max |v| [m/s], NaN-sample count. */
void bank_audio_stats(unsigned long *on, unsigned long *fault,
                      double *vmax, unsigned long *nan_n);

#ifdef __cplusplus
}
#endif

#endif
