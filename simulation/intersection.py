"""Conflict-zone reservations: compatible movements share the box, conflicting ones are exclusive.

A green signal is not an entry grant. A vehicle enters only once it holds a reservation that does
not conflict with any vehicle already committed to the box. Permissive far-side turns (right
turns under left-hand traffic) and free left turns additionally need an accepted gap.
"""
import math

from simulation.junction import NEAR_TURN
from simulation.routing import conflicts

COMFORT_BRAKING = 3.0  # Yellow stop/go decision deceleration, m/s^2.
CRITICAL_GAP = 4.5  # Permissive turn critical gap (HCM range 4.1-5.0 s).
CROSSING_TIME = 3.0  # Moving turner from stop line to clear of opposing lanes, s.
START_ACCELERATION = 2.0


def to_line(vehicle):
    return vehicle.route.stop - vehicle.length / 2 - vehicle.s


def time_to_line(vehicle):
    distance = max(0, to_line(vehicle))
    v = vehicle.speed
    return (math.sqrt(v * v + 2 * START_ACCELERATION * distance) - v) / START_ACCELERATION


def can_stop(vehicle, config):
    # A vehicle already pulled up to the line and moving off is committed.
    distance = to_line(vehicle)
    return distance > config.min_gap + 1 and vehicle.speed ** 2 / (2 * COMFORT_BRAKING) <= distance


def horizon(vehicle, config):
    """Distance from the line at which a driver claims a reservation, far enough that a driver
    facing a free green never brakes for the stop line."""
    return 7 + config.min_gap + vehicle.speed * config.time_headway + vehicle.speed ** 2 / 5


def free_turn(vehicle, config):
    return config.free_left and vehicle.route.turn == NEAR_TURN


class Intersection:
    def __init__(self):
        self.occupants = []

    @property
    def owner(self):
        return self.occupants[0] if self.occupants else None

    def release(self, vehicles):
        self.occupants = [vid for vid in self.occupants if vid in vehicles and
                          vehicles[vid].admitted and
                          vehicles[vid].s - vehicles[vid].length / 2 <= vehicles[vid].route.exit_start + 1]

    def _will_enter(self, vehicle, colors, config):
        color = colors[vehicle.route.approach]
        if color == "GREEN" or free_turn(vehicle, config):
            return True
        return (color == "YELLOW" and config.yellow_policy == "clear_if_unavoidable" and
                not can_stop(vehicle, config) and vehicle.speed > 1)

    def admit(self, vehicles, signal, config):
        colors = signal.colors()
        # Yellow/red onset: drivers who can still stop comfortably give up their reservation.
        for vehicle in vehicles.values():
            if (vehicle.admitted and colors[vehicle.route.approach] != "GREEN" and
                    not free_turn(vehicle, config) and can_stop(vehicle, config)):
                vehicle.admitted = False
        self.release(vehicles)
        waiting = [v for v in vehicles.values() if not v.admitted and v.s < v.route.stop]
        candidates = []
        for vehicle in waiting:
            distance = to_line(vehicle)
            eligible = self._will_enter(vehicle, colors, config)
            # Permissive "sneaker": already waiting at the line, clears on yellow.
            if (colors[vehicle.route.approach] == "YELLOW" and vehicle.route.permissive and
                    distance < config.min_gap + 1 and vehicle.waiting_time > 0):
                eligible = True
            if not eligible or distance > horizon(vehicle, config):
                continue
            # Only the first not-yet-admitted vehicle in a lane strip can claim; two-wheelers
            # in the other half of the lane may filter up beside it.
            if any(other.lane_id == vehicle.lane_id and other.s > vehicle.s and vehicle.shares_strip(other)
                   for other in waiting):
                continue
            # Avoid blocking the box if the destination's receiving lane is occupied.
            if any(other.route.destination == vehicle.route.destination and
                   other.route.exit_lane == vehicle.route.exit_lane and vehicle.shares_strip(other) and
                   other.s >= other.route.exit_start and
                   other.s - other.route.exit_start < (other.length + vehicle.length) / 2 + config.min_gap
                   for other in vehicles.values() if other.id != vehicle.id):
                continue
            candidates.append(vehicle)
        # Priority movements first, then longest wait, then stable ID tie breaking.
        candidates.sort(key=lambda v: (v.route.permissive or free_turn(v, config), -v.waiting_time, v.id))
        for vehicle in candidates:
            if any(conflicts(vehicle.route, vehicles[vid].route) for vid in self.occupants):
                continue
            if ((vehicle.route.permissive or (free_turn(vehicle, config) and colors[vehicle.route.approach] != "GREEN"))
                    and not self._gap_accepted(vehicle, waiting, colors, config)):
                continue
            vehicle.admitted = True
            self.occupants.append(vehicle.id)

    def _gap_accepted(self, vehicle, waiting, colors, config):
        # HCM critical gap is measured from a standing start at the line; a vehicle still
        # approaching must first reach the line, then cross at least as quickly.
        own = max(CRITICAL_GAP, time_to_line(vehicle) + CROSSING_TIME)
        return not any(other.route.approach != vehicle.route.approach and not other.route.permissive and
                       not free_turn(other, config) and conflicts(vehicle.route, other.route) and
                       self._will_enter(other, colors, config) and time_to_line(other) < own
                       for other in waiting)
