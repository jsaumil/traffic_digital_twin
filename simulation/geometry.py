"""Planar polyline helpers. Local ENU metres: x east, y north. Pure Python (Blender-safe)."""
import math


def add(a, b):
    return a[0] + b[0], a[1] + b[1]


def sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def mul(a, n):
    return a[0] * n, a[1] * n


def unit(a):
    length = math.hypot(*a)
    return (a[0] / length, a[1] / length) if length > 1e-12 else (0.0, 0.0)


def left_normal(direction):
    return -direction[1], direction[0]


def length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def resample(points, start, end, step=2.0):
    """Points every `step` metres between arc lengths start..end (both included)."""
    count = max(1, round((end - start) / step))
    return [point_at(points, start + (end - start) * i / count) for i in range(count + 1)]


def point_at(points, s):
    if s <= 0:
        direction = unit(sub(points[1], points[0]))
        return add(points[0], mul(direction, s))
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        segment = math.dist(a, b)
        if travelled + segment >= s and segment > 0:
            t = (s - travelled) / segment
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        travelled += segment
    direction = unit(sub(points[-1], points[-2]))
    return add(points[-1], mul(direction, s - travelled))


def offset(points, distance):
    """Offset to the left of travel direction by `distance` (negative = right), mitred joints."""
    result = []
    for i, point in enumerate(points):
        before = unit(sub(point, points[i - 1])) if i else None
        after = unit(sub(points[i + 1], point)) if i + 1 < len(points) else None
        tangent = unit(add(before or after, after or before))
        normal = left_normal(tangent)
        reference = left_normal(after or before)
        scale = 1 / max(0.5, normal[0] * reference[0] + normal[1] * reference[1])
        result.append(add(point, mul(normal, distance * scale)))
    return result


def bearing(direction):
    """Compass bearing in degrees (0 = north, 90 = east)."""
    return math.degrees(math.atan2(direction[0], direction[1])) % 360


def signed_angle(a, b):
    """Counter-clockwise angle from direction a to direction b, radians in (-pi, pi]."""
    return math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])


def convex_hull(points):
    points = sorted(set(points))
    if len(points) < 3:
        return points
    def half(sequence):
        hull = []
        for p in sequence:
            while len(hull) >= 2 and ((hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1]) -
                                      (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0])) <= 0:
                hull.pop()
            hull.append(p)
        return hull[:-1]
    return half(points) + half(reversed(points))


def distance_to_polyline(point, points):
    best = math.inf
    for a, b in zip(points, points[1:]):
        ab, ap = sub(b, a), sub(point, a)
        t = max(0, min(1, (ab[0] * ap[0] + ab[1] * ap[1]) / max(1e-12, ab[0] ** 2 + ab[1] ** 2)))
        best = min(best, math.dist(point, add(a, mul(ab, t))))
    return best
