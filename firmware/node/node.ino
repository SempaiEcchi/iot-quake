// firmware/node/node.ino
// Networked shake node. Samples at 100 Hz, publishes events over MQTT.
//
// One MPU6050 at 0x68, plus a MIRROR channel that replays the same readings
// under a second node ID so the correlator has two sources to agree on.
//
// The mirror is not a measurement. It is the same sensor, the same sample, the
// same instant -- so it agrees with the real channel by construction and the
// correlation rule can never reject anything. Every alarm it produces is
// vacuous. Its node ID is prefixed "mirror-" precisely so no log, dashboard or
// report can present it as a second station.
//
// This exists to demonstrate the alarm path end to end with one sensor. The
// design's actual claim -- that agreement between spatially separated sensors
// distinguishes ground motion from someone leaning on the desk -- is NOT
// demonstrated by it, and needs a real second sensor at 0x69 (AD0 high).
#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ESPmDNS.h>
#include "config.h"
#include "detector.h"

#define SDA_PIN      26
#define SCL_PIN      27
#define LED_PIN      2      // onboard LED on the FNK0090 (LED_IO2)
#define BUZZER_PIN   25
// This module is active-LOW: it sounds while the pin is LOW and is silent
// while HIGH. Measured, not assumed -- driving it the obvious way left it
// screaming continuously and going quiet for 1.5 s on each alarm, which is
// exactly backwards. Use these two names rather than HIGH/LOW anywhere the
// buzzer is touched, including the diagnostic sketches.
#define BUZZ_ON      LOW
#define BUZZ_OFF     HIGH

#define REG_PWR_MGMT   0x6B
#define REG_CONFIG     0x1A
#define REG_ACCEL_CFG  0x1C
#define REG_ACCEL_XOUT 0x3B

// DLPF_CFG = 6 -> accelerometer bandwidth 5 Hz (19 ms group delay).
// This is the low-pass half of the 0.2-5 Hz band the design specifies. The
// EMA in detector.cpp is only a high-pass; without this the sensor runs at
// its 260 Hz default and the noise floor is ~sqrt(260/4.8) = 7x worse, which
// would push the measured threshold above shindo 3 entirely. Sampling at
// 100 Hz does not fix it -- out-of-band noise aliases in rather than
// disappearing, so the filtering has to happen in the sensor.
#define DLPF_5HZ       0x06

#define LSB_PER_G    16384.0f // +-2 g full scale
#define GAL_PER_G    980.665f
#define SAMPLE_US    10000    // 100 Hz
#define TEL_MS       1000     // telemetry at 1 Hz
#define BUZZ_MS      1500     // alarm buzz length
#define RETRY_MS     5000     // how often to re-probe a missing sensor

// Simulated-sensor mode. A channel whose MPU6050 does not answer synthesises
// acceleration instead of going dark: gravity plus noise, with a burst on
// demand. Everything downstream -- detector, event payload, correlator -- is
// the real code path, so only the source of the numbers differs. The shake
// alternates sign each sample so the EMA high-pass cannot track it out.
//
// Both channels shake together, which is what two co-located sensors would
// genuinely do. That means an all-simulated node self-correlates: it is a
// demo mode, not evidence. A channel stops simulating the moment its sensor
// answers, so this fades out on its own as hardware arrives.
// Simulation is OFF. With a real sensor on 0x68 the only thing synthetic data
// can do now is contaminate real measurements, and it did: fabricated events
// were interleaved with genuine ones in the earthquake log. A missing sensor
// publishes nothing and says so, which is a visible failure rather than a
// plausible lie. Set to 1 only to demo with no hardware attached.
#define SIM_ENABLED    0
#define BOOT_BTN       0      // FNK0090 BOOT button, active low
#define SIM_NOISE_GAL  0.30f
// 12 gal is shindo 4 -- a plausible reading for a second station that felt the
// same quake. It used to be 80 gal, which was fine when both channels were
// synthetic but is not now: the alarm reports the maximum across channels, so
// an 80 gal simulated peak would drown out whatever the real sensor measured
// and every alarm would claim shindo 5+ regardless of the ground truth.
#define SIM_SHAKE_GAL  12.0f
#define SIM_SHAKE_MS   800
// 0 disables the timer. A simulated channel firing on its own schedule filled
// the earthquake log with fabricated entries, which was harmless while nothing
// was real and is not harmless now. The BOOT button is the only trigger.
#define SIM_AUTO_MS    0

#define NCHAN 2

struct Channel {
  uint8_t  addr;
  char     suffix;
  bool     present;
  Detector det;
  char     id[20];
  char     topic_event[56];
  char     topic_tel[56];
  float    last_dev;
  uint32_t sim_rng;
  uint32_t sim_parity;
};

WiFiClient   net;
PubSubClient mqtt(net);

#define MIRROR_ADDR 0x00      // not an I2C address: marks the mirror channel

Channel chan[NCHAN] = {
  {0x68,        0, false, {}, "", "", "", 0.0f, 0x5eed1234, 0},
  {MIRROR_ADDR, 0, false, {}, "", "", "", 0.0f, 0x1234beef, 0},
};

char     base_id[16];
uint32_t next_sample_us = 0, next_tel_ms = 0, buzz_until_ms = 0;
uint32_t last_reconnect_ms = 0, next_retry_ms = 0;
uint32_t shake_until_ms = 0, btn_ok_ms = 0, next_auto_shake_ms = 0;
uint32_t samples_this_sec = 0;
uint32_t reconnect_backoff_ms = 2000;

// ---------- sensor ----------

static bool mpu_init(uint8_t addr) {
  Wire.beginTransmission(addr);
  Wire.write(REG_PWR_MGMT);
  Wire.write(0x00);                    // wake from sleep
  if (Wire.endTransmission() != 0) return false;

  Wire.beginTransmission(addr);
  Wire.write(REG_CONFIG);
  Wire.write(DLPF_5HZ);                // band-limit to 5 Hz -- see above
  if (Wire.endTransmission() != 0) return false;

  Wire.beginTransmission(addr);
  Wire.write(REG_ACCEL_CFG);
  Wire.write(0x00);                    // +-2 g
  return Wire.endTransmission() == 0;
}

// Magnitude of the acceleration vector, in gal. Returns false on I2C failure.
static bool mpu_read_mag(uint8_t addr, float* mag_gal) {
  Wire.beginTransmission(addr);
  Wire.write(REG_ACCEL_XOUT);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)addr, 6) != 6) return false;

  int16_t x = (Wire.read() << 8) | Wire.read();
  int16_t y = (Wire.read() << 8) | Wire.read();
  int16_t z = (Wire.read() << 8) | Wire.read();

  float gx = x / LSB_PER_G, gy = y / LSB_PER_G, gz = z / LSB_PER_G;
  *mag_gal = sqrtf(gx*gx + gy*gy + gz*gz) * GAL_PER_G;
  return true;
}

// ---------- simulated sensor ----------

static float sim_unit(Channel* c) {          // cheap LCG, 0..1
  c->sim_rng = c->sim_rng * 1664525u + 1013904223u;
  return (float)((c->sim_rng >> 8) & 0xFFFF) / 65535.0f;
}

static bool sim_read_mag(Channel* c, float* mag_gal) {
  float shake = 0.0f;
  if (shake_until_ms && millis() < shake_until_ms)
    shake = (c->sim_parity++ & 1) ? SIM_SHAKE_GAL : -SIM_SHAKE_GAL;
  *mag_gal = GAL_PER_G + (sim_unit(c) - 0.5f) * 2.0f * SIM_NOISE_GAL + shake;
  return true;
}

// BOOT button injects a shake, so the node can be triggered by hand in a demo.
static void poll_button() {
  if (digitalRead(BOOT_BTN) != LOW) return;
  if (millis() < btn_ok_ms) return;
  btn_ok_ms = millis() + 400;              // debounce
  shake_until_ms = millis() + SIM_SHAKE_MS;
  Serial.println("BOOT pressed - injecting shake");
}

// ---------- network ----------

static void on_message(char* topic, byte* payload, unsigned int len) {
  (void)payload; (void)len;
  if (strcmp(topic, "quake/alarm") == 0) {
    Serial.println("ALARM received - buzzer on");
    digitalWrite(BUZZER_PIN, BUZZ_ON);
    digitalWrite(LED_PIN, HIGH);           // visible alarm as well as audible
    buzz_until_ms = millis() + BUZZ_MS;
  }
}

// Near-non-blocking. mqtt.connect() still blocks: the TCP connect phase is
// bounded by WiFiClient's own default (~3 s), and setSocketTimeout(2) bounds
// the MQTT handshake that follows, instead of PubSubClient's 15 s default.
// Either way the stall is seconds, so the sample gate resyncs afterwards
// rather than firing a catch-up burst. See loop().
static void net_pump() {
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - last_reconnect_ms > 5000) {
      last_reconnect_ms = millis();
      WiFi.reconnect();
    }
    return;
  }
  if (!mqtt.connected()) {
    // Back off, do not hammer. Each failed connect() blocks for seconds while
    // the TCP handshake times out, and retrying every 2 s spends most of the
    // loop inside it -- measured at 1 Hz sampling against an unreachable
    // broker, against a nominal 100. Detection is supposed to survive a
    // network outage; at 1 Hz it does not. Backing off to 30 s keeps sampling
    // above 90% while an outage lasts.
    if (millis() - last_reconnect_ms > reconnect_backoff_ms) {
      last_reconnect_ms = millis();
      if (mqtt.connect(base_id)) {
        reconnect_backoff_ms = 2000;
        bool sub = mqtt.subscribe("quake/alarm");
        Serial.printf("MQTT connected, subscribe(quake/alarm)=%s\n",
                      sub ? "ok" : "FAILED");
      } else {
        reconnect_backoff_ms = min(reconnect_backoff_ms * 2, (uint32_t)30000);
        Serial.printf("MQTT connect failed, retry in %lu ms\n",
                      (unsigned long)reconnect_backoff_ms);
      }
    }
    return;
  }
  mqtt.loop();
}

static void publish_tel() {
  if (millis() < next_tel_ms) return;
  next_tel_ms = millis() + TEL_MS;
  // Actual sample rate, not the nominal 100. A real I2C read costs about a
  // millisecond per sensor, and if the loop ever falls behind the gate resyncs
  // by dropping samples -- silently. Event durations would shrink and the EMA
  // time constant would stretch, both of which corrupt detection while
  // everything still looks like it is working. Watch this number.
  Serial.printf("health: %lu Hz  a=%s %.2f gal  b=%s %.2f gal\n",
                (unsigned long)samples_this_sec,
                chan[0].present ? "real" : "sim", chan[0].last_dev,
                chan[1].present ? "real" : "sim", chan[1].last_dev);
  samples_this_sec = 0;
  for (int i = 0; i < NCHAN; i++) {
    char buf[96];
    snprintf(buf, sizeof(buf), "{\"node\":\"%s\",\"dev_gal\":%.2f,\"uptime_s\":%lu}",
             chan[i].id, chan[i].last_dev, (unsigned long)(millis() / 1000));
    mqtt.publish(chan[i].topic_tel, buf);
  }
}

// Re-probe channels whose sensor is missing. One plugged in later takes over
// from the simulation with no reflash; its detector is re-initialised so the
// EMA baseline reseeds from real readings instead of inheriting synthetic ones.
static void retry_sensors() {
  if (millis() < next_retry_ms) return;
  next_retry_ms = millis() + RETRY_MS;
  for (int i = 0; i < NCHAN; i++) {
    if (chan[i].present) continue;
    if (mpu_init(chan[i].addr)) {
      chan[i].present = true;
      detector_init(&chan[i].det, THRESHOLD_GAL);
      Serial.printf("%s: MPU6050 at 0x%02X came up - real sensor driving detection\n",
                    chan[i].id, chan[i].addr);
    }
  }
}

// ---------- setup / loop ----------

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(BOOT_BTN, INPUT_PULLUP);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, BUZZ_OFF);

  // Short chirp at boot. Confirms the buzzer is wired and the polarity is
  // right, so a silent alarm later is a subscription problem, not this.
  digitalWrite(BUZZER_PIN, BUZZ_ON);
  delay(120);
  digitalWrite(BUZZER_PIN, BUZZ_OFF);

  Wire.begin(SDA_PIN, SCL_PIN);
  // The MPU6050 needs ~100 ms after power-up before it answers. Probing
  // immediately made every boot report NO SENSOR and recover only on the 5 s
  // retry -- harmless but indistinguishable from a genuine wiring fault.
  delay(150);
  // 100 kHz, not 400 kHz. Two sensors at 100 Hz is 1.2 kB/s, so bandwidth is
  // irrelevant, and the slower edge rate is what lets the second sensor sit on
  // a metre or two of cable at the far end of the room. Raise it only if both
  // modules are on the same breadboard and you have a reason to.
  Wire.setClock(100000);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint8_t mac[6];
  WiFi.macAddress(mac);
  snprintf(base_id, sizeof(base_id), "node-%02x%02x%02x", mac[3], mac[4], mac[5]);

  for (int i = 0; i < NCHAN; i++) {
    if (chan[i].addr == MIRROR_ADDR)
      snprintf(chan[i].id, sizeof(chan[i].id), "mirror-%s", base_id + 5);
    else
      snprintf(chan[i].id, sizeof(chan[i].id), "%s", base_id);
    snprintf(chan[i].topic_event, sizeof(chan[i].topic_event), "quake/%s/event", chan[i].id);
    snprintf(chan[i].topic_tel,   sizeof(chan[i].topic_tel),   "quake/%s/tel",   chan[i].id);
    if (chan[i].addr == MIRROR_ADDR) {
      detector_init(&chan[i].det, THRESHOLD_GAL);
      Serial.printf("%s: MIRROR of %s - not an independent measurement\n",
                    chan[i].id, base_id);
      continue;
    }
    chan[i].present = mpu_init(chan[i].addr);
    detector_init(&chan[i].det, THRESHOLD_GAL);
    Serial.printf("%s at 0x%02X: %s\n", chan[i].id, chan[i].addr,
                  chan[i].present ? "MPU6050 ok"
                    : (SIM_ENABLED ? "no sensor - SIMULATED, press BOOT to trigger"
                                   : "NO SENSOR - not publishing, check wiring"));
  }
  Serial.printf("threshold=%.1f gal\n", THRESHOLD_GAL);

  // Resolve the broker by name, fall back to the literal IP. A DHCP lease that
  // moves is otherwise a silent failure: the node keeps running, keeps
  // sampling, and never reaches the broker.
  IPAddress broker;
  if (MDNS.begin(base_id) && (broker = MDNS.queryHost(MQTT_HOSTNAME, 5000)) != IPAddress()) {
    Serial.printf("broker %s resolved to %s\n", MQTT_HOSTNAME,
                  broker.toString().c_str());
    mqtt.setServer(broker, MQTT_PORT);
  } else {
    Serial.printf("mDNS could not resolve %s, falling back to %s\n",
                  MQTT_HOSTNAME, MQTT_HOST);
    mqtt.setServer(MQTT_HOST, MQTT_PORT);
  }
  mqtt.setCallback(on_message);
  mqtt.setSocketTimeout(2);   // default is 15 s, which stalls loop() hard

  next_sample_us = micros();
}

void loop() {
  net_pump();

  if (buzz_until_ms && millis() > buzz_until_ms) {
    digitalWrite(BUZZER_PIN, BUZZ_OFF);
    digitalWrite(LED_PIN, LOW);
    buzz_until_ms = 0;
  }

  if (SIM_ENABLED) poll_button();
  if (SIM_ENABLED && SIM_AUTO_MS && millis() > next_auto_shake_ms) {
    next_auto_shake_ms = millis() + SIM_AUTO_MS;
    shake_until_ms = millis() + SIM_SHAKE_MS;
  }
  retry_sensors();

  // 100 Hz gate. Runs regardless of network state - detection never stops.
  if ((int32_t)(micros() - next_sample_us) < 0) return;

  // Resync instead of catching up. A stall (a blocking reconnect, say) leaves
  // the gate many periods behind; catching up would fire a burst of samples
  // all stamped with nearly the same millis(), which corrupts the EMA
  // baseline and can bypass warm-up. Dropping those samples is harmless -
  // events are dropped during an outage anyway.
  if ((int32_t)(micros() - next_sample_us) > 10 * SAMPLE_US)
    next_sample_us = micros();
  else
    next_sample_us += SAMPLE_US;

  uint32_t now = millis();
  samples_this_sec++;
  float real_mag = 0.0f;
  bool  real_ok = false;

  for (int i = 0; i < NCHAN; i++) {
    Channel* c = &chan[i];
    float mag;
    bool ok;
    if (c->addr == MIRROR_ADDR) {
      // Replay the real channel's sample. Its detector is a separate instance,
      // so it keeps its own baseline and refractory state, but the input is
      // identical -- which is why its agreement proves nothing.
      ok = real_ok;
      mag = real_mag;
    } else if (c->present) {
      ok = mpu_read_mag(c->addr, &mag);
      real_ok = ok;
      real_mag = mag;
    } else if (SIM_ENABLED) {
      ok = sim_read_mag(c, &mag);
    } else {
      continue;                          // no sensor, no data. Never invent it.
    }
    if (!ok) {
      // Say so. A silent fallback is the worst outcome here: the channel keeps
      // publishing plausible values that are not measurements, and nothing
      // downstream can tell the difference.
      if (c->addr != MIRROR_ADDR) {
        Serial.printf("%s: I2C read failed at 0x%02X\n", c->id, c->addr);
        c->present = false;
      }
      continue;                         // never publish garbage
    }

    DetectorOut o = detector_update(&c->det, mag, now);
    c->last_dev = o.dev_gal;

    if (o.event_done) {
      char buf[112];
      snprintf(buf, sizeof(buf), "{\"node\":\"%s\",\"peak_gal\":%.2f,\"dur_ms\":%lu}",
               c->id, o.peak_gal, (unsigned long)o.dur_ms);
      mqtt.publish(c->topic_event, buf);  // drops silently if disconnected
      Serial.printf("EVENT %s peak=%.2f gal dur=%lu ms\n", c->id, o.peak_gal,
                    (unsigned long)o.dur_ms);
    }
  }

  publish_tel();
}
