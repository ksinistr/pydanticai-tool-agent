from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.morning_report_defaults import (
    DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
    DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
)

__all__ = [
    "DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID",
    "DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID",
    "DailyTrainingAdviceContext",
    "DailyTrainingAdviceSettings",
    "DailyTrainingAdviceSetup",
    "DailyTrainingAdviceStructuredOutput",
]


@dataclass(frozen=True, slots=True)
class DailyTrainingAdviceSettings:
    latitude: float
    longitude: float
    timezone: str
    language: str
    holidays_calendar_id: str
    vacation_calendar_id: str


@dataclass(frozen=True, slots=True)
class DailyTrainingAdviceSetup:
    settings: DailyTrainingAdviceSettings | None
    missing_variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DailyTrainingAdviceContext:
    generated_at: str
    current_time: str
    anchor_date: str
    weekday: str
    day_type: str
    workday_constraints_apply: bool
    timezone: str
    language: str
    latitude: float
    longitude: float
    history_from: str
    history_to: str
    calendar_from: str
    calendar_to: str
    intervals_error: str | None
    calendar_error: str | None
    weather_error: str | None
    recent_activities: list[dict[str, Any]]
    today_activities: list[dict[str, Any]]
    today_summary: dict[str, Any]
    wellness: list[dict[str, Any]]
    holidays: list[dict[str, Any]]
    vacation: list[dict[str, Any]]
    remaining_weather_hours: list[dict[str, Any]]

    def has_intervals(self) -> bool:
        return self.intervals_error is None

    def has_calendar(self) -> bool:
        return self.calendar_error is None

    def has_weather(self) -> bool:
        return self.weather_error is None


class DailyTrainingAdviceStructuredOutput(BaseModel):
    data_freshness: list[str] = Field(min_length=1, max_length=4)
    readiness_level: Literal["green", "yellow", "red"]
    readiness_summary: str = Field(min_length=1)
    completed_today: list[str] = Field(min_length=1, max_length=4)
    remaining_today: list[str] = Field(min_length=1, max_length=4)
    recovery: list[str] = Field(min_length=1, max_length=4)
    fueling_hydration: list[str] = Field(min_length=1, max_length=4)
    workday_actions: list[str] = Field(min_length=1, max_length=4)
    caution: list[str] = Field(min_length=1, max_length=4)
