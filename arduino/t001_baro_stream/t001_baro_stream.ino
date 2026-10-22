/*
 * t001_baro_stream.ino — T-001: one MS5611 (GY-63) @ OSR4096, protocol v1.
 *
 * HISTORICAL BASELINE — superseded by t002_baro_imu_stream (which adds the
 * IMU and meta-on-attach). Known limitation: meta frames print once at boot
 * only, so a logger attaching later loses #H/#K/#C. Kept for reference and
 * for baro-only re-runs; if you capture with it, patch prom_1 into the
 * sidecar afterwards.
 *
 *
 * Bench rig test per firmware/README.md bring-up order. Streams raw 24-bit
 * pressure (P) and temperature (T) frames from the Bus B barometer over
 * USB-CDC @ 921600. No compensation, no filtering — offline analysis does that.
 *
 * Startup sequence:
 *   1. A human-readable legend (every line starts with '#' -> the logger
 *      treats it as metadata, so it's safe to print).
 *   2. Health check: every expected device on every bus is probed (ACK + ID
 *      register) BEFORE streaming; results are #C key=value lines that
 *      capture.py stores in the run's JSON sidecar — every capture is
 *      self-documenting about what was on the bench.
 *   3. #K calibration dump, #C config, then the P/T stream.
 *
 * As-built addressing (from the 2026-10-21 bring-up scan, NOT the schematic):
 *   - Bus A (Wire,  GPIO4/5):  GY-63 @ 0x76 (CSB pulled low on that clone)
 *                              MPU6050 @ 0x69 (AD0 tied to 3V3)
 *   - Bus B (Wire1, GPIO6/7):  GY-63 @ 0x77  <- barometer under test, sid=1
 *   - Bus C (GPIO15/16):       optional GY-63 #3, not wired yet
 *
 * Sampling pattern (MS5611 OSR4096 conversion ~= 9.04 ms typ):
 *   20 ms cycle tick -> start one conversion, read it 10.0 ms later
 *   (spec max conversion time ~10 ms; 10 ms read point still fits the 20 ms
 *   cycle, so rates are unchanged).
 *   Every 10th cycle is a temperature conversion instead of pressure.
 *   Effective rates: P ~= 45 Hz, T = 5 Hz. Recorded honestly in the #C line.
 *
 * After flashing, log with:
 *   python ../tools/capture.py --auto --label t001_bench_60s --duration 60
 * then:
 *   python ../analysis/01_noise_floor.py '*t001*'
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

// ---- MS5611 / MPU6050 registers ---------------------------------------------
static const uint8_t MS5611_RESET      = 0x1E;
static const uint8_t MS5611_ADC_READ   = 0x00;
static const uint8_t MS5611_CONV_PRESS = 0x48;  // D1, OSR4096
static const uint8_t MS5611_CONV_TEMP  = 0x58;  // D2, OSR4096
static const uint8_t MPU_WHO_AM_I      = 0x75;

static const uint32_t CONV_US  = 10000;  // 9.04 ms typ, ~10 ms spec max
static const uint32_t CYCLE_US = 20000;  // 50 Hz tick

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

static inline uint64_t nowUs() { return (uint64_t)esp_timer_get_time(); }

static void emitError(uint64_t t, uint8_t code) {
  Serial.printf("E,%lu,%llu,%u\n", (unsigned long)seq++, (unsigned long long)t, code);
}

// ============================================================================
// Startup legend — human-readable "what to expect", safe for the logger
// (every line starts with '#' -> capture.py stores it as metadata, not data)
// ============================================================================

static void printLegend() {
  Serial.printf("#,================= what you are about to see =================\n");
  Serial.printf("#,HEALTH CHECK first — one line per sensor, expect status=ok:\n");
  Serial.printf("#,  #C,dev=a0,type=ms5611,addr=0x76,...  (Bus A baro, CSB-low clone)\n");
  Serial.printf("#,  #C,dev=a1,type=mpu6050,addr=0x69,... (Bus A IMU, AD0 high)\n");
  Serial.printf("#,  #C,dev=b1,type=ms5611,addr=0x77,...  (Bus B baro = unit under test)\n");
  Serial.printf("#,  #C,health=ok,missing=0   <- stream starts ONLY if this says ok\n");
  Serial.printf("#,THEN:\n");
  Serial.printf("#,  #K = factory calibration words of the streaming barometer.\n");
  Serial.printf("#,       Offline compensation NEEDS these — never delete a capture.\n");
  Serial.printf("#,  #C,osr=... = the real rates this firmware achieves.\n");
  Serial.printf("#,DATA FRAMES after that:\n");
  Serial.printf("#,  P,<seq>,<t_us>,<sid>,<d1>  raw pressure ADC, 24-bit.\n");
  Serial.printf("#,    Expect ~7.9M at bench level (972 hPa). d1 UP = pressure UP =\n");
  Serial.printf("#,    altitude DOWN. Adjacent-frame wiggle = sensor noise = what\n");
  Serial.printf("#,    T-001 measures. Slow drift = sensor warm-up, normal.\n");
  Serial.printf("#,  T,<seq>,<t_us>,<sid>,<d2>  raw temperature ADC, 24-bit.\n");
  Serial.printf("#,    Expect ~8.2M near 22 degC.\n");
  Serial.printf("#,  E,<seq>,<t_us>,<code>  ERROR (1=NAK 2=timeout 3=overflow).\n");
  Serial.printf("#,    None expected; any E line means check wiring/power.\n");
  Serial.printf("#,NOTES: t_us = microseconds since boot. seq counts every line;\n");
  Serial.printf("#,a seq gap = dropped sample. sid=1 means Bus B sensor.\n");
  Serial.printf("#,=============================================================\n");
}

// ============================================================================
// Health check — run once at boot, before anything streams
// ============================================================================

static bool probeAck(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  return w.endTransmission() == 0;
}

// Returns PROM word 0 (reserved/factory word) or 0xFFFF on failure.
static uint16_t ms5611Prom0(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  w.write(0xA0);
  if (w.endTransmission(false) != 0) return 0xFFFF;
  if (w.requestFrom(addr, (uint8_t)2) != 2) return 0xFFFF;
  uint8_t hi = w.read();   // read into locals: operand evaluation order of
  uint8_t lo = w.read();   // '|' is unspecified — don't chain read() calls
  return (uint16_t)((hi << 8) | lo);
}

// Returns WHO_AM_I byte or 0xFF on failure.
static uint8_t mpuWhoAmI(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  w.write(MPU_WHO_AM_I);
  if (w.endTransmission(false) != 0) return 0xFF;
  if (w.requestFrom(addr, (uint8_t)1) != 1) return 0xFF;
  return w.read();
}

// Emits one #C line per device plus a summary. Returns false if the
// barometer under test is missing — in that case streaming must not start.
static bool healthCheck() {
  int missing = 0;

  // --- Bus A: GY-63 #1 ---
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

  // --- Bus A: MPU6050 ---
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

  // --- Bus B: GY-63 #2 — the unit under test ---
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
// Sampling
// ============================================================================

// Read a 24-bit ADC result from the Bus B barometer. Returns false on NAK.
static bool readADC24(uint32_t &val) {
  Wire1.beginTransmission(ADDR_BARO_B);
  Wire1.write(MS5611_ADC_READ);
  if (Wire1.endTransmission(false) != 0) return false;
  if (Wire1.requestFrom(ADDR_BARO_B, (uint8_t)3) != 3) return false;
  uint8_t b0 = Wire1.read();  // locals, not chained calls (see ms5611Prom0)
  uint8_t b1 = Wire1.read();
  uint8_t b2 = Wire1.read();
  val = ((uint32_t)b0 << 16) | ((uint32_t)b1 << 8) | b2;
  return true;
}

static void startConversion(bool temp) {
  Wire1.beginTransmission(ADDR_BARO_B);
  Wire1.write(temp ? MS5611_CONV_TEMP : MS5611_CONV_PRESS);
  if (Wire1.endTransmission() != 0) {
    emitError(nowUs(), 1);          // NAK — device missing
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
  uint64_t t = nowUs();  // timestamp at the moment the sample was read
  if (convertingTemp)
    Serial.printf("T,%lu,%llu,%d,%lu\n", (unsigned long)seq++,
                  (unsigned long long)t, BARO_SID, (unsigned long)raw);
  else
    Serial.printf("P,%lu,%llu,%d,%lu\n", (unsigned long)seq++,
                  (unsigned long long)t, BARO_SID, (unsigned long)raw);
  phase = IDLE;
}

// ============================================================================
// Setup / loop
// ============================================================================

void setup() {
  Serial.begin(921600);
  // Meta frames (#H, legend, health, #K) must outlive capture.py's port-settle
  // sleep + input flush, or the logger swallows them and runs lose calibration.
  // 3.5 s is comfortably beyond that window.
  delay(3500);

  Wire.begin(BUSA_SDA, BUSA_SCL);
  Wire.setClock(400000);
  Wire.setTimeout(50);
  Wire1.begin(BUSB_SDA, BUSB_SCL);
  Wire1.setClock(400000);   // conversions dominate timing, 400k keeps reads snappy
  Wire1.setTimeout(50);     // ms; too-long stalls become E-lines, not hangs

  Serial.printf("#H,vario-bench-t001,0.1.3\n");
  printLegend();

  // ---- Health check: verify the whole rig before streaming ----
  if (!healthCheck()) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=baro_init_failed\n");
    return;
  }

  // Reset + PROM read of the barometer under test
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
      uint8_t hi = Wire1.read();  // locals again, same reason
      uint8_t lo = Wire1.read();
      prom[i] = (uint16_t)((hi << 8) | lo);
    }
  }

  if (!baroOK) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=prom_read_failed\n");
    return;
  }

  // #K carries the six factory calibration words (PROM words 1..6) — the
  // offline compensator needs these.
  Serial.printf("#K,%d,%u,%u,%u,%u,%u,%u\n", BARO_SID,
                prom[1], prom[2], prom[3], prom[4], prom[5], prom[6]);
  Serial.printf("#C,osr=4096,p_hz=45,t_hz=5,imu=off\n");

  nextCycleUs = nowUs() + CYCLE_US;
}

void loop() {
  if (!baroOK) return;

  uint64_t t = nowUs();

  if (phase == CONVERTING) {
    if ((int64_t)(t - convDeadlineUs) >= 0) finishConversion();
  } else if ((int64_t)(t - nextCycleUs) >= 0) {
    // 1 temperature conversion in every 10 cycles, pressure otherwise
    bool doTemp = (cycleCount % 10 == 9);
    cycleCount++;
    nextCycleUs += CYCLE_US;
    startConversion(doTemp);
  }
  // tight loop, no delay(): timing is deadline-based
}
