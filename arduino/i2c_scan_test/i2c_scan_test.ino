/*
 * i2c_scan_test.ino — T-000 wiring bring-up for the Vario USB bench rig.
 *
 * Scans all three I2C buses and identifies what answers:
 *
 *   Bus A (Wire,  hw I2C0): SDA=GPIO4  SCL=GPIO5  -> MS5611 #1 (0x77) + MPU6050 (0x68)
 *   Bus B (Wire1, hw I2C1): SDA=GPIO6  SCL=GPIO7  -> MS5611 #2 (0x77)
 *   Bus C (bit-bang):       SDA=GPIO15 SCL=GPIO16 -> MS5611 #3 (0x77, optional)
 *
 * Expected result per docs/test_rig_schematic.md §6:
 *   0x77 on A and B (and C if wired), 0x68 on A.
 * If any GY-63 answers at 0x76, its CSB is pulled low on that clone board.
 *
 * After the scan, a quick ID sanity check runs:
 *   - MPU6050: WHO_AM_I (reg 0x75) must read 0x68 (0x69 if AD0 tied high)
 *   - MS5611:  PROM word 0 (reg 0xA0) — factory value is typically 0x0Fxx-ish,
 *              reading anything non-0x0000/non-0xFFFF means the chip is alive.
 *
 * Board: ESP32-S3-DevKitC-1, Arduino core (esp32 by Espressif).
 * Serial: USB-CDC @ 115200.
 */

#include <Arduino.h>
#include <Wire.h>

// ---- Pin map (from docs/test_rig_schematic.md §2) --------------------------
static const int BUSA_SDA = 4;
static const int BUSA_SCL = 5;
static const int BUSB_SDA = 6;
static const int BUSB_SCL = 7;
static const int BUSC_SDA = 15;   // bit-banged
static const int BUSC_SCL = 16;   // bit-banged

// ---- Known addresses on this rig -------------------------------------------
static const uint8_t MS5611_ADDR = 0x77;  // might be 0x76 on some clones
static const uint8_t MPU6050_ADDR = 0x68; // 0x69 if AD0 -> 3V3

// ---------------------------------------------------------------------------
void scanBus(TwoWire &w, const char *name) {
  Serial.printf("--- Scanning %s ---\n", name);
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    w.beginTransmission(addr);
    if (w.endTransmission() == 0) {
      Serial.printf("  0x%02X", addr);
      if (addr == MS5611_ADDR) Serial.print("  (MS5611 / GY-63 barometer)");
      if (addr == MPU6050_ADDR || addr == 0x69)
        Serial.printf("  (MPU6050 IMU, AD0=%s)", addr == 0x68 ? "GND" : "3V3");
      Serial.println();
      found++;
      delay(5);
    }
  }
  if (!found) Serial.println("  (nothing found)");
  Serial.println();
}

// --- Minimal bit-banged I2C scanner for Bus C (no library needed) -----------
// Open-drain emulation: drive LOW, or release and rely on the module's
// onboard pull-ups.

static inline void bbRelease(int pin) { pinMode(pin, INPUT_PULLUP); }
static inline void bbLow(int pin)     { pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
static inline bool bbRead(int pin)    { return digitalRead(pin); }

static void bbStart() {
  bbRelease(BUSC_SDA); bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bbLow(BUSC_SDA);
  delayMicroseconds(5);
  bbLow(BUSC_SCL);
}

static void bbStop() {
  bbLow(BUSC_SDA);
  delayMicroseconds(5);
  bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bbRelease(BUSC_SDA);
}

// Clock out 8 bits, then read ACK. Returns true if ACKed.
static bool bbWriteAddr(uint8_t addr7, bool readBit) {
  uint8_t byte = (addr7 << 1) | (readBit ? 1 : 0);
  for (int i = 7; i >= 0; i--) {
    if (byte & (1 << i)) bbRelease(BUSC_SDA); else bbLow(BUSC_SDA);
    delayMicroseconds(5);
    bbRelease(BUSC_SCL);
    delayMicroseconds(5);
    bbLow(BUSC_SCL);
    delayMicroseconds(5);
  }
  bbRelease(BUSC_SDA);          // release SDA for the ACK bit
  delayMicroseconds(5);
  bbRelease(BUSC_SCL);
  delayMicroseconds(5);
  bool ack = !bbRead(BUSC_SDA); // ACK = SDA pulled low by slave
  bbLow(BUSC_SCL);
  bbStop();
  return ack;
}

void scanBusC() {
  Serial.println("--- Scanning Bus C (bit-banged, GPIO15/16) ---");
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    bbStart();
    if (bbWriteAddr(addr, false)) {
      Serial.printf("  0x%02X", addr);
      if (addr == MS5611_ADDR) Serial.print("  (MS5611 / GY-63 barometer)");
      Serial.println();
      found++;
      delay(5);
    }
  }
  if (!found) Serial.println("  (nothing found — GY-63 #3 not wired? that's OK, it's optional)");
  Serial.println();
}

// ---------------------------------------------------------------------------
// Quick "is it really alive" checks
// ---------------------------------------------------------------------------

void checkMPU6050(TwoWire &w) {
  uint8_t addr = 0;
  // WHO_AM_I (reg 0x75) exists at both 0x68 and 0x69; probe both.
  for (uint8_t cand : {0x68, 0x69}) {
    w.beginTransmission(cand);
    w.write(0x75);
    if (w.endTransmission(false) == 0 && w.requestFrom(cand, (uint8_t)1) == 1) {
      addr = cand;
      break;
    }
  }
  if (!addr) { Serial.println("MPU6050: NOT FOUND"); return; }

  w.beginTransmission(addr);
  w.write(0x75);
  w.endTransmission(false);
  w.requestFrom(addr, (uint8_t)1);
  uint8_t who = w.read();

  Serial.printf("MPU6050 @0x%02X  WHO_AM_I = 0x%02X  -> %s\n",
                addr, who,
                (who == 0x68) ? "OK (MPU6050)" :
                (who == 0x70) ? "MPU6500 clone?" :
                (who == 0x71) ? "MPU9250 clone?" : "UNEXPECTED — check wiring/part");
}

void checkMS5611(TwoWire &w, const char *busName) {
  uint8_t addr = 0;
  for (uint8_t cand : {0x77, 0x76}) {
    w.beginTransmission(cand);
    w.write(0xA0);            // PROM read, word 0
    if (w.endTransmission(false) == 0 && w.requestFrom(cand, (uint8_t)2) == 2) {
      addr = cand;
      break;
    }
  }
  if (!addr) { Serial.printf("MS5611 on %s: NOT FOUND\n", busName); return; }

  w.beginTransmission(addr);
  w.write(0xA0);
  w.endTransmission(false);
  w.requestFrom(addr, (uint8_t)2);
  uint16_t prom0 = (w.read() << 8) | w.read();

  Serial.printf("MS5611 on %s @0x%02X  PROM[0] = 0x%04X  -> %s\n",
                busName, addr, prom0,
                (prom0 != 0x0000 && prom0 != 0xFFFF) ? "OK (alive)" : "BAD read");
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1500);   // give USB-CDC time to attach
  Serial.println("\n=== Vario USB test rig — I2C bring-up scan ===\n");

  Wire.begin(BUSA_SDA, BUSA_SCL);
  Wire.setClock(100000);
  Wire1.begin(BUSB_SDA, BUSB_SCL);
  Wire1.setClock(100000);

  scanBus(Wire,  "Bus A (Wire,  GPIO4/5)");
  scanBus(Wire1, "Bus B (Wire1, GPIO6/7)");
  scanBusC();

  Serial.println("--- ID sanity checks ---");
  checkMS5611(Wire,  "Bus A");
  checkMS5611(Wire1, "Bus B");
  checkMPU6050(Wire);
  Serial.println();

  // Pass/fail summary against the expected map
  Serial.println("--- Expected vs reality ---");
  Serial.println("Bus A: expect 0x77 (GY-63 #1) and 0x68 (MPU6050)");
  Serial.println("Bus B: expect 0x77 (GY-63 #2)");
  Serial.println("Bus C: expect 0x77 (GY-63 #3, optional)");
  Serial.println("If a GY-63 shows 0x76 instead of 0x77, that clone pulls CSB low.");
  Serial.println("\nDone.");
}

void loop() {
  // one-shot test; nothing here
}
