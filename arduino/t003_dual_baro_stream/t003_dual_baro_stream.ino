/*
 * t003_dual_baro_stream.ino — T-003: two MS5611s streaming simultaneously.
 *
 * The ADR-002 evidence test: do two independent barometers averaged together
 * beat one? Analysis: ../analysis/03_dual_sensor_compare.py
 *
 *   - Baro A: GY-63 #1 on Bus A (Wire,  GPIO4/5) @ 0x76 -> sid=0
 *   - Baro B: GY-63 #2 on Bus B (Wire1, GPIO6/7) @ 0x77 -> sid=1
 *
 * Both sensors run in lockstep on one 20 ms tick: at each tick ONE conversion
 * type is started on BOTH buses back-to-back (two quick I2C writes), both are
 * read 10 ms later, and two frames are emitted. Every 10th tick is a
 * temperature conversion for both. Result: 45 Hz P + 5 Hz T PER sensor,
 * ~100 lines/s total. The conversions happen in parallel on two separate
 * hardware I2C peripherals, so doubling the sensors does NOT halve the rate.
 *
 * No IMU streaming in this build — it's a barometer-only study (fewer
 * variables; the MPU is still health-checked at boot). The Bus C / GY-63 #3
 * (bit-banged) variant from the test plan is not needed for ADR-002; two
 * sids already answer the dual-vs-single question.
 *
 * Meta-on-attach: #H/#K/#C are re-emitted whenever a new host session
 * attaches (CDC open does not reset the S3 — see t002 history).
 *
 * After flashing, log with:
 *   python ../tools/capture.py --auto --label t003_dual_60s --duration 60
 * then:
 *   python ../analysis/03_dual_sensor_compare.py '*t003*'
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
static const uint8_t ADDR_BARO_B = 0x77;   // GY-63 #2
static const uint8_t ADDR_MPU_A  = 0x69;   // health-check only in this build
static const int SID_A = 0;                // protocol: sid 0 = Bus A
static const int SID_B = 1;                // protocol: sid 1 = Bus B

// ---- MS5611 registers --------------------------------------------------------
static const uint8_t MS5611_RESET      = 0x1E;
static const uint8_t MS5611_ADC_READ   = 0x00;
static const uint8_t MS5611_CONV_PRESS = 0x48;  // D1, OSR4096
static const uint8_t MS5611_CONV_TEMP  = 0x58;  // D2, OSR4096
static const uint8_t MPU_WHO_AM_I      = 0x75;

static const uint32_t CONV_US  = 10000;  // 9.04 ms typ, ~10 ms max
static const uint32_t CYCLE_US = 20000;  // tick: 45 Hz P + 5 Hz T per sensor

// ---- Protocol state ---------------------------------------------------------
static uint32_t seq = 0;
static uint16_t promA[8], promB[8];

enum Phase { IDLE, CONVERTING };
static Phase phase = IDLE;
static bool convertingTemp = false;
static uint64_t convDeadlineUs = 0;
static uint64_t nextCycleUs = 0;
static uint32_t cycleCount = 0;
static bool baroOK = false;

static bool hostSeen = false;

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
  Serial.printf("#,  #C,dev=a0,...,addr=0x76,...  (Bus A baro, sid=0)\n");
  Serial.printf("#,  #C,dev=a1,...,addr=0x69,...  (Bus A IMU — checked, not streamed)\n");
  Serial.printf("#,  #C,dev=b1,...,addr=0x77,...  (Bus B baro, sid=1)\n");
  Serial.printf("#,  #C,health=ok,missing=0   <- stream starts ONLY if this says ok\n");
  Serial.printf("#,THEN: TWO #K lines, one per barometer (sid 0 and sid 1) — keep them.\n");
  Serial.printf("#,DATA FRAMES — two per tick, one from each sensor:\n");
  Serial.printf("#,  P,<seq>,<t_us>,0,<d1>  Bus A raw pressure ADC 24-bit\n");
  Serial.printf("#,  P,<seq>,<t_us>,1,<d1>  Bus B raw pressure ADC 24-bit\n");
  Serial.printf("#,    Same pressure, two independent readings. The DIFFERENCE\n");
  Serial.printf("#,    between sids = independent noise (what T-003 measures);\n");
  Serial.printf("#,    the COMMON part = real pressure + shared environment.\n");
  Serial.printf("#,  T,<seq>,<t_us>,<sid>,<d2>  temperature ADC, both sids\n");
  Serial.printf("#,  E,<seq>,<t_us>,<code>  ERROR (1=NAK 2=timeout 3=overflow).\n");
  Serial.printf("#,=============================================================\n");
}

static void emitHeader(bool full) {
  Serial.printf("#H,vario-bench-t003,0.3.1\n");
  if (full) printLegend();
}

static void emitConfig() {
  if (!baroOK) {
    Serial.printf("#C,status=fault_no_stream\n");
    return;
  }
  Serial.printf("#K,%d,%u,%u,%u,%u,%u,%u\n", SID_A,
                promA[1], promA[2], promA[3], promA[4], promA[5], promA[6]);
  Serial.printf("#K,%d,%u,%u,%u,%u,%u,%u\n", SID_B,
                promB[1], promB[2], promB[3], promB[4], promB[5], promB[6]);
  Serial.printf("#C,osr=4096,p_hz=45,t_hz=5,sensors=2,imu=off\n");
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

// Health-checks the whole rig; streaming requires BOTH barometers alive.
// The MPU is checked for completeness (state of the bench) but not streamed.
static bool healthCheck() {
  int missing = 0;
  bool baroAOK = false, baroBOK = false;

  if (probeAck(Wire, ADDR_BARO_A)) {
    uint16_t p0 = ms5611Prom0(Wire, ADDR_BARO_A);
    baroAOK = (p0 != 0x0000 && p0 != 0xFFFF);
    Serial.printf("#C,dev=a0,type=ms5611,addr=0x%02X,prom0=0x%04X,status=%s\n",
                  ADDR_BARO_A, p0, baroAOK ? "ok" : "bad_id");
  } else {
    Serial.printf("#C,dev=a0,type=ms5611,addr=0x%02X,status=missing\n", ADDR_BARO_A);
  }

  if (probeAck(Wire, ADDR_MPU_A)) {
    uint8_t who = mpuWhoAmI(Wire, ADDR_MPU_A);
    bool alive = (who == 0x68);
    Serial.printf("#C,dev=a1,type=mpu6050,addr=0x%02X,whoami=0x%02X,status=%s\n",
                  ADDR_MPU_A, who, alive ? "ok" : "bad_id");
    if (!alive) missing++;   // not streamed — report but don't block
  } else {
    Serial.printf("#C,dev=a1,type=mpu6050,addr=0x%02X,status=missing\n", ADDR_MPU_A);
    missing++;
  }

  if (probeAck(Wire1, ADDR_BARO_B)) {
    uint16_t p0 = ms5611Prom0(Wire1, ADDR_BARO_B);
    baroBOK = (p0 != 0x0000 && p0 != 0xFFFF);
    Serial.printf("#C,dev=b1,type=ms5611,addr=0x%02X,prom0=0x%04X,status=%s\n",
                  ADDR_BARO_B, p0, baroBOK ? "ok" : "bad_id");
  } else {
    Serial.printf("#C,dev=b1,type=ms5611,addr=0x%02X,status=missing\n", ADDR_BARO_B);
  }

  if (!baroAOK) missing++;
  if (!baroBOK) missing++;
  Serial.printf("#C,health=%s,missing=%d\n", (baroAOK && baroBOK) ? "ok" : "fail",
                missing);
  return baroAOK && baroBOK;
}

// ============================================================================
// Dual barometer sampling (lockstep)
// ============================================================================

static bool readADC24(TwoWire &w, uint8_t addr, uint32_t &val) {
  w.beginTransmission(addr);
  w.write(MS5611_ADC_READ);
  if (w.endTransmission(false) != 0) return false;
  if (w.requestFrom(addr, (uint8_t)3) != 3) return false;
  uint8_t b0 = w.read();
  uint8_t b1 = w.read();
  uint8_t b2 = w.read();
  val = ((uint32_t)b0 << 16) | ((uint32_t)b1 << 8) | b2;
  return true;
}

// Start the SAME conversion type on both sensors back-to-back; they then
// convert in parallel on their own buses.
static void startConversion(bool temp) {
  uint8_t cmd = temp ? MS5611_CONV_TEMP : MS5611_CONV_PRESS;
  Wire.beginTransmission(ADDR_BARO_A);
  Wire.write(cmd);
  bool okA = (Wire.endTransmission() == 0);
  Wire1.beginTransmission(ADDR_BARO_B);
  Wire1.write(cmd);
  bool okB = (Wire1.endTransmission() == 0);
  uint64_t t = nowUs();
  if (!okA) emitError(t, 1);
  if (!okB) emitError(t, 1);
  convertingTemp = temp;
  convDeadlineUs = t + CONV_US;
  phase = CONVERTING;
}

static void finishConversion() {
  uint32_t rawA = 0, rawB = 0;
  bool okA = readADC24(Wire, ADDR_BARO_A, rawA);
  bool okB = readADC24(Wire1, ADDR_BARO_B, rawB);
  uint64_t t = nowUs();
  if (convertingTemp) {
    if (okA) Serial.printf("T,%lu,%llu,%d,%lu\n", (unsigned long)seq++,
                           (unsigned long long)t, SID_A, (unsigned long)rawA);
    else     emitError(t, 1);
    if (okB) Serial.printf("T,%lu,%llu,%d,%lu\n", (unsigned long)seq++,
                           (unsigned long long)t, SID_B, (unsigned long)rawB);
    else     emitError(t, 1);
  } else {
    if (okA) Serial.printf("P,%lu,%llu,%d,%lu\n", (unsigned long)seq++,
                           (unsigned long long)t, SID_A, (unsigned long)rawA);
    else     emitError(t, 1);
    if (okB) Serial.printf("P,%lu,%llu,%d,%lu\n", (unsigned long)seq++,
                           (unsigned long long)t, SID_B, (unsigned long)rawB);
    else     emitError(t, 1);
  }
  phase = IDLE;
}

// Read all 8 PROM words of one barometer into dst[]. Returns false on failure.
static bool readProm(TwoWire &w, uint8_t addr, uint16_t dst[8]) {
  w.beginTransmission(addr);
  w.write(MS5611_RESET);
  if (w.endTransmission() != 0) return false;
  delay(3);
  for (int i = 0; i < 8; i++) {
    w.beginTransmission(addr);
    w.write(0xA0 + 2 * i);
    if (w.endTransmission(false) != 0 || w.requestFrom(addr, (uint8_t)2) != 2)
      return false;
    uint8_t hi = w.read();
    uint8_t lo = w.read();
    dst[i] = (uint16_t)((hi << 8) | lo);
  }
  return true;
}

// ============================================================================
// Setup / loop
// ============================================================================

void setup() {
  Serial.begin(921600);

  // Wait for a host (max 5 s) + CDC settle, so boot meta survives the
  // logger's port-open input flush.
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

  bool okA = readProm(Wire, ADDR_BARO_A, promA);
  bool okB = readProm(Wire1, ADDR_BARO_B, promB);
  baroOK = okA && okB;
  if (!baroOK) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=prom_read_failed,a=%d,b=%d\n", okA, okB);
    return;
  }

  emitConfig();

  nextCycleUs = nowUs() + CYCLE_US;
}

void loop() {
  // Meta-on-attach: a new host session (capture.py opening the port) gets
  // #H/#K/#C re-emitted — but DELAYED 2.5 s, because capture.py flushes its
  // input buffer ~2 s after port open; an immediate emit lands inside that
  // flush and is lost (learned on the first t003 capture). At t+2.5 s the
  // logger is reading, so the meta is captured.
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
  // tight loop, no delay(): timing is deadline-based
}
