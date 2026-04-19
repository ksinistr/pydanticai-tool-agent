from __future__ import annotations

from functools import partial

from pydantic_ai import Agent, ModelRetry

from app.config import AppConfig
from app.plugins.base import AgentPlugin, PluginCli
from app.plugins.get_time.cli import main as cli_main
from app.plugins.get_time.models import TimeRequest
from app.plugins.get_time.service import GetTimeService


class GetTimePlugin(AgentPlugin):
    name = "get_time"

    def __init__(self, service: GetTimeService) -> None:
        self._service = service

    def register(self, agent: Agent[None, str]) -> None:
        agent.tool_plain(self.get_time)

    def build_cli(self) -> PluginCli:
        return partial(cli_main, self._service)

    def get_time(self, timezone_name: str | None = None) -> str:
        """Return the current date and time.

        Args:
            timezone_name: Optional IANA timezone such as UTC or Europe/Nicosia.
        """
        try:
            response = self._service.get_current_time(TimeRequest(timezone_name=timezone_name))
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc

        return response.display


def build_plugin(config: AppConfig) -> GetTimePlugin:
    del config
    return GetTimePlugin(GetTimeService())

