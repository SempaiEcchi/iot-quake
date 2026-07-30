# Plan 03: Correlator & Simulated Node

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A service that publishes `quake/alarm` only when two distinct channels trigger within 2 seconds, a simulated second channel to stand in for the ESP32 you do not have, and a cloud dashboard fed by the correlator.

**Architecture:** Same split as the firmware — `core.py` holds the correlation rule with no network code and takes `now` as a parameter, so tests drive time directly instead of sleeping. `main.py` is the paho-mqtt shell and the Thingsboard bridge. `fake_node.py` is channel B.

**Tech Stack:** Python 3.11+, paho-mqtt 2.x, pytest, Thingsboard

**No hardware needed.** Do all of this while parts ship.

## Global Constraints

See [00-index.md](00-index.md#global-constraints). Relevant here:

- Window 2.0 s, cooldown 10.0 s, `min_nodes` 2
- Subscribes `quake/+/event` and `quake/+/tel`, publishes `quake/alarm`
- Alarm payload `{"nodes": [...], "peak_gal": float}`
- Simulated channel ID is `sim-000001` — the `sim-` prefix must survive, so a simulated channel
  is never mistaken for a real one in a log or screenshot
- `TB_TOKEN` comes from the environment. Never a tracked file, never a CLI flag.

---

### Task 1: Project setup

**Files:**
- Create: `correlator/requirements.txt`

- [ ] **Step 1: Write requirements**

```
paho-mqtt>=2.0
pytest>=8.0
```

- [ ] **Step 2: Create a virtualenv and install**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r correlator/requirements.txt
```

- [ ] **Step 3: Confirm paho is version 2.x**

```bash
python -c "import paho.mqtt; print(paho.mqtt.__version__)"
```

Expected: `2.` something. Version 2 changed the client constructor — it now requires a
callback API version argument. Task 4 uses the v2 form. If you somehow have 1.x, `pip install
--upgrade 'paho-mqtt>=2.0'`.

- [ ] **Step 4: Commit**

```bash
git add correlator/requirements.txt
git commit -m "chore: correlator dependencies"
```

---

### Task 2: Correlation rule — failing test first

**Files:**
- Create: `correlator/test_core.py`

**Interfaces:**
- Produces: `Alarm(nodes: list[str], peak_gal: float)` and
  `Correlator(window_s=2.0, cooldown_s=10.0, min_nodes=2)` with
  `add_event(node_id: str, peak_gal: float, now: float) -> Alarm | None`.
  `main.py` in Task 4 consumes exactly these.

`now` is a parameter, not `time.monotonic()` called inside. That is what makes cooldown
testable without a 10-second sleep.

- [ ] **Step 1: Write the failing tests**

```python
# correlator/test_core.py
import pytest
from core import Alarm, Correlator


def test_single_node_does_not_alarm():
    """The core negative case: one node shaking is local noise, not a quake."""
    c = Correlator()
    assert c.add_event("node-aaa", 100.0, now=0.0) is None


def test_same_node_twice_does_not_alarm():
    """Two events from one node must not be mistaken for two nodes agreeing."""
    c = Correlator()
    assert c.add_event("node-aaa", 100.0, now=0.0) is None
    assert c.add_event("node-aaa", 120.0, now=0.5) is None


def test_two_nodes_within_window_alarms():
    c = Correlator()
    assert c.add_event("node-aaa", 100.0, now=0.0) is None
    alarm = c.add_event("node-bbb", 150.0, now=1.0)
    assert alarm is not None
    assert sorted(alarm.nodes) == ["node-aaa", "node-bbb"]
    assert alarm.peak_gal == 150.0          # the max, not the latest


def test_two_nodes_outside_window_does_not_alarm():
    c = Correlator()
    assert c.add_event("node-aaa", 100.0, now=0.0) is None
    assert c.add_event("node-bbb", 150.0, now=3.0) is None   # window is 2.0 s


def test_cooldown_suppresses_second_alarm():
    c = Correlator()
    c.add_event("node-aaa", 100.0, now=0.0)
    assert c.add_event("node-bbb", 150.0, now=1.0) is not None
    c.add_event("node-aaa", 100.0, now=5.0)
    assert c.add_event("node-bbb", 150.0, now=5.5) is None    # cooldown is 10.0 s


def test_new_alarm_allowed_after_cooldown():
    c = Correlator()
    c.add_event("node-aaa", 100.0, now=0.0)
    assert c.add_event("node-bbb", 150.0, now=1.0) is not None
    c.add_event("node-aaa", 100.0, now=12.0)
    assert c.add_event("node-bbb", 150.0, now=12.5) is not None


def test_three_nodes_still_one_alarm():
    """min_nodes is a floor, not an exact count."""
    c = Correlator(min_nodes=2)
    c.add_event("node-aaa", 100.0, now=0.0)
    assert c.add_event("node-bbb", 150.0, now=0.5) is not None
    assert c.add_event("node-ccc", 900.0, now=1.0) is None    # cooldown holds


def test_stale_events_are_pruned():
    """An old event must not combine with a much later one."""
    c = Correlator()
    c.add_event("node-aaa", 100.0, now=0.0)
    for t in (10.0, 20.0, 30.0):
        assert c.add_event("node-aaa", 100.0, now=t) is None
    assert c.add_event("node-bbb", 100.0, now=40.0) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd correlator && python -m pytest test_core.py -v
```

Expected: **collection error** — `ModuleNotFoundError: No module named 'core'`. Correct
failure; nothing is implemented.

---

### Task 3: Correlation rule — make it pass

**Files:**
- Create: `correlator/core.py`
- Test: `correlator/test_core.py`

**Interfaces:**
- Produces: `Alarm`, `Correlator.add_event` as specified in Task 2

- [ ] **Step 1: Write the implementation**

```python
# correlator/core.py
"""Correlation rule. No network, no wall clock - `now` is always passed in."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Alarm:
    nodes: list[str]
    peak_gal: float


class Correlator:
    """Declares an earthquake when >= min_nodes distinct nodes trigger inside window_s.

    A single node shaking is local noise - a truck, a door, someone leaning on
    the desk. Ground motion reaches every node. Requiring agreement is what
    separates the two, and it is the whole point of requiring two channels.
    """

    def __init__(self, window_s: float = 2.0, cooldown_s: float = 10.0,
                 min_nodes: int = 2):
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self.min_nodes = min_nodes
        self._recent: list[tuple[str, float, float]] = []   # (node, peak, t)
        self._last_alarm_at: float | None = None

    def add_event(self, node_id: str, peak_gal: float, now: float) -> Alarm | None:
        self._recent.append((node_id, peak_gal, now))
        # Drop anything that fell out of the window.
        self._recent = [e for e in self._recent if now - e[2] <= self.window_s]

        if (self._last_alarm_at is not None
                and now - self._last_alarm_at < self.cooldown_s):
            return None      # one earthquake, one alarm

        nodes = {e[0] for e in self._recent}
        if len(nodes) < self.min_nodes:
            return None

        self._last_alarm_at = now
        peak = max(e[1] for e in self._recent)
        self._recent.clear()
        return Alarm(nodes=sorted(nodes), peak_gal=peak)
```

- [ ] **Step 2: Run the tests to verify they pass**

```bash
cd correlator && python -m pytest test_core.py -v
```

Expected: `8 passed`

- [ ] **Step 3: Commit**

```bash
git add correlator/core.py correlator/test_core.py
git commit -m "feat: correlation rule with unit tests

Requires distinct node IDs, so two events from one node cannot fake
agreement. Cooldown collapses one earthquake into one alarm. `now` is a
parameter rather than a clock read, which makes the cooldown testable
without sleeping."
```

---

### Task 4: MQTT shell

**Files:**
- Create: `correlator/main.py`

**Interfaces:**
- Consumes: `Alarm`, `Correlator` from `core.py` (Task 3)
- Produces: publishes `quake/alarm`; the node subscribes to it in plan 02 Task 4

- [ ] **Step 1: Write the shell**

```python
# correlator/main.py
"""Subscribe to node events, publish an alarm when nodes agree.

Also bridges to Thingsboard for the cloud dashboard. The bridge lives here
rather than in the firmware so the node stays plaintext with no TLS, and so
the local path - events, correlation, alarm, buzzer - keeps working when the
internet does not.
"""
import argparse
import json
import os
import time

import paho.mqtt.client as mqtt

from core import Correlator

EVENT_SUB = "quake/+/event"
TEL_SUB = "quake/+/tel"
ALARM_TOPIC = "quake/alarm"
TB_TELEMETRY = "v1/devices/me/telemetry"


def connect_thingsboard(host: str, token: str | None):
    """Return a connected Thingsboard client, or None to run local-only.

    Thingsboard authenticates a device by using its access token as the MQTT
    username, with no password.
    """
    if not token:
        print("no TB_TOKEN set - running local-only, no cloud dashboard")
        return None
    tb = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    tb.username_pw_set(token)
    try:
        tb.connect(host, 1883, keepalive=60)
    except OSError as e:
        # Never let a cloud outage take down local detection.
        print(f"thingsboard unreachable ({e}) - running local-only")
        return None
    tb.loop_start()
    print(f"thingsboard connected: {host}")
    return tb


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", required=True, help="broker IP, e.g. 192.168.1.100")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--cooldown", type=float, default=10.0)
    ap.add_argument("--min-nodes", type=int, default=2)
    ap.add_argument("--tb-host", default="demo.thingsboard.io")
    args = ap.parse_args()

    corr = Correlator(window_s=args.window, cooldown_s=args.cooldown,
                      min_nodes=args.min_nodes)
    tb = connect_thingsboard(args.tb_host, os.environ.get("TB_TOKEN"))

    def to_cloud(fields: dict) -> None:
        if tb:
            tb.publish(TB_TELEMETRY, json.dumps(fields))

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"connected ({reason_code}), subscribing {EVENT_SUB} and {TEL_SUB}")
        client.subscribe(EVENT_SUB)
        client.subscribe(TEL_SUB)

    def on_message(client, userdata, msg):
        # Node ID comes from the topic, not the payload: the topic is set by
        # broker routing and cannot disagree with itself.
        parts = msg.topic.split("/")
        if len(parts) != 3:
            return
        node_id, kind = parts[1], parts[2]

        try:
            data = json.loads(msg.payload)
        except ValueError:
            print(f"  ignoring malformed payload from {node_id}: {msg.payload!r}")
            return

        if kind == "tel":
            # Per-node keys so the dashboard can chart channels separately.
            dev = data.get("dev_gal")
            if dev is not None:
                to_cloud({f"dev_gal_{node_id}": dev})
            return

        try:
            peak = float(data["peak_gal"])
        except (ValueError, KeyError, TypeError):
            print(f"  ignoring malformed event from {node_id}: {msg.payload!r}")
            return

        now = time.monotonic()
        print(f"event  {node_id}  peak={peak:.2f} gal")
        to_cloud({"event_node": node_id, "event_peak_gal": peak})

        alarm = corr.add_event(node_id, peak, now)
        if alarm:
            payload = json.dumps({"nodes": alarm.nodes,
                                  "peak_gal": alarm.peak_gal})
            client.publish(ALARM_TOPIC, payload)
            print(f"ALARM  {alarm.nodes}  peak={alarm.peak_gal:.2f} gal")
            to_cloud({"alarm": 1, "alarm_peak_gal": alarm.peak_gal,
                      "alarm_nodes": ",".join(alarm.nodes)})

    # paho-mqtt 2.x requires the callback API version explicitly.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
```

`TB_TOKEN` comes from the environment, never a file and never a flag — flags land in your
shell history. Without it the correlator runs local-only, which is exactly what you want if
the venue's internet fails mid-demo.

- [ ] **Step 2: Verify it starts and fails cleanly with no broker**

```bash
cd correlator && python main.py --broker 127.0.0.1
```

Expected: first `no TB_TOKEN set - running local-only, no cloud dashboard` (you set the token in
Task 6), then `ConnectionRefusedError` on the local broker. That proves argument parsing and
imports work — there is no broker yet. Plan 04 starts one.

- [ ] **Step 3: Verify the unit tests are unaffected**

```bash
cd correlator && python -m pytest test_core.py -v
```

Expected: `8 passed`

- [ ] **Step 4: Commit**

```bash
git add correlator/main.py
git commit -m "feat: correlator MQTT shell

Node ID is taken from the topic rather than the payload, so a node cannot
misreport its own identity. Malformed payloads are logged and skipped
instead of crashing the service."
```

---

### Task 5: Simulated second channel

**Files:**
- Create: `correlator/fake_node.py`

Only one ESP32 is available, so channel B is simulated. It speaks the same MQTT contract, which
means a real second node later is a drop-in with no code changes.

**This script must never subscribe to the real node's events.** If it echoed them, every real
event would auto-correlate: the alarm would become vacuous and single-node rejection could
never be demonstrated. It publishes only when you press Enter.

- [ ] **Step 1: Write the simulated node**

```python
# correlator/fake_node.py
"""Simulated second channel. Publishes an event when you press Enter.

Deliberately does NOT subscribe to any topic. If this echoed the real node's
events, correlation would always succeed and the alarm would mean nothing -
and the single-node rejection test would be impossible to run.

The ID is prefixed 'sim-' so a simulated channel can never be mistaken for a
real one in a log or a screenshot.
"""
import argparse
import json
import random
import time

import paho.mqtt.client as mqtt

NODE_ID = "sim-000001"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", required=True)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--peak", type=float, default=0.0,
                    help="peak_gal to report; 0 picks a random 20-80")
    args = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    ev_topic = f"quake/{NODE_ID}/event"
    tel_topic = f"quake/{NODE_ID}/tel"
    started = time.monotonic()

    print(f"{NODE_ID} ready. Enter = publish event, Ctrl-C = quit.")
    print(f"  events -> {ev_topic}")

    try:
        while True:
            input()
            peak = args.peak or round(random.uniform(20.0, 80.0), 2)
            client.publish(ev_topic, json.dumps({
                "node": NODE_ID, "peak_gal": peak, "dur_ms": 1200,
            }))
            client.publish(tel_topic, json.dumps({
                "node": NODE_ID, "dev_gal": peak,
                "uptime_s": int(time.monotonic() - started),
            }))
            print(f"published  peak={peak:.2f} gal")
    except KeyboardInterrupt:
        print("\nstopping")
        client.loop_stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it fails cleanly with no broker**

```bash
cd correlator && python fake_node.py --broker 127.0.0.1
```

Expected: `ConnectionRefusedError`. No broker yet — plan 04 starts one.

- [ ] **Step 3: Confirm it subscribes to nothing**

```bash
grep -n 'subscribe' correlator/fake_node.py || echo "correct: no subscriptions"
```

Expected: `correct: no subscriptions`. This is the guard against a vacuous alarm — if a future
edit adds a subscription here, the whole demonstration becomes circular.

- [ ] **Step 4: Commit**

```bash
git add correlator/fake_node.py
git commit -m "feat: simulated second channel

Only one ESP32 is available, so channel B is simulated. Speaks the same
MQTT contract, so a real second node is a drop-in.

Subscribes to nothing on purpose: echoing the real node's events would
make every event auto-correlate, rendering the alarm vacuous and the
single-node rejection test impossible."
```

---

### Task 6: Thingsboard dashboard

**Files:** none — this is account setup and web UI work.

Thingsboard is the display sink only. The correlator forwards to it; nothing depends on it.

- [ ] **Step 1: Create a device on the public demo instance**

Sign up at [demo.thingsboard.io](https://demo.thingsboard.io), then **Devices → + → Add new
device**. Name it `quake-net`. Open it, go to **Details → Copy access token**.

The public demo instance deletes data periodically and is rate-limited. Fine for a course demo;
take screenshots of your dashboard rather than relying on it to still hold your data at grading
time.

- [ ] **Step 2: Export the token into your shell**

```bash
export TB_TOKEN='paste-your-device-access-token'
```

Never put this in a file that git tracks, and never pass it as a command-line flag — flags are
recorded in your shell history. Add it to your `~/.zshrc` if you want it to persist.

- [ ] **Step 3: Verify the token works before wiring anything up**

```bash
mosquitto_pub -h demo.thingsboard.io -p 1883 -u "$TB_TOKEN" \
  -t 'v1/devices/me/telemetry' -m '{"test":1}'
```

Expected: exits silently with status 0. Then check **Devices → quake-net → Latest telemetry**
in the web UI for a `test` key.

A `Connection Refused: not authorised` means the token is wrong or was copied with whitespace.

- [ ] **Step 4: Build the dashboard**

**Dashboards → + → Create new dashboard**, then add widgets bound to the `quake-net` device:

| Widget | Type | Key |
|---|---|---|
| Live deviation | Time series chart | `dev_gal_node-XXXXXX` (your real node's ID) |
| Last event peak | Latest values card | `event_peak_gal` |
| Alarm state | Latest values card | `alarm`, `alarm_nodes` |

You will not know your real node's ID until plan 04 Task 3, so add that first widget after
flashing. The other two work immediately.

- [ ] **Step 5: Confirm graceful degradation**

```bash
cd correlator && unset TB_TOKEN && python main.py --broker 127.0.0.1
```

Expected: `no TB_TOKEN set - running local-only, no cloud dashboard`, then a connection error
for the local broker. The cloud must never be load-bearing — if the venue's internet dies
mid-demo, the buzzer still has to fire.

---

## Done when

- `cd correlator && python -m pytest test_core.py -v` → `8 passed`
- `python main.py --broker 127.0.0.1` fails on the *local* broker, not in your own code
- `grep -n subscribe correlator/fake_node.py` finds nothing
- A manual `mosquitto_pub` to Thingsboard shows up in Latest telemetry
- With `TB_TOKEN` unset, the correlator says it is running local-only rather than crashing

Next: [04-bringup-and-calibration.md](04-bringup-and-calibration.md)
