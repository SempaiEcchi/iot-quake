"""Mock ESP32 node. Runs the real detection algorithm against synthetic
acceleration and speaks the real MQTT contract.

Lets you build and test the whole system before any hardware arrives. The
detector is the same algorithm as the firmware (see detector.py), so a bug in
the detection logic shows up here too.

What it does NOT test: I2C, WiFi reconnection, the 100 Hz sample gate under
real load, and whether your desk is quiet enough. Those need the ESP32.

  python sim/mock_node.py --broker localhost                    # Enter = shake
  python sim/mock_node.py --broker localhost --auto-shake 8     # shake every 8 s
"""
import os
import argparse
import json
import random
import sys
import threading
import time

import paho.mqtt.client as mqtt

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from detector import Detector, GAL_PER_G

# Topic namespace. Every publisher and subscriber in this system shares it, so
# two deployments -- or a test run and live hardware -- can use one broker
# without correlating each other's events into false alarms.
PREFIX = os.environ.get("QUAKE_PREFIX", "quake")


SAMPLE_HZ = 100
SAMPLE_DT = 1.0 / SAMPLE_HZ
TEL_S = 1.0


class MockNode:
    def __init__(self, args):
        self.a = args
        self.det = Detector(args.threshold, warmup_ms=args.warmup_ms,
                            refractory_ms=args.refractory_ms)
        self.shake_until = 0.0
        self.shake_i = 0
        self.led = False
        self.rng = random.Random(args.seed)

        self.ev_topic = f"{PREFIX}/{args.node_id}/event"
        self.tel_topic = f"{PREFIX}/{args.node_id}/tel"

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    # ---------- MQTT ----------

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(f"{PREFIX}/alarm")
        print(f"[{self.a.node_id}] connected ({reason_code}), "
              f"threshold={self.a.threshold} gal")

    def _on_message(self, client, userdata, msg):
        if msg.topic == f"{PREFIX}/alarm":
            print(f"[{self.a.node_id}] *** BUZZER *** {msg.payload.decode()}")

    # ---------- synthetic sensor ----------

    def _read_mag(self, now: float) -> float:
        """Magnitude in gal: gravity, plus noise, plus a shake if one is on."""
        mag = GAL_PER_G + self.rng.gauss(0.0, self.a.noise)
        if now < self.shake_until:
            # Alternate every sample so the EMA cannot chase it out, matching
            # the sustained-shake case in the unit tests.
            self.shake_i += 1
            mag += self.a.shake_gal if self.shake_i % 2 else -self.a.shake_gal
        return mag

    def shake(self):
        self.shake_until = time.monotonic() + self.a.shake_ms / 1000.0
        print(f"[{self.a.node_id}] shaking for {self.a.shake_ms} ms")

    # ---------- main loop ----------

    def run(self):
        self.client.connect(self.a.broker, self.a.port, keepalive=60)
        self.client.loop_start()

        if self.a.auto_shake:
            print(f"[{self.a.node_id}] auto-shaking every {self.a.auto_shake} s")
        else:
            threading.Thread(target=self._stdin_shakes, daemon=True).start()
            print(f"[{self.a.node_id}] Enter = shake, Ctrl-C = quit")

        t_start = time.monotonic()
        next_sample = t_start
        next_tel = t_start + TEL_S
        next_auto = t_start + self.a.auto_shake if self.a.auto_shake else None
        last_dev = 0.0

        try:
            while True:
                now = time.monotonic()
                if now < next_sample:
                    time.sleep(min(SAMPLE_DT / 4, next_sample - now))
                    continue

                # Resync rather than catch up, exactly as the firmware does.
                next_sample = (now if now - next_sample > 10 * SAMPLE_DT
                               else next_sample + SAMPLE_DT)

                if next_auto and now >= next_auto:
                    self.shake()
                    next_auto = now + self.a.auto_shake

                out = self.det.update(self._read_mag(now), int((now - t_start) * 1000))
                last_dev = out.dev_gal

                if out.started:
                    self.led = True
                    print(f"[{self.a.node_id}] LED on  (dev={out.dev_gal:.2f} gal)")
                if out.event_done:
                    self.led = False
                    self.client.publish(self.ev_topic, json.dumps({
                        "node": self.a.node_id,
                        "peak_gal": round(out.peak_gal, 2),
                        "dur_ms": out.dur_ms,
                    }))
                    print(f"[{self.a.node_id}] LED off EVENT "
                          f"peak={out.peak_gal:.2f} gal dur={out.dur_ms} ms")

                if now >= next_tel:
                    next_tel = now + TEL_S
                    self.client.publish(self.tel_topic, json.dumps({
                        "node": self.a.node_id,
                        "dev_gal": round(last_dev, 2),
                        "uptime_s": int(now - t_start),
                    }))
        except KeyboardInterrupt:
            print(f"\n[{self.a.node_id}] stopping")
            self.client.loop_stop()

    def _stdin_shakes(self):
        for _ in sys.stdin:
            self.shake()


def main():
    # Line-buffer stdout so logs appear immediately when redirected to a
    # file or a pipe, not just on a terminal. Without this, prints sit in
    # the buffer and events look like they went missing.
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--node-id", default="mock-000001")
    ap.add_argument("--threshold", type=float, default=5.0,
                    help="gal; default suits the default noise level")
    ap.add_argument("--noise", type=float, default=0.5,
                    help="gal RMS of synthetic desk noise")
    ap.add_argument("--shake-gal", type=float, default=40.0)
    ap.add_argument("--shake-ms", type=int, default=1000)
    ap.add_argument("--auto-shake", type=float, default=0.0,
                    help="seconds between automatic shakes; 0 = Enter only")
    ap.add_argument("--warmup-ms", type=int, default=3000)
    ap.add_argument("--refractory-ms", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=None)
    MockNode(ap.parse_args()).run()


if __name__ == "__main__":
    main()
