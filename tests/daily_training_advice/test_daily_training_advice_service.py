from __future__ import annotations

import asyncio
from types import SimpleNamespace
from zoneinfo import ZoneInfoNotFoundError

from app.daily_training_advice.models import (
    DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
    DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
    DailyTrainingAdviceContext,
    DailyTrainingAdviceSettings,
    DailyTrainingAdviceSetup,
    DailyTrainingAdviceStructuredOutput,
)
from app.daily_training_advice.service import DailyTrainingAdviceService


class FakeAgent:
    def __init__(self, output: DailyTrainingAdviceStructuredOutput | None = None) -> None:
        self.output = output or _make_structured_output()
        self.prompts: list[str] = []

    async def run(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(output=self.output)


class FakeContextBuilder:
    def __init__(self, context: DailyTrainingAdviceContext) -> None:
        self.context = context
        self.calls: list[DailyTrainingAdviceSettings] = []

    def build(self, settings: DailyTrainingAdviceSettings) -> DailyTrainingAdviceContext:
        self.calls.append(settings)
        return self.context


class InvalidTimezoneContextBuilder:
    def build(self, settings: DailyTrainingAdviceSettings) -> DailyTrainingAdviceContext:
        raise ZoneInfoNotFoundError(settings.timezone)


def test_service_returns_setup_error_when_required_variables_are_missing() -> None:
    service = DailyTrainingAdviceService(
        agent=FakeAgent(),
        context_builder=FakeContextBuilder(_make_context()),
        setup=DailyTrainingAdviceSetup(settings=None, missing_variables=("MORNING_REPORT_LATITUDE",)),
        default_language="en",
    )

    reply = asyncio.run(service.generate())

    assert "MORNING_REPORT_LATITUDE" in reply


def test_service_renders_structured_agent_output() -> None:
    settings = DailyTrainingAdviceSettings(
        latitude=34.7765,
        longitude=32.4241,
        timezone="Asia/Nicosia",
        language="ru",
        holidays_calendar_id=DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
        vacation_calendar_id=DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
    )
    agent = FakeAgent()
    context_builder = FakeContextBuilder(_make_context(language="ru", day_type="holiday"))
    service = DailyTrainingAdviceService(
        agent=agent,
        context_builder=context_builder,
        setup=DailyTrainingAdviceSetup(settings=settings, missing_variables=()),
        default_language="ru",
    )

    reply = asyncio.run(service.generate())

    assert context_builder.calls == [settings]
    assert "**Completed Today**" in reply
    assert "**Remaining Today**" in reply
    assert "GREEN: Stable recovery and enough room left in the day." in reply
    assert '"today_summary": {' in agent.prompts[0]
    assert '"remaining_weather_hours": [' in agent.prompts[0]


def test_service_returns_conservative_message_when_intervals_are_unavailable() -> None:
    agent = FakeAgent()
    service = DailyTrainingAdviceService(
        agent=agent,
        context_builder=FakeContextBuilder(_make_context(intervals_error="intervals down")),
        setup=DailyTrainingAdviceSetup(
            settings=DailyTrainingAdviceSettings(
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
    service = DailyTrainingAdviceService(
        agent=FakeAgent(),
        context_builder=FakeContextBuilder(
            _make_context(
                intervals_error="intervals down",
                calendar_error="calendar down",
                weather_error="weather down",
            )
        ),
        setup=DailyTrainingAdviceSetup(
            settings=DailyTrainingAdviceSettings(
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
    service = DailyTrainingAdviceService(
        agent=FakeAgent(),
        context_builder=InvalidTimezoneContextBuilder(),
        setup=DailyTrainingAdviceSetup(
            settings=DailyTrainingAdviceSettings(
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
) -> DailyTrainingAdviceContext:
    return DailyTrainingAdviceContext(
        generated_at="2026-04-20T16:30+03:00",
        current_time="16:30",
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
        recent_activities=[
            {
                "date": "2026-04-19",
                "sport": "Ride",
                "training_load": 81,
            },
            {
                "date": "2026-04-20",
                "sport": "Ride",
                "training_load": 25,
                "start_time": "08:05",
            },
        ],
        today_activities=[
            {
                "date": "2026-04-20",
                "sport": "Ride",
                "training_load": 25,
                "start_time": "08:05",
            }
        ],
        today_summary={
            "count": 1,
            "sports": ["Ride"],
            "training_load": 25,
            "last_activity_time": "08:05",
        },
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
        remaining_weather_hours=[
            {
                "time": "2026-04-20T18:00+03:00",
                "weather": "clear sky",
                "temp": 21.8,
                "wind_speed": 12.4,
            }
        ],
    )


def _make_structured_output() -> DailyTrainingAdviceStructuredOutput:
    return DailyTrainingAdviceStructuredOutput(
        data_freshness=[
            "Intervals, weather, and calendars refreshed for the current day.",
        ],
        readiness_level="green",
        readiness_summary="Stable recovery and enough room left in the day.",
        completed_today=[
            "One short ride is already done, so the main aerobic box is partially checked.",
        ],
        remaining_today=[
            "If the legs still feel calm, keep any extra ride short and easy before dinner.",
        ],
        recovery=[
            "Add 10 minutes of mobility after work instead of extra intensity.",
        ],
        fueling_hydration=[
            "Replace the fluids from the first ride and eat a normal carb-forward dinner.",
        ],
        workday_actions=[
            "Protect one clear training window and keep the rest of the evening light.",
        ],
        caution=[
            "Do not stack a second hard session on top of the morning load.",
        ],
    )
