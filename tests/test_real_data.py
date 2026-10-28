import asyncio
import json
import math
from pathlib import Path
import sys
import pytest
from communication.live_traffic import MEAN_PCU,LiveTraffic,capacity,demand_from_speed,probe_point
from simulation.config import Config
from simulation.demand import HOURLY,profile_rate
from simulation.engine import Engine
from simulation.junction import ARMS,DATA

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import import_osm


def test_importer_reproduces_committed_junction_from_cached_osm():
    raw=json.loads((ROOT/'data/osm/navrangpura_raw.json').read_text())
    overrides=json.loads((ROOT/'data/osm/navrangpura_overrides.json').read_text());overrides.pop('_comment')
    built=import_osm.build(raw,DATA['center']['lat'],DATA['center']['lon'],DATA['name'],overrides)
    assert built==DATA


def test_osm_geometry_is_the_real_junction():
    # 120 Feet Ring Road runs NNE-SSW and Drive-in Road ESE-WNW; neither is a right-angle grid.
    bearings={arm['id']:arm['bearing'] for arm in DATA['arms']}
    assert 20<bearings['N']<40 and 185<bearings['S']<205 and 110<bearings['E']<130 and 295<bearings['W']<315
    assert {arm['name'] for arm in DATA['arms']}=={'120 Feet Ring Road','Drive-in Road'}
    assert DATA['driving_side']=='left' and len(DATA['buildings'])>50
    assert all(10<=arm.stop<=40 and arm.extent>=100 for arm in ARMS.values())


def test_demand_profile_matches_published_peak_share():
    for arm,values in HOURLY.items():
        assert sum(values)==pytest.approx(json.loads((ROOT/'data/demand/navrangpura.json').read_text())['daily_inbound'][arm])
        assert .08<=max(values)/sum(values)<=.11  # DPR peak-hour share 8.5-11%.
    assert profile_rate('N',10.5)==pytest.approx(max(HOURLY['N']))
    assert profile_rate('N',0)==pytest.approx((HOURLY['N'][23]+HOURLY['N'][0])/2)


def test_live_speed_to_saturation_demand():
    assert demand_from_speed(40,40,1000)==0  # At free-flow speed: no queueing delay.
    assert demand_from_speed(20,40,1000)*MEAN_PCU==pytest.approx(1000)  # Doubled travel time: x = 1.
    assert demand_from_speed(30,40,1000)<demand_from_speed(20,40,1000)<demand_from_speed(10,40,1000)
    assert demand_from_speed(1,40,1000)*MEAN_PCU==pytest.approx(1500)  # Capped at x = 1.5.


def test_capacity_follows_signal_plan_and_irc_saturation_flow():
    c=Config();cycle=Engine(c).signal.cycle(c)
    assert capacity(ARMS['N'],c,cycle)==pytest.approx(525*3*3.5*c.green_ns/cycle)


def test_probe_points_lie_on_inbound_carriageways_near_junction():
    for arm in ARMS.values():
        lat,lon=probe_point(arm)
        dy=(lat-DATA['center']['lat'])*110540;dx=(lon-DATA['center']['lon'])*111320*math.cos(math.radians(DATA['center']['lat']))
        assert 55<math.hypot(dx,dy)<70


def test_live_poll_applies_logged_parameter_command():
    class Service:
        def __init__(self):
            self.engine=Engine(Config(demand_mode='live'));self.commands=[]
        def command(self,message):
            self.commands.append(message);self.engine.command(message['action'],message['parameters'])
    async def fake(session,key,lat,lon):
        return {'currentSpeed':20,'freeFlowSpeed':40,'confidence':.9,'roadClosure':False}
    service=Service();live=LiveTraffic(service,key='test',fetch=fake)
    asyncio.run(live.poll_once(None))
    assert service.commands[0]['action']=='parameters' and live.status['message']=='live'
    expected=demand_from_speed(20,40,capacity(ARMS['N'],service.engine.config,service.engine.signal.cycle(service.engine.config)))
    assert service.engine.config.demand_north==round(expected)
    assert service.engine.config.desired_speed==pytest.approx(40/3.6,abs=.01)
    assert LiveTraffic(service,key='').status['enabled'] is False
