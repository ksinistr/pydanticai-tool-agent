from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RouteProfile = Literal["road", "gravel", "trekking", "mountain", "mtb", "safety", "shortest"]


class PointToPointRouteRequest(BaseModel):
    start_location: str = Field(min_length=2)
    end_location: str = Field(min_length=2)
    profile: RouteProfile = "gravel"
    route_name: str | None = Field(default=None, max_length=120)


class RoundTripRouteRequest(BaseModel):
    start_location: str = Field(min_length=2)
    max_total_km: float = Field(gt=1, le=500)
    max_elevation_m: float | None = Field(default=None, ge=0, le=10000)
    profile: RouteProfile = "gravel"
    avoid_known_roads: bool = False


class RoutePlannerSettings(BaseModel):
    brouter_url: str = Field(min_length=1)
    output_dir: Path
    geocoder_user_agent: str = Field(min_length=3)


class StravaSettings(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str = "http://localhost/exchange_token"
    data_dir: Path

    @model_validator(mode="after")
    def normalize_values(self) -> StravaSettings:
        if self.client_id is not None:
            self.client_id = self.client_id.strip() or None
        if self.client_secret is not None:
            self.client_secret = self.client_secret.strip() or None
        self.redirect_uri = self.redirect_uri.strip()
        return self

    def missing_auth_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.client_id:
            missing.append("STRAVA_CLIENT_ID")
        if not self.client_secret:
            missing.append("STRAVA_CLIENT_SECRET")
        if not self.redirect_uri:
            missing.append("STRAVA_REDIRECT_URI")
        return missing
