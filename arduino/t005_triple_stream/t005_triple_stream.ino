/*
 * t005_triple_stream.ino — R-1 bench set (Phase A): three MS5611s streaming.
 *
 * Purpose: clone-quality statistics + spatial decorrelation evidence.
 *   - Per-unit noise floor across all three GY-63s -> which physical unit
 *     is the "best single sensor" (research ranks that above dual averaging).
 *   - Full 3x3 noise correlation matrix in the shared chamber.
 *   - With GY-63 #3 moved OUT of the enclosure: does corr drop below the
 *     +0.65 measured for two units in one chamber (T-003)? If yes, port
 *     placement matters; if no, that's settled for good.
 *
 *   - Baro A: GY-63 #1 on Bus A (Wire,   GPIO4/5) @ 0x76 -> sid=0
 *   - Baro B: GY-63 #2 on Bus B (Wire1,  GPIO6/7) @ 0x77 -> sid=1
 *   - Baro C: GY-63 #3 on Bus C (bit-bang GPIO15/16) -> sid=2
 *             Address probed 0x77 then 0x76 (clone CSB state unknown for #3);
 *             it is alone on its bus so either address works. The discovered
 *             address is reported in the health check and #C line.
 *
 * Timing: same lockstep scheme as t003 — one 20 ms tick, ONE conversion
 * type started on ALL THREE sensors back-to-back, all read 10 ms later,
 * three frames emitted. 45 Hz P + 5 Hz T PER sensor, ~150 lines/s total.
 * Bus C is bit-banged at ~100 kHz (onboard GY-63 pull-ups): one full
 * conversion-start + 3-byte ADC read costs ~1.5 ms, comfortably inside
 * the 20 ms tick.
 *
 * No IMU streaming in this build — same rationale as t003 (baro-only study,
 * fewer variables; the MPU is still health-checked at boot).
 *
 * Meta-on-attach: #H/#K/#C are re-emitted whenever a new host session
 * attaches (CDC open does not reset the S3 — see t002/t003 history).
 *
 * After flashing, capture per docs/phase_a_capture_checklist.md, then:
 *   python ../analysis/03_dual_sensor_compare.py '*t005_static*'
 *   python ../analysis/03_dual_sensor_compare.py '*t005_spatial*'
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
static const uint8_t ADDR_MPU_A  = 0x69;   // health-check only in this build
static const int SID_A = 0;                // protocol: sid 0 = Bus A
static const int SID_B = 1;                // protocol: sid 1 = Bus B
static const int SID_C = 2;                // protocol: sid 2 = Bus C (soft)

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

static bool hostSeen = false;

static inline uint64_t nowUs() { return (uint64_t)esp_timer_get_time(); }

static void emitError(uint64_t t, uint8_t code) {
  Serial.printf("E,%lu,%llu,%u\n", (unsigned long)seq++, (unsigned long long)t, code);
}

// ============================================================================
// Bit-banged I2C for Bus C (proven in i2c_scan_test / T-000).
// Open-drain emulation: drive LOW, or release and rely on the module's
// onboard pull-ups. ~100 kHz (10 us per bit incl. half-period margins).
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

// Clock out 8 bits, then read the ACK bit. Returns true if ACKed.
static bool bbWriteByte(uint8_t byte) {
  for (int i = 7; i >= 0; i--) {
    if (byte & (1 << i)) bbRelease(BUSC_SDA); else bbLow(BUSC_SDA);
    delayMicroseconds(5);
    bbRelease(BUSC_SCL);
    delayMicroseconds(5);
    bbLow(BUSC_SCL);
    delayMicroseconds(5);
  }
  bbRelease(BUSC_SDA);            // release SDA for the ACK bit
  delayMicroseconds(5);
  bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bool ack = !bbRead(BUSC_SDA);   // ACK = SDA pulled low by slave
  bbLow(BUSC_SCL);
  delayMicroseconds(5);
  return ack;
}

// Read 8 bits; ackMore=true sends ACK (more bytes coming), else NACK.
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
  if (ackMore) bbLow(BUSC_SDA); else bbRelease(BUSC_SDA);   // ACK / NACK
  delayMicroseconds(5);
  bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bbLow(BUSC_SCL);
  delayMicroseconds(5);
  return v;
}

// Write one register/command byte (start, addr+W, reg, stop).
static bool bbWriteReg(uint8_t addr, uint8_t reg) {
  bbStartCond();
  if (!bbWriteByte(addr << 1)) { bbStop(); return false; }
  bool ok = bbWriteByte(reg);
  bbStop();
  return ok;
}

// Write reg, then read n bytes (start, addr+W, reg, stop, start, addr+R, data).
// Stop-then-start works on the MS5611: the command is registered on write
// and the ADC result is read back with the 0x00 read command afterwards.
static bool bbReadBytes(uint8_t addr, uint8_t reg, uint8_t *dst, int n) {
  if (!bbWriteReg(addr, reg)) return false;
  bbStartCond();
  if (!bbWriteByte((addr << 1) | 1)) { bbStop(); return false; }
  for (int i = 0; i < n; i++) dst[i] = bbReadByte(i < n - 1);
  bbStop();
  return true;
}

// ============================================================================
// Sensor-generic bus ops (hardware bus OR bit-banged bus)
// ============================================================================

static bool probeAck(TwoWire &w, uint8_t addr) {
  w.beginTransmission(addr);
  return w.endTransmission() == 0;
}

// ACK probe on the bit-banged bus: just the address phase.
static bool bbProbe(uint8_t addr) {
  bbStartCond();
  bool ack = bbWriteByte(addr << 1);
  bbStop();
  return ack;
}

// I2C bus recovery: if a slave was left mid-transaction (the ESP can reset
// while bit-banging — every re-flash does this), it may hold SDA low and
// ignore the bus until clocked out. Its 3V3 rail stays up across EN resets,
// so it stays stuck across reboots and every scan then finds "nothing".
// Standard fix: release SDA, clock SCL 9x, issue a stop.
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
    buf[0] = b.hw->read();   // same no-chained-read rule as above
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

// Start ONE conversion on ONE sensor.
static bool convStart(Baro &b, bool temp) {
  uint8_t cmd = temp ? MS5611_CONV_TEMP : MS5611_CONV_PRESS;
  if (b.hw) {
    b.hw->beginTransmission(b.addr);
    b.hw->write(cmd);
    return b.hw->endTransmission() == 0;
  }
  return bbWriteReg(b.addr, cmd);
}

// Read all 8 PROM words of one barometer into b.prom. Returns false on failure.
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
// Meta frames
// ============================================================================

static void printLegend() {
  Serial.printf("#,================= what you are about to see =================\n");
  Serial.printf("#,HEALTH CHECK first — one line per sensor, expect status=ok:\n");
  Serial.printf("#,  #C,dev=a0,...,addr=0x76,...  (Bus A baro, sid=0)\n");
  Serial.printf("#,  #C,dev=a1,...,addr=0x69,...  (Bus A IMU — checked, not streamed)\n");
  Serial.printf("#,  #C,dev=b1,...,addr=0x77,...  (Bus B baro, sid=1)\n");
  Serial.printf("#,  #C,dev=c1,...,addr=0x??,...  (Bus C baro, sid=2 — addr PROBED)\n");
  Serial.printf("#,  #C,health=ok (3 sids) or health=degraded (2 sids —\n");
  Serial.printf("#,    the dead one is skipped, sensors= in #C says which)\n");
  Serial.printf("#,THEN: THREE #K lines, one per barometer (sid 0, 1, 2) — keep them.\n");
  Serial.printf("#,DATA FRAMES — three per tick, one from each sensor:\n");
  Serial.printf("#,  P,<seq>,<t_us>,<sid>,<d1>  raw pressure ADC 24-bit, sid 0/1/2\n");
  Serial.printf("#,    Same pressure, three independent readings. The DIFFERENCES\n");
  Serial.printf("#,    between sids = independent noise (clone quality, R-1);\n");
  Serial.printf("#,    the pairwise correlations = how much noise is shared\n");
  Serial.printf("#,    (chamber/common-mode, T-003 vs spatial-decorrelation).\n");
  Serial.printf("#,  T,<seq>,<t_us>,<sid>,<d2>  temperature ADC, all sids\n");
  Serial.printf("#,  E,<seq>,<t_us>,<code>  ERROR (1=NAK 2=timeout 3=overflow).\n");
  Serial.printf("#,=============================================================\n");
}

static void emitHeader(bool full) {
  Serial.printf("#H,vario-bench-t005,0.5.3\n");
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
  Serial.printf("#C,osr=4096,p_hz=45,t_hz=5,sensors=%d,imu=off,"
                "c_addr=0x%02X,c_status=%s\n", nOK, baros[2].addr,
                baros[2].ok ? "ok" : "missing");
}

// ============================================================================
// Health check — streaming requires AT LEAST TWO barometers alive.
// All three -> health=ok; two -> health=degraded (the missing sid is simply
// absent from the stream; #C sensors= reports the truth). This keeps the
// session productive if GY-63 #3 (bus C) stays dark — the spatial test
// works with two units. The MPU is checked for completeness (state of the
// bench) but not streamed and never blocks.
// ============================================================================

static bool healthCheck() {
  int baroMissing = 0, otherMissing = 0;

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
    bool alive = (who == 0x68);
    Serial.printf("#C,dev=a1,type=mpu6050,addr=0x%02X,whoami=0x%02X,status=%s\n",
                  ADDR_MPU_A, who, alive ? "ok" : "bad_id");
    if (!alive) otherMissing++;   // not streamed — report but don't block
  } else {
    Serial.printf("#C,dev=a1,type=mpu6050,addr=0x%02X,status=missing\n", ADDR_MPU_A);
    otherMissing++;
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

  // Bus C: probe 0x77 then 0x76 (clone #3's CSB state is unknown — it is
  // alone on its own bus, so either address is usable; we just report it).
  // A fresh MS5611 may not ACK for a while after power-up (t000's scanner
  // only works because scanning addr 1..126 spends ~hundreds of ms first),
  // so retry each address once after a settle delay before giving up.
  // First: bus recovery — a slave left mid-transaction by an earlier reset
  // holds SDA low and NAKs everything until clocked out.
  bbBusRecover();
  uint8_t cAddr = 0;
  for (int attempt = 0; attempt < 2 && !cAddr; attempt++) {
    for (uint8_t cand : {0x77, 0x76}) {
      if (bbProbe(cand)) { cAddr = cand; break; }
    }
    if (!cAddr) delay(150);
  }
  baros[2].addr = cAddr ? cAddr : 0x77;   // nominal for the error line
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
  Serial.printf("#C,health=%s,missing=%d\n", hs, baroMissing + otherMissing);
  return baroMissing <= 1;
}

// ============================================================================
// Triple barometer sampling (lockstep)
// ============================================================================

static void startConversion(bool temp) {
  uint64_t t = nowUs();
  for (int i = 0; i < 3; i++) {
    if (!baros[i].ok) continue;              // degraded mode: skip dead sid
    if (!convStart(baros[i], temp)) emitError(t, 1);
  }
  convertingTemp = temp;
  convDeadlineUs = t + CONV_US;
  phase = CONVERTING;
}

static void finishConversion() {
  uint64_t t = nowUs();
  for (int i = 0; i < 3; i++) {
    if (!baros[i].ok) continue;              // degraded mode: skip dead sid
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
  // Bus C pins start released (INPUT_PULLUP) — bit-bang drives them per-op.

  // Power/I2C settle before touching anything: a fresh MS5611 can ignore
  // its first I2C transactions for a while after power-up (this is why the
  // t000 scanner, which spends ~hundreds of ms scanning low addresses
  // first, sees bus C fine). t005 used to probe within ms of boot.
  delay(300);

  emitHeader(true);

  if (!healthCheck()) {
    emitError(nowUs(), 1);
    Serial.printf("#C,status=baro_init_failed\n");
    return;
  }

  bool okProm = true;
  for (int i = 0; i < 3; i++) {
    if (!baros[i].ok) continue;              // degraded mode: skip dead sid
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
