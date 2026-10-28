"""Authoritative fixed-time signal machine over the junction's phase plan; no renderer-owned timing."""
from simulation.junction import PHASES
from simulation.lane import APPROACHES

STAGES = tuple(stage for i, (name, _, _) in enumerate(PHASES) for stage in
               (f"{name}_GREEN", f"{name}_YELLOW", f"ALL_RED_TO_{PHASES[(i + 1) % len(PHASES)][0]}"))


def groups_for(stage):
    """Signal colour per approach implied by a stage name."""
    result = {approach: "RED" for approach in APPROACHES}
    index = STAGES.index(stage)
    if index % 3 < 2:
        for approach in PHASES[index // 3][1]:
            result[approach] = "GREEN" if index % 3 == 0 else "YELLOW"
    return result


class TrafficSignal:
    def __init__(self):
        self.index = 0
        self.elapsed = 0.0
        self.transitions = 0

    @property
    def stage(self):
        return STAGES[self.index]

    def duration(self, config):
        kind = self.index % 3
        if kind == 0:
            return getattr(config, PHASES[self.index // 3][2])
        return config.yellow_time if kind == 1 else config.all_red_time

    def step(self, dt, config):
        # A live duration reduction must NOT borrow time from a yellow/all-red stage
        # that has not actually occurred. Expire an overdue current stage at "now".
        if self.elapsed+1e-9 >= self.duration(config):
            self.elapsed=0.0
            self.index=(self.index+1)%len(STAGES)
            self.transitions+=1
        self.elapsed += dt
        while self.elapsed + 1e-9 >= self.duration(config):
            self.elapsed = max(0, self.elapsed - self.duration(config))
            self.index = (self.index + 1) % len(STAGES)
            self.transitions += 1

    def colors(self):
        return groups_for(self.stage)

    def cycle(self, config):
        saved, total = self.index, 0.0
        for self.index in range(len(STAGES)):
            total += self.duration(config)
        self.index = saved
        return total

    def snapshot(self, config):
        return {"stage": self.stage, "elapsed": self.elapsed, "cycle": self.cycle(config),
                "remaining": max(0, self.duration(config) - self.elapsed), "groups": self.colors()}
