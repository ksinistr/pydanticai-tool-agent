from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class LocationSearchRequest(BaseModel):
    query: str = Field(min_length=2)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def normalize_country_code(self) -> LocationSearchRequest:
        if self.country_code:
            self.country_code = self.country_code.upper()
        return self


class ForecastRequest(BaseModel):
    latitude: float | None = None
    longitude: float | None = None
    hours: int | None = Field(default=None, ge=1, le=168)
    days: int | None = Field(default=None, ge=1, le=16)

    @model_validator(mode="after")
    def validate_inputs(self) -> ForecastRequest:
        if self.latitude is None or self.longitude is None:
            raise ValueError("Both latitude and longitude are required.")

        if self.hours is not None and self.days is not None:
            raise ValueError("Use either hours or days, not both.")

        if self.hours is None and self.days is None:
            self.hours = 12

        return self
