# Testing without hardware

Everything here runs on your laptop. No ESP32, no sensor, no breadboard.

A mock node generates synthetic acceleration, runs **the same detection algorithm as the
firmware**, and speaks the real MQTT contract. Mosquitto runs in Docker. So the whole system
— detect, publish, correlate, alarm, buzz — can be exercised and debugged before your parts
arrive.

---

## Setup (once)

```bash
docker compose up -d                       # Mosquitto on localhost:1883
python3 -m venv .venv
source .venv/bin/activate
pip install -r correlator/requirements.txt
```

Check the broker came up:

```bash
docker compose ps                          # STATUS should say Up
```

**Always `source .venv/bin/activate` first.** Calling the venv by relative path
(`../.venv/bin/python`) works but spews `RuntimeWarning` noise.

---

## 1. Unit tests — no Docker needed

```bash
cd test && make run && cd ..               # C++ detector, 6 tests
source .venv/bin/activate
pytest sim/test_parity.py correlator/test_core.py -q
```

Expected:

```
all detector tests passed
14 passed
```

Five suites. The parity one is the load-bearing one:

| Suite | Tests | Broker? | What it proves |
|---|---|---|---|
| `test/test_detector.cpp` | 6 | no | The **firmware** algorithm is correct |
| `sim/test_parity.py` | 6 | no | The **Python port** gives identical results — so the mock is faithful |
| `correlator/test_core.py` | 8 | no | The correlation rule is correct |
| `sim/test_e2e.py` | 3 | yes | The whole loop works, mock nodes to alarm to buzzer |
| `dashboard/test_dashboard.py` | 6 | yes | The dashboard aggregates state correctly |

Everything at once, once Docker is up: `pytest sim correlator dashboard -q` → **23 passed**.

If parity ever fails, the mock has drifted from the firmware and mock results stop meaning
anything. `sim/detector.py` and `firmware/node/detector.cpp` must be changed together.

---

## 2. End-to-end tests — needs Docker

```bash
docker compose up -d
source .venv/bin/activate
pytest sim/test_e2e.py -q
```

Expected: `3 passed in ~30s`. Takes 30 s because it runs in real time.

These spawn real processes talking over the real broker:

- **single channel → events but no alarm** — the core negative case
- **two channels agreeing → exactly one alarm** — including that cooldown suppresses repeats
- **alarm reaches the node as a buzzer** — proves the return path, not just a printed line

They skip themselves with a clear message if the broker is down, so `pytest` never fails
merely because Docker is not running.

---

## 3. Watch it work

Three terminals, `source .venv/bin/activate` in each.

```bash
# 1 — correlator
cd correlator && python main.py --broker localhost

# 2 — mock node A (Enter = shake)
cd sim && python mock_node.py --broker localhost --node-id mock-aaa

# 3 — mock node B
cd sim && python mock_node.py --broker localhost --node-id mock-bbb
```

**Shake one node only** — press Enter in terminal 2. Expect an event and an LED line, and
**no alarm**. One channel is not agreement.

**Shake both** — press Enter in both within 2 seconds. Real output from a run:

```
event  mock-aaa  peak=41.87 gal
event  mock-bbb  peak=41.60 gal
ALARM  ['mock-aaa', 'mock-bbb']  peak=41.87 gal
```

and in the node terminals:

```
[mock-aaa] LED on  (dev=39.74 gal)
[mock-aaa] LED off EVENT peak=41.87 gal dur=590 ms
[mock-aaa] *** BUZZER *** {"nodes": ["mock-aaa", "mock-bbb"], "peak_gal": 41.87}
```

Shake both again straight away and you get events but **no second alarm** — the 10 s cooldown
collapsing one earthquake into one alarm.

### Useful flags

| Flag | Does |
|---|---|
| `--auto-shake 5` | Shake every 5 s instead of waiting for Enter |
| `--noise 3.0` | Louder synthetic desk noise, in gal RMS |
| `--threshold 5.0` | Trigger threshold in gal |
| `--warmup-ms 500 --refractory-ms 1000` | Speed up the timing constants for quick experiments |
| `--seed 1` | Reproducible noise |

Try `--noise 8 --threshold 5` to watch a badly-tuned threshold fire constantly. That is the
failure mode plan 05's tuning task exists to catch.

---

## 4. The dashboard

The presentation layer. Subscribes to the broker directly and serves one self-contained page —
no build step, no CDN, no accounts, works offline.

```bash
source .venv/bin/activate
python dashboard/server.py --broker localhost
open http://localhost:8000
```

With mock nodes running (section 3) you get:

- a **banner** that turns red on alarm and names the agreeing channels
- **live traces** of `dev_gal` per channel, with simulated channels tagged and dead ones
  marked offline after 5 s of silence
- an **event log** with alarms highlighted
- the **headline metric**: single-channel events rejected — each of which would have been a
  false alarm on a single-channel design

It is deliberately separate from the correlator: detection must not depend on whether a browser
is open. Kill the dashboard and alarms still fire.

Tested by `dashboard/test_dashboard.py`, which starts the real server, publishes real MQTT, and
reads the real HTTP endpoint:

```bash
pytest dashboard -q
```

Expected: `6 passed`.

## 5. Compile the firmware — still no hardware

You cannot run the sketch without an ESP32, but you can prove it builds. This catches every
syntax error, missing include, and type mistake before your parts arrive.

```bash
brew install arduino-cli
arduino-cli config init
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32          # large download, few minutes
arduino-cli lib install PubSubClient

cp firmware/node/config.h.example firmware/node/config.h
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/node
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/i2c_scan
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/calibrate
```

Expected for `firmware/node`:

```
Sketch uses 921932 bytes (70%) of program storage space.
Global variables use 48304 bytes (14%) of dynamic memory.
```

70% flash and 14% RAM leaves plenty of headroom. Worth re-checking after any firmware change —
if flash creeps toward 100%, that is the number that tells you.

To see warnings the default build hides:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 --warnings all --clean firmware/node
```

Expected: no output beyond the size summary.

## 6. Optional: Thingsboard in Docker

The local dashboard in section 4 is the presentation layer. Thingsboard is optional on top, if
your course wants a named IoT platform in the report.

```bash
docker compose --profile cloud up -d       # ~2 GB, a few minutes on first boot
```

Then http://localhost:8080, log in as `tenant@thingsboard.org` / `tenant`. **Devices → + → Add
new device**, name it `quake-net`, open it and copy the access token from **Details**. Then:

```bash
export TB_TOKEN='your-device-token'
export TB_HOST=localhost
export TB_PORT=1884                        # remapped so it cannot clash with Mosquitto
cd correlator && python main.py --broker localhost
```

Expected first line: `thingsboard connected: localhost:1884`. Shake two channels, then check
**Devices → quake-net → Latest telemetry**. Verified keys:

```
alarm            1
alarm_nodes      mock-tb1,mock-tb2
alarm_peak_gal   41.52
dev_gal_<node>   0.43
event_node       mock-tb1
event_peak_gal   41.50
```

Build a dashboard from those keys with **Dashboards → + → Create new dashboard**: a time-series
widget on `dev_gal_<node>`, latest-value cards on `event_peak_gal` and `alarm`.

To use the hosted instance instead of Docker, drop `TB_HOST`/`TB_PORT` — they default to
`demo.thingsboard.io:1883`.

Without `TB_TOKEN` the correlator prints `running local-only` and everything else works. The
cloud is never load-bearing — that is deliberate, so a dead internet connection cannot kill
your demo.

---

## What the mocks do NOT cover

Be honest about this in your report. Passing every test above — including the compile — still
leaves these unproven:

- **I2C** — wiring, the `0x68` address, register reads
- **WiFi** — connection, reconnection, the blocking-`connect()` stall the firmware guards against
- **The real 100 Hz sample gate** under actual load
- **Your actual noise floor** — the whole point of calibration. Synthetic noise is a guess.
- **Whether an MPU6050 on your desk can see a real earthquake**

The mock proves the *logic* is right. The hardware plans prove the *system* is right.

---

## When your parts arrive

Work through the plans in order — the mock work above already completed plan 03:

[docs/superpowers/plans/2026-07-30-quake-net/00-index.md](docs/superpowers/plans/2026-07-30-quake-net/00-index.md)

Point the ESP32 at the same Docker broker: set `MQTT_HOST` in `firmware/node/config.h` to your
laptop's IP (`ipconfig getifaddr en0`), not `localhost`. The mock nodes and the real node can
run side by side on the same broker — that is a good first hardware test, because the real
node correlating with a mock proves the firmware speaks the contract correctly.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `3 skipped` on the e2e tests | Broker down. `docker compose up -d` |
| `ConnectionRefusedError` | Same. Check `docker compose ps`. |
| `ModuleNotFoundError: core` | Run the correlator from inside `correlator/` |
| `ModuleNotFoundError: paho` | venv not activated, or requirements not installed |
| `RuntimeWarning: Unexpected value in sys.prefix` | You called `../.venv/bin/python`. Activate instead. Harmless. |
| Events but never an alarm | The two Enters were more than 2 s apart, or you are inside the 10 s cooldown |
| Alarm with only one node running | Should be impossible. Check for a leftover `mock_node.py`: `pgrep -fl mock_node` |
| Port 1883 already in use | Another broker is running. `brew services stop mosquitto`, or `docker compose down` |

Stop everything:

```bash
docker compose --profile cloud down
pkill -f mock_node.py; pkill -f fake_node.py; pkill -f dashboard/server.py
```

Stray publishers are worth checking for: the dashboard aggregates **every** node on the broker,
so a forgotten `mock_node.py` inflates its counters.

```bash
pgrep -fl "mock_node|fake_node|main.py --broker|dashboard/server" || echo "all stopped"
```
