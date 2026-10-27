"""Network worker -> single latest state -> main-thread Blender rendering."""
import logging
import queue
import threading
import time
import bpy

from communication.client import WebSocketClient
from communication.protocol import StateOrder, validate_state
from blender import dashboard_overlay
from blender.scene_builder import SCENE_NAME, VEHICLES_COLLECTION
from blender.vehicle_renderer import VehicleRenderer
from blender.signal_renderer import SignalRenderer

LOG = logging.getLogger("traffic.blender")
_active = None


class Controller:
    def __init__(self, url):
        self.url = url
        self.halt = threading.Event()
        self.latest = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.socket = None
        self.error = "Connecting"
        self.received = 0
        self.ack = None
        self.order = StateOrder()
        self.last_state = None
        self.vehicle_renderer = VehicleRenderer(bpy.data.collections[VEHICLES_COLLECTION])
        self.signal_renderer = SignalRenderer()
        self.thread = threading.Thread(target=self.worker, name="traffic-ws", daemon=True)
        self.timer = self.tick

    def start(self):
        self.thread.start()
        bpy.app.timers.register(self.timer, first_interval=0.05)

    def stop(self):
        self.halt.set()
        with self.lock:
            socket = self.socket
        if socket:
            socket.close()
        if bpy.app.timers.is_registered(self.timer):
            bpy.app.timers.unregister(self.timer)
        self.thread.join(timeout=2.1)
        scene = bpy.data.scenes.get(SCENE_NAME)
        if scene:
            scene["traffic_connected"] = False
        if self.last_state:
            dashboard_overlay.update(self.last_state, False)

    def worker(self):
        backoff = 0.2
        while not self.halt.is_set():
            client = None
            try:
                client = WebSocketClient(self.url)
                with self.lock:
                    self.socket = client
                last_ack = 0
                while not self.halt.is_set():
                    message = client.receive()
                    if message.get("type") != "state":
                        continue
                    state = validate_state(message.get("state"))
                    try:
                        self.latest.get_nowait()
                    except queue.Empty:
                        pass
                    self.latest.put_nowait(state)
                    with self.lock:
                        self.error, self.received = "", time.monotonic()
                        ack = self.ack
                    if ack and ack["session_id"] == state["session_id"] and time.monotonic()-last_ack>0.5:
                        client.send(ack)
                        last_ack = time.monotonic()
                    backoff = 0.2
            except (OSError, ValueError, KeyError) as exc:
                with self.lock:
                    self.error = str(exc)
                if not self.halt.is_set():
                    LOG.warning("Traffic socket lost: %s; reconnecting", exc)
            finally:
                if client:
                    client.close()
                with self.lock:
                    self.socket = None
            self.halt.wait(backoff)
            backoff = min(2, backoff*2)

    def tick(self):
        if self.halt.is_set():
            return None
        try:
            try:
                state = self.latest.get_nowait()
            except queue.Empty:
                state = None
            scene = bpy.data.scenes.get(SCENE_NAME)
            if not scene:
                return 0.5
            if state and self.order.accept(state):
                self.vehicle_renderer.apply(state["vehicles"])
                self.signal_renderer.apply(state["signals"])
                self.last_state = state
                scene["traffic_sequence"] = state["sequence"]
                scene["traffic_session"] = state["session_id"]
                scene["traffic_time"] = state["timestamp"]
                scene["traffic_phase"] = state["signals"]["stage"]
                scene["traffic_missing_signals"] = ",".join(self.signal_renderer.missing)
                with self.lock:
                    self.ack = {"type": "blender_ack", "session_id": state["session_id"],
                                "sequence": state["sequence"], "vehicle_count": len(self.vehicle_renderer.objects),
                                "missing_signals":list(self.signal_renderer.missing)}
            with self.lock:
                connected = not self.error and time.monotonic()-self.received<3
                error = self.error
            scene["traffic_connected"], scene["traffic_error"] = connected, error
            if self.last_state:
                dashboard_overlay.update(self.last_state, connected, error)
        except Exception:
            LOG.exception("Traffic scene update failed; inspect mapped objects or rebuild")
        return 0.05


def start(url="ws://127.0.0.1:8875/ws"):
    global _active
    stop()
    _active = Controller(url)
    _active.start()
    return _active


def stop():
    global _active
    if _active:
        _active.stop()
        _active = None


@bpy.app.handlers.persistent
def on_load(_):
    stop()


for callback in list(bpy.app.handlers.load_pre):
    if callback.__module__ == __name__ and callback.__name__ == "on_load":
        bpy.app.handlers.load_pre.remove(callback)
bpy.app.handlers.load_pre.append(on_load)
