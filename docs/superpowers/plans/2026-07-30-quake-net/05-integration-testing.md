# Plan 05: Integration Testing & Tuning

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Every test here requires physically shaking hardware and reading output. An agent can prepare the log document and apply tuning edits; a human must run the tests.

**Goal:** All six design tests passing, thresholds tuned against real false-positive behaviour, and a recorded attempt at capturing a genuine earthquake.

**Architecture:** Work up from the sensor to the network. Each test isolates one layer, so a failure tells you where the problem is instead of just that there is one.

**Tech Stack:** mosquitto_sub, arduino-cli monitor

## Global Constraints

See [00-index.md](00-index.md#global-constraints). Relevant here:

- `WARMUP_MS` 3000, `REFRACTORY_MS` 5000, correlation window 2.0 s, cooldown 10.0 s
- Threshold from plan 04 — shared across both nodes

## Setup for every task

Three terminals, running throughout:

```bash
# 1: broker
mosquitto -c correlator/mosquitto.conf -v

# 2: all traffic
mosquitto_sub -h 127.0.0.1 -t 'quake/#' -v

# 3: correlator
source .venv/bin/activate && cd correlator && python main.py --broker 127.0.0.1
```

---

### Task 1: Prepare the test log

**Files:**
- Create: `docs/TESTLOG.md`

- [ ] **Step 1: Write the log skeleton**

```markdown
# Test Log

Firmware threshold: 0.00 gal. Correlation window 2.0 s, cooldown 10.0 s.
Node IDs: node-XXXXXX (node-01, has buzzer), node-XXXXXX (node-02).

| # | Test | Result | Notes |
|---|---|---|---|
| 1 | Sensor sanity — magnitude ~980 gal in all orientations | | |
| 2 | Warm-up — no event in first 3 s after boot | | |
| 3 | Single-node rejection — one node tapped, no alarm | | |
| 4 | Correlated detection — both shaken, alarm fires | | |
| 5 | Refractory — 20 s shake yields ~4 events per node | | |
| 6 | Network resilience — one node killed, clean recovery | | |
```

- [ ] **Step 2: Commit**

```bash
git add docs/TESTLOG.md
git commit -m "docs: test log skeleton"
```

---

### Task 2: Test 1 — sensor sanity

Confirms the axes and the unit conversion. If this is wrong, every later number is wrong.

- [ ] **Step 1: Watch telemetry from node-01 while rotating it**

Watch `dev_gal` in terminal 2. Slowly rotate the breadboard through flat, on-edge, and
upside-down, pausing several seconds in each orientation.

Expected: `dev_gal` spikes **during** each rotation and settles back near your noise floor
within a couple of seconds in each new orientation.

This is the EMA doing its job: it tracks the changed gravity direction, so a tilted node is
not permanently "triggered". A node that stays at a large `dev_gal` after settling means the
EMA is not updating — check `EMA_ALPHA`.

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

- [ ] **Step 1: Reboot node-01 while shaking it**

Hold the reset button, start shaking, release reset, keep shaking for 2 seconds, then stop.

Expected: **no** `quake/.../event` message. The LED may flicker, but nothing publishes.

- [ ] **Step 2: Confirm it works normally after warm-up**

Wait 5 seconds, then shake again. Expected: an event publishes.

If step 1 produced an event, `WARMUP_MS` is not being honoured — check that `t0_ms` is set on
the first sample in `detector.cpp` and that `millis()` is passed as `now_ms`.

- [ ] **Step 3: Record the result**

---

### Task 4: Test 3 — single-node rejection

**This is the most important test in the project.** It is the negative case that justifies
having two nodes at all.

- [ ] **Step 1: Tap only node-01's breadboard**

Tap firmly, several times, over about 10 seconds. Do not touch node-02 or the surface it
rests on.

Expected:
- `quake/node-01/event` messages appear
- node-01's LED lights
- **no `ALARM` line in the correlator**
- **the buzzer stays silent**

- [ ] **Step 2: Repeat with only node-02**

Expected: symmetric result. Events from node-02, no alarm.

- [ ] **Step 3: If an alarm fires, diagnose**

| Cause | Fix |
|---|---|
| Both nodes share a surface, so the tap reached both | Move them apart, or onto separate surfaces |
| Correlator counting one node twice | Should be impossible — `test_same_node_twice_does_not_alarm` covers it. Re-run `pytest test_core.py`. |
| Both nodes reporting the **same** ID | Both would need identical MAC bytes. Check the `id=` line from each node's serial output. |

- [ ] **Step 4: Record the result**

---

### Task 5: Test 4 — correlated detection

- [ ] **Step 1: Place both nodes on the same table and shake the table**

Not the breadboards — the table both rest on. This is the earthquake analogue: one motion,
reaching both sensors.

Expected, in order:
- both LEDs light
- two `event` messages, one per node
- one `ALARM` line naming both nodes
- node-01's buzzer sounds for about 1.5 s

- [ ] **Step 2: Confirm the alarm peak is the maximum, not the latest**

The `ALARM` line's `peak_gal` should equal the larger of the two `event` peaks.

- [ ] **Step 3: Time the two-node demo contrast**

Run Task 4 Step 1 and this test back to back, as you will on demo day. Tap one node — LED,
no buzzer. Shake the table — LEDs, buzzer. Practise the timing; the cooldown is 10 s, so
leave a gap between the two halves or the second will be suppressed.

- [ ] **Step 4: Record the result**

---

### Task 6: Test 5 — refractory window

- [ ] **Step 1: Shake the table continuously for 20 seconds**

Count `event` messages per node in terminal 2.

Expected: **3 per node**, published at roughly 5 s intervals. Not 4 — an event is published
when its refractory window *closes*, so a 20 s shake closes three windows and leaves a fourth
still open. The count always lags the shake by one window. Two to four is fine depending on
when you started and stopped.

Seeing dozens or hundreds means the refractory logic is not engaging. `test_one_event_per_refractory_window`
covers this on the host, so re-run `cd test && make run` before suspecting the hardware.

- [ ] **Step 2: Confirm the correlator emitted only one alarm**

Expected: **one** `ALARM`, not four. The 10 s cooldown collapses a 20 s shake into a single
alarm — which is what you want, since it is one earthquake.

- [ ] **Step 3: Record the result**

---

### Task 7: Test 6 — network resilience

- [ ] **Step 1: Unplug node-02's USB power mid-run**

Expected: node-02's telemetry stops. The correlator keeps running and does not crash.

- [ ] **Step 2: Shake the table with only node-01 alive**

Expected: events from node-01, **no alarm** — the correlator can never reach two distinct
nodes. This is correct behaviour and worth demonstrating: a degraded network fails safe
rather than raising false alarms.

- [ ] **Step 3: Plug node-02 back in**

Expected: telemetry resumes within about 10 seconds without touching anything. Then shake the
table and confirm the alarm fires again.

- [ ] **Step 4: Kill the broker while both nodes run**

Ctrl-C the mosquitto terminal. Expected: node LEDs still respond to shaking — detection is
independent of the network. Restart the broker; telemetry resumes on its own.

- [ ] **Step 5: Record the result**

- [ ] **Step 6: Commit the completed log**

```bash
git add docs/TESTLOG.md
git commit -m "test: all six integration tests recorded"
```

---

### Task 8: Tune against real false positives

The threshold from plan 04 came from 60 quiet seconds. Real rooms are not quiet for 60
seconds. This task finds out what actually trips it.

- [ ] **Step 1: Run for one hour of normal activity**

Leave everything running while you work normally at the desk — typing, walking past, opening
doors, moving your chair.

```bash
mosquitto_sub -h 127.0.0.1 -t 'quake/+/event' -v | tee /tmp/onehour.log
```

- [ ] **Step 2: Count false positives**

```bash
wc -l /tmp/onehour.log
grep -c ALARM /tmp/onehour.log || true
```

- [ ] **Step 3: Apply the tuning decision**

| Observation | Change | Why |
|---|---|---|
| Many single-node events, **zero** alarms | **Nothing.** This is the system working. | Correlation is rejecting local noise exactly as designed. Single-node events are not failures — they are the evidence your architecture works. Report this count. |
| Alarms fire from walking past | Raise `THRESHOLD_GAL` by 2× and reflash both nodes | Footsteps couple into both nodes through the floor, so correlation cannot reject them. Only amplitude can. |
| One node produces 10× the events of the other | Recalibrate that node (plan 04 Task 2). It may sit on a resonant spot. | Move it, or accept the higher shared threshold. |
| Zero events even when you shake the table hard | Lower `THRESHOLD_GAL` by 2× | Threshold is above your achievable shake amplitude. |
| Events but never an alarm, even shaking the table | Raise the correlation window: `--window 3.0` | Nodes may be triggering more than 2 s apart if one is much less sensitive. |

Change **one** thing at a time, then re-run tests 3 and 4. Two simultaneous changes and you
will not know which one helped.

- [ ] **Step 4: Record the final tuned values in `docs/RESULTS.md`**

Add a section:

```markdown
## Tuning

One hour of normal desk activity produced N single-node events and M alarms.
Final threshold: 0.00 gal. Correlation window: 2.0 s.

Single-node events rejected by correlation: N. Each would have been a false
alarm on a single-node design.
```

That last number is the strongest quantitative result in the project. It is the measured
value of the architecture.

- [ ] **Step 5: Commit**

```bash
git add docs/RESULTS.md
git commit -m "docs: tuning results and false-positive rejection count"
```

---

### Task 9: Attempt a real earthquake capture

Optional and time-dependent. Roughly 5–7 shindo-3+ opportunities per three months near
Tokyo; fewer elsewhere. Not required for the project to succeed.

- [ ] **Step 1: Leave the system logging unattended**

```bash
mosquitto_sub -h 127.0.0.1 -t 'quake/#' -v | tee -a /tmp/quake-long.log
```

Both nodes powered from a charger, not the laptop, so the log survives sleep. Keep it running
for days.

- [ ] **Step 2: Check the log after any shaking you feel**

```bash
grep -A2 -B2 ALARM /tmp/quake-long.log
```

- [ ] **Step 3: Cross-check against JMA**

Look the event up in [JMA's shindo database](https://www.data.jma.go.jp/eqdb/data/shindo/) by
date and time. Record the published shindo for your prefecture next to your measured
`peak_gal`.

- [ ] **Step 4: Record it in `docs/RESULTS.md`**

Fill in the "Captured real events" table with timestamp, your peak in gal, which nodes fired,
and JMA's published shindo. A single verified row is a strong result. Report honestly if you
capture nothing — with a measured noise floor you can state exactly what magnitude you *would*
have caught, which is a legitimate finding either way.

- [ ] **Step 5: Commit**

```bash
git add docs/RESULTS.md
git commit -m "docs: real event capture attempt"
```

---

## Done when

- All six rows in `docs/TESTLOG.md` are filled in and passing
- `docs/RESULTS.md` records the one-hour false-positive count and final tuned threshold
- Test 3 (single-node rejection) passes reliably — without it there is no project

Next: [06-public-release.md](06-public-release.md)
