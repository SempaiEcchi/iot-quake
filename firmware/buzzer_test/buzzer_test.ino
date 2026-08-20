// firmware/buzzer_test/buzzer_test.ino
// Throwaway check for the 3-pin buzzer module on GPIO25.
//
// 3-pin modules come in three flavours and the silkscreen never says which:
//   active-HIGH active  - sounds while the pin is HIGH        (what node.ino assumes)
//   active-LOW  active  - sounds while the pin is LOW
//   passive             - silent on a DC level, needs a tone
// This runs all three in turn and announces each on serial, so you can hear
// which one your module is and fix node.ino if it is not the first.

#define BUZZER_PIN 25
#define TONE_HZ    2000

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  Serial.println("\nbuzzer test on GPIO25 - listen, and note which test beeps");
}

void loop() {
  Serial.println("A: pin HIGH   (active-HIGH active buzzer)");
  digitalWrite(BUZZER_PIN, HIGH);
  delay(1500);
  digitalWrite(BUZZER_PIN, LOW);
  delay(2000);

  Serial.println("B: pin LOW    (active-LOW active buzzer)");
  digitalWrite(BUZZER_PIN, HIGH);   // idle high for this one
  delay(300);
  digitalWrite(BUZZER_PIN, LOW);
  delay(1500);
  delay(2000);

  Serial.println("C: 2 kHz tone (passive buzzer)");
  tone(BUZZER_PIN, TONE_HZ);
  delay(1500);
  noTone(BUZZER_PIN);
  digitalWrite(BUZZER_PIN, LOW);
  delay(3000);

  Serial.println("--- repeating ---\n");
}
