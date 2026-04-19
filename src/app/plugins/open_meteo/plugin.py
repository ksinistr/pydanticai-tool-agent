from __future__ import annotations

from functools import partial
from typing import Literal

from pydantic_ai import Agent

from app.config import AppConfig
from app.plugins.base import AgentPlugin, PluginCli
from app.plugins.open_meteo.cli import main as cli_main
from app.plugins.open_meteo.client import OpenMeteoClient, OpenMeteoError
from app.plugins.open_meteo.models import ForecastRequest, LocationSearchRequest
from app.plugins.open_meteo.service import OpenMeteoService


class OpenMeteoPlugin(AgentPlugin):
    name = "open_meteo"

    def __init__(self, service: OpenMeteoService) -> None:
        self._service = service

    def register(self, agent: Agent[None, str]) -> None:
        agent.tool_plain(self.search_open_meteo_locations)
        agent.tool_plain(self.get_open_meteo_forecast)

    def build_cli(self) -> PluginCli:
        return partial(cli_main, self._service)

    def search_open_meteo_locations(
        self,
        query: str,
        country_code: str | None = None,
        limit: int = 5,
    ) -> str:
        """Search locations using Open-Meteo geocoding.

        Args:
            query: City, town, or postal code to search for.
            country_code: Optional ISO-3166-1 alpha-2 country code.
            limit: Maximum number of matches to return.
        """
        request = LocationSearchRequest(query=query, country_code=country_code, limit=limit)
        return self._run(lambda: self._service.search_locations(request))

    def get_open_meteo_forecast(
        self,
        latitude: float,
        longitude: float,
        period_count: int = 12,
        period_unit: Literal["hours", "days"] = "hours",
    ) -> str:
        """Get an hourly or daily weather forecast for a location.

        Args:
            latitude: Latitude of the forecast location.
            longitude: Longitude of the forecast location.
            period_count: Number of forecast periods to return.
            period_unit: Forecast granularity, either hours or days.
        """
        hours = period_count if period_unit == "hours" else None
        days = period_count if period_unit == "days" else None
        request = ForecastRequest(
            latitude=latitude,
            longitude=longitude,
            hours=hours,
            days=days,
        )
        return self._run(lambda: self._service.get_forecast(request))

    def _run(self, operation) -> str:
        try:
            return operation()
        except (OpenMeteoError, ValueError) as exc:
            return f"Open-Meteo error: {exc}"


def build_plugin(config: AppConfig) -> OpenMeteoPlugin:
    del config
    return OpenMeteoPlugin(OpenMeteoService(OpenMeteoClient()))
