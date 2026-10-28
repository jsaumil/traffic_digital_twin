"""Time-of-day arrival demand for the real junction (vehicles/hour per inbound arm)."""
import json
import os
from pathlib import Path

from simulation.lane import APPROACHES, DEMAND_KEYS

ROOT = Path(__file__).resolve().parents[1]
PATH = Path(os.environ.get("TRAFFIC_DEMAND", ROOT / "data/demand/navrangpura.json"))
PROFILE = json.loads(PATH.read_text())


def _hourly(arm):
    if PROFILE.get("hourly_inbound"):
        return PROFILE["hourly_inbound"][arm]
    share = PROFILE["hourly_share"]
    return [PROFILE["daily_inbound"][arm] * value / sum(share) for value in share]


HOURLY = {arm: _hourly(arm) for arm in APPROACHES}


def profile_rate(arm, hour):
    """Hourly values apply at each hour's midpoint; linear in between, wrapping at midnight."""
    position = (hour - 0.5) % 24
    low = int(position)
    t = position - low
    values = HOURLY[arm]
    return values[low] * (1 - t) + values[(low + 1) % 24] * t


def rates(config, hour):
    if config.demand_mode == "profile":
        return {arm: profile_rate(arm, hour) for arm in APPROACHES}
    return {arm: getattr(config, DEMAND_KEYS[arm]) for arm in APPROACHES}
