from __future__ import annotations

import asyncio
import json
from typing import Protocol
from zoneinfo import ZoneInfoNotFoundError

from pydantic_ai import Agent

from app.morning_report.models import (
    MorningReportContext,
    MorningReportSettings,
    MorningReportSetup,
)


class MorningReportContextBuilderProtocol(Protocol):
    def build(self, settings: MorningReportSettings) -> MorningReportContext: ...


class MorningReportService:
    def __init__(
        self,
        agent: Agent[None, str],
        context_builder: MorningReportContextBuilderProtocol,
        setup: MorningReportSetup,
        default_language: str | None = None,
    ) -> None:
        self._agent = agent
        self._context_builder = context_builder
        self._setup = setup
        self._default_language = default_language

    async def generate(self) -> str:
        if self._setup.missing_variables:
            return _setup_error_message(self._setup.missing_variables, self._default_language)

        settings = self._setup.settings
        if settings is None:
            return _setup_error_message((), self._default_language)

        try:
            context = await asyncio.to_thread(self._context_builder.build, settings)
        except ZoneInfoNotFoundError:
            return _timezone_error_message(settings.language)
        if not context.has_intervals() and not context.has_weather():
            return _both_sources_failed_message(context)
        if not context.has_intervals():
            return _intervals_failed_message(context)

        result = await self._agent.run(_build_prompt(context))
        return result.output


def _build_prompt(context: MorningReportContext) -> str:
    payload = {
        "generated_at": context.generated_at,
        "anchor_date": context.anchor_date,
        "weekday": context.weekday,
        "day_type": context.day_type,
        "timezone": context.timezone,
        "language": context.language,
        "location": {
            "latitude": context.latitude,
            "longitude": context.longitude,
        },
        "history_window": {
            "from": context.history_from,
            "to": context.history_to,
        },
        "intervals_status": "ok" if context.has_intervals() else context.intervals_error,
        "weather_status": "ok" if context.has_weather() else context.weather_error,
        "wellness": context.wellness,
        "activities": context.activities,
        "weather_hours": context.weather_hours,
    }

    return "\n\n".join(
        [
            f"Language: {context.language}",
            (
                "Write a short coach note for this morning. "
                "Vary the opening. Make the note sound individual rather than templated. "
                "State a clear readiness verdict, mention the best ride window if weather allows, "
                "recommend one concrete session for today, and end with one caution or limit."
            ),
            "Use the context exactly as provided:",
            json.dumps(payload, indent=2, ensure_ascii=False),
        ]
    )


def _setup_error_message(missing_variables: tuple[str, ...], language: str | None) -> str:
    joined = ", ".join(missing_variables) if missing_variables else "morning report settings"
    if _is_russian(language):
        return f"Утренний отчет пока не настроен. Нужны значения: {joined}."
    return f"Morning report is not configured yet. Missing: {joined}."


def _timezone_error_message(language: str | None) -> str:
    if _is_russian(language):
        return "Утренний отчет не настроен: MORNING_REPORT_TIMEZONE задан некорректно."
    return "Morning report is not configured correctly: MORNING_REPORT_TIMEZONE is invalid."


def _both_sources_failed_message(context: MorningReportContext) -> str:
    if _is_russian(context.language):
        return (
            "Утренний отчет не смог получить свежие данные. "
            f"Intervals.icu: {context.intervals_error}. "
            f"Погода: {context.weather_error}."
        )
    return (
        "Morning report could not fetch fresh data. "
        f"Intervals.icu: {context.intervals_error}. "
        f"Weather: {context.weather_error}."
    )


def _intervals_failed_message(context: MorningReportContext) -> str:
    if _is_russian(context.language):
        message = [
            "Свежая готовность из Intervals.icu недоступна, поэтому сегодня лучше выбрать консервативный день.",
            "Сильную работу и длинную сессию лучше не планировать, пока нет нормальной оценки восстановления.",
        ]
        weather_line = _weather_line(context, russian=True)
        if weather_line:
            message.append(weather_line)
        return " ".join(message)

    message = [
        "Intervals.icu readiness data is unavailable, so today should stay conservative.",
        "Avoid a hard session or a long ride until recovery data is available again.",
    ]
    weather_line = _weather_line(context, russian=False)
    if weather_line:
        message.append(weather_line)
    return " ".join(message)


def _weather_line(context: MorningReportContext, russian: bool) -> str | None:
    if not context.has_weather() or not context.weather_hours:
        return None

    first_hour = context.weather_hours[0]
    time_value = first_hour.get("time")
    weather = first_hour.get("weather")
    temp = first_hour.get("temp")
    wind = first_hour.get("wind_speed")

    if russian:
        return (
            f"По погоде ближайшее окно начинается около {time_value}: "
            f"{weather}, {temp}°C, ветер {wind} км/ч."
        )
    return f"Weather at the next window around {time_value}: {weather}, {temp}C, wind {wind} km/h."


def _is_russian(language: str | None) -> bool:
    if language is None:
        return False
    return language.casefold().startswith("ru")
