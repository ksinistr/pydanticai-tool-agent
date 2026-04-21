from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.plugins.route_planner.geometry import bbox_from_points, decode_polyline
from app.plugins.route_planner.models import StravaSettings


STRAVA_OAUTH_BASE_URL = "https://www.strava.com/oauth"
STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
STRAVA_API_BASE_URL = "https://www.strava.com/api/v3"
STRAVA_REQUIRED_SCOPE = "activity:read_all"


class StravaError(RuntimeError):
    pass


@dataclass(slots=True)
class StravaTokenSet:
    access_token: str
    refresh_token: str
    expires_at: int
    token_type: str = "Bearer"
    scope: str = ""
    athlete_id: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any], scope: str = "") -> StravaTokenSet:
        athlete = payload.get("athlete") or {}
        athlete_id = athlete.get("id")
        return cls(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_at=int(payload["expires_at"]),
            token_type=str(payload.get("token_type", "Bearer")),
            scope=scope,
            athlete_id=int(athlete_id) if athlete_id is not None else None,
        )

    def expires_within(self, seconds: int) -> bool:
        return self.expires_at <= int(time.time()) + seconds


@dataclass(slots=True)
class StravaSyncSummary:
    total_activities: int
    pages_fetched: int


class StravaService:
    def __init__(self, settings: StravaSettings, http_client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.Client(timeout=60.0)

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()

    def build_authorize_url(
        self,
        scope: str = STRAVA_REQUIRED_SCOPE,
        approval_prompt: str = "auto",
        state: str = "pydanticai-tool-agent",
    ) -> str:
        missing = self._settings.missing_auth_fields()
        if missing:
            raise StravaError(f"Missing Strava configuration: {', '.join(missing)}")
        params = urlencode(
            {
                "client_id": self._settings.client_id,
                "redirect_uri": self._settings.redirect_uri,
                "response_type": "code",
                "approval_prompt": approval_prompt,
                "scope": scope,
                "state": state,
            }
        )
        return f"{STRAVA_OAUTH_BASE_URL}/authorize?{params}"

    def extract_authorization_code(self, value: str) -> tuple[str, str]:
        text = value.strip()
        if not text:
            raise StravaError("No Strava authorization code provided.")
        if "code=" not in text and "?" not in text:
            return text, ""
        parsed_url = urlparse(text)
        query = parse_qs(parsed_url.query)
        if "error" in query:
            raise StravaError(f"Strava authorization failed: {query['error'][0]}")
        if "code" not in query:
            raise StravaError("Could not find `code` in the provided Strava callback URL.")
        scope = query.get("scope", [""])[0]
        return query["code"][0], scope

    def exchange_authorization_code(self, code: str, scope: str = "") -> StravaTokenSet:
        payload = {
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        response = self._http_client.post(STRAVA_TOKEN_URL, data=payload, timeout=30.0)
        if response.status_code != 200:
            raise StravaError(
                f"Strava token exchange failed: {response.status_code} {response.text[:300]}"
            )
        token_set = StravaTokenSet.from_payload(response.json(), scope=scope)
        self.save_token_set(token_set)
        return token_set

    def ensure_access_token(self) -> StravaTokenSet:
        missing = self._settings.missing_auth_fields()
        if missing:
            raise StravaError(f"Missing Strava configuration: {', '.join(missing)}")
        token_set = self.load_token_set()
        if token_set is None:
            raise StravaError(
                "Strava is not authorized yet. Run route-planner-tool strava-auth-url first."
            )
        if not token_set.scope:
            token_set.scope = STRAVA_REQUIRED_SCOPE
        if STRAVA_REQUIRED_SCOPE not in token_set.scope.split(","):
            raise StravaError(
                "Stored Strava token does not include `activity:read_all`. Re-authorize and accept that scope."
            )
        if token_set.expires_within(3600):
            token_set = self.refresh_access_token(token_set.refresh_token, token_set.scope)
        return token_set

    def get_authenticated_athlete(self) -> dict[str, Any]:
        token_set = self.ensure_access_token()
        response = self._http_client.get(
            f"{STRAVA_API_BASE_URL}/athlete",
            headers={"Authorization": f"Bearer {token_set.access_token}"},
            timeout=30.0,
        )
        if response.status_code != 200:
            raise StravaError(
                f"Strava athlete lookup failed: {response.status_code} {response.text[:300]}"
            )
        return response.json()

    def sync_all_activities(self) -> StravaSyncSummary:
        self.ensure_storage()
        token_set = self.ensure_access_token()
        all_records: list[dict[str, Any]] = []
        page_number = 1
        while True:
            response = self._http_client.get(
                f"{STRAVA_API_BASE_URL}/athlete/activities",
                headers={"Authorization": f"Bearer {token_set.access_token}"},
                params={"page": page_number, "per_page": 200},
                timeout=60.0,
            )
            if response.status_code != 200:
                raise StravaError(
                    f"Strava activity sync failed: {response.status_code} {response.text[:300]}"
                )
            activities = response.json()
            if not isinstance(activities, list) or not activities:
                break
            all_records.extend(_build_activity_record(activity) for activity in activities)
            page_number += 1

        metadata_path = self.activities_metadata_path()
        metadata_path.write_text(
            "\n".join(json.dumps(record, separators=(",", ":")) for record in all_records)
            + ("\n" if all_records else ""),
            encoding="utf-8",
        )
        return StravaSyncSummary(
            total_activities=len(all_records), pages_fetched=max(page_number - 1, 0)
        )

    def load_cached_activities(self) -> list[dict[str, Any]]:
        path = self.activities_metadata_path()
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records

    def ensure_activity_stream(self, activity_id: int) -> list[tuple[float, float]]:
        cached_points = self.load_cached_stream(activity_id)
        if cached_points is not None:
            return cached_points
        token_set = self.ensure_access_token()
        response = self._http_client.get(
            f"{STRAVA_API_BASE_URL}/activities/{activity_id}/streams",
            headers={"Authorization": f"Bearer {token_set.access_token}"},
            params={"keys": "latlng", "key_by_type": "true"},
            timeout=60.0,
        )
        if response.status_code != 200:
            raise StravaError(
                f"Strava activity stream fetch failed for {activity_id}: {response.status_code} {response.text[:300]}"
            )
        payload = response.json()
        latlng_stream = payload.get("latlng") or {}
        points = [
            (float(latitude), float(longitude))
            for latitude, longitude in latlng_stream.get("data", [])
        ]
        self.save_cached_stream(activity_id, points)
        return points

    def activities_metadata_path(self) -> Path:
        return self._settings.data_dir / "activities.ndjson"

    def load_token_set(self) -> StravaTokenSet | None:
        token_path = self._settings.data_dir / "strava_tokens.json"
        if not token_path.exists():
            return None
        payload = json.loads(token_path.read_text(encoding="utf-8"))
        return StravaTokenSet(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_at=int(payload["expires_at"]),
            token_type=str(payload.get("token_type", "Bearer")),
            scope=str(payload.get("scope", "")),
            athlete_id=int(payload["athlete_id"])
            if payload.get("athlete_id") is not None
            else None,
        )

    def save_token_set(self, token_set: StravaTokenSet) -> None:
        self.ensure_storage()
        token_path = self._settings.data_dir / "strava_tokens.json"
        token_path.write_text(
            json.dumps(asdict(token_set), indent=2, sort_keys=True), encoding="utf-8"
        )

    def load_cached_stream(self, activity_id: int) -> list[tuple[float, float]] | None:
        path = self._settings.data_dir / "streams" / f"{activity_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [
            (float(latitude), float(longitude)) for latitude, longitude in payload.get("points", [])
        ]

    def save_cached_stream(self, activity_id: int, points: list[tuple[float, float]]) -> None:
        self.ensure_storage()
        path = self._settings.data_dir / "streams" / f"{activity_id}.json"
        path.write_text(json.dumps({"points": points}, separators=(",", ":")), encoding="utf-8")

    def selection_cache_path(self, cache_key: str) -> Path:
        return self._settings.data_dir / "nogo_cache" / f"{cache_key}.json"

    def ensure_storage(self) -> None:
        self._settings.data_dir.mkdir(parents=True, exist_ok=True)
        (self._settings.data_dir / "streams").mkdir(parents=True, exist_ok=True)
        (self._settings.data_dir / "nogo_cache").mkdir(parents=True, exist_ok=True)

    def refresh_access_token(self, refresh_token: str, scope: str = "") -> StravaTokenSet:
        payload = {
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        response = self._http_client.post(STRAVA_TOKEN_URL, data=payload, timeout=30.0)
        if response.status_code != 200:
            raise StravaError(
                f"Strava token refresh failed: {response.status_code} {response.text[:300]}"
            )
        token_set = StravaTokenSet.from_payload(response.json(), scope=scope)
        self.save_token_set(token_set)
        return token_set


def _build_activity_record(activity: dict[str, Any]) -> dict[str, Any]:
    summary_polyline = (
        activity.get("map", {}).get("summary_polyline")
        if isinstance(activity.get("map"), dict)
        else None
    )
    summary_points = decode_polyline(summary_polyline) if summary_polyline else []
    bbox = bbox_from_points(summary_points)
    start_latlng = activity.get("start_latlng") or None
    end_latlng = activity.get("end_latlng") or None

    if bbox is None:
        endpoint_points = [
            (float(point[0]), float(point[1]))
            for point in (start_latlng, end_latlng)
            if isinstance(point, list) and len(point) >= 2
        ]
        bbox = bbox_from_points(endpoint_points)

    return {
        "id": int(activity["id"]),
        "name": activity.get("name", ""),
        "sport_type": activity.get("sport_type") or activity.get("type") or "",
        "start_date": activity.get("start_date"),
        "distance_m": float(activity.get("distance", 0)),
        "elevation_gain_m": float(activity.get("total_elevation_gain", 0)),
        "private": bool(activity.get("private", False)),
        "summary_polyline": summary_polyline,
        "bbox": list(bbox) if bbox is not None else None,
        "start_latlng": start_latlng,
        "end_latlng": end_latlng,
    }
