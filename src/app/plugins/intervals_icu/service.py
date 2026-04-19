from __future__ import annotations

from datetime import date, datetime, timedelta
import json

from app.plugins.intervals_icu.client import IntervalsIcuClient
from app.plugins.intervals_icu.models import ActivitiesQuery, WellnessQuery

ACTIVITY_FIELDS = (
    "id",
    "start_date_local",
    "type",
    "name",
    "distance",
    "moving_time",
    "total_elevation_gain",
    "average_heartrate",
    "calories",
    "icu_training_load",
)

WELLNESS_FIELDS = (
    "id",
    "ctl",
    "atl",
    "ctlLoad",
    "atlLoad",
    "rampRate",
    "weight",
    "restingHR",
    "hrv",
    "sleepSecs",
    "sleepScore",
    "fatigue",
    "stress",
    "mood",
    "motivation",
    "readiness",
    "steps",
    "comments",
)

FITNESS_FIELDS = (
    "id",
    "ctl",
    "atl",
    "ctlLoad",
    "atlLoad",
    "rampRate",
    "readiness",
    "fatigue",
    "motivation",
    "stress",
    "mood",
    "weight",
    "restingHR",
    "hrv",
    "sleepSecs",
    "sleepScore",
)


class IntervalsIcuService:
    def __init__(self, client: IntervalsIcuClient) -> None:
        self._client = client

    def get_wellness(self, query: WellnessQuery) -> str:
        if query.date:
            return _to_json(_compact_dict(self._client.get_wellness_record(query.date)))

        oldest, newest = _resolve_date_range(query.oldest, query.newest, query.limit)
        records = self._client.list_wellness_records(
            oldest=oldest,
            newest=newest,
            fields=WELLNESS_FIELDS,
        )
        result = {
            "oldest": oldest,
            "newest": newest,
            "records": [_compact_dict(record) for record in records[: query.limit]],
        }
        return _to_json(result)

    def list_activities(self, query: ActivitiesQuery) -> str:
        activities = self._client.list_activities(
            oldest=query.oldest,
            newest=query.newest,
            limit=query.limit,
            fields=ACTIVITY_FIELDS,
        )
        result = {
            "oldest": query.oldest,
            "newest": query.newest,
            "count": len(activities),
            "activities": [_compact_dict(activity) for activity in activities],
        }
        return _to_json(result)

    def get_activity(self, activity_id: str, include_intervals: bool = False) -> str:
        payload = self._client.get_activity(activity_id, include_intervals=include_intervals)
        return _to_json(_compact_dict(payload))

    def get_fitness_status(self, date_value: str | None = None) -> str:
        local_date = date_value or _today_local().isoformat()
        payload = self._client.get_wellness_record(local_date)
        result = _pick_dict(payload, FITNESS_FIELDS)
        result["date"] = local_date

        form = _calculate_form(payload)
        if form is not None:
            result["form"] = form

        return _to_json(_compact_dict(result))

    def get_weekly_load_progress(
        self,
        week_start: str | None = None,
        week_end: str | None = None,
    ) -> str:
        oldest, newest = _resolve_week_range(week_start, week_end)
        events = self._client.list_events(oldest=oldest, newest=newest, limit=500)
        activities = self._client.list_activities(
            oldest=oldest,
            newest=newest,
            limit=200,
            fields=ACTIVITY_FIELDS,
        )

        target_events = [event for event in events if event.get("category") == "TARGET"]
        plan_events = [event for event in events if event.get("category") == "PLAN"]
        note_events = [event for event in events if event.get("category") == "NOTE"]
        planned_load_by_type = _sum_by_type(target_events, _target_load)
        completed_load_by_type = _sum_by_type(activities, _actual_load)
        completed_total = _numeric_total(completed_load_by_type.values())

        by_type = _build_load_by_type(planned_load_by_type, completed_load_by_type)
        plan = _compact_dict(
            {
                "blocks": [_compact_dict(_summarize_plan_event(event)) for event in plan_events],
                "notes": [_compact_dict(_summarize_note_event(event)) for event in note_events],
            }
        )

        result = {
            "week": {
                "start": oldest,
                "end": newest,
            },
            "load": _compact_dict(
                {
                    "all_activities": {
                        "completed": completed_total,
                    },
                    "by_type": by_type,
                }
            ),
            "plan": plan,
        }
        return _to_json(_compact_dict(result))


def _resolve_date_range(
    oldest: str | None,
    newest: str | None,
    limit: int,
) -> tuple[str, str]:
    newest_date = date.fromisoformat(newest) if newest else _today_local()
    oldest_date = date.fromisoformat(oldest) if oldest else newest_date - timedelta(days=limit - 1)
    return oldest_date.isoformat(), newest_date.isoformat()


def _resolve_week_range(week_start: str | None, week_end: str | None) -> tuple[str, str]:
    if week_start and week_end:
        return week_start, week_end

    if week_start:
        start = date.fromisoformat(week_start)
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()

    if week_end:
        end = date.fromisoformat(week_end)
        start = end - timedelta(days=6)
        return start.isoformat(), end.isoformat()

    today = _today_local()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _today_local() -> date:
    return datetime.now().astimezone().date()


def _pick_dict(payload: dict, fields: tuple[str, ...]) -> dict:
    return {field: payload[field] for field in fields if field in payload}


def _calculate_form(payload: dict) -> float | None:
    ctl = payload.get("ctl")
    atl = payload.get("atl")
    if isinstance(ctl, (int, float)) and isinstance(atl, (int, float)):
        return round(ctl - atl, 2)
    return None


def _target_load(payload: dict) -> int | float | None:
    value = payload.get("load_target")
    if isinstance(value, (int, float)):
        return value
    return None


def _actual_load(payload: dict) -> int | float | None:
    value = payload.get("icu_training_load")
    if isinstance(value, (int, float)):
        return value
    return None


def _sum_by_type(records: list[dict], value_getter) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    for record in records:
        value = value_getter(record)
        if value is None:
            continue
        record_type = _extract_type(record)
        result[record_type] = round(result.get(record_type, 0) + value, 2)
    return result


def _extract_day(payload: dict) -> str:
    start_date_local = payload.get("start_date_local")
    if isinstance(start_date_local, str) and len(start_date_local) >= 10:
        return start_date_local[:10]
    record_id = payload.get("id")
    if isinstance(record_id, str) and len(record_id) >= 10:
        return record_id[:10]
    return "unknown"


def _extract_type(payload: dict) -> str:
    value = payload.get("type")
    if isinstance(value, str) and value:
        return value
    return "unknown"


def _completion_pct(planned_total: int | float, completed_total: int | float) -> float | None:
    if planned_total <= 0:
        return None
    return round(completed_total / planned_total * 100, 2)


def _build_load_by_type(
    planned_by_type: dict[str, int | float],
    completed_by_type: dict[str, int | float],
) -> dict[str, dict[str, int | float]]:
    result: dict[str, dict[str, int | float]] = {}
    all_types = set(planned_by_type) | set(completed_by_type)

    for activity_type in sorted(all_types):
        completed = completed_by_type.get(activity_type)
        planned = planned_by_type.get(activity_type)

        item: dict[str, int | float] = {}
        if isinstance(completed, (int, float)) and completed > 0:
            item["completed"] = completed
        if isinstance(planned, (int, float)) and planned > 0:
            item["planned"] = planned

        completion_pct = _completion_pct(
            planned if isinstance(planned, (int, float)) else 0,
            completed if isinstance(completed, (int, float)) else 0,
        )
        if completion_pct is not None and completion_pct > 0:
            item["completion_pct"] = completion_pct

        if item:
            result[activity_type] = item

    return result


def _numeric_total(values) -> int | float:
    total = 0
    for value in values:
        if isinstance(value, (int, float)):
            total += value
    return round(total, 2)


def _summarize_plan_event(payload: dict) -> dict:
    return {
        "type": payload.get("type"),
        "name": payload.get("name"),
        "start": payload.get("start_date_local"),
        "end": payload.get("end_date_local"),
        "tags": payload.get("tags"),
        "description": payload.get("description"),
    }


def _summarize_note_event(payload: dict) -> dict:
    return {
        "name": payload.get("name"),
        "start": payload.get("start_date_local"),
        "end": payload.get("end_date_local"),
        "description": payload.get("description"),
    }


def _compact_dict(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value not in (None, [], {}, "")}


def _to_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
