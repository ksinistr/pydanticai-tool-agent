from __future__ import annotations

from datetime import UTC, datetime

from app.daily_training_advice.context import DailyTrainingAdviceContextBuilder
from app.daily_training_advice.models import (
    DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
    DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
    DailyTrainingAdviceSettings,
)
from app.plugins.caldav.models import EventRecord


class FakeIntervalsClient:
    def list_activities(
        self,
        oldest: str,
        newest: str | None = None,
        limit: int | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> list[dict]:
        assert oldest == "2026-04-14"
        assert newest == "2026-04-20"
        assert limit == 20
        assert fields is not None
        return [
            {
                "start_date_local": "2026-04-19T07:10:00Z",
                "type": "Ride",
                "name": "Endurance Ride",
                "moving_time": 5400,
                "distance": 42150,
                "total_elevation_gain": 620,
                "icu_training_load": 81.4,
                "average_heartrate": 142,
            },
            {
                "start_date_local": "2026-04-20T08:05:00+03:00",
                "type": "Ride",
                "name": "Commute Spin",
                "moving_time": 2400,
                "distance": 12200,
                "total_elevation_gain": 120,
                "icu_training_load": 24.5,
                "average_heartrate": 118,
            },
        ]

    def list_wellness_records(
        self,
        oldest: str | None = None,
        newest: str | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> list[dict]:
        assert oldest == "2026-04-14"
        assert newest == "2026-04-20"
        assert fields is not None
        return [
            {
                "id": "2026-04-20",
                "readiness": 71,
                "sleepScore": 84,
                "sleepSecs": 27000,
                "restingHR": 47,
                "hrv": 74,
                "fatigue": 35,
                "stress": 20,
                "motivation": 80,
                "mood": 78,
            }
        ]


class FakeCaldavClient:
    def list_events(self, request) -> list[EventRecord]:
        assert request.from_datetime.isoformat() == "2026-04-20T00:00:00+03:00"
        assert request.to_datetime.isoformat() == "2026-04-27T00:00:00+03:00"
        if request.calendar_id == DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID:
            return [
                EventRecord(
                    calendar_id=request.calendar_id,
                    event_id="holiday.ics",
                    uid="holiday-1",
                    title="Easter Monday",
                    description="",
                    start=datetime(2026, 4, 20, tzinfo=UTC),
                    end=datetime(2026, 4, 20, tzinfo=UTC),
                    all_day=True,
                )
            ]
        assert request.calendar_id == DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID
        return []


class MorningWeatherClient:
    def get_forecast(
        self,
        latitude: float,
        longitude: float,
        timezone: str = "auto",
        hours: int | None = None,
        days: int | None = None,
    ) -> dict:
        assert latitude == 34.7765
        assert longitude == 32.4241
        assert timezone == "Asia/Nicosia"
        assert hours == 18
        assert days is None
        return {
            "hourly": {
                "time": ["2026-04-20T07:00", "2026-04-20T08:00", "2026-04-21T00:00"],
                "temperature_2m": [18.6, 19.3, 15.0],
                "apparent_temperature": [18.4, 19.0, 14.7],
                "precipitation_probability": [10, 5, 15],
                "precipitation": [0.0, 0.0, 0.1],
                "wind_speed_10m": [8.1, 7.4, 5.2],
                "wind_gusts_10m": [11.5, 9.8, 7.1],
                "weather_code": [0, 1, 2],
            }
        }


class LateDayWeatherClient:
    def get_forecast(
        self,
        latitude: float,
        longitude: float,
        timezone: str = "auto",
        hours: int | None = None,
        days: int | None = None,
    ) -> dict:
        assert latitude == 34.7765
        assert longitude == 32.4241
        assert timezone == "Asia/Nicosia"
        assert hours == 8
        assert days is None
        return {
            "hourly": {
                "time": ["2026-04-20T16:00", "2026-04-20T18:00", "2026-04-21T00:00"],
                "temperature_2m": [24.2, 21.8, 18.0],
                "apparent_temperature": [24.0, 21.6, 17.8],
                "precipitation_probability": [0, 10, 15],
                "precipitation": [0.0, 0.0, 0.0],
                "wind_speed_10m": [10.1, 12.4, 9.0],
                "wind_gusts_10m": [15.5, 18.8, 11.0],
                "weather_code": [0, 1, 2],
            }
        }


def test_context_builder_shapes_remaining_day_payloads() -> None:
    builder = DailyTrainingAdviceContextBuilder(
        intervals_client=FakeIntervalsClient(),
        weather_client=MorningWeatherClient(),
        caldav_client=FakeCaldavClient(),
        now=lambda timezone: datetime(2026, 4, 20, 6, 30, tzinfo=timezone),
    )

    context = builder.build(
        DailyTrainingAdviceSettings(
            latitude=34.7765,
            longitude=32.4241,
            timezone="Asia/Nicosia",
            language="ru",
            holidays_calendar_id=DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
            vacation_calendar_id=DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
        )
    )

    assert context.current_time == "06:30"
    assert context.anchor_date == "2026-04-20"
    assert context.day_type == "holiday"
    assert context.workday_constraints_apply is False
    assert context.history_from == "2026-04-14"
    assert context.calendar_from == "2026-04-20T00:00:00+03:00"
    assert context.calendar_to == "2026-04-27T00:00:00+03:00"
    assert context.calendar_error is None
    assert context.recent_activities[0] == {
        "date": "2026-04-19",
        "start_time": "10:10",
        "sport": "Ride",
        "name": "Endurance Ride",
        "moving_minutes": 90,
        "distance_km": 42.1,
        "elevation_m": 620,
        "training_load": 81.4,
        "avg_hr": 142,
    }
    assert context.today_activities == [
        {
            "date": "2026-04-20",
            "start_time": "08:05",
            "sport": "Ride",
            "name": "Commute Spin",
            "moving_minutes": 40,
            "distance_km": 12.2,
            "elevation_m": 120,
            "training_load": 24.5,
            "avg_hr": 118,
        }
    ]
    assert context.today_summary == {
        "count": 1,
        "sports": ["Ride"],
        "moving_minutes": 40,
        "training_load": 24.5,
        "distance_km": 12.2,
        "last_activity_time": "08:05",
    }
    assert context.wellness[0]["sleep_hours"] == 7.5
    assert context.holidays == [
        {
            "title": "Easter Monday",
            "all_day": True,
            "start_date": "2026-04-20",
            "end_date": "2026-04-20",
        }
    ]
    assert context.vacation == []
    assert context.remaining_weather_hours == [
        {
            "time": "2026-04-20T07:00+03:00",
            "temp": 18.6,
            "feels_like": 18.4,
            "wind_speed": 8.1,
            "wind_gust": 11.5,
            "precipitation": 0.0,
            "precipitation_probability": 10,
            "weather_code": 0,
            "weather": "clear sky",
        },
        {
            "time": "2026-04-20T08:00+03:00",
            "temp": 19.3,
            "feels_like": 19.0,
            "wind_speed": 7.4,
            "wind_gust": 9.8,
            "precipitation": 0.0,
            "precipitation_probability": 5,
            "weather_code": 1,
            "weather": "mainly clear",
        },
    ]


def test_context_builder_filters_weather_to_remaining_hours_and_today() -> None:
    builder = DailyTrainingAdviceContextBuilder(
        intervals_client=FakeIntervalsClient(),
        weather_client=LateDayWeatherClient(),
        caldav_client=None,
        calendar_setup_error="CalDAV is not configured (CALDAV_SERVER_URL, CALDAV_USERNAME).",
        now=lambda timezone: datetime(2026, 4, 20, 16, 30, tzinfo=timezone),
    )

    context = builder.build(
        DailyTrainingAdviceSettings(
            latitude=34.7765,
            longitude=32.4241,
            timezone="Asia/Nicosia",
            language="en",
            holidays_calendar_id=DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
            vacation_calendar_id=DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
        )
    )

    assert context.day_type == "workday"
    assert context.workday_constraints_apply is True
    assert context.calendar_error == "CalDAV is not configured (CALDAV_SERVER_URL, CALDAV_USERNAME)."
    assert context.remaining_weather_hours == [
        {
            "time": "2026-04-20T18:00+03:00",
            "temp": 21.8,
            "feels_like": 21.6,
            "wind_speed": 12.4,
            "wind_gust": 18.8,
            "precipitation": 0.0,
            "precipitation_probability": 10,
            "weather_code": 1,
            "weather": "mainly clear",
        }
    ]
