// firmware/buzzer_test/buzzer_test.ino
// Polarity check for the 3-pin buzzer module on GPIO25.
//
// Modules of this shape come in both polarities and the silkscreen never says
// which. Measured answer for the module on this build: ACTIVE-LOW -- it sounds
// while the pin is LOW. node.ino encodes that as BUZZ_ON/BUZZ_OFF. Re-run this
// if the module is ever swapped.
// Hold each level long enough to be unmistakable, and announce it, so
// the answer is "which one was quiet" rather than a guess about a short beep.
#define BUZZER_PIN 25
#define LED_PIN    2      // reports which state we are in, so serial is not needed

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  Serial.println("\nLED ON = pin HIGH.  LED OFF = pin LOW.  Which is silent?");
}

void loop() {
  Serial.println("A: pin HIGH for 6 s  (LED ON)");
  digitalWrite(BUZZER_PIN, HIGH);
  digitalWrite(LED_PIN, HIGH);
  delay(6000);

  Serial.println("B: pin LOW  for 6 s  (LED OFF)");
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_PIN, LOW);
  delay(6000);
}
