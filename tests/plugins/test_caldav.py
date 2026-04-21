from __future__ import annotations

from datetime import UTC, datetime
from html import escape
import json
from pathlib import Path

import httpx
import pytest
from pydantic_ai import ModelRetry

from app.config import AppConfig
from app.plugins.caldav.client import CaldavClient, CaldavError
from app.plugins.caldav.ics import parse_event
from app.plugins.caldav.models import (
    CaldavSettings,
    CreateEventRequest,
    GetEventRequest,
    ListEventsRequest,
    UpdateEventRequest,
)
from app.plugins.caldav.plugin import CaldavPlugin, build_plugin
from app.plugins.caldav.service import CaldavService


class MockCaldavServer:
    def __init__(self) -> None:
        self.calendar_path = "/dav.php/calendars/alice/personal/"
        self.calendar_entries = [
            (self.calendar_path, "Personal Calendar"),
            ("/dav.php/calendars/alice/work/", "Work Calendar"),
        ]
        self.event_payloads: dict[str, str] = {}
        self.last_report_body = ""
        self.put_requests: list[tuple[str, str]] = []
        self.delete_requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND" and request.url.path in {"/dav.php", "/dav.php/"}:
            return _xml_response(
                _multistatus(
                    _response_with_prop(
                        request.url.path.rstrip("/") + "/",
                        "<D:current-user-principal><D:href>/dav.php/principal/</D:href></D:current-user-principal>",
                    )
                )
            )

        if request.method == "PROPFIND" and request.url.path == "/dav.php/principal/":
            return _xml_response(
                _multistatus(
                    _response_with_prop(
                        "/dav.php/principal/",
                        "<C:calendar-home-set><D:href>/dav.php/calendars/alice/</D:href></C:calendar-home-set>",
                    )
                )
            )

        if request.method == "PROPFIND" and request.url.path == "/dav.php/calendars/alice/":
            return _xml_response(
                _multistatus(
                    *[_calendar_response(path, name) for path, name in self.calendar_entries]
                )
            )

        if request.method == "REPORT" and request.url.path == self.calendar_path:
            self.last_report_body = request.content.decode()
            return _xml_response(
                _multistatus(
                    *[
                        _calendar_object_response(path, payload)
                        for path, payload in self.event_payloads.items()
                        if path.startswith(self.calendar_path)
                    ]
                )
            )

        if request.method == "GET" and request.url.path in self.event_payloads:
            return httpx.Response(200, text=self.event_payloads[request.url.path])

        if request.method == "PUT" and request.url.path.startswith(self.calendar_path):
            payload = request.content.decode()
            self.event_payloads[request.url.path] = payload
            self.put_requests.append((request.url.path, payload))
            return httpx.Response(201)

        if request.method == "DELETE" and request.url.path.startswith(self.calendar_path):
            self.delete_requests.append(request.url.path)
            self.event_payloads.pop(request.url.path, None)
            return httpx.Response(204)

        return httpx.Response(404, text=f"Unhandled request: {request.method} {request.url.path}")


def test_caldav_service_lists_calendars_and_skips_recurring_events() -> None:
    server = MockCaldavServer()
    server.event_payloads = {
        f"{server.calendar_path}team-sync.ics": _timed_event_payload(),
        f"{server.calendar_path}recurring.ics": _recurring_event_payload(),
    }
    service = CaldavService(_build_client(server))

    calendars = json.loads(service.list_calendars())
    payload = json.loads(
        service.list_events(
            ListEventsRequest(
                calendar_id="personal",
                from_datetime="2026-03-24T00:00:00Z",
                to_datetime="2026-03-31T23:59:59Z",
            )
        )
    )

    assert calendars["calendars"] == [
        {"calendar_id": "personal", "name": "Personal Calendar"},
        {"calendar_id": "work", "name": "Work Calendar"},
    ]
    assert '<C:comp-filter name="VEVENT">' in server.last_report_body
    assert (
        '<C:time-range start="20260324T000000Z" end="20260331T235959Z"/>' in server.last_report_body
    )
    assert payload["calendar_id"] == "personal"
    assert payload["events"] == [
        {
            "all_day": False,
            "calendar_id": "personal",
            "description": "Weekly team sync meeting",
            "end": "2026-03-25T09:30:00Z",
            "event_id": "team-sync.ics",
            "start": "2026-03-25T09:00:00Z",
            "title": "Team Sync",
            "uid": "20260325T090000Z-team-sync@example.com",
        }
    ]


def test_caldav_service_gets_all_day_event() -> None:
    server = MockCaldavServer()
    server.event_payloads = {f"{server.calendar_path}day-off.ics": _all_day_event_payload()}
    service = CaldavService(_build_client(server))

    payload = json.loads(
        service.get_event(GetEventRequest(calendar_id="personal", event_id="day-off.ics"))
    )

    assert payload == {
        "all_day": True,
        "calendar_id": "personal",
        "description": "Vacation day",
        "end": "2026-03-27T00:00:00Z",
        "event_id": "day-off.ics",
        "start": "2026-03-27T00:00:00Z",
        "title": "Day Off",
        "uid": "20260327-dayoff@example.com",
    }


def test_caldav_service_keeps_cyrillic_chars_unescaped() -> None:
    server = MockCaldavServer()
    server.event_payloads = {f"{server.calendar_path}rest.ics": _cyrillic_event_payload()}
    service = CaldavService(_build_client(server))

    payload = service.get_event(GetEventRequest(calendar_id="personal", event_id="rest.ics"))

    assert "Отдых перед байкпакингом" in payload
    assert "Полный отдых" in payload
    assert "\\u041e" not in payload


def test_caldav_client_creates_event_with_generated_uid_and_filename() -> None:
    server = MockCaldavServer()
    client = _build_client(server)

    result = client.create_event(
        CreateEventRequest(
            calendar_id="personal",
            title="Team Sync",
            description="Weekly sync",
            start="2026-03-25T09:00:00Z",
            end="2026-03-25T09:30:00Z",
        )
    )

    assert result.action == "created"
    assert result.calendar_id == "personal"
    assert result.uid.endswith("@caldav-cli")
    assert result.event_id.endswith("team-sync.ics")
    assert server.put_requests
    path, payload = server.put_requests[0]
    assert path.endswith(result.event_id)
    parsed = parse_event("personal", result.event_id, payload)
    assert parsed.title == "Team Sync"
    assert parsed.description == "Weekly sync"
    assert parsed.uid == result.uid
    assert parsed.start == datetime(2026, 3, 25, 9, 0, tzinfo=UTC)
    assert parsed.end == datetime(2026, 3, 25, 9, 30, tzinfo=UTC)


def test_caldav_client_updates_event_and_increments_sequence() -> None:
    server = MockCaldavServer()
    existing_path = f"{server.calendar_path}team-sync.ics"
    server.event_payloads = {
        existing_path: (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Baikal//Baikal//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:20260325T090000Z-team-sync@example.com\r\n"
            "SEQUENCE:2\r\n"
            "DTSTART:20260325T090000Z\r\n"
            "DTEND:20260325T093000Z\r\n"
            "SUMMARY:Team Sync\r\n"
            "DESCRIPTION:Weekly team sync meeting\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
    }
    client = _build_client(server)

    result = client.update_event(
        UpdateEventRequest(
            calendar_id="personal",
            event_id="team-sync.ics",
            title="Team Sync Updated",
            start="2026-03-25T10:00:00Z",
            end="2026-03-25T10:30:00Z",
        )
    )

    assert result.action == "updated"
    assert result.uid == "20260325T090000Z-team-sync@example.com"
    assert result.title == "Team Sync Updated"
    _, payload = server.put_requests[-1]
    assert "SEQUENCE:3" in payload
    parsed = parse_event("personal", "team-sync.ics", payload)
    assert parsed.title == "Team Sync Updated"
    assert parsed.uid == "20260325T090000Z-team-sync@example.com"
    assert parsed.start == datetime(2026, 3, 25, 10, 0, tzinfo=UTC)
    assert parsed.end == datetime(2026, 3, 25, 10, 30, tzinfo=UTC)


def test_caldav_client_deletes_event() -> None:
    server = MockCaldavServer()
    server.event_payloads = {f"{server.calendar_path}team-sync.ics": _timed_event_payload()}
    client = _build_client(server)

    result = client.delete_event("personal", "team-sync.ics")

    assert result.action == "deleted"
    assert server.delete_requests == [f"{server.calendar_path}team-sync.ics"]


def test_caldav_client_rejects_duplicate_calendar_ids() -> None:
    server = MockCaldavServer()
    server.calendar_entries = [
        ("/dav.php/calendars/alice/personal/", "Personal"),
        ("/dav.php/calendars/alice/team/personal/", "Team Personal"),
    ]
    client = _build_client(server)

    with pytest.raises(CaldavError, match="duplicate calendar_ids detected"):
        client.discover_calendars()


def test_caldav_client_rejects_invalid_event_id() -> None:
    client = _build_client(MockCaldavServer())

    with pytest.raises(CaldavError, match="invalid event_id"):
        client.get_event(GetEventRequest(calendar_id="personal", event_id="../secret.ics"))


def test_parse_event_rejects_non_iana_tzid() -> None:
    payload = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:test@example.com\r\n"
        "DTSTART;TZID=Office/Desk:20260325T090000\r\n"
        "DTEND;TZID=Office/Desk:20260325T093000\r\n"
        "SUMMARY:Desk Sync\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    with pytest.raises(
        ValueError, match="non-IANA timezone ID 'Office/Desk' is not supported in v1"
    ):
        parse_event("personal", "desk-sync.ics", payload)


def test_build_caldav_plugin_requires_server_and_username() -> None:
    config = AppConfig(
        openai_api_key="test-key",
        openai_base_url="https://provider.example.test/v1",
        openai_model="gpt-4.1-mini",
        openai_temperature=None,
        openai_top_p=None,
        telegram_bot_token=None,
        telegram_authorized_users=(),
        enabled_plugins=("caldav",),
        web_host="127.0.0.1",
        web_port=8000,
        public_base_url="https://agent.example.test",
        intervals_icu_api_key=None,
        intervals_icu_athlete_id=None,
        intervals_icu_base_url="https://intervals.icu",
        route_planner_brouter_url="http://127.0.0.1:17777/brouter",
        strava_client_id=None,
        strava_client_secret=None,
        strava_redirect_uri="http://localhost/exchange_token",
        strava_data_dir=Path("/tmp/strava"),
    )

    with pytest.raises(ValueError, match="CALDAV_SERVER_URL, CALDAV_USERNAME is required"):
        build_plugin(config)


def test_caldav_plugin_builds_requests() -> None:
    service = FakeCaldavService()
    plugin = CaldavPlugin(service, user_timezone="Asia/Nicosia")

    result = plugin.create_caldav_event(
        calendar_id="personal",
        title="Team Sync",
        start="2026-03-25T09:00:00",
        end="2026-03-25T09:30:00",
        description="Weekly sync",
    )

    assert result == "ok"
    assert isinstance(service.last_request, CreateEventRequest)
    assert service.last_request.calendar_id == "personal"
    assert service.last_request.title == "Team Sync"
    assert service.last_request.description == "Weekly sync"
    assert service.last_request.start.isoformat() == "2026-03-25T09:00:00+02:00"
    assert service.last_request.end.isoformat() == "2026-03-25T09:30:00+02:00"


def test_caldav_plugin_accepts_naive_datetimes_in_user_timezone() -> None:
    service = FakeCaldavService()
    plugin = CaldavPlugin(service, user_timezone="Asia/Nicosia")

    result = plugin.list_caldav_events(
        calendar_id="vacation",
        from_datetime="2026-04-01T00:00:00",
        to_datetime="2026-04-30T23:59:59",
    )

    assert result == "ok"
    assert isinstance(service.last_request, ListEventsRequest)
    assert service.last_request.from_datetime.isoformat() == "2026-04-01T00:00:00+03:00"
    assert service.last_request.to_datetime.isoformat() == "2026-04-30T23:59:59+03:00"


def test_caldav_plugin_expands_date_only_month_boundaries() -> None:
    service = FakeCaldavService()
    plugin = CaldavPlugin(service, user_timezone="Asia/Nicosia")

    result = plugin.list_caldav_events(
        calendar_id="vacation",
        from_datetime="2026-04-01",
        to_datetime="2026-04-30",
    )

    assert result == "ok"
    assert isinstance(service.last_request, ListEventsRequest)
    assert service.last_request.from_datetime.isoformat() == "2026-04-01T00:00:00+03:00"
    assert service.last_request.to_datetime.isoformat() == "2026-04-30T23:59:59+03:00"


def test_caldav_plugin_retries_on_invalid_datetime_input() -> None:
    plugin = CaldavPlugin(FakeCaldavService(), user_timezone="Asia/Nicosia")

    with pytest.raises(ModelRetry, match="Use ISO 8601 datetime"):
        plugin.list_caldav_events(
            calendar_id="vacation",
            from_datetime="april first",
            to_datetime="2026-04-30",
        )


def test_caldav_plugin_returns_error_string() -> None:
    plugin = CaldavPlugin(FailingCaldavService())

    result = plugin.list_caldav_calendars()

    assert result == "CalDAV error: boom"


class FakeCaldavService:
    def __init__(self) -> None:
        self.last_request = None

    def list_calendars(self) -> str:
        return "ok"

    def list_events(self, request) -> str:
        self.last_request = request
        return "ok"

    def get_event(self, request) -> str:
        self.last_request = request
        return "ok"

    def create_event(self, request) -> str:
        self.last_request = request
        return "ok"

    def update_event(self, request) -> str:
        self.last_request = request
        return "ok"

    def delete_event(self, request) -> str:
        self.last_request = request
        return "ok"


class FailingCaldavService:
    def list_calendars(self) -> str:
        raise ValueError("boom")


def _build_client(server: MockCaldavServer) -> CaldavClient:
    http_client = httpx.Client(transport=httpx.MockTransport(server.handler), follow_redirects=True)
    return CaldavClient(
        CaldavSettings(
            server_url="https://baikal.example.test/dav.php/",
            username="alice",
            password="secret",
        ),
        http_client=http_client,
    )


def _xml_response(payload: str) -> httpx.Response:
    return httpx.Response(
        207, headers={"Content-Type": "application/xml; charset=utf-8"}, text=payload
    )


def _multistatus(*responses: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        + "".join(responses)
        + "</D:multistatus>"
    )


def _response_with_prop(href: str, inner_xml: str) -> str:
    return (
        "<D:response>"
        f"<D:href>{href}</D:href>"
        "<D:propstat><D:prop>"
        f"{inner_xml}"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        "</D:response>"
    )


def _calendar_response(path: str, name: str) -> str:
    display_name = f"<D:displayname>{escape(name)}</D:displayname>" if name else ""
    return (
        "<D:response>"
        f"<D:href>{path}</D:href>"
        "<D:propstat><D:prop>"
        "<D:resourcetype><D:collection/><C:calendar/></D:resourcetype>"
        f"{display_name}"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        "</D:response>"
    )


def _calendar_object_response(path: str, payload: str) -> str:
    return (
        "<D:response>"
        f"<D:href>{path}</D:href>"
        "<D:propstat><D:prop>"
        f"<C:calendar-data>{escape(payload)}</C:calendar-data>"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        "</D:response>"
    )


def _timed_event_payload() -> str:
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Baikal//Baikal//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:20260325T090000Z-team-sync@example.com\r\n"
        "DTSTART:20260325T090000Z\r\n"
        "DTEND:20260325T093000Z\r\n"
        "SUMMARY:Team Sync\r\n"
        "DESCRIPTION:Weekly team sync meeting\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def _all_day_event_payload() -> str:
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Baikal//Baikal//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:20260327-dayoff@example.com\r\n"
        "DTSTART;VALUE=DATE:20260327\r\n"
        "DTEND;VALUE=DATE:20260328\r\n"
        "SUMMARY:Day Off\r\n"
        "DESCRIPTION:Vacation day\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def _recurring_event_payload() -> str:
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:recurring@example.com\r\n"
        "DTSTART:20260325T090000Z\r\n"
        "DTEND:20260325T093000Z\r\n"
        "RRULE:FREQ=WEEKLY\r\n"
        "SUMMARY:Recurring Sync\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def _cyrillic_event_payload() -> str:
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Baikal//Baikal//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:rest@example.com\r\n"
        "DTSTART;VALUE=DATE:20260408\r\n"
        "DTEND;VALUE=DATE:20260409\r\n"
        "SUMMARY:Отдых перед байкпакингом\r\n"
        "DESCRIPTION:Полный отдых, ранний ужин и отбой\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
