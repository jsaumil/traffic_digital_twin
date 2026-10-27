import argparse
import asyncio
from collections import deque
import contextlib
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time

from aiohttp import web, WSMsgType
from communication.protocol import MAX_BYTES, dumps, loads
from simulation.config import Config
from simulation.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("traffic")


class Service:
    def __init__(self, config=None, autostart=False):
        self.engine = Engine(config)
        if autostart:
            self.engine.command("start")
        self.peers = {}
        self.blender_ack = None
        self.tasks = []
        self.revision = 0
        self.events = deque(maxlen=200)

    def command(self, message):
        if set(message) - {"type", "request_id", "action", "parameters"}:
            raise ValueError("Unknown command fields")
        if not isinstance(message.get("action"), str):
            raise ValueError("Command action required")
        if "parameters" in message and message["action"] != "parameters":
            raise ValueError("Use action=parameters to edit settings")
        state = self.engine.command(message["action"], message.get("parameters"))
        self.revision += 1
        event = {"sequence": state["sequence"], "timestamp": state["timestamp"],
                 "session_id": state["session_id"], "action": message["action"],
                 "parameters": message.get("parameters")}
        self.events.append(event)
        LOG.info(dumps(event))
        return {"type": "ack", "request_id": message.get("request_id"), "sequence": state["sequence"]}

    def acknowledge(self, body):
        if (body.get("session_id") != self.engine.session_id or type(body.get("sequence")) is not int
                or not 0 <= body["sequence"] <= self.engine.sequence):
            raise ValueError("Invalid applied-state acknowledgement")
        count = body.get("vehicle_count")
        if type(count) is not int or not 0 <= count <= 200:
            raise ValueError("Invalid rendered vehicle count")
        missing=body.get("missing_signals",[])
        if not isinstance(missing,list) or len(missing)>12 or any(not isinstance(x,str) or len(x)>32 for x in missing):
            raise ValueError("Invalid missing signal list")
        self.blender_ack = {"sequence": body["sequence"], "vehicle_count": count,
                            "missing_signals":missing,
                            "session_id": body["session_id"], "received": time.monotonic()}

    def health(self):
        ack = dict(self.blender_ack) if self.blender_ack else None
        age = time.monotonic() - ack.pop("received") if ack else None
        return {"ok": True, "session_id": self.engine.session_id, "clients": len(self.peers),
                "blender_connected": age is not None and age < 3, "blender_age": age, "blender": ack}

    async def simulation_loop(self):
        last, accumulator, revision = time.monotonic(), 0.0, -1
        while True:
            now = time.monotonic()
            elapsed, last = min(0.25, now - last), now
            if revision != self.revision:
                accumulator, elapsed, revision = 0, 0, self.revision
            c = self.engine.config
            if self.engine.mode == "running":
                accumulator += elapsed * c.simulation_speed
                steps = min(20, int((accumulator + 1e-9) / c.timestep))
                for _ in range(steps):
                    self.engine.step()
                accumulator = min(max(0, accumulator - steps * c.timestep), 20 * c.timestep)
            else:
                accumulator = 0
            await asyncio.sleep(0.01)

    def packet(self, history=False):
        return dumps({"type": "state", "state": self.engine.snapshot(), "health": self.health(),
                      **({"history": list(self.engine.history)} if history else {})})

    async def publish_loop(self):
        index = 0
        while True:
            if self.peers:
                packet = self.packet(index % 10 == 0)
                for queue in list(self.peers.values()):
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(packet)
            index += 1
            await asyncio.sleep(0.1)


def trusted(request):
    port = request.transport.get_extra_info("sockname")[1]
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    return request.host in hosts and request.headers.get("Origin") in {None, *(f"http://{h}" for h in hosts)}


@web.middleware
async def local_only(request, handler):
    if not trusted(request):
        return web.json_response({"error": "Use this server's localhost origin"}, status=403)
    response = await handler(request)
    if not isinstance(response, web.WebSocketResponse):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


async def websocket(request):
    service = request.app["service"]
    if len(service.peers) >= 16:
        raise web.HTTPServiceUnavailable(text="Maximum 16 clients")
    ws = web.WebSocketResponse(heartbeat=5, timeout=1, max_msg_size=MAX_BYTES, compress=False)
    await ws.prepare(request)
    queue = asyncio.Queue(maxsize=1)
    service.peers[ws] = queue
    queue.put_nowait(service.packet(True))
    async def sender():
        while True:
            packet = await queue.get()
            await asyncio.wait_for(ws.send_str(packet), timeout=2)
    task = asyncio.create_task(sender())
    task.add_done_callback(lambda done: asyncio.create_task(ws.close()) if not done.cancelled() else None)
    try:
        async for incoming in ws:
            if incoming.type != WSMsgType.TEXT:
                if incoming.type == WSMsgType.ERROR:
                    break
                continue
            request_id = None
            try:
                message = loads(incoming.data)
                request_id = message.get("request_id")
                if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 64):
                    raise ValueError("Invalid request_id")
                if message.get("type") == "command":
                    await ws.send_str(dumps(service.command(message)))
                elif message.get("type") == "blender_ack":
                    service.acknowledge(message)
                else:
                    raise ValueError("Use command or blender_ack message type")
            except (ValueError, TypeError) as exc:
                await ws.send_str(dumps({"type": "error", "request_id": request_id, "error": str(exc)}))
    finally:
        service.peers.pop(ws, None)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, ConnectionError, TimeoutError):
            await task
    return ws


def create_app(config=None, autostart=False):
    service = Service(config, autostart)
    app = web.Application(middlewares=[local_only], client_max_size=MAX_BYTES)
    app["service"] = service
    async def state(request):
        return web.json_response(service.engine.snapshot())
    async def health(request):
        return web.json_response(service.health())
    async def history(request):
        return web.json_response({"samples": list(service.engine.history)})
    async def asset(request):
        name = request.match_info.get("asset", "index.html")
        if name not in {"index.html", "styles.css", "app.js"}:
            raise web.HTTPNotFound()
        return web.FileResponse(ROOT / "dashboard" / name)
    async def lifecycle(app):
        service.tasks = [asyncio.create_task(service.simulation_loop()), asyncio.create_task(service.publish_loop())]
        yield
        for ws in list(service.peers):
            await ws.close(code=1001, message=b"Server shutting down")
        for task in service.tasks:
            task.cancel()
        await asyncio.gather(*service.tasks, return_exceptions=True)
    async def shutdown(app):
        # Close peers before aiohttp waits for long-lived request handlers.
        for task in service.tasks:
            task.cancel()
        await asyncio.gather(*(ws.close(code=1001,message=b"Server shutting down")
                               for ws in list(service.peers)),return_exceptions=True)
    app.on_shutdown.append(shutdown)
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/history", history)
    app.router.add_get("/", asset)
    app.router.add_get("/{asset}", asset)
    return app


def main():
    parser = argparse.ArgumentParser(description="Real-time traffic twin WebSocket server")
    parser.add_argument("--port", type=int, default=8875)
    parser.add_argument("--config", type=Path, default=ROOT / "config/intersection.json")
    parser.add_argument("--autostart", action="store_true")
    args = parser.parse_args()
    try:
        config = Config(**loads(args.config.read_bytes()))
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"Configuration error: {exc}\n")
    (ROOT / "artifacts").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    handler = RotatingFileHandler(ROOT / "artifacts/commands.jsonl", maxBytes=2_000_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOG.addHandler(handler)
    web.run_app(create_app(config, args.autostart), host="127.0.0.1", port=args.port, access_log=None)


if __name__ == "__main__":
    main()
