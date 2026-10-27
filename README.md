# Nexus — Real-Time Traffic Signal Digital Twin

A functional four-way urban intersection with **external Python traffic physics**, authoritative
signal phases, **WebSocket synchronization**, a procedural Blender scene, and a working browser
control dashboard. Vehicle movement is computed at runtime, not keyframed.

![Intersection](artifacts/intersection.png)
![Intersection detail](artifacts/intersection_detail.png)
![Dashboard](artifacts/dashboard.png)

## Verified environment

- Blender **5.2.3 LTS**, bundled Python **3.14.8**.
- System Python **3.14.8**; the isolated external simulation environment uses Python **3.13.14**.
- External dependencies installed: **aiohttp 3.14.5**, **pytest 9.1.1**.
- Linux with a graphical Blender desktop. Other Blender/platform combinations are unverified.
- Blender imports **only its bundled APIs and Python's standard library**. It does not need aiohttp,
  pytest, NumPy, FastAPI, or a separately installed WebSocket package.

The actual project is `/home/saumil/Projects/code/traffic-digital-twin`. Earlier projects were
preserved. All traffic code, configuration, and generated assets are contained here.

## Installation and startup

The project environment is already installed. From this directory:

```bash
.venv/bin/python run.py
```

This launches the external server, opens the saved scene or builds it on first use, connects
Blender, and opens **http://127.0.0.1:8875**. Click **Start** in the dashboard.
**Ctrl+C** in the launcher, or closing the Blender window it launched, shuts down its processes.
The launcher also handles SIGTERM and refuses to silently attach to an occupied port.

```bash
.venv/bin/python run.py --no-browser
.venv/bin/python run.py --port 8876 --blender /absolute/path/to/blender
```

To install on a fresh checkout with `uv`:

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python run.py
```

Alternatively, create a Python 3.11+ virtual environment and install `requirements.txt` with pip.
Runtime requires aiohttp only; pytest is a development dependency listed for reproducible testing.

### Separate-process development commands

Terminal 1:

```bash
.venv/bin/python run_simulation.py --autostart
```

Terminal 2, first build:

```bash
blender --python blender/launch.py -- --save artifacts/traffic_twin.blend
```

Load the generated file and reconnect:

```bash
blender artifacts/traffic_twin.blend --python blender/launch.py
```

Explicitly rebuild the managed intersection and save it:

```bash
blender artifacts/traffic_twin.blend --python blender/launch.py -- --rebuild --save artifacts/traffic_twin.blend
```

Use `--config config/intersection.json` and `--port 8876` on the server to select configuration
and port. Pass `--url ws://127.0.0.1:8876/ws` after Blender's `--` when selecting another port.
The server can run independently of Blender; the dashboard still controls and visualizes it.

**Opening the `.blend` alone is a saved snapshot.** Use the documented launch script to install
the live controller. No embedded script auto-execution setting is required.

### Blender MCP / already-open Blender

The delivered traffic scene was created, connected, inspected, and rendered using Blender MCP.
In a fresh Blender Python Console or through Blender MCP, execute:

```python
import sys
sys.path.insert(0, '/home/saumil/Projects/code/traffic-digital-twin')
from blender.scene_builder import build_scene
from blender import traffic_controller, addon
traffic_controller.stop()
build_scene()  # omit when the traffic scene is already loaded
addon.register()
traffic_controller.start('ws://127.0.0.1:8875/ws')
```

Use a fresh Blender process if another project has already imported packages named `blender`,
`simulation`, or `communication`: changing `sys.path` does not replace cached Python modules.
`blender/launch.py` handles the path in a normal fresh launch.

The **Traffic Twin** sidebar offers Connect/Disconnect and live phase/connection information.
The scene builder manages only its dedicated scene and `traffic_owned` objects; other scenes
and objects are preserved. Rebuilding twice does not accumulate scene objects.

## What to observe

- Four approaches, **two inbound and two outbound lanes each**, right-hand traffic.
- Lane dividers, centerlines, directional arrows, stop lines, zebra crossings, curbs, sidewalks,
  buildings, landscaping, streetlights, and four three-lamp signal heads.
- Cars, buses, trucks, and motorcycles accelerate, brake, queue, turn, cross, and leave the network.
- The **inner inbound lane** carries straight/left routes; the **outer lane** carries straight/right.
- Vehicle meshes, signal lamps, queue labels, phase countdown, clock, and metrics follow incoming
  simulation snapshots. There are no vehicle animation keyframes.
- `TR.camera` is the complete overview. `TR.camera.detail` is a closer junction observer.
  Switch in Blender's scene camera setting, or use:

```python
bpy.context.scene.camera = bpy.data.objects['TR.camera.detail']
# Return to the full scene:
bpy.context.scene.camera = bpy.data.objects['TR.camera']
```

### Demonstrate a real timing change

1. **Reset**, set **NS green = 5 s**, **EW green = 40 s**, and **Time scale = 5×**; click Apply.
2. Click Start. NS serves first, followed by 3 s yellow and 1 s all-red, then EW serves.
3. Watch the same phase/lamp changes in the browser map and Blender. EW vehicles receive entry
   reservations, accelerate, and cross; red-side queues remain behind their stop lines.
4. Increase East demand to **900 vehicles/h**. New arrivals increase according to that rate;
   congestion and approach queue metrics change. Reduce it to zero to stop future arrivals.
5. Pause freezes **both vehicles and signal timers**. Resume continues from the same state.
   Stop freezes the current state; Start continues it. Reset is the operation that restarts time.

The configuration file defaults to **25 s green per phase, 3 s yellow, 1 s all-red**. Screenshots
use a shorter 12/12 s demonstration plan. These are demonstration values, not timing recommendations.

## Architecture and ownership

```text
dashboard/app.js ── WebSocket commands ──► aiohttp /ws ──► simulation.Engine
        ▲                                      │           fixed steps + signal FSM
        │                                      ▼
        └──────── WebSocket state/history ── single authoritative snapshot
                                               │
                               Blender stdlib WebSocket worker
                                               │
                                    queue(maxsize=1), newest wins
                                               │
                                bpy.app.timers main-thread callback
                                  ├─ vehicle creation/removal + transforms
                                  ├─ signal materials from authoritative colors
                                  ├─ labels / connection indicators
                                  └─ applied-state acknowledgement back over WS
```

The aiohttp event loop serializes engine commands, simulation steps, and snapshot construction.
No `bpy` is imported by the server or physics model. Blender's network worker never accesses
`bpy`; all scene reads/writes used for rendering happen in its main-thread timer (20 Hz).
The server broadcasts snapshots at approximately 10 Hz with one-slot queues per peer, so a slow
client cannot accumulate an unbounded stale-state backlog. History accompanies one snapshot/s.

The wall-clock scheduler accumulates elapsed time × simulation speed and takes complete fixed
steps. It caps catch-up batches and backlog. Under overload, wall-clock simulation speed may lag;
it never increases the physics timestep to catch up. Identical configuration, initial state, and
command steps produce identical physical results; network command arrival times are not a
deterministic replay mechanism.

### Files

```text
blender/
  scene_builder.py       Roads, city environment, collections, cameras, signals
  traffic_controller.py  WS worker, latest-state queue, ordering, bpy timer
  vehicle_renderer.py    Linked type/color meshes and stable vehicle objects
  signal_renderer.py     Separate red/yellow/green on/off lamp materials
  dashboard_overlay.py   Live in-scene text instrumentation
  materials.py           PBR materials and installed-enum lookup helpers
  addon.py               Connect/disconnect sidebar
  launch.py              Blender startup entry point
simulation/
  config.py              Atomic validation and immutable parameters
  engine.py              Fixed-step state and lifecycle owner
  vehicle.py             Vehicle types, state, and IDM equation
  traffic_signal.py      Authoritative NS/EW phase state machine
  intersection.py        Entry reservations and receiving-lane checks
  lane.py                Approach/lane geometry and coordinate constants
  routing.py             Straight/left/right arc-length paths
  traffic_metrics.py     Queues, stop time, speed, throughput
communication/
  server.py              aiohttp WS + static dashboard + read-only HTTP endpoints
  protocol.py            Strict JSON/state validation and ordering guard
  client.py              Standard-library RFC6455 client used inside Blender
dashboard/               HTML, CSS, JavaScript, actual live map and charts
config/intersection.json Initial SI configuration
tests/                   pytest, headless Blender, real browser, launcher checks
run_simulation.py        Independent external simulation entry point
run.py                   One-command process supervisor
requirements.txt         External dependencies
artifacts/               Generated scene, renders, reports, command logs
```

## Traffic model

### Intelligent Driver Model (IDM)

```text
s* = s0 + max(0, v T + v(v - vleader)/(2 sqrt(a b)))
dv/dt = a [1 - (v/vdesired)^4 - (s*/gap)^2]
```

`s0` is the minimum bumper gap (default 2 m), `T` the headway (1.3 s), `b = 3 m/s²`
comfortable braking, and `a` a type-specific acceleration. Acceleration is bounded between
−8 m/s² and the vehicle's acceleration capability. A stopped virtual leader represents a
red/yellow signal or an unavailable conflict-zone reservation.

The fixed-step, semi-implicit update calculates all vehicles from the same old-state snapshot
in stable ID order, then applies updates. A hard non-penetration constraint limits advance to
the available old-state gap minus the minimum gap. This conservative guard can override the
nominal acceleration when necessary. Vehicles never reverse. Increasing the minimum gap does
not teleport an existing queue; it waits for new space before advancing.

Type dimensions/capabilities (`length × width × height`, metres; acceleration m/s²):

| Type | Dimensions | Acceleration |
|---|---|---|
| Car | 4.5 × 1.85 × 1.45 | 2.2 |
| Bus | 10.5 × 2.5 × 3.1 | 1.1 |
| Truck | 8.0 × 2.4 × 2.8 | 1.2 |
| Motorcycle | 2.2 × 0.8 × 1.2 | 2.8 |

Turning vehicles use a 6 m/s cornering target. Routes combine straight entry/exit segments and
100-sample cubic Bézier turn paths, indexed by arc length. Vehicles are removed when their rear
has passed the exit boundary. There is no lane changing or overtaking; routes remain fixed for
each vehicle. Crosswalks are modeled geometry, not a pedestrian simulation.

### Signal phases and safe entry

```text
NS_GREEN → NS_YELLOW → ALL_RED_TO_EW → EW_GREEN → EW_YELLOW → ALL_RED_TO_NS → repeat
```

Reset starts at **NS_GREEN**, elapsed **0**, simulation mode **stopped**, and zero vehicle speeds.
Minimum/maximum green bounds are validated with each update. Shortening an already-running green
expires that green on the next simulation step **without skipping the yellow or all-red clearance**.
This edge case has a dedicated regression test.

**Important model choice:** compatible NS or EW greens enable requests, but the conflict zone
has an **exclusive reservation**. Only one vehicle may occupy it at a time. Receiving-lane
space is checked, the leading vehicle in each lane is eligible, and longest-wait-first arbitration
breaks ties by stable ID. The owner is retained until the vehicle's rear clears its exit plus 1 m.
This protects opposing turns and merges, but deliberately gives lower capacity than a calibrated
multi-conflict-zone road model. A green light does not imply immediate entry if another vehicle
is still clearing the box. Existing reservations continue through yellow/red to clear safely.

Yellow policies:
- `stop` (default): no new yellow entries; already committed vehicles continue.
- `clear_if_unavoidable`: a vehicle unable to stop within `v²/(2b)` may request a yellow entry,
  but must still obtain the exclusive reservation. Otherwise the hard stop-line guard applies.

### Demand and metrics

Arrival credits accumulate at `approach_demand / 7200` vehicles/s **per inbound lane**, dividing
each approach's demand equally over its two lanes. Arrivals are deterministic, not random motion.
The seed shifts a repeatable vehicle-type/turn sequence. Turn ratios apply to new vehicles, with
left/right restricted to their compatible lanes. Each ratio is 0–50%, with total <=90%.
Entry space and the vehicle cap are enforced; excess arrivals are counted as blocked backpressure.

- Queue count: inbound vehicles moving below **0.5 m/s**.
- Queue length: longest stopped queue's tail distance to that approach's stop line.
- Waiting time: accumulated inbound time below 0.5 m/s; mean includes active and completed trips.
- Throughput: completed trips ×3600 / elapsed simulation time (initial-queue warm-up affects it).
- History: 1200 bounded samples, approximately 0.5 simulated seconds apart; reset clears it.

The default 300 vehicles/h per approach can exceed this conservative junction's capacity,
making congestion visible. It is a configurable synthetic traffic model, not a calibrated feed
from a particular real intersection. A sensor adapter can supply demand/control changes through
the same WebSocket protocol.

## Configuration and coordinates

All internal lengths are **metres**, times **seconds**, speeds **m/s**, headings **radians**,
and demand **vehicles/hour/approach**. Blender and simulation share the same right-handed XY
plane with **Z up**: +X East, +Y North; **1 Blender unit = 1 m**. Vehicle mesh forward is local +Y,
so Blender Z yaw is `atan2(dy, dx) - π/2`. No axis flip or scaling conversion is needed.
Lane width is 3.2 m, entry/exit boundary 65 m from center, stop line 11 m from center.

Stable mappings:
- Vehicle `veh_000001` → `TR.veh_000001`, with `entity_id` custom property.
- Signal group `N` → `TR.signal.N.RED`, `.YELLOW`, `.GREEN`, with group/identity properties.
- `TR | 06 Live Vehicles` contains only managed vehicle objects. Type/color meshes are shared,
  created once, and reused. Objects are added/removed only when population changes.
- Scene properties expose `traffic_connected`, `traffic_sequence`, `traffic_session`,
  `traffic_time`, `traffic_phase`, `traffic_error`, and `traffic_missing_signals`.

`config/intersection.json` contains all settings. Dashboard controls expose all settings:

| Setting | Default | Bounds / application |
|---|---|---|
| Timestep | 0.1 s | 0.02–0.2 s |
| Simulation speed | 2× | 0.1–20× |
| NS / EW green | 25 / 25 s | Between configured min/max green |
| Min / max green | 5 / 90 s | 3–60 / 5–120 s |
| Yellow / all-red | 3 / 1 s | 2–6 / 0.5–5 s |
| Each approach demand | 300 veh/h | 0–1800 |
| Desired speed | 13.9 m/s | 3–20 m/s; dashboard displays km/h |
| Minimum gap / headway | 2 m / 1.3 s | 1–5 m / 0.8–3 s |
| Left / right ratio | 25 / 25% | Each 0–50%; sum <=90%; new arrivals |
| Yellow policy | `stop` | `stop` / `clear_if_unavoidable` |
| Population cap | 160 | 24–200; gates new entries, doesn't delete existing vehicles |
| Seed | 42 | Integer 0–1,000,000; latched on reset |
| Initial queue per lane | 3 | Integer 0–4; next reset; must fit population cap |

Parameter changes are atomic. Booleans as numbers, strings, infinities, NaN, invalid bounds,
unknown keys, or contradictory green limits are rejected. Reset retains current configuration,
rebuilds the initial population/routes, clears metrics/history, and keeps transport sequence
numbers increasing. Vehicle IDs can repeat after reset; session+sequence establishes freshness.

## WebSocket protocol and reliability

Server: **`ws://127.0.0.1:8875/ws`**. Browser and Blender use this same transport.

Command:

```json
{"type":"command","request_id":"ui-1","action":"parameters","parameters":{"green_ns":12,"demand_east":900}}
```

Acknowledgement or error:

```json
{"type":"ack","request_id":"ui-1","sequence":123}
```

State envelope:

```text
{
  type: "state",
  state: {schema_version:1, session_id, sequence, timestamp, mode,
          parameters, signals:{stage,elapsed,remaining,groups},
          vehicles:{id:{position,heading,speed,acceleration,lane,turn,...}}, metrics},
  health: {...},
  history: [...]  // included about once per real second
}
```

This envelope illustration is a schema outline; `/api/state` supplies complete valid JSON.
Blender sends `blender_ack` only after main-thread rendering, including applied sequence,
vehicle count, session, and missing signal objects. Health marks an acknowledgement older than
3 s disconnected. Deleted vehicle objects are recreated on the next accepted snapshot; missing
signal lamps are skipped and reported, rather than stopping updates to the rest of the scene.

The server has a new UUID each startup; sequences increase for every successful command and
physics step, including across resets. Blender rejects duplicates, stale sequences, malformed
states, non-finite values, and phase/color contradictions. A new session retires the old one.
Messages are bounded to 512 KiB; JSON duplicate keys are rejected. Per-peer state queues have
capacity one; there are at most 16 peers. The RFC6455 client validates upgrades, masks outbound
frames, handles extended lengths/fragmentation/ping/pong/close, and negotiates no compression.

Blender reconnects with 0.2–2 s backoff and retains its last scene pose during disconnection.
The browser reconnects after 1 s and has a stale-stream watchdog, disables commands offline,
and never automatically retries a command that may already have been applied. A command's
4 s response timeout advises checking live state before retrying.

Read-only HTTP endpoints: `/api/state`, `/api/health`, `/api/history`. Controls use WebSockets.
Only loopback is bound; Host/Origin are checked. This is a local development service.
Command events append to `artifacts/commands.jsonl` with rotation at 2 MB and two backups.

## Automated checks — actually executed

Core pytest suite:

```bash
.venv/bin/python -m pytest -q
```

**Observed: 58 passed.** Includes phase transitions, clearance after live timing reductions,
pause/reset/resume, IDM acceleration/braking, continuous routes in all directions, queues,
vehicle generation/removal, seed/reset behavior, demand backpressure, population limits,
determinism, invalid parameters/messages, serialization, stale ordering, real WebSocket controls,
disconnect/reconnect, fragmented/extended frames, and ping/pong. Safety tests check **oriented
physical vehicle rectangles** across 180 simulated seconds, all turn types, and repeated phases.

Headless Blender + separate external Python process:

```bash
blender --background --factory-startup --python tests/blender_integration.py
```

**Observed: `TRAFFIC_BLENDER_INTEGRATION_PASS`.** Checks repeatable scene building, preservation
of prior objects, actual moving Blender vehicles, frozen vehicles/timers on pause, edited phase
timings driving actual lamp materials, reset mapping, deleted-vehicle repair, server shutdown,
and reconnection to a new session. Report: `artifacts/blender_integration.json`.

Optional real-browser E2E (requires Playwright and an installed Chrome):

```bash
uv pip install --python .venv/bin/python playwright
.venv/bin/python tests/browser_smoke.py --chrome /opt/google/chrome/chrome
```

Start a live development instance first. This test intentionally changes/resets its traffic
state and leaves it running with a 12/12 s observation plan. **Observed:
`TRAFFIC_BROWSER_SMOKE_PASS`**, including live timing/demand edits, vehicle release, pause/resume,
stop/reset, network-loss recovery, Blender acknowledgements, and **zero JavaScript errors**.
The observed run reused the already-installed neighboring Playwright environment:

```bash
/home/saumil/Projects/code/pathy/.venv/bin/python tests/browser_smoke.py
```

Reports: `artifacts/browser_smoke.json`, `artifacts/dashboard.png`.

One-command GUI launcher check:

```bash
.venv/bin/python tests/launcher_smoke.py
```

**Observed: `TRAFFIC_LAUNCHER_SMOKE_PASS`.** Opened the saved `.blend`, received Blender's actual
WebSocket acknowledgement, and verified that interrupting the launcher shut down its processes.
Report: `artifacts/launcher_smoke.json`.

```bash
node --check dashboard/app.js
```

JavaScript syntax check also passed. Tests use private ephemeral ports except the explicitly
documented browser test. The headless test manually invokes the Blender timer on its main thread
because a blocking background script doesn't run Blender's interactive event loop.

## Troubleshooting

- **Port busy:** another demo is already running. Use its dashboard, stop that server, or select
  `--port 8876` consistently. The launcher does not kill unrelated processes.
- **Static saved scene:** open it with `--python blender/launch.py`. Loading `.blend` alone does
  not register a live timer. The server must also be running.
- **Blender offline:** check `/api/health`, confirm the `ws://` URL and port, and wait for retry.
  A blocked Blender main thread cannot acknowledge applied states even if its socket is alive.
- **Green but queued:** another vehicle may own the protected conflict-zone reservation, or the
  receiving lane may be occupied. Inspect the dashboard's reservation line.
- **Timing update rejected:** make both greens consistent with min/max bounds; all form fields
  are sent atomically. Read the dashboard's specific error text.
- **Delayed new demand:** arrivals use deterministic credits, so a lower rate takes time to
  accumulate a vehicle. Existing queues don't disappear when demand is set to zero.
- **Missing signals:** inspect `traffic_missing_signals` and health's `missing_signals`; rebuild
  the scene or restore the stable lamp names. Deleted vehicle objects recover automatically.
- **Package imports resolve to another project:** launch fresh Blender from this project's script.
  Don't assume a `sys.path` change clears cached `simulation` or `blender` packages.
- **Need independent physics only:** run `run_simulation.py --autostart`; no Blender process is
  required. For headless verification, use the integration command above.
