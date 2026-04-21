from __future__ import annotations

from datetime import UTC, datetime

from app.morning_report.context import MorningReportContextBuilder
from app.morning_report.models import (
    DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
    DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
    MorningReportSettings,
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
            }
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


class FakeWeatherClient:
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
        assert hours == 12
        assert days is None
        return {
            "hourly": {
                "time": ["2026-04-20T06:00", "2026-04-20T07:00"],
                "temperature_2m": [18.6, 19.3],
                "apparent_temperature": [18.4, 19.0],
                "precipitation_probability": [10, 5],
                "precipitation": [0.0, 0.0],
                "wind_speed_10m": [8.1, 7.4],
                "wind_gusts_10m": [11.5, 9.8],
                "weather_code": [0, 1],
            }
        }


def test_context_builder_shapes_morning_report_payloads() -> None:
    builder = MorningReportContextBuilder(
        intervals_client=FakeIntervalsClient(),
        weather_client=FakeWeatherClient(),
        caldav_client=FakeCaldavClient(),
        now=lambda timezone: datetime(2026, 4, 20, 6, 30, tzinfo=timezone),
    )

    context = builder.build(
        MorningReportSettings(
            latitude=34.7765,
            longitude=32.4241,
            timezone="Asia/Nicosia",
            language="ru",
            holidays_calendar_id=DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
            vacation_calendar_id=DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
        )
    )

    assert context.anchor_date == "2026-04-20"
    assert context.day_type == "holiday"
    assert context.workday_constraints_apply is False
    assert context.history_from == "2026-04-14"
    assert context.calendar_from == "2026-04-20T00:00:00+03:00"
    assert context.calendar_to == "2026-04-27T00:00:00+03:00"
    assert context.calendar_error is None
    assert context.activities[0] == {
        "date": "2026-04-19",
        "start_time": "07:10",
        "sport": "Ride",
        "name": "Endurance Ride",
        "moving_minutes": 90,
        "distance_km": 42.1,
        "elevation_m": 620,
        "training_load": 81.4,
        "avg_hr": 142,
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
    assert context.weather_hours[0] == {
        "time": "2026-04-20T06:00",
        "temp": 18.6,
        "feels_like": 18.4,
        "wind_speed": 8.1,
        "wind_gust": 11.5,
        "precipitation": 0.0,
        "precipitation_probability": 10,
        "weather_code": 0,
        "weather": "clear sky",
    }


def test_context_builder_falls_back_to_weekday_when_calendar_is_unavailable() -> None:
    builder = MorningReportContextBuilder(
        intervals_client=FakeIntervalsClient(),
        weather_client=FakeWeatherClient(),
        caldav_client=None,
        calendar_setup_error="CalDAV is not configured (CALDAV_SERVER_URL, CALDAV_USERNAME).",
        now=lambda timezone: datetime(2026, 4, 20, 6, 30, tzinfo=timezone),
    )

    context = builder.build(
        MorningReportSettings(
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
