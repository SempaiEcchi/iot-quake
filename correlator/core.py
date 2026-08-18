"""Correlation rule. No network, no wall clock - `now` is always passed in."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Alarm:
    nodes: list[str]
    peak_gal: float


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
