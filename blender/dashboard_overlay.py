import bpy


def update(state, connected=True, error=""):
    metrics, signals = state["metrics"], state["signals"]
    labels = {
        "clock": f"{state['timestamp']:07.1f} s / {state['mode'].upper()}",
        "phase": f"{signals['stage'].replace('_',' ')} / {signals['remaining']:04.1f}s",
        "metrics": f"QUEUED {metrics['queue_total']:03d}    ACTIVE {metrics['active_vehicles']:03d}    PASSED {metrics['completed']:04d}",
        "connection": "LIVE / WEBSOCKET" if connected else "OFFLINE / RECONNECTING",
    }
    for approach, metric in metrics["approaches"].items():
        labels["queue."+approach] = f"{approach} / {metric['queue_count']:02d} QUEUED / {metric['queue_length_m']:04.1f}m"
    for key, value in labels.items():
        obj = bpy.data.objects.get("TR.text."+key)
        if obj and obj.data.body != value:
            obj.data.body = value
