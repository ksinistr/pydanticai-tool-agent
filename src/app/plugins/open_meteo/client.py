from __future__ import annotations

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation_probability",
    "precipitation",
    "snowfall",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
    "weather_code",
)

DAILY_VARIABLES = (
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
    "snowfall_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "sunrise",
    "sunset",
    "weather_code",
)


class OpenMeteoError(RuntimeError):
    pass


class OpenMeteoClient:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=20.0)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search_locations(
        self,
        query: str,
        country_code: str | None = None,
        limit: int = 5,
        language: str = "en",
    ) -> list[dict]:
        params = _clean_params(
            name=query,
            count=limit,
            language=language,
            format="json",
            countryCode=country_code,
        )
        payload = self._get_json(GEOCODING_URL, params)
        if not isinstance(payload, dict):
            raise OpenMeteoError("Open-Meteo returned an unexpected geocoding response.")

        results = payload.get("results")
        if isinstance(results, list):
            return results
        return []

    def get_forecast(
        self,
        latitude: float,
        longitude: float,
        timezone: str = "auto",
        hours: int | None = None,
        days: int | None = None,
    ) -> dict:
        params: dict[str, object] = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": timezone,
        }

        if hours is not None:
            params["forecast_hours"] = hours
            params["hourly"] = ",".join(HOURLY_VARIABLES)
        elif days is not None:
            params["forecast_days"] = days
            params["daily"] = ",".join(DAILY_VARIABLES)
        else:
            raise OpenMeteoError("Either hours or days is required for forecast requests.")

        payload = self._get_json(FORECAST_URL, params)
        if isinstance(payload, dict):
            return payload
        raise OpenMeteoError("Open-Meteo returned an unexpected forecast response.")

    def _get_json(self, url: str, params: dict[str, object]) -> dict | list:
        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _response_detail(exc.response)
            raise OpenMeteoError(
                f"Open-Meteo request failed with HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenMeteoError(f"Open-Meteo request failed: {exc}") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise OpenMeteoError("Open-Meteo returned invalid JSON.") from exc


def _clean_params(**kwargs: object) -> dict[str, object]:
    return {key: value for key, value in kwargs.items() if value is not None}


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase

    if isinstance(payload, dict):
        reason = payload.get("reason")
        if isinstance(reason, str) and reason:
            return reason

    return response.text.strip() or response.reason_phrase
