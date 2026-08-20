// firmware/line_probe/line_probe.ino
// Live pull-up monitor, twice a second. Move a bus wire's sensor end onto the
// GY-521's VCC pin: if that line flips to CONNECTED, the jumper and the
// breadboard holes are fine and the fault is at the module's own pin. If it
// stays FLOATING, the jumper or the hole is the problem.
int rise(int pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  delayMicroseconds(200);
  pinMode(pin, INPUT);
  for (int i = 0; i < 400; i++) if (digitalRead(pin)) return i;
  return -1;
}

void setup() {
  Serial.begin(115200);
  delay(400);
  pinMode(25, OUTPUT); digitalWrite(25, HIGH);   // buzzer is active-LOW: HIGH is silent
  Serial.println("\nmove a bus wire onto the GY-521 VCC pin and watch its line");
}

void loop() {
  int a = rise(26), b = rise(27);
  Serial.printf("GPIO26 %-9s   GPIO27 %-9s\n",
                a < 0 ? "FLOATING" : "CONNECTED",
                b < 0 ? "FLOATING" : "CONNECTED");
  delay(500);
}
