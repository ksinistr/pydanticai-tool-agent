from __future__ import annotations

import asyncio
from types import SimpleNamespace
from zoneinfo import ZoneInfoNotFoundError

from app.morning_report.models import (
    DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
    DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
    MorningReportContext,
    MorningReportSettings,
    MorningReportSetup,
    MorningReportStructuredOutput,
)
from app.morning_report.service import MorningReportService


class FakeAgent:
    def __init__(self, output: MorningReportStructuredOutput | None = None) -> None:
        self.output = output or _make_structured_output()
        self.prompts: list[str] = []

    async def run(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(output=self.output)


class FakeContextBuilder:
    def __init__(self, context: MorningReportContext) -> None:
        self.context = context
        self.calls: list[MorningReportSettings] = []

    def build(self, settings: MorningReportSettings) -> MorningReportContext:
        self.calls.append(settings)
        return self.context


class InvalidTimezoneContextBuilder:
    def build(self, settings: MorningReportSettings) -> MorningReportContext:
        raise ZoneInfoNotFoundError(settings.timezone)


def test_service_returns_setup_error_when_required_variables_are_missing() -> None:
    service = MorningReportService(
        agent=FakeAgent(),
        context_builder=FakeContextBuilder(_make_context()),
        setup=MorningReportSetup(settings=None, missing_variables=("MORNING_REPORT_LATITUDE",)),
        default_language="en",
    )

    reply = asyncio.run(service.generate())

    assert "MORNING_REPORT_LATITUDE" in reply


def test_service_renders_structured_agent_output() -> None:
    settings = MorningReportSettings(
        latitude=34.7765,
        longitude=32.4241,
        timezone="Asia/Nicosia",
        language="ru",
        holidays_calendar_id=DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
        vacation_calendar_id=DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
    )
    agent = FakeAgent()
    context_builder = FakeContextBuilder(_make_context(language="ru", day_type="holiday"))
    service = MorningReportService(
        agent=agent,
        context_builder=context_builder,
        setup=MorningReportSetup(settings=settings, missing_variables=()),
        default_language="ru",
    )

    reply = asyncio.run(service.generate())

    assert context_builder.calls == [settings]
    assert "**Data Freshness**" in reply
    assert "**Readiness**" in reply
    assert "GREEN: Stable recovery and full day availability." in reply
    assert '"calendar_status": "ok"' in agent.prompts[0]
    assert '"workday_constraints_apply": false' in agent.prompts[0]


def test_service_returns_conservative_message_when_intervals_are_unavailable() -> None:
    agent = FakeAgent()
    service = MorningReportService(
        agent=agent,
        context_builder=FakeContextBuilder(_make_context(intervals_error="intervals down")),
        setup=MorningReportSetup(
            settings=MorningReportSettings(
                latitude=34.7765,
                longitude=32.4241,
                timezone="Asia/Nicosia",
                language="en",
                holidays_calendar_id=DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
                vacation_calendar_id=DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
            ),
            missing_variables=(),
        ),
        default_language="en",
    )

    reply = asyncio.run(service.generate())

    assert "conservative" in reply
    assert "Intervals.icu" in reply
    assert not agent.prompts


def test_service_returns_source_errors_when_all_fetches_fail() -> None:
    service = MorningReportService(
        agent=FakeAgent(),
        context_builder=FakeContextBuilder(
            _make_context(
                intervals_error="intervals down",
                calendar_error="calendar down",
                weather_error="weather down",
            )
        ),
        setup=MorningReportSetup(
            settings=MorningReportSettings(
                latitude=34.7765,
                longitude=32.4241,
                timezone="Asia/Nicosia",
                language="en",
                holidays_calendar_id=DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
                vacation_calendar_id=DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
            ),
            missing_variables=(),
        ),
        default_language="en",
    )

    reply = asyncio.run(service.generate())

    assert "intervals down" in reply
    assert "weather down" in reply
    assert "calendar down" in reply


def test_service_returns_timezone_setup_error_for_invalid_timezone() -> None:
    service = MorningReportService(
        agent=FakeAgent(),
        context_builder=InvalidTimezoneContextBuilder(),
        setup=MorningReportSetup(
            settings=MorningReportSettings(
                latitude=34.7765,
                longitude=32.4241,
                timezone="Mars/Base",
                language="en",
                holidays_calendar_id=DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
                vacation_calendar_id=DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
            ),
            missing_variables=(),
        ),
        default_language="en",
    )

    reply = asyncio.run(service.generate())

    assert "USER_TIMEZONE" in reply


def _make_context(
    language: str = "en",
    day_type: str = "workday",
    intervals_error: str | None = None,
    calendar_error: str | None = None,
    weather_error: str | None = None,
) -> MorningReportContext:
    return MorningReportContext(
        generated_at="2026-04-20T06:30+03:00",
        anchor_date="2026-04-20",
        weekday="Monday",
        day_type=day_type,
        workday_constraints_apply=day_type == "workday",
        timezone="Asia/Nicosia",
        language=language,
        latitude=34.7765,
        longitude=32.4241,
        history_from="2026-04-14",
        history_to="2026-04-20",
        calendar_from="2026-04-20T00:00:00+03:00",
        calendar_to="2026-04-27T00:00:00+03:00",
        intervals_error=intervals_error,
        calendar_error=calendar_error,
        weather_error=weather_error,
        activities=[
            {
                "date": "2026-04-19",
                "sport": "Ride",
                "training_load": 81,
            }
        ],
        wellness=[
            {
                "date": "2026-04-20",
                "readiness": 71,
                "sleep_score": 84,
            }
        ],
        holidays=[
            {
                "title": "Holiday",
                "all_day": True,
                "start_date": "2026-04-20",
                "end_date": "2026-04-20",
            }
        ]
        if day_type == "holiday"
        else [],
        vacation=[],
        weather_hours=[
            {
                "time": "2026-04-20T06:00",
                "weather": "clear sky",
                "temp": 18.6,
                "wind_speed": 8.1,
            }
        ],
    )


def _make_structured_output() -> MorningReportStructuredOutput:
    return MorningReportStructuredOutput(
        data_freshness=[
            "Intervals, weather, and calendars refreshed for the morning window.",
        ],
        readiness_level="green",
        readiness_summary="Stable recovery and full day availability.",
        weather_impact=[
            "Best outdoor window is early morning before the wind builds.",
        ],
        today_plan=[
            "Ride 90 minutes easy endurance and stop while the legs still feel smooth.",
        ],
        recovery=[
            "Add 10 minutes of easy mobility in the evening.",
        ],
        fueling_hydration=[
            "Start hydrated and take one bottle plus a small carb snack.",
        ],
        workday_actions=[
            "Regular workday constraints do not apply today, so keep only one optional walk break.",
        ],
        caution=[
            "Back off if heart rate drifts high for easy power.",
        ],
    )
