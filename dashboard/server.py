"""Live web dashboard for quake-net.

Subscribes to the same MQTT topics as the correlator and serves a single
self-contained page over HTTP, pushed with server-sent events.

Deliberately separate from the correlator: the correlator decides whether an
earthquake happened, and nothing about that decision should depend on whether
a browser is watching. Killing this process must not change detection.

  python dashboard/server.py --broker localhost
  open http://localhost:8000
"""
import os
import argparse
import json
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt

# Topic namespace. Every publisher and subscriber in this system shares it, so
# two deployments -- or a test run and live hardware -- can use one broker
# without correlating each other's events into false alarms.
PREFIX = os.environ.get("QUAKE_PREFIX", "quake")

# Reuse the correlator's band table rather than copying it. Two copies of a
# lookup like this drift, and the drift is silent -- the dashboard would just
# start disagreeing with the cloud about how strong an earthquake was.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "correlator"))
from core import shindo_from_gal  # noqa: E402


TRACE_LEN = 120          # dev_gal samples kept per channel (~2 min at 1 Hz)
EVENT_LOG_LEN = 25
STALE_S = 5.0            # no telemetry for this long -> channel shown offline

state_lock = threading.Lock()
channels = {}            # node_id -> {dev_gal, uptime_s, last_seen, trace}
event_log = deque(maxlen=EVENT_LOG_LEN)
quake_log = deque(maxlen=EVENT_LOG_LEN)
counters = {"events": 0, "alarms": 0, "in_alarms": 0}
last_alarm = {"at": 0.0, "nodes": [], "peak_gal": 0.0, "shindo": "-"}
subscribers = []         # queue per connected browser


def broadcast():
    """Push current state to every connected browser."""
    payload = snapshot()
    for q in list(subscribers):
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass         # slow client; it will catch up on the next tick


def snapshot() -> str:
    now = time.monotonic()
    with state_lock:
        chans = [
            {
                "id": nid,
                "dev_gal": c["dev_gal"],
                "uptime_s": c["uptime_s"],
                "online": (now - c["last_seen"]) < STALE_S,
                # "mirror-" is a replay of another channel's samples, not a
                # second sensor. Flagging it alongside the synthetic channels
                # is the point: an unflagged mirror reads as corroboration.
                "simulated": nid.startswith(("sim-", "mock-", "mirror-")),
                "trace": list(c["trace"]),
            }
            for nid, c in sorted(channels.items())
        ]
        # An event that never became part of an alarm was rejected by the
        # correlation rule. On a single-channel design each would have been a
        # false alarm, so this is the headline number for the report.
        rejected = counters["events"] - counters["in_alarms"]
        return json.dumps({
            "channels": chans,
            "events": list(event_log),
            "quakes": list(quake_log),
            "counters": {**counters, "rejected": max(0, rejected)},
            "alarm_active": (now - last_alarm["at"]) < 8.0,
            "last_alarm": last_alarm,
        })


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"dashboard: broker connected ({reason_code})")
    client.subscribe(f"{PREFIX}/+/tel")
    client.subscribe(f"{PREFIX}/+/event")
    client.subscribe(f"{PREFIX}/alarm")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
    except ValueError:
        return
    parts = msg.topic.split("/")
    now = time.monotonic()

    if msg.topic == f"{PREFIX}/alarm":
        with state_lock:
            last_alarm["at"] = now
            last_alarm["nodes"] = data.get("nodes", [])
            peak = float(data.get("peak_gal", 0.0))
            shindo = data.get("shindo") or shindo_from_gal(peak)
            last_alarm["peak_gal"] = peak
            last_alarm["shindo"] = shindo
            counters["alarms"] += 1
            counters["in_alarms"] += len(data.get("nodes", []))
            row = {
                "kind": "alarm",
                "node": ", ".join(data.get("nodes", [])),
                "peak_gal": peak,
                "shindo": shindo,
                "t": time.strftime("%H:%M:%S"),
                "date": time.strftime("%Y-%m-%d"),
            }
            event_log.appendleft(row)
            quake_log.appendleft(row)
        broadcast()
        return

    if len(parts) != 3:
        return
    node_id, kind = parts[1], parts[2]

    with state_lock:
        c = channels.setdefault(node_id, {"dev_gal": 0.0, "uptime_s": 0,
                                          "last_seen": now,
                                          "trace": deque(maxlen=TRACE_LEN)})
        c["last_seen"] = now
        if kind == "tel":
            c["dev_gal"] = float(data.get("dev_gal", 0.0))
            c["uptime_s"] = int(data.get("uptime_s", 0))
            c["trace"].append(round(c["dev_gal"], 3))
        elif kind == "event":
            counters["events"] += 1
            peak = float(data.get("peak_gal", 0.0))
            event_log.appendleft({
                "kind": "event",
                "node": node_id,
                "peak_gal": peak,
                "shindo": shindo_from_gal(peak),
                "t": time.strftime("%H:%M:%S"),
            })
    broadcast()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass                                  # keep stdout for real messages

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            body = snapshot().encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = queue.Queue(maxsize=8)
            subscribers.append(q)
            try:
                self.wfile.write(f"data: {snapshot()}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        payload = q.get(timeout=2.0)
                    except queue.Empty:
                        payload = snapshot()   # heartbeat keeps clocks fresh
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                if q in subscribers:
                    subscribers.remove(q)
        else:
            self.send_error(404)


def ticker():
    """Repaint even when no MQTT arrives, so 'offline' appears on its own."""
    while True:
        time.sleep(2.0)
        broadcast()


def main():
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--http-port", type=int, default=8000)
    args = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    threading.Thread(target=ticker, daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", args.http_port), Handler)
    print(f"dashboard: http://localhost:{args.http_port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\ndashboard: stopping")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>quake-net</title>
<style>
  :root{
    --bg:#f6f7f9; --panel:#fff; --ink:#14181f; --muted:#5d6673;
    --line:#e2e6ec; --ok:#1a7f5a; --warn:#b3541e; --alarm:#c2273d;
    --accent:#2b5fd9;
  }
  @media (prefers-color-scheme:dark){:root{
    --bg:#0f1216; --panel:#171b21; --ink:#e8ecf1; --muted:#98a2b0;
    --line:#252b34; --ok:#3ecf8e; --warn:#e8a33d; --alarm:#ff5c72; --accent:#6f9bff;
  }}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:980px;margin:0 auto;padding:24px 18px 48px}
  h1{font-size:19px;margin:0;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:13px;margin-top:2px}
  header{display:flex;justify-content:space-between;align-items:flex-start;
         gap:16px;margin-bottom:20px;flex-wrap:wrap}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;
       background:var(--muted);margin-right:6px;vertical-align:1px}
  .dot.on{background:var(--ok)}
  #banner{border-radius:10px;padding:16px 18px;margin-bottom:20px;
          border:1px solid var(--line);background:var(--panel)}
  #banner.quiet .big{color:var(--muted)}
  #banner.fire{background:var(--alarm);border-color:var(--alarm);color:#fff;
               animation:pulse 1s ease-in-out infinite}
  @keyframes pulse{50%{opacity:.82}}
  @media (prefers-reduced-motion:reduce){#banner.fire{animation:none}}
  .big{font-size:26px;font-weight:640;letter-spacing:-.02em}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px;margin-bottom:20px}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;
        padding:13px 15px}
  .stat .n{font-size:24px;font-weight:640;font-variant-numeric:tabular-nums}
  .stat .l{color:var(--muted);font-size:12px;margin-top:2px}
  .stat.hero .n{color:var(--accent)}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
        padding:15px;margin-bottom:12px}
  .chead{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
  .cid{font-weight:600;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .tag{font-size:11px;padding:2px 7px;border-radius:99px;border:1px solid var(--line);
       color:var(--muted);margin-left:7px;vertical-align:1px}
  .dev{font-variant-numeric:tabular-nums;color:var(--muted);font-size:13px}
  svg{display:block;width:100%;height:44px;margin-top:9px;overflow:visible}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;
     padding:0 0 7px;border-bottom:1px solid var(--line)}
  td{padding:6px 0;border-bottom:1px solid var(--line);
     font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:0}
  td.k{font-family:ui-monospace,Menlo,monospace}
  .ev-alarm td.k{color:var(--alarm);font-weight:600}
  td.shindo{font-weight:700;font-variant-numeric:tabular-nums}
  h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;opacity:.7;
     margin:0 0 10px}
  .note{font-size:12px;opacity:.65;line-height:1.5;margin:12px 0 0}
  .empty{color:var(--muted);font-size:13px;padding:8px 0}
  footer{color:var(--muted);font-size:12px;margin-top:22px;line-height:1.7}
</style></head><body><div class="wrap">

<header>
  <div>
    <h1>quake-net</h1>
    <div class="sub">Alarm requires two distinct channels within 2&nbsp;s</div>
  </div>
  <div class="sub"><span class="dot" id="live"></span><span id="livetxt">connecting</span></div>
</header>

<div id="banner" class="quiet">
  <div class="big" id="btitle">No alarm</div>
  <div class="sub" id="bsub">Waiting for two channels to agree</div>
</div>

<div class="card">
  <h2>Earthquake log</h2>
  <table><thead><tr>
    <th>date</th><th>time</th><th>est. shindo</th>
    <th style="text-align:right">peak (gal)</th><th>channels agreeing</th>
  </tr></thead>
  <tbody id="qlog"></tbody></table>
  <div class="empty" id="qlogempty">No earthquakes recorded.</div>
  <p class="note">Shindo is <strong>estimated</strong> from peak acceleration. JMA computes the
  official value from a filtered three-component measure sustained for 0.3 s, which differs
  from a bare peak. <strong>Magnitude is not shown</strong>: it describes energy at the source
  and needs epicentre distance and depth, which one site cannot supply.</p>
</div>

<div class="stats">
  <div class="stat hero"><div class="n" id="s-rej">0</div>
    <div class="l">single-channel events rejected</div></div>
  <div class="stat"><div class="n" id="s-alarms">0</div><div class="l">alarms</div></div>
  <div class="stat"><div class="n" id="s-events">0</div><div class="l">events total</div></div>
  <div class="stat"><div class="n" id="s-chan">0</div><div class="l">channels online</div></div>
</div>

<div id="chans"></div>

<div class="card">
  <h2>All channel events</h2>
  <table><thead><tr><th>time</th><th>channel</th><th>est. shindo</th><th style="text-align:right">peak (gal)</th></tr></thead>
  <tbody id="log"></tbody></table>
  <div class="empty" id="logempty">No events yet. Shake a node.</div>
</div>

<footer>
  <strong>Rejected</strong> counts events that never became part of an alarm — each would have
  been a false alarm on a single-channel design. That is the measured value of the correlation
  rule.<br>
  Channels tagged <em>simulated</em> are software, not hardware. A
  <em>mirror-</em> channel replays another channel's samples, so its agreement is
  automatic and proves nothing — an alarm involving one is a demonstration of the
  alarm path, not evidence of ground motion.
</footer>
</div>

<script>
const $ = id => document.getElementById(id);

function spark(trace){
  if(!trace || trace.length < 2) return '<svg></svg>';
  const max = Math.max(...trace, 0.001), n = trace.length;
  const pts = trace.map((v,i) =>
    `${(i/(n-1)*100).toFixed(2)},${(40 - (v/max)*36).toFixed(2)}`).join(' ');
  return `<svg viewBox="0 0 100 44" preserveAspectRatio="none">
    <polyline points="${pts}" fill="none" stroke="var(--accent)"
      stroke-width="1.4" vector-effect="non-scaling-stroke"/></svg>`;
}

function render(s){
  const fire = s.alarm_active, b = $('banner');
  b.className = fire ? 'fire' : 'quiet';
  if(fire){
    $('btitle').textContent = 'EARTHQUAKE ALARM';
    $('bsub').textContent =
      `est. shindo ${s.last_alarm.shindo} · peak ${s.last_alarm.peak_gal.toFixed(2)} gal · `
      + s.last_alarm.nodes.join(' + ');
  } else {
    $('btitle').textContent = 'No alarm';
    $('bsub').textContent = s.counters.alarms
      ? `${s.counters.alarms} alarm(s) so far` : 'Waiting for two channels to agree';
  }

  $('s-rej').textContent = s.counters.rejected;
  $('s-alarms').textContent = s.counters.alarms;
  $('s-events').textContent = s.counters.events;
  $('s-chan').textContent = s.channels.filter(c => c.online).length;

  $('chans').innerHTML = s.channels.length ? s.channels.map(c => `
    <div class="card">
      <div class="chead">
        <div><span class="dot ${c.online?'on':''}"></span><span class="cid">${c.id}</span>
          ${c.simulated?'<span class="tag">simulated</span>':''}
          ${c.online?'':'<span class="tag">offline</span>'}</div>
        <div class="dev">${c.dev_gal.toFixed(2)} gal · up ${c.uptime_s}s</div>
      </div>${spark(c.trace)}
    </div>`).join('')
    : '<div class="card empty">No channels reporting. Start a node.</div>';

  $('qlog').innerHTML = s.quakes.map(q => `
    <tr class="ev-alarm">
      <td>${q.date}</td><td>${q.t}</td>
      <td class="shindo">${q.shindo}</td>
      <td style="text-align:right">${q.peak_gal.toFixed(2)}</td>
      <td>${q.node}</td></tr>`).join('');
  $('qlogempty').style.display = s.quakes.length ? 'none' : '';

  $('log').innerHTML = s.events.map(e => `
    <tr class="${e.kind==='alarm'?'ev-alarm':''}">
      <td>${e.t}</td><td class="k">${e.kind==='alarm'?'ALARM · ':''}${e.node}</td>
      <td class="shindo">${e.shindo}</td>
      <td style="text-align:right">${e.peak_gal.toFixed(2)}</td></tr>`).join('');
  $('logempty').style.display = s.events.length ? 'none' : '';
}

const es = new EventSource('/stream');
es.onopen = () => { $('live').classList.add('on'); $('livetxt').textContent = 'live'; };
es.onerror = () => { $('live').classList.remove('on'); $('livetxt').textContent = 'reconnecting'; };
es.onmessage = e => render(JSON.parse(e.data));
</script></body></html>
"""

if __name__ == "__main__":
    main()
