# Plan 04: Bringup & Calibration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Tasks involve physical hardware and a phone hotspot. An agent can write the code and the docs; a human must flash, shake, and read the output.

**Goal:** Both nodes live on the broker, publishing telemetry, with a threshold measured from your actual desk rather than guessed.

**Architecture:** Bring up the network first (hotspot, broker), then measure each node's real noise floor with a throwaway calibration sketch, then flash the real firmware with the measured threshold.

**Tech Stack:** mosquitto, arduino-cli, Python

## Global Constraints

See [00-index.md](00-index.md#global-constraints). Relevant here:

- MQTT on port 1883, no TLS, no auth
- Both nodes run **byte-identical** firmware — so there is one shared threshold, not two
- `THRESHOLD_GAL` is in gal, measured, never guessed

---

### Task 1: Network and broker

**Files:**
- Create: `correlator/mosquitto.conf`

Use a **phone hotspot**, not university WiFi. Campus networks isolate clients from each
other, which silently breaks node-to-broker traffic even though every device shows as
"connected". The hotspot removes that entire class of problem from your demo.

- [ ] **Step 1: Start the hotspot and join it with your laptop**

- [ ] **Step 2: Find your laptop's IP on the hotspot**

```bash
ipconfig getifaddr en0
```

If that prints nothing, the hotspot is on a different interface — try `en1`, or
`ifconfig | grep "inet "` and pick the `192.168.x.x` address. Write it down; this is
`MQTT_HOST`.

- [ ] **Step 3: Install mosquitto**

```bash
brew install mosquitto
```

- [ ] **Step 4: Write the broker config**

Mosquitto 2.x binds to localhost only and refuses anonymous clients by default. Without this
file the nodes cannot connect, and the symptom is a silent reconnect loop with no error on
the broker side.

```
# correlator/mosquitto.conf
# Demo broker: open on the LAN, no auth. Intended for a private phone hotspot.
listener 1883 0.0.0.0
allow_anonymous true
```

**Security note:** this broker accepts any client on the network with no credentials. That is
acceptable on a phone hotspot you control for a classroom demo. Do not run this
configuration on university WiFi, a home network shared with others, or anything
internet-facing. If you later need it on an untrusted network, add `password_file` and TLS.

- [ ] **Step 5: Start the broker in verbose mode**

```bash
mosquitto -c correlator/mosquitto.conf -v
```

Expected: `Opening ipv4 listen socket on port 1883`. Leave this running in its own terminal —
its log is your best debugging tool for the rest of this plan.

- [ ] **Step 6: Verify the broker locally**

In a second terminal:

```bash
mosquitto_sub -h 127.0.0.1 -t 'test/#' -v &
mosquitto_pub -h 127.0.0.1 -t 'test/hello' -m 'works'
```

Expected: `test/hello works`. Kill the subscriber with `kill %1`.

- [ ] **Step 7: Allow incoming connections through the macOS firewall**

If System Settings → Network → Firewall is on, macOS will prompt to allow incoming
connections for `mosquitto` the first time. Allow it. If you dismissed the prompt, the nodes
will fail to connect while local tests still pass — a confusing combination. Toggle the
firewall off for the demo, or add mosquitto to the allow list.

- [ ] **Step 8: Commit**

```bash
git add correlator/mosquitto.conf
git commit -m "chore: mosquitto config for LAN access

Mosquitto 2.x is localhost-only and anonymous-denied by default, which
makes nodes fail to connect with no broker-side error."
```

---

### Task 2: Measure the real noise floor

**Files:**
- Create: `firmware/calibrate/calibrate.ino`
- Create: `tools/rms.py`

This answers the open question in the design: **is the noise floor set by the sensor
(~0.9 gal predicted) or by the building?** Whatever number you measure is a real finding for
your report.

`calibrate.ino` is self-contained and does not include `detector.h` — Arduino only compiles
sources inside the sketch folder, and duplicating six lines of EMA is cheaper than fighting
the build system.

- [ ] **Step 1: Write the calibration sketch**

```cpp
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
```

- [ ] **Step 2: Write the RMS tool**

```python
# tools/rms.py
"""Read dev_gal values on stdin, print RMS and a suggested threshold."""
import math
import sys

vals = []
for line in sys.stdin:
    line = line.strip()
    try:
        vals.append(float(line))
    except ValueError:
        continue        # header, boot noise, serial garbage

if len(vals) < 100:
    sys.exit(f"only {len(vals)} samples parsed - capture longer")

# Discard the first 3 s: the EMA is still settling and would inflate the RMS.
vals = vals[300:]

rms = math.sqrt(sum(v * v for v in vals) / len(vals))
print(f"samples      {len(vals)}")
print(f"seconds      {len(vals) / 100:.1f}")
print(f"RMS          {rms:.3f} gal")
print(f"peak         {max(vals):.3f} gal")
print(f"threshold    {rms * 10:.2f} gal   (10x RMS)")
```

- [ ] **Step 3: Capture 60 seconds from node-01**

Put the node on the desk where it will live. **Do not touch the desk during capture** — no
typing, no leaning. Substitute your port.

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/calibrate
arduino-cli upload -p /dev/cu.usbserial-0001 --fqbn esp32:esp32:esp32 firmware/calibrate
arduino-cli monitor -p /dev/cu.usbserial-0001 -c baudrate=115200 > /tmp/node01.csv
```

Wait 65 seconds, then Ctrl-C.

- [ ] **Step 4: Compute node-01's noise floor**

```bash
python tools/rms.py < /tmp/node01.csv
```

Expected: RMS somewhere between roughly 0.3 and 5 gal. Write the number down.

Interpreting it, for your report:

| RMS | Meaning |
|---|---|
| ~0.5–1.5 gal | Sensor-limited. Matches the predicted ~0.9 gal. Shindo 3 (2.5–8 gal) is detectable. |
| 3–10 gal | Building-limited. Foot traffic, HVAC, or a resonant desk dominates. Real-quake floor is higher than predicted. |
| > 20 gal | Something is wrong — loose wiring, a fan on the desk, or the node moved. Re-seat the jumpers and recapture. |

- [ ] **Step 5: Repeat for node-02**

```bash
arduino-cli upload -p /dev/cu.usbserial-0002 --fqbn esp32:esp32:esp32 firmware/calibrate
arduino-cli monitor -p /dev/cu.usbserial-0002 -c baudrate=115200 > /tmp/node02.csv
python tools/rms.py < /tmp/node02.csv
```

- [ ] **Step 6: Pick one shared threshold**

The two nodes will not match — different sensor units and different spots on the desk. But
both run byte-identical firmware, so there is one threshold.

**Use 10× the *higher* of the two RMS values.** The noisier node sets the limit; a threshold
below its noise floor would make it fire constantly and destroy the correlation rule.

Record both RMS values anyway. The difference between two nominally identical sensors is a
legitimate measured result worth a sentence in your report.

- [ ] **Step 7: Commit the tools**

```bash
git add firmware/calibrate/calibrate.ino tools/rms.py
git commit -m "feat: noise floor calibration sketch and RMS tool

Answers whether the detection floor is set by the MPU6050 or by building
vibration. Discards the first 3 s so the settling EMA does not inflate
the RMS."
```

---

### Task 3: Flash the real firmware

**Files:**
- Modify: `firmware/node/config.h` (not committed)

- [ ] **Step 1: Fill in the measured values**

Edit `firmware/node/config.h`:

```cpp
#define MQTT_HOST      "192.168.1.100"   // your laptop's hotspot IP from Task 1
#define THRESHOLD_GAL  12.5f             // 10x the higher RMS from Task 2
```

- [ ] **Step 2: Flash node-01**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/node
arduino-cli upload -p /dev/cu.usbserial-0001 --fqbn esp32:esp32:esp32 firmware/node
```

- [ ] **Step 3: Read node-01's serial output and record its node ID**

```bash
arduino-cli monitor -p /dev/cu.usbserial-0001 -c baudrate=115200
```

Expected:

```
id=node-a4c1f8 threshold=12.5 gal
```

Write the ID down — you need it for the test plan and the report. Ctrl-C to exit.

If you see `MPU6050 not responding` and a fast-blinking LED, the wiring broke. Re-run the
I2C scanner from plan 01 Task 4.

- [ ] **Step 4: Flash node-02 and record its ID**

Same commands, node-02's port. Same firmware, different ID.

- [ ] **Step 5: Verify both nodes are publishing telemetry**

```bash
mosquitto_sub -h 127.0.0.1 -t 'quake/#' -v
```

Expected: two distinct lines repeating about once a second:

```
quake/node-a4c1f8/tel {"node":"node-a4c1f8","dev_gal":0.42,"uptime_s":31}
quake/node-b7e220/tel {"node":"node-b7e220","dev_gal":0.55,"uptime_s":29}
```

Troubleshooting, in order of likelihood:

| Symptom | Cause |
|---|---|
| No messages at all | Nodes not on the hotspot. Check `WIFI_SSID` / `WIFI_PASSWORD` in config.h. |
| No messages, WiFi fine | Wrong `MQTT_HOST`. Re-run `ipconfig getifaddr en0` — hotspot IPs change. |
| No messages, host right | macOS firewall blocking mosquitto (Task 1 Step 7) |
| Only one node | The other's config.h was not re-flashed, or its USB power is dead |
| `dev_gal` huge and rising | Node is being touched, or a fan is blowing on it |

- [ ] **Step 6: Verify the end-to-end path with the correlator**

Broker in terminal 1, then:

```bash
source .venv/bin/activate
cd correlator && python main.py --broker 127.0.0.1
```

Expected: `connected (Success), subscribing quake/+/event`. Now tap **both** breadboards at
once. Expected: two `event` lines, then an `ALARM` line, and the buzzer on node-01 sounds.

If events print but no alarm ever fires, the two taps were more than 2 s apart. Tap harder
and closer together.

- [ ] **Step 7: Record the results**

Create `docs/RESULTS.md`:

```markdown
# Measured Results

## Noise floor (60 s, quiet desk, 100 Hz)

| Node | ID | RMS (gal) | Peak (gal) |
|---|---|---|---|
| node-01 | node-XXXXXX | 0.00 | 0.00 |
| node-02 | node-XXXXXX | 0.00 | 0.00 |

Shared threshold: 0.00 gal (10x the higher RMS).

**Is the floor sensor-limited or building-limited?** [Fill in from the Task 2 Step 4 table.]
The design predicted ~0.9 gal from the MPU6050's ~400 ug/sqrt(Hz) over a 0.2-5 Hz band.

## Detectable intensity

JMA shindo bands: 1 = 0.2-0.8 gal, 2 = 0.8-2.5, 3 = 2.5-8, 4 = 8-25.
With a threshold of 0.00 gal, the lowest detectable shindo is [fill in].

## Captured real events

| Date/time | Peak (gal) | Nodes | JMA published shindo |
|---|---|---|---|
| _(none yet)_ | | | |

Cross-check against https://www.data.jma.go.jp/eqdb/data/shindo/
```

- [ ] **Step 8: Commit**

```bash
git add docs/RESULTS.md
git commit -m "docs: measured noise floor and threshold"
```

---

## Done when

- `mosquitto_sub -h 127.0.0.1 -t 'quake/#' -v` shows telemetry from **two distinct** node IDs
- Tapping both breadboards produces one `ALARM` and the buzzer sounds
- `docs/RESULTS.md` has real numbers, not zeros

Next: [05-integration-testing.md](05-integration-testing.md)
