import pytest
from simulation.config import Config
from simulation.junction import PHASES
from simulation.traffic_signal import STAGES,TrafficSignal,groups_for
from simulation.engine import Engine


def test_split_phasing_gives_each_arm_its_own_green():
    assert [arms for _,arms,_ in PHASES]==[('N',),('E',),('S',),('W',)]  # Clockwise by real bearing.
    for stage in STAGES:
        assert sum(color!='RED' for color in groups_for(stage).values())<=1


def test_complete_signal_cycle_and_clearance():
    c=Config();signal=TrafficSignal();observed=[]
    steps=round(signal.cycle(c)/.1)
    assert signal.cycle(c)==pytest.approx(2*c.green_ns+2*c.green_ew+4*(c.yellow_time+c.all_red_time))
    for _ in range(steps):
        if not observed or observed[-1]!=signal.stage:observed.append(signal.stage)
        assert sum(color=='GREEN' for color in signal.colors().values())<=1
        signal.step(.1,c)
    assert observed==list(STAGES)
    assert signal.stage=='N_GREEN'
    assert signal.elapsed==pytest.approx(0,abs=1e-8)


def test_phase_exact_boundaries():
    s=TrafficSignal();c=Config()
    s.step(c.green_ns,c);assert s.stage=='N_YELLOW'
    s.step(c.yellow_time,c);assert s.stage=='ALL_RED_TO_E';assert set(s.colors().values())=={'RED'}
    s.step(c.all_red_time,c);assert s.stage=='E_GREEN' and s.colors()['E']=='GREEN'
    s.step(c.green_ew,c);assert s.stage=='E_YELLOW'


def test_live_shortening_preserves_full_yellow_and_clearance():
    signal=TrafficSignal();config=Config()
    signal.step(20,config)
    config=config.updated({'green_ns':5})
    signal.step(.1,config)
    assert signal.stage=='N_YELLOW' and signal.elapsed==pytest.approx(.1)
    for _ in range(28):signal.step(.1,config)
    assert signal.stage=='N_YELLOW'
    signal.step(.1,config);assert signal.stage=='ALL_RED_TO_E'
    for _ in range(19):signal.step(.1,config)
    assert signal.stage=='ALL_RED_TO_E'
    signal.step(.1,config);assert signal.stage=='E_GREEN'


def test_pause_and_reset_pause_signal_timers():
    e=Engine();e.command('start');e.step();e.command('pause')
    before=e.signal.snapshot(e.config)
    for _ in range(100):e.step()
    assert e.signal.snapshot(e.config)==before
    e.command('resume');e.step();assert e.signal.elapsed>before['elapsed']
    seq=e.sequence;e.command('reset')
    assert e.mode=='stopped' and e.timestamp==0 and e.signal.stage=='N_GREEN' and e.signal.elapsed==0
    assert e.sequence>seq


@pytest.mark.parametrize('changes',[{'green_ns':2},{'green_ew':100},{'yellow_time':0},
    {'all_red_time':0},{'timestep':float('nan')},{'demand_north':-1},{'desired_speed':True},
    {'simulation_speed':'2'},{'seed':1.5},{'yellow_policy':[]},{'initial_queue':4,'max_vehicles':24},
    {'left_ratio':.5,'right_ratio':.5},{'unknown':1},{'green_ns':10**400},{'demand_mode':'random'},
    {'start_hour':24},{'free_left':1},{'demand_east':4001}])
def test_invalid_settings_are_atomic(changes):
    e=Engine();old=e.config
    with pytest.raises(ValueError):e.command('parameters',changes)
    assert e.config==old and e.sequence==0


def test_live_green_change_affects_vehicle_release():
    zero=dict(demand_mode='manual',demand_north=0,demand_south=0,demand_east=0,demand_west=0,left_ratio=0,
              right_ratio=0,initial_queue=1)
    short,long=Engine(Config(**zero)),Engine(Config(**zero))
    short.command('parameters',{'green_ns':5,'green_ew':60})
    long.command('parameters',{'green_ns':60,'green_ew':5})
    pick=lambda e:next(v for v in e.vehicles.values() if v.route.approach=='E')
    short_vehicle,long_vehicle=pick(short),pick(long)
    for e in (short,long):
        e.command('start')
        for _ in range(250):e.step()
    assert short_vehicle.s>long_vehicle.s+5
    assert short.signal.stage=='E_GREEN' and long.signal.stage=='N_GREEN'
