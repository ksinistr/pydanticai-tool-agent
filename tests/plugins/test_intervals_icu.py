from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import AppConfig
from app.plugins.intervals_icu.client import IntervalsIcuClient
from app.plugins.intervals_icu.models import ActivitiesQuery, WellnessQuery
from app.plugins.intervals_icu.plugin import build_plugin
from app.plugins.intervals_icu.service import IntervalsIcuService


def test_intervals_service_lists_activities_with_selected_fields() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(
            200,
            json=[
                {
                    "id": "activity-1",
                    "start_date_local": "2026-04-18T07:00:00Z",
                    "type": "Ride",
                    "name": "Morning Ride",
                    "distance": 42000.0,
                    "moving_time": 5400,
                    "icu_training_load": 82,
                }
            ],
        )

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://intervals.icu",
    )
    client = IntervalsIcuClient(
        athlete_id="athlete-1",
        api_key="secret-key",
        http_client=http_client,
    )
    service = IntervalsIcuService(client)

    payload = json.loads(
        service.list_activities(
            ActivitiesQuery(oldest="2026-04-01", newest="2026-04-19", limit=5)
        )
    )

    assert seen["path"] == "/api/v1/athlete/athlete-1/activities"
    assert seen["query"]["oldest"] == "2026-04-01"
    assert seen["query"]["newest"] == "2026-04-19"
    assert seen["query"]["limit"] == "5"
    assert payload["activities"][0]["name"] == "Morning Ride"


def test_intervals_wellness_query_rejects_date_and_range_together() -> None:
    with pytest.raises(ValueError, match="Use either date or oldest/newest, not both."):
        WellnessQuery(date="2026-04-19", oldest="2026-04-01")


def test_build_intervals_plugin_requires_credentials() -> None:
    config = AppConfig(
        openai_api_key="test-key",
        openai_base_url="https://provider.example.test/v1",
        openai_model="gpt-4.1-mini",
        telegram_bot_token=None,
        telegram_authorized_users=(),
        enabled_plugins=("intervals_icu",),
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

    with pytest.raises(ValueError, match="INTERVALS_ICU_ATHLETE_ID is required"):
        build_plugin(config)


class FakeIntervalsIcuClient:
    def get_wellness_record(self, date: str) -> dict:
        assert date == "2026-04-19"
        return {
            "id": "2026-04-19",
            "ctl": 71.5,
            "atl": 79.25,
            "readiness": 63,
            "fatigue": 72,
            "sleepScore": 81,
        }

    def list_events(
        self,
        oldest: str | None = None,
        newest: str | None = None,
        categories: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        assert oldest == "2026-04-14"
        assert newest == "2026-04-20"
        assert categories is None
        assert limit == 500
        return [
            {
                "category": "TARGET",
                "start_date_local": "2026-04-14T00:00:00Z",
                "end_date_local": "2026-04-15T00:00:00Z",
                "load_target": 140,
                "type": "Ride",
                "name": "Weekly",
            },
            {
                "category": "TARGET",
                "start_date_local": "2026-04-14T00:00:00Z",
                "end_date_local": "2026-04-15T00:00:00Z",
                "load_target": 40,
                "type": "Run",
                "name": "Weekly",
            },
            {
                "category": "PLAN",
                "id": 99,
                "type": "Ride",
                "name": "Base Block",
                "start_date_local": "2026-04-14T00:00:00Z",
                "end_date_local": "2026-04-21T00:00:00Z",
                "tags": ["Base"],
                "color": "4caf50",
                "description": "Aerobic capacity",
            },
            {
                "category": "NOTE",
                "id": 100,
                "name": "Recovery Week",
                "start_date_local": "2026-04-14T00:00:00Z",
                "end_date_local": "2026-04-15T00:00:00Z",
                "description": "Take it easy",
            },
        ]

    def list_activities(
        self,
        oldest: str,
        newest: str | None = None,
        limit: int | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> list[dict]:
        assert oldest == "2026-04-14"
        assert newest == "2026-04-20"
        assert limit == 200
        assert fields is not None
        return [
            {"start_date_local": "2026-04-14T07:00:00Z", "icu_training_load": 55, "type": "Ride"},
            {"start_date_local": "2026-04-18T07:00:00Z", "icu_training_load": 45, "type": "Walk"},
        ]


def test_intervals_service_computes_fitness_status_form() -> None:
    service = IntervalsIcuService(FakeIntervalsIcuClient())

    payload = json.loads(service.get_fitness_status("2026-04-19"))

    assert payload["date"] == "2026-04-19"
    assert payload["ctl"] == 71.5
    assert payload["atl"] == 79.25
    assert payload["form"] == -7.75
    assert payload["readiness"] == 63


def test_intervals_service_builds_weekly_load_progress() -> None:
    service = IntervalsIcuService(FakeIntervalsIcuClient())

    payload = json.loads(service.get_weekly_load_progress("2026-04-14", "2026-04-20"))

    assert payload["week"] == {
        "start": "2026-04-14",
        "end": "2026-04-20",
    }
    assert payload["load"]["all_activities"] == {"completed": 100}
    assert payload["load"]["by_type"]["Ride"] == {
        "completed": 55,
        "planned": 140,
        "completion_pct": 39.29,
    }
    assert payload["load"]["by_type"]["Run"] == {"planned": 40}
    assert payload["load"]["by_type"]["Walk"] == {"completed": 45}
    assert payload["plan"]["blocks"][0] == {
        "type": "Ride",
        "name": "Base Block",
        "start": "2026-04-14T00:00:00Z",
        "end": "2026-04-21T00:00:00Z",
        "tags": ["Base"],
        "description": "Aerobic capacity",
    }
    assert payload["plan"]["notes"][0] == {
        "name": "Recovery Week",
        "start": "2026-04-14T00:00:00Z",
        "end": "2026-04-15T00:00:00Z",
        "description": "Take it easy",
    }
    assert "target_event_count" not in payload
    assert "planned_load_total" not in payload
    assert "completed_load_total" not in payload
