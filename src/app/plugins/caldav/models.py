from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date as dt_date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator


@dataclass(frozen=True, slots=True)
class CalendarRecord:
    calendar_id: str
    name: str
    path: str


@dataclass(frozen=True, slots=True)
class EventRecord:
    calendar_id: str
    event_id: str
    uid: str
    title: str
    description: str
    start: datetime
    end: datetime
    all_day: bool
    sequence: int = 0


@dataclass(frozen=True, slots=True)
class MutationRecord:
    action: str
    calendar_id: str
    event_id: str
    message: str
    uid: str = ""
    title: str = ""


class CaldavSettings(BaseModel):
    server_url: str | None = None
    username: str | None = None
    password: str | None = None
    insecure_skip_verify: bool = False

    @model_validator(mode="after")
    def validate_required_values(self) -> CaldavSettings:
        self.server_url = _clean_optional_text(self.server_url)
        self.username = _clean_optional_text(self.username)
        self.password = _clean_optional_text(self.password)

        missing: list[str] = []
        if not self.server_url:
            missing.append("CALDAV_SERVER_URL")
        if not self.username:
            missing.append("CALDAV_USERNAME")

        if missing:
            names = ", ".join(missing)
            raise ValueError(f"{names} is required to use the CalDAV plugin.")

        return self


class CalendarRequest(BaseModel):
    calendar_id: str = Field(min_length=1)

    @field_validator("calendar_id")
    @classmethod
    def validate_calendar_id(cls, value: str) -> str:
        return _require_text(value, "calendar_id")


class EventRequest(CalendarRequest):
    event_id: str = Field(min_length=1)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        return _require_text(value, "event_id")


class ListEventsRequest(CalendarRequest):
    from_datetime: datetime
    to_datetime: datetime

    @field_validator("from_datetime", "to_datetime", mode="before")
    @classmethod
    def parse_datetime_fields(cls, value: datetime | str) -> datetime:
        return _parse_datetime(value)

    @model_validator(mode="after")
    def validate_range(self) -> ListEventsRequest:
        if self.to_datetime < self.from_datetime:
            raise ValueError("invalid date range: --to must be after --from")
        return self


class GetEventRequest(EventRequest):
    pass


class DeleteEventRequest(EventRequest):
    pass


class CreateEventRequest(CalendarRequest):
    title: str = Field(min_length=1)
    description: str = ""
    start: datetime | None = None
    end: datetime | None = None
    date: dt_date | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _require_text(value, "title")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("start", "end", mode="before")
    @classmethod
    def parse_datetime_fields(cls, value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        return _parse_datetime(value)

    @field_validator("date", mode="before")
    @classmethod
    def parse_date_field(cls, value: dt_date | str | None) -> dt_date | None:
        if value is None:
            return None
        return _parse_date(value)

    @model_validator(mode="after")
    def validate_timing(self) -> CreateEventRequest:
        _validate_event_timing(self.start, self.end, self.date)
        return self


class UpdateEventRequest(EventRequest):
    title: str | None = None
    description: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    date: dt_date | None = None

    @field_validator("title", "description", mode="before")
    @classmethod
    def normalize_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("start", "end", mode="before")
    @classmethod
    def parse_datetime_fields(cls, value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        return _parse_datetime(value)

    @field_validator("date", mode="before")
    @classmethod
    def parse_date_field(cls, value: dt_date | str | None) -> dt_date | None:
        if value is None:
            return None
        return _parse_date(value)

    @model_validator(mode="after")
    def validate_timing(self) -> UpdateEventRequest:
        _validate_event_timing(self.start, self.end, self.date, allow_empty=True)
        return self


def all_day_datetime(value: dt_date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def to_rfc3339(value: datetime) -> str:
    text = value.isoformat(timespec="seconds")
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _require_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if cleaned:
        return cleaned
    raise ValueError(f"{field_name} is required")


def _parse_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Datetime must include a timezone offset.")
        return value

    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Datetime must be ISO 8601 format like 2026-03-25T09:00:00Z.") from exc

    if parsed.tzinfo is None:
        raise ValueError("Datetime must include a timezone offset.")
    return parsed


def _parse_date(value: dt_date | str) -> dt_date:
    if isinstance(value, dt_date) and not isinstance(value, datetime):
        return value

    try:
        return dt_date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("Date must be YYYY-MM-DD format like 2026-03-27.") from exc


def _validate_event_timing(
    start: datetime | None,
    end: datetime | None,
    event_date: dt_date | None,
    allow_empty: bool = False,
) -> None:
    if event_date is not None and (start is not None or end is not None):
        raise ValueError("cannot use --date with --start/--end flags")

    if start is None and end is None:
        if event_date is None and not allow_empty:
            raise ValueError(
                "either --date (for all-day) or --start and --end (for timed) must be provided"
            )
        return

    if start is None:
        raise ValueError("--start required when --end is provided")
    if end is None:
        raise ValueError("--end required when --start is provided")
    if end < start:
        raise ValueError("invalid date range: --end must be after --start")
