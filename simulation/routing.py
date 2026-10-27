"""Arc-length sampled lane-center paths. XY metres, Z up, right-hand traffic."""
from bisect import bisect_right
from functools import lru_cache
import math

from simulation.lane import EXTENT, LANE_WIDTH, OUTWARD, STOP_DISTANCE, STOP_RADIUS


def add(a, b):
    return a[0] + b[0], a[1] + b[1]


def mul(a, n):
    return a[0] * n, a[1] * n


class Route:
    def __init__(self, approach, lane, turn):
        self.approach, self.lane, self.turn = approach, lane, turn
        outward = OUTWARD[approach]
        incoming = mul(outward, -1)
        right = (incoming[1], -incoming[0])
        offset = (lane + 0.5) * LANE_WIDTH
        start = add(mul(outward, EXTENT), mul(right, offset))
        stop = add(mul(outward, STOP_RADIUS), mul(right, offset))
        outgoing = incoming if turn == "straight" else ((-incoming[1], incoming[0]) if turn == "left" else (incoming[1], -incoming[0]))
        self.destination = next(key for key, value in OUTWARD.items() if value == outgoing)
        self.exit_lane = 0 if turn == "left" else 1 if turn == "right" else lane
        right_out = (outgoing[1], -outgoing[0])
        end = add(mul(outgoing, STOP_RADIUS), mul(right_out, (self.exit_lane + 0.5) * LANE_WIDTH))
        far = add(end, mul(outgoing, EXTENT - STOP_RADIUS))
        control = 12 if turn != "right" else 7
        c1, c2 = add(stop, mul(incoming, control)), add(end, mul(outgoing, -control))
        self.points = [start, stop]
        for i in range(1, 101):
            t, u = i / 100, 1 - i / 100
            self.points.append(tuple(u**3 * stop[j] + 3*u*u*t*c1[j] + 3*u*t*t*c2[j] + t**3*end[j] for j in range(2)))
        self.distance = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.distance.append(self.distance[-1] + math.dist(a, b))
        self.exit_start = self.distance[-1]
        self.points.append(far)
        self.distance.append(self.exit_start + math.dist(end, far))
        self.length = self.distance[-1]
        self.id = f"{approach}_{lane}_{turn}"

    def pose(self, s):
        if s > self.length:
            end=self.points[-1]
            direction=OUTWARD[self.destination]
            return [end[0]+direction[0]*(s-self.length),end[1]+direction[1]*(s-self.length),0.14], math.atan2(direction[1],direction[0])-math.pi/2
        s = max(0, min(s, self.length))
        index = min(len(self.points) - 2, max(0, bisect_right(self.distance, s) - 1))
        a, b = self.points[index:index+2]
        t = (s - self.distance[index]) / max(1e-9, self.distance[index+1] - self.distance[index])
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        # Vehicle geometry's forward axis is local +Y.
        return [x, y, 0.14], math.atan2(b[1] - a[1], b[0] - a[0]) - math.pi / 2


@lru_cache(maxsize=32)
def route_for(approach, lane, turn):
    return Route(approach, lane, turn)
