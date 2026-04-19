from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx


BROUTER_PROFILES = {
    "road": "fastbike",
    "gravel": "quaelnix-gravel",
    "trekking": "trekking",
    "mountain": "mtb",
    "mtb": "mtb",
    "safety": "safety",
    "shortest": "shortest",
}

BROUTER_MAX_QUERY_CHARS = 7000
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class RoutePlannerError(RuntimeError):
    pass


@dataclass(slots=True)
class BrouterNogoCircle:
    latitude: float
    longitude: float
    radius_m: float
    weight: float | None = None


@dataclass(slots=True)
class BrouterPolygonNogo:
    points: list[tuple[float, float]]
    weight: float | None = None


class RoutePlannerClient:
    def __init__(
        self,
        brouter_url: str,
        geocoder_user_agent: str,
        output_dir: Path,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._brouter_url = brouter_url.rstrip("/")
        self._geocoder_user_agent = geocoder_user_agent
        self._output_dir = output_dir
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.Client(timeout=60.0)

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()

    def geocode_location(self, location_name: str) -> dict:
        try:
            response = self._http_client.get(
                NOMINATIM_URL,
                params={
                    "q": location_name,
                    "format": "json",
                    "limit": 1,
                },
                headers={"User-Agent": self._geocoder_user_agent},
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RoutePlannerError(f"Geocoding failed for {location_name}: {exc}") from exc

        payload = response.json()
        if not isinstance(payload, list) or not payload:
            raise RoutePlannerError(f"Could not find location: {location_name}")

        result = payload[0]
        return {
            "name": str(result.get("display_name", location_name))[:120],
            "lat": float(result["lat"]),
            "lon": float(result["lon"]),
        }

    def calculate_route(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        bike_profile: str = "trekking",
        include_geometry: bool = False,
        alternative_idx: int = 0,
        nogos: list[BrouterNogoCircle] | None = None,
        polygons: list[BrouterPolygonNogo] | None = None,
    ) -> dict:
        profile = BROUTER_PROFILES.get(bike_profile, "trekking")
        lonlats = f"{start_lon},{start_lat}|{end_lon},{end_lat}"
        return self._calculate_brouter_route(
            lonlats=lonlats,
            profile=profile,
            include_geometry=include_geometry,
            alternative_idx=alternative_idx,
            nogos=nogos,
            polygons=polygons,
        )

    def calculate_route_with_waypoints(
        self,
        waypoints: list[tuple[float, float]],
        bike_profile: str = "trekking",
        include_geometry: bool = False,
        alternative_idx: int = 0,
        nogos: list[BrouterNogoCircle] | None = None,
        polygons: list[BrouterPolygonNogo] | None = None,
    ) -> dict:
        if len(waypoints) < 2:
            raise RoutePlannerError("At least 2 waypoints are required.")

        profile = BROUTER_PROFILES.get(bike_profile, "trekking")
        lonlats = "|".join(f"{lon},{lat}" for lat, lon in waypoints)
        return self._calculate_brouter_route(
            lonlats=lonlats,
            profile=profile,
            include_geometry=include_geometry,
            alternative_idx=alternative_idx,
            nogos=nogos,
            polygons=polygons,
        )

    def export_route_gpx(
        self,
        waypoints: list[tuple[float, float]],
        route_name: str,
        profile: str,
    ) -> dict:
        if len(waypoints) < 2:
            raise RoutePlannerError("At least 2 waypoints are required.")

        self._output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in route_name).strip("_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_name or 'route'}_{timestamp}.gpx"
        filepath = self._output_dir / filename
        lonlats = "|".join(f"{lon},{lat}" for lat, lon in waypoints)
        profile_name = BROUTER_PROFILES.get(profile, "trekking")

        try:
            response = self._http_client.get(
                self._brouter_url,
                params={
                    "lonlats": lonlats,
                    "profile": profile_name,
                    "alternativeidx": 0,
                    "format": "gpx",
                },
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            raise RoutePlannerError(f"GPX export request failed: {exc}") from exc

        if response.status_code != 200:
            raise RoutePlannerError(
                f"BRouter GPX export failed with HTTP {response.status_code}: {response.text[:300]}"
            )

        filepath.write_text(response.text)
        return {
            "filepath": str(filepath),
            "filename": filename,
        }

    def estimate_brouter_query_length(
        self,
        lonlats: str,
        profile: str,
        alternative_idx: int = 0,
        nogos: list[BrouterNogoCircle] | None = None,
        polygons: list[BrouterPolygonNogo] | None = None,
    ) -> int:
        params = _build_brouter_params(
            lonlats=lonlats,
            profile=profile,
            alternative_idx=alternative_idx,
            nogos=nogos,
            polygons=polygons,
        )
        return len(f"{self._brouter_url}?{urlencode(params)}")

    def fit_brouter_polygons_to_query_budget(
        self,
        lonlats: str,
        profile: str,
        alternative_idx: int = 0,
        nogos: list[BrouterNogoCircle] | None = None,
        polygons: list[BrouterPolygonNogo] | None = None,
        max_query_chars: int = BROUTER_MAX_QUERY_CHARS,
    ) -> tuple[list[BrouterPolygonNogo], int, int]:
        if not polygons:
            query_chars = self.estimate_brouter_query_length(
                lonlats=lonlats,
                profile=profile,
                alternative_idx=alternative_idx,
                nogos=nogos,
                polygons=None,
            )
            return [], query_chars, 0

        kept_polygons: list[BrouterPolygonNogo] = []
        for polygon in polygons:
            candidate_polygons = kept_polygons + [polygon]
            query_chars = self.estimate_brouter_query_length(
                lonlats=lonlats,
                profile=profile,
                alternative_idx=alternative_idx,
                nogos=nogos,
                polygons=candidate_polygons,
            )
            if query_chars <= max_query_chars:
                kept_polygons.append(polygon)

        query_chars = self.estimate_brouter_query_length(
            lonlats=lonlats,
            profile=profile,
            alternative_idx=alternative_idx,
            nogos=nogos,
            polygons=kept_polygons or None,
        )
        return kept_polygons, query_chars, len(polygons) - len(kept_polygons)

    def _calculate_brouter_route(
        self,
        lonlats: str,
        profile: str,
        include_geometry: bool,
        alternative_idx: int,
        nogos: list[BrouterNogoCircle] | None,
        polygons: list[BrouterPolygonNogo] | None,
    ) -> dict:
        fitted_polygons, query_chars, trimmed_polygons = self.fit_brouter_polygons_to_query_budget(
            lonlats=lonlats,
            profile=profile,
            alternative_idx=alternative_idx,
            nogos=nogos,
            polygons=polygons,
        )

        try:
            response = self._http_client.get(
                self._brouter_url,
                params=_build_brouter_params(
                    lonlats=lonlats,
                    profile=profile,
                    alternative_idx=alternative_idx,
                    nogos=nogos,
                    polygons=fitted_polygons or None,
                ),
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            raise RoutePlannerError(f"BRouter request failed: {exc}") from exc

        if response.status_code != 200:
            raise RoutePlannerError(f"BRouter error {response.status_code}: {response.text[:500]}")

        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("features"):
            raise RoutePlannerError("No route found between the specified points.")

        feature = payload["features"][0]
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        track_length = float(properties.get("track-length", 0))
        total_time = float(properties.get("total-time", 0))
        total_ascend = float(properties.get("filtered ascend", properties.get("plain-ascend", 0)))
        total_descend = abs(float(properties.get("filtered descend", properties.get("plain-descend", 0))))

        result = {
            "profile": profile,
            "distance_km": round(track_length / 1000, 2),
            "duration_hours": round(total_time / 3600, 2),
            "elevation": {
                "ascent_m": round(total_ascend, 2),
                "descent_m": round(total_descend, 2),
            },
            "waypoints_count": len(coordinates),
            "nogo_polygons_used": len(fitted_polygons),
            "nogo_polygons_trimmed": trimmed_polygons,
            "estimated_query_chars": query_chars,
        }
        if coordinates:
            result["start_point"] = {"lon": coordinates[0][0], "lat": coordinates[0][1]}
            result["end_point"] = {"lon": coordinates[-1][0], "lat": coordinates[-1][1]}
        if include_geometry:
            result["geometry"] = geometry
        return result


def _build_brouter_params(
    lonlats: str,
    profile: str,
    alternative_idx: int = 0,
    nogos: list[BrouterNogoCircle] | None = None,
    polygons: list[BrouterPolygonNogo] | None = None,
) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "lonlats": lonlats,
        "profile": profile,
        "alternativeidx": alternative_idx,
        "format": "geojson",
    }
    nogos_value = _serialize_brouter_nogos(nogos)
    if nogos_value:
        params["nogos"] = nogos_value
    polygons_value = _serialize_brouter_polygons(polygons)
    if polygons_value:
        params["polygons"] = polygons_value
    return params


def _format_brouter_number(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _serialize_brouter_nogos(nogos: list[BrouterNogoCircle] | None) -> str | None:
    if not nogos:
        return None
    encoded_nogos: list[str] = []
    for nogo in nogos:
        parts = [
            _format_brouter_number(nogo.longitude),
            _format_brouter_number(nogo.latitude),
            _format_brouter_number(nogo.radius_m),
        ]
        if nogo.weight is not None:
            parts.append(_format_brouter_number(nogo.weight))
        encoded_nogos.append(",".join(parts))
    return "|".join(encoded_nogos)


def _serialize_brouter_polygons(polygons: list[BrouterPolygonNogo] | None) -> str | None:
    if not polygons:
        return None
    encoded_polygons: list[str] = []
    for polygon in polygons:
        if len(polygon.points) < 3:
            continue
        points = list(polygon.points)
        if points[0] != points[-1]:
            points.append(points[0])
        parts: list[str] = []
        for latitude, longitude in points:
            parts.append(_format_brouter_number(longitude))
            parts.append(_format_brouter_number(latitude))
        if polygon.weight is not None:
            parts.append(_format_brouter_number(polygon.weight))
        encoded_polygons.append(",".join(parts))
    if not encoded_polygons:
        return None
    return "|".join(encoded_polygons)
