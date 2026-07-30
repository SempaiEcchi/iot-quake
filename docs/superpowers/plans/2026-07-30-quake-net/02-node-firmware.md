# Plan 02: Node Firmware

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Firmware that samples the MPU6050 at 100 Hz, detects shaking, and publishes events over MQTT — with the detection algorithm unit-tested on your laptop before it touches hardware.

**Architecture:** `detector.cpp` is pure C++ with no Arduino headers, so it compiles and runs on macOS under `g++` with fake acceleration and fake timestamps. `node.ino` is a thin shell that feeds it real sensor data. All the logic that can be wrong lives in the part you can test in a second.

**Tech Stack:** C++17, arduino-cli, `Wire`, `WiFi`, PubSubClient, plain `assert` for tests

## Global Constraints

See [00-index.md](00-index.md#global-constraints). Critical for this plan:

- 100 Hz sampling, 10 000 µs period, gated on `micros()`, **resyncing** rather than catching up
  when more than 10 periods behind
- `mqtt.setSocketTimeout(2)` — PubSubClient's default blocks 15 s
- MPU6050 at `0x68`, ±2 g, 16384 LSB/g, 1 g = 980.665 gal — **all acceleration in gal**
- `EMA_ALPHA` 0.01, `WARMUP_MS` 3000, `REFRACTORY_MS` 5000
- Node ID = last three MAC bytes, lowercase hex, `node-a4c1f8`
- Payloads via `snprintf` — no JSON library
- **`firmware/node/config.h` is gitignored from its first commit.** It holds your WiFi
  password and this repo becomes public in plan 06.

---

### Task 1: Protect the secrets before writing any

**Files:**
- Create: `.gitignore`
- Create: `firmware/node/config.h.example`

Do this first. Once a password reaches git history, removing it means rewriting history —
and if you have already pushed, rotating the password. Cheaper to never commit it.

- [ ] **Step 1: Write the gitignore**

```gitignore
# secrets — never commit
firmware/node/config.h

# build artifacts
test/test_detector
build/
*.o
__pycache__/
.pytest_cache/
.venv/
```

- [ ] **Step 2: Write the committed template**

```cpp
// firmware/node/config.h.example
// Copy to config.h and fill in. config.h is gitignored.
#pragma once

#define WIFI_SSID      "your-hotspot-name"
#define WIFI_PASSWORD  "your-hotspot-password"

// Laptop's IP on the hotspot. Find it with: ipconfig getifaddr en0
#define MQTT_HOST      "192.168.1.100"
#define MQTT_PORT      1883

// Trigger threshold in gal. Measured in plan 04 — do not guess.
// Placeholder only, large enough that nothing triggers until calibrated.
#define THRESHOLD_GAL  50.0f
```

- [ ] **Step 3: Create your real config**

```bash
cp firmware/node/config.h.example firmware/node/config.h
```

Fill in your hotspot name and password. Leave `MQTT_HOST` and `THRESHOLD_GAL` for plan 04.

- [ ] **Step 4: Verify git ignores it**

```bash
git status --short firmware/node/config.h
```

Expected: **no output at all.** Any output means the gitignore is wrong — fix it before
continuing.

- [ ] **Step 5: Commit**

```bash
git add .gitignore firmware/node/config.h.example
git commit -m "chore: gitignore secrets, add config template"
```

---

### Task 2: The detector — failing test first

**Files:**
- Create: `firmware/node/detector.h`
- Create: `test/test_detector.cpp`
- Create: `test/Makefile`

**Interfaces:**
- Produces: `Detector`, `DetectorOut`, `detector_init(Detector*, float threshold_gal)`,
  `detector_update(Detector*, float mag_gal, uint32_t now_ms) -> DetectorOut`.
  `node.ino` in Task 4 consumes exactly these.

`detector_update` computes deviation against the **previous** baseline, then updates the
baseline. That ordering matters: it means a single spike sample reports its full deviation
instead of a value already diluted by itself.

- [ ] **Step 1: Write the header**

```cpp
// firmware/node/detector.h
// Pure detection logic. No Arduino headers — compiles and runs on the host.
#pragma once
#include <stdint.h>

// Tuning constants. See docs/superpowers/specs/2026-07-30-esp32-quake-node-design.md
#define EMA_ALPHA      0.01f   // single-pole high-pass; ~1 s time constant at 100 Hz
#define WARMUP_MS      3000    // suppress triggers while the baseline settles
#define REFRACTORY_MS  5000    // one event per shake, not hundreds

struct Detector {
  float    threshold_gal;
  float    baseline;        // tracks gravity (~980 gal)
  uint32_t samples;
  uint32_t t0_ms;           // timestamp of first sample
  bool     in_event;
  float    peak_gal;
  uint32_t event_start_ms;
  uint32_t last_over_ms;    // last sample still above threshold
};

struct DetectorOut {
  float    dev_gal;     // deviation from baseline, always valid
  bool     started;     // true on the one sample that opens an event
  bool     event_done;  // true on the one sample that closes an event
  float    peak_gal;    // valid when event_done
  uint32_t dur_ms;      // valid when event_done
};

void        detector_init(Detector* d, float threshold_gal);
DetectorOut detector_update(Detector* d, float mag_gal, uint32_t now_ms);
```

- [ ] **Step 2: Write the failing tests**

```cpp
// test/test_detector.cpp
// Host unit tests. Plain assert — no framework, no dependencies.
#include "detector.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static const float G = 980.665f;   // 1 g in gal

// Feed n quiet samples starting at t_ms, 10 ms apart. Returns next timestamp.
static uint32_t quiet(Detector* d, int n, uint32_t t_ms) {
  for (int i = 0; i < n; i++) { detector_update(d, G, t_ms); t_ms += 10; }
  return t_ms;
}

static void test_baseline_converges_to_gravity() {
  Detector d; detector_init(&d, 50.0f);
  quiet(&d, 1000, 0);
  DetectorOut o = detector_update(&d, G, 10000);
  assert(fabsf(o.dev_gal) < 0.01f);
  printf("ok baseline_converges_to_gravity\n");
}

static void test_no_event_during_warmup() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 100, 0);           // t = 1000 ms, still inside warmup
  DetectorOut o = detector_update(&d, G + 1000.0f, t);
  assert(o.dev_gal > 900.0f);               // deviation is seen...
  assert(!o.started);                       // ...but must not trigger
  assert(!o.event_done);
  printf("ok no_event_during_warmup\n");
}

static void test_event_fires_after_refractory() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 400, 0);           // t = 4000 ms, past warmup

  DetectorOut o = detector_update(&d, G + 1000.0f, t);
  assert(o.started);
  assert(!o.event_done);                    // not yet — refractory is open
  assert(fabsf(o.dev_gal - 1000.0f) < 1.0f);
  t += 10;

  int events = 0; float peak = 0;
  for (int i = 0; i < 600; i++) {           // 6 s of quiet
    DetectorOut q = detector_update(&d, G, t); t += 10;
    if (q.event_done) { events++; peak = q.peak_gal; }
  }
  assert(events == 1);                      // exactly once
  assert(fabsf(peak - 1000.0f) < 1.0f);     // the true peak, not a later sample
  printf("ok event_fires_after_refractory\n");
}

static void test_below_threshold_never_triggers() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 400, 0);
  for (int i = 0; i < 500; i++) {
    // +-10 gal oscillation: well under the 50 gal threshold
    float mag = G + ((i % 2) ? 10.0f : -10.0f);
    DetectorOut o = detector_update(&d, mag, t); t += 10;
    assert(!o.started);
    assert(!o.event_done);
  }
  printf("ok below_threshold_never_triggers\n");
}

static void test_one_event_per_refractory_window() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 400, 0);   // t = 4000 ms
  // 25 s of sustained +-200 gal shaking. Alternating each sample keeps it
  // above the EMA's ~1 s time constant, so the baseline cannot chase it out.
  int events = 0;
  for (int i = 0; i < 2500; i++) {
    float mag = G + ((i % 2) ? 200.0f : -200.0f);
    DetectorOut o = detector_update(&d, mag, t); t += 10;
    if (o.event_done) events++;
  }
  // Events CLOSE at t = 9000, 14010, 19020, 24030 -- one per 5 s refractory,
  // each starting on the sample after the previous one closed. Four, not
  // hundreds. Note a 5th is open but unclosed when the loop ends: the count
  // is completed events, so it lags the shake duration by one window.
  assert(events == 4);
  printf("ok one_event_per_refractory_window\n");
}

static void test_duration_measures_time_above_threshold() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 400, 0);
  for (int i = 0; i < 100; i++) {           // 1 s above threshold
    float mag = G + ((i % 2) ? 200.0f : -200.0f);
    detector_update(&d, mag, t); t += 10;
  }
  uint32_t dur = 0;
  for (int i = 0; i < 600; i++) {           // then quiet until it closes
    DetectorOut o = detector_update(&d, G, t); t += 10;
    if (o.event_done) dur = o.dur_ms;
  }
  assert(dur >= 900 && dur <= 1100);        // ~1 s, not the 5 s refractory
  printf("ok duration_measures_time_above_threshold\n");
}

int main() {
  test_baseline_converges_to_gravity();
  test_no_event_during_warmup();
  test_event_fires_after_refractory();
  test_below_threshold_never_triggers();
  test_one_event_per_refractory_window();
  test_duration_measures_time_above_threshold();
  printf("\nall detector tests passed\n");
  return 0;
}
```

- [ ] **Step 3: Write the Makefile**

```makefile
# test/Makefile
CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O0 -g

test_detector: test_detector.cpp ../firmware/node/detector.cpp
	$(CXX) $(CXXFLAGS) -I../firmware/node -o $@ $^

.PHONY: run clean
run: test_detector
	./test_detector

clean:
	rm -f test_detector
```

- [ ] **Step 4: Run the tests to verify they fail**

```bash
cd test && make run
```

Expected: a **link error** — `undefined symbols: detector_init, detector_update`. The header
declares them; nothing implements them yet. That is the correct failure.

---

### Task 3: The detector — make it pass

**Files:**
- Create: `firmware/node/detector.cpp`
- Test: `test/test_detector.cpp`

**Interfaces:**
- Consumes: `Detector`, `DetectorOut` from `detector.h` (Task 2)
- Produces: implementations of `detector_init` and `detector_update`

- [ ] **Step 1: Write the implementation**

```cpp
// firmware/node/detector.cpp
#include "detector.h"
#include <math.h>

void detector_init(Detector* d, float threshold_gal) {
  d->threshold_gal  = threshold_gal;
  d->baseline       = 0.0f;
  d->samples        = 0;
  d->t0_ms          = 0;
  d->in_event       = false;
  d->peak_gal       = 0.0f;
  d->event_start_ms = 0;
  d->last_over_ms   = 0;
}

DetectorOut detector_update(Detector* d, float mag_gal, uint32_t now_ms) {
  DetectorOut out = {0.0f, false, false, 0.0f, 0};

  if (d->samples == 0) {
    // Seed the baseline to the first sample instead of 0. Without this the
    // first deviation is ~980 gal and the filter spends a second settling.
    d->baseline = mag_gal;
    d->t0_ms    = now_ms;
    d->samples  = 1;
    return out;                        // dev is meaningless for sample one
  }

  // Deviation against the PREVIOUS baseline, then update. This order lets a
  // single spike report its full amplitude rather than one diluted by itself.
  out.dev_gal = fabsf(mag_gal - d->baseline);
  d->baseline = (1.0f - EMA_ALPHA) * d->baseline + EMA_ALPHA * mag_gal;
  d->samples++;

  if (now_ms - d->t0_ms < WARMUP_MS) return out;   // still settling

  if (d->in_event) {
    if (out.dev_gal > d->peak_gal)       d->peak_gal     = out.dev_gal;
    if (out.dev_gal > d->threshold_gal)  d->last_over_ms = now_ms;

    if (now_ms - d->event_start_ms >= REFRACTORY_MS) {
      out.event_done = true;
      out.peak_gal   = d->peak_gal;
      out.dur_ms     = d->last_over_ms - d->event_start_ms;
      d->in_event    = false;
      d->peak_gal    = 0.0f;
    }
  } else if (out.dev_gal > d->threshold_gal) {
    out.started       = true;
    d->in_event       = true;
    d->event_start_ms = now_ms;
    d->last_over_ms   = now_ms;
    d->peak_gal       = out.dev_gal;
  }

  return out;
}
```

- [ ] **Step 2: Run the tests to verify they pass**

```bash
cd test && make run
```

Expected:

```
ok baseline_converges_to_gravity
ok no_event_during_warmup
ok event_fires_after_refractory
ok below_threshold_never_triggers
ok one_event_per_refractory_window
ok duration_measures_time_above_threshold

all detector tests passed
```

- [ ] **Step 3: Commit**

```bash
git add firmware/node/detector.h firmware/node/detector.cpp test/
git commit -m "feat: shake detector with host unit tests

EMA high-pass removes the 980 gal gravity offset without a filter library.
Warmup suppression and a refractory window prevent the two failure modes
that would otherwise dominate: a startup spike, and hundreds of events per
shake. Deviation is computed against the previous baseline so a single
spike reports its full amplitude."
```

---

### Task 4: The Arduino shell

**Files:**
- Create: `firmware/node/node.ino`

**Interfaces:**
- Consumes: `detector_init`, `detector_update`, `Detector`, `DetectorOut` (Tasks 2–3);
  `WIFI_SSID`, `WIFI_PASSWORD`, `MQTT_HOST`, `MQTT_PORT`, `THRESHOLD_GAL` (Task 1)
- Produces: MQTT messages on `quake/<id>/event` and `quake/<id>/tel`; subscribes `quake/alarm`

Everything here is I/O. Nothing here decides whether a shake happened.

- [ ] **Step 1: Write the sketch**

```cpp
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

#define MPU_ADDR     0x68     // 0x69 if your scan found AD0 pulled high
#define REG_PWR_MGMT 0x6B
#define REG_ACCEL_CFG 0x1C
#define REG_ACCEL_XOUT 0x3B

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

// Near-non-blocking: mqtt.connect() still blocks, but setSocketTimeout(2)
// caps that at ~2 s instead of PubSubClient's 15 s default, and the sample
// gate resyncs afterwards rather than firing a catch-up burst.
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

  // 100 Hz gate. Runs regardless of network state — detection never stops.
  if ((int32_t)(micros() - next_sample_us) < 0) return;

  // Resync instead of catching up. A stall (a blocking reconnect, say) leaves
  // the gate many periods behind; catching up would fire a burst of samples
  // all stamped with nearly the same millis(), which corrupts the EMA
  // baseline and can bypass warm-up. Dropping those samples is harmless —
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
```

- [ ] **Step 2: Compile it**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/node
```

Expected: `Sketch uses NNNNNN bytes`, no errors. `detector.cpp` is picked up automatically
because it sits in the sketch folder.

If it fails with `config.h: No such file`, you skipped Task 1 Step 3.

- [ ] **Step 3: Verify the detector tests still pass**

`detector.h` is now included by two consumers. Confirm the host tests are unaffected.

```bash
cd test && make clean && make run
```

Expected: `all detector tests passed`

- [ ] **Step 4: Confirm no secret is staged**

```bash
git status --short
```

Expected: `firmware/node/node.ino` listed, `firmware/node/config.h` **absent**.

- [ ] **Step 5: Commit**

```bash
git add firmware/node/node.ino
git commit -m "feat: node sketch - sensor, WiFi, MQTT, LED, buzzer

Raw Wire register reads instead of a driver library: two fewer
dependencies for twenty lines.

PubSubClient's connect() blocks for 15 s by default when the broker is
unreachable, and the sample gate would then catch up in a burst of
samples all stamped with the same millis(), corrupting the EMA baseline
and bypassing warm-up. Socket timeout is capped at 2 s and the gate
resyncs rather than catching up.

Events during an outage are dropped rather than queued - a stale
timestamp would corrupt the correlator's window."
```

---

## Done when

- `cd test && make run` prints `all detector tests passed`
- `arduino-cli compile --fqbn esp32:esp32:esp32 firmware/node` succeeds
- `git status --short` never shows `config.h`

Not flashed yet — that is plan 04. Write the correlator next; it needs no hardware.

Next: [03-correlator.md](03-correlator.md)
