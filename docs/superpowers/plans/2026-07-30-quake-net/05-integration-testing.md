# Plan 05: Integration Testing & Tuning

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Every test here requires physically shaking hardware and reading output. An agent can prepare the log document and apply tuning edits; a human must run the tests.

**Goal:** All six design tests passing, the threshold tuned against real false-positive behaviour, and a recorded attempt at capturing a genuine earthquake.

**Architecture:** Work up from the sensor to the network. Each test isolates one layer, so a failure tells you where the problem is instead of just that there is one.

**Tech Stack:** mosquitto_sub, arduino-cli monitor

## Global Constraints

See [00-index.md](00-index.md#global-constraints). Relevant here:

- `WARMUP_MS` 3000, `REFRACTORY_MS` 5000, correlation window 2.0 s, cooldown 10.0 s
- Threshold from plan 04 — measured, not guessed
- Channel B is `fake_node.py`, triggered by hand and subscribing to nothing

## Setup for every task

Four terminals. **Note which tests need `fake_node.py` stopped** — Test 3 depends on it.

```bash
# 1: broker
mosquitto -c correlator/mosquitto.conf -v

# 2: all traffic
mosquitto_sub -h 127.0.0.1 -t 'quake/#' -v

# 3: correlator
source .venv/bin/activate && cd correlator && python main.py --broker 127.0.0.1

# 4: simulated channel — START ONLY WHEN A TEST CALLS FOR IT
source .venv/bin/activate && cd correlator && python fake_node.py --broker 127.0.0.1
```

---

### Task 1: Prepare the test log

**Files:**
- Create: `docs/TESTLOG.md`

- [ ] **Step 1: Write the log skeleton**

```markdown
# Test Log

Firmware threshold: 0.00 gal. Correlation window 2.0 s, cooldown 10.0 s.
Real node: node-XXXXXX. Simulated channel: sim-000001 (keypress-triggered).

| # | Test | Result | Notes |
|---|---|---|---|
| 1 | Sensor sanity — magnitude ~980 gal in all orientations | | |
| 2 | Warm-up — no event in first 3 s after boot | | |
| 3 | Single-channel rejection — real node alone, no alarm | | |
| 4 | Correlated detection — node + sim within 2 s, alarm fires | | |
| 5 | Refractory — 20 s shake yields 3 events | | |
| 6 | Resilience — broker killed, LED still works, clean recovery | | |
```

- [ ] **Step 2: Commit**

```bash
git add docs/TESTLOG.md
git commit -m "docs: test log skeleton"
```

---

### Task 2: Test 1 — sensor sanity

Confirms the axes and the unit conversion. If this is wrong, every later number is wrong.

- [ ] **Step 1: Watch telemetry while rotating the node**

Watch `dev_gal` in terminal 2. Slowly rotate the breadboard through flat, on-edge, and
upside-down, pausing several seconds in each orientation.

Expected: `dev_gal` spikes **during** each rotation and settles back near your noise floor
within a couple of seconds in each new orientation.

That is the EMA doing its job: it tracks the changed gravity direction, so a tilted node is not
permanently "triggered". A node that stays at a large `dev_gal` after settling means the EMA is
not updating — check `EMA_ALPHA`.

- [ ] **Step 2: Verify absolute magnitude with the calibration sketch**

`dev_gal` shows deviation, not absolute magnitude, so it cannot confirm the gal conversion.
Reflash `firmware/calibrate` briefly and add one line after the `mag` computation:

```cpp
  Serial.printf("mag=%.1f dev=%.3f\n", mag, seeded ? fabsf(mag - baseline) : 0.0f);
```

Expected: `mag` between roughly 960 and 1000 gal in every orientation — that is 1 g. A value
near 9.8 means the code is in m/s² somewhere; near 1.0 means it is in g. Both are unit bugs.

- [ ] **Step 3: Reflash the real firmware**

```bash
arduino-cli upload -p /dev/cu.usbserial-0001 --fqbn esp32:esp32:esp32 firmware/node
```

- [ ] **Step 4: Record the result in `docs/TESTLOG.md`**

---

### Task 3: Test 2 — warm-up suppression

- [ ] **Step 1: Reboot while shaking**

Hold the reset button, start shaking, release reset, keep shaking for 2 seconds, then stop.

Expected: **no** `quake/.../event` message. The LED may flicker, but nothing publishes.

- [ ] **Step 2: Confirm it works normally after warm-up**

Wait 5 seconds, then shake again. Expected: an event publishes.

If step 1 produced an event, `WARMUP_MS` is not being honoured — check that `t0_ms` is set on
the first sample in `detector.cpp` and that `millis()` is passed as `now_ms`.

- [ ] **Step 3: Record the result**

---

### Task 4: Test 3 — single-channel rejection

**This is the most important test in the project, and the only part of the correlation
demonstration that is entirely real hardware.** It is the negative case that justifies the
architecture.

**`fake_node.py` must be stopped.** Kill terminal 4 before starting.

- [ ] **Step 1: Confirm the simulated channel is not running**

```bash
pgrep -fl fake_node.py || echo "correct: not running"
```

Expected: `correct: not running`.

- [ ] **Step 2: Tap the breadboard repeatedly**

Tap firmly, several times, over about 10 seconds.

Expected:
- `quake/node-XXXXXX/event` messages appear
- the LED lights on each trigger
- **no `ALARM` line in the correlator**
- **the buzzer stays silent**

- [ ] **Step 3: If an alarm fires, diagnose**

| Cause | Fix |
|---|---|
| `fake_node.py` still running | Kill it. Step 1 exists to catch this. |
| Correlator counting one node twice | Should be impossible — `test_same_node_twice_does_not_alarm` covers it. Re-run `pytest test_core.py`. |
| A stray `mosquitto_pub` or old process publishing events | `pgrep -fl mosquitto_pub`, and check the broker log for a third client ID. |

- [ ] **Step 4: Record the result**

Note the event count. Every one of these is a rejection — on a single-channel design each would
have been a false alarm.

---

### Task 5: Test 4 — correlated detection

- [ ] **Step 1: Start the simulated channel**

Terminal 4:

```bash
source .venv/bin/activate && cd correlator && python fake_node.py --broker 127.0.0.1
```

- [ ] **Step 2: Tap the breadboard, then press Enter within 2 seconds**

Expected, in order:
- LED lights, `event` from `node-XXXXXX`
- `event` from `sim-000001`
- one `ALARM` naming both
- the buzzer sounds for about 1.5 s

- [ ] **Step 3: Confirm the alarm peak is the maximum, not the latest**

The `ALARM` line's `peak_gal` should equal the larger of the two `event` peaks. `fake_node.py`
reports a random 20–80 gal by default, so pass `--peak 5` if you want the real node's tap to be
the larger of the two and prove the max is being taken.

- [ ] **Step 4: Practise the demo contrast**

Run Task 4 Step 2 and this test back to back, as you will on demo day. Tap alone — LED, no
buzzer. Tap plus Enter — LED, buzzer. Leave more than 10 s between the two halves or the
cooldown suppresses the second.

Rehearse saying the honest version out loud: *"the second channel here is simulated — what this
shows is the protocol and the correlation rule; the rejection you just saw was real."*

- [ ] **Step 5: Record the result**

---

### Task 6: Test 5 — refractory window

- [ ] **Step 1: Shake the breadboard continuously for 20 seconds**

Count `event` messages from the real node in terminal 2.

Expected: **3**, published at roughly 5 s intervals. Not 4 — an event publishes when its
refractory window *closes*, so a 20 s shake closes three windows and leaves a fourth still open.
The count always lags the shake by one window. Two to four is fine depending on when you started
and stopped.

Seeing dozens or hundreds means the refractory logic is not engaging.
`test_one_event_per_refractory_window` covers this on the host, so re-run `cd test && make run`
before suspecting the hardware.

- [ ] **Step 2: Confirm the cooldown collapses repeats**

With `fake_node.py` running, shake for 20 s and press Enter several times. Expected: **one**
`ALARM`, not several. The 10 s cooldown collapses sustained shaking into a single alarm — which
is what you want, since it is one earthquake.

- [ ] **Step 3: Record the result**

---

### Task 7: Test 6 — resilience

- [ ] **Step 1: Kill the broker while the node runs**

Ctrl-C the mosquitto terminal.

Expected: the LED **still responds to shaking**. Detection is independent of the network. This is
the point of keeping the detector free of I/O.

- [ ] **Step 2: Confirm sampling did not corrupt itself**

Restart the broker. Expected: telemetry resumes within about 10 seconds without touching the
node, and `dev_gal` returns to its normal noise-floor value rather than sitting at some large
number.

A `dev_gal` stuck high after reconnect would mean the sample gate caught up in a burst and
poisoned the EMA baseline — the exact failure the resync guard prevents. If you see it, check
that the resync branch is present in `loop()`.

- [ ] **Step 3: Kill the simulated channel and confirm fail-safe**

With the broker back up, stop `fake_node.py` and shake the node.

Expected: events, **no alarm**. The correlator can never reach two distinct channels. A degraded
network fails safe rather than raising false alarms — worth demonstrating explicitly.

- [ ] **Step 4: Unplug the node's USB power, then restore it**

Expected: telemetry stops, correlator keeps running and does not crash, and telemetry resumes on
its own after reconnection. Remember the 3 s warm-up applies again after every boot.

- [ ] **Step 5: Kill the internet and confirm the local path survives**

Turn off the hotspot's mobile data, leaving WiFi up.

Expected: the Thingsboard dashboard stops updating, but events, correlation, alarm, and buzzer
all still work. The cloud must never be load-bearing.

- [ ] **Step 6: Record the result**

- [ ] **Step 7: Commit the completed log**

```bash
git add docs/TESTLOG.md
git commit -m "test: all six integration tests recorded"
```

---

### Task 8: Tune against real false positives

The threshold from plan 04 came from 60 quiet seconds. Real rooms are not quiet for 60 seconds.
This task finds out what actually trips it.

- [ ] **Step 1: Run for one hour of normal activity**

Leave everything running — **with `fake_node.py` stopped** — while you work normally at the
desk: typing, walking past, opening doors, moving your chair.

```bash
mosquitto_sub -h 127.0.0.1 -t 'quake/+/event' -v | tee /tmp/onehour.log
```

- [ ] **Step 2: Count the events**

```bash
wc -l /tmp/onehour.log
```

With the simulated channel stopped, **every line here is a rejection**: a single-channel event
that produced no alarm.

- [ ] **Step 3: Apply the tuning decision**

| Observation | Change | Why |
|---|---|---|
| A moderate number of events, **zero** alarms | **Nothing.** This is the system working. | Correlation rejected every one. Report the count — it is the measured value of the architecture. |
| Hundreds of events per hour | Raise `THRESHOLD_GAL` by 2× and reflash | Below this level the threshold is tracking ordinary room noise, and the event log becomes useless for spotting a real quake. |
| Zero events even when you shake the desk hard | Lower `THRESHOLD_GAL` by 2× | Threshold is above your achievable shake amplitude. |
| Events cluster at one time of day | Nothing — record it | Building activity. A genuine, reportable observation about environmental noise. |
| Alarm fires with `fake_node.py` stopped | Investigate immediately | Impossible by design. Something else is publishing events. |

Change **one** thing at a time, then re-run tests 3 and 4. Two simultaneous changes and you will
not know which one helped.

- [ ] **Step 4: Record the final tuned values in `docs/RESULTS.md`**

Add a section:

```markdown
## Tuning

One hour of normal desk activity, simulated channel stopped: N single-channel
events, 0 alarms.

Final threshold: 0.00 gal. Correlation window: 2.0 s.

All N events were rejected by the correlation rule. On a single-channel design
each would have been a false alarm - a false-alarm rate of N/hour reduced to 0.
```

That last figure is the strongest quantitative result in the project.

- [ ] **Step 5: Commit**

```bash
git add docs/RESULTS.md
git commit -m "docs: tuning results and false-positive rejection count"
```

---

### Task 9: Attempt a real earthquake capture

Optional and time-dependent. Roughly 5–7 shindo-3+ opportunities per three months near Tokyo;
fewer elsewhere. Not required for the project to succeed.

**Read this first.** A real earthquake shakes the real node only. The simulated channel is
keypress-triggered, so **it will not fire and no alarm will be raised.** Real-event capture is
therefore evaluated from the *event log*, not from alarms. Say this plainly in the report — it
is a direct consequence of having one ESP32, and an examiner will ask.

- [ ] **Step 1: Leave the system logging unattended**

```bash
mosquitto_sub -h 127.0.0.1 -t 'quake/#' -v | tee -a /tmp/quake-long.log
```

Power the node from a charger, not the laptop, so the log survives sleep. Keep it running for
days. Leave `fake_node.py` stopped — a stray keypress would fabricate an event in your
long-run log.

- [ ] **Step 2: After any shaking you feel, check the log**

```bash
grep -c 'event' /tmp/quake-long.log
grep 'event' /tmp/quake-long.log | tail -20
```

- [ ] **Step 3: Cross-check against JMA**

Look the event up in [JMA's shindo database](https://www.data.jma.go.jp/eqdb/data/shindo/) by
date and time. Record the published shindo for your prefecture next to your measured `peak_gal`.

Correlating your timestamp with JMA's is what turns a spike in a log into evidence. Without it
you cannot distinguish an earthquake from someone bumping the desk — which, with one real
channel, is exactly the ambiguity the architecture was meant to remove.

- [ ] **Step 4: Record it in `docs/RESULTS.md`**

Fill in the "Captured real events" table with timestamp, your peak in gal, and JMA's published
shindo. A single verified row is a strong result.

Report honestly if you capture nothing. With a measured noise floor you can state exactly what
magnitude you *would* have caught, which is a legitimate finding either way.

- [ ] **Step 5: Commit**

```bash
git add docs/RESULTS.md
git commit -m "docs: real event capture attempt"
```

---

## Done when

- All six rows in `docs/TESTLOG.md` are filled in and passing
- `docs/RESULTS.md` records the one-hour event count and final tuned threshold
- Test 3 (single-channel rejection) passes reliably — without it there is no project

Next: [06-public-release.md](06-public-release.md)
