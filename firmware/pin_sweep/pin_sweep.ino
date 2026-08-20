// firmware/pin_sweep/pin_sweep.ino
// Diagnostic: the buzzer made no sound on GPIO25. This finds out why.
//
// Phase 0 blinks the onboard LED (GPIO2) three times. If you see that, the
// sketch is running and the board is fine, so the fault is wiring or power.
// Phase 1 then drives every output-capable header pin in turn, announcing each
// on serial. Whichever pin the buzzer is actually wired to will beep, which
// tells us the miscount.

#define LED 2

const int PINS[] = {32, 33, 25, 26, 27, 14, 13,
                    23, 22, 21, 19, 18, 5, 17, 16, 4};
const int N = sizeof(PINS) / sizeof(PINS[0]);

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(LED, OUTPUT);

  Serial.println("\nphase 0: onboard LED on GPIO2, three blinks");
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED, HIGH); delay(300);
    digitalWrite(LED, LOW);  delay(300);
  }

  for (int i = 0; i < N; i++) {
    pinMode(PINS[i], OUTPUT);
    digitalWrite(PINS[i], LOW);
  }
  Serial.println("phase 1: driving each pin HIGH in turn");
}

void loop() {
  for (int i = 0; i < N; i++) {
    Serial.printf("GPIO%d\n", PINS[i]);
    for (int b = 0; b < 2; b++) {
      digitalWrite(PINS[i], HIGH); delay(350);
      digitalWrite(PINS[i], LOW);  delay(150);
    }
    delay(700);
  }
  Serial.println("--- repeating ---\n");
  delay(1500);
}
