from __future__ import annotations

from functools import partial

from pydantic_ai import Agent

from app.config import AppConfig
from app.plugins.base import AgentPlugin, PluginCli
from app.plugins.intervals_icu.cli import main as cli_main
from app.plugins.intervals_icu.client import IntervalsIcuClient, IntervalsIcuError
from app.plugins.intervals_icu.models import ActivitiesQuery, WellnessQuery
from app.plugins.intervals_icu.service import IntervalsIcuService


class IntervalsIcuPlugin(AgentPlugin):
    name = "intervals_icu"

    def __init__(self, service: IntervalsIcuService) -> None:
        self._service = service

    def register(self, agent: Agent[None, str]) -> None:
        agent.tool_plain(self.get_intervals_wellness)
        agent.tool_plain(self.get_intervals_fitness_status)
        agent.tool_plain(self.get_intervals_weekly_load_progress)
        agent.tool_plain(self.list_intervals_activities)
        agent.tool_plain(self.get_intervals_activity)

    def build_cli(self) -> PluginCli:
        return partial(cli_main, self._service)

    def get_intervals_wellness(
        self,
        date: str | None = None,
        oldest: str | None = None,
        newest: str | None = None,
        limit: int = 7,
    ) -> str:
        """Get wellness for one day or a short date range.

        Args:
            date: Local ISO-8601 day, for example 2026-04-19.
            oldest: Oldest local ISO-8601 day in the range.
            newest: Newest local ISO-8601 day in the range.
            limit: Maximum number of records to return for range queries.
        """
        query = WellnessQuery(date=date, oldest=oldest, newest=newest, limit=limit)
        return self._run(lambda: self._service.get_wellness(query))

    def list_intervals_activities(
        self,
        oldest: str,
        newest: str | None = None,
        limit: int = 10,
    ) -> str:
        """List athlete activities in a date range.

        Args:
            oldest: Oldest local ISO-8601 day in the range.
            newest: Newest local ISO-8601 day in the range.
            limit: Maximum number of activities to return.
        """
        query = ActivitiesQuery(oldest=oldest, newest=newest, limit=limit)
        return self._run(lambda: self._service.list_activities(query))

    def get_intervals_fitness_status(self, date: str | None = None) -> str:
        """Get CTL, ATL, readiness, fatigue, and inferred form from wellness data.

        Args:
            date: Local ISO-8601 day, for example 2026-04-19. Defaults to today.
        """
        return self._run(lambda: self._service.get_fitness_status(date))

    def get_intervals_weekly_load_progress(
        self,
        week_start: str | None = None,
        week_end: str | None = None,
    ) -> str:
        """Compare planned weekly load against completed weekly load.

        Args:
            week_start: ISO-8601 week start day. Defaults to the current week start.
            week_end: ISO-8601 week end day. Defaults to six days after week_start.
        """
        return self._run(lambda: self._service.get_weekly_load_progress(week_start, week_end))

    def get_intervals_activity(self, activity_id: str, include_intervals: bool = False) -> str:
        """Get one activity by id from Intervals.icu.

        Args:
            activity_id: Activity id from Intervals.icu.
            include_intervals: Include interval data when available.
        """
        return self._run(lambda: self._service.get_activity(activity_id, include_intervals))

    def _run(self, operation) -> str:
        try:
            return operation()
        except (IntervalsIcuError, ValueError) as exc:
            return f"Intervals.icu error: {exc}"


def build_plugin(config: AppConfig) -> IntervalsIcuPlugin:
    client = IntervalsIcuClient(
        athlete_id=config.require_intervals_icu_athlete_id(),
        api_key=config.require_intervals_icu_api_key(),
        base_url=config.intervals_icu_base_url,
    )
    return IntervalsIcuPlugin(IntervalsIcuService(client))
