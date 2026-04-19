from __future__ import annotations

from math import asin, atan2, cos, degrees, pi, radians, sin, sqrt


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius_km = 6371.0
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return radius_km * c


def destination_point(
    lat: float,
    lon: float,
    distance_km: float,
    bearing_deg: float,
) -> tuple[float, float]:
    radius_km = 6371.0
    angular_distance = distance_km / radius_km
    bearing = radians(bearing_deg)
    lat1 = radians(lat)
    lon1 = radians(lon)
    lat2 = asin(
        sin(lat1) * cos(angular_distance)
        + cos(lat1) * sin(angular_distance) * cos(bearing)
    )
    lon2 = lon1 + atan2(
        sin(bearing) * sin(angular_distance) * cos(lat1),
        cos(angular_distance) - sin(lat1) * sin(lat2),
    )
    lon2 = (lon2 + 3 * pi) % (2 * pi) - pi
    return degrees(lat2), degrees(lon2)
