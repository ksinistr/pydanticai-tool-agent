from __future__ import annotations

import json

from app.plugins.caldav.client import CaldavClient
from app.plugins.caldav.models import (
    CreateEventRequest,
    DeleteEventRequest,
    EventRecord,
    GetEventRequest,
    ListEventsRequest,
    MutationRecord,
    UpdateEventRequest,
    to_rfc3339,
)


class CaldavService:
    def __init__(self, client: CaldavClient) -> None:
        self._client = client

    def list_calendars(self) -> str:
        payload = {
            "calendars": [
                {
                    "calendar_id": calendar.calendar_id,
                    "name": calendar.name,
                }
                for calendar in self._client.discover_calendars()
            ]
        }
        return _to_json(payload)

    def list_events(self, request: ListEventsRequest) -> str:
        payload = {
            "calendar_id": request.calendar_id,
            "from": to_rfc3339(request.from_datetime),
            "to": to_rfc3339(request.to_datetime),
            "events": [_event_payload(event) for event in self._client.list_events(request)],
        }
        return _to_json(payload)

    def get_event(self, request: GetEventRequest) -> str:
        return _to_json(_event_payload(self._client.get_event(request)))

    def create_event(self, request: CreateEventRequest) -> str:
        return _to_json(_mutation_payload(self._client.create_event(request)))

    def update_event(self, request: UpdateEventRequest) -> str:
        return _to_json(_mutation_payload(self._client.update_event(request)))

    def delete_event(self, request: DeleteEventRequest) -> str:
        return _to_json(
            _mutation_payload(self._client.delete_event(request.calendar_id, request.event_id))
        )


def _event_payload(event: EventRecord) -> dict:
    payload = {
        "all_day": event.all_day,
        "calendar_id": event.calendar_id,
        "end": to_rfc3339(event.end),
        "event_id": event.event_id,
        "start": to_rfc3339(event.start),
        "title": event.title,
        "uid": event.uid,
    }
    if event.description:
        payload["description"] = event.description
    return payload


def _mutation_payload(result: MutationRecord) -> dict:
    payload = {
        "action": result.action,
        "calendar_id": result.calendar_id,
        "message": result.message,
    }
    if result.event_id:
        payload["event_id"] = result.event_id
    if result.uid:
        payload["uid"] = result.uid
    if result.title:
        payload["title"] = result.title
    return payload


def _to_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
