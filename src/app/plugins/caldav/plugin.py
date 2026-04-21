from __future__ import annotations

from datetime import UTC, date, datetime, time, tzinfo
from functools import partial
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_ai import Agent, ModelRetry

from app.config import AppConfig
from app.plugins.base import AgentPlugin, PluginCli
from app.plugins.caldav.cli import main as cli_main
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


class CaldavPlugin(AgentPlugin):
    name = "caldav"

    def __init__(
        self,
        service: CaldavService,
        user_timezone: str | None = None,
    ) -> None:
        self._service = service
        self._default_timezone = _resolve_timezone(user_timezone)

    def register(self, agent: Agent[None, str]) -> None:
        agent.tool_plain(self.list_caldav_calendars)
        agent.tool_plain(self.list_caldav_events)
        agent.tool_plain(self.get_caldav_event)
        agent.tool_plain(self.create_caldav_event)
        agent.tool_plain(self.update_caldav_event)
        agent.tool_plain(self.delete_caldav_event)

    def build_cli(self) -> PluginCli:
        return partial(cli_main, self._service)

    def list_caldav_calendars(self) -> str:
        return self._run(self._service.list_calendars)

    def list_caldav_events(
        self,
        calendar_id: str,
        from_datetime: str,
        to_datetime: str,
    ) -> str:
        """List calendar events in a date range.

        Args:
            calendar_id: Calendar identifier such as `personal`.
            from_datetime: Start boundary. Accepts `YYYY-MM-DD`,
                `YYYY-MM-DDTHH:MM:SS`, or offset-aware ISO 8601 like
                `2026-04-01T00:00:00+03:00`.
            to_datetime: End boundary. Accepts the same formats. If no offset
                is included, `USER_TIMEZONE` is assumed. Plain dates expand to
                the full local day.
        """
        try:
            request = ListEventsRequest(
                calendar_id=calendar_id,
                from_datetime=_normalize_datetime_input(
                    from_datetime,
                    timezone=self._default_timezone,
                    end_of_day=False,
                ),
                to_datetime=_normalize_datetime_input(
                    to_datetime,
                    timezone=self._default_timezone,
                    end_of_day=True,
                ),
            )
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return self._run(lambda: self._service.list_events(request))

    def get_caldav_event(self, calendar_id: str, event_id: str) -> str:
        request = GetEventRequest(calendar_id=calendar_id, event_id=event_id)
        return self._run(lambda: self._service.get_event(request))

    def create_caldav_event(
        self,
        calendar_id: str,
        title: str,
        start: str | None = None,
        end: str | None = None,
        date: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create a calendar event.

        Args:
            calendar_id: Calendar identifier such as `personal`.
            title: Event title.
            start: Timed event start. Accepts `YYYY-MM-DDTHH:MM:SS` with or
                without offset, or plain date.
            end: Timed event end. Accepts the same formats as `start`.
            date: All-day event date in `YYYY-MM-DD` form.
            description: Optional description.
        """
        try:
            request = CreateEventRequest(
                calendar_id=calendar_id,
                title=title,
                start=_normalize_optional_datetime_input(
                    start,
                    timezone=self._default_timezone,
                    end_of_day=False,
                ),
                end=_normalize_optional_datetime_input(
                    end,
                    timezone=self._default_timezone,
                    end_of_day=True,
                ),
                date=date,
                description=description or "",
            )
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return self._run(lambda: self._service.create_event(request))

    def update_caldav_event(
        self,
        calendar_id: str,
        event_id: str,
        title: str | None = None,
        start: str | None = None,
        end: str | None = None,
        date: str | None = None,
        description: str | None = None,
    ) -> str:
        """Update a calendar event.

        Args:
            calendar_id: Calendar identifier such as `personal`.
            event_id: Event filename such as `2026-03-25-team-sync.ics`.
            title: Optional new title.
            start: Optional timed start. Accepts the same formats as create.
            end: Optional timed end. Accepts the same formats as create.
            date: Optional all-day date in `YYYY-MM-DD` form.
            description: Optional description.
        """
        try:
            request = UpdateEventRequest(
                calendar_id=calendar_id,
                event_id=event_id,
                title=title,
                start=_normalize_optional_datetime_input(
                    start,
                    timezone=self._default_timezone,
                    end_of_day=False,
                ),
                end=_normalize_optional_datetime_input(
                    end,
                    timezone=self._default_timezone,
                    end_of_day=True,
                ),
                date=date,
                description=description,
            )
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return self._run(lambda: self._service.update_event(request))

    def delete_caldav_event(self, calendar_id: str, event_id: str) -> str:
        request = DeleteEventRequest(calendar_id=calendar_id, event_id=event_id)
        return self._run(lambda: self._service.delete_event(request))

    def _run(self, operation) -> str:
        try:
            return operation()
        except (CaldavError, ValueError) as exc:
            return f"CalDAV error: {exc}"


def build_plugin(config: AppConfig) -> CaldavPlugin:
    settings = CaldavSettings(
        server_url=config.caldav_server_url,
        username=config.caldav_username,
        password=config.caldav_password,
        insecure_skip_verify=config.caldav_insecure_skip_verify,
    )
    return CaldavPlugin(CaldavService(CaldavClient(settings)), user_timezone=config.user_timezone)


def _normalize_optional_datetime_input(
    value: str | None,
    timezone: tzinfo,
    end_of_day: bool,
) -> str | None:
    if value is None:
        return None
    return _normalize_datetime_input(value, timezone=timezone, end_of_day=end_of_day)


def _normalize_datetime_input(
    value: str,
    timezone: tzinfo,
    end_of_day: bool,
) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(_datetime_format_hint())

    if "T" not in cleaned and " " not in cleaned:
        try:
            parsed_date = date.fromisoformat(cleaned)
        except ValueError as exc:
            raise ValueError(_datetime_format_hint()) from exc
        parsed_datetime = datetime.combine(
            parsed_date,
            time(23, 59, 59) if end_of_day else time.min,
            tzinfo=timezone,
        )
        return parsed_datetime.isoformat(timespec="seconds")

    try:
        parsed_datetime = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(_datetime_format_hint()) from exc

    if parsed_datetime.tzinfo is None:
        parsed_datetime = parsed_datetime.replace(tzinfo=timezone)
    return parsed_datetime.isoformat(timespec="seconds")


def _datetime_format_hint() -> str:
    return (
        "Use ISO 8601 datetime like 2026-03-25T09:00:00Z or plain date like 2026-03-27. "
        "If no timezone offset is provided, USER_TIMEZONE is assumed."
    )


def _resolve_timezone(value: str | None) -> tzinfo:
    if value is None:
        return UTC
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return UTC
