from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.plugins.caldav.models import EventRecord, all_day_datetime

ICAL_DATETIME_FORMAT = "%Y%m%dT%H%M%S"
ICAL_DATE_FORMAT = "%Y%m%d"


class EventParseError(ValueError):
    pass


class RecurringEventError(EventParseError):
    pass


@dataclass(frozen=True, slots=True)
class IcsProperty:
    value: str
    params: dict[str, str]


def parse_event(calendar_id: str, event_id: str, payload: str) -> EventRecord:
    properties = _parse_vevent_properties(payload)

    if _get_property(properties, "RRULE") is not None:
        raise RecurringEventError("recurring events are not supported in v1")

    dtstart = _require_property(properties, "DTSTART")
    dtend = _get_property(properties, "DTEND")
    duration = _get_property(properties, "DURATION")
    summary = _get_property(properties, "SUMMARY")
    description_prop = _get_property(properties, "DESCRIPTION")
    uid_prop = _get_property(properties, "UID")

    title = _unescape_text(summary.value) if summary else ""
    description = _unescape_text(description_prop.value) if description_prop else ""
    uid = uid_prop.value if uid_prop else ""
    sequence = _parse_sequence(_get_property(properties, "SEQUENCE"))

    all_day = _is_all_day(dtstart)
    if all_day:
        start = all_day_datetime(_parse_date_value(dtstart.value))
        if dtend is not None:
            end = all_day_datetime(_parse_date_value(dtend.value)) - timedelta(days=1)
        elif duration is not None:
            end = start + _parse_duration(duration.value)
        else:
            end = start
    else:
        start = _parse_datetime_value(dtstart)
        if dtend is not None:
            end = _parse_datetime_value(dtend)
        elif duration is not None:
            end = start + _parse_duration(duration.value)
        else:
            raise EventParseError("event missing DTEND or DURATION")

    if end < start:
        raise EventParseError(f"event end time ({end}) is before start time ({start})")

    return EventRecord(
        calendar_id=calendar_id,
        event_id=event_id,
        uid=uid,
        title=title,
        description=description,
        start=start,
        end=end,
        all_day=all_day,
        sequence=sequence,
    )


def build_event_calendar(
    uid: str,
    title: str,
    description: str,
    all_day: bool,
    start: datetime,
    end: datetime,
    sequence: int = 0,
) -> str:
    dtstamp = datetime.now(UTC).strftime(ICAL_DATETIME_FORMAT) + "Z"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//caldav-cli//caldav-cli//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{_escape_text(title)}",
        f"DTSTAMP:{dtstamp}",
    ]

    if description:
        lines.append(f"DESCRIPTION:{_escape_text(description)}")
    if sequence > 0:
        lines.append(f"SEQUENCE:{sequence}")

    if all_day:
        lines.append(f"DTSTART;VALUE=DATE:{start.date().strftime(ICAL_DATE_FORMAT)}")
        lines.append(
            f"DTEND;VALUE=DATE:{(end.date() + timedelta(days=1)).strftime(ICAL_DATE_FORMAT)}"
        )
    else:
        lines.extend(_format_datetime_property("DTSTART", start))
        lines.extend(_format_datetime_property("DTEND", end))

    lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
    return "\r\n".join(lines)


def _parse_vevent_properties(payload: str) -> dict[str, list[IcsProperty]]:
    properties: dict[str, list[IcsProperty]] = {}
    in_event = False

    for line in _unfold_lines(payload):
        if line == "BEGIN:VEVENT":
            in_event = True
            continue
        if line == "END:VEVENT":
            return properties
        if not in_event or ":" not in line:
            continue

        left, value = line.split(":", 1)
        parts = left.split(";")
        name = parts[0].upper()
        params: dict[str, str] = {}
        for part in parts[1:]:
            key, _, param_value = part.partition("=")
            if key and param_value:
                params[key.upper()] = param_value
        properties.setdefault(name, []).append(IcsProperty(value=value, params=params))

    raise EventParseError("no VEVENT found in iCalendar")


def _unfold_lines(payload: str) -> list[str]:
    unfolded: list[str] = []
    for raw_line in payload.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            continue
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
            continue
        unfolded.append(line)
    return unfolded


def _get_property(
    properties: dict[str, list[IcsProperty]],
    name: str,
) -> IcsProperty | None:
    items = properties.get(name)
    if not items:
        return None
    return items[0]


def _require_property(properties: dict[str, list[IcsProperty]], name: str) -> IcsProperty:
    prop = _get_property(properties, name)
    if prop is None:
        raise EventParseError(f"event missing {name}")
    return prop


def _is_all_day(prop: IcsProperty) -> bool:
    if prop.params.get("VALUE") == "DATE":
        return True
    if len(prop.value) != 8:
        return False
    try:
        _parse_date_value(prop.value)
    except EventParseError:
        return False
    return True


def _parse_date_value(value: str) -> date:
    try:
        return datetime.strptime(value, ICAL_DATE_FORMAT).date()
    except ValueError as exc:
        raise EventParseError(f"failed to parse all-day date: {value}") from exc


def _parse_datetime_value(prop: IcsProperty) -> datetime:
    value = prop.value
    tzid = prop.params.get("TZID")

    if tzid:
        try:
            zone = ZoneInfo(tzid)
        except ZoneInfoNotFoundError as exc:
            raise EventParseError(f"non-IANA timezone ID '{tzid}' is not supported in v1") from exc

        try:
            parsed = datetime.strptime(value, ICAL_DATETIME_FORMAT)
        except ValueError as exc:
            raise EventParseError(f"failed to parse datetime with TZID {tzid}: {value}") from exc
        return parsed.replace(tzinfo=zone)

    if value.endswith("Z"):
        try:
            return datetime.strptime(value[:-1], ICAL_DATETIME_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass

    try:
        return datetime.strptime(value, ICAL_DATETIME_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise EventParseError(f"failed to parse datetime: {value}") from exc


def _parse_duration(value: str) -> timedelta:
    match = re.fullmatch(
        r"P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value,
    )
    if match is None:
        raise EventParseError(f"invalid duration format: {value}")

    weeks = int(match.group("weeks") or 0)
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return timedelta(
        weeks=weeks,
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
    )


def _parse_sequence(prop: IcsProperty | None) -> int:
    if prop is None or not prop.value:
        return 0
    try:
        return int(prop.value)
    except ValueError:
        return 0


def _escape_text(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace("\n", "\\n")
    escaped = escaped.replace(";", "\\;")
    escaped = escaped.replace(",", "\\,")
    return escaped


def _unescape_text(value: str) -> str:
    unescaped = value.replace("\\N", "\n").replace("\\n", "\n")
    unescaped = unescaped.replace("\\,", ",").replace("\\;", ";")
    return unescaped.replace("\\\\", "\\")


def _format_datetime_property(name: str, value: datetime) -> list[str]:
    if value.tzinfo is None:
        utc_value = value.replace(tzinfo=UTC)
        return [f"{name}:{utc_value.strftime(ICAL_DATETIME_FORMAT)}Z"]

    if value.utcoffset() == timedelta(0):
        utc_value = value.astimezone(UTC)
        return [f"{name}:{utc_value.strftime(ICAL_DATETIME_FORMAT)}Z"]

    zone_key = getattr(value.tzinfo, "key", None)
    if zone_key:
        local_value = value.astimezone(value.tzinfo)
        return [f"{name};TZID={zone_key}:{local_value.strftime(ICAL_DATETIME_FORMAT)}"]

    utc_value = value.astimezone(UTC)
    return [f"{name}:{utc_value.strftime(ICAL_DATETIME_FORMAT)}Z"]
