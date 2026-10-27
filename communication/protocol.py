import json
import re
from simulation.config import Config, number
from simulation.lane import APPROACHES
from simulation.traffic_signal import STAGES
from simulation.vehicle import TYPES

MAX_BYTES = 512 * 1024


def loads(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("Message exceeds 512 KiB")
    def reject(value):
        raise ValueError(f"Non-finite number: {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate key: {key}")
            result[key] = value
        return result
    try:
        data = json.loads(raw, parse_constant=reject, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def dumps(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def validate_state(state):
    if not isinstance(state, dict) or type(state.get("schema_version")) is not int or state["schema_version"] != 1:
        raise ValueError("Unsupported schema")
    if not isinstance(state.get("session_id"), str) or not 1 <= len(state["session_id"]) <= 128:
        raise ValueError("Invalid session")
    if type(state.get("sequence")) is not int or state["sequence"] < 0:
        raise ValueError("Invalid sequence")
    if number(state.get("timestamp"), "timestamp") < 0 or state.get("mode") not in {"running", "paused", "stopped"}:
        raise ValueError("Invalid time/mode")
    try:
        if set(state["parameters"]) != set(Config.__dataclass_fields__):
            raise ValueError("Incomplete configuration")
        Config(**state["parameters"])
        signals = state["signals"]
        if signals["stage"] not in STAGES or set(signals["groups"]) != set(APPROACHES):
            raise ValueError("Invalid signals")
        expected = {a: "RED" for a in APPROACHES}
        if signals["stage"][:2] in {"NS", "EW"}:
            color = signals["stage"].split("_")[1]
            for a in signals["stage"][:2]:
                expected[a] = color
        if signals["groups"] != expected:
            raise ValueError("Signal groups contradict authoritative phase")
        for key in ("elapsed", "remaining"):
            if not 0 <= number(signals[key], key) <= 100000:
                raise ValueError("Invalid signal timer")
        vehicles = state["vehicles"]
        if not isinstance(vehicles, dict) or len(vehicles) > 200:
            raise ValueError("Too many vehicles")
        for entity_id, v in vehicles.items():
            if not re.fullmatch(r"veh_\d{6,9}", entity_id) or v["id"] != entity_id or v["type"] not in TYPES:
                raise ValueError("Invalid vehicle identity/type")
            if (v["lane"] not in {f"{a}_{i}" for a in APPROACHES for i in range(2)}
                    or v["turn"] not in {"left", "right", "straight"}
                    or v["destination"] not in APPROACHES or type(v["admitted"]) is not bool):
                raise ValueError("Invalid lane/route")
            if (v["state"] not in {"approaching","queued","crossing","exiting"}
                    or v["route"] != v["lane"]+"_"+v["turn"]
                    or not 0<number(v["desired_speed"],"desired_speed")<=30):
                raise ValueError("Invalid vehicle state/desired speed")
            if not isinstance(v["position"], list) or len(v["position"]) != 3:
                raise ValueError("Invalid position")
            for coordinate in v["position"]:
                if abs(number(coordinate, "position")) > 1000:
                    raise ValueError("Position outside scene bounds")
            for key in ("heading", "speed", "acceleration", "length", "progress", "distance_to_stop", "waiting_time"):
                if abs(number(v[key], key)) > 100000:
                    raise ValueError(f"Invalid {key}")
            if v["speed"] < 0 or v["length"] <= 0 or v["waiting_time"] < 0:
                raise ValueError("Invalid vehicle sensor")
        metrics = state["metrics"]
        for key in ("queue_total", "active_vehicles", "completed", "mean_speed", "mean_wait", "throughput_vph"):
            if number(metrics[key], key) < 0:
                raise ValueError("Invalid metrics")
        if set(metrics["approaches"]) != set(APPROACHES):
            raise ValueError("Invalid approach metrics")
        for metric in metrics["approaches"].values():
            for key in ("queue_count", "queue_length_m", "waiting_time"):
                if number(metric[key], key) < 0:
                    raise ValueError("Invalid queue metric")
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Incomplete state: {exc}") from exc
    return state


class StateOrder:
    def __init__(self):
        self.session = None
        self.sequence = -1
        self.retired = set()

    def accept(self, state):
        validate_state(state)
        session, sequence = state["session_id"], state["sequence"]
        if session in self.retired or (session == self.session and sequence <= self.sequence):
            return False
        if self.session and session != self.session:
            self.retired.add(self.session)
            if len(self.retired) > 64:
                self.retired = {self.session}
        self.session, self.sequence = session, sequence
        return True
