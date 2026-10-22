/*
 * t002_baro_imu_stream.ino — T-002: T-001 stream + MPU6050 @ 200 Hz I frames.
 *
 * Adds to the T-001 baseline:
 *   - MPU6050 init (Bus A, Wire, GPIO4/5, @0x69): 200 Hz polling, ±2 g,
 *     ±250 dps, DLPF ~44 Hz. Raw int16 counts only — scaling/fusion offline.
 *   - I,<seq>,<t_us>,ax,ay,az,gx,gy,gz frames on the same USB-CDC stream.
 *   - IMU reads run on Wire (Bus A), barometer on Wire1 (Bus B): separate
 *     hardware I2C peripherals, so the 10 ms baro conversion never blocks
 *     the 5 ms IMU cadence.
 *
 * Meta-on-attach: opening a CDC port on the ESP32-S3 does NOT reset the
 * board, so a logger attaching after boot would miss the boot-time #H/#K/#C
 * frames (learned the hard way: t002_bench_60s capture lost its meta).
 * Fix: whenever a NEW host session attaches (CDC connect edge), the firmware
 * re-emits #H + #K + #C inline (a few hundred microseconds — no sampling
 * stall, no seq gap). At boot it additionally prints the legend and runs
 * the health check first.
 *
 * If the IMU fails init, the firmware degrades to baro-only (imu=off in #C)
 * instead of refusing to stream — the baro data is still valid.
 *
 * As-built addressing (docs/test_rig_schematic.md §6b):
 *   - Bus A (Wire,  GPIO4/5):  GY-63 @ 0x76, MPU6050 @ 0x69 (AD0 high)
 *   - Bus B (Wire1, GPIO6/7):  GY-63 @ 0x77  <- barometer under test, sid=1
 *
 * After flashing, log with:
 *   python ../tools/capture.py --auto --label t002_bench_60s --duration 60
 */

#include <Arduino.h>
#include <Wire.h>
#include <esp_timer.h>

// ---- Pin map ----------------------------------------------------------------
static const int BUSA_SDA = 4;
static const int BUSA_SCL = 5;
static const int BUSB_SDA = 6;
static const int BUSB_SCL = 7;

// ---- As-built device map (see docs/test_rig_schematic.md §6b) ---------------
static const uint8_t ADDR_BARO_A = 0x76;   // GY-63 #1, CSB low on this clone
static const uint8_t ADDR_MPU_A  = 0x69;   // AD0 tied to 3V3
static const uint8_t ADDR_BARO_B = 0x77;   // GY-63 #2 — the unit under test
static const int BARO_SID = 1;             // protocol: sid 1 = Bus B

// ---- MS5611 registers --------------------------------------------------------
static const uint8_t MS5611_RESET      = 0x1E;
static const uint8_t MS5611_ADC_READ   = 0x00;
static const uint8_t MS5611_CONV_PRESS = 0x48;  // D1, OSR4096
static const uint8_t MS5611_CONV_TEMP  = 0x58;  // D2, OSR4096

// ---- MPU6050 registers -------------------------------------------------------
static const uint8_t MPU_REG_SMPLRT_DIV   = 0x19;
static const uint8_t MPU_REG_CONFIG       = 0x1A;
static const uint8_t MPU_REG_GYRO_CONFIG  = 0x1B;
static const uint8_t MPU_REG_ACCEL_CONFIG = 0x1C;
static const uint8_t MPU_REG_PWR_MGMT_1   = 0x6B;
static const uint8_t MPU_REG_ACCEL_XOUT_H = 0x3B;
static const uint8_t MPU_WHO_AM_I         = 0x75;

static const uint32_t CONV_US  = 10000;  // MS5611: 9.04 ms typ, ~10 ms max
static const uint32_t CYCLE_US = 20000;  // baro tick: 45 Hz P + 5 Hz T
static const uint32_t IMU_US   = 5000;   // 200 Hz IMU cadence

// ---- Protocol state ---------------------------------------------------------
static uint32_t seq = 0;
static uint16_t prom[8];

enum Phase { IDLE, CONVERTING };
static Phase phase = IDLE;
static bool convertingTemp = false;
static uint64_t convDeadlineUs = 0;
static uint64_t nextCycleUs = 0;
static uint32_t cycleCount = 0;
static bool baroOK = false;

static bool imuOK = false;
static uint64_t nextImuUs = 0;

static bool hostSeen = false;   // CDC host-session state for meta-on-attach

static inline uint64_t nowUs() { return (uint64_t)esp_timer_get_time(); }

static void emitError(uint64_t t, uint8_t code) {
  Serial.printf("E,%lu,%llu,%u\n", (unsigned long)seq++, (unsigned long long)t, code);
}

// ============================================================================
// Meta frames
// ============================================================================

static void printLegend() {
  Serial.printf("#,================= what you are about to see =================\n");
  Serial.printf("#,HEALTH CHECK first — one line per sensor, expect status=ok:\n");
  Serial.printf("#,  #C,dev=a0,...,addr=0x76,...  (Bus A baro)\n");
  Serial.printf("#,  #C,dev=a1,...,addr=0x69,...  (Bus A IMU, whoami must be 0x68)\n");
  Serial.printf("#,  #C,dev=b1,...,addr=0x77,...  (Bus B baro = unit under test)\n");
  Serial.printf("#,  #C,health=ok,missing=0   <- stream starts ONLY if this says ok\n");
  Serial.printf("#,THEN: #K = factory calibration of the streaming barometer (keep!)\n");
  Serial.printf("#,  #C,osr=... = the real rates this firmware achieves.\n");
  Serial.printf("#,DATA FRAMES:\n");
  Serial.printf("#,  P,<seq>,<t_us>,1,<d1>  raw pressure ADC 24-bit (~7.9M at bench level;\n");
  Serial.printf("#,    d1 UP = pressure UP = altitude DOWN; wiggle = noise floor)\n");
  Serial.printf("#,  T,<seq>,<t_us>,1,<d2>  raw temperature ADC 24-bit (~8.2M near 22C)\n");
  Serial.printf("#,  I,<seq>,<t_us>,ax,ay,az,gx,gy,gz  MPU6050 raw int16 counts,\n");
  Serial.printf("#,    accel +-2g (16384 LSB/g), gyro +-250dps (131 LSB/dps), ~200 Hz.\n");
  Serial.printf("#,    Self-check: whichever accel axis points up reads ~+-16384,\n");
  Serial.printf("#,    the other two ~0. Gyro biases can be LARGE on clones\n");
  Serial.printf("#,    (tens of dps) — that's normal, removed offline at rest.\n");
  Serial.printf("#,  E,<seq>,<t_us>,<code>  ERROR (1=NAK 2=timeout 3=overflow).\n");
  Serial.printf("#,NOTES: t_us = us since boot. seq counts every line; a gap = a\n");
  Serial.printf("#,dropped sample. sid=1 means the Bus B barometer.\n");
  Serial.printf("#,=============================================================\n");
}

static void emitHeader(bool full) {
  Serial.printf("#H,vario-bench-t002,0.2.2\n");
  if (full) printLegend();
}

static void emitConfig() {
  if (!baroOK) {
    Serial.printf("#C,status=fault_no_stream\n");
    return;
  }
  Serial.printf("#K,%d,%u,%u,%u,%u,%u,%u\n", BARO_SID,
                prom[1], prom[2], prom[3], prom[4], prom[5], prom[6]);
  Serial.printf("#C,osr=4096,p_hz=45,t_hz=5,imu=%s,i_hz=%d,dlpf=44hz,"
                "accel_fs=2g,gyro_fs=250dps\n", imuOK ? "on" : "off", 200);
}

// ============================================================================
// Health check
// ============================================================================

static bool probeAck(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  return w.endTransmission() == 0;
}

static uint16_t ms5611Prom0(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  w.write(0xA0);
  if (w.endTransmission(false) != 0) return 0xFFFF;
  if (w.requestFrom(addr, (uint8_t)2) != 2) return 0xFFFF;
  uint8_t hi = w.read();   // locals: operand order of '|' is unspecified —
  uint8_t lo = w.read();   // never chain read() calls inside one expression
  return (uint16_t)((hi << 8) | lo);
}

static uint8_t mpuWhoAmI(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  w.write(MPU_WHO_AM_I);
  if (w.endTransmission(false) != 0) return 0xFF;
  if (w.requestFrom(addr, (uint8_t)1) != 1) return 0xFF;
  return w.read();
}

static bool healthCheck() {
  int missing = 0;

  if (probeAck(Wire, ADDR_BARO_A)) {
    uint16_t p0 = ms5611Prom0(Wire, ADDR_BARO_A);
    bool alive = (p0 != 0x0000 && p0 != 0xFFFF);
    Serial.printf("#C,dev=a0,type=ms5611,addr=0x%02X,prom0=0x%04X,status=%s\n",
                  ADDR_BARO_A, p0, alive ? "ok" : "bad_id");
    if (!alive) missing++;
  } else {
    Serial.printf("#C,dev=a0,type=ms5611,addr=0x%02X,status=missing\n", ADDR_BARO_A);
    missing++;
  }

  if (probeAck(Wire, ADDR_MPU_A)) {
    uint8_t who = mpuWhoAmI(Wire, ADDR_MPU_A);
    bool alive = (who == 0x68);
    Serial.printf("#C,dev=a1,type=mpu6050,addr=0x%02X,whoami=0x%02X,status=%s\n",
                  ADDR_MPU_A, who, alive ? "ok" : "bad_id");
    if (!alive) missing++;
  } else {
    Serial.printf("#C,dev=a1,type=mpu6050,addr=0x%02X,status=missing\n", ADDR_MPU_A);
    missing++;
  }

  bool testBaroOK = false;
  if (probeAck(Wire1, ADDR_BARO_B)) {
    uint16_t p0 = ms5611Prom0(Wire1, ADDR_BARO_B);
    bool alive = (p0 != 0x0000 && p0 != 0xFFFF);
    Serial.printf("#C,dev=b1,type=ms5611,addr=0x%02X,prom0=0x%04X,status=%s\n",
                  ADDR_BARO_B, p0, alive ? "ok" : "bad_id");
    testBaroOK = alive;
  } else {
    Serial.printf("#C,dev=b1,type=ms5611,addr=0x%02X,status=missing\n", ADDR_BARO_B);
  }

  Serial.printf("#C,health=%s,missing=%d\n", testBaroOK ? "ok" : "fail", missing);
  return testBaroOK;
}

// ============================================================================
// Barometer sampling
// ============================================================================

static bool readADC24(uint32_t &val) {
  Wire1.beginTransmission(ADDR_BARO_B);
  Wire1.write(MS5611_ADC_READ);
  if (Wire1.endTransmission(false) != 0) return false;
  if (Wire1.requestFrom(ADDR_BARO_B, (uint8_t)3) != 3) return false;
  uint8_t b0 = Wire1.read();
  uint8_t b1 = Wire1.read();
  uint8_t b2 = Wire1.read();
  val = ((uint32_t)b0 << 16) | ((uint32_t)b1 << 8) | b2;
  return true;
}

static void startConversion(bool temp) {
  Wire1.beginTransmission(ADDR_BARO_B);
  Wire1.write(temp ? MS5611_CONV_TEMP : MS5611_CONV_PRESS);
  if (Wire1.endTransmission() != 0) {
    emitError(nowUs(), 1);
    phase = IDLE;
    return;
  }
  convertingTemp = temp;
  convDeadlineUs = nowUs() + CONV_US;
  phase = CONVERTING;
}

static void finishConversion() {
  uint32_t raw;
  if (!readADC24(raw)) {
    emitError(nowUs(), 1);
    phase = IDLE;
    return;
  }
  uint64_t t = nowUs();
  if (convertingTemp)
    Serial.printf("T,%lu,%llu,%d,%lu\n", (unsigned long)seq++,
                  (unsigned long long)t, BARO_SID, (unsigned long)raw);
  else
    Serial.printf("P,%lu,%llu,%d,%lu\n", (unsigned long)seq++,
                  (unsigned long long)t, BARO_SID, (unsigned long)raw);
  phase = IDLE;
}

// ============================================================================
// IMU (MPU6050 @ 200 Hz, polled)
// ============================================================================

static bool mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(ADDR_MPU_A);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

static bool mpuInit() {
  if (!mpuWrite(MPU_REG_PWR_MGMT_1, 0x01)) return false;    // X-gyro PLL
  delay(10);
  if (!mpuWrite(MPU_REG_SMPLRT_DIV, 4)) return false;       // 1 kHz/(1+4) = 200 Hz
  if (!mpuWrite(MPU_REG_CONFIG, 0x03)) return false;        // DLPF ~44 Hz gyro BW
  if (!mpuWrite(MPU_REG_GYRO_CONFIG, 0x00)) return false;   // ±250 dps
  if (!mpuWrite(MPU_REG_ACCEL_CONFIG, 0x00)) return false;  // ±2 g
  return true;
}

static bool readIMU(int16_t v[6]) {
  Wire.beginTransmission(ADDR_MPU_A);
  Wire.write(MPU_REG_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(ADDR_MPU_A, (uint8_t)14) != 14) return false;
  uint8_t b[14];
  for (int i = 0; i < 14; i++) b[i] = Wire.read();
  for (int i = 0; i < 6; i++)
    v[i] = (int16_t)((b[2 * i] << 8) | b[2 * i + 1]);
  return true;
}

static void serviceIMU() {
  // schedule accumulator; if more than one interval behind, resync
  // instead of spiraling into back-to-back reads
  nextImuUs += IMU_US;
  if ((int64_t)(nowUs() - nextImuUs) >= 0) nextImuUs = nowUs() + IMU_US;

  int16_t v[6];
  if (!readIMU(v)) {
    emitError(nowUs(), 1);
    return;
  }
  uint64_t t = nowUs();
  Serial.printf("I,%lu,%llu,%d,%d,%d,%d,%d,%d\n", (unsigned long)seq++,
                (unsigned long long)t, v[0], v[1], v[2], v[3], v[4], v[5]);
}

// ============================================================================
// Setup / loop
// ============================================================================

void setup() {
  Serial.begin(921600);

  // Wait for a host to attach (max 5 s), then let the CDC link settle so the
  // boot meta doesn't land inside capture.py's port-open input flush.
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 5000) delay(10);
  delay(2500);
  hostSeen = (bool)Serial;

  Wire.begin(BUSA_SDA, BUSA_SCL);
  Wire.setClock(400000);
  Wire.setTimeout(50);
  Wire1.begin(BUSB_SDA, BUSB_SCL);
  Wire1.setClock(400000);
  Wire1.setTimeout(50);

  emitHeader(true);

  if (!healthCheck()) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=baro_init_failed\n");
    return;
  }

  Wire1.beginTransmission(ADDR_BARO_B);
  Wire1.write(MS5611_RESET);
  baroOK = (Wire1.endTransmission() == 0);
  delay(3);
  if (baroOK) {
    for (int i = 0; i < 8 && baroOK; i++) {
      Wire1.beginTransmission(ADDR_BARO_B);
      Wire1.write(0xA0 + 2 * i);
      if (Wire1.endTransmission(false) != 0 ||
          Wire1.requestFrom(ADDR_BARO_B, (uint8_t)2) != 2) {
        baroOK = false;
        break;
      }
      uint8_t hi = Wire1.read();
      uint8_t lo = Wire1.read();
      prom[i] = (uint16_t)((hi << 8) | lo);
    }
  }
  if (!baroOK) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=prom_read_failed\n");
    return;
  }

  imuOK = mpuInit();
  if (!imuOK) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=imu_init_failed\n");
  }

  emitConfig();

  uint64_t t0u = nowUs() + 5000;  // offset IMU/baron ticks slightly apart
  nextCycleUs = t0u;
  nextImuUs = t0u + IMU_US;
}

void loop() {
  // Meta-on-attach: a new host session (capture.py opening the port) gets
  // #H/#K/#C re-emitted — but DELAYED 2.5 s, because capture.py flushes its
  // input buffer ~2 s after port open; an immediate emit lands inside that
  // flush and is lost (learned on the first t003 capture). At t+2.5 s the
  // logger is reading, so the meta is captured. Costs ~0.5 ms once; the IMU
  // resync absorbs it.
  static uint64_t attachMetaAtUs = 0;
  bool connected = (bool)Serial;
  if (connected && !hostSeen) {
    hostSeen = true;
    attachMetaAtUs = nowUs() + 2500000;
  } else if (!connected && hostSeen) {
    hostSeen = false;
    attachMetaAtUs = 0;
  }
  if (attachMetaAtUs && connected &&
      (int64_t)(nowUs() - attachMetaAtUs) >= 0) {
    attachMetaAtUs = 0;
    emitHeader(false);
    emitConfig();
  }

  if (!baroOK) return;

  uint64_t t = nowUs();

  if (phase == CONVERTING) {
    if ((int64_t)(t - convDeadlineUs) >= 0) finishConversion();
  } else if ((int64_t)(t - nextCycleUs) >= 0) {
    bool doTemp = (cycleCount % 10 == 9);
    cycleCount++;
    nextCycleUs += CYCLE_US;
    startConversion(doTemp);
  }

  if (imuOK && (int64_t)(t - nextImuUs) >= 0) serviceIMU();
}
