"""Subscribe to node events, publish an alarm when nodes agree.

Also bridges to Thingsboard for the cloud dashboard. The bridge lives here
rather than in the firmware so the node stays plaintext with no TLS, and so
the local path - events, correlation, alarm, buzzer - keeps working when the
internet does not.
"""
import argparse
import json
import os
import sys
import time

import paho.mqtt.client as mqtt

from core import Correlator

# Topic namespace. Every publisher and subscriber in this system shares it, so
# two deployments -- or a test run and live hardware -- can use one broker
# without correlating each other's events into false alarms.
PREFIX = os.environ.get("QUAKE_PREFIX", "quake")

EVENT_SUB = f"{PREFIX}/+/event"
TEL_SUB = f"{PREFIX}/+/tel"
ALARM_TOPIC = f"{PREFIX}/alarm"
TB_TELEMETRY = "v1/devices/me/telemetry"


def connect_thingsboard(host: str, port: int, token: str | None):
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
        tb.connect(host, port, keepalive=60)
    except OSError as e:
        # Never let a cloud outage take down local detection.
        print(f"thingsboard unreachable ({e}) - running local-only")
        return None
    tb.loop_start()
    print(f"thingsboard connected: {host}:{port}")
    return tb


def main() -> None:
    # Line-buffer stdout so logs appear immediately when redirected to a
    # file or a pipe, not just on a terminal. Without this, prints sit in
    # the buffer and events look like they went missing.
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost", help="broker host or IP")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--cooldown", type=float, default=10.0)
    ap.add_argument("--min-nodes", type=int, default=2)
    ap.add_argument("--tb-host", default=os.environ.get("TB_HOST", "demo.thingsboard.io"))
    ap.add_argument("--tb-port", type=int, default=int(os.environ.get("TB_PORT", "1883")))
    args = ap.parse_args()

    corr = Correlator(window_s=args.window, cooldown_s=args.cooldown,
                      min_nodes=args.min_nodes)
    tb = connect_thingsboard(args.tb_host, args.tb_port, os.environ.get("TB_TOKEN"))

    def to_cloud(fields: dict) -> None:
        if tb:
            tb.publish(TB_TELEMETRY, json.dumps(fields))

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"connected ({reason_code}), subscribing {EVENT_SUB} and {TEL_SUB}",
              flush=True)
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
            print(f"  ignoring malformed payload from {node_id}: {msg.payload!r}",
                  flush=True)
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
            print(f"  ignoring malformed event from {node_id}: {msg.payload!r}",
                  flush=True)
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
