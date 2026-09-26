"""Grid ↔ geo conversions (Step 5 geo-tagging).

The companion computer reports survivors/hazards as occupancy-grid cells.
To geo-tag them we anchor the grid to WGS84 using, in order of preference:

1. an explicit ``mission.origin`` supplied in the map packet,
2. an anchor derived by co-registration — the drone's GPS position at the
   moment it reports a grid position (origin = gps − grid_offset),
3. otherwise nothing: coordinates stay ``UNKNOWN`` / ``GEO: PENDING``.

``cell_size_m`` is a configuration value (metres per grid cell), not a
measurement, and is rendered as such in the UI.
"""

from __future__ import annotations

import math

M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lon(lat: float) -> float:
    return M_PER_DEG_LAT * max(0.01, math.cos(math.radians(lat)))


def grid_to_latlon(origin: tuple[float, float], cell_size_m: float,
                   gx: float, gy: float) -> tuple[float, float]:
    """Grid x → east, grid y → north (documented axis convention)."""
    lat0, lon0 = origin
    lat = lat0 + (gy * cell_size_m) / M_PER_DEG_LAT
    lon = lon0 + (gx * cell_size_m) / _m_per_deg_lon(lat0)
    return lat, lon


def latlon_to_grid(origin: tuple[float, float], cell_size_m: float,
                   lat: float, lon: float) -> tuple[int, int]:
    lat0, lon0 = origin
    gy = (lat - lat0) * M_PER_DEG_LAT / cell_size_m
    gx = (lon - lon0) * _m_per_deg_lon(lat0) / cell_size_m
    return int(round(gx)), int(round(gy))


def origin_from_anchor(drone_lat: float, drone_lon: float,
                       drone_gx: float, drone_gy: float,
                       cell_size_m: float) -> tuple[float, float]:
    """Co-registration anchor: origin such that grid_to_latlon(origin)
    returns the drone's current GPS position for its grid cell."""
    lat0 = drone_lat - (drone_gy * cell_size_m) / M_PER_DEG_LAT
    lon0 = drone_lon - (drone_gx * cell_size_m) / _m_per_deg_lon(drone_lat)
    return lat0, lon0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def polygon_area_m2(poly: list[tuple[float, float]]) -> float:
    """Shoelace formula on a local equirectangular projection."""
    if not poly or len(poly) < 3:
        return 0.0
    lat0 = sum(p[0] for p in poly) / len(poly)
    kx = _m_per_deg_lon(lat0)
    ky = M_PER_DEG_LAT
    pts = [(lon * kx, lat * ky) for lat, lon in poly]
    area = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def point_in_polygon(lat: float, lon: float,
                     poly: list[tuple[float, float]]) -> bool:
    """Ray-casting; poly = [(lat, lon), ...]."""
    if not poly or len(poly) < 3:
        return True   # no area loaded → everything counts
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        lati, loni = poly[i]
        latj, lonj = poly[j]
        if ((lati > lat) != (latj > lat)) and \
                (lon < (lonj - loni) * (lat - lati) / (latj - lati or 1e-12) + loni):
            inside = not inside
        j = i
    return inside
