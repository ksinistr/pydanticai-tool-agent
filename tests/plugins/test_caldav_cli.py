from __future__ import annotations

import sys

import pytest

from app.plugins.caldav.cli import main
from app.plugins.caldav.models import CreateEventRequest, ListEventsRequest


class FakeCaldavService:
    def __init__(self) -> None:
        self.last_request = None

    def list_calendars(self) -> str:
        return '{"calendars":[]}'

    def list_events(self, request) -> str:
        self.last_request = request
        return '{"events":[]}'

    def get_event(self, request) -> str:
        self.last_request = request
        return '{"event_id":"demo.ics"}'

    def create_event(self, request) -> str:
        self.last_request = request
        return '{"action":"created"}'

    def update_event(self, request) -> str:
        self.last_request = request
        return '{"action":"updated"}'

    def delete_event(self, request) -> str:
        self.last_request = request
        return '{"action":"deleted"}'


def test_caldav_cli_builds_list_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = FakeCaldavService()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "caldav-tool",
            "events",
            "list",
            "--calendar-id",
            "personal",
            "--from",
            "2026-03-24T00:00:00Z",
            "--to",
            "2026-03-31T23:59:59Z",
        ],
    )

    exit_code = main(service)
    output = capsys.readouterr()

    assert exit_code == 0
    assert output.out.strip() == '{"events":[]}'
    assert isinstance(service.last_request, ListEventsRequest)
    assert service.last_request.calendar_id == "personal"


def test_caldav_cli_builds_create_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = FakeCaldavService()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "caldav-tool",
            "events",
            "create",
            "--calendar-id",
            "personal",
            "--title",
            "Team Sync",
            "--start",
            "2026-03-25T09:00:00Z",
            "--end",
            "2026-03-25T09:30:00Z",
            "--description",
            "Weekly sync",
        ],
    )

    exit_code = main(service)
    output = capsys.readouterr()

    assert exit_code == 0
    assert output.out.strip() == '{"action":"created"}'
    assert isinstance(service.last_request, CreateEventRequest)
    assert service.last_request.title == "Team Sync"
    assert service.last_request.description == "Weekly sync"


def test_caldav_cli_reports_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "caldav-tool",
            "events",
            "create",
            "--calendar-id",
            "personal",
            "--title",
            "Team Sync",
            "--start",
            "2026-03-25T09:00:00Z",
        ],
    )

    with pytest.raises(SystemExit):
        main(FakeCaldavService())

    output = capsys.readouterr()
    assert "--end required when --start is provided" in output.err
