"""Conservative exclusive intersection reservation; compatible green != entry grant."""
from simulation.lane import STOP_DISTANCE


class Intersection:
    def __init__(self):
        self.owner = None

    def release(self, vehicles):
        owner = vehicles.get(self.owner)
        if owner is None or owner.s - owner.length / 2 > owner.route.exit_start + 1:
            self.owner = None

    def admit(self, vehicles, signal, config):
        self.release(vehicles)
        if self.owner is not None:
            return
        colors = signal.colors()
        candidates = []
        for vehicle in vehicles.values():
            if vehicle.admitted or vehicle.s >= STOP_DISTANCE:
                continue
            distance = STOP_DISTANCE - vehicle.length / 2 - vehicle.s
            eligible = colors[vehicle.route.approach] == "GREEN"
            if colors[vehicle.route.approach] == "YELLOW" and config.yellow_policy == "clear_if_unavoidable":
                eligible = vehicle.speed ** 2 / 6 > distance and vehicle.speed > 1
            if not eligible or distance > 7:
                continue
            # Only the first vehicle in an incoming lane can claim the zone.
            if any(other.lane_id == vehicle.lane_id and other.s > vehicle.s and
                   other.s < STOP_DISTANCE for other in vehicles.values()):
                continue
            # Avoid blocking the box if the destination's receiving lane is occupied.
            if any(other.route.destination == vehicle.route.destination and
                   other.route.exit_lane == vehicle.route.exit_lane and
                   other.s >= other.route.exit_start and
                   other.s - other.route.exit_start < (other.length + vehicle.length) / 2 + config.min_gap
                   for other in vehicles.values() if other.id != vehicle.id):
                continue
            candidates.append(vehicle)
        if candidates:
            # Deterministic, longest-wait-first arbitration with stable ID tie breaking.
            winner = min(candidates, key=lambda v: (-v.waiting_time, v.id))
            self.owner = winner.id
            winner.admitted = True
