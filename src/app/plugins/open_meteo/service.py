from __future__ import annotations

import json

from app.plugins.open_meteo.client import OpenMeteoClient
from app.plugins.open_meteo.models import ForecastRequest, LocationSearchRequest


class OpenMeteoService:
    def __init__(self, client: OpenMeteoClient) -> None:
        self._client = client

    def search_locations(self, request: LocationSearchRequest) -> str:
        matches = self._client.search_locations(
            query=request.query,
            country_code=request.country_code,
            limit=request.limit,
        )
        result = {
            "query": request.query,
            "matches": [_summarize_location(match) for match in matches],
        }
        return _to_json(result)

    def get_forecast(self, request: ForecastRequest) -> str:
        forecast = self._client.get_forecast(
            latitude=request.latitude if request.latitude is not None else 0.0,
            longitude=request.longitude if request.longitude is not None else 0.0,
            timezone="auto",
            hours=request.hours,
            days=request.days,
        )
        location = _merge_location(
            {
                "latitude": _round_coordinate(request.latitude),
                "longitude": _round_coordinate(request.longitude),
            },
            forecast,
        )
        return _to_json(
            _build_forecast_result(location=location, forecast=forecast, request=request)
        )


def _build_forecast_result(location: dict, forecast: dict, request: ForecastRequest) -> dict:
    if request.hours is not None:
        forecast_data = {
            "type": "hourly",
            "hours": request.hours,
            "items": _build_hourly_items(forecast.get("hourly", {})),
        }
    else:
        forecast_data = {
            "type": "daily",
            "days": request.days,
            "items": _build_daily_items(forecast.get("daily", {})),
        }

    return {
        "location": _compact_dict(location),
        "forecast": _compact_dict(forecast_data),
    }


def _build_hourly_items(payload: dict) -> list[dict]:
    times = payload.get("time")
    if not isinstance(times, list):
        return []

    items: list[dict] = []
    for index, time_value in enumerate(times):
        if not isinstance(time_value, str):
            continue
        items.append(
            _compact_dict(
                {
                    "time": time_value,
                    "temp": _series_value(payload, "temperature_2m", index),
                    "feels_like": _series_value(payload, "apparent_temperature", index),
                    "precipitation_probability": _series_value(
                        payload, "precipitation_probability", index
                    ),
                    "wind_speed": _series_value(payload, "wind_speed_10m", index),
                    "wind_gust": _series_value(payload, "wind_gusts_10m", index),
                    "wind_deg": _series_value(payload, "wind_direction_10m", index),
                    "precipitation": _series_value(payload, "precipitation", index),
                    "snowfall": _series_value(payload, "snowfall", index),
                    "clouds": _series_value(payload, "cloud_cover", index),
                    "weather_code": _series_value(payload, "weather_code", index),
                }
            )
        )
    return items


def _build_daily_items(payload: dict) -> list[dict]:
    times = payload.get("time")
    if not isinstance(times, list):
        return []

    items: list[dict] = []
    for index, time_value in enumerate(times):
        if not isinstance(time_value, str):
            continue
        items.append(
            _compact_dict(
                {
                    "date": time_value,
                    "temp_min": _series_value(payload, "temperature_2m_min", index),
                    "temp_max": _series_value(payload, "temperature_2m_max", index),
                    "wind_speed": _series_value(payload, "wind_speed_10m_max", index),
                    "wind_gust": _series_value(payload, "wind_gusts_10m_max", index),
                    "wind_deg": _series_value(payload, "wind_direction_10m_dominant", index),
                    "precipitation": _series_value(payload, "precipitation_sum", index),
                    "snowfall": _series_value(payload, "snowfall_sum", index),
                    "sunrise": _series_value(payload, "sunrise", index),
                    "sunset": _series_value(payload, "sunset", index),
                    "weather_code": _series_value(payload, "weather_code", index),
                }
            )
        )
    return items


def _summarize_location(payload: dict) -> dict:
    return _compact_dict(
        {
            "name": payload.get("name"),
            "country_code": payload.get("country_code"),
            "country": payload.get("country"),
            "admin1": payload.get("admin1"),
            "timezone": payload.get("timezone"),
            "latitude": _round_coordinate(payload.get("latitude")),
            "longitude": _round_coordinate(payload.get("longitude")),
        }
    )


def _merge_location(location: dict, forecast: dict) -> dict:
    merged = dict(location)

    timezone = forecast.get("timezone")
    if isinstance(timezone, str) and timezone:
        merged["timezone"] = timezone

    latitude = _round_coordinate(forecast.get("latitude"))
    longitude = _round_coordinate(forecast.get("longitude"))
    if latitude is not None:
        merged["latitude"] = latitude
    if longitude is not None:
        merged["longitude"] = longitude

    return merged


def _series_value(payload: dict, key: str, index: int) -> int | float | str | None:
    values = payload.get(key)
    if not isinstance(values, list) or index >= len(values):
        return None

    value = values[index]
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, (int, str)):
        return value
    return None


def _round_coordinate(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    return None


def _string_or(value: object, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value
    return fallback


def _compact_dict(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value not in (None, [], {}, "")}


def _to_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
