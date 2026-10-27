from collections import deque
from dataclasses import asdict
import math
import uuid

from simulation.config import Config
from simulation.intersection import Intersection
from simulation.lane import DEMAND_KEYS, LANES, STOP_DISTANCE
from simulation.routing import route_for
from simulation.traffic_metrics import calculate
from simulation.traffic_signal import TrafficSignal
from simulation.vehicle import TYPE_SEQUENCE, TYPES, Vehicle, idm_acceleration


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
        self.signal, self.intersection = TrafficSignal(), Intersection()
        self.vehicles = {}
        self.serial = 0
        self.completed = self.completed_wait = self.blocked = 0
        self.credits = {lane.id: 0.0 for lane in LANES}
        self.history.clear()
        self.next_history = 0.0
        for lane in LANES:
            previous = None
            for i in range(self.config.initial_queue):
                vehicle = self._spawn(lane, STOP_DISTANCE-7)
                if previous:
                    vehicle.s = previous.s-(previous.length+vehicle.length)/2-self.config.min_gap-1
                previous = vehicle
        self._record()

    def _spawn(self, lane, s=0):
        self.serial += 1
        key = (self.serial * 73 + self.run_seed * 17) % 1000 / 1000
        # Dedicated turn intentions: left+straight inner lane, right+straight outer lane.
        turn = ("left" if key < min(1, self.config.left_ratio * 2) else "straight") if lane.index == 0 else (
            "right" if key < min(1, self.config.right_ratio * 2) else "straight")
        vehicle = Vehicle(f"veh_{self.serial:06d}", TYPE_SEQUENCE[(self.serial + self.run_seed) % len(TYPE_SEQUENCE)],
                          route_for(lane.approach, lane.index, turn), s=s)
        self.vehicles[vehicle.id] = vehicle
        return vehicle

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

    def _leader(self, vehicle):
        closest, leader_speed = math.inf, 0
        for other in self.vehicles.values():
            if other.id == vehicle.id:
                continue
            projected = None
            if other.lane_id == vehicle.lane_id and other.s < STOP_DISTANCE:
                projected = other.s
            elif (other.route.destination == vehicle.route.destination and
                  other.route.exit_lane == vehicle.route.exit_lane and other.s >= other.route.exit_start):
                projected = vehicle.route.exit_start + other.s - other.route.exit_start
            if projected is not None and projected > vehicle.s:
                gap = projected - vehicle.s - (other.length + vehicle.length) / 2
                if gap < closest:
                    closest, leader_speed = gap, other.speed
        return closest, leader_speed

    def step(self):
        if self.mode != "running":
            return
        c, dt = self.config, self.config.timestep
        self.signal.step(dt, c)
        self.intersection.admit(self.vehicles, self.signal, c)
        updates = []
        for vehicle in sorted(self.vehicles.values(), key=lambda v: v.id):
            gap, leader_speed = self._leader(vehicle)
            # A virtual stopped leader represents the stop line/reservation gate.
            if not vehicle.admitted:
                stop_gap = STOP_DISTANCE - vehicle.length / 2 - 0.5 - vehicle.s
                if stop_gap < gap:
                    gap, leader_speed = stop_gap, 0
            desired = min(c.desired_speed, 6.0) if vehicle.route.turn != "straight" and STOP_DISTANCE - 6 < vehicle.s < vehicle.route.exit_start else c.desired_speed
            accel = idm_acceleration(vehicle.speed, desired, gap, leader_speed,
                                     TYPES[vehicle.kind][3], minimum_gap=c.min_gap, headway=c.time_headway)
            new_speed = max(0, vehicle.speed + accel * dt)
            advance = min(new_speed * dt, max(0, gap - c.min_gap))
            new_speed = min(new_speed, advance / dt)
            updates.append((vehicle, advance, new_speed, (new_speed - vehicle.speed) / dt))
        # Synchronous old-state calculation avoids iteration-order movement effects.
        for vehicle, advance, speed, acceleration in updates:
            vehicle.s += advance
            vehicle.speed, vehicle.acceleration = speed, acceleration
            if speed < 0.5 and vehicle.s < STOP_DISTANCE:
                vehicle.waiting_time += dt
            vehicle.state = "crossing" if STOP_DISTANCE <= vehicle.s < vehicle.route.exit_start else (
                "exiting" if vehicle.s >= vehicle.route.exit_start else "queued" if speed < 0.5 else "approaching")
            if vehicle.s > vehicle.route.length + vehicle.length / 2:
                self.completed += 1
                self.completed_wait += vehicle.waiting_time
                del self.vehicles[vehicle.id]
        self.intersection.release(self.vehicles)
        for lane in LANES:
            self.credits[lane.id] = min(2, self.credits[lane.id] + getattr(c, DEMAND_KEYS[lane.approach]) * dt / 7200)
            if self.credits[lane.id] >= 1:
                # Reserve enough entrance space for even the longest next vehicle.
                clear = not any(v.lane_id == lane.id and v.s-v.length/2 < 5.25+c.min_gap
                                for v in self.vehicles.values())
                if clear and len(self.vehicles) < c.max_vehicles:
                    self._spawn(lane)
                    self.credits[lane.id] -= 1
                elif self.credits[lane.id] >= 2:
                    self.blocked += 1
                    self.credits[lane.id] -= 1
        self.timestamp += dt
        self.sequence += 1
        if self.timestamp + 1e-8 >= self.next_history:
            self._record()

    def metrics(self):
        return calculate(self.vehicles, self.completed, self.completed_wait, self.blocked,
                         self.timestamp, self.intersection)

    def _record(self):
        metrics = self.metrics()
        self.history.append({"timestamp": self.timestamp, "queue": metrics["queue_total"],
                             "mean_wait": metrics["mean_wait"], "completed": self.completed,
                             "mean_speed": metrics["mean_speed"]})
        self.next_history = self.timestamp + 0.5

    def snapshot(self):
        entities = {}
        for vehicle in self.vehicles.values():
            position, heading = vehicle.route.pose(vehicle.s)
            entities[vehicle.id] = {"id": vehicle.id, "type": vehicle.kind, "lane": vehicle.lane_id,
                "position": position, "heading": heading, "speed": vehicle.speed,
                "acceleration": vehicle.acceleration, "desired_speed": self.config.desired_speed,
                "length": vehicle.length, "turn": vehicle.route.turn, "destination": vehicle.route.destination,
                "route": vehicle.route.id, "progress": vehicle.s,
                "distance_to_stop": STOP_DISTANCE - vehicle.s - vehicle.length / 2,
                "waiting_time": vehicle.waiting_time, "state": vehicle.state, "admitted": vehicle.admitted}
        return {"schema_version": 1, "session_id": self.session_id, "sequence": self.sequence,
                "timestamp": self.timestamp, "mode": self.mode, "parameters": asdict(self.config),
                "signals": self.signal.snapshot(self.config), "vehicles": entities, "metrics": self.metrics()}
