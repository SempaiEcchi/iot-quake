# Quake-Net Implementation Plans — Index

One ESP32 detects shaking; a correlator declares an earthquake only when two channels agree
within 2 seconds. Design: [../../specs/2026-07-30-esp32-quake-node-design.md](../../specs/2026-07-30-esp32-quake-node-design.md)

Six plans. Run them in order — each depends on the one before.

| # | Plan | Deliverable | Blocked by |
|---|---|---|---|
| 01 | [Procurement & assembly](01-procurement-and-assembly.md) | Wired node, I2C verified | — |
| 02 | [Node firmware](02-node-firmware.md) | Sketch that detects and publishes | 01 |
| 03 | [Correlator & simulated node](03-correlator.md) | Python services, host-tested | — (parallel with 01/02) |
| 04 | [Bringup & calibration](04-bringup-and-calibration.md) | Node live, threshold measured, dashboard up | 01, 02, 03 |
| 05 | [Integration testing](05-integration-testing.md) | Six spec tests passing, results recorded | 04 |
| 06 | [Public release](06-public-release.md) | Public GitHub repo | 05 |

Plan 03 needs no hardware — write it while parts ship.

## Order rationale

Firmware before flashing, because the detector is tested on your laptop with fake data before
it ever touches an ESP32. Debugging an algorithm through a serial cable is miserable;
debugging it with `assert` on your laptop takes seconds. Same for the correlator.

Calibration (04) must come before testing (05): the tests reference threshold values that 04
measures. Do not guess thresholds to unblock 05.

## Architecture

```
[ESP32 + MPU6050] ──┐
                    ├──► Mosquitto ──► correlator ──┬──► quake/alarm ──► buzzer
[fake_node.py]    ──┘     (laptop)                  └──► Thingsboard (dashboard)
   (laptop)
```

Channel A is the real ESP32. **Channel B is simulated** — only one ESP32 is available.
`fake_node.py` speaks the same MQTT contract, so a real second node is a later drop-in.

**`fake_node.py` must never subscribe to channel A's events.** If it echoed them, every real
event would auto-correlate: the alarm would be vacuous and single-node rejection could never
be demonstrated. It publishes only on your keypress.

Both halves follow the same shape: a **pure core** with no I/O, plus a **thin shell** that
wires it to the world.

| Pure core | Shell |
|---|---|
| `firmware/node/detector.cpp` — no Arduino headers | `firmware/node/node.ino` — Wire, WiFi, MQTT |
| `correlator/core.py` — no network | `correlator/main.py` — paho-mqtt, Thingsboard |

The cores are unit-tested on your laptop. The shells are verified by hand in plans 04–05. This
split is why a hardware project can have real tests at all, and it is worth a paragraph in your
report.

## Files at completion

```
firmware/node/
  node.ino          Arduino sketch — sensor, WiFi, MQTT, LED, buzzer
  detector.h        Detection algorithm interface
  detector.cpp      Detection algorithm — pure, no Arduino deps
  config.h          YOUR secrets — gitignored, never committed
  config.h.example  Template, committed
firmware/i2c_scan/
  i2c_scan.ino      Wiring check
firmware/calibrate/
  calibrate.ino     Noise-floor capture
test/
  test_detector.cpp Host unit tests for the detector
  Makefile
correlator/
  core.py           Correlation logic — pure, no network
  main.py           paho-mqtt shell + Thingsboard bridge
  fake_node.py      Simulated second channel
  test_core.py      pytest unit tests
  mosquitto.conf
  requirements.txt
tools/
  rms.py            Noise-floor RMS calculator
docs/
  RESULTS.md        Measured noise floor, thresholds, captured events
  TESTLOG.md        Integration test results
  wiring.md         Wiring notes and photo
```

## Global constraints

These apply to every plan. Exact values, copied from the design.

- **Board:** ESP32-DevKitC-32E, FQBN `esp32:esp32:esp32`
- **Sampling:** 100 Hz (10 000 µs period), gated on `micros()`, **resyncing** rather than
  catching up when more than 10 periods behind
- **Socket timeout:** `mqtt.setSocketTimeout(2)` — PubSubClient's default blocks 15 s
- **Sensor:** MPU6050 at I2C address `0x68`, ±2 g full scale, 16384 LSB/g
- **Unit conversion:** 1 g = 980.665 gal. All acceleration in the code is gal.
- **Pins:** SDA `GPIO21`, SCL `GPIO22`, LED `GPIO26`, buzzer `GPIO25`
- **Detector constants:** `EMA_ALPHA` 0.01, `WARMUP_MS` 3000, `REFRACTORY_MS` 5000
- **Correlator constants:** window 2.0 s, cooldown 10.0 s, `min_nodes` 2
- **Node ID:** last three bytes of the WiFi MAC as lowercase hex, `node-a4c1f8`. The simulated
  channel uses a `sim-` prefix so it can never be mistaken for real in a log.
- **MQTT:** Mosquitto on the laptop, port 1883, no TLS, no auth. Topics:
  - `quake/<node_id>/event` — node → broker, on trigger
  - `quake/<node_id>/tel` — node → broker, 1 Hz
  - `quake/alarm` — correlator → broker, node subscribes
- **Payloads:** built with `snprintf`, not a JSON library. They are three fields long.
- **Libraries:** PubSubClient (knolleary) only. No ArduinoJson, no Adafruit MPU6050 driver —
  the sensor is driven with raw `Wire` register reads, which is ~20 lines and removes two
  dependencies.
- **Python:** 3.11+, `paho-mqtt` 2.x, `pytest`
- **Secrets:** `firmware/node/config.h` holds your WiFi password and is gitignored from its
  first commit. The Thingsboard token is passed via the `TB_TOKEN` environment variable — never
  a tracked file, never a CLI flag (flags land in shell history). Never commit either, not even
  once — git history is public after plan 06.

## Progress

- [ ] 01 Procurement & assembly
- [ ] 02 Node firmware
- [ ] 03 Correlator & simulated node
- [ ] 04 Bringup & calibration
- [ ] 05 Integration testing
- [ ] 06 Public release
