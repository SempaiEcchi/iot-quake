// firmware/i2c_scan/i2c_scan.ino
// Throwaway wiring check. Prints every I2C address that responds.
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  delay(500);

  // Hold the buzzer quiet. GPIO25 floats after reset, and some 3-pin modules
  // sound on a floating input, which makes running this scan unpleasant.
  pinMode(25, OUTPUT);
  digitalWrite(25, HIGH);            // buzzer is active-LOW: HIGH is silent

  Wire.begin(26, 27);   // SDA, SCL
  Serial.println("scanning...");

  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("found device at 0x%02X\n", addr);
      found++;
    }
  }
  Serial.printf("done, %d device(s)\n", found);
}

void loop() {}
