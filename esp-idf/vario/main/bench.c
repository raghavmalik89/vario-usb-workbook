/* bench.c */
#include "bench.h"

#include <stdio.h>
#include <string.h>

#include "config.h"
#include "esp_private/esp_clk.h"
#include "esp_cpu.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "tx.h"

uint32_t bench_cycles(void)
{
    return esp_cpu_get_cycle_count();
}

static uint64_t s_cpu_sum[2 * N_EST];
static uint32_t s_cpu_max[2 * N_EST];
static uint32_t s_cpu_cnt[2 * N_EST];
static uint64_t s_tick_sum;
static uint32_t s_tick_max, s_tick_cnt;
static uint32_t s_baro_miss;
static uint32_t s_i2c_err[3];
static uint32_t s_dbg[6];   /* p_start, p_emit, t_start, t_emit, read_defer, adc_bad */
static uint32_t s_au[4];    /* on, fault, vmax_cm_s, nan_n (audio-path diag) */
static uint32_t s_sec_sum[5], s_sec_max[5], s_sec_cnt;
static uint64_t s_sec_cyc_sum[2]; static uint32_t s_sec_cyc_max[2];

void bench_section_cyc(int which, uint32_t cycles)
{
    if (which < 0 || which > 1) return;
    s_sec_cyc_sum[which] += cycles;
    if (cycles > s_sec_cyc_max[which]) s_sec_cyc_max[which] = cycles;
}
static uint32_t s_delay_sum, s_delay_max, s_delay_cnt, s_delay_big;
static uint32_t s_i2c_call_max[3], s_i2c_call_slow[3], s_i2c_call_cnt[3];

void bench_i2c_call(int ch, uint32_t us)
{
    if (ch < 0 || ch > 2) return;
    s_i2c_call_cnt[ch]++;
    if (us > s_i2c_call_max[ch]) s_i2c_call_max[ch] = us;
    if (us > 5000) s_i2c_call_slow[ch]++;
}

void bench_section(int which, uint32_t us)
{
    if (which < 0 || which > 4) return;
    s_sec_sum[which] += us;
    if (us > s_sec_max[which]) s_sec_max[which] = us;
    s_sec_cnt++;
}

void bench_delay(uint32_t us)
{
    s_delay_sum += us;
    if (us > s_delay_max) s_delay_max = us;
    s_delay_cnt++;
    if (us > 8000) s_delay_big++;
}

void bench_dbg_baro(uint32_t p_start, uint32_t p_emit,
                    uint32_t t_start, uint32_t t_emit, uint32_t defer,
                    uint32_t adc_bad)
{
    s_dbg[0] = p_start; s_dbg[1] = p_emit;
    s_dbg[2] = t_start; s_dbg[3] = t_emit;
    s_dbg[4] = defer;   s_dbg[5] = adc_bad;
}

void bench_dbg_audio(unsigned long on, unsigned long fault,
                     double vmax_m_s, unsigned long nan_n)
{
    s_au[0] = (uint32_t)on;  s_au[1] = (uint32_t)fault;
    s_au[2] = (uint32_t)(vmax_m_s * 100.0 + 0.5);
    s_au[3] = (uint32_t)nan_n;
}

void bench_cpu(int eid, uint32_t cycles)
{
    if (eid < 0 || eid >= 2 * N_EST) return;
    s_cpu_sum[eid] += cycles;
    if (cycles > s_cpu_max[eid]) s_cpu_max[eid] = cycles;
    s_cpu_cnt[eid]++;
}

void bench_tick_duration(uint32_t tick_us)
{
    s_tick_sum += tick_us;
    if (tick_us > s_tick_max) s_tick_max = tick_us;
    s_tick_cnt++;
}

void bench_baro_miss(void) { s_baro_miss++; }

void bench_i2c_err(int which)
{
    if (which >= 0 && which < 3) s_i2c_err[which]++;
}

void bench_report(void)
{
    uint32_t now = (uint32_t)esp_timer_get_time();
    uint32_t cpu_mhz = esp_clk_cpu_freq() / 1000000;  /* 160 or 240 */

    char buf[768];   /* 512 truncated the c= tail (estimator CPU pairs) when
                        other fields grew (e.g. vmax=10904); 10 pairs need
                        ~100 chars after a ~450-char prefix */
    int n = snprintf(buf, sizeof(buf),
        "tick_avg_us=%lu;tick_max_us=%lu;baro_miss=%lu;"
        "i2c_a=%lu;i2c_b=%lu;i2c_mpu=%lu;tx_ovf=%lu;ring_hw=%lu;"
        "ps=%lu;pe=%lu;ts=%lu;te=%lu;df=%lu;abad=%lu;"
        "mpu_avg=%lu;mpu_max=%lu;bar_avg=%lu;bar_max=%lu;"
        "dly_avg=%lu;dly_max=%lu;dly_big=%lu;tkr=%lu;"
        "hd_avg=%lu;hd_max=%lu;tl_avg=%lu;tl_max=%lu;"
        "i0max=%lu;i0slow=%lu;i1max=%lu;i1slow=%lu;i2max=%lu;i2slow=%lu;wd_max=%lu;ftick=%lu;etim=%lu;ntask=%lu;mcyc=%lu;bcyc=%lu;von=%lu;vfault=%lu;vmax=%lu;vnan=%lu;c=",
        (unsigned long)(s_tick_cnt ? s_tick_sum / s_tick_cnt : 0),
        (unsigned long)s_tick_max,
        (unsigned long)s_baro_miss,
        (unsigned long)s_i2c_err[0], (unsigned long)s_i2c_err[1],
        (unsigned long)s_i2c_err[2],
        (unsigned long)tx_overflow_count(),
        (unsigned long)tx_ring_highwater(),
        (unsigned long)s_dbg[0], (unsigned long)s_dbg[1],
        (unsigned long)s_dbg[2], (unsigned long)s_dbg[3],
        (unsigned long)s_dbg[4], (unsigned long)s_dbg[5],
        (unsigned long)(s_sec_cnt ? s_sec_sum[0] / s_sec_cnt : 0),
        (unsigned long)s_sec_max[0],
        (unsigned long)(s_sec_cnt ? s_sec_sum[1] / s_sec_cnt : 0),
        (unsigned long)s_sec_max[1],
        (unsigned long)(s_delay_cnt ? s_delay_sum / s_delay_cnt : 0),
        (unsigned long)s_delay_max,
        (unsigned long)s_delay_big,
        (unsigned long)pdMS_TO_TICKS(1000),
        (unsigned long)(s_sec_cnt ? s_sec_sum[2] / s_sec_cnt : 0),
        (unsigned long)s_sec_max[2],
        (unsigned long)(s_sec_cnt ? s_sec_sum[3] / s_sec_cnt : 0),
        (unsigned long)s_sec_max[3],
        (unsigned long)s_i2c_call_max[0], (unsigned long)s_i2c_call_slow[0],
        (unsigned long)s_i2c_call_max[1], (unsigned long)s_i2c_call_slow[1],
        (unsigned long)s_i2c_call_max[2], (unsigned long)s_i2c_call_slow[2],
        (unsigned long)s_sec_max[4],
        (unsigned long)xTaskGetTickCount(), (unsigned long)esp_timer_get_time(),
        (unsigned long)uxTaskGetNumberOfTasks(),
        (unsigned long)(s_sec_cyc_sum[0] / 1000), (unsigned long)(s_sec_cyc_sum[1] / 1000),
        (unsigned long)s_au[0], (unsigned long)s_au[1],
        (unsigned long)s_au[2], (unsigned long)s_au[3]);
    if (n < 0) return;
    size_t off = (size_t)n;
    for (int e = 0; e < 2 * N_EST && off < sizeof(buf) - 24; e++) {
        unsigned long avg_us = s_cpu_cnt[e]
            ? (unsigned long)(s_cpu_sum[e] / cpu_mhz / s_cpu_cnt[e]) : 0;
        unsigned long max_us = s_cpu_max[e] / cpu_mhz;
        n = snprintf(buf + off, sizeof(buf) - off, "%s%lu/%lu",
                     e ? ";" : "", avg_us, max_us);
        if (n < 0) break;
        off += (size_t)n;
    }
    tx_b(buf);

    memset(s_cpu_sum, 0, sizeof(s_cpu_sum));
    memset(s_cpu_max, 0, sizeof(s_cpu_max));
    memset(s_cpu_cnt, 0, sizeof(s_cpu_cnt));
    memset(s_sec_sum, 0, sizeof(s_sec_sum));
    memset(s_sec_cyc_sum, 0, sizeof(s_sec_cyc_sum));
    memset(s_sec_cyc_max, 0, sizeof(s_sec_cyc_max));
    memset(s_sec_max, 0, sizeof(s_sec_max));
    s_sec_cnt = 0;
    s_delay_sum = s_delay_max = s_delay_cnt = s_delay_big = 0;
    memset(s_i2c_call_max, 0, sizeof(s_i2c_call_max));
    memset(s_i2c_call_slow, 0, sizeof(s_i2c_call_slow));
    memset(s_i2c_call_cnt, 0, sizeof(s_i2c_call_cnt));
    s_tick_sum = 0; s_tick_max = 0; s_tick_cnt = 0;
    s_baro_miss = 0;
    memset(s_i2c_err, 0, sizeof(s_i2c_err));
    (void)now;
}
