from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class WellnessQuery(BaseModel):
    date: str | None = None
    oldest: str | None = None
    newest: str | None = None
    limit: int = Field(default=7, ge=1, le=31)

    @model_validator(mode="after")
    def validate_date_or_range(self) -> WellnessQuery:
        if self.date and (self.oldest or self.newest):
            raise ValueError("Use either date or oldest/newest, not both.")
        return self


class ActivitiesQuery(BaseModel):
    oldest: str
    newest: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
