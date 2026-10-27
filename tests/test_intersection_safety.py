import itertools
import math
from simulation.config import Config
from simulation.engine import Engine
from simulation.lane import STOP_DISTANCE
from simulation.lane import LANES
from simulation.vehicle import TYPES


def overlaps(a,b):
    pa,ha=a.route.pose(a.s);pb,hb=b.route.pose(b.s)
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


def test_multiple_cycles_conflict_reservations_and_physical_vehicle_boxes():
    e=Engine(Config(green_ns=8,green_ew=11,initial_queue=3));e.command('start')
    turns=set()
    for step in range(1800):
        e.step()
        inside=[v for v in e.vehicles.values() if v.s+v.length/2>STOP_DISTANCE and v.s-v.length/2<v.route.exit_start]
        assert len(inside)<=1
        if inside:
            assert inside[0].id==e.intersection.owner and inside[0].admitted
            turns.add(inside[0].route.turn)
        for v in e.vehicles.values():
            if not v.admitted:assert v.s+v.length/2<STOP_DISTANCE
        if step%10==0:
            for a,b in itertools.combinations(e.vehicles.values(),2):
                assert not overlaps(a,b),f'Collision at {e.timestamp}: {a.id} {b.id}'
    assert e.completed>10 and turns=={'straight','left','right'}


def test_yellow_never_admits_uncommitted_vehicle_with_stop_policy():
    e=Engine(Config(initial_queue=1));e.signal.index=1;e.signal.elapsed=0
    e.command('start');e.step()
    assert e.intersection.owner is None and not any(v.admitted for v in e.vehicles.values())


def test_committed_vehicle_clears_after_phase_change():
    e=Engine(Config(initial_queue=1));e.command('start');e.step()
    owner=e.intersection.owner;assert owner
    e.signal.index=2
    for _ in range(20):
        e.step()
        assert e.intersection.owner==owner
    assert e.vehicles[owner].admitted


def test_yellow_dilemma_policy_still_requires_reservation():
    e=Engine(Config(initial_queue=0,yellow_policy='clear_if_unavoidable'))
    vehicle=e._spawn(LANES[0],47);vehicle.speed=10
    e.signal.index=1;e.command('start');e.step()
    assert vehicle.admitted and e.intersection.owner==vehicle.id


def test_population_cap_and_demand_backpressure():
    e=Engine(Config(initial_queue=0,max_vehicles=24,demand_north=1800,demand_south=1800,demand_east=1800,demand_west=1800))
    e.command('start')
    for _ in range(800):
        e.step();assert len(e.vehicles)<=24
    assert e.blocked>0
