from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
import secrets
import time
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import httpx

from app.plugins.caldav.ics import (
    EventParseError,
    RecurringEventError,
    build_event_calendar,
    parse_event,
)
from app.plugins.caldav.models import (
    CalendarRecord,
    CaldavSettings,
    CreateEventRequest,
    EventRecord,
    GetEventRequest,
    ListEventsRequest,
    MutationRecord,
    UpdateEventRequest,
    all_day_datetime,
)

DAV_NS = "DAV:"
CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
MULTI_STATUS = 207


class CaldavError(RuntimeError):
    pass


class CaldavClient:
    def __init__(
        self,
        settings: CaldavSettings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._collection_url = _normalize_collection_url(settings.server_url or "")
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            auth=httpx.BasicAuth(settings.username or "", settings.password or ""),
            follow_redirects=True,
            timeout=30.0,
            verify=not settings.insecure_skip_verify,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def discover_calendars(self) -> list[CalendarRecord]:
        principal_path = self._find_current_user_principal()
        home_set_path = self._find_calendar_home_set(principal_path)
        calendars = self._find_calendars(home_set_path)

        duplicates = Counter(calendar.calendar_id for calendar in calendars)
        repeated = {calendar_id: count for calendar_id, count in duplicates.items() if count > 1}
        if repeated:
            duplicate_list = ", ".join(
                f"{calendar_id} ({count})" for calendar_id, count in repeated.items()
            )
            raise CaldavError(f"duplicate calendar_ids detected: {duplicate_list}")

        return calendars

    def list_events(self, request: ListEventsRequest) -> list[EventRecord]:
        calendar = self._resolve_calendar(request.calendar_id)
        response = self._request(
            "REPORT",
            calendar.path,
            headers={"Depth": "1", "Content-Type": 'text/xml; charset="utf-8"'},
            content=_build_calendar_query_xml(request.from_datetime, request.to_datetime),
            expected_status=MULTI_STATUS,
        )
        root = _parse_xml(response.text)

        events: list[EventRecord] = []
        for response_element in _iter_dav(root, "response"):
            href = _find_text(response_element, DAV_NS, "href")
            if not href:
                continue
            event_id = _event_id_from_href(href)
            calendar_data = _find_calendar_data(response_element)
            if not calendar_data:
                continue
            try:
                event = parse_event(request.calendar_id, event_id, calendar_data)
            except (EventParseError, RecurringEventError):
                continue
            events.append(event)

        return events

    def get_event(self, request: GetEventRequest) -> EventRecord:
        _validate_event_id(request.event_id)
        calendar = self._resolve_calendar(request.calendar_id)
        response = self._request("GET", _join_path(calendar.path, request.event_id))
        try:
            return parse_event(request.calendar_id, request.event_id, response.text)
        except RecurringEventError as exc:
            raise CaldavError(str(exc)) from exc
        except EventParseError as exc:
            raise CaldavError(f"failed to parse event: {exc}") from exc

    def create_event(self, request: CreateEventRequest) -> MutationRecord:
        calendar = self._resolve_calendar(request.calendar_id)
        uid = _generate_uid()
        event_id = _generate_event_id(request.title)
        start, end, all_day = _resolve_request_timing(request.date, request.start, request.end)
        payload = build_event_calendar(uid, request.title, request.description, all_day, start, end)
        self._request(
            "PUT",
            _join_path(calendar.path, event_id),
            headers={"Content-Type": "text/calendar; charset=utf-8"},
            content=payload,
            expected_status=(200, 201, 204),
        )
        return MutationRecord(
            action="created",
            calendar_id=request.calendar_id,
            event_id=event_id,
            uid=uid,
            title=request.title,
            message=f"Event '{request.title}' created successfully",
        )

    def update_event(self, request: UpdateEventRequest) -> MutationRecord:
        _validate_event_id(request.event_id)
        calendar = self._resolve_calendar(request.calendar_id)
        event_path = _join_path(calendar.path, request.event_id)
        response = self._request("GET", event_path)
        try:
            current = parse_event(request.calendar_id, request.event_id, response.text)
        except RecurringEventError as exc:
            raise CaldavError(str(exc)) from exc
        except EventParseError as exc:
            raise CaldavError(f"failed to parse current event: {exc}") from exc

        title = current.title if request.title is None else request.title
        description = current.description if request.description is None else request.description

        if request.date is not None:
            start = all_day_datetime(request.date)
            end = start
            all_day = True
        elif request.start is not None and request.end is not None:
            start = request.start
            end = request.end
            all_day = False
        else:
            start = current.start
            end = current.end
            all_day = current.all_day

        payload = build_event_calendar(
            current.uid,
            title,
            description,
            all_day,
            start,
            end,
            sequence=current.sequence + 1,
        )
        self._request(
            "PUT",
            event_path,
            headers={"Content-Type": "text/calendar; charset=utf-8"},
            content=payload,
            expected_status=(200, 201, 204),
        )
        return MutationRecord(
            action="updated",
            calendar_id=request.calendar_id,
            event_id=request.event_id,
            uid=current.uid,
            title=title,
            message=f"Event '{title}' updated successfully",
        )

    def delete_event(self, calendar_id: str, event_id: str) -> MutationRecord:
        _validate_event_id(event_id)
        calendar = self._resolve_calendar(calendar_id)
        self._request(
            "DELETE",
            _join_path(calendar.path, event_id),
            expected_status=(200, 204),
        )
        return MutationRecord(
            action="deleted",
            calendar_id=calendar_id,
            event_id=event_id,
            message=f"Event '{event_id}' deleted successfully",
        )

    def _resolve_calendar(self, calendar_id: str) -> CalendarRecord:
        for calendar in self.discover_calendars():
            if calendar.calendar_id == calendar_id:
                return calendar
        raise CaldavError(f"calendar '{calendar_id}' not found")

    def _find_current_user_principal(self) -> str:
        response = self._request(
            "PROPFIND",
            self._collection_url,
            headers={"Depth": "0", "Content-Type": 'text/xml; charset="utf-8"'},
            content=_current_user_principal_xml(),
            expected_status=MULTI_STATUS,
        )
        root = _parse_xml(response.text)

        for response_element in _iter_dav(root, "response"):
            for propstat in response_element.findall(f"{{{DAV_NS}}}propstat"):
                prop = propstat.find(f"{{{DAV_NS}}}prop")
                if prop is None:
                    continue
                current_user_principal = prop.find(f"{{{DAV_NS}}}current-user-principal")
                if current_user_principal is None:
                    continue
                unauthenticated = current_user_principal.find(f"{{{DAV_NS}}}unauthenticated")
                if unauthenticated is not None:
                    raise CaldavError("webdav: unauthenticated")
                href = current_user_principal.findtext(f"{{{DAV_NS}}}href")
                if href:
                    return _normalize_href_path(href)

        raise CaldavError("webdav: current-user-principal not found")

    def _find_calendar_home_set(self, principal_path: str) -> str:
        response = self._request(
            "PROPFIND",
            principal_path,
            headers={"Depth": "0", "Content-Type": 'text/xml; charset="utf-8"'},
            content=_calendar_home_set_xml(),
            expected_status=MULTI_STATUS,
        )
        root = _parse_xml(response.text)

        for response_element in _iter_dav(root, "response"):
            for propstat in response_element.findall(f"{{{DAV_NS}}}propstat"):
                prop = propstat.find(f"{{{DAV_NS}}}prop")
                if prop is None:
                    continue
                home_set = prop.find(f"{{{CALDAV_NS}}}calendar-home-set")
                if home_set is None:
                    continue
                href = home_set.findtext(f"{{{DAV_NS}}}href")
                if href:
                    return _normalize_href_path(href)

        raise CaldavError("failed to discover calendar home set")

    def _find_calendars(self, home_set_path: str) -> list[CalendarRecord]:
        response = self._request(
            "PROPFIND",
            home_set_path,
            headers={"Depth": "1", "Content-Type": 'text/xml; charset="utf-8"'},
            content=_calendar_discovery_xml(),
            expected_status=MULTI_STATUS,
        )
        root = _parse_xml(response.text)

        calendars: list[CalendarRecord] = []
        for response_element in _iter_dav(root, "response"):
            href = _find_text(response_element, DAV_NS, "href")
            if not href:
                continue

            prop = _find_first_prop(response_element)
            if prop is None:
                continue

            resource_type = prop.find(f"{{{DAV_NS}}}resourcetype")
            if resource_type is None or resource_type.find(f"{{{CALDAV_NS}}}calendar") is None:
                continue

            path = _normalize_href_path(href)
            calendar_id = _calendar_id_from_href(path)
            if not calendar_id:
                continue
            name = _find_text(prop, DAV_NS, "displayname") or calendar_id
            calendars.append(CalendarRecord(calendar_id=calendar_id, name=name, path=path))

        return calendars

    def _request(
        self,
        method: str,
        path_or_url: str,
        headers: dict[str, str] | None = None,
        content: str | None = None,
        expected_status: int | tuple[int, ...] | None = None,
    ) -> httpx.Response:
        target = path_or_url
        if not path_or_url.startswith(("http://", "https://")):
            target = urljoin(self._collection_url, path_or_url)

        try:
            response = self._client.request(method, target, headers=headers, content=content)
        except httpx.HTTPError as exc:
            raise CaldavError(f"CalDAV request failed: {exc}") from exc

        if expected_status is None:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text.strip() or exc.response.reason_phrase
                raise CaldavError(
                    f"CalDAV request failed with HTTP {exc.response.status_code}: {detail}"
                ) from exc
            return response

        allowed = {expected_status} if isinstance(expected_status, int) else set(expected_status)
        if response.status_code not in allowed:
            detail = response.text.strip() or response.reason_phrase
            raise CaldavError(f"CalDAV request failed with HTTP {response.status_code}: {detail}")
        return response


def _normalize_collection_url(server_url: str) -> str:
    parsed = urlparse(server_url)
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return parsed._replace(path=path).geturl()


def _normalize_href_path(href: str) -> str:
    parsed = urlparse(href)
    path = parsed.path or href
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if href.endswith("/") and not path.endswith("/"):
        path += "/"
    return path


def _calendar_id_from_href(href: str) -> str:
    basename = PurePosixPath(href.rstrip("/")).name
    if basename in {"", ".", "/"}:
        return ""
    return basename


def _event_id_from_href(href: str) -> str:
    basename = PurePosixPath(_normalize_href_path(href)).name
    return basename if basename not in {"", ".", "/"} else href


def _validate_event_id(event_id: str) -> None:
    if not event_id:
        raise CaldavError("event_id cannot be empty")
    if event_id in {".", ".."}:
        raise CaldavError(f"invalid event_id: {event_id}")
    if "/" in event_id or "\\" in event_id:
        raise CaldavError(f"invalid event_id: {event_id}")
    if PurePosixPath(event_id).name != event_id:
        raise CaldavError(f"invalid event_id: {event_id}")


def _join_path(base_path: str, event_id: str) -> str:
    if base_path.endswith("/"):
        return base_path + event_id
    return base_path + "/" + event_id


def _resolve_request_timing(
    event_date: date | None,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime, bool]:
    if event_date is not None:
        start_value = all_day_datetime(event_date)
        return start_value, start_value, True

    if start is None or end is None:
        raise CaldavError("either --date or --start and --end must be provided")
    return start, end, False


def _generate_uid() -> str:
    now = datetime.now(UTC)
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}@caldav-cli"


def _generate_event_id(title: str) -> str:
    now_ns = time.time_ns()
    now = datetime.fromtimestamp(now_ns / 1_000_000_000, tz=UTC)
    sanitized = title.lower().replace(" ", "-").replace("_", "-")
    sanitized = "".join(char for char in sanitized if char.isalnum() or char == "-")
    if not sanitized:
        sanitized = "event"
    if len(sanitized) > 50:
        sanitized = sanitized[:50]
    return (
        f"{now.strftime('%Y-%m-%d')}-{now.strftime('%H%M%S')}"
        f"-{now_ns % 1_000_000_000:09d}-{sanitized}.ics"
    )


def _parse_xml(payload: str) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise CaldavError(f"invalid XML response: {exc}") from exc


def _iter_dav(root: ET.Element, name: str) -> list[ET.Element]:
    return root.findall(f".//{{{DAV_NS}}}{name}")


def _find_text(element: ET.Element, namespace: str, name: str) -> str:
    text = element.findtext(f"{{{namespace}}}{name}")
    return text.strip() if isinstance(text, str) else ""


def _find_first_prop(response_element: ET.Element) -> ET.Element | None:
    for propstat in response_element.findall(f"{{{DAV_NS}}}propstat"):
        prop = propstat.find(f"{{{DAV_NS}}}prop")
        if prop is not None:
            return prop
    return None


def _find_calendar_data(response_element: ET.Element) -> str:
    for propstat in response_element.findall(f"{{{DAV_NS}}}propstat"):
        prop = propstat.find(f"{{{DAV_NS}}}prop")
        if prop is None:
            continue
        calendar_data = prop.findtext(f"{{{CALDAV_NS}}}calendar-data")
        if isinstance(calendar_data, str) and calendar_data.strip():
            return calendar_data.strip()
    return ""


def _current_user_principal_xml() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propfind xmlns:D="DAV:">'
        "<D:prop><D:current-user-principal/></D:prop>"
        "</D:propfind>"
    )


def _calendar_home_set_xml() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<D:prop><C:calendar-home-set/></D:prop>"
        "</D:propfind>"
    )


def _calendar_discovery_xml() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<D:prop><D:displayname/><D:resourcetype/></D:prop>"
        "</D:propfind>"
    )


def _build_calendar_query_xml(from_datetime: datetime, to_datetime: datetime) -> str:
    start = from_datetime.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    end = to_datetime.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<D:prop><D:getetag/><C:calendar-data/></D:prop>"
        '<C:filter><C:comp-filter name="VCALENDAR">'
        '<C:comp-filter name="VEVENT">'
        f'<C:time-range start="{start}" end="{end}"/>'
        "</C:comp-filter></C:comp-filter></C:filter>"
        "</C:calendar-query>"
    )
