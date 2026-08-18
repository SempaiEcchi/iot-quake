// firmware/calibrate/calibrate.ino
// Throwaway. Prints deviation-from-baseline in gal at 100 Hz as CSV.
// Self-contained: repeats the EMA rather than including detector.h, because
// Arduino only compiles sources inside the sketch folder.
#include <Wire.h>

#define MPU_ADDR   0x68
#define LSB_PER_G  16384.0f
#define GAL_PER_G  980.665f
#define EMA_ALPHA  0.01f
#define SAMPLE_US  10000

float baseline = 0.0f;
bool  seeded = false;
uint32_t next_us = 0;

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  Wire.setClock(400000);
  Wire.beginTransmission(MPU_ADDR); Wire.write(0x6B); Wire.write(0x00);
  Wire.endTransmission();
  Wire.beginTransmission(MPU_ADDR); Wire.write(0x1C); Wire.write(0x00);
  Wire.endTransmission();
  delay(100);
  Serial.println("dev_gal");     // CSV header
  next_us = micros();
}

void loop() {
  if ((int32_t)(micros() - next_us) < 0) return;
  next_us += SAMPLE_US;

  Wire.beginTransmission(MPU_ADDR); Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return;
  if (Wire.requestFrom(MPU_ADDR, 6) != 6) return;

  int16_t x = (Wire.read() << 8) | Wire.read();
  int16_t y = (Wire.read() << 8) | Wire.read();
  int16_t z = (Wire.read() << 8) | Wire.read();
  float gx = x / LSB_PER_G, gy = y / LSB_PER_G, gz = z / LSB_PER_G;
  float mag = sqrtf(gx*gx + gy*gy + gz*gz) * GAL_PER_G;

  if (!seeded) { baseline = mag; seeded = true; return; }
  float dev = fabsf(mag - baseline);
  baseline = (1.0f - EMA_ALPHA) * baseline + EMA_ALPHA * mag;
  Serial.println(dev, 4);
}
