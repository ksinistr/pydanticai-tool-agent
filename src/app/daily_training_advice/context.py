from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from math import ceil
from zoneinfo import ZoneInfo

from app.daily_training_advice.models import (
    DailyTrainingAdviceContext,
    DailyTrainingAdviceSettings,
)
from app.plugins.caldav.client import CaldavClient, CaldavError
from app.plugins.caldav.models import EventRecord, ListEventsRequest
from app.plugins.intervals_icu.client import IntervalsIcuClient, IntervalsIcuError
from app.plugins.open_meteo.client import OpenMeteoClient, OpenMeteoError

ACTIVITY_FIELDS = (
    "start_date_local",
    "type",
    "name",
    "moving_time",
    "distance",
    "total_elevation_gain",
    "icu_training_load",
    "average_heartrate",
)

WELLNESS_FIELDS = (
    "id",
    "readiness",
    "sleepScore",
    "sleepSecs",
    "restingHR",
    "hrv",
    "fatigue",
    "stress",
    "motivation",
    "mood",
)

HISTORY_DAYS = 7
CALENDAR_DAYS = 7


class DailyTrainingAdviceContextBuilder:
    def __init__(
        self,
        intervals_client: IntervalsIcuClient | None,
        weather_client: OpenMeteoClient,
        caldav_client: CaldavClient | None = None,
        calendar_setup_error: str | None = None,
        now: Callable[[ZoneInfo], datetime] | None = None,
    ) -> None:
        self._intervals_client = intervals_client
        self._weather_client = weather_client
        self._caldav_client = caldav_client
        self._calendar_setup_error = calendar_setup_error
        self._now = now or (lambda timezone: datetime.now(timezone))

    def build(self, settings: DailyTrainingAdviceSettings) -> DailyTrainingAdviceContext:
        timezone = ZoneInfo(settings.timezone)
        current_time = self._now(timezone)
        anchor_date = current_time.date()
        history_from = (anchor_date - timedelta(days=HISTORY_DAYS - 1)).isoformat()
        history_to = anchor_date.isoformat()
        calendar_from_dt = datetime.combine(anchor_date, time.min, tzinfo=timezone)
        calendar_to_dt = calendar_from_dt + timedelta(days=CALENDAR_DAYS)

        intervals_error: str | None = None
        calendar_error: str | None = None
        weather_error: str | None = None
        recent_activities: list[dict] = []
        today_activities: list[dict] = []
        wellness: list[dict] = []
        holidays_events: list[EventRecord] = []
        vacation_events: list[EventRecord] = []
        remaining_weather_hours: list[dict] = []

        if self._intervals_client is None:
            intervals_error = "Intervals.icu is not configured."
        else:
            try:
                recent_activities = _shape_activities(
                    self._intervals_client.list_activities(
                        oldest=history_from,
                        newest=history_to,
                        limit=20,
                        fields=ACTIVITY_FIELDS,
                    ),
                    timezone,
                )
                today_activities = [
                    activity for activity in recent_activities if activity.get("date") == history_to
                ]
                wellness = _shape_wellness(
                    self._intervals_client.list_wellness_records(
                        oldest=history_from,
                        newest=history_to,
                        fields=WELLNESS_FIELDS,
                    )
                )
            except IntervalsIcuError as exc:
                intervals_error = str(exc)

        calendar_errors: list[str] = []
        if self._caldav_client is None:
            calendar_errors.append(self._calendar_setup_error or "CalDAV is not configured.")
        else:
            try:
                holidays_events = self._caldav_client.list_events(
                    ListEventsRequest(
                        calendar_id=settings.holidays_calendar_id,
                        from_datetime=calendar_from_dt,
                        to_datetime=calendar_to_dt,
                    )
                )
            except (CaldavError, ValueError) as exc:
                calendar_errors.append(f"holiday calendar: {exc}")

            try:
                vacation_events = self._caldav_client.list_events(
                    ListEventsRequest(
                        calendar_id=settings.vacation_calendar_id,
                        from_datetime=calendar_from_dt,
                        to_datetime=calendar_to_dt,
                    )
                )
            except (CaldavError, ValueError) as exc:
                calendar_errors.append(f"vacation calendar: {exc}")

        if calendar_errors:
            calendar_error = "; ".join(calendar_errors)

        try:
            forecast = self._weather_client.get_forecast(
                latitude=settings.latitude,
                longitude=settings.longitude,
                timezone=settings.timezone,
                hours=_remaining_forecast_hours(current_time),
            )
            remaining_weather_hours = _shape_remaining_weather_hours(
                forecast,
                timezone,
                current_time,
                anchor_date,
            )
        except OpenMeteoError as exc:
            weather_error = str(exc)

        day_type = _resolve_day_type(anchor_date, timezone, holidays_events, vacation_events)

        return DailyTrainingAdviceContext(
            generated_at=current_time.isoformat(timespec="minutes"),
            current_time=current_time.strftime("%H:%M"),
            anchor_date=history_to,
            weekday=current_time.strftime("%A"),
            day_type=day_type,
            workday_constraints_apply=day_type == "workday",
            timezone=settings.timezone,
            language=settings.language,
            latitude=round(settings.latitude, 4),
            longitude=round(settings.longitude, 4),
            history_from=history_from,
            history_to=history_to,
            calendar_from=calendar_from_dt.isoformat(timespec="seconds"),
            calendar_to=calendar_to_dt.isoformat(timespec="seconds"),
            intervals_error=intervals_error,
            calendar_error=calendar_error,
            weather_error=weather_error,
            recent_activities=recent_activities,
            today_activities=today_activities,
            today_summary=_summarize_today_activities(today_activities),
            wellness=wellness,
            holidays=_shape_calendar_events(holidays_events, timezone),
            vacation=_shape_calendar_events(vacation_events, timezone),
            remaining_weather_hours=remaining_weather_hours,
        )


def _remaining_forecast_hours(current_time: datetime) -> int:
    next_midnight = datetime.combine(
        current_time.date() + timedelta(days=1),
        time.min,
        tzinfo=current_time.tzinfo,
    )
    remaining_seconds = max(0.0, (next_midnight - current_time).total_seconds())
    return max(1, ceil(remaining_seconds / 3600))


def _resolve_day_type(
    anchor_date: date,
    timezone: ZoneInfo,
    holidays_events: list[EventRecord],
    vacation_events: list[EventRecord],
) -> str:
    has_holiday = any(_event_covers_date(event, anchor_date, timezone) for event in holidays_events)
    has_vacation = any(_event_covers_date(event, anchor_date, timezone) for event in vacation_events)

    if has_holiday and has_vacation:
        return "holiday_and_vacation"
    if has_holiday:
        return "holiday"
    if has_vacation:
        return "vacation"
    if anchor_date.weekday() >= 5:
        return "weekend"
    return "workday"


def _event_covers_date(event: EventRecord, anchor_date: date, timezone: ZoneInfo) -> bool:
    if event.all_day:
        start_date = event.start.date()
        end_date = event.end.date()
    else:
        start_date = event.start.astimezone(timezone).date()
        end_date = event.end.astimezone(timezone).date()
    return start_date <= anchor_date <= end_date


def _shape_activities(items: list[dict], timezone: ZoneInfo) -> list[dict]:
    shaped: list[dict] = []
    for item in items:
        local_start = _parse_datetime(item.get("start_date_local"), timezone)
        shaped.append(
            _compact_dict(
                {
                    "date": local_start.date().isoformat() if local_start else None,
                    "start_time": local_start.strftime("%H:%M") if local_start else None,
                    "sport": item.get("type"),
                    "name": item.get("name"),
                    "moving_minutes": _seconds_to_minutes(item.get("moving_time")),
                    "distance_km": _meters_to_km(item.get("distance")),
                    "elevation_m": _rounded_number(item.get("total_elevation_gain")),
                    "training_load": _rounded_number(item.get("icu_training_load")),
                    "avg_hr": _rounded_number(item.get("average_heartrate")),
                }
            )
        )
    return shaped


def _shape_wellness(items: list[dict]) -> list[dict]:
    shaped: list[dict] = []
    for item in items:
        shaped.append(
            _compact_dict(
                {
                    "date": item.get("id"),
                    "readiness": _rounded_number(item.get("readiness")),
                    "sleep_score": _rounded_number(item.get("sleepScore")),
                    "sleep_hours": _seconds_to_hours(item.get("sleepSecs")),
                    "resting_hr": _rounded_number(item.get("restingHR")),
                    "hrv": _rounded_number(item.get("hrv")),
                    "fatigue": _rounded_number(item.get("fatigue")),
                    "stress": _rounded_number(item.get("stress")),
                    "motivation": _rounded_number(item.get("motivation")),
                    "mood": _rounded_number(item.get("mood")),
                }
            )
        )
    return shaped


def _summarize_today_activities(items: list[dict]) -> dict:
    sports: list[str] = []
    last_activity_time: str | None = None
    moving_minutes_total = 0
    moving_minutes_seen = False
    training_load_total = 0.0
    training_load_seen = False
    distance_total = 0.0
    distance_seen = False

    for item in items:
        sport = item.get("sport")
        if isinstance(sport, str) and sport and sport not in sports:
            sports.append(sport)

        start_time = item.get("start_time")
        if isinstance(start_time, str) and (last_activity_time is None or start_time > last_activity_time):
            last_activity_time = start_time

        moving_minutes = item.get("moving_minutes")
        if isinstance(moving_minutes, int):
            moving_minutes_total += moving_minutes
            moving_minutes_seen = True

        training_load = item.get("training_load")
        if isinstance(training_load, (int, float)):
            training_load_total += float(training_load)
            training_load_seen = True

        distance_km = item.get("distance_km")
        if isinstance(distance_km, (int, float)):
            distance_total += float(distance_km)
            distance_seen = True

    return _compact_dict(
        {
            "count": len(items),
            "sports": sports,
            "moving_minutes": moving_minutes_total if moving_minutes_seen else None,
            "training_load": _rounded_number(training_load_total) if training_load_seen else None,
            "distance_km": _rounded_number(distance_total) if distance_seen else None,
            "last_activity_time": last_activity_time,
        }
    )


def _shape_calendar_events(events: list[EventRecord], timezone: ZoneInfo) -> list[dict]:
    shaped: list[dict] = []
    for event in sorted(events, key=lambda item: (item.start, item.end, item.title.casefold())):
        if event.all_day:
            payload = {
                "title": event.title,
                "all_day": True,
                "start_date": event.start.date().isoformat(),
                "end_date": event.end.date().isoformat(),
                "description": event.description,
            }
        else:
            local_start = event.start.astimezone(timezone)
            local_end = event.end.astimezone(timezone)
            payload = {
                "title": event.title,
                "all_day": False,
                "start": local_start.isoformat(timespec="minutes"),
                "end": local_end.isoformat(timespec="minutes"),
                "start_date": local_start.date().isoformat(),
                "end_date": local_end.date().isoformat(),
                "start_time": local_start.strftime("%H:%M"),
                "end_time": local_end.strftime("%H:%M"),
                "description": event.description,
            }
        shaped.append(_compact_dict(payload))
    return shaped


def _shape_remaining_weather_hours(
    forecast: dict,
    timezone: ZoneInfo,
    current_time: datetime,
    anchor_date: date,
) -> list[dict]:
    hourly = forecast.get("hourly", {})
    times = hourly.get("time")
    if not isinstance(times, list):
        return []

    shaped: list[dict] = []
    for index, time_value in enumerate(times):
        weather_time = _parse_datetime(time_value, timezone)
        if weather_time is None or weather_time.date() != anchor_date or weather_time < current_time:
            continue

        weather_code = _series_value(hourly, "weather_code", index)
        shaped.append(
            _compact_dict(
                {
                    "time": weather_time.isoformat(timespec="minutes"),
                    "temp": _rounded_number(_series_value(hourly, "temperature_2m", index)),
                    "feels_like": _rounded_number(
                        _series_value(hourly, "apparent_temperature", index)
                    ),
                    "wind_speed": _rounded_number(_series_value(hourly, "wind_speed_10m", index)),
                    "wind_gust": _rounded_number(_series_value(hourly, "wind_gusts_10m", index)),
                    "precipitation": _rounded_number(_series_value(hourly, "precipitation", index)),
                    "precipitation_probability": _rounded_number(
                        _series_value(hourly, "precipitation_probability", index)
                    ),
                    "weather_code": weather_code,
                    "weather": _describe_weather(weather_code),
                }
            )
        )
    return shaped


def _parse_datetime(value: object, timezone: ZoneInfo) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _series_value(payload: dict, key: str, index: int) -> int | float | str | None:
    values = payload.get(key)
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    if isinstance(value, (int, float, str)):
        return value
    return None


def _describe_weather(code: int | float | str | None) -> str | None:
    if not isinstance(code, (int, float)):
        return None

    mapping = {
        0: "clear sky",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "fog",
        48: "rime fog",
        51: "light drizzle",
        53: "moderate drizzle",
        55: "dense drizzle",
        61: "slight rain",
        63: "moderate rain",
        65: "heavy rain",
        71: "slight snow",
        73: "moderate snow",
        75: "heavy snow",
        80: "slight rain showers",
        81: "moderate rain showers",
        82: "violent rain showers",
        95: "thunderstorm",
    }
    return mapping.get(int(code), f"weather code {int(code)}")


def _meters_to_km(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value) / 1000, 1)
    return None


def _seconds_to_minutes(value: object) -> int | None:
    if isinstance(value, (int, float)):
        return int(round(float(value) / 60))
    return None


def _seconds_to_hours(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value) / 3600, 1)
    return None


def _rounded_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 2)
    return None


def _compact_dict(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value not in (None, [], {}, "")}
