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
import sys
import time

import paho.mqtt.client as mqtt

NODE_ID = "sim-000001"


def main() -> None:
    # Line-buffer stdout so logs appear immediately when redirected to a
    # file or a pipe, not just on a terminal. Without this, prints sit in
    # the buffer and events look like they went missing.
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
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
            try:
                input()
            except EOFError:
                # stdin closed (piped input exhausted, or run detached).
                # Exit quietly rather than dumping a traceback.
                break
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
