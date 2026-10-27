from dataclasses import asdict, dataclass, replace
import math


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected a finite number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name}: number too large") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name}: expected a finite number")
    return value


@dataclass(frozen=True)
class Config:
    timestep: float = 0.1
    simulation_speed: float = 2.0
    green_ns: float = 25.0
    green_ew: float = 25.0
    yellow_time: float = 3.0
    all_red_time: float = 1.0
    min_green: float = 5.0
    max_green: float = 90.0
    demand_north: float = 300.0
    demand_south: float = 300.0
    demand_east: float = 300.0
    demand_west: float = 300.0
    desired_speed: float = 13.9
    min_gap: float = 2.0
    time_headway: float = 1.3
    left_ratio: float = 0.25
    right_ratio: float = 0.25
    yellow_policy: str = "stop"
    seed: int = 42
    max_vehicles: int = 160
    initial_queue: int = 3

    def __post_init__(self):
        limits = {"timestep": (0.02, 0.2), "simulation_speed": (0.1, 20),
                  "min_green": (3, 60), "max_green": (5, 120),
                  "green_ns": (3, 120), "green_ew": (3, 120),
                  "yellow_time": (2, 6), "all_red_time": (0.5, 5),
                  "desired_speed": (3, 20), "min_gap": (1, 5), "time_headway": (0.8, 3),
                  "left_ratio": (0, 0.5), "right_ratio": (0, 0.5)}
        limits.update({f"demand_{name}": (0, 1800) for name in ("north", "south", "east", "west")})
        for key, (low, high) in limits.items():
            if not low <= number(getattr(self, key), key) <= high:
                raise ValueError(f"{key}: allowed range {low}..{high}")
        if not self.min_green <= self.green_ns <= self.max_green or not self.min_green <= self.green_ew <= self.max_green:
            raise ValueError("Both green times must fall between min_green and max_green")
        if self.left_ratio + self.right_ratio > 0.9:
            raise ValueError("left_ratio + right_ratio must be <= 0.9")
        if not isinstance(self.yellow_policy,str) or self.yellow_policy not in {"stop", "clear_if_unavoidable"}:
            raise ValueError("yellow_policy: use stop or clear_if_unavoidable")
        for key, low, high in (("seed", 0, 1000000), ("max_vehicles", 24, 200), ("initial_queue", 0, 4)):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key}: integer {low}..{high} required")
        if self.initial_queue*8 > self.max_vehicles:
            raise ValueError("Initial queues exceed max_vehicles")

    def updated(self, changes):
        if not isinstance(changes, dict) or not changes or changes.keys() - asdict(self).keys():
            raise ValueError("parameters: expected non-empty object of known configuration keys")
        # Reproducibility/population settings are reset-only, not instantaneous teleports.
        return replace(self, **changes)
