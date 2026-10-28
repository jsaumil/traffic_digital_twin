# Nexus — Real-Time Traffic Signal Digital Twin

A digital twin of a **real signalized junction: 120 Feet Ring Road × Drive-in Road, Navrangpura,
Ahmedabad** (23.0427 N, 72.5491 E). Road geometry, carriageway layout and surrounding buildings
come from **OpenStreetMap**. It has **external Python traffic physics** for Indian mixed,
left-hand traffic, authoritative split-phase signals, **WebSocket synchronization**, a Blender
scene generated from the map, and a working browser control dashboard. Demand follows an
Ahmedabad time-of-day profile, and can optionally be driven live from TomTom real-time speeds.
Vehicle movement is computed at runtime, not keyframed.

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

- The real junction from OpenStreetMap: 120 Feet Ring Road (bearings 30° / 195°, 3 + 3 lanes)
  crossing Drive-in Road (119° / 305°, 2 + 2 lanes), both divided by a kerbed median. Arms are
  labelled N/E/S/W by nearest compass bearing; the roads are not on a right-angle grid.
- **Left-hand traffic.** Left turns are the short near-side turn (and may go on red, "free left");
  right turns cross oncoming traffic.
- **Split phasing:** each arm gets its own green in clockwise order N → E → S → W, with 3 s amber and
  2 s all-red (IRC:93), as is typical at Ahmedabad signals.
- **Indian mixed traffic:** two-wheelers (~62%), cars, auto-rickshaws, buses and trucks.
  Two-wheelers ride in half-lane strips, so they filter up beside each other to the stop line.
- Lane markings, stop lines, zebra crossings, kerbs, footpaths, median streetlights, four signal
  heads at the real stop lines, and 106 OSM building footprints extruded to height.
- Vehicle meshes, signal lamps, queue labels, phase countdown, clock, and metrics follow incoming
  simulation snapshots. There are no vehicle animation keyframes.
- The dashboard map (`dashboard/map.js`) animates at the display frame rate by interpolating
  between the ~10 Hz snapshots (drawn ~120 ms behind the newest one). Scroll to zoom, drag to
  pan, double-click to reset, hover a vehicle for its speed, state and route. Brake lights,
  turn indicators and, after dusk on the simulated clock, headlights and streetlights are shown.
- `TR.camera` is the complete overview. `TR.camera.detail` is a closer junction observer.
  Switch in Blender's scene camera setting, or use:

```python
bpy.context.scene.camera = bpy.data.objects['TR.camera.detail']
# Return to the full scene:
bpy.context.scene.camera = bpy.data.objects['TR.camera']
```

### Demonstrate a real timing change

1. **Reset**, set **N / S arm green = 5 s**, **E / W arm green = 40 s**, and **Time scale = 5×**; click Apply.
2. Click Start. N serves first, then 3 s amber and 2 s all-red, then E, S and W in turn.
3. Watch the same phase/lamp changes in the browser map and Blender.
4. Change **Start time** to 03:00 and back to 10:30 to see night and morning-peak demand, or set
   **Demand source = Manual** and type your own vehicles/hour per arm.
5. Pause freezes **both vehicles and signal timers**. Resume continues from the same state.
   Stop freezes the current state; Start continues it. Reset is the operation that restarts time.

## Real data: sources, assumptions and how to replace them

| Input | Source | Status |
|---|---|---|
| Road alignment, divided carriageways, one-way structure, buildings | OpenStreetMap (cached in `data/osm/navrangpura_raw.json`, ODbL) | Real |
| Lane counts, median width | OSM has no lane tags here; 3 + 3 lanes on Ring Road (120 ft right of way), 2 + 2 on Drive-in Road, 1.2 m median, in `data/osm/navrangpura_overrides.json` | **Estimate: verify on satellite imagery** |
| Stop-line positions | Computed from crossing road widths + 4 m zebra crossing | Derived |
| Hourly demand shape | Morning and evening peaks; peak hour 8.4% of daily traffic, from published Ahmedabad arterial counts (8.5–11%) | Published basis |
| Daily volume per arm | 20,000 (Ring Road) / 9,000 (Drive-in Road) inbound vehicles per day in `data/demand/navrangpura.json` | **Estimate: no published count for this junction** |
| Fleet mix, PCU | ~62% two-wheelers (~70% city-wide); PCU car 1.0, two-wheeler 0.5, bus/truck 3.5, auto 1.0 (assumed) | Published basis + assumption |
| Saturation flow | IRC `525 × approach width` PCU/h; model calibrated to 98% (time headway 1.2 s) | Calibrated |
| Live conditions | TomTom Traffic Flow speeds on each approach, when `TOMTOM_API_KEY` is set | Optional live |

Street View imagery is not used: Google's terms do not allow deriving models from it.

**Use your own counts (the strongest improvement).** Count vehicles entering from each arm, by
hour, for example from a phone video. Then either set `daily_inbound`, or replace
`"hourly_inbound": null` with 24 hourly values per arm in `data/demand/navrangpura.json`.
`TRAFFIC_DEMAND=/path/file.json` selects a different profile.

**Fix lanes and medians** in `data/osm/navrangpura_overrides.json` (keys per arm: `in_lanes`,
`out_lanes`, `median`, `lane_width`, `name`), then run `.venv/bin/python tools/import_osm.py`.

**Model a different junction:**

```bash
.venv/bin/python tools/import_osm.py --fetch --lat 23.0225 --lon 72.5714 --name mine --title "My junction"
```

This downloads the junction from the Overpass API and writes `config/junction.json`. 3- and
4-arm junctions are supported. Check the printed lanes, add an overrides file, rebuild the
Blender scene with `--rebuild`, and supply a matching demand profile.

**Live mode.** Create a free TomTom developer key, then
`TOMTOM_API_KEY=... .venv/bin/python run.py`, and choose **Demand source = Live speeds** on the
dashboard. Every 2 minutes the server samples the current and free-flow speed 60 m upstream on
each approach. It reads the speed drop as a degree of saturation, using
`free/current = 1 + x²`, and sets demand = `x × capacity`, where capacity is the IRC saturation
flow × green / cycle of the current plan. It also sets the desired speed to the measured
free-flow speed. These updates go through the normal command path, so they are logged in
`artifacts/commands.jsonl` and replayable. This is an estimate from speeds, not a vehicle count:
Ahmedabad publishes no open live counts.

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
  scene_builder.py       Real roads, OSM buildings, collections, cameras, signals
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
  junction.py            Real junction geometry (config/junction.json), turns, lane permissions
  geometry.py            Polyline offset/resample helpers shared with Blender
  demand.py              Time-of-day demand profile (data/demand/)
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
tools/import_osm.py      OpenStreetMap junction importer -> config/junction.json
data/osm/                Cached OSM download and manual lane/median overrides
data/demand/             Time-of-day demand profile with sources
communication/live_traffic.py  Optional TomTom live-speed demand feed
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

The fixed-step ballistic update (`Δs = (v + v')/2 · Δt`; a vehicle that would reverse stops
exactly within the step) calculates all vehicles from the same old-state snapshot in stable ID
order, then applies updates. A hard non-penetration constraint limits advance to the available
old-state gap minus the minimum gap and caps speed at the leader's. This conservative guard can
override the nominal acceleration when necessary. Vehicles never reverse.

Leaders are found on the same route anywhere (including inside the conflict zone), in the same
incoming lane until same-lane paths diverge 8 m past the stop line, and in the shared receiving
lane after merging. Each driver has an individual desired-speed factor (normal, σ = 7%, clipped
to ±15%); trucks and buses additionally use 90% and 85% of the configured desired speed. Increasing the minimum gap does
not teleport an existing queue; it waits for new space before advancing.

Type dimensions/capabilities (`length × width × height`, metres; acceleration m/s²). Two-wheelers
and autos use smaller standstill gaps and headways (gap ×0.5 / ×0.8, headway ×0.6 / ×0.9):

| Type | Dimensions | Acceleration | Share | PCU |
|---|---|---|---|---|
| Two-wheeler (`motorcycle`) | 1.9 × 0.75 × 1.3 | 2.6 | 62% | 0.5 |
| Car | 4.2 × 1.75 × 1.5 | 2.2 | 20% | 1.0 |
| Auto-rickshaw (`auto`) | 3.2 × 1.4 × 1.75 | 1.5 | 12% | 1.0 |
| Bus | 12.0 × 2.6 × 3.2 | 1.0 | 3% | 3.5 |
| Truck | 7.5 × 2.3 × 2.8 | 1.1 | 3% | 3.5 |

Two-wheelers ride in half-lane strips (0.85 m either side of the lane centre). They follow only
vehicles in their strip or full-width vehicles, so two can wait side by side and filter to the
front of a queue. Riders keep to the side of their turn.

Lanes are offset from the real OSM road axis. The kerb lane carries left + straight, the median
lane right + straight, and middle lanes straight only. Turn paths are cubic Béziers fitted as
circular arcs between the real approach and exit tangents: left 4.4–13 m radius, right 9–22 m.
Each turn's speed limit is `sqrt(a_lat × R)` with a comfortable lateral acceleration of 2.5 m/s².
Drivers decelerate toward it at 1.5 m/s² before the curve. Vehicles are posed with front and rear
axles both on the path, so long vehicles off-track inside a curve. Approaches are modelled 120 m
out from the junction centre. There is no lane changing; crosswalks are geometry, not a
pedestrian simulation.

### Signal phases and safe entry

```text
N_GREEN → N_YELLOW → ALL_RED_TO_E → E_GREEN → … → W_YELLOW → ALL_RED_TO_N → repeat
```

The phase plan comes from `config/junction.json` (split phasing, clockwise by bearing).
`green_ns` times the N and S phases, `green_ew` the E and W phases. The default cycle is
2 × 40 + 2 × 30 + 4 × 5 = 160 s. Reset starts at **N_GREEN**, elapsed **0**, simulation mode
**stopped**. Shortening an already-running green expires it on the next step **without skipping
amber or all-red**.

**Conflict-matrix reservations:** a green enables requests, and entry requires a reservation.
Two routes conflict when their conflict-zone paths come within 3 m of each other (crossings and
merges), precomputed from the real geometry. All of one arm's movements are mutually compatible,
so under split phasing an arm discharges all its lanes at once. A vehicle reserves within
`7 + s0 + vT + v²/5` m of the line. Facing a green, it does not brake for the stop line until
it is that close and has been refused. The first not-yet-reserved vehicle in each lane strip is
eligible. Priority movements are served before permissive ones, then longest wait, then stable
ID. Receiving-lane space is checked.

**Permissive and free turns:** right turns (and free left turns made on red, `free_left`) yield
to conflicting priority traffic. They accept a gap only when every such vehicle is at least
`max(4.5 s, own time-to-line + 3 s)` away (HCM critical gap 4.1–5.0 s). A right turner waiting at
the line may clear on amber.

**Amber onset:** a reserved vehicle that can still stop at ≤ 3 m/s² gives up its reservation.
Yellow policies: `stop` (default) admits no new entries on amber; `clear_if_unavoidable` admits
a vehicle that cannot stop comfortably, if it can get a non-conflicting reservation.

### Demand and metrics

Arrivals are **Poisson** per arm at the current demand. Demand comes from the time-of-day profile
(simulated clock = `start_hour` + elapsed time), the manual `demand_*` fields, or the live feed.
Each arrival draws a vehicle type, a turn (left/right ratios) and a driver speed factor
(σ = 7%), then joins the least-occupied lane serving its turn. It enters at the fastest speed
the IDM accepts without braking harder than 3 m/s². Up to 6 arrivals per arm wait at the network
edge; beyond that they count as blocked. Seeds make runs reproducible.

- Queue count/length/waiting time: inbound vehicles below **0.5 m/s**, per arm.
- Throughput: completed vehicles/h and **PCU/h** (`pcu_throughput_pch`).
- `demand_vph`: current arrival rate per arm; `clock_hour`: simulated local time.

## Configuration and coordinates

All internal lengths are **metres**, times **seconds**, speeds **m/s**, headings **radians**. The
local frame is centred on the junction (OSM coordinates projected to metres): +X East, +Y North,
**Z up**, **1 Blender unit = 1 m**. Vehicle mesh forward is local +Y, so Blender Z yaw is
`atan2(dy, dx) - π/2`. `/api/junction` serves the geometry to the dashboard.

Stable mappings:
- Vehicle `veh_000001` → `TR.veh_000001`, with `entity_id` custom property.
- Signal group `N` → `TR.signal.N.RED`, `.YELLOW`, `.GREEN`, with group/identity properties.
- `TR | 06 Live Vehicles` contains only managed vehicle objects. Type/color meshes are shared.
- Scene properties expose `traffic_connected`, `traffic_sequence`, `traffic_session`,
  `traffic_time`, `traffic_phase`, `traffic_error`, and `traffic_missing_signals`.

`config/intersection.json` contains all settings. Dashboard controls expose all settings:

| Setting | Default | Bounds / application |
|---|---|---|
| Timestep | 0.1 s | 0.02–0.2 s |
| Simulation speed | 2× | 0.1–20× |
| N/S arm green, E/W arm green | 40 / 30 s | Between configured min/max green |
| Min / max green | 5 / 90 s | 3–60 / 5–120 s |
| Amber / all-red | 3 / 2 s | 2–6 / 0.5–5 s |
| Demand source | `profile` | `profile` / `manual` / `live` |
| Start time | 9.5 h | 0–23.99 (simulated local time at reset) |
| Each arm demand (manual/live) | 900 / 900 / 500 / 500 veh/h | 0–4000 |
| Desired speed | 11.1 m/s (40 km/h) | 3–20 m/s; dashboard displays km/h |
| Minimum gap / headway | 1.5 m / 1.2 s | 1–5 m / 0.8–3 s (car values) |
| Left / right ratio | 20 / 20% | Each 0–50%; sum <=90%; new arrivals |
| Free left turn | on | Left turn on red after yielding |
| Yellow policy | `stop` | `stop` / `clear_if_unavoidable` |
| Population cap | 400 | 24–600 |
| Seed | 42 | Integer 0–1,000,000; latched on reset |
| Initial queue per lane | 2 | Integer 0–4; next reset; must fit population cap |

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
- **Green but queued:** a conflicting vehicle may hold a reservation, a permissive left turner
  may be waiting for a gap at the head of the shared left/through lane, or the receiving lane
  may be occupied. Inspect the dashboard's reservation line.
- **Timing update rejected:** make both greens consistent with min/max bounds; all form fields
  are sent atomically. Read the dashboard's specific error text.
- **Irregular arrivals:** arrivals are Poisson-random, so platoons and gaps occur naturally even
  at constant demand. Existing queues don't disappear when demand is set to zero.
- **Missing signals:** inspect `traffic_missing_signals` and health's `missing_signals`; rebuild
  the scene or restore the stable lamp names. Deleted vehicle objects recover automatically.
- **Package imports resolve to another project:** launch fresh Blender from this project's script.
  Don't assume a `sys.path` change clears cached `simulation` or `blender` packages.
- **Need independent physics only:** run `run_simulation.py --autostart`; no Blender process is
  required. For headless verification, use the integration command above.
