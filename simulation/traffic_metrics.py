from simulation.lane import APPROACHES, STOP_DISTANCE


def calculate(vehicles, completed, completed_wait, blocked, timestamp, intersection):
    approaches = {}
    for approach in APPROACHES:
        queue = [v for v in vehicles.values() if v.route.approach == approach and
                 v.s < STOP_DISTANCE and v.speed < 0.5]
        approaches[approach] = {"queue_count": len(queue),
                                "queue_length_m": max((STOP_DISTANCE - v.s + v.length / 2 for v in queue), default=0),
                                "waiting_time": sum(v.waiting_time for v in queue)}
    active = list(vehicles.values())
    return {"approaches": approaches, "queue_total": sum(a["queue_count"] for a in approaches.values()),
            "active_vehicles": len(active), "completed": completed, "blocked_arrivals": blocked,
            "mean_speed": sum(v.speed for v in active) / max(1, len(active)),
            "mean_wait": (completed_wait + sum(v.waiting_time for v in active)) / max(1, len(active) + completed),
            "throughput_vph": completed * 3600 / max(1, timestamp), "reservation_owner": intersection.owner}
