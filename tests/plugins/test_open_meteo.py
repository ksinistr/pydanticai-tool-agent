from __future__ import annotations

import json

import pytest

from app.plugins.open_meteo.models import ForecastRequest, LocationSearchRequest
from app.plugins.open_meteo.service import OpenMeteoService


class FakeOpenMeteoClient:
    def search_locations(
        self,
        query: str,
        country_code: str | None = None,
        limit: int = 5,
        language: str = "en",
    ) -> list[dict]:
        assert language == "en"

        if query == "Limassol":
            assert country_code is None
            assert limit == 5
            return [
                {
                    "name": "Limassol",
                    "country_code": "CY",
                    "country": "Cyprus",
                    "admin1": "Limassol",
                    "timezone": "Asia/Nicosia",
                    "latitude": 34.68406,
                    "longitude": 33.03794,
                }
            ]

        if query == "Springfield":
            return [
                {
                    "name": "Springfield",
                    "country_code": "US",
                    "country": "United States",
                    "admin1": "Illinois",
                    "timezone": "America/Chicago",
                    "latitude": 39.799,
                    "longitude": -89.644,
                },
                {
                    "name": "Springfield",
                    "country_code": "US",
                    "country": "United States",
                    "admin1": "Missouri",
                    "timezone": "America/Chicago",
                    "latitude": 37.2153,
                    "longitude": -93.2982,
                },
            ]

        return []

    def get_forecast(
        self,
        latitude: float,
        longitude: float,
        timezone: str = "auto",
        hours: int | None = None,
        days: int | None = None,
    ) -> dict:
        assert latitude == 34.684
        assert longitude == 33.0379
        assert timezone == "auto"
        assert hours == 2
        assert days is None
        return {
            "latitude": 34.68406,
            "longitude": 33.03794,
            "timezone": "Asia/Nicosia",
            "hourly": {
                "time": ["2026-04-19T15:00", "2026-04-19T16:00"],
                "temperature_2m": [19.53, 19.2],
                "apparent_temperature": [19.5, 19.1],
                "precipitation_probability": [35, 20],
                "precipitation": [0.11, 0.0],
                "snowfall": [0.0, 0.0],
                "cloud_cover": [73, 68],
                "wind_speed_10m": [6.19, 6.4],
                "wind_gusts_10m": [6.65, 6.9],
                "wind_direction_10m": [237, 240],
                "weather_code": [500, 803],
            },
        }


def test_open_meteo_search_locations_returns_compact_matches() -> None:
    service = OpenMeteoService(FakeOpenMeteoClient())

    payload = json.loads(service.search_locations(LocationSearchRequest(query="Limassol")))

    assert payload == {
        "query": "Limassol",
        "matches": [
            {
                "name": "Limassol",
                "country_code": "CY",
                "country": "Cyprus",
                "admin1": "Limassol",
                "timezone": "Asia/Nicosia",
                "latitude": 34.6841,
                "longitude": 33.0379,
            }
        ],
    }


def test_open_meteo_forecast_by_coordinates_returns_hourly_items() -> None:
    service = OpenMeteoService(FakeOpenMeteoClient())

    payload = json.loads(
        service.get_forecast(ForecastRequest(latitude=34.6840, longitude=33.0379, hours=2))
    )

    assert payload["location"] == {
        "latitude": 34.6841,
        "longitude": 33.0379,
        "timezone": "Asia/Nicosia",
    }
    assert payload["forecast"]["type"] == "hourly"
    assert payload["forecast"]["hours"] == 2
    assert payload["forecast"]["items"][0] == {
        "time": "2026-04-19T15:00",
        "temp": 19.53,
        "feels_like": 19.5,
        "precipitation_probability": 35,
        "wind_speed": 6.19,
        "wind_gust": 6.65,
        "wind_deg": 237,
        "precipitation": 0.11,
        "snowfall": 0.0,
        "clouds": 73,
        "weather_code": 500,
    }


def test_open_meteo_forecast_request_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="Both latitude and longitude are required."):
        ForecastRequest(latitude=34.6)

    with pytest.raises(ValueError, match="Use either hours or days, not both."):
        ForecastRequest(latitude=34.6, longitude=33.0, hours=12, days=5)
