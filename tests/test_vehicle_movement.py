import math
import pytest
from simulation.config import Config
from simulation.engine import Engine
from simulation.junction import ARMS, TURNS, lane_turns
from simulation.lane import LANES
from simulation.routing import route_for
from simulation.vehicle import TYPES,idm_acceleration


def empty_config(**values):
    return Config(**{**dict(initial_queue=0,demand_mode='manual',demand_north=0,demand_south=0,demand_east=0,
                            demand_west=0),**values})


def lane(arm,index):
    return next(l for l in LANES if l.approach==arm and l.index==index)


def test_idm_free_flow_and_braking():
    assert idm_acceleration(0,13.9)==pytest.approx(2.2)
    assert idm_acceleration(13.9,13.9)==pytest.approx(0)
    assert idm_acceleration(10,13.9,gap=5,leader_speed=0)<0
    assert idm_acceleration(10,13.9,gap=.01,leader_speed=0)==-8


def test_vehicle_stops_at_red_then_releases():
    e=Engine(empty_config(free_left=False));v=e._spawn(lane('E',1),turn='straight',kind='car')
    v.s=v.route.stop-12;e.command('start')
    for _ in range(300):e.step()
    assert e.signal.colors()['E']=='RED' and v.s+v.length/2<v.route.stop and v.speed<.5 and v.waiting_time>1
    while e.signal.colors()['E']!='GREEN':e.step()
    for _ in range(100):e.step()
    assert v.s>v.route.stop and v.speed>0 and v.admitted


def test_safe_following_queue_and_no_reverse():
    e=Engine(empty_config());front=e._spawn(lane('E',1),turn='straight',kind='car')
    back=e._spawn(lane('E',1),turn='straight',kind='car');front.s=front.route.stop-6;back.s=front.s-20
    e.command('start')
    for _ in range(220):
        previous=back.s;e.step()
        assert back.s>=previous and back.speed>=0
        assert front.s-back.s-(front.length+back.length)/2>=e.config.min_gap-1e-7


def test_two_wheelers_filter_beside_each_other():
    e=Engine(empty_config());a=e._spawn(lane('E',1),turn='straight',kind='motorcycle')
    b=e._spawn(lane('E',1),turn='straight',kind='motorcycle')
    assert {a.sub,b.sub}=={-1,1}
    a.s=b.s=a.route.stop-3
    assert e._leader(b)[0]==math.inf  # Side by side: neither is the other's leader.


@pytest.mark.parametrize('arm,index,turn',[(l.approach,l.index,t) for l in LANES for t in lane_turns(l.approach,l.index)])
def test_routes_are_continuous_and_terminate_in_correct_outbound_lane(arm,index,turn):
    r=route_for(arm,index,turn)
    assert r.destination==TURNS[arm][turn] and 0<=r.exit_lane<ARMS[r.destination].out_lanes
    for s in (r.stop,r.exit_start):
        before,_=r.pose(s-1e-4);after,_=r.pose(s+1e-4)
        assert math.dist(before,after)<.001
    assert all(b>a for a,b in zip(r.distance,r.distance[1:]))
    assert r.length>200 and all(math.isfinite(x) for x in r.pose(60)[0])
    end,_=r.pose(r.length);assert math.hypot(end[0],end[1])>100


def test_left_hand_traffic_keeps_left():
    # Driving inbound, the kerb lane must be on the driver's left.
    for arm in ARMS.values():
        r=route_for(arm.id,0,'straight');(x0,y0,_),_=r.pose(10);(x1,y1,_),_=r.pose(11)
        centre=arm.axis[len(arm.axis)//2];kerb=(x1-x0)*(centre[1]-y0)-(y1-y0)*(centre[0]-x0)
        assert kerb<0,f'{arm.id} kerb lane is not left of travel'


def test_departure_after_rear_leaves_area():
    e=Engine(empty_config());v=e._spawn(LANES[0]);v.s=v.route.length+v.length/2-.05;v.speed=10;v.admitted=True
    e.command('start');e.step()
    assert v.id not in e.vehicles and e.completed==1


def test_arrival_demand_changes_population_and_types():
    e=Engine(empty_config());e.command('start')
    for _ in range(100):e.step()
    assert not e.vehicles
    e.command('parameters',{key:1800 for key in ('demand_north','demand_south','demand_east','demand_west')})
    for _ in range(1200):e.step()
    # 4 arms x 1800 veh/h over 120 s: 240 expected Poisson arrivals.
    assert 190<=e.serial+e.blocked+sum(map(len,e.pending.values()))<=290
    assert {v.kind for v in e.vehicles.values()}==set(TYPES)
    assert sum(v.kind=='motorcycle' for v in e.vehicles.values())>len(e.vehicles)/3


def test_time_of_day_profile_drives_demand():
    morning,night=Engine(Config(start_hour=10.5)),Engine(Config(start_hour=3.5))
    assert morning.metrics()['demand_vph']['N']>10*night.metrics()['demand_vph']['N']
    for e in (morning,night):
        e.command('start')
        for _ in range(1500):e.step()
    assert morning.serial>3*night.serial


def test_reproducibility_for_identical_config_and_command_steps():
    a,b=Engine(session_id='same'),Engine(session_id='same')
    for e in (a,b):
        e.command('start')
        for _ in range(350):e.step()
        e.command('parameters',{'green_ns':20,'desired_speed':10})
        for _ in range(120):e.step()
    assert a.snapshot()==b.snapshot()


def test_seed_change_is_latched_until_reset():
    e=Engine(empty_config(seed=42));e.command('parameters',{'seed':43})
    spawn=lambda engine:[(v.kind,v.route.id,v.driver_factor) for v in (engine._spawn(LANES[0]) for _ in range(6))]
    old=spawn(e);assert old==spawn(Engine(empty_config(seed=42)))
    e.command('reset');new=spawn(e);assert new==spawn(Engine(empty_config(seed=43)))
    assert old!=new
