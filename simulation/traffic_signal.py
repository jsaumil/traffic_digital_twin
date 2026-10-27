"""Authoritative fixed-time NS/EW signal machine; no renderer-owned timing."""
from simulation.lane import APPROACHES

STAGES = ("NS_GREEN", "NS_YELLOW", "ALL_RED_TO_EW", "EW_GREEN", "EW_YELLOW", "ALL_RED_TO_NS")


class TrafficSignal:
    def __init__(self):
        self.index = 0
        self.elapsed = 0.0
        self.transitions = 0

    @property
    def stage(self):
        return STAGES[self.index]

    def duration(self, config):
        return (config.green_ns, config.yellow_time, config.all_red_time,
                config.green_ew, config.yellow_time, config.all_red_time)[self.index]

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
        result = {approach: "RED" for approach in APPROACHES}
        if self.index in (0, 1, 3, 4):
            pair = "NS" if self.index < 3 else "EW"
            for approach in pair:
                result[approach] = "GREEN" if self.index in (0, 3) else "YELLOW"
        return result

    def snapshot(self, config):
        return {"stage": self.stage, "elapsed": self.elapsed,
                "remaining": max(0, self.duration(config) - self.elapsed), "groups": self.colors()}
