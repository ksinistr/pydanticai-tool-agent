from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MorningReportSettings:
    latitude: float
    longitude: float
    timezone: str
    language: str


@dataclass(frozen=True, slots=True)
class MorningReportSetup:
    settings: MorningReportSettings | None
    missing_variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MorningReportContext:
    generated_at: str
    anchor_date: str
    weekday: str
    day_type: str
    timezone: str
    language: str
    latitude: float
    longitude: float
    history_from: str
    history_to: str
    intervals_error: str | None
    weather_error: str | None
    activities: list[dict[str, Any]]
    wellness: list[dict[str, Any]]
    weather_hours: list[dict[str, Any]]

    def has_intervals(self) -> bool:
        return self.intervals_error is None

    def has_weather(self) -> bool:
        return self.weather_error is None
