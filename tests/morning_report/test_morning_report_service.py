from __future__ import annotations

import asyncio
from types import SimpleNamespace
from zoneinfo import ZoneInfoNotFoundError

from app.morning_report.models import MorningReportContext, MorningReportSettings, MorningReportSetup
from app.morning_report.service import MorningReportService


class FakeAgent:
    def __init__(self, output: str = "report ready") -> None:
        self.output = output
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


def test_service_uses_agent_when_intervals_data_is_available() -> None:
    settings = MorningReportSettings(
        latitude=34.7765,
        longitude=32.4241,
        timezone="Asia/Nicosia",
        language="ru",
    )
    agent = FakeAgent(output="custom note")
    context_builder = FakeContextBuilder(_make_context(language="ru", weather_error="weather down"))
    service = MorningReportService(
        agent=agent,
        context_builder=context_builder,
        setup=MorningReportSetup(settings=settings, missing_variables=()),
        default_language="ru",
    )

    reply = asyncio.run(service.generate())

    assert reply == "custom note"
    assert context_builder.calls == [settings]
    assert "Language: ru" in agent.prompts[0]
    assert '"weather_status": "weather down"' in agent.prompts[0]


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
            _make_context(intervals_error="intervals down", weather_error="weather down")
        ),
        setup=MorningReportSetup(
            settings=MorningReportSettings(
                latitude=34.7765,
                longitude=32.4241,
                timezone="Asia/Nicosia",
                language="en",
            ),
            missing_variables=(),
        ),
        default_language="en",
    )

    reply = asyncio.run(service.generate())

    assert "intervals down" in reply
    assert "weather down" in reply


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
            ),
            missing_variables=(),
        ),
        default_language="en",
    )

    reply = asyncio.run(service.generate())

    assert "MORNING_REPORT_TIMEZONE" in reply


def _make_context(
    language: str = "en",
    intervals_error: str | None = None,
    weather_error: str | None = None,
) -> MorningReportContext:
    return MorningReportContext(
        generated_at="2026-04-20T06:30+03:00",
        anchor_date="2026-04-20",
        weekday="Monday",
        day_type="workday",
        timezone="Asia/Nicosia",
        language=language,
        latitude=34.7765,
        longitude=32.4241,
        history_from="2026-04-14",
        history_to="2026-04-20",
        intervals_error=intervals_error,
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
        weather_hours=[
            {
                "time": "2026-04-20T06:00",
                "weather": "clear sky",
                "temp": 18.6,
                "wind_speed": 8.1,
            }
        ],
    )
