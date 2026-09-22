# Networked Earthquake Detection

An ESP32 with an accelerometer publishes shake events over MQTT. A correlator declares an
earthquake only when two channels agree within 2 seconds — so a passing truck that shakes one
channel is rejected, while ground motion that shakes both is not.

University IoT course project. Japan.

**One ESP32, so the second channel is simulated.** `fake_node.py` speaks the same MQTT
contract and is triggered by hand. What this project demonstrates is the protocol and the
correlation rule end to end, not two-point physical seismology. A real second node is a
drop-in: no code changes.

## Try it now — no hardware needed

A mock node generates synthetic acceleration, runs the same detection algorithm as the
firmware, and speaks the real MQTT contract. Mosquitto runs in Docker.

```bash
docker compose up -d
python3 -m venv .venv && source .venv/bin/activate
pip install -r correlator/requirements.txt
pytest sim correlator dashboard -q      # unit + end-to-end + dashboard
python dashboard/server.py --broker localhost   # then open localhost:8000
```

The firmware can be compile-checked without an ESP32 too — see TESTING.md §4.

Full guide: **[TESTING.md](TESTING.md)**

## Why correlation

A single accelerometer cannot distinguish local vibration from ground motion. Requiring two
channels to agree is the cheapest way to get that discrimination, and it is the approach used
by real dense-array networks such as the Community Seismic Network and MyShake.

## Parts (~¥3,100)

| Part | Qty | Price |
|---|---|---|
| [ESP32-DevKitC-32E](https://akizukidenshi.com/catalog/g/g115673/) (ESP32-WROOM-32E, 4 MB) | 1 | ¥1,800 |
| MPU6050 / GY-521 accelerometer module | 1 | ~¥300 |
| Active buzzer module, 3-pin | 1 | ~¥100 |
| Breadboard | 1 | ~¥300 |
| Jumper wires, male-male | 1 set | ~¥400 |
| 5 mm LED + 330 Ω resistor (packs) | 1 ea | ~¥200 |

In Osaka: シリコンハウス共立, 浪速区日本橋5-8-26. 秋月電子 is online-only outside Tokyo.

## Wiring

```
MPU6050        ESP32
  VCC   ──────  3V3        <-- 3.3 V, NOT 5V
  GND   ──────  GND
  SCL   ──────  GPIO27
  SDA   ──────  GPIO26

LED    ──────  GPIO2   (onboard on the FNK0090, no wiring)
Buzzer ──────  GPIO25
```

## Architecture

```
[ESP32 + MPU6050] ──┐                     ┌──► quake/alarm ──► buzzer
                    ├──► Mosquitto ──┬──► correlator ──┴──► Thingsboard (optional cloud)
[fake_node.py]    ──┘    (laptop)    │
                                     └──► dashboard ──► http://localhost:8000
```

**`dashboard/server.py` is the presentation layer** — one self-contained page at
`localhost:8000`, no account and no external service, working with the network unplugged.
Thingsboard is wired up behind `docker compose --profile cloud` if a rubric wants a named IoT
platform, but nothing depends on it. The dashboard subscribes to the broker directly, not
through the correlator — detection never depends on a browser being open. The broker stays local so the demo survives an internet outage — events, correlation, alarm,
and buzzer all keep working; only the cloud dashboard goes blank. The correlator forwards to
Thingsboard rather than the firmware doing it, which keeps the node plaintext with no TLS.

Both halves split a **pure core** from a **thin shell**: `detector.cpp` has no Arduino headers
and `core.py` has no network, so both run on your laptop against fake data and fake time.
That is why a hardware project can have real unit tests.

## Running it

1. Start a broker on your laptop and note its IP:

   ```
   docker compose up -d          # or: mosquitto -c mosquitto/mosquitto.conf -v
   ipconfig getifaddr en0
   ```

2. Put the laptop and the node on the same phone hotspot. This avoids university WiFi and
   captive portals, and its cellular link carries the dashboard traffic.

3. Copy `firmware/node/config.h.example` to `config.h`, fill in your WiFi and the broker IP,
   then flash. `config.h` is gitignored — do not commit yours.

4. Calibrate: log deviation on a quiet desk for 60 seconds, set the threshold to 10× the RMS
   you measure. Do not guess it.

5. Run the correlator, the dashboard, and the simulated channel — one terminal each:

   ```
   source .venv/bin/activate
   cd correlator && python main.py --broker <laptop-ip>
   python dashboard/server.py --broker <laptop-ip>     # http://localhost:8000
   cd correlator && python fake_node.py --broker <laptop-ip>
   ```

## MQTT topics

| Topic | Direction | Payload |
|---|---|---|
| `quake/<node_id>/event` | node → broker | `{"node","peak_gal","dur_ms"}` on trigger |
| `quake/<node_id>/tel` | node → broker | `{"node","dev_gal","uptime_s"}` at 1 Hz |
| `quake/alarm` | correlator → node | `{"nodes":[...],"peak_gal"}` |

LED means one channel felt something. Buzzer means the channels agree.

## Demo

Shake the node with the simulated channel stopped: LED lights, event publishes, **no alarm**.
That rejection is entirely real. Then shake it while triggering the simulated channel: LED,
buzzer, alarm on the dashboard.

## Limitations

Stated up front rather than buried.

- **The second channel is simulated.** Two-point physical discrimination is not demonstrated;
  the protocol and the correlation rule are.
- **A real earthquake will not raise an alarm.** It shakes the real node only, and the simulated
  channel is triggered by hand, so real events are evidenced from the event log cross-checked
  against JMA rather than from alarms.
- **Correlation rejects only channel-local noise.** Even with a real second sensor, floor-borne
  noise like footsteps reaches every sensor and correlates. Only amplitude rejects that.
- **No epicentre location** — that needs sub-millisecond timing, which WiFi cannot provide.
- **No official JMA shindo** — peak acceleration in gal only.
- **Detection floor around shindo 3** (at a 5× threshold; shindo 4 at 10×), subject to the
  measured noise floor.

## Documentation

- [SEMINAR.md](SEMINAR.md) — seminar paper (Croatian): motivation, theory, architecture,
  firmware, correlator, testing, measured results, lessons learned, limitations
- [SEMINAR.pptx](SEMINAR.pptx) — 12-slide presentation of the same
- [TESTING.md](TESTING.md) — run and debug the whole system on your laptop, no hardware
- [Design](docs/superpowers/specs/2026-07-30-esp32-quake-node-design.md) — architecture,
  detection algorithm, error handling, and every feature deliberately cut
- [Build plans](docs/superpowers/plans/2026-07-30-quake-net/00-index.md) — step by step, from
  buying parts to publishing
