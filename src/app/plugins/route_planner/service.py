from __future__ import annotations

import json
from pathlib import Path

from app.artifacts import artifact_store
from app.plugins.route_planner.models import PointToPointRouteRequest, RoundTripRouteRequest
from app.plugins.route_planner.round_trip import ELEVATION_PENALTY_WEIGHT, RoundTripPipeline
from app.plugins.route_planner.routing import RoutePlannerClient
from app.plugins.route_planner.strava import StravaService
from app.plugins.route_planner.strava_nogo import build_round_trip_strava_nogos


class RoutePlannerService:
    def __init__(
        self,
        route_client: RoutePlannerClient,
        strava_service: StravaService | None = None,
        public_base_url: str | None = None,
        brouter_web_url: str | None = None,
    ) -> None:
        self._route_client = route_client
        self._strava_service = strava_service
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else None
        self._brouter_web_url = brouter_web_url.rstrip("/") if brouter_web_url else None

    def plan_point_to_point_route_gpx(self, request: PointToPointRouteRequest) -> str:
        start = self._route_client.geocode_location(request.start_location)
        end = self._route_client.geocode_location(request.end_location)
        route = self._route_client.calculate_route(
            start_lat=start["lat"],
            start_lon=start["lon"],
            end_lat=end["lat"],
            end_lon=end["lon"],
            bike_profile=request.profile,
        )
        route_name = request.route_name or _default_point_to_point_name(start["name"], end["name"])
        gpx = self._route_client.export_route_gpx(
            [(start["lat"], start["lon"]), (end["lat"], end["lon"])],
            route_name=route_name,
            profile=request.profile,
        )
        artifact = artifact_store.register_file(Path(gpx["filepath"]), gpx["filename"])
        return _to_json(
            _compact_dict(
                {
                    "route": {
                        "name": route_name,
                        "profile": request.profile,
                        "start": _compact_location(start),
                        "end": _compact_location(end),
                        "distance_km": route.get("distance_km"),
                        "duration_hours": route.get("duration_hours"),
                        "ascent_m": route.get("elevation", {}).get("ascent_m"),
                        "descent_m": route.get("elevation", {}).get("descent_m"),
                    },
                    "gpx": {
                        "download_url": self._download_url(artifact.download_url),
                    },
                    "brouter_web_url": self._route_client.build_brouter_web_url(
                        waypoints=[(start["lat"], start["lon"]), (end["lat"], end["lon"])],
                        bike_profile=request.profile,
                        brouter_web_url=self._brouter_web_url,
                    ),
                }
            )
        )

    def plan_round_trip_route_gpx(self, request: RoundTripRouteRequest) -> str:
        start_coords = (request.start_latitude, request.start_longitude)
        strava_selection = None
        if request.avoid_known_roads:
            if self._strava_service is None:
                raise ValueError("Strava support is not configured for this deployment.")

            probe_radii = _derive_round_trip_radii(request.max_total_km)
            strava_selection = build_round_trip_strava_nogos(
                self._strava_service,
                self._route_client,
                start_coords,
                request.max_total_km,
                probe_radii,
            )
            pipeline = RoundTripPipeline(
                route_client=self._route_client,
                global_nogo_provider=lambda start_coords, max_total_km, radii_km: (
                    strava_selection.polygons
                ),
            )
        else:
            pipeline = RoundTripPipeline(route_client=self._route_client)

        result = pipeline.execute(
            start_coords=start_coords,
            max_total_km=request.max_total_km,
            max_elevation_m=request.max_elevation_m,
            profile=request.profile,
        )
        if not result.success or result.start_coords is None:
            raise ValueError(result.error or "Round-trip planning failed.")

        payload = {
            "start": {
                "name": result.start_name,
                "latitude": round(result.start_coords[0], 5),
                "longitude": round(result.start_coords[1], 5),
            },
            "request": _compact_dict(
                {
                    "max_total_km": request.max_total_km,
                    "max_elevation_m": request.max_elevation_m,
                    "profile": request.profile,
                    "avoid_known_roads": request.avoid_known_roads,
                }
            ),
            "options": [
                _compact_dict(
                    {
                        "id": candidate.candidate_id,
                        "distance_km": round(candidate.distance_km, 2),
                        "ascent_m": round(candidate.ascent_m, 2),
                        "score": round(candidate.total_score, 2),
                        "scoring": {
                            "overlap_penalty": round(candidate.overlap_penalty, 2),
                            "overlap_max_run_m": round(candidate.overlap_max_run_m, 1),
                            "overlap_total_m": round(candidate.overlap_total_m, 1),
                            "distance_penalty": round(candidate.distance_penalty, 2),
                            "under_distance_penalty": round(candidate.under_distance_penalty, 2),
                            "elevation_penalty": round(candidate.elevation_penalty, 2),
                            "weighted_elevation_penalty": round(
                                candidate.elevation_penalty * ELEVATION_PENALTY_WEIGHT, 2
                            ),
                            "distance_bonus": round(candidate.distance_bonus, 2),
                        },
                        "gpx": self._gpx_attachment(candidate.gpx_filepath, candidate.gpx_filename),
                    }
                )
                for candidate in result.selected_candidates
            ],
        }
        if strava_selection is not None:
            payload["avoid_known_roads"] = {
                "source": "strava",
                "candidate_activities": strava_selection.candidate_activities,
                "clipped_segments": strava_selection.clipped_segments,
                "polygons_used": len(strava_selection.polygons),
                "search_radius_km": round(strava_selection.search_radius_km, 2),
            }
        return _to_json(payload)

    def _gpx_attachment(self, filepath: str, filename: str) -> dict:
        artifact = artifact_store.register_file(Path(filepath), filename)
        return {
            "download_url": self._download_url(artifact.download_url),
        }

    def _download_url(self, relative_url: str) -> str:
        if self._public_base_url:
            return f"{self._public_base_url}{relative_url}"
        return relative_url


def _default_point_to_point_name(start_name: str, end_name: str) -> str:
    return f"{start_name.split(',')[0].strip()}_to_{end_name.split(',')[0].strip()}"


def _derive_round_trip_radii(max_total_km: float) -> list[float]:
    center = max_total_km * 0.20
    step = max(0.75, max_total_km / 30)
    radii = [
        max(0.5, round(center - step, 1)),
        max(0.5, round(center, 1)),
        max(0.5, round(center + step, 1)),
    ]
    return sorted(dict.fromkeys(radii))


def _compact_location(payload: dict) -> dict:
    return {
        "name": payload["name"],
        "latitude": round(float(payload["lat"]), 5),
        "longitude": round(float(payload["lon"]), 5),
    }


def _compact_dict(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value not in (None, [], {}, "")}


def _to_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
