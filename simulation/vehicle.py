from dataclasses import dataclass
import math

TYPES = {"car": (4.5, 1.85, 1.45, 2.2), "bus": (10.5, 2.5, 3.1, 1.1),
         "truck": (8.0, 2.4, 2.8, 1.2), "motorcycle": (2.2, 0.8, 1.2, 2.8)}
TYPE_SEQUENCE = ("car", "car", "motorcycle", "car", "bus", "car", "truck", "car")


def idm_acceleration(speed, desired_speed, gap=math.inf, leader_speed=0,
                     acceleration=2.2, braking=3.0, minimum_gap=2, headway=1.3):
    """Intelligent Driver Model, bounded by service acceleration/emergency braking."""
    desired_gap = minimum_gap + max(0, speed * headway + speed * (speed - leader_speed) /
                                   (2 * math.sqrt(acceleration * braking)))
    interaction = 0 if math.isinf(gap) else (desired_gap / max(0.05, gap)) ** 2
    return max(-8.0, min(acceleration, acceleration * (1 - (speed / desired_speed) ** 4 - interaction)))


@dataclass
class Vehicle:
    id: str
    kind: str
    route: object
    s: float = 0
    speed: float = 0
    acceleration: float = 0
    waiting_time: float = 0
    admitted: bool = False
    state: str = "approaching"

    @property
    def length(self):
        return TYPES[self.kind][0]

    @property
    def lane_id(self):
        return f"{self.route.approach}_{self.route.lane}"
