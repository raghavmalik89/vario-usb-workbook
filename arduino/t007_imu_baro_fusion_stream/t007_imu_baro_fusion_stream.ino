/*
 * t007_imu_baro_fusion_stream.ino — Phase 5: dual MS5611 + MPU6050, one stream.
 *
 * Purpose: give the Phase-4 BaroImuFusion interface REAL IMU data to validate
 * against (Phase 4 was synthetic-IMU only). Sensor-independent by design:
 * the firmware streams raw integer counts + LSB scale factors in #C meta, so
 * any future IMU/baro substitute only changes init code and the #C line —
 * the analysis side never hard-codes a part number.
 *
 *   - Baro A: GY-63 #1 on Bus A (Wire,   GPIO4/5) @ 0x76 -> sid=0
 *   - Baro B: GY-63 #2 on Bus B (Wire1,  GPIO6/7) @ 0x77 -> sid=1
 *   - Baro C: bus C (bit-bang GPIO15/16) probed, empty on this rig
 *     (t005 v0.5.2+ degraded semantics: >=2 baros -> stream).
 *   - IMU:    MPU6050 on Bus A (Wire, shares the bus with baro A @0x69)
 *     200 Hz, ±8 g, ±500 dps, DLPF ~44 Hz.
 *
 * Baro timing identical to t006 (OSR2048, 10 ms tick -> 90 Hz P + 10 Hz T)
 * so t007 baro columns are directly comparable with the t006 captures.
 *
 * Why ±8 g / ±500 dps (t002 used ±2 g / ±250): drop landings and throws
 * saturate a ±2 g accel for the whole impact — exactly the interval fusion
 * cares about. ±8 g keeps landings in range; 4096 LSB/g costs 4x raw
 * resolution, still ~2.4 mm/s^2/LSB, far below baro-derived accel noise.
 * Gyro ±500 dps covers throw spins without clipping.
 *
 * IMU failure degrades to baro-only (imu=off in #C), matching t002 semantics.
 * IMU reads and baro-A reads share Wire: all synchronous, single thread,
 * the 5 ms conversion window absorbs the ~0.5 ms IMU transaction.
 *
 * Meta-on-attach: #H/#K/#C re-emitted on new host session (CDC open does not
 * reset the S3 — see t002/t003 history).
 *
 * Capture (same motion profile as t005/t006 so datasets compare):
 *   python ../tools/capture.py --port COM5 --label t007_benchstatic --duration 60
 *   python ../tools/capture.py --port COM5 --label t007_drop --duration 35
 *   python ../tools/capture.py --port COM5 --label t007_toss --duration 45
 *   python ../tools/capture.py --port COM5 --label t007_ControledMove --duration 40
 *   python ../tools/capture.py --port COM5 --label t007_elevator_2x --duration 180
 */

#include <Arduino.h>
#include <Wire.h>
#include <esp_timer.h>

// ---- Pin map ----------------------------------------------------------------
static const int BUSA_SDA = 4;
static const int BUSA_SCL = 5;
static const int BUSB_SDA = 6;
static const int BUSB_SCL = 7;
static const int BUSC_SDA = 15;   // bit-banged
static const int BUSC_SCL = 16;   // bit-banged

// ---- As-built device map (see docs/test_rig_schematic.md §6b) ---------------
static const uint8_t ADDR_BARO_A = 0x76;   // GY-63 #1, CSB low on this clone
static const uint8_t ADDR_BARO_B = 0x77;   // GY-63 #2
static const uint8_t ADDR_MPU_A  = 0x69;   // AD0 tied to 3V3
static const int SID_A = 0;                // protocol: sid 0 = Bus A
static const int SID_B = 1;                // protocol: sid 1 = Bus B
static const int SID_C = 2;                // protocol: sid 2 = Bus C (soft)

// ---- MS5611 registers --------------------------------------------------------
static const uint8_t MS5611_RESET      = 0x1E;
static const uint8_t MS5611_ADC_READ   = 0x00;
static const uint8_t MS5611_CONV_PRESS = 0x46;  // D1, OSR2048
static const uint8_t MS5611_CONV_TEMP  = 0x56;  // D2, OSR2048

// ---- MPU6050 registers -------------------------------------------------------
static const uint8_t MPU_REG_SMPLRT_DIV   = 0x19;
static const uint8_t MPU_REG_CONFIG       = 0x1A;
static const uint8_t MPU_REG_GYRO_CONFIG  = 0x1B;
static const uint8_t MPU_REG_ACCEL_CONFIG = 0x1C;
static const uint8_t MPU_REG_PWR_MGMT_1   = 0x6B;
static const uint8_t MPU_REG_ACCEL_XOUT_H = 0x3B;
static const uint8_t MPU_WHO_AM_I         = 0x75;

// Full-scale scale factors for the #C meta line (sensor-independence contract:
// offline tools read these instead of hard-coding part numbers).
static const int ACCEL_LSB_PER_G    = 4096;   // ±8 g (exact)
// ±500 dps is 65.5 LSB/dps — printed as a float in #C, not an int.

static const uint32_t CONV_US  = 5000;   // OSR2048: 4.13 ms typ, ~4.6 ms max
static const uint32_t CYCLE_US = 10000;  // baro tick: 90 Hz P + 10 Hz T per sid
static const uint32_t IMU_US   = 5000;   // 200 Hz IMU cadence

// ---- Protocol state ---------------------------------------------------------
static uint32_t seq = 0;

struct Baro {
  TwoWire *hw;        // Wire / Wire1, or nullptr for the bit-banged bus
  uint8_t addr;       // resolved (bus C is probed at health-check time)
  int sid;
  uint16_t prom[8];
  bool ok;
};
static Baro baros[3] = {
  { &Wire,  ADDR_BARO_A, SID_A, {0}, false },
  { &Wire1, ADDR_BARO_B, SID_B, {0}, false },
  { nullptr, 0x77,       SID_C, {0}, false },   // addr probed below
};

enum Phase { IDLE, CONVERTING };
static Phase phase = IDLE;
static bool convertingTemp = false;
static uint64_t convDeadlineUs = 0;
static uint64_t nextCycleUs = 0;
static uint32_t cycleCount = 0;
static bool baroOK = false;

static bool imuOK = false;
static uint64_t nextImuUs = 0;

static bool hostSeen = false;

static inline uint64_t nowUs() { return (uint64_t)esp_timer_get_time(); }

static void emitError(uint64_t t, uint8_t code) {
  Serial.printf("E,%lu,%llu,%u\n", (unsigned long)seq++, (unsigned long long)t, code);
}

// ============================================================================
// Bit-banged I2C for Bus C (proven in i2c_scan_test / T-000 / t005 / t006).
// ============================================================================

static inline void bbRelease(int pin) { pinMode(pin, INPUT_PULLUP); }
static inline void bbLow(int pin)     { pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
static inline bool bbRead(int pin)    { return digitalRead(pin); }

static void bbStartCond() {
  bbRelease(BUSC_SDA); bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bbLow(BUSC_SDA);
  delayMicroseconds(5);
  bbLow(BUSC_SCL);
  delayMicroseconds(5);
}

static void bbStop() {
  bbLow(BUSC_SDA);
  delayMicroseconds(5);
  bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bbRelease(BUSC_SDA);
  delayMicroseconds(5);
}

static bool bbWriteByte(uint8_t byte) {
  for (int i = 7; i >= 0; i--) {
    if (byte & (1 << i)) bbRelease(BUSC_SDA); else bbLow(BUSC_SDA);
    delayMicroseconds(5);
    bbRelease(BUSC_SCL);
    delayMicroseconds(5);
    bbLow(BUSC_SCL);
    delayMicroseconds(5);
  }
  bbRelease(BUSC_SDA);
  delayMicroseconds(5);
  bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bool ack = !bbRead(BUSC_SDA);
  bbLow(BUSC_SCL);
  delayMicroseconds(5);
  return ack;
}

static uint8_t bbReadByte(bool ackMore) {
  bbRelease(BUSC_SDA);
  uint8_t v = 0;
  for (int i = 0; i < 8; i++) {
    bbRelease(BUSC_SCL);
    delayMicroseconds(5);
    v = (v << 1) | (bbRead(BUSC_SDA) ? 1 : 0);
    bbLow(BUSC_SCL);
    delayMicroseconds(5);
  }
  if (ackMore) bbLow(BUSC_SDA); else bbRelease(BUSC_SDA);
  delayMicroseconds(5);
  bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bbLow(BUSC_SCL);
  delayMicroseconds(5);
  return v;
}

static bool bbWriteReg(uint8_t addr, uint8_t reg) {
  bbStartCond();
  if (!bbWriteByte(addr << 1)) { bbStop(); return false; }
  bool ok = bbWriteByte(reg);
  bbStop();
  return ok;
}

static bool bbReadBytes(uint8_t addr, uint8_t reg, uint8_t *dst, int n) {
  if (!bbWriteReg(addr, reg)) return false;
  bbStartCond();
  if (!bbWriteByte((addr << 1) | 1)) { bbStop(); return false; }
  for (int i = 0; i < n; i++) dst[i] = bbReadByte(i < n - 1);
  bbStop();
  return true;
}

// ============================================================================
// Sensor-generic bus ops
// ============================================================================

static bool probeAck(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  return w.endTransmission() == 0;
}

static bool bbProbe(uint8_t addr) {
  bbStartCond();
  bool ack = bbWriteByte(addr << 1);
  bbStop();
  return ack;
}

static void bbBusRecover() {
  bbRelease(BUSC_SDA);
  for (int i = 0; i < 9; i++) {
    bbRelease(BUSC_SCL);
    delayMicroseconds(5);
    bbLow(BUSC_SCL);
    delayMicroseconds(5);
  }
  bbStop();
}

static bool prom0Of(TwoWire &w, uint8_t addr, uint16_t &p0) {
  w.beginTransmission(addr);
  w.write(0xA0);
  if (w.endTransmission(false) != 0) return false;
  if (w.requestFrom(addr, (uint8_t)2) != 2) return false;
  uint8_t hi = w.read();   // locals: operand order of '|' is unspecified —
  uint8_t lo = w.read();   // never chain read() calls inside one expression
  p0 = (uint16_t)((hi << 8) | lo);
  return true;
}

static uint8_t mpuWhoAmI(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  w.write(MPU_WHO_AM_I);
  if (w.endTransmission(false) != 0) return 0xFF;
  if (w.requestFrom(addr, (uint8_t)1) != 1) return 0xFF;
  return w.read();
}

static bool readADC24(Baro &b, uint32_t &val) {
  uint8_t buf[3];
  bool ok;
  if (b.hw) {
    b.hw->beginTransmission(b.addr);
    b.hw->write(MS5611_ADC_READ);
    if (b.hw->endTransmission(false) != 0) return false;
    if (b.hw->requestFrom(b.addr, (uint8_t)3) != 3) return false;
    buf[0] = b.hw->read();
    buf[1] = b.hw->read();
    buf[2] = b.hw->read();
    ok = true;
  } else {
    ok = bbReadBytes(b.addr, MS5611_ADC_READ, buf, 3);
  }
  if (!ok) return false;
  val = ((uint32_t)buf[0] << 16) | ((uint32_t)buf[1] << 8) | buf[2];
  return true;
}

static bool convStart(Baro &b, bool temp) {
  uint8_t cmd = temp ? MS5611_CONV_TEMP : MS5611_CONV_PRESS;
  if (b.hw) {
    b.hw->beginTransmission(b.addr);
    b.hw->write(cmd);
    return b.hw->endTransmission() == 0;
  }
  return bbWriteReg(b.addr, cmd);
}

static bool readProm(Baro &b) {
  if (b.hw) {
    b.hw->beginTransmission(b.addr);
    b.hw->write(MS5611_RESET);
    if (b.hw->endTransmission() != 0) return false;
  } else {
    if (!bbWriteReg(b.addr, MS5611_RESET)) return false;
  }
  delay(3);
  for (int i = 0; i < 8; i++) {
    uint8_t reg = 0xA0 + 2 * i;
    if (b.hw) {
      b.hw->beginTransmission(b.addr);
      b.hw->write(reg);
      if (b.hw->endTransmission(false) != 0 || b.hw->requestFrom(b.addr, (uint8_t)2) != 2)
        return false;
      uint8_t hi = b.hw->read();
      uint8_t lo = b.hw->read();
      b.prom[i] = (uint16_t)((hi << 8) | lo);
    } else {
      uint8_t buf[2];
      if (!bbReadBytes(b.addr, reg, buf, 2)) return false;
      b.prom[i] = (uint16_t)((buf[0] << 8) | buf[1]);
    }
  }
  return true;
}

// ============================================================================
// IMU (MPU6050 @ 200 Hz, polled — t002 proven path)
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
  if (!mpuWrite(MPU_REG_CONFIG, 0x03)) return false;        // DLPF ~44 Hz
  if (!mpuWrite(MPU_REG_GYRO_CONFIG, 0x08)) return false;   // ±500 dps
  if (!mpuWrite(MPU_REG_ACCEL_CONFIG, 0x10)) return false;  // ±8 g
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
  // schedule accumulator; resync instead of spiraling if behind (t002 logic)
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
// Meta frames
// ============================================================================

static void printLegend() {
  Serial.printf("#,================= what you are about to see =================\n");
  Serial.printf("#,HEALTH CHECK first — one line per sensor, expect status=ok:\n");
  Serial.printf("#,  #C,dev=a0,...,addr=0x76,...  (Bus A baro, sid=0)\n");
  Serial.printf("#,  #C,dev=a1,...,addr=0x69,...  (Bus A IMU — STREAMED this time)\n");
  Serial.printf("#,  #C,dev=b1,...,addr=0x77,...  (Bus B baro, sid=1)\n");
  Serial.printf("#,  #C,dev=c1,...,addr=0x??,...  (Bus C baro, sid=2 — probed)\n");
  Serial.printf("#,  #C,health=ok|degraded — stream starts with >= 2 baros\n");
  Serial.printf("#,THEN: #K lines, one per live barometer — keep them.\n");
  Serial.printf("#,  #C,osr=...,a_lsb_per_g=...,g_lsb_per_dps=... = scales for\n");
  Serial.printf("#,    offline conversion — analysis never hard-codes a part.\n");
  Serial.printf("#,DATA FRAMES:\n");
  Serial.printf("#,  P,<seq>,<t_us>,<sid>,<d1>  raw pressure ADC 24-bit, sid 0/1(/2)\n");
  Serial.printf("#,  T,<seq>,<t_us>,<sid>,<d2>  raw temperature ADC\n");
  Serial.printf("#,  I,<seq>,<t_us>,ax,ay,az,gx,gy,gz  IMU raw int16 counts at ~200 Hz.\n");
  Serial.printf("#,    Self-check at rest: the axis pointing up reads +-a_lsb_per_g,\n");
  Serial.printf("#,    the other two ~0; |a| = g means the rig is NOT accelerating —\n");
  Serial.printf("#,    the fusion bias estimator keys on that.\n");
  Serial.printf("#,  E,<seq>,<t_us>,<code>  ERROR (1=NAK 2=timeout 3=overflow).\n");
  Serial.printf("#,=============================================================\n");
}

static void emitHeader(bool full) {
  Serial.printf("#H,vario-bench-t007,0.7.0\n");
  if (full) printLegend();
}

static void emitConfig() {
  if (!baroOK) {
    Serial.printf("#C,status=fault_no_stream\n");
    return;
  }
  int nOK = 0;
  for (int i = 0; i < 3; i++) if (baros[i].ok) nOK++;
  for (int i = 0; i < 3; i++) {
    if (!baros[i].ok) continue;
    Serial.printf("#K,%d,%u,%u,%u,%u,%u,%u\n", baros[i].sid,
                  baros[i].prom[1], baros[i].prom[2], baros[i].prom[3],
                  baros[i].prom[4], baros[i].prom[5], baros[i].prom[6]);
  }
  Serial.printf("#C,osr=2048,p_hz=90,t_hz=10,sensors=%d,imu=%s,i_hz=%d,"
                "dlpf=44hz,a_lsb_per_g=%d,g_lsb_per_dps=65.5,a_fs=8g,"
                "g_fs=500dps,c_addr=0x%02X,c_status=%s\n",
                nOK, imuOK ? "on" : "off", imuOK ? 200 : 0,
                ACCEL_LSB_PER_G,
                baros[2].addr, baros[2].ok ? "ok" : "missing");
}

// ============================================================================
// Health check — >=2 baros required; IMU reported but never blocking.
// ============================================================================

static bool healthCheck() {
  int baroMissing = 0;

  if (probeAck(Wire, ADDR_BARO_A)) {
    uint16_t p0 = 0xFFFF;
    baros[0].ok = prom0Of(Wire, ADDR_BARO_A, p0) &&
                  (p0 != 0x0000 && p0 != 0xFFFF);
    Serial.printf("#C,dev=a0,type=ms5611,addr=0x%02X,prom0=0x%04X,status=%s\n",
                  ADDR_BARO_A, p0, baros[0].ok ? "ok" : "bad_id");
  } else {
    Serial.printf("#C,dev=a0,type=ms5611,addr=0x%02X,status=missing\n", ADDR_BARO_A);
  }

  if (probeAck(Wire, ADDR_MPU_A)) {
    uint8_t who = mpuWhoAmI(Wire, ADDR_MPU_A);
    imuOK = (who == 0x68);
    Serial.printf("#C,dev=a1,type=mpu6050,addr=0x%02X,whoami=0x%02X,status=%s\n",
                  ADDR_MPU_A, who, imuOK ? "ok" : "bad_id");
  } else {
    Serial.printf("#C,dev=a1,type=mpu6050,addr=0x%02X,status=missing\n", ADDR_MPU_A);
  }

  if (probeAck(Wire1, ADDR_BARO_B)) {
    uint16_t p0 = 0xFFFF;
    baros[1].ok = prom0Of(Wire1, ADDR_BARO_B, p0) &&
                  (p0 != 0x0000 && p0 != 0xFFFF);
    Serial.printf("#C,dev=b1,type=ms5611,addr=0x%02X,prom0=0x%04X,status=%s\n",
                  ADDR_BARO_B, p0, baros[1].ok ? "ok" : "bad_id");
  } else {
    Serial.printf("#C,dev=b1,type=ms5611,addr=0x%02X,status=missing\n", ADDR_BARO_B);
  }

  // Bus C probe (same retry + bus-recovery logic as t006)
  bbBusRecover();
  uint8_t cAddr = 0;
  for (int attempt = 0; attempt < 2 && !cAddr; attempt++) {
    for (uint8_t cand : {0x77, 0x76}) {
      if (bbProbe(cand)) { cAddr = cand; break; }
    }
    if (!cAddr) delay(150);
  }
  baros[2].addr = cAddr ? cAddr : 0x77;
  if (cAddr) {
    uint8_t buf[2];
    uint16_t p0 = 0xFFFF;
    if (bbReadBytes(cAddr, 0xA0, buf, 2))
      p0 = (uint16_t)((buf[0] << 8) | buf[1]);
    baros[2].ok = (p0 != 0x0000 && p0 != 0xFFFF);
    Serial.printf("#C,dev=c1,type=ms5611,addr=0x%02X,prom0=0x%04X,status=%s\n",
                  cAddr, p0, baros[2].ok ? "ok" : "bad_id");
  } else {
    Serial.printf("#C,dev=c1,type=ms5611,addr=0x77,status=missing\n");
  }

  for (int i = 0; i < 3; i++) {
    if (!baros[i].ok) baroMissing++;
  }
  const char *hs = (baroMissing == 0) ? "ok" : (baroMissing == 1) ? "degraded" : "fail";
  // IMU missing is reported via dev=a1 status and imu=off in #C, but does not
  // count toward health=fail: the baro stream is still valuable (t002 rule).
  Serial.printf("#C,health=%s,missing=%d\n", hs, baroMissing);
  return baroMissing <= 1;
}

// ============================================================================
// Dual barometer sampling (lockstep, t006 scheme)
// ============================================================================

static void startConversion(bool temp) {
  uint64_t t = nowUs();
  for (int i = 0; i < 3; i++) {
    if (!baros[i].ok) continue;
    if (!convStart(baros[i], temp)) emitError(t, 1);
  }
  convertingTemp = temp;
  convDeadlineUs = t + CONV_US;
  phase = CONVERTING;
}

static void finishConversion() {
  uint64_t t = nowUs();
  for (int i = 0; i < 3; i++) {
    if (!baros[i].ok) continue;
    uint32_t raw = 0;
    if (readADC24(baros[i], raw)) {
      Serial.printf("%c,%lu,%llu,%d,%lu\n", convertingTemp ? 'T' : 'P',
                    (unsigned long)seq++, (unsigned long long)t, baros[i].sid,
                    (unsigned long)raw);
    } else {
      emitError(t, 1);
    }
  }
  phase = IDLE;
}

// ============================================================================
// Setup / loop
// ============================================================================

void setup() {
  Serial.begin(921600);

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

  delay(300);  // power/I2C settle (fresh MS5611 can ignore first transactions)

  emitHeader(true);

  if (!healthCheck()) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=baro_init_failed\n");
    return;
  }

  // IMU init AFTER the health check set imuOK; failure degrades, never blocks.
  if (imuOK) {
    imuOK = mpuInit();
    if (!imuOK) {
      emitError(nowUs(), 1);
      Serial.printf("#C,status=imu_init_failed (baro-only stream)\n");
    }
  }

  bool okProm = true;
  for (int i = 0; i < 3; i++) {
    if (!baros[i].ok) continue;
    if (!readProm(baros[i])) okProm = false;
  }
  baroOK = okProm;
  if (!baroOK) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=prom_read_failed,a=%d,b=%d,c=%d\n",
                  baros[0].ok, baros[1].ok, baros[2].ok);
    return;
  }

  emitConfig();

  uint64_t t0u = nowUs() + CYCLE_US;
  nextCycleUs = t0u;
  nextImuUs = t0u + IMU_US / 2;  // stagger IMU vs baro tick
}

void loop() {
  // Meta-on-attach (t002/t003 lesson: delay 2.5 s past the logger's flush)
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
  // tight loop, no delay(): timing is deadline-based
}
