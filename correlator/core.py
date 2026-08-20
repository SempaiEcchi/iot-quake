"""Correlation rule. No network, no wall clock - `now` is always passed in."""
from dataclasses import dataclass

# Peak acceleration -> approximate JMA shindo. Upper bound of each band, in gal.
#
# This is an ESTIMATE and must be labelled as one everywhere it is shown. Real
# JMA shindo is not a function of peak acceleration: it comes from a filtered,
# three-component measure of the acceleration sustained for 0.3 s, which
# systematically differs from a bare peak. The bands below are the classical
# intensity-acceleration correspondence, consistent with the 2.5-8 gal figure
# for shindo 3 used elsewhere in this project.
_SHINDO_BANDS = [
    (0.2, "0"),
    (0.8, "1"),
    (2.5, "2"),
    (8.0, "3"),
    (25.0, "4"),
    (80.0, "5-"),
    (140.0, "5+"),
    (250.0, "6-"),
    (400.0, "6+"),
]


def shindo_from_gal(peak_gal: float) -> str:
    """Approximate JMA shindo for a peak acceleration in gal.

    Returns the band label, not a number: JMA's 5 and 6 are each split into
    weak (-) and strong (+), so "5-" is a real intensity and 5.0 is not.
    """
    for upper, label in _SHINDO_BANDS:
        if peak_gal < upper:
            return label
    return "7"


# Magnitude is deliberately absent. It describes the energy released at the
# source, and recovering it needs epicentre distance and depth -- neither of
# which a single site can supply. One station's peak acceleration is consistent
# with a small nearby quake or a large distant one, so any magnitude printed
# here would be invented. Shindo is different: it is defined as local shaking,
# which is exactly what this measures.


@dataclass(frozen=True)
class Alarm:
    nodes: list[str]
    peak_gal: float

    @property
    def shindo(self) -> str:
        """Approximate shindo. See shindo_from_gal."""
        return shindo_from_gal(self.peak_gal)


class Correlator:
    """Declares an earthquake when >= min_nodes distinct nodes trigger inside window_s.

    A single node shaking is local noise - a truck, a door, someone leaning on
    the desk. Ground motion reaches every node. Requiring agreement is what
    separates the two, and it is the whole point of requiring two channels.
    """

    def __init__(self, window_s: float = 2.0, cooldown_s: float = 10.0,
                 min_nodes: int = 2):
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self.min_nodes = min_nodes
        self._recent: list[tuple[str, float, float]] = []   # (node, peak, t)
        self._last_alarm_at: float | None = None

    def add_event(self, node_id: str, peak_gal: float, now: float) -> Alarm | None:
        self._recent.append((node_id, peak_gal, now))
        # Drop anything that fell out of the window.
        self._recent = [e for e in self._recent if now - e[2] <= self.window_s]

        if (self._last_alarm_at is not None
                and now - self._last_alarm_at < self.cooldown_s):
            return None      # one earthquake, one alarm

        nodes = {e[0] for e in self._recent}
        if len(nodes) < self.min_nodes:
            return None

        self._last_alarm_at = now
        peak = max(e[1] for e in self._recent)
        self._recent.clear()
        return Alarm(nodes=sorted(nodes), peak_gal=peak)
