# Quake-Net Implementation Plans — Index

Two ESP32 nodes detect shaking; a correlator declares an earthquake only when both agree
within 2 seconds. Design: [../../specs/2026-07-30-esp32-quake-node-design.md](../../specs/2026-07-30-esp32-quake-node-design.md)

Six plans. Run them in order — each depends on the one before.

| # | Plan | Deliverable | Blocked by |
|---|---|---|---|
| 01 | [Procurement & assembly](01-procurement-and-assembly.md) | Two wired nodes, I2C verified | — |
| 02 | [Node firmware](02-node-firmware.md) | Sketch that detects and publishes | 01 |
| 03 | [Correlator](03-correlator.md) | Python service, host-tested | — (parallel with 01/02) |
| 04 | [Bringup & calibration](04-bringup-and-calibration.md) | Both nodes live, thresholds measured | 01, 02, 03 |
| 05 | [Integration testing](05-integration-testing.md) | Six spec tests passing, results recorded | 04 |
| 06 | [Public release](06-public-release.md) | Public GitHub repo | 05 |

Plan 03 needs no hardware — write it while parts ship.

## Order rationale

Firmware before flashing, because the detector is tested on your laptop with fake data
before it ever touches an ESP32. Debugging an algorithm through a serial cable is miserable;
debugging it with `assert` on your laptop takes seconds. Same for the correlator.

Calibration (04) must come before testing (05): the tests reference threshold values that
04 measures. Do not guess thresholds to unblock 05.

## Architecture

```
node-01 ─┐
         ├─► Mosquitto (laptop) ─► correlator.py ─► quake/alarm ─► node-01 buzzer
node-02 ─┘   quake/<id>/event
```

Both halves follow the same shape: a **pure core** with no I/O, plus a **thin shell** that
wires it to the world.

| Pure core | Shell |
|---|---|
| `firmware/node/detector.cpp` — no Arduino headers | `firmware/node/node.ino` — Wire, WiFi, MQTT |
| `correlator/core.py` — no network | `correlator/main.py` — paho-mqtt |

The cores are unit-tested on your laptop. The shells are verified by hand in plans 04–05.
This split is why a hardware project can have real tests at all, and it is worth a paragraph
in your report.

## Files at completion

```
firmware/node/
  node.ino          Arduino sketch — sensor, WiFi, MQTT, LED, buzzer
  detector.h        Detection algorithm interface
  detector.cpp      Detection algorithm — pure, no Arduino deps
  config.h          YOUR secrets — gitignored, never committed
  config.h.example  Template, committed
test/
  test_detector.cpp Host unit tests for the detector
  Makefile
correlator/
  core.py           Correlation logic — pure, no network
  main.py           paho-mqtt shell
  test_core.py      pytest unit tests
  requirements.txt
docs/
  RESULTS.md        Measured noise floor, thresholds, captured events
  wiring.md         Wiring notes and photo
```

## Global constraints

These apply to every plan. Exact values, copied from the design.

- **Board:** ESP32-DevKitC-32E, FQBN `esp32:esp32:esp32`
- **Sampling:** 100 Hz (10 000 µs period), gated on `micros()`
- **Sensor:** MPU6050 at I2C address `0x68`, ±2 g full scale, 16384 LSB/g
- **Unit conversion:** 1 g = 980.665 gal. All acceleration in the code is gal.
- **Pins:** SDA `GPIO21`, SCL `GPIO22`, LED `GPIO26`, buzzer `GPIO25` (node-01 only)
- **Detector constants:** `EMA_ALPHA` 0.01, `WARMUP_MS` 3000, `REFRACTORY_MS` 5000
- **Correlator constants:** window 2.0 s, cooldown 10.0 s, `min_nodes` 2
- **Node ID:** last three bytes of the WiFi MAC as lowercase hex, formatted `node-a4c1f8`.
  Both nodes run byte-identical firmware — no per-node build.
- **MQTT:** Mosquitto on the laptop, port 1883, no TLS, no auth. Topics:
  - `quake/<node_id>/event` — node → broker, on trigger
  - `quake/<node_id>/tel` — node → broker, 1 Hz
  - `quake/alarm` — correlator → broker, node-01 subscribes
- **Payloads:** built with `snprintf`, not a JSON library. They are three fields long.
- **Libraries:** PubSubClient (knolleary) only. No ArduinoJson, no Adafruit MPU6050 driver —
  the sensor is driven with raw `Wire` register reads, which is ~20 lines and removes two
  dependencies.
- **Python:** 3.11+, `paho-mqtt` 2.x, `pytest`
- **Secrets:** `firmware/node/config.h` holds your WiFi password. It is gitignored from the
  first commit in plan 02. Never commit it, not even once — git history is public after
  plan 06.

## Progress

- [ ] 01 Procurement & assembly
- [ ] 02 Node firmware
- [ ] 03 Correlator
- [ ] 04 Bringup & calibration
- [ ] 05 Integration testing
- [ ] 06 Public release
