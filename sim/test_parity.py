"""The C++ detector tests, re-run against the Python port.

Same cases, same numbers as test/test_detector.cpp. If these pass and the C++
tests pass, the mock node is running the same algorithm as the firmware and
mock results mean something.
"""
import pytest

from detector import Detector, GAL_PER_G as G


def quiet(d, n, t_ms):
    """Feed n quiet samples 10 ms apart. Returns the next timestamp."""
    for _ in range(n):
        d.update(G, t_ms)
        t_ms += 10
    return t_ms


def test_baseline_converges_to_gravity():
    d = Detector(50.0)
    quiet(d, 1000, 0)
    o = d.update(G, 10000)
    assert abs(o.dev_gal) < 0.01


def test_no_event_during_warmup():
    d = Detector(50.0)
    t = quiet(d, 100, 0)                 # t = 1000 ms, still inside warmup
    o = d.update(G + 1000.0, t)
    assert o.dev_gal > 900.0             # deviation is seen...
    assert not o.started                 # ...but must not trigger
    assert not o.event_done


def test_event_fires_after_refractory():
    d = Detector(50.0)
    t = quiet(d, 400, 0)                 # t = 4000 ms, past warmup

    o = d.update(G + 1000.0, t)
    assert o.started
    assert not o.event_done              # not yet -- refractory is open
    assert abs(o.dev_gal - 1000.0) < 1.0
    t += 10

    events, peak = 0, 0.0
    for _ in range(600):                 # 6 s of quiet
        q = d.update(G, t)
        t += 10
        if q.event_done:
            events += 1
            peak = q.peak_gal
    assert events == 1
    assert abs(peak - 1000.0) < 1.0      # the true peak, not a later sample


def test_below_threshold_never_triggers():
    d = Detector(50.0)
    t = quiet(d, 400, 0)
    for i in range(500):
        mag = G + (10.0 if i % 2 else -10.0)
        o = d.update(mag, t)
        t += 10
        assert not o.started
        assert not o.event_done


def test_one_event_per_refractory_window():
    d = Detector(50.0)
    t = quiet(d, 400, 0)                 # t = 4000 ms
    events = 0
    for i in range(2500):                # 25 s of sustained +-200 gal shaking
        mag = G + (200.0 if i % 2 else -200.0)
        o = d.update(mag, t)
        t += 10
        if o.event_done:
            events += 1
    # Events CLOSE at t = 9000, 14010, 19020, 24030. Four, not hundreds. A
    # fifth is open but unclosed when the loop ends, so the count lags the
    # shake duration by one window.
    assert events == 4


def test_duration_measures_time_above_threshold():
    d = Detector(50.0)
    t = quiet(d, 400, 0)
    for i in range(100):                 # 1 s above threshold
        mag = G + (200.0 if i % 2 else -200.0)
        d.update(mag, t)
        t += 10
    dur = 0
    for _ in range(600):                 # then quiet until it closes
        o = d.update(G, t)
        t += 10
        if o.event_done:
            dur = o.dur_ms
    assert 900 <= dur <= 1100            # ~1 s, not the 5 s refractory
