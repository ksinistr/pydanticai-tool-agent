from __future__ import annotations

from functools import partial

from pydantic_ai import Agent

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

    def __init__(self, service: CaldavService) -> None:
        self._service = service

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
        request = ListEventsRequest(
            calendar_id=calendar_id,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
        )
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
        request = CreateEventRequest(
            calendar_id=calendar_id,
            title=title,
            start=start,
            end=end,
            date=date,
            description=description or "",
        )
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
        request = UpdateEventRequest(
            calendar_id=calendar_id,
            event_id=event_id,
            title=title,
            start=start,
            end=end,
            date=date,
            description=description,
        )
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
    return CaldavPlugin(CaldavService(CaldavClient(settings)))
