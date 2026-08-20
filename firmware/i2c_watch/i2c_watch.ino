// firmware/i2c_watch/i2c_watch.ino
// Continuous I2C probe, ~4 Hz. Use it while pressing an unsoldered GY-521 header
// against its pads: any momentary contact shows up as a hit. Proves the sensor is
// alive before you commit to soldering it.
#include <Wire.h>

int hits = 0, polls = 0;

void setup() {
  Serial.begin(115200);
  delay(400);
  pinMode(25, OUTPUT); digitalWrite(25, HIGH);   // buzzer is active-LOW: HIGH is silent
  Wire.begin(26, 27);
  Wire.setClock(100000);
  Serial.println("\npress the sensor pins - watching for 0x68");
}

void loop() {
  polls++;
  Wire.beginTransmission(0x68);
  bool ok = (Wire.endTransmission() == 0);
  int sda = digitalRead(26), scl = digitalRead(27);
  if (ok) hits++;
  Serial.printf("%s  poll %3d  hits %2d   SDA=%d SCL=%d\n",
                ok ? "HIT  0x68 " : "  ...     ", polls, hits, sda, scl);
  delay(250);
}
