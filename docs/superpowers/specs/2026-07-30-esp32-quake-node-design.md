# Networked Earthquake Detection Node — Design

Date: 2026-07-30
Status: Approved for planning. Revised 2026-07-30 after grilling — see Revision history.

## Goal

Build one network-ready earthquake-detection node, for a university IoT course in Japan. The
node publishes shake events over MQTT. A correlator declares an earthquake only when two
distinct channels agree within a short time window, and a local web dashboard shows the result
live.

The correlation rule is the point of the project. A single accelerometer cannot tell a passing
truck from a quake. Two agreeing channels can, because local noise is local and ground motion
is not.

Only one ESP32 is available, so the second channel is a **simulated node** running on the
laptop. This is stated plainly wherever results are reported. What the project demonstrates is
the protocol and the correlation rule end to end — not two-point physical seismology. Adding a
real second ESP32 later requires no code change, because the simulated node speaks the same
MQTT contract.

## Non-goals

Considered and deliberately cut. Reintroducing any of them should be a conscious decision, not
drift.

| Cut | Reason |
|---|---|
| A second physical node | Only one ESP32 available. The MQTT contract is unchanged by this, so a second node is a drop-in later. |
| Two sensors on one ESP32 (AD0 → `0x69`) | Would give real two-channel physics for ~¥300. Rejected in favour of the simplest build. Noted here because it is the natural upgrade. |
| NTP time synchronisation | The correlator timestamps events on arrival. MQTT latency is ~100 ms against a 2 s window, so node-side clocks are unnecessary. |
| JMA calculated seismic intensity (計測震度) | The official algorithm needs a specified frequency-domain filter and the 0.3 s rule. Out of proportion to the course. Report peak acceleration in gal instead. |
| Epicentre location / triangulation | Requires sub-millisecond timing. Impossible over WiFi, and impossible with one sensor. Must not be claimed. |
| Cloud MQTT broker | The broker is Mosquitto in Docker on the laptop. Nodes stay plaintext with no TLS, and the demo survives an internet outage entirely. |
| A hosted dashboard as the primary UI | `dashboard/server.py` is the presentation layer: no account, no external service, no build step, and it works with the network unplugged. Thingsboard remains wired up behind `--profile cloud` for anyone whose rubric wants a named IoT platform, but nothing depends on it. |
| OLED display, microSD logging, battery power | No function the web dashboard does not already provide. |
| Hardware-timer sampling ISR | A two-line gate resync closes the same failure mode. See Sampling. |

## Architecture

```
[ESP32 + MPU6050] ──┐                     ┌──► quake/alarm ──► buzzer
                    ├──► Mosquitto ──┬──► correlator ──┴──► Thingsboard (optional cloud)
[fake_node.py]    ──┘    (laptop)    │
                                     └──► dashboard ──► http://localhost:8000
```

The **dashboard subscribes to the broker directly rather than reading from the correlator.**
Detection must not depend on whether a browser is watching — killing the dashboard changes
nothing about whether an alarm fires.

Channel A is the real ESP32. Channel B is `fake_node.py`, triggered by a keypress.

**`fake_node.py` must not subscribe to channel A's events.** If it echoed them, every real
event would auto-correlate: the alarm would become vacuous and single-node rejection could
never be shown. It publishes only when you tell it to, and it uses an ID prefixed `sim-` so a
simulated channel can never be mistaken for a real one in a log.

Both halves of the software follow the same shape: a **pure core** with no I/O, plus a **thin
shell** wiring it to the world.

| Pure core | Shell |
|---|---|
| `firmware/node/detector.cpp` — no Arduino headers | `firmware/node/node.ino` — Wire, WiFi, MQTT |
| `correlator/core.py` — no network | `correlator/main.py` — paho-mqtt, Thingsboard |
| — | `dashboard/server.py` — MQTT + HTTP, read-only |

The cores are unit-tested on the laptop with fake acceleration and fake time. That split is
why a hardware project can have real tests, and it is worth a paragraph in the report.

## Hardware

~¥3,100, plus ~¥500 Akizuki shipping and ~¥300 if you need a USB cable.

| Part | Qty | Price | Source |
|---|---|---|---|
| ESP32-DevKitC-32E (ESP32-WROOM-32E, 4 MB) | 1 | ¥1,800 | [Akizuki M-15673](https://akizukidenshi.com/catalog/g/g115673/) — confirmed |
| MPU6050 / GY-521 accelerometer module | 1 | ~¥300 | Amazon.co.jp, any seller — unconfirmed |
| Active buzzer module, 3-pin | 1 | ~¥100 | Akizuki / Silicon House |
| 5 mm LED (pack) | 1 | ~¥100 | Akizuki / Silicon House |
| 330 Ω resistor (pack) | 1 | ~¥100 | Akizuki / Silicon House |
| Breadboard | 1 | ~¥300 | Akizuki / Silicon House |
| Jumper wires, male-male | 1 set | ~¥400 | Akizuki / Silicon House |

In Osaka: シリコンハウス共立, 浪速区日本橋5-8-26, 月–土 10:30–19:30 / 日祝 10:00–19:00. 秋月電子 has
no Osaka store, so its ¥1,800 is the online price; expect ¥2,500–3,000 locally for the board.

The MPU6050's noise floor is roughly 400 µg/√Hz, which over a 0.2–5 Hz band is about 0.9 gal
RMS. **That band is not free.** The EMA in `detector.cpp` supplies only the high-pass end; the
low-pass end comes from the sensor's own DLPF, set via CONFIG (`0x1A`) `DLPF_CFG = 6` → 5 Hz.
Left at the 260 Hz default the floor is √(260/4.8) ≈ 7× worse, around 6 gal, and sampling at
100 Hz does not rescue it — out-of-band noise aliases into the passband rather than vanishing.
Both `node.ino` and `calibrate.ino` set this register, and they must agree, or calibration
characterises a sensor configuration that never runs.

With the filter in place, JMA shindo 3 (roughly 2.5–8 gal) sits above the sensor noise floor
while shindo 1–2 does not. Whether ambient building vibration dominates that figure is
measured during calibration, not assumed.

### Wiring

```
MPU6050 (GY-521)     ESP32-DevKitC-32E
  VCC   ───────────── 3V3        <-- 3.3 V, NOT 5V
  GND   ───────────── GND
  SCL   ───────────── GPIO22
  SDA   ───────────── GPIO21

LED    ───────────── GPIO26  (through 330 Ω to GND)
Buzzer ───────────── GPIO25
```

## Node firmware

### Sampling

100 Hz, gated on `micros()`. Read all three accelerometer axes over I2C at ±2 g full scale
(16384 LSB/g). Convert to gal: `gal = g * 980.665`.

The gate **resyncs rather than catches up** when it falls more than 10 periods behind:

```
if (micros() - next_sample_us > 10 * SAMPLE_US) next_sample_us = micros();
else                                            next_sample_us += SAMPLE_US;
```

Without this, any stall in `loop()` leaves the gate hundreds of periods behind, and it then
fires hundreds of times back to back — all with nearly the same `millis()`. That burst
corrupts the EMA baseline and can bypass warm-up entirely. The matching cause is capped with
`mqtt.setSocketTimeout(2)`: `connect()` blocks whenever the broker is unreachable — the TCP
phase bounded by WiFiClient's own ~3 s default, the MQTT handshake by PubSubClient's, which
defaults to 15 s. The resync makes the stall harmless either way.

### Detection

```
dev      = abs(mag - baseline)        // against the PREVIOUS baseline
baseline = 0.99 * baseline + 0.01 * mag
if dev > THRESHOLD and not in_refractory:
    trigger()
```

The exponential moving average is a single-pole high-pass filter. It removes the ~980 gal
gravity offset without a filter library, and adapts if the node is tilted. Deviation is
computed against the previous baseline so a single spike reports its full amplitude rather
than one already diluted by itself.

Two details that otherwise cause misbehaviour:

- **Warm-up suppression.** `baseline` is seeded to the first sample, but the EMA still needs
  time to settle. Suppress all triggers for the first 3 seconds after boot.
- **Refractory period.** A single shake lasts seconds and would otherwise emit hundreds of
  events. After a trigger, ignore further triggers for 5 seconds. The event publishes when the
  window *closes*, so `peak_gal` is the true peak and `dur_ms` is the time from trigger to the
  last sample above threshold. The published event count therefore lags a sustained shake by
  one window: 20 s of shaking yields three events, not four.

### Threshold calibration

`THRESHOLD` is in gal, the same units as `dev`. Do not hardcode a guessed value. On a quiet
desk, log `dev` for 60 seconds and take its RMS.

The multiplier is a genuine trade-off, and 10× does not sit where the shindo-3 claim needs it:

| Multiplier | Threshold at 0.9 gal RMS | Lowest shindo reached | False triggers |
|---|---|---|---|
| 10× | 9.0 gal | 4 (8–25 gal) | effectively never |
| **5×** | **4.5 gal** | **3 (2.5–8 gal)** | ~1 per two days |
| 3× | 2.7 gal | 3, low end | several per hour |

**Use 5× if the goal is shindo 3.** At 5σ on Gaussian noise band-limited to 5 Hz (~10
independent samples/second) the false-trigger rate is roughly one per two days — and every
one of those is a single-channel event that correlation rejects anyway. 10× is the safe
default when the measured floor turns out to be building-dominated rather than
sensor-dominated. Decide from your measured RMS, and state the multiplier in the report.

### Identity

Node ID is derived from the WiFi MAC: last three bytes as lowercase hex, e.g. `node-a4c1f8`.
The simulated channel uses `sim-` plus a fixed suffix, so the two are never confusable.

## MQTT contract

Broker: Mosquitto on the laptop, port 1883, no TLS, no authentication. The ESP32 and the
laptop share a phone hotspot, which removes university WiFi and captive portals from the demo.
The hotspot's cellular link also carries the correlator's traffic to the cloud dashboard.

**`quake/<node_id>/event`** — published on trigger, by the real node and the simulated one:

```json
{ "node": "node-a4c1f8", "peak_gal": 42.7, "dur_ms": 1800 }
```

**`quake/<node_id>/tel`** — published at 1 Hz, so the dashboard is populated between events:

```json
{ "node": "node-a4c1f8", "dev_gal": 0.8, "uptime_s": 431 }
```

**`quake/alarm`** — published by the correlator, subscribed by the node to sound the buzzer:

```json
{ "nodes": ["node-a4c1f8", "sim-000001"], "peak_gal": 42.7 }
```

The LED is driven locally on the node's own trigger. The buzzer fires only on `quake/alarm`.
That split is what makes the demo legible: an LED means "this channel felt something", the
buzzer means "the network agrees".

## Correlator

A Python service on the laptop using `paho-mqtt`, subscribing to `quake/+/event`.

Keep a list of recent events with arrival timestamps. On each event, discard entries older
than 2 seconds, then count **distinct** node IDs remaining. If the count reaches 2, publish
`quake/alarm` with the maximum `peak_gal` seen, and enter a 10-second cooldown so one
earthquake produces one alarm. Requiring distinct IDs is what stops two events from one
channel faking agreement.

Arrival-time stamping is why no clock synchronisation is needed. It assumes broker-to-client
latency is small and similar across channels, which holds on a single hotspot.

The correlator is also the bridge to the cloud: it forwards telemetry, events, and alarms to
Thingsboard for display. Putting the bridge here rather than in the firmware keeps the node
plaintext and keeps the demo working when the internet does not.

## Error handling

| Condition | Behaviour |
|---|---|
| MPU6050 absent or not answering at boot | Blink LED at 5 Hz and retry I2C init every second. Never publish garbage. |
| I2C read fails mid-run | Skip that sample. Never feed the detector a fabricated value. |
| WiFi or MQTT connection lost | Detection continues and the LED still fires. Socket timeout is capped at 2 s and the sample gate resyncs, so a dead broker costs samples but never corrupts the baseline. Events during an outage are dropped, not queued — a stale timestamp would corrupt the correlator's window. |
| Simulated channel not running | Correlator can never reach 2 distinct nodes, so no alarm fires. Correct behaviour, and the basis of the single-node rejection test. |
| Correlator not running | Node publishes normally, LED works, buzzer stays silent. |
| Internet down | Local path is unaffected — events, correlation, alarm, and buzzer all work. Only the Thingsboard dashboard goes blank. |

## Testing

1. **Sensor sanity.** Print raw gal at 1 Hz. Rotate the node through all axes and confirm the
   magnitude stays near 980 gal.
2. **Warm-up.** Reboot while shaking and confirm no event publishes in the first 3 seconds.
3. **Single-node rejection.** Shake the real node with the simulated channel stopped. LED
   lights, events publish, no alarm. This half of the demo is entirely real and is the core
   negative test.
4. **Correlated detection.** Shake the real node and trigger the simulated channel within 2 s.
   Expect one alarm and the buzzer.
5. **Refractory.** Shake continuously for 20 seconds. Expect three events, not hundreds.
6. **Resilience.** Kill the broker and confirm the LED still responds to shaking. Restart it
   and confirm telemetry resumes unaided.

## Demo

Shake the node alone — LED, no buzzer, "rejected: one channel is not agreement". Then shake it
while triggering the simulated channel — LED, buzzer, alarm on the dashboard. State openly
that channel B is simulated and that what is being shown is the protocol and the rule.

## Honest limitations

State these in the report rather than letting an examiner find them.

- **The second channel is simulated.** Two-point physical discrimination is not demonstrated.
  The protocol, the correlation rule, and the end-to-end path are.
- **A real earthquake will not raise an alarm.** It shakes the real node only, and the simulated
  channel is keypress-triggered, so the correlator can never reach two channels unattended. Real
  events are evidenced from the *event log* cross-checked against JMA, not from alarms. This
  follows directly from having one ESP32 and should be stated before an examiner asks.
- **Correlation rejects only channel-local noise.** With a real second sensor on the same desk
  it would still not reject floor-borne noise such as footsteps, which reaches every sensor.
  Only amplitude thresholds reject that.
- **No epicentre, no official shindo.** Peak acceleration in gal only.
- **Detection floor is around shindo 3 at a 5× threshold, shindo 4 at 10×.** Subject to the
  measured noise floor, which may be building-dominated rather than sensor-dominated.

## Chance of catching a real event

Over 1923–2014 the per-prefecture average was 474 shindo-3+ events in 92 years (~5/year), and
Tokyo recorded 2,549 (~28/year) — see [todo-ran prefecture ranking](https://todo-ran.com/t/kiji/18560)
and [tenki.jp shindo-3+ log](https://earthquake.tenki.jp/bousai/earthquake/entries/level-3/index.html).
On the Tokyo figure a three-month semester would expect roughly 5–7 opportunities.

Treat those numbers as approximate — they come from secondary aggregators, and a separate 2018
figure in the same search (238 shindo-1+ events nationwide) looks inconsistent with JMA's
usual annual counts, so at least one source is miscounting. Check
[JMA's shindo database](https://www.data.jma.go.jp/eqdb/data/shindo/) for the authoritative
count for your prefecture before quoting a number.

## Open question

One remains, and the build answers it for free: **is the real noise floor set by the sensor or
by the building?** Threshold calibration measures exactly this. If quiet-desk RMS lands near
the predicted ~0.9 gal, the MPU6050 dominates and shindo 3 is detectable. If it lands well
above, building vibration dominates and the floor is higher. Either result is a legitimate
measured finding — report the number you get.

If real-event capture turns out to be unlikely, the project still stands on the correlation
demonstration and the measured noise floor. Real capture is a bonus, not a requirement.

## Revision history

**2026-07-30, after grilling.** Six changes:

1. **One ESP32, not two.** Hardware availability. Second channel is now `fake_node.py`.
   BOM ¥5,500 → ~¥3,100.
2. **Cloud dashboard added.** Four earlier references to a "dashboard" described something no
   plan built. Thingsboard now, fed by the correlator.
3. **Broker stays local.** Cloud platforms are broker-plus-dashboard but do not let an outside
   client subscribe to other devices' telemetry, so the correlator had nowhere to live.
   Mosquitto locally, correlator bridges to the cloud.
4. **Sample-gate resync and 2 s socket timeout.** `net_pump()` was described as non-blocking
   but `mqtt.connect()` blocks up to 15 s, and the gate then caught up in a burst that
   corrupted the baseline.
5. **Shared threshold, not per-node.** The earlier text called for per-node thresholds while
   also requiring byte-identical firmware. Moot with one node, but the contradiction is fixed.
6. **Honest limitations section added.** The simulated channel and the floor-borne noise
   caveat are now stated rather than implied.
