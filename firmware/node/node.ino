// firmware/node/node.ino
// Networked shake node. Samples at 100 Hz, publishes events over MQTT.
// The ID comes from the WiFi MAC, so this is drop-in for additional nodes.
#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "config.h"
#include "detector.h"

#define SDA_PIN      21
#define SCL_PIN      22
#define LED_PIN      26
#define BUZZER_PIN   25

#define MPU_ADDR       0x68   // 0x69 if your scan found AD0 pulled high
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

WiFiClient   net;
PubSubClient mqtt(net);
Detector     det;

char node_id[16];
char topic_event[48], topic_tel[48];
uint32_t next_sample_us = 0, next_tel_ms = 0, buzz_until_ms = 0;
uint32_t last_reconnect_ms = 0;
float last_dev = 0.0f;

// ---------- sensor ----------

static bool mpu_init() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(REG_PWR_MGMT);
  Wire.write(0x00);                    // wake from sleep
  if (Wire.endTransmission() != 0) return false;

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(REG_CONFIG);
  Wire.write(DLPF_5HZ);                // band-limit to 5 Hz -- see above
  if (Wire.endTransmission() != 0) return false;

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(REG_ACCEL_CFG);
  Wire.write(0x00);                    // +-2 g
  return Wire.endTransmission() == 0;
}

// Magnitude of the acceleration vector, in gal. Returns false on I2C failure.
static bool mpu_read_mag(float* mag_gal) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(REG_ACCEL_XOUT);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(MPU_ADDR, 6) != 6) return false;

  int16_t x = (Wire.read() << 8) | Wire.read();
  int16_t y = (Wire.read() << 8) | Wire.read();
  int16_t z = (Wire.read() << 8) | Wire.read();

  float gx = x / LSB_PER_G, gy = y / LSB_PER_G, gz = z / LSB_PER_G;
  *mag_gal = sqrtf(gx*gx + gy*gy + gz*gz) * GAL_PER_G;
  return true;
}

// ---------- network ----------

static void on_message(char* topic, byte* payload, unsigned int len) {
  (void)payload; (void)len;
  if (strcmp(topic, "quake/alarm") == 0) {
    digitalWrite(BUZZER_PIN, HIGH);
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
    if (millis() - last_reconnect_ms > 2000) {
      last_reconnect_ms = millis();
      if (mqtt.connect(node_id)) mqtt.subscribe("quake/alarm");
    }
    return;
  }
  mqtt.loop();
}

// ---------- setup / loop ----------

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  while (!mpu_init()) {                 // blink fast until the sensor answers
    Serial.println("MPU6050 not responding - check wiring");
    for (int i = 0; i < 5; i++) {
      digitalWrite(LED_PIN, !digitalRead(LED_PIN));
      delay(100);
    }
  }
  digitalWrite(LED_PIN, LOW);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint8_t mac[6];
  WiFi.macAddress(mac);
  snprintf(node_id, sizeof(node_id), "node-%02x%02x%02x", mac[3], mac[4], mac[5]);
  snprintf(topic_event, sizeof(topic_event), "quake/%s/event", node_id);
  snprintf(topic_tel,   sizeof(topic_tel),   "quake/%s/tel",   node_id);
  Serial.printf("id=%s threshold=%.1f gal\n", node_id, THRESHOLD_GAL);

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(on_message);
  mqtt.setSocketTimeout(2);   // default is 15 s, which stalls loop() hard

  detector_init(&det, THRESHOLD_GAL);
  next_sample_us = micros();
}

void loop() {
  net_pump();

  if (buzz_until_ms && millis() > buzz_until_ms) {
    digitalWrite(BUZZER_PIN, LOW);
    buzz_until_ms = 0;
  }

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

  float mag;
  if (!mpu_read_mag(&mag)) return;      // skip this sample, never publish garbage

  DetectorOut o = detector_update(&det, mag, millis());
  last_dev = o.dev_gal;

  if (o.started)    digitalWrite(LED_PIN, HIGH);
  if (o.event_done) {
    digitalWrite(LED_PIN, LOW);
    char buf[96];
    snprintf(buf, sizeof(buf), "{\"node\":\"%s\",\"peak_gal\":%.2f,\"dur_ms\":%lu}",
             node_id, o.peak_gal, (unsigned long)o.dur_ms);
    mqtt.publish(topic_event, buf);     // drops silently if disconnected
    Serial.printf("EVENT peak=%.2f gal dur=%lu ms\n", o.peak_gal,
                  (unsigned long)o.dur_ms);
  }

  if (millis() > next_tel_ms) {
    next_tel_ms = millis() + TEL_MS;
    char buf[96];
    snprintf(buf, sizeof(buf), "{\"node\":\"%s\",\"dev_gal\":%.2f,\"uptime_s\":%lu}",
             node_id, last_dev, (unsigned long)(millis() / 1000));
    mqtt.publish(topic_tel, buf);
  }
}
