from core import Alarm, Correlator, shindo_from_gal


def test_single_node_does_not_alarm():
    """The core negative case: one node shaking is local noise, not a quake."""
    c = Correlator()
    assert c.add_event("node-aaa", 100.0, now=0.0) is None


def test_same_node_twice_does_not_alarm():
    """Two events from one node must not be mistaken for two nodes agreeing."""
    c = Correlator()
    assert c.add_event("node-aaa", 100.0, now=0.0) is None
    assert c.add_event("node-aaa", 120.0, now=0.5) is None


def test_two_nodes_within_window_alarms():
    c = Correlator()
    assert c.add_event("node-aaa", 100.0, now=0.0) is None
    alarm = c.add_event("node-bbb", 150.0, now=1.0)
    assert alarm is not None
    assert sorted(alarm.nodes) == ["node-aaa", "node-bbb"]
    assert alarm.peak_gal == 150.0          # the max, not the latest


def test_two_nodes_outside_window_does_not_alarm():
    c = Correlator()
    assert c.add_event("node-aaa", 100.0, now=0.0) is None
    assert c.add_event("node-bbb", 150.0, now=3.0) is None   # window is 2.0 s


def test_cooldown_suppresses_second_alarm():
    c = Correlator()
    c.add_event("node-aaa", 100.0, now=0.0)
    assert c.add_event("node-bbb", 150.0, now=1.0) is not None
    c.add_event("node-aaa", 100.0, now=5.0)
    assert c.add_event("node-bbb", 150.0, now=5.5) is None    # cooldown is 10.0 s


def test_new_alarm_allowed_after_cooldown():
    c = Correlator()
    c.add_event("node-aaa", 100.0, now=0.0)
    assert c.add_event("node-bbb", 150.0, now=1.0) is not None
    c.add_event("node-aaa", 100.0, now=12.0)
    assert c.add_event("node-bbb", 150.0, now=12.5) is not None


def test_three_nodes_still_one_alarm():
    """min_nodes is a floor, not an exact count."""
    c = Correlator(min_nodes=2)
    c.add_event("node-aaa", 100.0, now=0.0)
    assert c.add_event("node-bbb", 150.0, now=0.5) is not None
    assert c.add_event("node-ccc", 900.0, now=1.0) is None    # cooldown holds


def test_stale_events_are_pruned():
    """An old event must not combine with a much later one."""
    c = Correlator()
    c.add_event("node-aaa", 100.0, now=0.0)
    for t in (10.0, 20.0, 30.0):
        assert c.add_event("node-aaa", 100.0, now=t) is None
    assert c.add_event("node-bbb", 100.0, now=40.0) is None


# --- shindo estimation ---

def test_shindo_band_boundaries():
    # Each band is [lower, upper). Check both sides of every edge so an
    # off-by-one in the comparison cannot pass.
    assert shindo_from_gal(0.0) == "0"
    assert shindo_from_gal(0.19) == "0"
    assert shindo_from_gal(0.2) == "1"
    assert shindo_from_gal(0.79) == "1"
    assert shindo_from_gal(0.8) == "2"
    assert shindo_from_gal(2.49) == "2"
    assert shindo_from_gal(2.5) == "3"
    assert shindo_from_gal(7.99) == "3"
    assert shindo_from_gal(8.0) == "4"
    assert shindo_from_gal(24.99) == "4"
    assert shindo_from_gal(25.0) == "5-"
    assert shindo_from_gal(80.0) == "5+"
    assert shindo_from_gal(140.0) == "6-"
    assert shindo_from_gal(250.0) == "6+"
    assert shindo_from_gal(400.0) == "7"
    assert shindo_from_gal(10000.0) == "7"


def test_shindo_3_matches_the_design_target():
    # The whole threshold argument in the design rests on shindo 3 being
    # 2.5-8 gal. If this drifts, the 5x multiplier rationale is wrong too.
    assert shindo_from_gal(2.5) == "3"
    assert shindo_from_gal(7.9) == "3"


def test_alarm_exposes_shindo():
    a = Alarm(nodes=["node-a", "node-b"], peak_gal=12.0)
    assert a.shindo == "4"
