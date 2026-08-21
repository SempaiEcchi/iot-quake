# Measured results

## Noise floor

Captured 2026-08-21 with `firmware/calibrate`, board stationary on a desk,
177 s at 100 Hz. First 3 s discarded while the EMA settles.

| | |
|---|---|
| Samples | 17675 |
| Duration | 176.8 s |
| **RMS** | **0.733 gal** |
| Peak | 3.295 gal (4.5 sigma) |

The design predicted roughly 0.9 gal for an MPU6050 band-limited to 0.2-5 Hz.
Measured 0.733 gal is **below** that, which answers the spec's open question:
this floor is **sensor-dominated, not building-dominated**. The 5 Hz DLPF is
doing its job and the desk is not the limiting factor.

## Threshold choice

Samples exceeding each candidate, over the same 177 s window:

| Multiplier | Threshold | Samples over | Extrapolated per hour |
|---|---|---|---|
| 3x | 2.20 gal | 60 | 1222.1 |
| 5x | 3.67 gal | 0 | 0.0 |
| 10x | 7.33 gal | 0 | 0.0 |

**Chosen: 10x = 7.33 gal.**

The spec recommended 5x, on the assumption of a 0.9 gal floor where 10x would
have been 9 gal -- above shindo 3's 8 gal ceiling. The measured floor is lower,
so 10x lands at 7.33 gal and still sits inside shindo 3 (2.5-8 gal). The
conservative multiplier and shindo 3 coverage are no longer in tension. This is
precisely why the plan forbids guessing the threshold.

5x was rejected on the evidence: it would put the threshold at 3.67 gal
against an observed peak of 3.295 gal in only three minutes of a quiet
room. That peak is 4.5 sigma, heavier-tailed than Gaussian, so the
spec's "~1 false trigger per two days" estimate does not hold in this
environment.

## Detection floor

At 7.33 gal the node triggers on shindo 3 and above. Shindo 1-2 is below
the sensor's noise floor and is not detectable with an MPU6050 -- a hardware
limit, not a tuning one.

## Sample rate

Confirmed 100 Hz flat via the node's health line. An earlier measurement showed
1 Hz, caused by blocking MQTT reconnects against an unreachable broker; see the
backoff fix in `node.ino`.

## Still outstanding

- Channel B (`0x69`) has no sensor yet and runs simulated. Alarms therefore
  self-correlate and are a demo, not evidence.
- No real earthquake captured yet.
