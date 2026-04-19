from __future__ import annotations

from functools import partial

from pydantic_ai import Agent

from app.config import AppConfig, project_root
from app.plugins.base import AgentPlugin, PluginCli
from app.plugins.route_planner.cli import main as cli_main
from app.plugins.route_planner.models import (
    PointToPointRouteRequest,
    RoundTripRouteRequest,
    RoutePlannerSettings,
    StravaSettings,
)
from app.plugins.route_planner.routing import RoutePlannerClient, RoutePlannerError
from app.plugins.route_planner.service import RoutePlannerService
from app.plugins.route_planner.strava import StravaError, StravaService


class RoutePlannerPlugin(AgentPlugin):
    name = "route_planner"

    def __init__(self, service: RoutePlannerService) -> None:
        self._service = service

    def register(self, agent: Agent[None, str]) -> None:
        agent.tool_plain(self.plan_point_to_point_route_gpx)
        agent.tool_plain(self.plan_round_trip_route_gpx)

    def build_cli(self) -> PluginCli:
        return partial(cli_main, self._service)

    def plan_point_to_point_route_gpx(
        self,
        start_location: str,
        end_location: str,
        profile: str = "gravel",
        route_name: str | None = None,
    ) -> str:
        """Build a GPX route between two named places.

        Args:
            start_location: Human-readable start place.
            end_location: Human-readable destination place.
            profile: Routing profile like road, gravel, trekking, or mountain.
            route_name: Optional GPX route name.
        """
        request = PointToPointRouteRequest(
            start_location=start_location,
            end_location=end_location,
            profile=profile,
            route_name=route_name,
        )
        return self._run(lambda: self._service.plan_point_to_point_route_gpx(request))

    def plan_round_trip_route_gpx(
        self,
        start_location: str,
        max_total_km: float,
        max_elevation_m: float | None = None,
        profile: str = "gravel",
        avoid_known_roads: bool = False,
    ) -> str:
        """Build a round-trip GPX route from one start point.

        Args:
            start_location: Human-readable start place.
            max_total_km: Maximum total route distance in km.
            max_elevation_m: Optional ascent cap in meters.
            profile: Routing profile like road, gravel, trekking, or mountain.
            avoid_known_roads: Prefer unfamiliar roads using cached Strava history.
        """
        request = RoundTripRouteRequest(
            start_location=start_location,
            max_total_km=max_total_km,
            max_elevation_m=max_elevation_m,
            profile=profile,
            avoid_known_roads=avoid_known_roads,
        )
        return self._run(lambda: self._service.plan_round_trip_route_gpx(request))

    def _run(self, operation) -> str:
        try:
            return operation()
        except (RoutePlannerError, StravaError, ValueError) as exc:
            return f"Route planner error: {exc}"


def build_plugin(config: AppConfig) -> RoutePlannerPlugin:
    route_settings = RoutePlannerSettings(
        brouter_url=config.route_planner_brouter_url,
        output_dir=project_root() / "output" / "route_planner",
        geocoder_user_agent="pydanticai-tool-agent/0.1",
    )
    route_client = RoutePlannerClient(
        brouter_url=route_settings.brouter_url,
        geocoder_user_agent=route_settings.geocoder_user_agent,
        output_dir=route_settings.output_dir,
    )

    strava_service = None
    if config.strava_data_dir:
        strava_service = StravaService(
            StravaSettings(
                client_id=config.strava_client_id,
                client_secret=config.strava_client_secret,
                redirect_uri=config.strava_redirect_uri,
                data_dir=config.strava_data_dir,
            )
        )

    return RoutePlannerPlugin(
        RoutePlannerService(
            route_client=route_client,
            strava_service=strava_service,
            public_base_url=config.public_base_url,
        )
    )
