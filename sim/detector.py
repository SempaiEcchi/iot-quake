"""Python port of firmware/node/detector.cpp.

This exists so the mock node runs the SAME algorithm as the ESP32. If the two
ever drift apart, mock testing stops telling you anything about the firmware,
so test_parity.py re-runs the C++ test cases against this port.

Keep this file and detector.cpp in step. Any change to one needs the same
change to the other.
"""
from dataclasses import dataclass

EMA_ALPHA = 0.01      # single-pole high-pass; ~1 s time constant at 100 Hz
WARMUP_MS = 3000      # suppress triggers while the baseline settles
REFRACTORY_MS = 5000  # one event per shake, not hundreds

GAL_PER_G = 980.665


@dataclass
class DetectorOut:
    dev_gal: float = 0.0     # deviation from baseline, always valid
    started: bool = False    # True on the one sample that opens an event
    event_done: bool = False # True on the one sample that closes an event
    peak_gal: float = 0.0    # valid when event_done
    dur_ms: int = 0          # valid when event_done


class Detector:
    def __init__(self, threshold_gal: float,
                 warmup_ms: int = WARMUP_MS,
                 refractory_ms: int = REFRACTORY_MS):
        self.threshold_gal = threshold_gal
        self.warmup_ms = warmup_ms
        self.refractory_ms = refractory_ms
        self.baseline = 0.0
        self.samples = 0
        self.t0_ms = 0
        self.in_event = False
        self.peak_gal = 0.0
        self.event_start_ms = 0
        self.last_over_ms = 0

    def update(self, mag_gal: float, now_ms: int) -> DetectorOut:
        out = DetectorOut()

        if self.samples == 0:
            # Seed the baseline to the first sample instead of 0. Without this
            # the first deviation is ~980 gal and the filter spends a second
            # settling.
            self.baseline = mag_gal
            self.t0_ms = now_ms
            self.samples = 1
            return out                      # dev is meaningless for sample one

        # Deviation against the PREVIOUS baseline, then update. This order lets
        # a single spike report its full amplitude rather than one diluted by
        # itself.
        out.dev_gal = abs(mag_gal - self.baseline)
        self.baseline = (1.0 - EMA_ALPHA) * self.baseline + EMA_ALPHA * mag_gal
        self.samples += 1

        if now_ms - self.t0_ms < self.warmup_ms:
            return out                      # still settling

        if self.in_event:
            if out.dev_gal > self.peak_gal:
                self.peak_gal = out.dev_gal
            if out.dev_gal > self.threshold_gal:
                self.last_over_ms = now_ms

            if now_ms - self.event_start_ms >= self.refractory_ms:
                out.event_done = True
                out.peak_gal = self.peak_gal
                out.dur_ms = self.last_over_ms - self.event_start_ms
                self.in_event = False
                self.peak_gal = 0.0
        elif out.dev_gal > self.threshold_gal:
            out.started = True
            self.in_event = True
            self.event_start_ms = now_ms
            self.last_over_ms = now_ms
            self.peak_gal = out.dev_gal

        return out
