from dataclasses import dataclass

from simulation.junction import ARMS

APPROACHES = tuple(ARMS)
DEMAND_KEYS = {"N": "demand_north", "S": "demand_south", "E": "demand_east", "W": "demand_west"}


@dataclass(frozen=True)
class Lane:
    approach: str
    index: int

    @property
    def id(self):
        return f"{self.approach}_{self.index}"


LANES = tuple(Lane(arm.id, index) for arm in ARMS.values() for index in range(arm.in_lanes))
