/* main.c — vario-idf 0.1.0: bring-up, health check, streaming + estimation.
 *
 * Task layout (ESP32-S3, FreeRTOS):
 *   sens_task (core 1, prio 20): 5 ms base tick. Every tick: MPU6050 read
 *     (200 Hz) + attitude + fusion IMU path; async pipelined MS5611 slots:
 *     ~48 Hz P + 10 Hz T (a T cycle displaces one P slot every 20 ticks).
 *     Baro samples are compensated (baro_proc.c), fed to the per-sid
 *     estimator bank, which drives the virtual-audio V frames.
 *   tx_task (core 0, prio 8): drains the TX ring to USB Serial/JTAG.
 *
 * Protocol v1 output: P/T/I/E data frames + V (virtual audio events:
 * ev 1=ON val=tone_hz, 2=OFF val=episode_ms, 3=TONE val=tone_hz) +
 * B (benchmark stats) + keepalive #H/#K/#C meta every 5 s (the USB
 * Serial/JTAG driver exposes no DTR, so periodic meta re-broadcast is the
 * meta-on-attach mechanism).
 */
#include <stdio.h>
#include <string.h>
#include <math.h>

#include "baro_proc.h"
#include "bench.h"
#include "config.h"
#include "driver/i2c_master.h"
#include "driver/usb_serial_jtag.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "estimators.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mpu6050.h"
#include "ms5611.h"
#include "tx.h"

static const char *TAG = "vario";

static i2c_master_bus_handle_t s_bus_a, s_bus_b;
static ms5611_t s_baro_a, s_baro_b;
static mpu6050_t s_mpu;
static uint8_t s_mpu_addr;         /* probed at boot (0x69 or 0x68) */
static baro_proc_t s_bp[2];
static uint32_t s_d2[2];           /* latest temperature ADC per sid */
static int s_t_seen[2];            /* first T frame received per sid */

/* ---- async MS5611 sampling ------------------------------------------------ *
 * One conversion slot per device, non-blocking: a conversion started on tick
 * N is read on tick N+4 (>=20 ms elapsed — GY-63 clones need >10 ms even at
 * OSR2048, bench-verified), and the next conversion is started in the same
 * service pass.  No busy-wait, so the 5 ms tick budget is spent on IMU +
 * estimation + formatting only.  The T cycle (every TEMP_EVERY ticks)
 * displaces one P slot, giving ~48 Hz P + 10 Hz T.
 */
typedef struct {
    int busy;
    int is_temp;
    uint32_t start_tick;   /* conversion started this tick; read 3 ticks later */
} baro_slot_t;
static baro_slot_t s_slot[2];

/* diagnostics (surfaced in the B report) */
static uint32_t s_dbg_p_start, s_dbg_p_emit, s_dbg_t_start, s_dbg_t_emit;
static uint32_t s_dbg_read_defer, s_dbg_adc_bad;

static void baro_service(int64_t now, uint32_t tick)
{
    for (int s = 0; s < 2; s++) {
        ms5611_t *b = s ? &s_baro_b : &s_baro_a;
        baro_slot_t *sl = &s_slot[s];
        if (!sl->busy) continue;
        /* deterministic pipeline: conversion started on tick N is always
         * read on tick N+4 (>=20 ms elapsed vs ~4.6-5.4 ms datasheet
         * conversion).  Shorter waits bench-fail on the GY-63 clones:
         * N+2 (10 ms) gave d1=0 / partial-ADC frames on ~33% of reads on
         * BOTH sensors with zero I2C errors — the clones ACK and clock out
         * zeros while still converting instead of NAKing.  N+3 (15 ms) was
         * 100% clean over 6000 reads; N+4 keeps margin on the 66.7 Hz
         * schedule.  abad counts any implausible residual. */
        if ((int32_t)(tick - sl->start_tick) < 4) { s_dbg_read_defer++; continue; }
        uint32_t adc = 0;
        int64_t t_i2c0 = esp_timer_get_time();
        esp_err_t rd_err = ms5611_read_adc(b, &adc);
        bench_i2c_call(0, (uint32_t)(esp_timer_get_time() - t_i2c0));
        if (rd_err == ESP_OK && !sl->is_temp &&
            (adc < 1000000u || adc > 16000000u)) {
            s_dbg_adc_bad++;
        }
        if (rd_err == ESP_OK) {
            uint32_t t_s = (uint32_t)now;
            if (sl->is_temp) {
                s_d2[s] = adc;
                s_t_seen[s] = 1;
                tx_t(t_s, s, adc);
                s_dbg_t_emit++;
            } else {
                double alt = baro_proc_altitude(&s_bp[s], adc, s_d2[s]);
                if (s == 0) tx_p(t_s, 0, adc);
                else         tx_p(t_s, 1, adc);
                s_dbg_p_emit++;
                /* NaN guard: skip bad compensation.  Also hold estimator
                 * feeds until the first real T frame: the seeded d2
                 * (dt=0) compensates ~10 hPa off, and the step when the
                 * first T lands otherwise whips every estimator (~13 m/s
                 * v-spike, observed as von=20 in the first B window). */
                if (alt == alt && s_t_seen[s])
                    bank_feed_baro(s, alt, (double)now / 1e6);
            }
        } else {
            bench_i2c_err(s);
            tx_e((uint32_t)now, 1);
        }
        sl->busy = 0;
    }

    int want_temp = (tick % TEMP_EVERY) == 0;
    int want_p    = (tick % BARO_EVERY) == 0;
    if (!want_temp && !want_p) return;
    for (int s = 0; s < 2; s++) {
        if (s_slot[s].busy) continue;
        ms5611_t *b = s ? &s_baro_b : &s_baro_a;
        uint8_t cmd = want_temp ? MS5611_OSR_CMD_T : MS5611_OSR_CMD_P;
        int64_t t_i2c0 = esp_timer_get_time();
        esp_err_t st_err = ms5611_start_conv(b, cmd);
        bench_i2c_call(1, (uint32_t)(esp_timer_get_time() - t_i2c0));
        if (st_err == ESP_OK) {
            s_slot[s].busy = 1;
            s_slot[s].is_temp = want_temp;
            s_slot[s].start_tick = tick;
            if (want_temp) s_dbg_t_start++; else s_dbg_p_start++;
        } else {
            bench_i2c_err(s);
        }
    }
}

static void sens_task(void *arg)
{
    (void)arg;
    esp_task_wdt_add(NULL);

    TickType_t last_wake = xTaskGetTickCount();
    uint32_t tick = 0;
    int64_t t_prev_start = esp_timer_get_time();

    for (;;) {
        int64_t t_dly0 = esp_timer_get_time();
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(TICK_MS));
        bench_delay((uint32_t)(esp_timer_get_time() - t_dly0));
        int64_t t_start = esp_timer_get_time();
        bench_tick_duration((uint32_t)(t_start - t_prev_start) < 100000
            ? (uint32_t)(t_start - t_prev_start) : 0);
        t_prev_start = t_start;
        tick++;

        /* ---- IMU every tick (200 Hz); stream I frames at 100 Hz ----
         * (fusion paths still consume the full 200 Hz internally; the
         * 100 Hz stream keeps the USB link under its measured ~20 KB/s
         * drain ceiling — at 200 Hz text I-frames the ring saturates) */
        int64_t t_mpu0 = esp_timer_get_time();
        uint32_t c_mpu0 = bench_cycles();
        bench_section(2, (uint32_t)(t_mpu0 - t_start));
        int16_t raw[8];
        int64_t t_i2c0 = esp_timer_get_time();
        esp_err_t mpu_err = mpu6050_read(&s_mpu, raw);
        bench_i2c_call(2, (uint32_t)(esp_timer_get_time() - t_i2c0));
        if (mpu_err == ESP_OK) {
            double t_s = (double)esp_timer_get_time() / 1e6;
            if ((tick % 2) == 0) {
                tx_i((uint32_t)(t_s * 1e6),
                     raw[0], raw[1], raw[2], raw[4], raw[5], raw[6]);
            }
            double a_m_s2[3], g_rad_s[3];
            for (int i = 0; i < 3; i++) {
                a_m_s2[i] = (double)raw[i] * 9.80665 / MPU_A_LSB_PER_G;
                g_rad_s[i] = (double)raw[4 + i] / MPU_G_LSB_PER_DPS
                             * (M_PI / 180.0);
            }
            attitude_feed(a_m_s2, g_rad_s, t_s);
            bank_feed_imu(0, a_m_s2, t_s);
            bank_feed_imu(1, a_m_s2, t_s);
        } else {
            bench_i2c_err(2);
            tx_e((uint32_t)esp_timer_get_time(), 1);
        }

        /* ---- baro: async pipelined conversion slots (no busy-wait) ---- */
        bench_section(0, (uint32_t)(esp_timer_get_time() - t_mpu0));
        bench_section_cyc(0, bench_cycles() - c_mpu0);
        int64_t t_bar0 = esp_timer_get_time();
        uint32_t c_bar0 = bench_cycles();
        baro_service(esp_timer_get_time(), tick);
        bench_section(1, (uint32_t)(esp_timer_get_time() - t_bar0));
        bench_section_cyc(1, bench_cycles() - c_bar0);
        int64_t t_tick_end = esp_timer_get_time();
        if (t_tick_end - t_start > 10500) bench_baro_miss();

        if ((tick % BENCH_REPORT_TICKS) == 0) {
            bench_dbg_baro(s_dbg_p_start, s_dbg_p_emit,
                           s_dbg_t_start, s_dbg_t_emit, s_dbg_read_defer,
                           s_dbg_adc_bad);
            s_dbg_p_start = s_dbg_p_emit = s_dbg_t_start = s_dbg_t_emit
                          = s_dbg_read_defer = s_dbg_adc_bad = 0;
            {
                unsigned long au_on, au_ft, au_nan;
                double au_vmax;
                bank_audio_stats(&au_on, &au_ft, &au_vmax, &au_nan);
                bench_dbg_audio(au_on, au_ft, au_vmax, au_nan);
            }
            tx_meta_keepalive();
            bench_report();
        }
        bench_section(3, (uint32_t)(esp_timer_get_time() - t_tick_end));
        int64_t t_wd0 = esp_timer_get_time();
        esp_task_wdt_reset();
        bench_section(4, (uint32_t)(esp_timer_get_time() - t_wd0));
    }
}

static void emit_boot_meta(void)
{
    char line[320];
    tx_meta("#H,vario-idf,0.1.0");
    snprintf(line, sizeof(line), "#K,0,%u,%u,%u,%u,%u,%u",
             s_baro_a.prom[1], s_baro_a.prom[2], s_baro_a.prom[3],
             s_baro_a.prom[4], s_baro_a.prom[5], s_baro_a.prom[6]);
    tx_meta(line);
    snprintf(line, sizeof(line), "#K,1,%u,%u,%u,%u,%u,%u",
             s_baro_b.prom[1], s_baro_b.prom[2], s_baro_b.prom[3],
             s_baro_b.prom[4], s_baro_b.prom[5], s_baro_b.prom[6]);
    tx_meta(line);
    snprintf(line, sizeof(line),
             "#C,dev=a0,type=ms5611,addr=0x%02x,prom0=0x%04x,prom7=0x%04x,"
             "crc=%x/%x,status=%s",
             s_baro_a.addr, s_baro_a.prom[0], s_baro_a.prom[7],
             ms5611_crc_computed(&s_baro_a), ms5611_crc_stored(&s_baro_a),
             s_baro_a.ok ? "ok" : "fail");
    tx_meta(line);
    snprintf(line, sizeof(line),
             "#C,dev=b1,type=ms5611,addr=0x%02x,prom0=0x%04x,prom7=0x%04x,"
             "crc=%x/%x,status=%s",
             s_baro_b.addr, s_baro_b.prom[0], s_baro_b.prom[7],
             ms5611_crc_computed(&s_baro_b), ms5611_crc_stored(&s_baro_b),
             s_baro_b.ok ? "ok" : "fail");
    tx_meta(line);
    snprintf(line, sizeof(line),
             "#C,dev=a1,type=mpu6050,addr=0x%02x,whoami=0x68,status=%s",
             s_mpu_addr, s_mpu.ok ? "ok" : "missing");
    tx_meta(line);
    snprintf(line, sizeof(line),
             "#C,health=%s,missing=%d", 
             (s_baro_a.ok && s_baro_b.ok && s_mpu.ok) ? "ok" : "fail",
             (s_baro_a.ok ? 0 : 1) + (s_baro_b.ok ? 0 : 1) +
             (s_mpu.ok ? 0 : 1));
    tx_meta(line);
    snprintf(line, sizeof(line),
             "#C,osr=2048,p_hz=48,t_hz=10,i_hz=200,imu=on,est=on,"
             "a_lsb_per_g=%d,g_lsb_per_dps=65.5,a_fs=8g,dlpf=44hz,"
             "tick_ms=%d,est_map=e0..e4=D01,C03,S4,S5,FUS@sid0;"
             "e5..e9=sid1,tone=%d+%dv,au=0.20/0.05",
             MPU_A_LSB_PER_G, TICK_MS, AU_TONE_BASE_HZ, AU_TONE_SLOPE_HZ);
    tx_meta(line);
}

static void health_fail_loop(void)
{
    for (;;) {
        tx_meta_keepalive();   /* host must see WHICH device failed */
        tx_e((uint32_t)esp_timer_get_time(), 1);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(100));   /* let USB enumerate */

    tx_init();
    tx_start_task();

    /* ---- I2C buses ---- */
    i2c_master_bus_config_t cfg_a = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = BUSA_SDA_GPIO,
        .scl_io_num = BUSA_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_config_t cfg_b = {
        .i2c_port = I2C_NUM_1,
        .sda_io_num = BUSB_SDA_GPIO,
        .scl_io_num = BUSB_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&cfg_a, &s_bus_a));
    ESP_ERROR_CHECK(i2c_new_master_bus(&cfg_b, &s_bus_b));

    /* ---- boot bus scan (diagnostic): which addresses ACK? ---- */
    {
        char line[160];
        int n;
        n = snprintf(line, sizeof(line), "#C,scan_A:");
        for (uint8_t a = 0x08; a < 0x78 && n < (int)sizeof(line) - 6; a++) {
            if (i2c_master_probe(s_bus_a, a, pdMS_TO_TICKS(50)) == ESP_OK)
                n += snprintf(line + n, sizeof(line) - n, "0x%02x,", a);
        }
        tx_meta(line);
        n = snprintf(line, sizeof(line), "#C,scan_B:");
        for (uint8_t a = 0x08; a < 0x78 && n < (int)sizeof(line) - 6; a++) {
            if (i2c_master_probe(s_bus_b, a, pdMS_TO_TICKS(50)) == ESP_OK)
                n += snprintf(line + n, sizeof(line) - n, "0x%02x,", a);
        }
        tx_meta(line);
    }

    /* ---- devices (failures leave the handle un-ok; meta reports it) ----
     * addresses are auto-probed: 0x77 then 0x76 for baros, 0x69 then 0x68
     * for the MPU (wiring/AD0/CSB state has changed across bench reworks). */
    uint8_t addr_baro_a = 0;
    for (uint8_t a = 0x77; a >= 0x76; a--)   /* 0x77, then 0x76 */
        if (i2c_master_probe(s_bus_a, a, pdMS_TO_TICKS(50)) == ESP_OK) {
            addr_baro_a = a; break;
        }
    uint8_t addr_baro_b = 0;
    for (uint8_t a = 0x77; a >= 0x76; a--)
        if (i2c_master_probe(s_bus_b, a, pdMS_TO_TICKS(50)) == ESP_OK) {
            addr_baro_b = a; break;
        }
    uint8_t addr_mpu = 0;
    for (uint8_t a = 0x69; a >= 0x68; a--)   /* 0x69, then 0x68 */
        if (i2c_master_probe(s_bus_a, a, pdMS_TO_TICKS(50)) == ESP_OK) {
            addr_mpu = a; break;
        }
    esp_err_t ea = addr_baro_a
        ? ms5611_init(&s_baro_a, s_bus_a, addr_baro_a) : ESP_ERR_NOT_FOUND;
    esp_err_t eb = addr_baro_b
        ? ms5611_init(&s_baro_b, s_bus_b, addr_baro_b) : ESP_ERR_NOT_FOUND;
    esp_err_t em = addr_mpu
        ? mpu6050_init(&s_mpu, s_bus_a, addr_mpu) : ESP_ERR_NOT_FOUND;
    s_mpu_addr = addr_mpu;
    if (ea != ESP_OK) ESP_LOGW(TAG, "baro A init failed: %s", esp_err_to_name(ea));
    if (eb != ESP_OK) ESP_LOGW(TAG, "baro B init failed: %s", esp_err_to_name(eb));
    if (em != ESP_OK) ESP_LOGW(TAG, "mpu init failed: %s", esp_err_to_name(em));

    emit_boot_meta();

    if (!(s_baro_a.ok && s_baro_b.ok && s_mpu.ok)) {
        tx_meta("#C,status=health_fail_halt");
        health_fail_loop();   /* does not return */
    }

    baro_proc_init(&s_bp[0], s_baro_a.prom);
    baro_proc_init(&s_bp[1], s_baro_b.prom);
    /* seed d2 to the nominal temperature ADC (dt=0 -> 20 degC) so the
     * first pressure samples before the first T frame compensate sanely;
     * a 0 here explodes the compensation to negative Pa -> NaN altitude
     * -> poisons the p0 mean (found via vnan B-line diagnostic). */
    s_d2[0] = (uint32_t)s_baro_a.prom[5] * 256u;
    s_d2[1] = (uint32_t)s_baro_b.prom[5] * 256u;

    /* clock calibration: spin 240,000 cycles (~1 ms @240 MHz nominal),
     * compare CPU cycles against esp_timer and the FreeRTOS tick */
    {
        uint32_t c0 = bench_cycles();
        int64_t e0 = esp_timer_get_time();
        TickType_t f0 = xTaskGetTickCount();
        volatile uint32_t spin = 0;
        while (bench_cycles() - c0 < 240000) { spin++; }
        int64_t e1 = esp_timer_get_time();
        TickType_t f1 = xTaskGetTickCount();
        char cline[160];
        snprintf(cline, sizeof(cline),
                 "#C,cal: cycles=240000 etim_us=%lld ftick_delta=%lu spin=%lu",
                 (long long)(e1 - e0), (unsigned long)(f1 - f0), spin);
        tx_meta(cline);
    }

    /* Host handshake: the stream starts only after the host sends 'G'
     * (capture.py does this right after opening the port).  Without it the
     * ring would absorb the boot burst and overflow before the host's first
     * read.  Standalone runs start after a 10 s grace period. */
    tx_meta("#C,status=waiting_host_g");
    {
        uint8_t ch;
        int64_t t_wait0 = esp_timer_get_time();
        while (esp_timer_get_time() - t_wait0 < 10000000) {
            int n = usb_serial_jtag_read_bytes(&ch, 1, 0);
            if (n == 1 && ch == 'G') break;
            vTaskDelay(pdMS_TO_TICKS(5));
        }
    }
    tx_meta("#C,status=stream_go");

    xTaskCreatePinnedToCore(sens_task, "sens", 8192, NULL, 20, NULL, 1);
}
