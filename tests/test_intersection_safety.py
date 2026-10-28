import itertools
import math
import pytest
from simulation.config import Config
from simulation.engine import Engine
from simulation.junction import ARMS, FAR_TURN, NEAR_TURN
from simulation.lane import LANES
from simulation.routing import conflicts,route_for
from simulation.traffic_signal import STAGES
from simulation.vehicle import TYPES


def overlaps(a,b):
    pa,ha=a.pose();pb,hb=b.pose()
    delta=(pb[0]-pa[0],pb[1]-pa[1])
    if math.hypot(*delta)>(a.length+b.length)/2+3:return False
    axes_a=((math.cos(ha),math.sin(ha)),(-math.sin(ha),math.cos(ha)))
    axes_b=((math.cos(hb),math.sin(hb)),(-math.sin(hb),math.cos(hb)))
    dot=lambda x,y:x[0]*y[0]+x[1]*y[1]
    for axis in (*axes_a,*axes_b):
        ra=TYPES[a.kind][1]/2*abs(dot(axes_a[0],axis))+a.length/2*abs(dot(axes_a[1],axis))
        rb=TYPES[b.kind][1]/2*abs(dot(axes_b[0],axis))+b.length/2*abs(dot(axes_b[1],axis))
        if abs(dot(delta,axis))>=ra+rb-0.02:return False
    return True


def empty_config(**values):
    return Config(**{**dict(initial_queue=0,demand_mode='manual',demand_north=0,demand_south=0,demand_east=0,
                            demand_west=0),**values})


@pytest.mark.parametrize('hour',[10.5,15.0])
def test_multiple_cycles_conflict_reservations_and_physical_vehicle_boxes(hour):
    e=Engine(Config(green_ns=15,green_ew=12,start_hour=hour,max_vehicles=600));e.command('start')
    turns=set();shared=0
    for step in range(2400):
        e.step()
        inside=[v for v in e.vehicles.values() if v.s+v.length/2>v.route.stop and v.s-v.length/2<v.route.exit_start]
        for v in inside:
            assert v.admitted and v.id in e.intersection.occupants
            turns.add(v.route.turn)
        for a,b in itertools.combinations(inside,2):
            assert not conflicts(a.route,b.route),f'Conflicting movements share the box: {a.route.id} {b.route.id}'
        shared+=len(inside)>1
        for v in e.vehicles.values():
            if not v.admitted:assert v.s+v.length/2<v.route.stop
        if step%5==0:
            for a,b in itertools.combinations(e.vehicles.values(),2):
                assert not overlaps(a,b),f'Collision at {e.timestamp}: {a.id} {b.id}'
    assert e.completed>50 and turns=={'straight','left','right'} and shared>200


def test_red_arm_never_enters_except_free_left():
    e=Engine(Config(start_hour=10.5));e.command('start')
    for _ in range(3000):
        before={v.id:v.s+v.length/2 for v in e.vehicles.values()}
        e.step();colors=e.signal.colors()
        for v in e.vehicles.values():
            if before.get(v.id,1e9)<v.route.stop<=v.s+v.length/2 and colors[v.route.approach]=='RED':
                # Committed dilemma-zone vehicles finish within the all-red clearance.
                assert v.route.turn==NEAR_TURN or e.signal.stage.startswith('ALL_RED'),v.route.id


def test_yellow_never_admits_uncommitted_vehicle_with_stop_policy():
    e=Engine(Config(initial_queue=1,free_left=False,demand_mode='manual'));e.signal.index=1;e.signal.elapsed=0
    e.command('start');e.step()
    assert e.intersection.owner is None and not any(v.admitted for v in e.vehicles.values())


def test_committed_vehicle_clears_after_phase_change():
    e=Engine(Config(initial_queue=1,free_left=False,demand_mode='manual'));e.command('start');e.step()
    owner=e.vehicles[e.intersection.owner]
    while owner.s+owner.length/2<=owner.route.stop:e.step()
    owner=owner.id;e.signal.index=2
    for _ in range(20):
        e.step()
        assert owner in e.intersection.occupants
    assert e.vehicles[owner].admitted


def test_yellow_dilemma_policy_still_requires_reservation():
    e=Engine(empty_config(yellow_policy='clear_if_unavoidable'))
    vehicle=e._spawn(LANES[0],turn='straight',kind='car');vehicle.s=vehicle.route.stop-9;vehicle.speed=10
    e.signal.index=1;e.command('start');e.step()
    assert vehicle.admitted and vehicle.id in e.intersection.occupants


def test_population_cap_and_demand_backpressure():
    e=Engine(Config(initial_queue=0,max_vehicles=24,demand_mode='manual',demand_north=4000,demand_south=4000,
                    demand_east=4000,demand_west=4000))
    e.command('start')
    for _ in range(800):
        e.step();assert len(e.vehicles)<=24
    assert e.blocked>0


def test_permissive_right_turn_yields_to_opposing_through_traffic():
    # Split phasing never shows opposing greens together, so give N and S one shared phase here.
    e=Engine(empty_config(free_left=False))
    e.signal.colors=lambda:{'N':'GREEN','S':'GREEN','E':'RED','W':'RED'}
    north=ARMS['N'].in_lanes-1
    turner=e._spawn(next(l for l in LANES if l.approach=='N' and l.index==north),turn=FAR_TURN,kind='car')
    turner.s=turner.route.stop-3
    through=e._spawn(next(l for l in LANES if l.approach=='S' and l.index==0),turn='straight',kind='car')
    through.s=through.route.stop-40;through.speed=11
    assert conflicts(turner.route,through.route)
    e.command('start');e.step()
    assert through.admitted and not turner.admitted
    while through.id in e.vehicles and through.s<through.route.exit_start:
        e.step();assert not (turner.admitted and through.id in e.intersection.occupants)
    for _ in range(30):e.step()
    assert turner.admitted


def test_free_left_turn_proceeds_on_red():
    e=Engine(empty_config());e.signal.index=STAGES.index('S_GREEN')  # E is red.
    v=e._spawn(next(l for l in LANES if l.approach=='E' and l.index==0),turn=NEAR_TURN,kind='car')
    v.s=v.route.stop-6;e.command('start')
    for _ in range(80):e.step()
    assert e.signal.colors()['E']=='RED' and v.s>v.route.stop
    e=Engine(empty_config(free_left=False));e.signal.index=STAGES.index('S_GREEN')
    v=e._spawn(next(l for l in LANES if l.approach=='E' and l.index==0),turn=NEAR_TURN,kind='car')
    v.s=v.route.stop-6;e.command('start')
    for _ in range(80):e.step()
    assert v.s<v.route.stop


def test_same_arm_movements_share_the_box():
    e=Engine(empty_config())
    vehicles=[e._spawn(l,turn='straight',kind='car') for l in LANES if l.approach=='N']
    for v in vehicles:v.s=v.route.stop-5
    e.command('start');e.step()
    assert all(v.admitted for v in vehicles) and len(e.intersection.occupants)==len(vehicles)


def test_free_green_approach_does_not_brake_for_stop_line():
    e=Engine(empty_config())
    v=e._spawn(next(l for l in LANES if l.approach=='N'),turn='straight',kind='car');v.speed=e._desired_speed(v)
    e.command('start');lowest=v.speed
    while v.s<v.route.exit_start:e.step();lowest=min(lowest,v.speed)
    assert lowest>.95*e._desired_speed(v)


def test_turning_speed_respects_curve_radius():
    e=Engine(empty_config());e.signal.index=0
    v=e._spawn(next(l for l in LANES if l.approach=='N' and l.index==ARMS['N'].in_lanes-1),turn=FAR_TURN,kind='car')
    v.speed=e._desired_speed(v);e.command('start');peak=0
    while v.s<v.route.exit_start:
        e.step()
        if v.s>v.route.stop+2:peak=max(peak,v.speed**2/v.route.radius)
    assert peak<3.5
