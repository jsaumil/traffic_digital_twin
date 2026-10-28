"""Live demand from TomTom real-time speeds on each approach (optional; needs TOMTOM_API_KEY).

No open live vehicle counts exist for Ahmedabad. On a signalized approach the measured segment
speed mostly reflects signal delay, so the speed drop is read as a degree of saturation x by
inverting a travel-time function t/t0 = vf/v = 1 + ALPHA * x**BETA, and demand = x * capacity,
with capacity = IRC saturation flow (525 PCU/h per metre of approach width) * green / cycle of
the twin's current signal plan. This is an estimate, not a count.
"""
import asyncio
import json
import math
import os
import time
from urllib.parse import urlencode

from simulation.geometry import offset, point_at
from simulation.junction import ARMS, DATA, LEFT_HAND, PHASES
from simulation.lane import DEMAND_KEYS
from simulation.vehicle import PCU, TYPE_SHARE

URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/14/json"
ALPHA, BETA = 1.0, 2.0  # Urban signalized travel-time function (x = 1 doubles travel time).
MAX_SATURATION = 1.5
SATURATION_FLOW = 525.0  # PCU/h per metre of approach width (IRC).
PROBE_DISTANCE = 60.0  # Metres upstream of the junction centre where speed is sampled.
MEAN_PCU = sum(PCU[kind] * share for kind, share in TYPE_SHARE.items())


def probe_point(arm):
    """Latitude/longitude on the arm's inbound carriageway, PROBE_DISTANCE out."""
    side = -1 if LEFT_HAND else 1
    lateral = arm.median / 2 + arm.in_lanes * arm.lane_width / 2
    x, y = offset([point_at(arm.axis, PROBE_DISTANCE - 1), point_at(arm.axis, PROBE_DISTANCE)], side * lateral)[1]
    lat0, lon0 = DATA["center"]["lat"], DATA["center"]["lon"]
    return lat0 + y / 110540, lon0 + x / (111320 * math.cos(math.radians(lat0)))


def capacity(arm, config, cycle):
    """Approach capacity in PCU/h for the current signal plan."""
    green = next(getattr(config, key) for _, arms, key in PHASES if arm.id in arms)
    return SATURATION_FLOW * arm.in_lanes * arm.lane_width * green / cycle


def demand_from_speed(current, free, capacity_pcu):
    """Estimated arrival demand (vehicles/h) on an approach from speeds in km/h."""
    if free <= 0 or current <= 0:
        return capacity_pcu * MAX_SATURATION / MEAN_PCU
    saturation = min(MAX_SATURATION, (max(0.0, free / current - 1) / ALPHA) ** (1 / BETA))
    return saturation * capacity_pcu / MEAN_PCU


async def fetch_tomtom(session, key, lat, lon):
    params = urlencode({"point": f"{lat:.6f},{lon:.6f}", "unit": "KMPH", "key": key})
    async with session.get(f"{URL}?{params}", timeout=15) as response:
        if response.status != 200:
            raise ValueError(f"TomTom HTTP {response.status}")
        return (await response.json())["flowSegmentData"]


class LiveTraffic:
    def __init__(self, service, interval=120.0, key=None, fetch=fetch_tomtom):
        self.service, self.interval, self.fetch = service, interval, fetch
        self.key = key if key is not None else os.environ.get("TOMTOM_API_KEY", "")
        self.status = {"enabled": bool(self.key), "provider": "TomTom Traffic Flow",
                       "message": "waiting for demand_mode=live" if self.key else
                       "disabled: set TOMTOM_API_KEY to use live speeds", "arms": {}, "updated": None}

    async def poll_once(self, session):
        arms, parameters, free_speeds = {}, {}, []
        engine = self.service.engine
        cycle = engine.signal.cycle(engine.config)
        for arm in ARMS.values():
            lat, lon = probe_point(arm)
            data = await self.fetch(session, self.key, lat, lon)
            current, free = float(data["currentSpeed"]), float(data["freeFlowSpeed"])
            closed = bool(data.get("roadClosure"))
            demand = 0.0 if closed else min(4000.0, demand_from_speed(current, free, capacity(arm, engine.config, cycle)))
            arms[arm.id] = {"current_kmh": current, "free_flow_kmh": free, "closed": closed,
                            "confidence": data.get("confidence"), "demand_vph": round(demand)}
            parameters[DEMAND_KEYS[arm.id]] = round(demand)
            free_speeds.append(free)
        parameters["desired_speed"] = round(max(3.0, min(20.0, sum(free_speeds) / len(free_speeds) / 3.6)), 2)
        # Applied through the normal command path, so live inputs are logged and replayable.
        self.service.command({"type": "command", "request_id": "live", "action": "parameters",
                              "parameters": parameters})
        self.status.update(arms=arms, updated=time.time(), message="live")

    async def run(self):
        if not self.key:
            return
        import aiohttp
        async with aiohttp.ClientSession(headers={"User-Agent": "traffic-digital-twin/1.0"}) as session:
            while True:
                if self.service.engine.config.demand_mode == "live":
                    try:
                        await self.poll_once(session)
                    except (OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
                        self.status["message"] = f"error: {exc}"
                    await asyncio.sleep(self.interval)
                else:
                    self.status["message"] = "waiting for demand_mode=live"
                    await asyncio.sleep(2)
