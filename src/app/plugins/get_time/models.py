from __future__ import annotations

from pydantic import BaseModel


class TimeRequest(BaseModel):
    timezone_name: str | None = None


class TimeResponse(BaseModel):
    iso_datetime: str
    display: str
    timezone_name: str

