"""Arc-length sampled lane-centre paths over the real junction geometry. XY metres, Z up."""
from bisect import bisect_right
from functools import lru_cache
import math

from simulation.geometry import add, left_normal, mul, signed_angle, sub, unit
from simulation.junction import ARMS, FAR_TURN, TURNS

LATERAL_ACCELERATION = 2.5  # Comfortable urban turning, m/s^2.
CONFLICT_DISTANCE = 3.0  # Centreline separation below which two box paths conflict.


def arc_controls(start, d0, end, d1):
    """Cubic Bezier control legs approximating a circular arc between two tangents."""
    theta = abs(signed_angle(d0, d1))
    chord = math.dist(start, end)
    denominator = d0[0] * d1[1] - d0[1] * d1[0]
    if theta < 0.05 or abs(denominator) < 1e-9:
        return chord / 3, chord / 3
    # Corner where the entry and exit tangent lines meet: start + t*d0 == end - u*d1.
    delta = sub(end, start)
    t = (delta[0] * d1[1] - delta[1] * d1[0]) / denominator
    u = (delta[0] * d0[1] - delta[1] * d0[0]) / denominator
    if t <= 0 or u <= 0:
        return chord / 3, chord / 3
    factor = 4 / 3 * math.tan(theta / 4) / math.tan(theta / 2)
    return t * factor, u * factor


class Route:
    def __init__(self, approach, lane, turn):
        self.approach, self.lane, self.turn = approach, lane, turn
        self.lane_id = f"{approach}_{lane}"
        arm = ARMS[approach]
        self.destination = TURNS[approach][turn]
        exit_arm = ARMS[self.destination]
        far = exit_arm.out_lanes - 1
        self.exit_lane = 0 if turn not in (FAR_TURN, "straight") else far if turn == FAR_TURN else min(lane, far)
        self.permissive = turn == FAR_TURN
        approach_points = arm.inbound(lane, arm.stop, arm.extent)
        exit_points = exit_arm.outbound(self.exit_lane, exit_arm.stop, exit_arm.extent)
        stop, end = approach_points[-1], exit_points[0]
        d0, d1 = unit(sub(stop, approach_points[-2])), unit(sub(exit_points[1], end))
        l0, l1 = arc_controls(stop, d0, end, d1)
        c1, c2 = add(stop, mul(d0, l0)), add(end, mul(d1, -l1))
        curve = []
        for i in range(1, 100):
            t, v = i / 100, 1 - i / 100
            curve.append(tuple(v**3 * stop[j] + 3*v*v*t*c1[j] + 3*v*t*t*c2[j] + t**3 * end[j] for j in range(2)))
        self.points = list(approach_points) + curve + list(exit_points)
        self.distance = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.distance.append(self.distance[-1] + math.dist(a, b))
        first_box, first_exit = len(approach_points) - 1, len(approach_points) + len(curve)
        self.stop = self.distance[first_box]
        self.exit_start = self.distance[first_exit]
        self.box_points = self.points[first_box:first_exit + 1]
        self.length = self.distance[-1]
        self.id = f"{approach}_{lane}_{turn}"
        self.radius = min(radius(*self.box_points[i:i+3]) for i in range(len(self.box_points) - 2))
        self.turn_speed = math.sqrt(LATERAL_ACCELERATION * self.radius)

    def pose(self, s, lateral=0.0):
        """Position `lateral` metres left of the path at arc length s, and heading (local +Y forward)."""
        if s <= 0 or s >= self.length:
            a, b = (self.points[0], self.points[1]) if s <= 0 else (self.points[-2], self.points[-1])
            direction = unit(sub(b, a))
            base = add(self.points[0] if s <= 0 else self.points[-1], mul(direction, s if s <= 0 else s - self.length))
        else:
            index = min(len(self.points) - 2, bisect_right(self.distance, s) - 1)
            a, b = self.points[index:index+2]
            t = (s - self.distance[index]) / max(1e-9, self.distance[index+1] - self.distance[index])
            base, direction = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), unit(sub(b, a))
        x, y = add(base, mul(left_normal(direction), lateral))
        return [x, y, 0.14], math.atan2(direction[1], direction[0]) - math.pi / 2


def radius(a, b, c):
    cross = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    return math.inf if cross < 1e-9 else math.dist(a, b) * math.dist(b, c) * math.dist(a, c) / (2 * cross)


@lru_cache(maxsize=4096)
def conflicts(a, b):
    """Whether two routes' conflict-zone paths cross or merge. Same-lane pairs follow instead."""
    if (a.approach, a.lane) == (b.approach, b.lane):
        return False
    return any(math.dist(p, q) < CONFLICT_DISTANCE for p in a.box_points[1:] for q in b.box_points[1:])


@lru_cache(maxsize=256)
def route_for(approach, lane, turn):
    return Route(approach, lane, turn)
