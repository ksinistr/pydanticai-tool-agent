from __future__ import annotations

import json
from dataclasses import dataclass

from app.plugins.route_planner.models import (
    PointToPointRouteRequest,
    RoundTripRouteRequest,
    StravaSettings,
)
from app.plugins.route_planner.round_trip import RoundTripCandidate, RoundTripResult
from app.plugins.route_planner.service import RoutePlannerService
from app.plugins.route_planner.strava import StravaService


class FakeRoutePlannerClient:
    def geocode_location(self, location_name: str) -> dict:
        mapping = {
            "Paphos, Cyprus": {"name": "Paphos, Cyprus", "lat": 34.775, "lon": 32.424},
            "Limassol, Cyprus": {"name": "Limassol, Cyprus", "lat": 34.684, "lon": 33.038},
        }
        return mapping[location_name]

    def calculate_route(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        bike_profile: str = "trekking",
        include_geometry: bool = False,
        alternative_idx: int = 0,
        nogos=None,
        polygons=None,
    ) -> dict:
        assert (start_lat, start_lon) == (34.775, 32.424)
        assert (end_lat, end_lon) == (34.684, 33.038)
        assert bike_profile == "gravel"
        return {
            "distance_km": 71.2,
            "duration_hours": 4.15,
            "elevation": {"ascent_m": 810, "descent_m": 760},
        }

    def export_route_gpx(
        self,
        waypoints: list[tuple[float, float]],
        route_name: str,
        profile: str,
    ) -> dict:
        assert len(waypoints) == 2
        assert route_name == "coast_ride"
        assert profile == "gravel"
        return {
            "filepath": "/tmp/coast_ride.gpx",
            "filename": "coast_ride.gpx",
        }


@dataclass
class FakeStravaSelection:
    candidate_activities: int
    clipped_segments: int
    polygons: list[object]
    search_radius_km: float


class FakeStravaService:
    def __init__(self) -> None:
        self.used = False


class FakeRoundTripPipeline:
    def __init__(self, route_client, global_nogo_provider=None) -> None:
        self._global_nogo_provider = global_nogo_provider

    def execute(
        self,
        start_location: str,
        max_total_km: float,
        max_elevation_m: float | None,
        profile: str,
    ) -> RoundTripResult:
        assert start_location == "Paphos, Cyprus"
        assert max_total_km == 60
        assert max_elevation_m == 800
        assert profile == "gravel"
        if self._global_nogo_provider is not None:
            polygons = self._global_nogo_provider(
                (34.775, 32.424), max_total_km, [11.3, 12.0, 12.7]
            )
            assert len(polygons) == 2
        candidate = RoundTripCandidate(
            candidate_id="RT03",
            attempt_type="soft_nogo",
            radius_km=12.0,
            base_bearing_deg=90.0,
            control_points=[],
            control_bearings_deg=[],
            waypoints=[(34.775, 32.424), (34.81, 32.52), (34.75, 32.61), (34.775, 32.424)],
            distance_km=58.6,
            ascent_m=792,
            total_score=0.94,
            gpx_filepath="/tmp/rt03.gpx",
            gpx_filename="rt03.gpx",
        )
        return RoundTripResult(
            success=True,
            start_name="Paphos, Cyprus",
            start_coords=(34.775, 32.424),
            max_total_km=max_total_km,
            max_elevation_m=max_elevation_m,
            profile=profile,
            radii_km=[11.3, 12.0, 12.7],
            selected_candidates=[candidate],
        )


def test_route_planner_service_builds_point_to_point_payload(monkeypatch) -> None:
    import app.plugins.route_planner.service as service_module

    class FakeArtifact:
        filename = "coast_ride.gpx"
        download_url = "/downloads/fake-point"

    monkeypatch.setattr(
        service_module.artifact_store, "register_file", lambda path, filename=None: FakeArtifact()
    )
    service = RoutePlannerService(
        FakeRoutePlannerClient(),
        public_base_url="https://agent.example.test",
    )

    payload = json.loads(
        service.plan_point_to_point_route_gpx(
            PointToPointRouteRequest(
                start_location="Paphos, Cyprus",
                end_location="Limassol, Cyprus",
                profile="gravel",
                route_name="coast_ride",
            )
        )
    )

    assert payload == {
        "gpx": {
            "download_url": "https://agent.example.test/downloads/fake-point",
        },
        "route": {
            "name": "coast_ride",
            "profile": "gravel",
            "start": {
                "latitude": 34.775,
                "longitude": 32.424,
                "name": "Paphos, Cyprus",
            },
            "end": {
                "latitude": 34.684,
                "longitude": 33.038,
                "name": "Limassol, Cyprus",
            },
            "distance_km": 71.2,
            "duration_hours": 4.15,
            "ascent_m": 810,
            "descent_m": 760,
        },
    }


def test_route_planner_service_adds_strava_avoidance_summary(monkeypatch) -> None:
    import app.plugins.route_planner.service as service_module

    monkeypatch.setattr(service_module, "RoundTripPipeline", FakeRoundTripPipeline)
    monkeypatch.setattr(
        service_module,
        "build_round_trip_strava_nogos",
        lambda strava_service, route_client, start_coords, max_total_km, radii_km: (
            FakeStravaSelection(
                candidate_activities=27,
                clipped_segments=14,
                polygons=[object(), object()],
                search_radius_km=9.5,
            )
        ),
    )
    monkeypatch.setattr(
        service_module.artifact_store,
        "register_file",
        lambda path, filename=None: type(
            "FakeArtifact",
            (),
            {
                "filename": filename or "route.gpx",
                "download_url": f"/downloads/{filename or 'route.gpx'}",
            },
        )(),
    )

    service = RoutePlannerService(FakeRoutePlannerClient(), FakeStravaService())

    payload = json.loads(
        service.plan_round_trip_route_gpx(
            RoundTripRouteRequest(
                start_location="Paphos, Cyprus",
                max_total_km=60,
                max_elevation_m=800,
                profile="gravel",
                avoid_known_roads=True,
            )
        )
    )

    assert payload["start"] == {
        "name": "Paphos, Cyprus",
        "latitude": 34.775,
        "longitude": 32.424,
    }
    assert payload["request"] == {
        "avoid_known_roads": True,
        "max_elevation_m": 800.0,
        "max_total_km": 60.0,
        "profile": "gravel",
    }
    assert payload["avoid_known_roads"] == {
        "candidate_activities": 27,
        "clipped_segments": 14,
        "polygons_used": 2,
        "search_radius_km": 9.5,
        "source": "strava",
    }
    assert payload["options"][0]["id"] == "RT03"
    assert payload["options"][0]["gpx"] == {"download_url": "/downloads/rt03.gpx"}


def test_strava_service_builds_authorize_url_and_extracts_code(tmp_path) -> None:
    service = StravaService(
        StravaSettings(
            client_id="12345",
            client_secret="secret",
            redirect_uri="http://localhost/exchange_token",
            data_dir=tmp_path / "strava",
        )
    )

    authorize_url = service.build_authorize_url()
    code, scope = service.extract_authorization_code(
        "http://localhost/exchange_token?state=pydanticai-tool-agent&code=xyz789&scope=activity:read_all"
    )

    assert "client_id=12345" in authorize_url
    assert "redirect_uri=http%3A%2F%2Flocalhost%2Fexchange_token" in authorize_url
    assert "scope=activity%3Aread_all" in authorize_url
    assert code == "xyz789"
    assert scope == "activity:read_all"
