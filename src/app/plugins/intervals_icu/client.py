from __future__ import annotations

from collections.abc import Sequence

import httpx


class IntervalsIcuError(RuntimeError):
    pass


class IntervalsIcuClient:
    def __init__(
        self,
        athlete_id: str,
        api_key: str,
        base_url: str = "https://intervals.icu",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._athlete_id = athlete_id
        self._owns_client = http_client is None
        self._auth = httpx.BasicAuth("API_KEY", api_key)
        self._headers = {"Accept": "application/json"}
        self._client = http_client or httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=self._auth,
            headers=self._headers,
            timeout=20.0,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_wellness_record(self, date: str) -> dict:
        return self._get_json(f"/api/v1/athlete/{self._athlete_id}/wellness/{date}")

    def list_wellness_records(
        self,
        oldest: str | None = None,
        newest: str | None = None,
        fields: Sequence[str] | None = None,
    ) -> list[dict]:
        params = _clean_params(
            oldest=oldest,
            newest=newest,
            fields=list(fields) if fields else None,
        )
        data = self._get_json(f"/api/v1/athlete/{self._athlete_id}/wellness.json", params=params)
        if isinstance(data, list):
            return data
        raise IntervalsIcuError("Intervals.icu returned an unexpected wellness response.")

    def list_activities(
        self,
        oldest: str,
        newest: str | None = None,
        limit: int | None = None,
        fields: Sequence[str] | None = None,
    ) -> list[dict]:
        params = _clean_params(
            oldest=oldest,
            newest=newest,
            limit=limit,
            fields=list(fields) if fields else None,
        )
        data = self._get_json(f"/api/v1/athlete/{self._athlete_id}/activities", params=params)
        if isinstance(data, list):
            return data
        raise IntervalsIcuError("Intervals.icu returned an unexpected activities response.")

    def list_events(
        self,
        oldest: str | None = None,
        newest: str | None = None,
        categories: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        params = _clean_params(
            oldest=oldest,
            newest=newest,
            category=list(categories) if categories else None,
            limit=limit,
        )
        data = self._get_json(f"/api/v1/athlete/{self._athlete_id}/events.json", params=params)
        if isinstance(data, list):
            return data
        raise IntervalsIcuError("Intervals.icu returned an unexpected events response.")

    def get_activity(self, activity_id: str, include_intervals: bool = False) -> dict:
        params = _clean_params(intervals=include_intervals or None)
        return self._get_json(f"/api/v1/activity/{activity_id}", params=params)

    def _get_json(self, path: str, params: dict | None = None) -> dict | list:
        try:
            response = self._client.get(
                path,
                params=params,
                auth=self._auth,
                headers=self._headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() or exc.response.reason_phrase
            raise IntervalsIcuError(
                f"Intervals.icu request failed with HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise IntervalsIcuError(f"Intervals.icu request failed: {exc}") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise IntervalsIcuError("Intervals.icu returned invalid JSON.") from exc


def _clean_params(**kwargs: object) -> dict:
    return {key: value for key, value in kwargs.items() if value is not None}
