"""Real junction geometry, loaded from config/junction.json (built by tools/import_osm.py).

Arms are labelled N/E/S/W by nearest compass bearing; each arm's `axis` is the road centreline
from the junction centre outward, in local ENU metres (x east, y north).
"""
from dataclasses import dataclass
from functools import cached_property
import json
import os
from pathlib import Path

from simulation.geometry import offset, point_at, resample, signed_angle, sub, unit

ROOT = Path(__file__).resolve().parents[1]
PATH = Path(os.environ.get("TRAFFIC_JUNCTION", ROOT / "config/junction.json"))
DATA = json.loads(PATH.read_text())
LEFT_HAND = DATA["driving_side"] == "left"
# Near-side turn needs no crossing of oncoming traffic; far-side turn is permissive.
NEAR_TURN, FAR_TURN = ("left", "right") if LEFT_HAND else ("right", "left")


@dataclass(frozen=True)
class Arm:
    id: str
    name: str
    axis: tuple
    lane_width: float
    median: float
    in_lanes: int
    out_lanes: int
    stop: float
    extent: float

    @cached_property
    def outward(self):
        return unit(sub(point_at(self.axis, 30), point_at(self.axis, 0)))

    def _lateral(self, lanes, index):
        # Index 0 is the kerb lane; the highest index is next to the median.
        return self.median / 2 + (lanes - index - 0.5) * self.lane_width

    def inbound(self, lane, start, end):
        """Inbound lane centreline from axis distance `end` (far) to `start` (near centre)."""
        side = -1 if LEFT_HAND else 1  # LHT: inbound traffic is right of the outward axis.
        return offset(resample(self.axis, start, end), side * self._lateral(self.in_lanes, lane))[::-1]

    def outbound(self, lane, start, end):
        side = 1 if LEFT_HAND else -1
        return offset(resample(self.axis, start, end), side * self._lateral(self.out_lanes, lane))

    def kerb_offset(self, inbound):
        lanes = self.in_lanes if inbound else self.out_lanes
        return self.median / 2 + lanes * self.lane_width


ARMS = {arm["id"]: Arm(arm["id"], arm["name"], tuple(map(tuple, arm["axis"])), arm["lane_width"],
                       arm["median"], arm["in_lanes"], arm["out_lanes"], arm["stop"], arm["extent"])
        for arm in DATA["arms"]}
PHASES = tuple((phase["name"], tuple(phase["arms"]), phase["green"]) for phase in DATA["phases"])


def turn_targets():
    """For each inbound arm, the outbound arm reached by each turn (by real road angles)."""
    targets = {}
    canonical = {"straight": 0.0, "left": 1.5708, "right": -1.5708}
    for a in ARMS.values():
        incoming = (-a.outward[0], -a.outward[1])
        options = {}
        for b in ARMS.values():
            if b.id == a.id:
                continue
            angle = signed_angle(incoming, b.outward)
            turn = "straight" if abs(angle) < 0.7 else "left" if angle > 0 else "right"
            if turn not in options or abs(angle - canonical[turn]) < abs(options[turn][1] - canonical[turn]):
                options[turn] = (b.id, angle)
        targets[a.id] = {turn: target for turn, (target, _) in options.items()}
    return targets


TURNS = turn_targets()


def lane_turns(arm, lane):
    """Turns permitted from an inbound lane: near turn from the kerb lane, far turn from the median lane."""
    lanes = ARMS[arm].in_lanes
    allowed = {"straight"}
    if lane == 0:
        allowed.add(NEAR_TURN)
    if lane == lanes - 1:
        allowed.add(FAR_TURN)
    return sorted(turn for turn in allowed if turn in TURNS[arm])
