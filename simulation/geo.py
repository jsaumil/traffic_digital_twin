"""WGS84 <-> local twin metres. Local tangent plane at the junction, rotated so streets align with X/Y."""
import math

EARTH_RADIUS = 6378137.0


class LocalFrame:
    def __init__(self, lat, lon, rotation_deg=0.0):
        self.lat, self.lon, self.rotation_deg = lat, lon, rotation_deg
        self._cos_lat = math.cos(math.radians(lat))
        self._rot = math.radians(rotation_deg)

    def east_north(self, lat, lon):
        """Unrotated east/north metres from the origin (equirectangular, accurate to ~1 km)."""
        return (math.radians(lon - self.lon) * EARTH_RADIUS * self._cos_lat,
                math.radians(lat - self.lat) * EARTH_RADIUS)

    def to_local(self, lat, lon):
        """Twin XY: east/north rotated counter-clockwise by rotation_deg."""
        e, n = self.east_north(lat, lon)
        c, s = math.cos(self._rot), math.sin(self._rot)
        return e * c - n * s, e * s + n * c

    def to_wgs84(self, x, y):
        c, s = math.cos(-self._rot), math.sin(-self._rot)
        e, n = x * c - y * s, x * s + y * c
        return (self.lat + math.degrees(n / EARTH_RADIUS),
                self.lon + math.degrees(e / (EARTH_RADIUS * self._cos_lat)))

    @classmethod
    def from_map(cls, site):
        origin = site["origin"]
        return cls(origin["lat"], origin["lon"], site["rotation_deg"])
