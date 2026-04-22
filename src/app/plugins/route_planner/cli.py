from __future__ import annotations

import argparse
import json

from app.config import AppConfig, project_root
from app.plugins.route_planner.models import (
    PointToPointRouteRequest,
    RoundTripRouteRequest,
    StravaSettings,
)
from app.plugins.route_planner.routing import RoutePlannerClient, RoutePlannerError
from app.plugins.route_planner.service import RoutePlannerService
from app.plugins.route_planner.strava import StravaError, StravaService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="route-planner-tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    point_to_point = subparsers.add_parser("point-to-point")
    point_to_point.add_argument("--start-location", required=True)
    point_to_point.add_argument("--end-location", required=True)
    point_to_point.add_argument("--profile", default="gravel")
    point_to_point.add_argument("--route-name")

    round_trip = subparsers.add_parser("round-trip")
    round_trip.add_argument(
        "--start-latitude",
        "--start-lat",
        dest="start_latitude",
        type=float,
        required=True,
    )
    round_trip.add_argument(
        "--start-longitude",
        "--start-lon",
        dest="start_longitude",
        type=float,
        required=True,
    )
    round_trip.add_argument("--max-total-km", type=float, required=True)
    round_trip.add_argument("--max-elevation-m", type=float)
    round_trip.add_argument("--profile", default="gravel")
    round_trip.add_argument("--avoid-known-roads", action="store_true")

    subparsers.add_parser("strava-auth-url")

    strava_exchange = subparsers.add_parser("strava-exchange")
    strava_exchange.add_argument("--code-or-url", required=True)

    subparsers.add_parser("strava-sync")
    subparsers.add_parser("strava-athlete")

    return parser


def main(service: RoutePlannerService | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in {"point-to-point", "round-trip"}:
        service = service or build_service_from_env()

    try:
        if args.command == "point-to-point":
            print(
                service.plan_point_to_point_route_gpx(
                    PointToPointRouteRequest(
                        start_location=args.start_location,
                        end_location=args.end_location,
                        profile=args.profile,
                        route_name=args.route_name,
                    )
                )
            )
        elif args.command == "round-trip":
            print(
                service.plan_round_trip_route_gpx(
                    RoundTripRouteRequest(
                        start_latitude=args.start_latitude,
                        start_longitude=args.start_longitude,
                        max_total_km=args.max_total_km,
                        max_elevation_m=args.max_elevation_m,
                        profile=args.profile,
                        avoid_known_roads=args.avoid_known_roads,
                    )
                )
            )
        else:
            strava_service = build_strava_service_from_env()
            if args.command == "strava-auth-url":
                print(strava_service.build_authorize_url())
            elif args.command == "strava-exchange":
                code, scope = strava_service.extract_authorization_code(args.code_or_url)
                token_set = strava_service.exchange_authorization_code(code, scope)
                print(
                    json.dumps(
                        {
                            "athlete_id": token_set.athlete_id,
                            "expires_at": token_set.expires_at,
                            "scope": token_set.scope,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            elif args.command == "strava-sync":
                summary = strava_service.sync_all_activities()
                print(
                    json.dumps(
                        {
                            "total_activities": summary.total_activities,
                            "pages_fetched": summary.pages_fetched,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(
                    json.dumps(strava_service.get_authenticated_athlete(), indent=2, sort_keys=True)
                )
    except (RoutePlannerError, StravaError, ValueError) as exc:
        parser.error(str(exc))
    return 0


def build_service_from_env() -> RoutePlannerService:
    config = AppConfig.from_env()
    route_client = RoutePlannerClient(
        brouter_url=config.route_planner_brouter_url,
        geocoder_user_agent="pydanticai-tool-agent/0.1",
        output_dir=project_root() / "output" / "route_planner",
    )
    strava_service = None
    if config.strava_data_dir:
        strava_service = build_strava_service_from_env()
    return RoutePlannerService(
        route_client=route_client,
        strava_service=strava_service,
        public_base_url=config.public_base_url,
        brouter_web_url=config.route_planner_brouter_web_url,
    )


def build_strava_service_from_env() -> StravaService:
    config = AppConfig.from_env()
    return StravaService(
        StravaSettings(
            client_id=config.strava_client_id,
            client_secret=config.strava_client_secret,
            redirect_uri=config.strava_redirect_uri,
            data_dir=config.strava_data_dir,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
