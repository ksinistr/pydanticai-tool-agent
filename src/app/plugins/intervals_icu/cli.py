from __future__ import annotations

import argparse

from app.config import AppConfig
from app.plugins.intervals_icu.client import IntervalsIcuClient, IntervalsIcuError
from app.plugins.intervals_icu.models import ActivitiesQuery, WellnessQuery
from app.plugins.intervals_icu.service import IntervalsIcuService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="intervals-icu-tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fitness = subparsers.add_parser("fitness-status")
    fitness.add_argument("--date")

    wellness = subparsers.add_parser("wellness")
    wellness.add_argument("--date")
    wellness.add_argument("--oldest")
    wellness.add_argument("--newest")
    wellness.add_argument("--limit", type=int, default=7)

    weekly_load_progress = subparsers.add_parser("weekly-load-progress")
    weekly_load_progress.add_argument("--week-start")
    weekly_load_progress.add_argument("--week-end")

    activities = subparsers.add_parser("activities")
    activities.add_argument("--oldest", required=True)
    activities.add_argument("--newest")
    activities.add_argument("--limit", type=int, default=10)

    activity = subparsers.add_parser("activity")
    activity.add_argument("--activity-id", required=True)
    activity.add_argument("--include-intervals", action="store_true")

    return parser


def main(service: IntervalsIcuService | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args()
    service = service or build_service_from_env()

    try:
        if args.command == "fitness-status":
            print(service.get_fitness_status(date_value=args.date))
        elif args.command == "wellness":
            query = WellnessQuery(
                date=args.date,
                oldest=args.oldest,
                newest=args.newest,
                limit=args.limit,
            )
            print(service.get_wellness(query))
        elif args.command == "weekly-load-progress":
            print(
                service.get_weekly_load_progress(
                    week_start=args.week_start,
                    week_end=args.week_end,
                )
            )
        elif args.command == "activities":
            query = ActivitiesQuery(oldest=args.oldest, newest=args.newest, limit=args.limit)
            print(service.list_activities(query))
        else:
            print(
                service.get_activity(
                    activity_id=args.activity_id,
                    include_intervals=args.include_intervals,
                )
            )
    except (IntervalsIcuError, ValueError) as exc:
        parser.error(str(exc))

    return 0


def build_service_from_env() -> IntervalsIcuService:
    config = AppConfig.from_env()
    client = IntervalsIcuClient(
        athlete_id=config.require_intervals_icu_athlete_id(),
        api_key=config.require_intervals_icu_api_key(),
        base_url=config.intervals_icu_base_url,
    )
    return IntervalsIcuService(client)


if __name__ == "__main__":
    raise SystemExit(main())
