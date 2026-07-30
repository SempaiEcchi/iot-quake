# Plan 03: Correlator

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A service that subscribes to node events and publishes `quake/alarm` only when two distinct nodes trigger within 2 seconds.

**Architecture:** Same split as the firmware — `core.py` holds the correlation rule with no network code and takes `now` as a parameter, so tests drive time directly instead of sleeping. `main.py` is the paho-mqtt shell.

**Tech Stack:** Python 3.11+, paho-mqtt 2.x, pytest

**No hardware needed.** Do this while parts ship.

## Global Constraints

See [00-index.md](00-index.md#global-constraints). Relevant here:

- Window 2.0 s, cooldown 10.0 s, `min_nodes` 2
- Subscribes `quake/+/event`, publishes `quake/alarm`
- Alarm payload `{"nodes": [...], "peak_gal": float}`

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
    separates the two, and it is the whole point of using two nodes.
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
"""Subscribe to node events, publish an alarm when nodes agree."""
import argparse
import json
import time

import paho.mqtt.client as mqtt

from core import Correlator

EVENT_SUB = "quake/+/event"
ALARM_TOPIC = "quake/alarm"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", required=True, help="broker IP, e.g. 192.168.1.100")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--cooldown", type=float, default=10.0)
    ap.add_argument("--min-nodes", type=int, default=2)
    args = ap.parse_args()

    corr = Correlator(window_s=args.window, cooldown_s=args.cooldown,
                      min_nodes=args.min_nodes)

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"connected ({reason_code}), subscribing {EVENT_SUB}")
        client.subscribe(EVENT_SUB)

    def on_message(client, userdata, msg):
        # Node ID comes from the topic, not the payload: the topic is set by
        # the broker routing and cannot disagree with itself.
        parts = msg.topic.split("/")
        if len(parts) != 3:
            return
        node_id = parts[1]

        try:
            peak = float(json.loads(msg.payload)["peak_gal"])
        except (ValueError, KeyError, TypeError):
            print(f"  ignoring malformed payload from {node_id}: {msg.payload!r}")
            return

        now = time.monotonic()
        print(f"event  {node_id}  peak={peak:.2f} gal")

        alarm = corr.add_event(node_id, peak, now)
        if alarm:
            payload = json.dumps({"nodes": alarm.nodes,
                                  "peak_gal": alarm.peak_gal})
            client.publish(ALARM_TOPIC, payload)
            print(f"ALARM  {alarm.nodes}  peak={alarm.peak_gal:.2f} gal")

    # paho-mqtt 2.x requires the callback API version explicitly.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it starts and fails cleanly with no broker**

```bash
cd correlator && python main.py --broker 127.0.0.1
```

Expected: `ConnectionRefusedError`. That proves argument parsing and imports work — there is
no broker yet. Plan 04 starts one.

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

## Done when

- `cd correlator && python -m pytest test_core.py -v` → `8 passed`
- `python main.py --broker 127.0.0.1` fails with a connection error, not a traceback in your
  own code

Next: [04-bringup-and-calibration.md](04-bringup-and-calibration.md)
