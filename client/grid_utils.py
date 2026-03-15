# FT8 Propagation Tracker — grid validation and field/coordinate math
from __future__ import annotations

import math
import re

GRID_4_RE = re.compile(r"^[A-Ra-r]{2}[0-9]{2}$")
EARTH_RADIUS_KM = 6371.0


def validate_grid(s: str) -> bool:
    if not s or len(s) < 4:
        return False
    return bool(GRID_4_RE.match(s.strip().upper()[:4]))


def truncate_grid(s: str) -> str:
    """Return 4-char Maidenhead; empty if invalid."""
    s = (s or "").strip().upper()
    if len(s) >= 4 and GRID_4_RE.match(s[:4]):
        return s[:4]
    return ""


def field_center(field: str) -> tuple[float, float]:
    """2-char field (e.g. 'PM') -> (lat_deg, lon_deg)."""
    if not field or len(field) < 2:
        return (0.0, 0.0)
    c0, c1 = field[0].upper(), field[1].upper()
    if not ("A" <= c0 <= "R" and "A" <= c1 <= "R"):
        return (0.0, 0.0)
    lon_idx = ord(c0) - ord("A")
    lat_idx = ord(c1) - ord("A")
    lon = lon_idx * 20 - 180 + 10
    lat = lat_idx * 10 - 90 + 5
    return (lat, lon)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from (lat1,lon1) to (lat2,lon2); 0°=North, clockwise, [0, 360)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    theta = math.degrees(math.atan2(x, y))
    return theta % 360.0
