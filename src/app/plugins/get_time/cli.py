from __future__ import annotations

import argparse

from app.plugins.get_time.models import TimeRequest
from app.plugins.get_time.service import GetTimeService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="get-time-tool")
    parser.add_argument("--timezone", dest="timezone_name")
    parser.add_argument("--json", action="store_true")
    return parser


def main(service: GetTimeService | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args()
    service = service or GetTimeService()

    try:
        response = service.get_current_time(TimeRequest(timezone_name=args.timezone_name))
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(response.model_dump_json(indent=2))
    else:
        print(response.display)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
