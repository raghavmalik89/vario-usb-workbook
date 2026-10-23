/* estimators.c — estimator bank; see estimators.h for the parity contract. */
#include "estimators.h"

#include <math.h>
#include <string.h>

#include "bench.h"
#include "config.h"
#include "madgwick.h"
#include "tx.h"
#include "vario_core.h"

/* ------------------------------------------------------------------ */
/* D01 — plain CV Kalman (kalman.py::D01KalmanCV, q/r fixed)           */
/* ------------------------------------------------------------------ */
typedef struct {
    double h, v, p00, p01, p11;
    double t_prev;
    int init;
} d01_t;

static void d01_reset(d01_t *f)
{
    memset(f, 0, sizeof(*f));
    f->p00 = 10.0; f->p11 = 10.0;   /* P = eye(2)*10 */
}

static double d01_update(d01_t *f, double q, double r, double z, double t)
{
    if (!f->init) { f->init = 1; f->t_prev = t; f->h = z; f->v = 0.0;
                    return 0.0; }
    double dt = t - f->t_prev;
    if (dt <= 0.0) return f->v;
    f->t_prev = t;
    double xp0 = f->h + f->v * dt;
    double q00 = q * dt * dt * dt * dt / 4.0;
    double q01 = q * dt * dt * dt / 2.0;
    double q11 = q * dt * dt;
    double pp00 = f->p00 + 2.0 * dt * f->p01 + dt * dt * f->p11 + q00;
    double pp01 = f->p01 + dt * f->p11 + q01;
    double pp11 = f->p11 + q11;
    double y = z - xp0;
    double S = pp00 + r;
    double k0 = pp00 / S, k1 = pp01 / S;
    f->h = xp0 + k0 * y;
    f->v = f->v + k1 * y;
    f->p00 = pp00 - k0 * pp00;
    f->p01 = pp01 - k0 * pp01;
    f->p11 = pp11 - k1 * pp01;
    return f->v;
}

/* ------------------------------------------------------------------ */
/* C03 — steady-state-gain CV tracker (tracking.py::_SteadyStateTracker)*/
/* ------------------------------------------------------------------ */
typedef struct {
    double h, v, k0, k1;
    double dt_fit, t_prev;
    int init;
    /* steady-state gain cache keyed by quantized dt (refit storm fix:
     * baro dt ping-pongs 20<->40 ms across the temperature-conversion slot,
     * and each >2% drift re-ran the 200-iteration Riccati refit, measured
     * at 1330 us avg / 2671 us max per update on ESP32-S3).  Each distinct
     * dt bucket refits exactly once. */
    double dtq[4];     /* quantized dt keys, 0 = empty */
    double ck0[4], ck1[4];
    int    nq;
} c03_t;

static void c03_reset(c03_t *f) { memset(f, 0, sizeof(*f)); }

static void c03_refit(c03_t *f, double dt, double q, double r)
{
    double p00 = 10.0, p01 = 0.0, p11 = 10.0;
    for (int it = 0; it < 200; it++) {
        double pp00 = p00 + 2.0*dt*p01 + dt*dt*p11 + q*dt*dt*dt*dt/4.0;
        double pp01 = p01 + dt*p11 + q*dt*dt*dt/2.0;
        double pp11 = p11 + q*dt*dt;
        double S = pp00 + r;
        double k0 = pp00 / S, k1 = pp01 / S;
        p00 = pp00 - k0 * pp00;
        p01 = pp01 - k0 * pp01;
        p11 = pp11 - k1 * pp01;
    }
    double pp00 = p00 + 2.0*dt*p01 + dt*dt*p11 + q*dt*dt*dt*dt/4.0;
    double pp01 = p01 + dt*p11 + q*dt*dt*dt/2.0;
    double S = pp00 + r;
    f->k0 = pp00 / S;
    f->k1 = pp01 / S;
    f->dt_fit = dt;
}

static double c03_update(c03_t *f, double q, double r, double z, double t)
{
    if (!f->init) { f->init = 1; f->t_prev = t; f->h = z; f->v = 0.0;
                    return 0.0; }
    double dt = t - f->t_prev;
    if (dt <= 0.0) return f->v;
    f->t_prev = t;
    if (f->dt_fit <= 0.0 ||
        fabs(dt - f->dt_fit) / f->dt_fit > 0.02) {   /* DT_RECOMP_TOLERANCE */
        /* cache lookup by quantized dt (1 ms buckets) before refitting */
        double qdt = (double)((int)(dt * 1000.0 + 0.5)) / 1000.0;
        int hit = -1;
        for (int i = 0; i < f->nq; i++) {
            if (fabs(qdt - f->dtq[i]) < 0.0015) { hit = i; break; }
        }
        if (hit >= 0) {
            f->k0 = f->ck0[hit]; f->k1 = f->ck1[hit];
            f->dt_fit = qdt;
        } else {
            c03_refit(f, qdt, q, r);   /* refit converges gains for qdt */
            int slot = (f->nq < 4) ? f->nq++ : 3;   /* evict oldest-ish */
            if (slot == 3 && f->nq >= 4) {
                /* shift out slot 0 to keep the 3 most recent */
                for (int i = 0; i < 3; i++) {
                    f->dtq[i] = f->dtq[i+1];
                    f->ck0[i] = f->ck0[i+1];
                    f->ck1[i] = f->ck1[i+1];
                }
            }
            f->dtq[slot] = qdt; f->ck0[slot] = f->k0; f->ck1[slot] = f->k1;
        }
    }
    double xp0 = f->h + f->v * dt;                 /* F at ACTUAL dt */
    double y = z - xp0;
    f->h = xp0 + f->k0 * y;
    f->v = f->v + f->k1 * y;
    return f->v;
}

/* ------------------------------------------------------------------ */
/* S4 — fast/slow gated (stacked.py::S4FastSlowGated, corrected WP-B)  */
/* ------------------------------------------------------------------ */
typedef struct {
    double fh, fv, fdt_fit, falpha, fbeta;   /* fast: C01 alpha-beta */
    d01_t slow;                              /* slow: D01 CV Kalman */
    int fast_hold, hold_valid;
    double below_since;                      /* <0: none */
    double h, v, t_prev;
    int init;
} s4_t;

static void s4_reset(s4_t *f)
{
    memset(f, 0, sizeof(*f));
    f->below_since = -1.0;
    d01_reset(&f->slow);
}

static double s4_update(s4_t *f, double z, double t)
{
    if (!f->init) {
        f->init = 1;
        f->t_prev = t;
        f->fh = z; f->fv = 0.0; f->h = z; f->v = 0.0;
        d01_reset(&f->slow);
        f->slow.init = 1; f->slow.h = z; f->slow.t_prev = t;
        return 0.0;
    }
    double dt = t - f->t_prev;
    if (dt <= 0.0) return f->v;
    f->t_prev = t;

    if (f->fdt_fit <= 0.0 ||
        fabs(dt - f->fdt_fit) / f->fdt_fit > 0.02) {
        f->falpha = 1.0 - exp(-dt / S4_TAU_FAST_S);
        f->fbeta = f->falpha * f->falpha / (2.0 - f->falpha);
        f->fdt_fit = dt;
    }
    /* plausibility SATURATE (never replace) */
    double h_pred = f->fh + f->fv * dt;
    double max_dev = S4_V_PLAUS_MAX * dt + S4_PLAUS_MARGIN;
    double dev = z - h_pred;
    double zc = z;
    if (fabs(dev) > max_dev) zc = h_pred + (dev > 0.0 ? max_dev : -max_dev);

    double yf = zc - h_pred;
    f->fh = h_pred + f->falpha * yf;
    f->fv = f->fv + (f->fbeta / dt) * yf;
    double vf = f->fv;
    double vs = d01_update(&f->slow, S4_Q_SLOW, S4_R_SLOW, zc, t);

    if (!f->fast_hold && fabs(vf) > S4_V_SCALE) f->fast_hold = 1;
    if (f->fast_hold) {
        if (fabs(vf) < S4_EXIT_V) {
            if (!f->hold_valid) { f->below_since = t; f->hold_valid = 1; }
            if (t - f->below_since >= S4_EXIT_HOLD_S) {
                f->fast_hold = 0;
                f->hold_valid = 0;
            }
        } else {
            f->hold_valid = 0;
        }
    }
    double w = fabs(vf) / S4_V_SCALE;
    if (w > 1.0) w = 1.0;
    if (f->fast_hold) {
        if (((vf > 0.0 && vs < 0.0) || (vf < 0.0 && vs > 0.0)) &&
            fabs(vs) < S4_EXIT_V) {
            w = 0.0;
        } else if (w < S4_W_FLOOR) {
            w = S4_W_FLOOR;
        }
    }
    f->h = f->slow.h;
    f->v = (1.0 - w) * vs + w * vf;
    return f->v;
}

/* ------------------------------------------------------------------ */
/* FUS — baro+IMU (fusion.py::BaroImuFusion), Earth-z DOWN             */
/* ------------------------------------------------------------------ */
typedef struct {
    double x0, x1, p00, p01, p11;
    double a_down;
    double bias[3];
    double t_state, t_baro, t_imu;
    double rest_since;      /* <0: none */
    int rest_valid;
    int fault_count, fault;
    unsigned long n_gated, n_reinit;
    int init;
} fus_t;

static void fus_reset(fus_t *f)
{
    memset(f, 0, sizeof(*f));
    f->rest_since = -1.0;
}

static double fus_a_comp(const fus_t *f, const double a[3], const double q[4])
{
    double w = q[0], x = q[1], y = q[2], z = q[3];
    double ab0 = a[0] - f->bias[0], ab1 = a[1] - f->bias[1], ab2 = a[2] - f->bias[2];
    double r20 = 2.0 * (x * z - w * y);
    double r21 = 2.0 * (y * z + w * x);
    double r22 = 1.0 - 2.0 * (x * x + y * y);
    return r20 * ab0 + r21 * ab1 + r22 * ab2 + 9.80665;
}

static void fus_propagate(fus_t *f, double t)
{
    if (!f->init) return;
    double dt = t - f->t_state;
    if (dt <= 0.0) return;
    double a = f->a_down;
    f->x0 += f->x1 * dt + 0.5 * a * dt * dt;
    f->x1 += a * dt;
    f->t_state = t;
}

static void fus_feed_imu(fus_t *f, const double a[3], const double q[4],
                         double t)
{
    if (!f->init) return;
    fus_propagate(f, t);                    /* coast with PREVIOUS accel */
    double a_comp = fus_a_comp(f, a, q);
    if (fabs(f->x1) < FUS_REST_V_MAX && fabs(a_comp) < 1.0) {
        if (!f->rest_valid) { f->rest_since = t; f->rest_valid = 1; }
        else if (t - f->rest_since >= FUS_REST_WIN_S) {
            double dt = (f->t_imu <= 0.0) ? 0.0 : t - f->t_imu;
            if (dt > 0.0) {
                double zb[3];
                accel_vertical_body_frame(q, zb);
                double g = dt / FUS_BIAS_TAU_S;
                if (g > 1.0) g = 1.0;
                for (int i = 0; i < 3; i++) {
                    f->bias[i] += zb[i] * a_comp * g;
                    if (f->bias[i] > FUS_BIAS_ABSMAX) f->bias[i] = FUS_BIAS_ABSMAX;
                    if (f->bias[i] < -FUS_BIAS_ABSMAX) f->bias[i] = -FUS_BIAS_ABSMAX;
                }
                a_comp = fus_a_comp(f, a, q);
            }
        }
    } else {
        f->rest_valid = 0;
    }
    f->a_down = a_comp;
    f->t_imu = t;
}

static double fus_feed_baro(fus_t *f, double z, double t)
{
    if (!f->init) {
        f->init = 1;
        f->x0 = z; f->x1 = 0.0;
        f->p00 = 1.0; f->p01 = 0.0; f->p11 = 1.0;
        f->t_state = t; f->t_baro = t;
        f->a_down = 0.0;
        return 0.0;
    }
    double dt = t - f->t_baro;
    if (dt <= 0.0) return f->x1;
    fus_propagate(f, t);
    double pp00 = f->p00 + 2.0*dt*f->p01 + dt*dt*f->p11 + FUS_Q*dt*dt*dt*dt/4.0;
    double pp01 = f->p01 + dt*f->p11 + FUS_Q*dt*dt*dt/2.0;
    double pp11 = f->p11 + FUS_Q*dt*dt;
    double y = z - f->x0;
    double S = pp00 + FUS_R;
    double sig = sqrt(S);
    if (fabs(y) > 5.0 * sig) {
        f->fault_count++;
        if (f->fault_count >= 8) {           /* loss of track: reacquire */
            f->fault = 1;
            f->fault_count = 0;
            f->n_reinit++;
            f->x0 = z; f->x1 = 0.0;
            f->p00 = 1.0; f->p01 = 0.0; f->p11 = 1.0;
            f->t_state = t; f->t_baro = t;
            return f->x1;
        }
    } else {
        f->fault_count = 0;
        f->fault = 0;
    }
    if (fabs(y) > FUS_GATE_SIGMA * sig) {
        f->n_gated++;
        f->p00 = pp00; f->p01 = pp01; f->p11 = pp11;   /* prediction only */
    } else {
        double k0 = pp00 / S, k1 = pp01 / S;
        f->x0 += k0 * y;
        f->x1 += k1 * y;
        f->p00 = pp00 - k0 * pp00;
        f->p01 = pp01 - k0 * pp01;
        f->p11 = pp11 - k1 * pp01;
    }
    f->t_baro = t;
    return f->x1;
}

/* ------------------------------------------------------------------ */
/* Bank                                                                */
/* ------------------------------------------------------------------ */
typedef struct {
    d01_t d01;
    c03_t c03;
    s4_t  s4;
    fus_t fus;
    vario_est_state_t s5;
    vario_audio_state_t au[N_EST];
    double au_last_tone[N_EST];
    double v[N_EST];
    int init;
} bank_t;

static bank_t s_bank[2];
static double s_quat[4] = {1.0, 0.0, 0.0, 0.0};
static int s_att_init;
static double s_att_t_prev;

/* per-B-window audio-path diagnostics (surface via bank_audio_stats) */
static unsigned long s_au_on, s_au_fault, s_vnan;
static double s_vmax;

static const vario_est_config_t S5_CFG = {
    .q = S5_Q, .r = S5_R, .gate_sigma = S5_GATE_SIGMA,
    .q_gain = S5_Q_GAIN, .v_scale = S5_V_SCALE,
    .v_plaus_max = S5_V_PLAUS_MAX, .plaus_margin_m = S5_PLAUS_MARGIN,
};

static const vario_audio_config_t AU_CFG = {
    .lift_on = AU_LIFT_ON, .lift_off = AU_LIFT_OFF,
    .hold_s = 0.0, .min_on_s = 0.0, .max_on_s = 0.0,
};

static int au_tone_hz(double v)
{
    long hz = (long)(AU_TONE_BASE_HZ + AU_TONE_SLOPE_HZ * v + 0.5);
    if (hz < AU_TONE_MIN_HZ) hz = AU_TONE_MIN_HZ;
    if (hz > AU_TONE_MAX_HZ) hz = AU_TONE_MAX_HZ;
    return (int)hz;
}

static void bank_reset(bank_t *b)
{
    memset(b, 0, sizeof(*b));
    d01_reset(&b->d01);
    c03_reset(&b->c03);
    s4_reset(&b->s4);
    fus_reset(&b->fus);
    vario_est_init(&b->s5, &S5_CFG);
    for (int i = 0; i < N_EST; i++) {
        vario_audio_init(&b->au[i]);
        b->au_last_tone[i] = 0.0;
    }
    b->init = 1;
}

void attitude_feed(const double a[3], const double g[3], double t)
{
    if (!s_att_init) {
        s_att_init = 1;
        quat_from_accel_tilt(a, s_quat);   /* shortest-arc warm start */
        s_att_t_prev = t;
        return;
    }
    double dt = t - s_att_t_prev;
    if (dt <= 0.0) return;
    s_att_t_prev = t;
    if (dt > 0.1) dt = 0.1;              /* gap clamp (attitude.py) */
    madgwick_update(s_quat, a, g, dt, MADGWICK_BETA);
}

void bank_feed_imu(int sid, const double a[3], double t)
{
    fus_feed_imu(&s_bank[sid].fus, a, s_quat, t);
}

static void audio_update(bank_t *b, int sid, int which, double v, double t,
                         int fault)
{
    vario_audio_state_t *au = &b->au[which];
    int eid = sid * N_EST + which;
    int was = au->state;
    vario_audio_update(au, &AU_CFG, (vario_real_t)v, t, fault);
    if (au->state != was && au->state == 1) s_au_on++;
    if (fault) s_au_fault++;
    {
        double av = v;
        if (av != av) { s_vnan++; }             /* NaN detector */
        else { if (av < 0.0) av = -av; if (av > s_vmax) s_vmax = av; }
    }
    if (au->state != was) {
        if (au->state == 1) {
            int tone = au_tone_hz(v);
            b->au_last_tone[which] = (double)tone;
            tx_v((uint32_t)(t * 1e6), eid, 1, tone);           /* ON */
        } else {
            long dur_ms = (long)((t - au->on_since) * 1000.0 + 0.5);
            b->au_last_tone[which] = 0.0;
            tx_v((uint32_t)(t * 1e6), eid, 2, dur_ms);         /* OFF */
        }
    } else if (au->state == 1) {
        int tone = au_tone_hz(v);
        if (fabs((double)tone - b->au_last_tone[which]) >= AU_TONE_STEP_HZ) {
            b->au_last_tone[which] = (double)tone;
            tx_v((uint32_t)(t * 1e6), eid, 3, tone);           /* TONE */
        }
    }
}

void bank_feed_baro(int sid, double alt_m, double t_s)
{
    bank_t *b = &s_bank[sid];
    if (!b->init) {
        bank_reset(b);
    }
    uint32_t c0 = bench_cycles();
    b->v[EST_D01] = d01_update(&b->d01, D01_Q, D01_R, alt_m, t_s);
    uint32_t c1 = bench_cycles();
    b->v[EST_C03] = c03_update(&b->c03, C03_Q, C03_R, alt_m, t_s);
    uint32_t c2 = bench_cycles();
    b->v[EST_S4] = s4_update(&b->s4, alt_m, t_s);
    uint32_t c3 = bench_cycles();
    b->v[EST_S5] = (double)vario_est_update(&b->s5, &S5_CFG,
                                            (vario_real_t)alt_m, t_s);
    uint32_t c4 = bench_cycles();
    b->v[EST_FUS] = fus_feed_baro(&b->fus, alt_m, t_s);
    uint32_t c5 = bench_cycles();

    int eid0 = sid * N_EST;
    bench_cpu(eid0 + 0, c1 - c0);
    bench_cpu(eid0 + 1, c2 - c1);
    bench_cpu(eid0 + 2, c3 - c2);
    bench_cpu(eid0 + 3, c4 - c3);
    bench_cpu(eid0 + 4, c5 - c4);

    audio_update(b, sid, EST_D01, b->v[EST_D01], t_s, 0);
    audio_update(b, sid, EST_C03, b->v[EST_C03], t_s, 0);
    audio_update(b, sid, EST_S4,  b->v[EST_S4],  t_s, 0);
    audio_update(b, sid, EST_S5,  b->v[EST_S5],  t_s, 0);
    audio_update(b, sid, EST_FUS, b->v[EST_FUS], t_s, b->fus.fault);
}

double bank_velocity(int sid, int which)
{
    return s_bank[sid].v[which];
}

void bank_audio_stats(unsigned long *on, unsigned long *fault,
                      double *vmax, unsigned long *nan_n)
{
    *on = s_au_on; *fault = s_au_fault;
    *vmax = s_vmax; *nan_n = s_vnan;
    s_au_on = s_au_fault = s_vnan = 0;
    s_vmax = 0.0;
}
