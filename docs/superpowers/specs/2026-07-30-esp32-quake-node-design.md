# Networked Earthquake Detection Node — Design

Date: 2026-07-30
Status: Approved for planning

## Goal

Build the cheapest useful node for a distributed earthquake-detection network, for a
university IoT course in Japan. Two identical nodes publish shake events over MQTT; a
correlator only declares an earthquake when both nodes agree within a short time window.

The correlation rule is the point of the project. A single accelerometer cannot tell a
passing truck from a quake. Two nodes can, because local noise is local and ground motion
is not.

## Non-goals

These were considered and deliberately cut. Reintroducing any of them should be a conscious
decision, not drift.

| Cut | Reason |
|---|---|
| More than two nodes | Two is the minimum that demonstrates correlation. More nodes add cost, not concept. |
| NTP time synchronisation | The correlator timestamps events on arrival. MQTT latency is ~100 ms against a 2 s correlation window, so node-side clocks are unnecessary. |
| JMA calculated seismic intensity (計測震度) | The official algorithm needs a specified frequency-domain filter and the 0.3 s rule. Out of proportion to the course. Report peak acceleration in gal instead. |
| Epicentre location / triangulation | Requires sub-millisecond timing. Not achievable over WiFi with two nodes. Must not be claimed in the report. |
| Cloud MQTT broker | A broker on the presenter's laptop needs no account, no TLS, and no cooperation from university WiFi. Swapping to a cloud broker later is a one-line change. |
| OLED display, microSD logging, battery power | No function the dashboard does not already provide. |

## Hardware

Per-node cost ~¥2,130; total ~¥5,100 including the shared breadboard and the single buzzer.

| Part | Qty | Price | Source |
|---|---|---|---|
| ESP32-DevKitC-32E (ESP32-WROOM-32E, 4 MB) | 2 | ¥3,600 | [Akizuki M-15673](https://akizukidenshi.com/catalog/g/g115673/), ¥1,800 ea — confirmed |
| MPU6050 / GY-521 accelerometer module | 2 | ~¥600 | Amazon.co.jp, any seller — price unconfirmed |
| Active buzzer module, 3-pin | 1 | ~¥100 | Akizuki or Amazon.co.jp |
| 5 mm LED + 330 Ω resistor | 2 | ~¥60 | Akizuki |
| Breadboard and jumper wires | 1 set | ~¥700 | Akizuki |

The ESP32-DevKitC is chosen over the cheaper ESP32-C3 SuperMini (~¥700) because every
MPU6050 tutorial targets the classic board. At two nodes the ¥1,800 difference does not
justify the setup friction.

The MPU6050 is the cheapest and best-documented option. Its noise floor is roughly
400 µg/√Hz, which over a 0.2–5 Hz band works out to about 0.9 gal RMS. JMA shindo 3
corresponds to roughly 2.5–8 gal, so shindo 3 and above should sit clearly above sensor
noise, while shindo 1–2 will not. Whether ambient building vibration dominates that figure
in practice is an open question (see below).

### Wiring

Both nodes are wired identically. The buzzer is fitted to node-01 only.

```
MPU6050        ESP32
  VCC   ──────  3V3
  GND   ──────  GND
  SCL   ──────  GPIO22
  SDA   ──────  GPIO21

LED    ──────  GPIO26  (through 330 Ω to GND)
Buzzer ──────  GPIO25  (node-01 only)
```

## Node firmware

Three responsibilities, each independent: sample the sensor, decide whether a shake
happened, publish. Nothing in the detector knows about MQTT, and nothing in the transport
knows about acceleration.

### Sampling

100 Hz, gated on `micros()`. Read all three accelerometer axes over I2C at ±2 g full scale
(16384 LSB/g). Convert to gal: `gal = g * 980.665`.

### Detection

```
mag      = sqrt(ax² + ay² + az²)
baseline = 0.99 * baseline + 0.01 * mag
dev      = abs(mag - baseline)
if dev > THRESHOLD and not in_refractory:
    trigger()
```

The exponential moving average is a single-pole high-pass filter. It removes the ~980 gal
gravity offset without a filter library, and adapts if the node is tilted.

Two details that otherwise cause misbehaviour:

- **Warm-up suppression.** `baseline` starts at zero, so `dev` is enormous for the first
  few hundred samples. Suppress all triggers for the first 3 seconds after boot.
- **Refractory period.** A single shake lasts seconds and would otherwise emit hundreds of
  events. After a trigger, ignore further triggers for 5 seconds and report the peak `dev`
  observed during that window. The event is published at the *end* of the refractory window,
  so `peak_gal` is the true peak and `dur_ms` is the time from trigger to the last sample
  still above threshold.

### Threshold calibration

`THRESHOLD` is in gal, the same units as `dev`. Do not hardcode a guessed value. On a quiet
desk, log `dev` for 60 seconds and record its RMS. Measure **both** nodes — they will differ,
being different sensor units on different spots of the desk.

Set a **single shared threshold** to 10× the *higher* of the two RMS values. Both nodes run
byte-identical firmware, so there is one threshold; and the noisier node has to set it, since
a threshold below its noise floor would make it fire continuously and destroy the correlation
rule. Record both RMS figures anyway — the spread between two nominally identical sensors is a
legitimate measured result for the report.

### Identity

Node ID is derived from the WiFi MAC: the last three bytes as hex, e.g. `node-a4c1f8`.
No per-node configuration, so both nodes run byte-identical firmware.

## MQTT contract

Broker: Mosquitto on the presenter's laptop, port 1883, no TLS, no authentication. Nodes
and laptop share a phone hotspot, which removes university WiFi and captive portals from
the demo entirely.

**`quake/<node_id>/event`** — published on trigger:

```json
{ "node": "node-a4c1f8", "peak_gal": 42.7, "dur_ms": 1800 }
```

**`quake/<node_id>/tel`** — published at 1 Hz, so the dashboard is populated between
events:

```json
{ "node": "node-a4c1f8", "dev_gal": 0.8, "uptime_s": 431 }
```

**`quake/alarm`** — published by the correlator, subscribed by node-01 to sound the buzzer:

```json
{ "nodes": ["node-a4c1f8", "node-b7e220"], "peak_gal": 42.7 }
```

The LED is driven locally on each node's own trigger. The buzzer fires only on `quake/alarm`.
That split is what makes the demo legible: an LED means "this node felt something", the
buzzer means "the network agrees".

## Correlator

A Python script on the laptop using `paho-mqtt`, subscribing to `quake/+/event`.

Keep a list of recent events with arrival timestamps. On each event, discard entries older
than 2 seconds, then count distinct node IDs remaining. If the count reaches 2, publish
`quake/alarm` with the maximum `peak_gal` seen, and enter a 10-second cooldown so one
earthquake produces one alarm.

Arrival-time stamping is why no clock synchronisation is needed. It assumes broker-to-node
latency is small and similar across nodes, which holds on a single hotspot.

## Error handling

| Condition | Behaviour |
|---|---|
| MPU6050 absent or not answering at boot | Blink LED at 5 Hz and retry I2C init every second. Never publish garbage. |
| WiFi or MQTT connection lost | Detection continues and the LED still fires. Reconnect attempts are non-blocking so sampling never stalls. Events during the outage are dropped, not queued — a stale event would corrupt the correlator's time window. |
| One node offline | Correlator can never reach 2 nodes, so no alarm fires. Correct behaviour, and worth demonstrating. |
| Correlator not running | Nodes publish normally, LEDs work, buzzer stays silent. |

## Testing

1. **Sensor sanity.** Print raw gal at 1 Hz. Rotate the node through all axes and confirm
   the magnitude stays near 980 gal.
2. **Warm-up.** Reboot and confirm no event is published in the first 3 seconds.
3. **Single-node rejection.** Tap node-01 only. LED lights, no alarm. This is the core
   negative test.
4. **Correlated detection.** Shake the table both nodes rest on. Both LEDs light, buzzer
   fires, one alarm message.
5. **Refractory.** Shake continuously for 20 seconds. Expect roughly four events per node,
   not hundreds.
6. **Network resilience.** Disconnect node-02's power mid-run. Confirm no alarm, no
   correlator crash, and clean recovery when it returns.

## Demo

Tap one node — LED only, no alarm, "rejected as local noise". Then shake the table both
nodes sit on — both LEDs, buzzer, alarm on the dashboard. The contrast between those two
actions is the whole project.

## Chance of catching a real event

Shindo 3+ is common enough in Japan to be worth waiting for. Over 1923–2014 the per-
prefecture average was 474 shindo-3+ events in 92 years (~5/year), and Tokyo recorded 2,549
(~28/year) — see [todo-ran prefecture ranking](https://todo-ran.com/t/kiji/18560) and
[tenki.jp shindo-3+ log](https://earthquake.tenki.jp/bousai/earthquake/entries/level-3/index.html).
On the Tokyo figure, a three-month semester would expect roughly 5–7 opportunities.

Treat those numbers as approximate. They come from secondary aggregators, and a separate
2018 figure in the same search (238 shindo-1+ events nationwide) looks inconsistent with
JMA's usual annual counts, so at least one source is miscounting. Check
[JMA's shindo database](https://www.data.jma.go.jp/eqdb/data/shindo/) directly for the
authoritative count for your prefecture before quoting a number in the report.

## Open question

One remains, and the build answers it for free: **is the real noise floor set by the sensor
or by the building?** The threshold calibration in step 4 measures exactly this. If quiet-desk
RMS lands near the predicted ~0.9 gal, the MPU6050 dominates and shindo 3 is detectable. If
it lands well above, building vibration dominates and the floor is higher. Either result is
a legitimate measured finding — report the number you get.

If real-event capture turns out to be unlikely, the project still stands on the correlation
demonstration. Real capture is a bonus, not a requirement.
