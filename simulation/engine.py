from collections import deque
from dataclasses import asdict
import math
import random
import uuid

from simulation.config import Config
from simulation.demand import rates
from simulation.intersection import COMFORT_BRAKING, Intersection, horizon, to_line
from simulation.junction import FAR_TURN, LEFT_HAND, NEAR_TURN, lane_turns
from simulation.lane import APPROACHES, LANES
from simulation.routing import route_for
from simulation.traffic_metrics import calculate
from simulation.traffic_signal import TrafficSignal
from simulation.vehicle import (GAP_FACTOR, HEADWAY_FACTOR, PCU, SPEED_FACTOR, TYPE_SHARE, TYPES, Vehicle,
                                idm_acceleration)

# Distance past the stop line after which same-lane turning/straight paths have diverged.
DIVERGE = 8.0
# Arrivals that cannot enter yet wait at the network edge (per arm) before counting as blocked.
EDGE_QUEUE = 6
ENTRY_CLEARANCE = 5.25


class Engine:
    def __init__(self, config=None, session_id=None):
        self.config = config or Config()
        self.session_id = session_id or str(uuid.uuid4())
        self.sequence = 0
        self.mode = "stopped"
        self.history = deque(maxlen=1200)
        self.events = deque(maxlen=200)
        self._reset()

    def _reset(self):
        self.timestamp = 0.0
        self.run_seed = self.config.seed
        self.rng = random.Random(self.run_seed)
        self.signal, self.intersection = TrafficSignal(), Intersection()
        self.vehicles = {}
        self.serial = 0
        self.completed = self.completed_wait = self.blocked = 0
        self.completed_pcu = 0.0
        self.pending = {arm: deque() for arm in APPROACHES}
        self.history.clear()
        self.next_history = 0.0
        for lane in LANES:
            previous = None
            for i in range(self.config.initial_queue):
                vehicle = self._spawn(lane)
                vehicle.s = vehicle.route.stop - 7
                if previous:
                    vehicle.s = previous.s-(previous.length+vehicle.length)/2-self.config.min_gap-1
                previous = vehicle
        self._record()

    def _turn_weights(self):
        c = self.config
        return {NEAR_TURN: c.left_ratio if NEAR_TURN == "left" else c.right_ratio,
                FAR_TURN: c.right_ratio if FAR_TURN == "right" else c.left_ratio,
                "straight": 1 - c.left_ratio - c.right_ratio}

    def _spawn(self, lane, s=0, turn=None, kind=None):
        self.serial += 1
        if turn is None:
            allowed = lane_turns(lane.approach, lane.index)
            weights = self._turn_weights()
            turn = self.rng.choices(allowed, weights=[weights[t] + 1e-9 for t in allowed])[0]
        if kind is None:
            kind = self.rng.choices(tuple(TYPE_SHARE), weights=tuple(TYPE_SHARE.values()))[0]
        factor = min(1.15, max(0.85, self.rng.gauss(1, 0.07))) * SPEED_FACTOR[kind]
        vehicle = Vehicle(f"veh_{self.serial:06d}", kind, route_for(lane.approach, lane.index, turn), s=s,
                          driver_factor=factor)
        if kind == "motorcycle":
            # Riders keep to the side of their turn (sub +1 = left half), otherwise take the
            # half-lane strip with more room behind the last vehicle in it.
            kerb = 1 if LEFT_HAND else -1
            strips = (kerb,) if turn == NEAR_TURN else (-kerb,) if turn == FAR_TURN else (-1, 1)
            vehicle.sub = max(strips, key=lambda sub: min(
                (v.s - v.length / 2 for v in self.vehicles.values()
                 if v.lane_id == vehicle.lane_id and (v.sub == 0 or v.sub == sub)), default=math.inf))
        self.vehicles[vehicle.id] = vehicle
        return vehicle

    @property
    def hour(self):
        return (self.config.start_hour + self.timestamp / 3600) % 24

    def command(self, action, parameters=None):
        if action == "parameters":
            self.config = self.config.updated(parameters)
        elif action in {"start", "stop"}:
            self.mode = "running" if action == "start" else "stopped"
        elif action == "pause" and self.mode == "running":
            self.mode = "paused"
        elif action == "resume" and self.mode == "paused":
            self.mode = "running"
        elif action == "reset":
            self._reset()
            self.mode = "stopped"
        else:
            raise ValueError(f"Invalid action/transition: {action} from {self.mode}")
        self.sequence += 1
        self.events.append({"sequence": self.sequence, "timestamp": self.timestamp,
                            "action": action, "parameters": parameters})
        return self.snapshot()

    def _leader_index(self):
        """Possible leaders, grouped by incoming lane and by occupied receiving lane, with their
        creation order. Lets each vehicle scan its own lane instead of the whole population."""
        by_lane, by_exit = {}, {}
        for order, vehicle in enumerate(self.vehicles.values()):
            by_lane.setdefault(vehicle.lane_id, []).append((order, vehicle))
            if vehicle.s >= vehicle.route.exit_start:
                by_exit.setdefault((vehicle.route.destination, vehicle.route.exit_lane), []).append((order, vehicle))
        return by_lane, by_exit

    def _leader(self, vehicle, index=None):
        by_lane, by_exit = index or self._leader_index()
        closest, leader_speed, leader_order = math.inf, 0, None
        candidates = (by_lane.get(vehicle.lane_id, []) +
                      by_exit.get((vehicle.route.destination, vehicle.route.exit_lane), []))
        for order, other in candidates:
            if other is vehicle:
                continue
            projected = None
            # Same route anywhere, or same incoming lane until the paths diverge in the box.
            if not vehicle.shares_strip(other):
                continue  # Two-wheelers in the other half of the lane ride alongside.
            if other.route is vehicle.route or (other.lane_id == vehicle.lane_id and
                                                other.s - other.length / 2 < other.route.stop + DIVERGE):
                projected = other.s
            elif (other.route.destination == vehicle.route.destination and
                  other.route.exit_lane == vehicle.route.exit_lane and other.s >= other.route.exit_start):
                projected = vehicle.route.exit_start + other.s - other.route.exit_start
            if projected is not None and projected > vehicle.s:
                gap = projected - vehicle.s - (other.length + vehicle.length) / 2
                # Equal gaps go to the earliest-created vehicle, as in a full population scan.
                if gap < closest or (gap == closest and order < leader_order):
                    closest, leader_speed, leader_order = gap, other.speed, order
        return closest, leader_speed

    def step(self):
        if self.mode != "running":
            return
        c, dt = self.config, self.config.timestep
        self.signal.step(dt, c)
        self.intersection.admit(self.vehicles, self.signal, c)
        updates = []
        index = self._leader_index()
        for vehicle in sorted(self.vehicles.values(), key=lambda v: v.id):
            gap, leader_speed = self._gap(vehicle, index)
            accel = self._acceleration(vehicle, vehicle.speed, gap, leader_speed)
            # Ballistic update; a vehicle that would reverse stops exactly within the step.
            new_speed = vehicle.speed + accel * dt
            if new_speed >= 0:
                advance = (vehicle.speed + new_speed) / 2 * dt
            else:
                advance, new_speed = vehicle.speed ** 2 / (-2 * accel), 0.0
            # Collision guard: never close below the standstill gap.
            minimum = c.min_gap * GAP_FACTOR[vehicle.kind]
            if advance > gap - minimum:
                advance = max(0, gap - minimum)
                new_speed = min(new_speed, leader_speed, 2 * advance / dt)
            updates.append((vehicle, advance, new_speed, (new_speed - vehicle.speed) / dt))
        # Synchronous old-state calculation avoids iteration-order movement effects.
        for vehicle, advance, speed, acceleration in updates:
            vehicle.s += advance
            vehicle.speed, vehicle.acceleration = speed, acceleration
            if speed < 0.5 and vehicle.s < vehicle.route.stop:
                vehicle.waiting_time += dt
            vehicle.state = "crossing" if vehicle.route.stop <= vehicle.s < vehicle.route.exit_start else (
                "exiting" if vehicle.s >= vehicle.route.exit_start else "queued" if speed < 0.5 else "approaching")
            if vehicle.s > vehicle.route.length + vehicle.length / 2:
                self.completed += 1
                self.completed_wait += vehicle.waiting_time
                self.completed_pcu += PCU[vehicle.kind]
                del self.vehicles[vehicle.id]
        self.intersection.release(self.vehicles)
        demand = rates(c, self.hour)
        weights = self._turn_weights()
        for arm in APPROACHES:
            # Poisson arrivals (random, memoryless) at the arm's current hourly demand.
            if self.rng.random() < demand[arm] * dt / 3600:
                kind = self.rng.choices(tuple(TYPE_SHARE), weights=tuple(TYPE_SHARE.values()))[0]
                turns = sorted({t for lane in LANES if lane.approach == arm for t in lane_turns(arm, lane.index)})
                turn = self.rng.choices(turns, weights=[weights[t] + 1e-9 for t in turns])[0]
                if len(self.pending[arm]) >= EDGE_QUEUE:
                    self.blocked += 1
                else:
                    self.pending[arm].append((kind, turn))
            if self.pending[arm] and len(self.vehicles) < c.max_vehicles:
                kind, turn = self.pending[arm][0]
                lane = self._entry_lane(arm, kind, turn)
                if lane is not None:
                    self._enter(lane, turn, kind)
                    self.pending[arm].popleft()
        self.timestamp += dt
        self.sequence += 1
        if self.timestamp + 1e-8 >= self.next_history:
            self._record()

    def _entry_lane(self, arm, kind, turn):
        """Drivers join the least-occupied lane serving their turn whose entrance has space."""
        clearance = ENTRY_CLEARANCE + self.config.min_gap
        options = []
        for lane in LANES:
            if lane.approach != arm or turn not in lane_turns(arm, lane.index):
                continue
            occupants = [v for v in self.vehicles.values() if v.lane_id == lane.id]
            near_entry = [v for v in occupants if v.s - v.length / 2 < clearance]
            # A two-wheeler fits if one half-lane strip at the entrance is free.
            if kind == "motorcycle":
                fits = any(all(v.sub not in (0, sub) for v in near_entry) for sub in (-1, 1))
            else:
                fits = not near_entry
            if fits:
                options.append((len(occupants), lane.index, lane))
        return min(options)[2] if options else None

    def _gap(self, vehicle, index=None):
        gap, leader_speed = self._leader(vehicle, index)
        # A virtual stopped leader represents the stop line/reservation gate. Facing a green, a
        # driver only brakes for it once close enough to have asked for (and been refused) entry.
        if not vehicle.admitted and not (self.signal.colors()[vehicle.route.approach] == "GREEN" and
                                         to_line(vehicle) > horizon(vehicle, self.config)):
            stop_gap = vehicle.route.stop - vehicle.length / 2 - 0.5 - vehicle.s
            if stop_gap < gap:
                gap, leader_speed = stop_gap, 0
        return gap, leader_speed

    def _acceleration(self, vehicle, speed, gap, leader_speed):
        return idm_acceleration(speed, self._desired_speed(vehicle), gap, leader_speed, TYPES[vehicle.kind][3],
                                minimum_gap=self.config.min_gap * GAP_FACTOR[vehicle.kind],
                                headway=self.config.time_headway * HEADWAY_FACTOR[vehicle.kind])

    def _desired_speed(self, vehicle):
        route, desired = vehicle.route, self.config.desired_speed * vehicle.driver_factor
        if route.turn != "straight" and vehicle.s < route.exit_start:
            # Decelerate comfortably ahead of the curve to its lateral-acceleration speed limit.
            ahead = max(0, route.stop - vehicle.s)
            desired = min(desired, math.sqrt(route.turn_speed ** 2 + 2 * 1.5 * ahead))
        return desired

    def _enter(self, lane, turn=None, kind=None):
        """Arrivals join at the fastest speed the car-following model accepts without harsh braking."""
        vehicle = self._spawn(lane, turn=turn, kind=kind)
        gap, leader_speed = self._gap(vehicle)
        low, high = 0.0, self._desired_speed(vehicle)
        for _ in range(20):
            mid = (low + high) / 2
            low, high = (mid, high) if self._acceleration(vehicle, mid, gap, leader_speed) >= -COMFORT_BRAKING else (low, mid)
        vehicle.speed = low

    def metrics(self):
        result = calculate(self.vehicles, self.completed, self.completed_wait, self.blocked,
                           self.timestamp, self.intersection)
        hour = self.hour
        result.update({"clock_hour": hour, "demand_vph": rates(self.config, hour),
                       "pcu_throughput_pch": self.completed_pcu * 3600 / max(1, self.timestamp),
                       "edge_queue": sum(len(queue) for queue in self.pending.values())})
        return result

    def _record(self):
        metrics = self.metrics()
        self.history.append({"timestamp": self.timestamp, "queue": metrics["queue_total"],
                             "mean_wait": metrics["mean_wait"], "completed": self.completed,
                             "mean_speed": metrics["mean_speed"]})
        self.next_history = self.timestamp + 0.5

    def snapshot(self):
        entities = {}
        for vehicle in self.vehicles.values():
            position, heading = vehicle.pose()
            entities[vehicle.id] = {"id": vehicle.id, "type": vehicle.kind, "lane": vehicle.lane_id,
                "position": position, "heading": heading, "speed": vehicle.speed,
                "acceleration": vehicle.acceleration, "desired_speed": self._desired_speed(vehicle),
                "length": vehicle.length, "turn": vehicle.route.turn, "destination": vehicle.route.destination,
                "route": vehicle.route.id, "progress": vehicle.s,
                "distance_to_stop": vehicle.route.stop - vehicle.s - vehicle.length / 2, "sub_lane": vehicle.sub,
                "waiting_time": vehicle.waiting_time, "state": vehicle.state, "admitted": vehicle.admitted}
        return {"schema_version": 1, "session_id": self.session_id, "sequence": self.sequence,
                "timestamp": self.timestamp, "mode": self.mode, "parameters": asdict(self.config),
                "signals": self.signal.snapshot(self.config), "vehicles": entities, "metrics": self.metrics()}
