from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.plugins.get_time.models import TimeRequest, TimeResponse


class GetTimeService:
    def get_current_time(self, request: TimeRequest) -> TimeResponse:
        current_time = datetime.now().astimezone()

        if request.timezone_name:
            try:
                current_time = current_time.astimezone(ZoneInfo(request.timezone_name))
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"Unknown timezone: {request.timezone_name}") from exc

        timezone_name = request.timezone_name or current_time.tzname() or "local"

        return TimeResponse(
            iso_datetime=current_time.isoformat(timespec="seconds"),
            display=f"{current_time.strftime('%Y-%m-%d %H:%M:%S')} ({timezone_name})",
            timezone_name=timezone_name,
        )

