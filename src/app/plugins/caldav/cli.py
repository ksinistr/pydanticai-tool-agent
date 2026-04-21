from __future__ import annotations

import argparse

from app.config import AppConfig
from app.plugins.caldav.client import CaldavClient, CaldavError
from app.plugins.caldav.models import (
    CaldavSettings,
    CreateEventRequest,
    DeleteEventRequest,
    GetEventRequest,
    ListEventsRequest,
    UpdateEventRequest,
)
from app.plugins.caldav.service import CaldavService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="caldav-tool")
    resources = parser.add_subparsers(dest="resource", required=True)

    calendars = resources.add_parser("calendars")
    calendar_commands = calendars.add_subparsers(dest="command", required=True)
    calendar_commands.add_parser("list")

    events = resources.add_parser("events")
    event_commands = events.add_subparsers(dest="command", required=True)

    list_events = event_commands.add_parser("list")
    list_events.add_argument("--calendar-id", required=True)
    list_events.add_argument("--from", dest="from_datetime", required=True)
    list_events.add_argument("--to", dest="to_datetime", required=True)

    get_event = event_commands.add_parser("get")
    get_event.add_argument("--calendar-id", required=True)
    get_event.add_argument("--event-id", required=True)

    create_event = event_commands.add_parser("create")
    create_event.add_argument("--calendar-id", required=True)
    create_event.add_argument("--title", required=True)
    create_event.add_argument("--start")
    create_event.add_argument("--end")
    create_event.add_argument("--date")
    create_event.add_argument("--description", default="")

    update_event = event_commands.add_parser("update")
    update_event.add_argument("--calendar-id", required=True)
    update_event.add_argument("--event-id", required=True)
    update_event.add_argument("--title")
    update_event.add_argument("--start")
    update_event.add_argument("--end")
    update_event.add_argument("--date")
    update_event.add_argument("--description")

    delete_event = event_commands.add_parser("delete")
    delete_event.add_argument("--calendar-id", required=True)
    delete_event.add_argument("--event-id", required=True)

    return parser


def main(service: CaldavService | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args()
    service = service or build_service_from_env()

    try:
        if args.resource == "calendars":
            print(service.list_calendars())
        elif args.command == "list":
            print(
                service.list_events(
                    ListEventsRequest(
                        calendar_id=args.calendar_id,
                        from_datetime=args.from_datetime,
                        to_datetime=args.to_datetime,
                    )
                )
            )
        elif args.command == "get":
            print(
                service.get_event(
                    GetEventRequest(
                        calendar_id=args.calendar_id,
                        event_id=args.event_id,
                    )
                )
            )
        elif args.command == "create":
            print(
                service.create_event(
                    CreateEventRequest(
                        calendar_id=args.calendar_id,
                        title=args.title,
                        start=args.start,
                        end=args.end,
                        date=args.date,
                        description=args.description,
                    )
                )
            )
        elif args.command == "update":
            print(
                service.update_event(
                    UpdateEventRequest(
                        calendar_id=args.calendar_id,
                        event_id=args.event_id,
                        title=args.title,
                        start=args.start,
                        end=args.end,
                        date=args.date,
                        description=args.description,
                    )
                )
            )
        else:
            print(
                service.delete_event(
                    DeleteEventRequest(
                        calendar_id=args.calendar_id,
                        event_id=args.event_id,
                    )
                )
            )
    except (CaldavError, ValueError) as exc:
        parser.error(str(exc))

    return 0


def build_service_from_env() -> CaldavService:
    config = AppConfig.from_env()
    settings = CaldavSettings(
        server_url=config.caldav_server_url,
        username=config.caldav_username,
        password=config.caldav_password,
        insecure_skip_verify=config.caldav_insecure_skip_verify,
    )
    return CaldavService(CaldavClient(settings))


if __name__ == "__main__":
    raise SystemExit(main())
