from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.plugins.route_planner.geometry import (
    bbox_from_points,
    bboxes_intersect,
    buffer_polyline,
    build_radial_polygon,
    clip_polyline_to_polygon,
    decode_polyline,
    downsample_polyline,
    point_in_polygon,
    polyline_length_m,
)
from app.plugins.route_planner.routing import BrouterPolygonNogo, RoutePlannerClient
from app.plugins.route_planner.strava import StravaService


SUMMARY_SPACING_M = 60.0
NOGO_TRACK_SPACING_M = 90.0
NOGO_POLYGON_SPACING_M = 140.0
MIN_CLIPPED_SEGMENT_M = 180.0
MAX_NOGO_POLYGONS = 60
MAX_STRAVA_QUERY_CHARS = 5500
SEARCH_RADIUS_EXTRA_RATIO = 0.10
SEARCH_RADIUS_MIN_EXTRA_KM = 1.0
SOFT_CORRIDOR_M = 28.0
SOFT_WEIGHT = 2.5
SELECTION_BUDGET_LONLATS = "32.42316,34.77440|32.38121,34.80330|32.46511,34.80330|32.42316,34.77440"
SELECTION_BUDGET_PROFILE = "trekking"


@dataclass(slots=True)
class StravaNogoSelection:
    polygons: list[BrouterPolygonNogo]
    search_polygon: list[tuple[float, float]]
    search_radius_km: float
    candidate_activities: int
    clipped_segments: int


def build_round_trip_strava_nogos(
    strava_service: StravaService,
    route_client: RoutePlannerClient,
    start_coords: tuple[float, float],
    max_total_km: float,
    radii_km: list[float],
) -> StravaNogoSelection:
    metadata = strava_service.load_cached_activities()
    if not metadata:
        strava_service.sync_all_activities()
        metadata = strava_service.load_cached_activities()
    if not metadata:
        return StravaNogoSelection([], [], 0.0, 0, 0)

    search_radius_km = _derive_search_radius_km(max_total_km, radii_km)
    search_polygon = build_radial_polygon(
        start_coords[0], start_coords[1], search_radius_km, vertex_count=24
    )
    search_bbox = bbox_from_points(search_polygon)
    cache_key = _build_selection_cache_key(strava_service, start_coords, search_radius_km)
    cached_selection = _load_selection_cache(strava_service, cache_key)
    if cached_selection is not None:
        return cached_selection

    candidate_records = [
        record
        for record in metadata
        if _record_intersects_search_area(record, search_polygon, search_bbox)
    ]

    scored_polygons: list[tuple[float, BrouterPolygonNogo]] = []
    clipped_segments = 0
    for record in candidate_records:
        activity_id = int(record["id"])
        points = _summary_points(record)
        if len(points) < 2:
            points = strava_service.ensure_activity_stream(activity_id)
        if len(points) < 2:
            continue
        clipped_tracks = clip_polyline_to_polygon(points, search_polygon)
        if not clipped_tracks:
            continue

        for clipped_track in clipped_tracks:
            simplified_track = downsample_polyline(clipped_track, NOGO_TRACK_SPACING_M)
            length_m = polyline_length_m(simplified_track)
            if length_m < MIN_CLIPPED_SEGMENT_M:
                continue
            polygon = buffer_polyline(simplified_track, SOFT_CORRIDOR_M)
            polygon = _simplify_nogo_polygon(polygon)
            if len(polygon) < 4:
                continue
            scored_polygons.append(
                (length_m, BrouterPolygonNogo(points=polygon, weight=SOFT_WEIGHT))
            )
            clipped_segments += 1

    scored_polygons.sort(key=lambda item: item[0], reverse=True)
    polygons = _select_polygons_with_budget(route_client, scored_polygons)
    selection = StravaNogoSelection(
        polygons=polygons,
        search_polygon=search_polygon,
        search_radius_km=search_radius_km,
        candidate_activities=len(candidate_records),
        clipped_segments=clipped_segments,
    )
    _save_selection_cache(strava_service, cache_key, selection)
    return selection


def _derive_search_radius_km(max_total_km: float, radii_km: list[float]) -> float:
    base_radius = max(radii_km) if radii_km else max_total_km * 0.2
    return base_radius + max(SEARCH_RADIUS_MIN_EXTRA_KM, max_total_km * SEARCH_RADIUS_EXTRA_RATIO)


def _build_selection_cache_key(
    strava_service: StravaService,
    start_coords: tuple[float, float],
    search_radius_km: float,
) -> str:
    metadata_path = strava_service.activities_metadata_path()
    metadata_version = metadata_path.stat().st_mtime_ns if metadata_path.exists() else 0
    payload = (
        f"lat={start_coords[0]:.5f}|"
        f"lon={start_coords[1]:.5f}|"
        f"radius={search_radius_km:.2f}|"
        f"metadata={metadata_version}|"
        f"soft={SOFT_CORRIDOR_M}:{SOFT_WEIGHT}|"
        f"max_polygons={MAX_NOGO_POLYGONS}|"
        f"max_query_chars={MAX_STRAVA_QUERY_CHARS}|"
        f"track_spacing={NOGO_TRACK_SPACING_M}|"
        f"polygon_spacing={NOGO_POLYGON_SPACING_M}"
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _load_selection_cache(
    strava_service: StravaService,
    cache_key: str,
) -> StravaNogoSelection | None:
    cache_path = strava_service.selection_cache_path(cache_key)
    if not cache_path.exists():
        return None
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    return StravaNogoSelection(
        polygons=[
            BrouterPolygonNogo(
                points=[
                    (float(latitude), float(longitude)) for latitude, longitude in polygon["points"]
                ],
                weight=float(polygon["weight"]) if polygon.get("weight") is not None else None,
            )
            for polygon in payload.get("polygons", [])
        ],
        search_polygon=[
            (float(latitude), float(longitude))
            for latitude, longitude in payload.get("search_polygon", [])
        ],
        search_radius_km=float(payload.get("search_radius_km", 0.0)),
        candidate_activities=int(payload.get("candidate_activities", 0)),
        clipped_segments=int(payload.get("clipped_segments", 0)),
    )


def _save_selection_cache(
    strava_service: StravaService,
    cache_key: str,
    selection: StravaNogoSelection,
) -> None:
    strava_service.ensure_storage()
    cache_path = strava_service.selection_cache_path(cache_key)
    payload = {
        "polygons": [
            {
                "points": polygon.points,
                "weight": polygon.weight,
            }
            for polygon in selection.polygons
        ],
        "search_polygon": selection.search_polygon,
        "search_radius_km": selection.search_radius_km,
        "candidate_activities": selection.candidate_activities,
        "clipped_segments": selection.clipped_segments,
    }
    cache_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def _record_intersects_search_area(
    record: dict[str, Any],
    search_polygon: list[tuple[float, float]],
    search_bbox: tuple[float, float, float, float] | None,
) -> bool:
    bbox = _record_bbox(record)
    if bbox is not None and not bboxes_intersect(search_bbox, bbox):
        return False

    summary_polyline = record.get("summary_polyline")
    if summary_polyline:
        summary_points = downsample_polyline(decode_polyline(summary_polyline), SUMMARY_SPACING_M)
        if clip_polyline_to_polygon(summary_points, search_polygon):
            return True

    for point in (record.get("start_latlng"), record.get("end_latlng")):
        if isinstance(point, list) and len(point) >= 2:
            if point_in_polygon((float(point[0]), float(point[1])), search_polygon):
                return True
    return False


def _summary_points(record: dict[str, Any]) -> list[tuple[float, float]]:
    summary_polyline = record.get("summary_polyline")
    if not summary_polyline:
        return []
    return downsample_polyline(decode_polyline(summary_polyline), SUMMARY_SPACING_M)


def _simplify_nogo_polygon(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) < 5:
        return points
    ring = points[:-1] if points[0] == points[-1] else list(points)
    simplified_ring = downsample_polyline(ring, NOGO_POLYGON_SPACING_M)
    if len(simplified_ring) < 3:
        simplified_ring = ring
    if simplified_ring[0] != simplified_ring[-1]:
        simplified_ring.append(simplified_ring[0])
    return simplified_ring


def _select_polygons_with_budget(
    route_client: RoutePlannerClient,
    scored_polygons: list[tuple[float, BrouterPolygonNogo]],
) -> list[BrouterPolygonNogo]:
    selected: list[BrouterPolygonNogo] = []
    for _, polygon in scored_polygons:
        if len(selected) >= MAX_NOGO_POLYGONS:
            break
        candidate_selection = selected + [polygon]
        query_chars = route_client.estimate_brouter_query_length(
            SELECTION_BUDGET_LONLATS,
            SELECTION_BUDGET_PROFILE,
            polygons=candidate_selection,
        )
        if query_chars <= MAX_STRAVA_QUERY_CHARS:
            selected.append(polygon)
    return selected


def _record_bbox(record: dict[str, Any]) -> tuple[float, float, float, float] | None:
    bbox = record.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    return tuple(float(value) for value in bbox)
