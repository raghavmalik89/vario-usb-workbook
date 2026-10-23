/* bench.h — on-target benchmark instrumentation (CPU per estimator, tick
 * timing, I2C/TX error counters), reported as one B line every 5 s. */
#ifndef BENCH_H
#define BENCH_H

#include <stdint.h>

/* cycle counter (caller brackets the measured region) */
uint32_t bench_cycles(void);

/* per-estimator CPU accounting (cycles) for eid 0..(2*N_EST-1) */
void bench_cpu(int eid, uint32_t cycles);

/* sens-task tick budget: duration of one base tick [us] */
void bench_tick_duration(uint32_t tick_us);
/* a baro tick exceeded its 10 ms budget */
void bench_baro_miss(void);

/* I2C error counters: 0=baroA 1=baroB 2=mpu */
void bench_i2c_err(int which);

/* async baro slot diagnostics (start/emit/defer counts per window) */
void bench_dbg_baro(uint32_t p_start, uint32_t p_emit,
                    uint32_t t_start, uint32_t t_emit, uint32_t defer,
                    uint32_t adc_bad);

/* audio-path diagnostics for the next B report (consumed by bench_report) */
void bench_dbg_audio(unsigned long on, unsigned long fault,
                     double vmax_m_s, unsigned long nan_n);

/* section timing: which=0 IMU section, 1 baro service; us per call */
void bench_section(int which, uint32_t us);
/* CPU cycles per section call (cycle-counter ground truth) */
void bench_section_cyc(int which, uint32_t cycles);
/* vTaskDelayUntil wait duration, us (diagnoses scheduler stalls) */
void bench_delay(uint32_t us);
/* per-call I2C timing: channel 0=baro read_adc 1=baro start_conv 2=mpu read */
void bench_i2c_call(int ch, uint32_t us);

/* build + emit the B line, reset the reporting window */
void bench_report(void);

#endif
