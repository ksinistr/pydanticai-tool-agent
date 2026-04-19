from __future__ import annotations

import argparse

from app.plugins.open_meteo.client import OpenMeteoClient, OpenMeteoError
from app.plugins.open_meteo.models import ForecastRequest, LocationSearchRequest
from app.plugins.open_meteo.service import OpenMeteoService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="open-meteo-tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--country-code")
    search.add_argument("--limit", type=int, default=5)

    forecast = subparsers.add_parser("forecast")
    forecast.add_argument("--latitude", type=float, required=True)
    forecast.add_argument("--longitude", type=float, required=True)
    forecast.add_argument("--hours", type=int)
    forecast.add_argument("--days", type=int)

    return parser


def main(service: OpenMeteoService | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args()
    service = service or OpenMeteoService(OpenMeteoClient())

    try:
        if args.command == "search":
            request = LocationSearchRequest(
                query=args.query,
                country_code=args.country_code,
                limit=args.limit,
            )
            print(service.search_locations(request))
        else:
            request = ForecastRequest(
                latitude=args.latitude,
                longitude=args.longitude,
                hours=args.hours,
                days=args.days,
            )
            print(service.get_forecast(request))
    except (OpenMeteoError, ValueError) as exc:
        parser.error(str(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
