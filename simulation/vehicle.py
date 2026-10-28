from dataclasses import dataclass
import math

# length, width, height (m), maximum acceleration (m/s^2). "motorcycle" = two-wheeler (scooter/bike).
TYPES = {"car": (4.2, 1.75, 1.5, 2.2), "bus": (12.0, 2.6, 3.2, 1.0),
         "truck": (7.5, 2.3, 2.8, 1.1), "motorcycle": (1.9, 0.75, 1.3, 2.6),
         "auto": (3.2, 1.4, 1.75, 1.5)}
# Ahmedabad arterial fleet by vehicle count (two-wheelers dominate; ~70% city-wide).
TYPE_SHARE = {"motorcycle": 0.62, "car": 0.20, "auto": 0.12, "bus": 0.03, "truck": 0.03}
SPEED_FACTOR = {"car": 1.0, "motorcycle": 1.0, "auto": 0.8, "truck": 0.9, "bus": 0.85}
# Indian mixed traffic: two-wheelers accept much smaller gaps and headways than cars.
GAP_FACTOR = {"car": 1.0, "motorcycle": 0.5, "auto": 0.8, "truck": 1.2, "bus": 1.2}
HEADWAY_FACTOR = {"car": 1.0, "motorcycle": 0.6, "auto": 0.9, "truck": 1.2, "bus": 1.2}
# Passenger car units (car 1.0, two-wheeler 0.5, bus/truck 3.5; auto-rickshaw 1.0 assumed).
PCU = {"car": 1.0, "motorcycle": 0.5, "auto": 1.0, "truck": 3.5, "bus": 3.5}
WHEELBASE = {"car": 2.5, "bus": 6.5, "truck": 4.5, "motorcycle": 1.3, "auto": 2.0}
# Two-wheelers ride in half-lane strips (sub = -1 / +1), so two fit beside each other.
SUB_LANE_OFFSET = 0.85


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
    driver_factor: float = 1.0  # Individual desired-speed preference.
    sub: int = 0  # 0 = full lane width; -1/+1 = two-wheeler half-lane strip.

    @property
    def length(self):
        return TYPES[self.kind][0]

    @property
    def lane_id(self):
        return self.route.lane_id

    def shares_strip(self, other):
        return self.sub == 0 or other.sub == 0 or self.sub == other.sub

    def pose(self):
        """Rigid body whose front and rear axles both track the path, so long vehicles off-track
        inside a curve instead of swinging their tail into the neighbouring lane."""
        half, lateral = WHEELBASE[self.kind] / 2, self.sub * SUB_LANE_OFFSET
        (fx, fy, z), _ = self.route.pose(self.s + half, lateral)
        (rx, ry, _), _ = self.route.pose(self.s - half, lateral)
        return [(fx + rx) / 2, (fy + ry) / 2, z], math.atan2(fy - ry, fx - rx) - math.pi / 2
