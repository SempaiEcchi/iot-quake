"""End-to-end tests against a real broker, with mock nodes instead of ESP32s.

Exercises the whole loop: synthetic acceleration -> detector -> MQTT -> broker
-> correlator -> alarm -> back to the node. Everything except the hardware.

Needs the broker running:  docker compose up -d
Skips itself if the broker is unreachable, so `pytest` never fails just
because Docker is not up.
"""
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BROKER = os.environ.get("QUAKE_BROKER", "localhost")
PORT = int(os.environ.get("QUAKE_PORT", "1883"))

# Speed-ups so a test takes seconds, not half a minute. The algorithm is
# unchanged; only the two timing constants shrink.
FAST = ["--warmup-ms", "500", "--refractory-ms", "1000",
        "--shake-ms", "600", "--auto-shake", "2.5"]


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


class Runner:
    """Run processes for a while and collect their combined output."""

    def __init__(self):
        self.procs = []
        self.lines = []
        self._lock = threading.Lock()

    def start(self, argv, cwd):
        env = dict(os.environ)
        env.pop("TB_TOKEN", None)          # keep the cloud out of the test
        env["PYTHONUNBUFFERED"] = "1"
        p = subprocess.Popen(
            [sys.executable, *argv], cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True,
        )
        self.procs.append(p)
        threading.Thread(target=self._drain, args=(p,), daemon=True).start()
        return p

    def _drain(self, p):
        for line in p.stdout:
            with self._lock:
                self.lines.append(line.rstrip())

    def output(self) -> str:
        with self._lock:
            return "\n".join(self.lines)

    def stop(self):
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


@pytest.fixture
def runner():
    r = Runner()
    yield r
    r.stop()


def _correlator(r):
    r.start(["main.py", "--broker", BROKER, "--port", str(PORT)],
            cwd=ROOT / "correlator")


def _mock(r, node_id):
    r.start(["mock_node.py", "--broker", BROKER, "--port", str(PORT),
             "--node-id", node_id, "--seed", "1", *FAST],
            cwd=ROOT / "sim")


def test_single_channel_produces_events_but_no_alarm(runner):
    """The core negative case, end to end. One channel is not agreement."""
    _correlator(runner)
    time.sleep(1)
    _mock(runner, "mock-solo")
    time.sleep(9)

    out = runner.output()
    assert "event  mock-solo" in out, f"no events reached the correlator:\n{out}"
    assert "ALARM" not in out, f"a single channel must never alarm:\n{out}"


def test_two_channels_agreeing_raise_one_alarm(runner):
    """Two nodes shaking together within the window must alarm, exactly once."""
    _correlator(runner)
    time.sleep(1)
    _mock(runner, "mock-aaa")
    _mock(runner, "mock-bbb")
    time.sleep(9)

    out = runner.output()
    assert "ALARM" in out, f"two agreeing channels should alarm:\n{out}"
    assert "mock-aaa" in out and "mock-bbb" in out
    # The 10 s cooldown must collapse repeated shaking into one alarm.
    assert out.count("ALARM") == 1, f"cooldown should permit only one alarm:\n{out}"


def test_alarm_reaches_the_node_as_a_buzzer(runner):
    """The alarm must travel back down to the nodes, not just print."""
    _correlator(runner)
    time.sleep(1)
    _mock(runner, "mock-aaa")
    _mock(runner, "mock-bbb")
    time.sleep(9)

    out = runner.output()
    assert "BUZZER" in out, f"nodes did not receive quake/alarm:\n{out}"
