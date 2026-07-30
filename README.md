# Networked Earthquake Detection

Two ESP32 nodes, one accelerometer each, publishing shake events over MQTT. A correlator
declares an earthquake only when both nodes agree within 2 seconds — so a passing truck
that shakes one node is rejected, while ground motion that shakes both is not.

University IoT course project. Japan.

## Why two nodes

A single accelerometer cannot distinguish local vibration from ground motion. Adding a
second node and requiring agreement is the cheapest way to get that discrimination, and it
is the approach used by real dense-array networks such as the Community Seismic Network
and MyShake.

## Parts (~¥4,700)

| Part | Qty |
|---|---|
| ESP32-DevKitC (ESP32-WROOM-32E, 38-pin) | 2 |
| MPU6050 / GY-521 accelerometer module | 2 |
| Active buzzer module, 3-pin | 1 |
| 5 mm LED + 330 Ω resistor | 2 |
| Breadboard and jumper wires | 1 set |

## Wiring

Identical on both nodes. Buzzer on node-01 only.

```
MPU6050        ESP32
  VCC   ──────  3V3
  GND   ──────  GND
  SCL   ──────  GPIO22
  SDA   ──────  GPIO21

LED    ──────  GPIO26  (through 330 Ω to GND)
Buzzer ──────  GPIO25  (node-01 only)
```

## Running it

1. Start a broker on your laptop and note its IP:

   ```
   brew install mosquitto
   mosquitto -v
   ```

2. Put the laptop and both nodes on the same phone hotspot. This avoids university WiFi
   and captive portals during the demo.

3. Flash both nodes with the same firmware — node IDs derive from the WiFi MAC, so there is
   no per-node configuration.

4. Calibrate each node's threshold: log deviation on a quiet desk for 60 seconds, then set
   the threshold to 10× the RMS you measured. The two nodes will not match; that is
   expected.

5. Run the correlator:

   ```
   python correlator.py --broker <laptop-ip>
   ```

## MQTT topics

| Topic | Direction | Payload |
|---|---|---|
| `quake/<node_id>/event` | node → broker | `{"node","peak_gal","dur_ms"}` on trigger |
| `quake/<node_id>/tel` | node → broker | `{"node","dev_gal","uptime_s"}` at 1 Hz |
| `quake/alarm` | correlator → node-01 | `{"nodes":[...],"peak_gal"}` |

LED means this node felt something. Buzzer means the network agrees.

## Demo

Tap one node: LED lights, no alarm — rejected as local noise. Shake the table both nodes
rest on: both LEDs light, buzzer sounds, alarm appears on the dashboard.

## What this does not do

It does not locate an epicentre — that needs sub-millisecond timing, which WiFi cannot
provide. It does not compute official JMA seismic intensity; it reports peak acceleration
in gal. Sensor noise puts the realistic floor near shindo 3, so smaller tremors will not
register.

## Documentation

- [Design](docs/superpowers/specs/2026-07-30-esp32-quake-node-design.md) — architecture,
  detection algorithm, error handling, test plan, and the list of features deliberately cut.
