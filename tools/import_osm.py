"""Build config/junction.json from OpenStreetMap data for one real signalized junction.

    python tools/import_osm.py --fetch --lat 23.04266 --lon 72.54912 --name navrangpura
    python tools/import_osm.py --name navrangpura          # re-run from the cached raw file

Geometry, carriageway direction and one-way structure come from OSM. Lane counts and widths
use OSM tags where mapped, otherwise per-class defaults, then data/osm/<name>_overrides.json.
Verify lanes against imagery: OSM rarely tags them in Indian cities.
"""
import argparse
from itertools import permutations
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulation.geometry import (bearing, convex_hull, distance_to_polyline, length, offset, point_at,
                                 resample, signed_angle, sub, unit)

MAJOR = {"trunk", "primary", "secondary", "tertiary"}
# Lanes per direction when OSM has no lane tags (Indian urban arterials, IRC 3.5 m lanes).
DEFAULT_LANES = {"trunk": 3, "primary": 3, "secondary": 2, "tertiary": 2}
LANE_WIDTH = 3.5
EXTENT = 120.0
CROSSWALK = 4.0
COMPASS = {"N": 0, "E": 90, "S": 180, "W": 270}
QUERY = """[out:json][timeout:100];(way["highway"](around:{r},{lat},{lon});way["building"](around:{r},{lat},{lon});
node["highway"="traffic_signals"](around:{r},{lat},{lon}););out geom;"""


def fetch(lat, lon, radius, path):
    body = urlencode({"data": QUERY.format(r=radius, lat=lat, lon=lon)}).encode()
    request = Request("https://overpass-api.de/api/interpreter", body, {"User-Agent": "traffic-digital-twin/1.0"})
    with urlopen(request, timeout=120) as response:
        path.write_bytes(response.read())


def project(lat0, lon0):
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    return lambda p: ((p["lon"] - lon0) * kx, (p["lat"] - lat0) * ky)


def lanes_tag(tags, direction):
    for key in (f"lanes:{direction}", "lanes") if direction else ("lanes",):
        try:
            return int(tags[key])
        except (KeyError, ValueError):
            continue
    return None


def carriageways(elements, xy):
    """Major-road polylines touching the junction, oriented outward, tagged in/out."""
    result = []
    for e in elements:
        tags = e.get("tags", {})
        if e["type"] != "way" or tags.get("highway") not in MAJOR or "geometry" not in e:
            continue
        points = [xy(p) for p in e["geometry"]]
        near_start, near_end = math.hypot(*points[0]) < 30, math.hypot(*points[-1]) < 30
        if near_start == near_end or length(points) < 60:
            continue  # Junction-internal loop, or not attached to this junction.
        forward_outward = near_start
        outward = points if near_start else points[::-1]
        oneway = tags.get("oneway")
        if oneway in {"yes", "1", "-1"}:
            outbound = forward_outward != (oneway == "-1")
            kinds = [("out" if outbound else "in", lanes_tag(tags, None))]
        else:
            kinds = [("out", lanes_tag(tags, "forward" if forward_outward else "backward")),
                     ("in", lanes_tag(tags, "backward" if forward_outward else "forward"))]
        direction = unit(sub(point_at(outward, 70), point_at(outward, 15)))
        for kind, lanes in kinds:
            result.append({"kind": kind, "points": outward, "direction": direction, "lanes": lanes,
                           "highway": tags["highway"], "name": tags.get("name"), "osm_id": e["id"],
                           "divided": oneway in {"yes", "1", "-1"}})
    return result


def group_arms(ways):
    arms = []
    for way in ways:
        for arm in arms:
            if abs(signed_angle(arm["direction"], way["direction"])) < math.radians(35):
                arm["ways"].append(way)
                break
        else:
            arms.append({"direction": way["direction"], "ways": [way]})
    return [arm for arm in arms if {w["kind"] for w in arm["ways"]} == {"in", "out"}]


def label(arms):
    labels = list(COMPASS)
    def error(assignment):
        return sum(abs((bearing(arm["direction"]) - COMPASS[name] + 180) % 360 - 180)
                   for arm, name in zip(arms, assignment))
    return min(permutations(labels, len(arms)), key=error)


def build(raw, lat, lon, name, overrides):
    xy = project(lat, lon)
    elements = raw["elements"]
    arms = group_arms(carriageways(elements, xy))
    if not 3 <= len(arms) <= 4:
        raise SystemExit(f"Expected a 3- or 4-arm junction, found {len(arms)} arms")
    result = []
    for arm, arm_id in zip(arms, label(arms)):
        inbound = next(w for w in arm["ways"] if w["kind"] == "in")
        outbound = next(w for w in arm["ways"] if w["kind"] == "out")
        extent = min(EXTENT, length(inbound["points"]), length(outbound["points"]))
        a, b = resample(inbound["points"], 0, extent), resample(outbound["points"], 0, extent)
        axis = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(a, b)]
        cls = inbound["highway"]
        source = {}
        lanes = {}
        for key, way in (("in_lanes", inbound), ("out_lanes", outbound)):
            lanes[key] = way["lanes"] or DEFAULT_LANES[cls]
            source[key] = "osm" if way["lanes"] else f"default:{cls}"
        if inbound["divided"]:
            far = [math.dist(p, q) for p, q in zip(a, b)][len(a) // 3:]
            separation = sum(far) / len(far)
            median = max(0.5, separation - (lanes["in_lanes"] + lanes["out_lanes"]) * LANE_WIDTH / 2)
        else:
            median = 0.0
        entry = {"id": arm_id, "name": inbound["name"] or outbound["name"] or arm_id, "highway": cls,
                 "bearing": round(bearing(arm["direction"]), 1), "lane_width": LANE_WIDTH,
                 "median": round(median, 2), **lanes, "extent": round(extent, 1),
                 "axis": [[round(x, 2), round(y, 2)] for x, y in axis],
                 "osm_ways": {"in": inbound["osm_id"], "out": outbound["osm_id"]}, "lane_source": source}
        for key, value in overrides.get(arm_id, {}).items():
            entry[key] = value
            entry["lane_source"][key] = "override"
        result.append(entry)
    for arm in result:
        arm["half_width"] = arm["median"] / 2 + max(arm["in_lanes"], arm["out_lanes"]) * arm["lane_width"]
    for arm in result:
        direction = unit(sub(point_at(arm["axis"], 40), point_at(arm["axis"], 0)))
        clear = 0.0
        for other in result:
            if other is arm:
                continue
            other_direction = unit(sub(point_at(other["axis"], 40), point_at(other["axis"], 0)))
            sine = abs(math.sin(signed_angle(direction, other_direction)))
            if sine > 0.5:  # Crossing road, not the opposite arm.
                cosine = abs(math.cos(signed_angle(direction, other_direction)))
                clear = max(clear, (other["half_width"] + arm["half_width"] * cosine) / sine)
        arm["stop"] = round(min(40.0, max(10.0, clear + CROSSWALK)), 1)
    order = sorted(result, key=lambda arm: arm["bearing"])  # Clockwise rotation from north.
    phases = [{"name": arm["id"], "arms": [arm["id"]], "green": "green_ns" if arm["id"] in "NS" else "green_ew"}
              for arm in order]
    corridors = [(arm["axis"], arm["half_width"] + 2) for arm in result]
    corners = []
    for arm in result:
        d = arm["stop"] - CROSSWALK
        edge = arm["median"] / 2 + max(arm["in_lanes"], arm["out_lanes"]) * arm["lane_width"]
        corners += offset([tuple(point_at(arm["axis"], d)), tuple(point_at(arm["axis"], d + 1))], edge)[:1]
        corners += offset([tuple(point_at(arm["axis"], d)), tuple(point_at(arm["axis"], d + 1))], -edge)[:1]
    box = convex_hull(corners)
    buildings = []
    for e in elements:
        tags = e.get("tags", {})
        if e["type"] != "way" or "building" not in tags or "geometry" not in e:
            continue
        footprint = [xy(p) for p in e["geometry"]][:-1]
        if any(distance_to_polyline(p, axis) < width for p in footprint for axis, width in corridors):
            continue  # Overlaps the modelled carriageways' corridor.
        height = None
        try:
            height = float(tags["height"]) if "height" in tags else float(tags["building:levels"]) * 3.2
        except (KeyError, ValueError):
            pass
        buildings.append({"footprint": [[round(x, 2), round(y, 2)] for x, y in footprint],
                          "height": height, "osm_id": e["id"]})
    signals = [[round(v, 2) for v in xy(e)] for e in elements
               if e["type"] == "node" and e.get("tags", {}).get("highway") == "traffic_signals"]
    return {"schema_version": 1, "name": name, "driving_side": "left",
            "center": {"lat": lat, "lon": lon},
            "source": {"geometry": "© OpenStreetMap contributors (ODbL)",
                       "osm_timestamp": raw.get("osm3s", {}).get("timestamp_osm_base")},
            "arms": result, "phases": phases, "box": [[round(x, 2), round(y, 2)] for x, y in box],
            "signals_osm": signals, "buildings": buildings}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="navrangpura")
    parser.add_argument("--title", default="120 Feet Ring Road × Drive-in Road, Navrangpura, Ahmedabad")
    parser.add_argument("--lat", type=float, default=23.04266)
    parser.add_argument("--lon", type=float, default=72.54912)
    parser.add_argument("--radius", type=int, default=160)
    parser.add_argument("--fetch", action="store_true", help="Download fresh data from the Overpass API")
    parser.add_argument("--output", type=Path, default=ROOT / "config/junction.json")
    args = parser.parse_args()
    raw_path = ROOT / f"data/osm/{args.name}_raw.json"
    if args.fetch:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        fetch(args.lat, args.lon, args.radius, raw_path)
    overrides_path = ROOT / f"data/osm/{args.name}_overrides.json"
    overrides = json.loads(overrides_path.read_text()) if overrides_path.exists() else {}
    overrides.pop("_comment", None)
    junction = build(json.loads(raw_path.read_text()), args.lat, args.lon, args.title, overrides)
    args.output.write_text(json.dumps(junction, indent=1))
    for arm in junction["arms"]:
        print(f"{arm['id']}: {arm['name']} bearing {arm['bearing']}° in {arm['in_lanes']} / out "
              f"{arm['out_lanes']} lanes, median {arm['median']} m, stop line {arm['stop']} m, "
              f"{arm['extent']} m modelled ({arm['lane_source']})")
    print(f"{len(junction['buildings'])} buildings, {len(junction['signals_osm'])} OSM signal nodes -> {args.output}")


if __name__ == "__main__":
    main()
