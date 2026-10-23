/* config.h — vario-idf 0.1.0: as-built rig map and run configuration.
 *
 * ESP-IDF development firmware for the Vario USB bench rig, kept strictly
 * separate from the Arduino tree (../arduino). Speaks serial protocol v1
 * (docs/serial_protocol.md) so tools/capture.py and the whole offline
 * pipeline consume its captures unchanged. New frame types V (virtual
 * audio events) and B (benchmark stats) are additive; see README.md.
 *
 * Sensor-independence contract (same as the Arduino stream firmware):
 * raw ADC/counts are streamed; offline tools compensate. The MCU estimator
 * path compensates locally (baro_proc.c mirrors analysis/common.py exactly)
 * purely to drive the on-board estimator bank.
 */
#ifndef CONFIG_H
#define CONFIG_H

#include <stdint.h>

/* ---- Pin map (ESP32-S3-DevKitC-1; see docs/test_rig_schematic.md) -------- */
#define BUSA_SDA_GPIO  4
#define BUSA_SCL_GPIO  5
#define BUSB_SDA_GPIO  6
#define BUSB_SCL_GPIO  7

/* ---- As-built device map -------------------------------------------------- */
/* Addresses are auto-probed at boot (0x77 before 0x76 for baros — most
 * modules float CSB high; 0x69 before 0x68 for the MPU — AD0 high).  The
 * 2026-10-23 rework showed how easily wiring changes these: bench #1 clone
 * pulled CSB low (0x76) until the rework, after which it answered 0x77. */
#define I2C_FREQ_HZ    400000
#define I2C_TIMEOUT_MS 20

/* ---- Sampling schedule ---------------------------------------------------- */
/* GY-63 clone quirk (bench-verified 2026-10-23): conversion takes >10 ms at
 * OSR2048 despite the 4.54 ms datasheet typ — reads at +10 ms returned
 * d1=0 / partial ADC on ~33% of frames with zero I2C errors (clones ACK
 * and clock out junk while still converting; genuine MEAS parts NAK).
 * Schedule: convert every 4 ticks (20 ms, 50 Hz), read at +4 ticks
 * (>=20 ms window, 100% clean over 6000+ reads). */
#define TICK_MS        5      /* base tick: IMU read every tick            */
#define BARO_EVERY     4      /* baro D1 cycle every 4 ticks -> 50 Hz      */
#define TEMP_EVERY     20     /* baro D2 cycle every 20 ticks -> 10 Hz     */
#define MS5611_OSR_CMD_P 0x46 /* D1 OSR2048 */
#define MS5611_OSR_CMD_T 0x56 /* D2 OSR2048 */
#define MS5611_CONV_US   5000 /* OSR2048 typ 4.54 ms; wait 5.0 ms        */

/* ---- Streaming scales (declared in #C; offline tools read these) ---------- */
#define MPU_A_LSB_PER_G     4096    /* +-8 g   */
#define MPU_G_LSB_PER_DPS   65.5    /* +-500 dps */

/* ---- Estimator bank -------------------------------------------------------- *
 * One bank per barometer (sid). Each bank runs the competing architectures
 * side by side, all in double precision for parity with the Python
 * reference; float-precision equivalence is separately proven by the
 * portable-core host tests (results/15_portable_equivalence.csv).
 *   eid = sid * N_EST + index
 */
#define N_EST 5
#define EST_D01 0   /* plain CV Kalman, q=1.0 r=0.035                        */
#define EST_C03 1   /* steady-state-gain CV tracker (q=1.0 r=0.035)          */
#define EST_S4  2   /* fast/slow gated (tau_f=0.35, q_slow=0.3, r_slow=.035) */
#define EST_S5  3   /* light-gate robust KF (vario_core, q=0.3 r=0.035)      */
#define EST_FUS 4   /* baro+IMU fusion (Madgwick + async predict/correct)    */

#define D01_Q    1.0
#define D01_R    0.035
#define C03_Q    1.0
#define C03_R    0.035
#define S4_TAU_FAST_S   0.35
#define S4_Q_SLOW       0.3
#define S4_R_SLOW       0.035
#define S4_V_SCALE      0.8
#define S4_EXIT_V       0.12
#define S4_EXIT_HOLD_S  0.25
#define S4_W_FLOOR      0.3
#define S4_V_PLAUS_MAX  8.0
#define S4_PLAUS_MARGIN 0.3
#define S5_Q            0.3
#define S5_R            0.035
#define S5_GATE_SIGMA   3.5
#define S5_Q_GAIN       2.0
#define S5_V_SCALE      1.0
#define S5_V_PLAUS_MAX  8.0
#define S5_PLAUS_MARGIN 0.3
#define FUS_Q           0.3
#define FUS_R           0.035
#define FUS_GATE_SIGMA  3.5
#define FUS_REST_V_MAX  0.5
#define FUS_REST_WIN_S  1.0
#define FUS_BIAS_TAU_S  3.0
#define FUS_BIAS_ABSMAX 2.0
#define MADGWICK_BETA   0.3

/* ---- Virtual audio policy (common across estimators; audio.py defaults) --- */
#define AU_LIFT_ON      0.20
#define AU_LIFT_OFF     0.05
#define AU_TONE_BASE_HZ   500   /* tone = clamp(base + slope*v, min, max) */
#define AU_TONE_SLOPE_HZ  450
#define AU_TONE_MIN_HZ    400
#define AU_TONE_MAX_HZ    3500
#define AU_TONE_STEP_HZ   25    /* emit TONE event on >= this change      */

/* ---- TX path ---------------------------------------------------------------- */
#define TX_RING_BYTES   (240 * 1024)
#define TX_CHUNK_BYTES  2048

/* ---- Benchmark window -------------------------------------------------------- */
#define BENCH_REPORT_TICKS 1000   /* every 1000 base ticks = 5 s */

#endif
