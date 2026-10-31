"""Import a real intersection from OpenStreetMap into config/map.json.

Finds the signalised junction nearest --lat/--lon, puts it at the twin origin, and rotates the
area so its streets line up with the simulation's N/S/E/W approaches. Standard library only.

    python tools/osm_import.py --lat 41.9033 --lon -87.6676 --name "Ashland & Division, Chicago"
    python tools/osm_import.py --input saved.osm --lat ... --lon ...   (offline)

Map data © OpenStreetMap contributors, ODbL 1.0. Keep the attribution wherever it is shown.
"""
import argparse
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulation.geo import EARTH_RADIUS, LocalFrame  # noqa: E402

API = "https://api.openstreetmap.org/api/0.6/map"
ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0)"
DRIVABLE = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
            "living_street", "motorway_link", "trunk_link", "primary_link", "secondary_link",
            "tertiary_link"}
MINOR = {"service"}
PATHS = {"footway", "cycleway", "pedestrian", "path", "steps"}
DEFAULT_LANES = {"motorway": 4, "trunk": 4, "primary": 4, "secondary": 2, "tertiary": 2}
AREAS = {("leisure", "park"): "green", ("landuse", "grass"): "green", ("leisure", "garden"): "green",
         ("natural", "wood"): "green", ("landuse", "forest"): "green", ("natural", "water"): "water",
         ("amenity", "parking"): "parking", ("leisure", "pitch"): "green"}


def fetch(lat, lon, radius):
    dlat = math.degrees(radius / EARTH_RADIUS)
    dlon = dlat / math.cos(math.radians(lat))
    bbox = f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}"
    request = Request(f"{API}?{urlencode({'bbox': bbox})}", headers={"User-Agent": "traffic-digital-twin/0.1"})
    with urlopen(request, timeout=90) as response:
        return response.read()


def parse(raw):
    root = ET.fromstring(raw)
    nodes = {n.get("id"): (float(n.get("lat")), float(n.get("lon")),
                           {t.get("k"): t.get("v") for t in n.findall("tag")}) for n in root.iter("node")}
    ways = [{"id": w.get("id"), "nodes": [nd.get("ref") for nd in w.findall("nd")],
             "tags": {t.get("k"): t.get("v") for t in w.findall("tag")}} for w in root.iter("way")]
    return nodes, ways


def number(text):
    try:
        return float(str(text).split(";")[0].replace("m", "").strip())
    except (TypeError, ValueError):
        return None


def arms(junction, ways, nodes, frame, reach=25.0):
    """Unit directions leaving the junction along each drivable way, merging near-parallel arms."""
    found = []
    for way in ways:
        if way["tags"].get("highway") not in DRIVABLE:
            continue
        ids = way["nodes"]
        for i, node in enumerate(ids):
            if node != junction:
                continue
            for step in (-1, 1):
                j, point = i + step, None
                while 0 <= j < len(ids) and ids[j] in nodes:
                    point = frame.east_north(*nodes[ids[j]][:2])
                    if math.hypot(*point) >= reach:
                        break
                    j += step
                if point and math.hypot(*point) > 1:
                    found.append({"angle": math.atan2(point[1], point[0]), "way": way})
    merged = []
    for arm in found:
        if all(abs(math.remainder(arm["angle"] - m["angle"], math.tau)) > math.radians(25) for m in merged):
            merged.append(arm)
    return merged


def find_junction(lat, lon, nodes, ways):
    frame = LocalFrame(lat, lon)
    counts = {}
    for way in ways:
        if way["tags"].get("highway") in DRIVABLE:
            for node in way["nodes"]:
                counts[node] = counts.get(node, 0) + 1
    best = None
    for node, count in counts.items():
        if node not in nodes:
            continue
        distance = math.hypot(*frame.east_north(*nodes[node][:2]))
        if distance > 120:
            continue
        found = arms(node, ways, nodes, LocalFrame(*nodes[node][:2]))
        if len(found) < 3:
            continue
        signals = nodes[node][2].get("highway") == "traffic_signals"
        score = distance - 40 * (len(found) == 4) - 25 * signals
        if best is None or score < best[0]:
            best = (score, node, found)
    if best is None:
        raise SystemExit("No junction with 3+ drivable arms within 120 m; check the coordinates")
    return best[1], best[2]


def road_width(tags):
    width = number(tags.get("width"))
    if width:
        return width, None
    lanes = number(tags.get("lanes"))
    if not lanes:
        lanes = DEFAULT_LANES.get(tags.get("highway", "").replace("_link", ""), 2)
        if tags.get("oneway") == "yes":
            lanes = max(1, lanes // 2)
    return lanes * 3.2, int(lanes)


def building_height(tags, way_id):
    height = number(tags.get("height"))
    if height:
        return height
    levels = number(tags.get("building:levels"))
    if levels:
        return levels * 3.2 + 1
    return 8 + int(way_id) % 5 * 2  # Unknown height: deterministic 8-16 m variation.


def build(raw, lat, lon, name, radius):
    nodes, ways = parse(raw)
    junction, junction_arms = find_junction(lat, lon, nodes, ways)
    jlat, jlon, jtags = nodes[junction]
    # Circular mean of 4θ gives the rotation that best aligns all arms to multiples of 90°.
    phi = math.atan2(sum(math.sin(4 * a["angle"]) for a in junction_arms),
                     sum(math.cos(4 * a["angle"]) for a in junction_arms)) / 4
    frame = LocalFrame(jlat, jlon, -math.degrees(phi))
    approaches = {}
    for arm in junction_arms:
        angle = math.degrees(arm["angle"] - phi) % 360
        key = "ENWS"[round(angle / 90) % 4]
        tags = arm["way"]["tags"]
        approaches[key] = {"street": tags.get("name") or tags.get("ref") or "unnamed",
                           "highway": tags.get("highway"), "lanes": tags.get("lanes"),
                           "oneway": tags.get("oneway") == "yes",
                           "compass_deg": round((90 - math.degrees(arm["angle"])) % 360, 1)}

    def line(ids, close=False):
        points = [frame.to_local(*nodes[i][:2]) for i in ids if i in nodes]
        points = [[round(x, 2), round(y, 2)] for x, y in points]
        if close and len(points) > 2 and points[0] == points[-1]:
            points.pop()
        return points

    def inside(points, margin=0):
        return any(abs(x) <= radius + margin and abs(y) <= radius + margin for x, y in points)

    roads, buildings, areas = [], [], []
    for way in ways:
        tags = way["tags"]
        closed = len(way["nodes"]) > 3 and way["nodes"][0] == way["nodes"][-1]
        highway = tags.get("highway")
        if "building" in tags and closed:
            points = line(way["nodes"], True)
            cx, cy = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
            if abs(cx) <= radius and abs(cy) <= radius:
                buildings.append({"id": way["id"], "name": tags.get("name"), "points": points,
                                  "height": round(building_height(tags, way["id"]), 1)})
        elif highway in DRIVABLE | MINOR | PATHS and tags.get("area") != "yes":
            points = line(way["nodes"])
            if len(points) > 1 and inside(points, 40):
                width, lanes = road_width(tags) if highway not in PATHS else (2.0, None)
                if highway in MINOR:
                    width = number(tags.get("width")) or 4.0
                roads.append({"id": way["id"], "name": tags.get("name"), "highway": highway,
                              "kind": "path" if highway in PATHS else "minor" if highway in MINOR else "road",
                              "lanes": lanes, "width": round(width, 1),
                              "oneway": tags.get("oneway") == "yes", "points": points})
        elif closed:
            kind = next((v for (k, value), v in AREAS.items() if tags.get(k) == value), None)
            points = line(way["nodes"], True)
            if kind and inside(points):
                areas.append({"id": way["id"], "kind": kind, "points": points})
    missing = sorted(set("NSEW") - set(approaches))
    return {"schema_version": 1, "name": name or " & ".join(sorted({a["street"] for a in approaches.values()})),
            "attribution": ATTRIBUTION, "license": "ODbL-1.0",
            "origin": {"lat": jlat, "lon": jlon, "osm_node": int(junction),
                       "signalised": jtags.get("highway") == "traffic_signals"},
            "rotation_deg": round(frame.rotation_deg, 3), "radius_m": radius,
            "approaches": approaches, "missing_approaches": missing,
            "roads": roads, "buildings": buildings, "areas": areas}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--name")
    parser.add_argument("--radius", type=float, default=160, help="half-width of the imported square, metres")
    parser.add_argument("--input", type=Path, help="use a saved .osm XML file instead of downloading")
    parser.add_argument("--save-osm", type=Path, help="also keep the downloaded raw .osm XML")
    parser.add_argument("--out", type=Path, default=ROOT / "config/map.json")
    args = parser.parse_args()
    if not 40 <= args.radius <= 400:
        parser.error("--radius must be 40..400 m")
    raw = args.input.read_bytes() if args.input else fetch(args.lat, args.lon, args.radius * 1.35)
    if args.save_osm:
        args.save_osm.parent.mkdir(parents=True, exist_ok=True)
        args.save_osm.write_bytes(raw)
    site = build(raw, args.lat, args.lon, args.name, args.radius)
    args.out.write_text(json.dumps(site, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{site['name']}: node {site['origin']['osm_node']} "
          f"({'signalised' if site['origin']['signalised'] else 'NOT tagged traffic_signals'}), "
          f"rotation {site['rotation_deg']}°")
    for key in "NESW":
        a = site["approaches"].get(key)
        print(f"  {key}: " + (f"{a['street']} ({a['highway']}, lanes={a['lanes']}, oneway={a['oneway']})" if a else "— none"))
    print(f"  {len(site['roads'])} roads, {len(site['buildings'])} buildings, {len(site['areas'])} areas -> {args.out}")


if __name__ == "__main__":
    main()
