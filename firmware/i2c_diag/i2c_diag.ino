// firmware/i2c_diag/i2c_diag.ino
// Both bus lines read HIGH but nothing ACKs. This distinguishes a real pull-up
// resistor on a powered module from a floating line that merely reads HIGH.
//
// Drive the line LOW, release it, and count how many reads it takes to come back
// up. A 4.7k pull-up recovers on the very next read. A floating line held up by
// leakage takes far longer, or never recovers.
#include <Wire.h>

int rise_reads(int pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  delayMicroseconds(200);
  pinMode(pin, INPUT);              // release, no internal pull-up
  for (int i = 0; i < 1000; i++)
    if (digitalRead(pin)) return i;
  return -1;
}

void report(const char* name, int pin) {
  int n = rise_reads(pin);
  Serial.printf("  GPIO%-2d %-4s ", pin, name);
  if (n < 0)        Serial.println("never rose      -> FLOATING, no pull-up. Wire not on a live pin.");
  else if (n <= 2)  Serial.printf("rose in %d read(s) -> real pull-up present\n", n);
  else              Serial.printf("rose in %d reads   -> weak/leaky, not a proper pull-up\n", n);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(25, OUTPUT); digitalWrite(25, HIGH);   // buzzer is active-LOW: HIGH is silent

  Serial.println("\npull-up strength test");
  report("SDA", 26);
  report("SCL", 27);

  Serial.println("full scan on GPIO26/27, 50 kHz, three passes");
  Wire.begin(26, 27);
  Wire.setClock(50000);
  for (int pass = 1; pass <= 3; pass++) {
    int found = 0;
    for (uint8_t a = 1; a < 127; a++) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) { Serial.printf("  pass %d: 0x%02X\n", pass, a); found++; }
    }
    if (!found) Serial.printf("  pass %d: nothing\n", pass);
    delay(200);
  }
  Serial.println("done");
}

void loop() {}
