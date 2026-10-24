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
#include "bmp581.h"
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
static ms5611_t s_baro_a, s_baro_b;   /* optional legacy baros (0/1 present) */
static bmp581_t s_bmp;                /* BMP581 on bus B (2026-10-24 rig)  */
static mpu6050_t s_mpu;
static uint8_t s_mpu_addr;         /* probed at boot (0x69 or 0x68) */
static baro_proc_t s_bp[2];
static uint32_t s_d2[2];           /* latest temperature ADC per sid */
static int s_t_seen[2];            /* first T frame received per sid */

/* per-sid device routing.  Device assignment at boot (2026-10-24 rig):
 *   sid0 = BMP581 (bus B) when present — the sensor under test;
 *   next sid(s) = any MS5611 found (bus A first, then bus B) so the old
 *   dual-clone comparison keeps working if they are reattached.
 * MS5611-only rigs fall back to sequential assignment as before. */
typedef enum { BARO_NONE = 0, BARO_MS5611, BARO_BMP581 } baro_type_t;
static baro_type_t s_baro_type[2];
static ms5611_t *s_ms_hdl[2];       /* sid -> MS5611 handle (NULL for BMP) */
static int s_n_baros = 0;
static int s_bmp_t_div = 0;        /* BMP581 T-frame decimation counter */

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

static void ms5611_service(int64_t now, uint32_t tick)
{
    for (int s = 0; s < 2; s++) {
        if (s_baro_type[s] != BARO_MS5611) continue;
        ms5611_t *b = s_ms_hdl[s];
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
                tx_p(t_s, s, adc);
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
        if (s_baro_type[s] != BARO_MS5611) continue;
        if (s_slot[s].busy) continue;
        ms5611_t *b = s_ms_hdl[s];
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

/* BMP581: NORMAL mode free-runs at ODR.  IMPORTANT: on this part the drdy
 * flag is NOT cleared by a data-register read — a STATUS poll on every 5 ms
 * tick keeps re-asserting (bring-up capture showed 200 emitted reads/s
 * against only ~40 unique register values/s, bit-identical repeats).  So
 * we do NOT poll drdy; we sample on a fixed 25 ms cadence (40 Hz), matching
 * the programmed ODR.  Every pressure sample carries its own fresh
 * temperature (on-chip compensated) — no d2 seeding, no DEF-010 boot step.
 * T frames are decimated to 10 Hz for the stream; the MCU altitude path
 * uses the sample's own temperature regardless. */
static void bmp581_service(int64_t now, uint32_t tick)
{
    int s = (s_baro_type[0] == BARO_BMP581) ? 0 : 1;
    const uint32_t ticks_per_sample = (uint32_t)(1000 / TICK_MS) / BMP581_P_HZ;
    if (ticks_per_sample && (tick % ticks_per_sample)) return;

    uint32_t raw_t = 0, raw_p = 0;
    int64_t t_i2c0 = esp_timer_get_time();
    esp_err_t err = bmp581_read_raw(&s_bmp, &raw_t, &raw_p);
    bench_i2c_call(0, (uint32_t)(esp_timer_get_time() - t_i2c0));
    if (err != ESP_OK) { bench_i2c_err(s); tx_e((uint32_t)now, 1); return; }

    uint32_t t_s = (uint32_t)now;
    tx_p(t_s, s, raw_p);
    s_dbg_p_start++;
    s_dbg_p_emit++;
    if (++s_bmp_t_div >= 4) {
        s_bmp_t_div = 0;
        tx_t(t_s, s, raw_t);
        s_dbg_t_start++;
        s_dbg_t_emit++;
    }
    double alt = baro_proc_altitude_bmp581(raw_p);
    if (alt == alt) {
        s_d2[s] = raw_t;      /* informational; not used for compensation */
        s_t_seen[s] = 1;
        bank_feed_baro(s, alt, (double)now / 1e6);
    }
}

static void baro_service(int64_t now, uint32_t tick)
{
    ms5611_service(now, tick);
    if (s_bmp.ok) bmp581_service(now, tick);
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
    tx_meta("#H,vario-idf,0.2.0");
    for (int s = 0; s < 2; s++) {
        if (s_baro_type[s] == BARO_BMP581) {
            /* BMP581: no PROM sidecar — on-chip compensated (raw Pa*64);
             * type tag in #C is what the offline pipeline keys on. */
            uint8_t osr_rb = 0, odr_rb = 0;
            bmp581_read_config(&s_bmp, &osr_rb, &odr_rb);
            snprintf(line, sizeof(line),
                     "#C,dev=s%d,type=bmp581,addr=0x%02x,chipid=0x%02x,"
                     "rev=0x%02x,osr_p=%d,osr_t=%d,odr=%dhz,iir=bypass,"
                     "osr_cfg=0x%02x,odr_cfg=0x%02x,"
                     "scale=pa_x64,status=%s",
                     s, s_bmp.addr, s_bmp.chip_id, s_bmp.rev_id,
                     BMP581_OSR_P, BMP581_OSR_T, BMP581_P_HZ,
                     osr_rb, odr_rb,
                     s_bmp.ok ? "ok" : "fail");
            tx_meta(line);
        } else if (s_baro_type[s] == BARO_MS5611) {
            ms5611_t *b = s_ms_hdl[s];
            snprintf(line, sizeof(line), "#K,%d,%u,%u,%u,%u,%u,%u", s,
                     b->prom[1], b->prom[2], b->prom[3],
                     b->prom[4], b->prom[5], b->prom[6]);
            tx_meta(line);
            snprintf(line, sizeof(line),
                     "#C,dev=s%d,type=ms5611,addr=0x%02x,prom0=0x%04x,"
                     "prom7=0x%04x,crc=%x/%x,status=%s",
                     s, b->addr, b->prom[0], b->prom[7],
                     ms5611_crc_computed(b), ms5611_crc_stored(b),
                     b->ok ? "ok" : "fail");
            tx_meta(line);
        }
    }
    snprintf(line, sizeof(line),
             "#C,dev=imu,type=mpu6050,addr=0x%02x,whoami=0x68,status=%s",
             s_mpu_addr, s_mpu.ok ? "ok" : "missing");
    tx_meta(line);
    snprintf(line, sizeof(line),
             "#C,health=%s,baros=%d",
             (s_n_baros >= 1 && s_mpu.ok) ? "ok" : "fail", s_n_baros);
    tx_meta(line);
    snprintf(line, sizeof(line),
             "#C,rig=bmp581@B%s%s,i_hz=200,imu=on,est=on,"
             "a_lsb_per_g=%d,g_lsb_per_dps=65.5,a_fs=8g,dlpf=44hz,"
             "tick_ms=%d,est_map=e0..e4=D01,C03,S4,S5,FUS@sid0%s,"
             "tone=%d+%dv,au=0.20/0.05",
             s_baro_type[1] == BARO_MS5611 ? "+ms5611" : "",
             s_mpu.ok ? "" : "+imu_missing",
             MPU_A_LSB_PER_G, TICK_MS,
             s_baro_type[1] != BARO_NONE ? ";e5..e9=sid1" : "",
             AU_TONE_BASE_HZ, AU_TONE_SLOPE_HZ);
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
     * 2026-10-24 rig: BMP581 on bus B (0x47 then 0x46), MPU6050 on bus A
     * (0x69 then 0x68).  Legacy MS5611s are optional: probed on bus A then
     * bus B (0x77 then 0x76).  BMP581 always takes sid0 (sensor under
     * test); any MS5611 fills the next sid(s).  0x7E on a bus scan is the
     * BMP581's own CMD register address ACKing probes — not a device. */
    uint8_t addr_ms_a = 0;
    for (uint8_t a = 0x77; a >= 0x76; a--)
        if (i2c_master_probe(s_bus_a, a, pdMS_TO_TICKS(50)) == ESP_OK) {
            addr_ms_a = a; break;
        }
    uint8_t addr_ms_b = 0;
    for (uint8_t a = 0x77; a >= 0x76; a--)
        if (i2c_master_probe(s_bus_b, a, pdMS_TO_TICKS(50)) == ESP_OK) {
            addr_ms_b = a; break;
        }
    uint8_t addr_bmp = 0;
    for (uint8_t a = 0x47; a >= 0x46; a--)
        if (i2c_master_probe(s_bus_b, a, pdMS_TO_TICKS(50)) == ESP_OK) {
            addr_bmp = a; break;
        }
    uint8_t addr_mpu = 0;
    for (uint8_t a = 0x69; a >= 0x68; a--)   /* 0x69, then 0x68 */
        if (i2c_master_probe(s_bus_a, a, pdMS_TO_TICKS(50)) == ESP_OK) {
            addr_mpu = a; break;
        }

    int sid = 0;
    esp_err_t e_bmp = ESP_ERR_NOT_FOUND;
    if (addr_bmp) {
        e_bmp = bmp581_init(&s_bmp, s_bus_b, addr_bmp);
        if (e_bmp == ESP_OK) {
            e_bmp = bmp581_start(&s_bmp);
        }
        if (e_bmp == ESP_OK) {
            s_baro_type[0] = BARO_BMP581;
            sid = 1;
        } else {
            ESP_LOGW(TAG, "bmp581 init failed: %s", esp_err_to_name(e_bmp));
        }
    }
    esp_err_t ea = ESP_ERR_NOT_FOUND, eb = ESP_ERR_NOT_FOUND;
    if (addr_ms_a) {
        ea = ms5611_init(&s_baro_a, s_bus_a, addr_ms_a);
        if (ea == ESP_OK) { s_ms_hdl[sid] = &s_baro_a; s_baro_type[sid++] = BARO_MS5611; }
    }
    if (addr_ms_b) {
        eb = ms5611_init(&s_baro_b, s_bus_b, addr_ms_b);
        if (eb == ESP_OK) { s_ms_hdl[sid] = &s_baro_b; s_baro_type[sid++] = BARO_MS5611; }
    }
    if (eb == ESP_ERR_NOT_FOUND && s_baro_type[1] == BARO_NONE)
        memset(&s_baro_b, 0, sizeof(s_baro_b));
    esp_err_t em = addr_mpu
        ? mpu6050_init(&s_mpu, s_bus_a, addr_mpu) : ESP_ERR_NOT_FOUND;
    s_mpu_addr = addr_mpu;
    s_n_baros = sid;
    if (ea != ESP_OK && addr_ms_a)
        ESP_LOGW(TAG, "ms5611 A init failed: %s", esp_err_to_name(ea));
    if (eb != ESP_OK && addr_ms_b)
        ESP_LOGW(TAG, "ms5611 B init failed: %s", esp_err_to_name(eb));
    if (em != ESP_OK) ESP_LOGW(TAG, "mpu init failed: %s", esp_err_to_name(em));

    emit_boot_meta();

    if (!(s_n_baros >= 1 && s_mpu.ok)) {
        tx_meta("#C,status=health_fail_halt");
        health_fail_loop();   /* does not return */
    }

    for (int s = 0; s < 2; s++) {
        if (s_baro_type[s] != BARO_MS5611) continue;
        ms5611_t *b = s_ms_hdl[s];
        baro_proc_init(&s_bp[s], b->prom);
        /* seed d2 to the nominal temperature ADC (dt=0 -> 20 degC) so the
         * first pressure samples before the first T frame compensate sanely;
         * a 0 here explodes the compensation to negative Pa -> NaN altitude
         * -> poisons the p0 mean (found via vnan B-line diagnostic). */
        s_d2[s] = (uint32_t)b->prom[5] * 256u;
    }

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
