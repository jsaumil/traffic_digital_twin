import math
import pytest
from simulation.config import Config
from simulation.engine import Engine
from simulation.lane import LANES,STOP_DISTANCE
from simulation.routing import route_for
from simulation.vehicle import TYPES,idm_acceleration


def empty_config(**values):
    return Config(**{**dict(initial_queue=0,demand_north=0,demand_south=0,demand_east=0,demand_west=0),**values})


def test_idm_free_flow_and_braking():
    assert idm_acceleration(0,13.9)==pytest.approx(2.2)
    assert idm_acceleration(13.9,13.9)==pytest.approx(0)
    assert idm_acceleration(10,13.9,gap=5,leader_speed=0)<0
    assert idm_acceleration(10,13.9,gap=.01,leader_speed=0)==-8


def test_vehicle_stops_at_red_then_releases():
    e=Engine(empty_config());v=e._spawn(LANES[4],STOP_DISTANCE-12)
    e.command('start')
    for _ in range(240):e.step()
    assert v.s+v.length/2<STOP_DISTANCE and v.speed<.5 and v.waiting_time>1
    for _ in range(220):e.step()
    assert v.s>STOP_DISTANCE and v.speed>0 and v.admitted


def test_safe_following_queue_and_no_reverse():
    e=Engine(empty_config());front=e._spawn(LANES[4],47);back=e._spawn(LANES[4],30)
    e.command('start')
    for _ in range(220):
        previous=back.s;e.step()
        assert back.s>=previous and back.speed>=0
        assert front.s-back.s-(front.length+back.length)/2>=e.config.min_gap-1e-7


@pytest.mark.parametrize('approach',['N','S','E','W'])
@pytest.mark.parametrize('lane,turn',[(0,'straight'),(0,'left'),(1,'straight'),(1,'right')])
def test_routes_are_continuous_and_terminate_in_correct_outbound_lane(approach,lane,turn):
    r=route_for(approach,lane,turn)
    assert r.distance[1]==pytest.approx(STOP_DISTANCE)
    before,_=r.pose(STOP_DISTANCE-1e-4);after,_=r.pose(STOP_DISTANCE+1e-4)
    assert math.dist(before,after)<.001
    before,_=r.pose(r.exit_start-1e-4);after,_=r.pose(r.exit_start+1e-4)
    assert math.dist(before,after)<.001
    assert all(b>a for a,b in zip(r.distance,r.distance[1:]))
    assert r.length>100 and all(math.isfinite(x) for x in r.pose(60)[0])


def test_departure_after_rear_leaves_area():
    e=Engine(empty_config());v=e._spawn(LANES[0]);v.s=v.route.length+v.length/2-.05;v.speed=10;v.admitted=True
    e.command('start');e.step()
    assert v.id not in e.vehicles and e.completed==1


def test_arrival_demand_changes_population_and_types():
    e=Engine(empty_config());e.command('start')
    for _ in range(100):e.step()
    assert not e.vehicles
    e.command('parameters',{key:1800 for key in ('demand_north','demand_south','demand_east','demand_west')})
    for _ in range(41):e.step()
    assert e.serial==8 and {v.kind for v in e.vehicles.values()}==set(TYPES)


def test_reproducibility_for_identical_config_and_command_steps():
    a,b=Engine(session_id='same'),Engine(session_id='same')
    for e in (a,b):
        e.command('start')
        for _ in range(350):e.step()
        e.command('parameters',{'green_ns':8,'desired_speed':10})
        for _ in range(120):e.step()
    assert a.snapshot()==b.snapshot()


def test_seed_change_is_latched_until_reset():
    e=Engine(empty_config(seed=42));e.command('parameters',{'seed':43})
    old=e._spawn(LANES[0])
    reference=Engine(empty_config(seed=42))._spawn(LANES[0])
    assert (old.kind,old.route.id)==(reference.kind,reference.route.id)
    e.command('reset');new=e._spawn(LANES[0])
    reference=Engine(empty_config(seed=43))._spawn(LANES[0])
    assert (new.kind,new.route.id)==(reference.kind,reference.route.id)
    assert old.kind!=new.kind
