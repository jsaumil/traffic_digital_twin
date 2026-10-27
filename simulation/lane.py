from dataclasses import dataclass

APPROACHES = ("N", "S", "E", "W")
OUTWARD = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
DEMAND_KEYS = {"N": "demand_north", "S": "demand_south", "E": "demand_east", "W": "demand_west"}
LANE_WIDTH = 3.2
ROAD_HALF_WIDTH = 6.4
EXTENT = 65.0
STOP_RADIUS = 11.0
STOP_DISTANCE = EXTENT - STOP_RADIUS


@dataclass(frozen=True)
class Lane:
    approach: str
    index: int

    @property
    def id(self):
        return f"{self.approach}_{self.index}"

    @property
    def direction(self):
        x, y = OUTWARD[self.approach]
        return -x, -y


LANES = tuple(Lane(approach, index) for approach in APPROACHES for index in range(2))
