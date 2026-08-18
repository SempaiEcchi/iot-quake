"""Tests for the dashboard's state aggregation.

Starts the real server, publishes real MQTT messages, and reads the real HTTP
endpoint. Needs the broker:  docker compose up -d
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest

ROOT = Path(__file__).resolve().parent.parent
BROKER = os.environ.get("QUAKE_BROKER", "localhost")
PORT = int(os.environ.get("QUAKE_PORT", "1883"))
HTTP_PORT = 8077                      # not 8000, so a dev server can stay up


def broker_up() -> bool:
    try:
        with socket.create_connection((BROKER, PORT), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not broker_up(),
    reason=f"no MQTT broker at {BROKER}:{PORT} - run: docker compose up -d",
)


def get(path: str, tries: int = 25):
    url = f"http://localhost:{HTTP_PORT}{path}"
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return r.read().decode()
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    raise AssertionError(f"dashboard never answered {url}")


@pytest.fixture
def server():
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen(
        [sys.executable, "dashboard/server.py", "--broker", BROKER,
         "--port", str(PORT), "--http-port", str(HTTP_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )
    get("/api/state")                 # wait until it is actually serving
    yield p
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()


@pytest.fixture
def pub():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.connect(BROKER, PORT, keepalive=30)
    c.loop_start()
    yield c
    c.loop_stop()
    c.disconnect()


def baseline():
    """Counters before a test acts.

    The dashboard aggregates every publisher on the broker, which is the point
    in production but makes absolute counts fragile in tests - a stray mock
    node inflates them. Assert on deltas instead.
    """
    return json.loads(get("/api/state"))["counters"]


def wait_for(predicate, timeout=6.0):
    """Poll /api/state until predicate(state) holds. Returns the state."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = json.loads(get("/api/state"))
        if predicate(last):
            return last
        time.sleep(0.15)
    raise AssertionError(f"condition never met; last state: {last}")


def test_serves_page(server):
    page = get("/")
    assert "<title>quake-net</title>" in page
    assert "EventSource" in page          # the live-update path exists


def test_telemetry_creates_a_channel(server, pub):
    pub.publish("quake/node-test1/tel",
                json.dumps({"node": "node-test1", "dev_gal": 1.25,
                            "uptime_s": 42}))
    s = wait_for(lambda s: any(c["id"] == "node-test1" for c in s["channels"]))
    ch = next(c for c in s["channels"] if c["id"] == "node-test1")
    assert ch["dev_gal"] == 1.25
    assert ch["online"] is True
    assert ch["simulated"] is False       # a node- id is real hardware
    assert 1.25 in ch["trace"]


def test_simulated_channels_are_flagged(server, pub):
    pub.publish("quake/sim-000001/tel",
                json.dumps({"node": "sim-000001", "dev_gal": 0.5,
                            "uptime_s": 1}))
    s = wait_for(lambda s: any(c["id"] == "sim-000001" for c in s["channels"]))
    ch = next(c for c in s["channels"] if c["id"] == "sim-000001")
    assert ch["simulated"] is True, "a sim- channel must be labelled in the UI"


def test_rejected_counts_events_that_never_alarmed(server, pub):
    """The headline metric: events correlation threw away."""
    base = baseline()
    for i in range(3):
        pub.publish("quake/node-lonely/event",
                    json.dumps({"node": "node-lonely", "peak_gal": 10.0 + i,
                                "dur_ms": 100}))
        time.sleep(0.1)
    s = wait_for(lambda s: s["counters"]["events"] - base["events"] >= 3)
    assert s["counters"]["alarms"] - base["alarms"] == 0
    assert s["counters"]["rejected"] - base["rejected"] == 3


def test_alarm_sets_banner_and_is_not_counted_as_rejected(server, pub):
    base = baseline()
    pub.publish("quake/node-a/event",
                json.dumps({"node": "node-a", "peak_gal": 20.0, "dur_ms": 100}))
    pub.publish("quake/node-b/event",
                json.dumps({"node": "node-b", "peak_gal": 30.0, "dur_ms": 100}))
    pub.publish("quake/alarm",
                json.dumps({"nodes": ["node-a", "node-b"], "peak_gal": 30.0}))

    s = wait_for(lambda s: s["counters"]["alarms"] - base["alarms"] == 1)
    assert s["alarm_active"] is True
    assert s["last_alarm"]["peak_gal"] == 30.0
    assert sorted(s["last_alarm"]["nodes"]) == ["node-a", "node-b"]
    # Two events, both part of the alarm, so nothing new was rejected.
    assert s["counters"]["rejected"] - base["rejected"] == 0


def test_malformed_payload_does_not_crash(server, pub):
    pub.publish("quake/node-bad/tel", b"not json at all")
    pub.publish("quake/node-good/tel",
                json.dumps({"node": "node-good", "dev_gal": 1.0, "uptime_s": 1}))
    s = wait_for(lambda s: any(c["id"] == "node-good" for c in s["channels"]))
    assert not any(c["id"] == "node-bad" for c in s["channels"])
