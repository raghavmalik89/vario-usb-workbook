/* runner.c — host test-vector runner for the portable vario core.
 *
 * usage: runner <vector.csv> <out.csv>
 *   vector.csv header: t_s,z_m          (input stream)
 *   out.csv   header: t_s,v,state,fault (reference-comparable outputs)
 *
 * The runner wires estimator -> generic fault detector -> audio state
 * machine exactly as the Phase-4 recommended safety configuration, and
 * measures per-update execution time (host instrumentation demonstrating
 * the per-update timing hook).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "vario_core.h"

static double now_s(void)
{
    clock_t c = clock();
    return (double)c / (double)CLOCKS_PER_SEC;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: runner <vector.csv> <out.csv>\n");
        return 2;
    }
    FILE *in = fopen(argv[1], "r");
    if (!in) { fprintf(stderr, "cannot open %s\n", argv[1]); return 1; }
    FILE *out = fopen(argv[2], "w");
    if (!out) { fprintf(stderr, "cannot open %s\n", argv[2]); return 1; }

    /* Phase-4 frozen S5_LightGateKF config (config/phase4.json) */
    vario_est_config_t ecfg = {
        (vario_real_t)0.3,    /* q            */
        (vario_real_t)0.035,  /* r            */
        (vario_real_t)3.5,    /* gate_sigma   */
        (vario_real_t)2.0,    /* q_gain       */
        (vario_real_t)1.0,    /* v_scale      */
        (vario_real_t)8.0,    /* v_plaus_max  */
        (vario_real_t)0.3     /* plaus_margin */
    };
    vario_audio_config_t acfg = {
        (vario_real_t)0.20,   /* lift_on  */
        (vario_real_t)0.05,   /* lift_off */
        (vario_real_t)0.0,    /* hold_s   */
        (vario_real_t)0.0,    /* min_on_s */
        (vario_real_t)10.0    /* max_on_s (Phase-4 safety baseline) */
    };
    vario_est_state_t est;
    vario_audio_state_t aud;
    vario_fault_t flt;
    vario_est_init(&est, &ecfg);
    vario_audio_init(&aud);
    vario_fault_init(&flt, (vario_real_t)8.0, (vario_real_t)0.3, 5, 5);

    fprintf(out, "t_s,v,state,fault\n");
    char line[256];
    double t, z, t_prev = 0.0, h_prev = 0.0, v_prev = 0.0;
    int first = 1;
    double t_exec_total = 0.0;
    unsigned long n_updates = 0;
    while (fgets(line, sizeof(line), in)) {
        if (line[0] == 't' || line[0] == '\n' || line[0] == '\0')
            continue;                          /* header / blank */
        if (sscanf(line, "%lf,%lf", &t, &z) != 2)
            continue;
        double t0 = now_s();
        vario_real_t v = vario_est_update(&est, &ecfg, (vario_real_t)z, t);
        t_exec_total += now_s() - t0;
        n_updates++;
        vario_real_t h_pred = (vario_real_t)z;
        vario_real_t dt = (vario_real_t)0.02;
        if (!first) {
            dt = (vario_real_t)(t - t_prev);
            h_pred = (vario_real_t)(h_prev + v_prev * dt);
        }
        int fault = vario_fault_update(&flt, (vario_real_t)z, h_pred, dt);
        int state = vario_audio_update(&aud, &acfg, v, t, fault);
        fprintf(out, "%.9g,%.9g,%d,%d\n", t, (double)v, state, fault);
        t_prev = t;
        h_prev = (double)est.h;
        v_prev = (double)v;
        first = 0;
    }
    fprintf(stderr,
            "runner: %lu updates, mean exec %.3f us/update, "
            "gated=%lu rejected=%lu on=%lu off=%lu fault_veto=%lu max_on=%lu\n",
            n_updates, n_updates ? t_exec_total / n_updates * 1e6 : 0.0,
            est.n_gated, est.n_rejected, aud.n_on, aud.n_off,
            aud.n_fault_veto, aud.n_max_on);
    fclose(in);
    fclose(out);
    return 0;
}
