from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from app.plugins.route_planner.geo import destination_point, haversine_distance
from app.plugins.route_planner.geometry import buffer_polyline
from app.plugins.route_planner.routing import (
    BrouterPolygonNogo,
    RoutePlannerClient,
    RoutePlannerError,
)


GlobalNogoProvider = Callable[[tuple[float, float], float, list[float]], list[BrouterPolygonNogo]]

GEOMETRY_SPACING_M = 35.0
CORRIDOR_DISTANCE_M = 25.0
PARALLEL_DIFF_DEG = 30.0
START_GRACE_M = 250.0
MIN_SEGMENT_GAP = 8
TARGET_OVERLAP_RUN_M = 300.0
TARGET_OVERLAP_TOTAL_M = 600.0
MAX_OPTION_SHARED_RATIO = 0.75
MAX_OPTIONS = 3
SOFT_LIMIT_RATIO = 1.10
SOFT_REPAIR_CORRIDOR_M = 45.0
HARD_REPAIR_CORRIDOR_M = 75.0
SOFT_REPAIR_WEIGHT = 4.0
TARGET_MIN_RATIO = 0.70
UNDER_DISTANCE_SCALE = 8.0
DISTANCE_BONUS_WEIGHT = 2.0
ELEVATION_PENALTY_WEIGHT = 5.0


@dataclass
class SegmentInfo:
    start: tuple[float, float]
    end: tuple[float, float]
    length_m: float
    orientation_deg: float
    midpoint_dist_to_start_m: float


@dataclass
class OverlapRun:
    start_segment_index: int
    end_segment_index: int
    length_m: float


@dataclass
class RoundTripSeed:
    candidate_id: str
    radius_km: float
    base_bearing_deg: float
    control_points: list[tuple[float, float]]
    control_bearings_deg: list[float]
    waypoints: list[tuple[float, float]]


@dataclass
class RoundTripCandidate:
    candidate_id: str
    attempt_type: str
    radius_km: float
    base_bearing_deg: float
    control_points: list[tuple[float, float]]
    control_bearings_deg: list[float]
    waypoints: list[tuple[float, float]]
    distance_km: float = 0.0
    ascent_m: float = 0.0
    overlap_total_m: float = 0.0
    overlap_max_run_m: float = 0.0
    distance_penalty: float = 0.0
    under_distance_penalty: float = 0.0
    elevation_penalty: float = 0.0
    overlap_penalty: float = 0.0
    distance_bonus: float = 0.0
    total_score: float = float("inf")
    status: str = ""
    error: str = ""
    failed_segment_index: int | None = None
    shared_ratio: float = 0.0
    similar_to_candidate_id: str = ""
    gpx_filepath: str = ""
    gpx_filename: str = ""
    overlap_run: OverlapRun | None = field(default=None, repr=False)
    geometry_points: list[tuple[float, float]] = field(default_factory=list, repr=False)
    segments: list[SegmentInfo] = field(default_factory=list, repr=False)
    total_length_m: float = 0.0

    def label(self) -> str:
        return f"{self.candidate_id}/{self.attempt_type}"

    def waypoints_list(self) -> list[tuple[float, float]]:
        return list(self.waypoints)


@dataclass
class RoundTripResult:
    success: bool
    error: str | None = None
    start_name: str = ""
    start_coords: tuple[float, float] | None = None
    max_total_km: float = 0.0
    max_elevation_m: float | None = None
    profile: str = "trekking"
    radii_km: list[float] = field(default_factory=list)
    selected_candidates: list[RoundTripCandidate] = field(default_factory=list)


class RoundTripPipeline:
    def __init__(
        self,
        route_client: RoutePlannerClient,
        global_nogo_provider: GlobalNogoProvider | None = None,
    ) -> None:
        self._route_client = route_client
        self._global_nogo_provider = global_nogo_provider

    def execute(
        self,
        start_coords: tuple[float, float],
        max_total_km: float,
        max_elevation_m: float | None,
        profile: str,
    ) -> RoundTripResult:
        result = RoundTripResult(
            success=False,
            max_total_km=max_total_km,
            max_elevation_m=max_elevation_m,
            profile=profile,
        )
        result.start_name = _format_coordinate_label(*start_coords)
        result.start_coords = start_coords

        radii_km = self._derive_radii(max_total_km)
        result.radii_km = radii_km
        bearing_offset_deg = random.uniform(0, 30)
        bearings_deg = [float(bearing_offset_deg + index * 30) for index in range(12)]
        global_nogo_polygons: list[BrouterPolygonNogo] = []
        if self._global_nogo_provider is not None:
            global_nogo_polygons = self._global_nogo_provider(
                result.start_coords, max_total_km, radii_km
            )

        accepted_candidates: list[RoundTripCandidate] = []
        candidate_index = 1
        for radius_km in radii_km:
            for base_bearing_deg in bearings_deg:
                seed = self._build_seed(
                    candidate_index, result.start_coords, radius_km, base_bearing_deg
                )
                best_candidate = self._evaluate_seed(
                    seed=seed,
                    profile=profile,
                    max_total_km=max_total_km,
                    max_elevation_m=max_elevation_m,
                    global_nogo_polygons=global_nogo_polygons,
                )
                if best_candidate is not None:
                    accepted_candidates.append(best_candidate)
                candidate_index += 1

        selected_candidates = self._select_distinct_candidates(accepted_candidates)
        if not selected_candidates:
            result.error = (
                "No routable round-trip candidate could be built from the sampled sectors."
            )
            return result

        route_name = self._build_route_name(result.start_name)
        exported_candidates: list[RoundTripCandidate] = []
        for candidate in selected_candidates:
            export_result = self._route_client.export_route_gpx(
                candidate.waypoints_list(),
                f"{route_name}_{candidate.candidate_id}_{candidate.attempt_type}",
                profile,
            )
            candidate.gpx_filepath = export_result["filepath"]
            candidate.gpx_filename = export_result["filename"]
            exported_candidates.append(candidate)

        result.selected_candidates = exported_candidates
        result.success = True
        return result

    def _derive_radii(self, max_total_km: float) -> list[float]:
        center = max_total_km * 0.20
        step = max(0.75, max_total_km / 30)
        radii = [
            max(0.5, round(center - step, 1)),
            max(0.5, round(center, 1)),
            max(0.5, round(center + step, 1)),
        ]
        return sorted(dict.fromkeys(radii))

    def _build_seed(
        self,
        candidate_index: int,
        start_coords: tuple[float, float],
        radius_km: float,
        base_bearing_deg: float,
    ) -> RoundTripSeed:
        start_lat, start_lon = start_coords
        control_bearing_1 = self._normalize_bearing(base_bearing_deg - 15)
        control_bearing_2 = self._normalize_bearing(base_bearing_deg + 15)
        control_point_1 = destination_point(start_lat, start_lon, radius_km, control_bearing_1)
        control_point_2 = destination_point(start_lat, start_lon, radius_km, control_bearing_2)
        return RoundTripSeed(
            candidate_id=f"RT{candidate_index:02d}",
            radius_km=radius_km,
            base_bearing_deg=base_bearing_deg,
            control_points=[control_point_1, control_point_2],
            control_bearings_deg=[control_bearing_1, control_bearing_2],
            waypoints=[start_coords, control_point_1, control_point_2, start_coords],
        )

    def _evaluate_seed(
        self,
        seed: RoundTripSeed,
        profile: str,
        max_total_km: float,
        max_elevation_m: float | None,
        global_nogo_polygons: list[BrouterPolygonNogo],
    ) -> RoundTripCandidate | None:
        base_candidate = self._route_attempt(seed, profile, "base", global_nogo_polygons)
        if base_candidate is None:
            return None
        self._score_candidate(base_candidate, max_total_km, max_elevation_m)
        best_candidate = base_candidate

        if self._needs_repair(base_candidate):
            soft_polygon = self._build_repair_polygon(
                base_candidate, SOFT_REPAIR_CORRIDOR_M, SOFT_REPAIR_WEIGHT
            )
            if soft_polygon is not None:
                soft_candidate = self._route_attempt(
                    seed,
                    profile,
                    "soft_nogo",
                    global_nogo_polygons + [soft_polygon],
                )
                if soft_candidate is not None:
                    self._score_candidate(soft_candidate, max_total_km, max_elevation_m)
                    if soft_candidate.total_score < best_candidate.total_score:
                        best_candidate = soft_candidate

        if self._needs_repair(best_candidate):
            hard_polygon = self._build_repair_polygon(best_candidate, HARD_REPAIR_CORRIDOR_M, None)
            if hard_polygon is not None:
                hard_candidate = self._route_attempt(
                    seed,
                    profile,
                    "hard_nogo",
                    global_nogo_polygons + [hard_polygon],
                )
                if hard_candidate is not None:
                    self._score_candidate(hard_candidate, max_total_km, max_elevation_m)
                    if hard_candidate.total_score < best_candidate.total_score:
                        best_candidate = hard_candidate

        return best_candidate

    def _route_attempt(
        self,
        seed: RoundTripSeed,
        profile: str,
        attempt_type: str,
        polygons: list[BrouterPolygonNogo],
    ) -> RoundTripCandidate | None:
        candidate = RoundTripCandidate(
            candidate_id=seed.candidate_id,
            attempt_type=attempt_type,
            radius_km=seed.radius_km,
            base_bearing_deg=seed.base_bearing_deg,
            control_points=seed.control_points,
            control_bearings_deg=seed.control_bearings_deg,
            waypoints=seed.waypoints,
        )
        try:
            route = self._route_client.calculate_route_with_waypoints(
                seed.waypoints,
                bike_profile=profile,
                include_geometry=True,
                polygons=polygons or None,
            )
        except RoutePlannerError:
            return None

        candidate.distance_km = float(route.get("distance_km", 0))
        candidate.ascent_m = float(route.get("elevation", {}).get("ascent_m", 0))
        candidate.geometry_points = self._extract_geometry_points(route.get("geometry", {}))
        candidate.segments, candidate.total_length_m = self._build_segments(
            candidate.geometry_points
        )
        if not candidate.segments:
            return None
        candidate.overlap_total_m, candidate.overlap_max_run_m, candidate.overlap_run = (
            self._measure_self_overlap(candidate)
        )
        candidate.status = "accepted"
        return candidate

    def _extract_geometry_points(self, geometry: dict) -> list[tuple[float, float]]:
        coordinates = geometry.get("coordinates", [])
        points = [
            (float(coord[1]), float(coord[0]))
            for coord in coordinates
            if isinstance(coord, list) and len(coord) >= 2
        ]
        return self._downsample_geometry(points)

    def _downsample_geometry(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(points) <= 2:
            return points
        sampled = [points[0]]
        for point in points[1:-1]:
            if (
                haversine_distance(sampled[-1][0], sampled[-1][1], point[0], point[1]) * 1000
                >= GEOMETRY_SPACING_M
            ):
                sampled.append(point)
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        return sampled

    def _build_segments(self, points: list[tuple[float, float]]) -> tuple[list[SegmentInfo], float]:
        if len(points) < 2:
            return [], 0.0
        average_lat = sum(lat for lat, _ in points) / len(points)
        cos_lat = math.cos(math.radians(average_lat))
        origin_lat, origin_lon = points[0]
        projected_points = [
            ((lon - origin_lon) * 111320.0 * cos_lat, (lat - origin_lat) * 111320.0)
            for lat, lon in points
        ]

        segments: list[SegmentInfo] = []
        total_length_m = 0.0
        for index in range(len(projected_points) - 1):
            start = projected_points[index]
            end = projected_points[index + 1]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length_m = math.hypot(dx, dy)
            if length_m <= 0:
                continue
            orientation_deg = math.degrees(math.atan2(dy, dx)) % 180
            midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            midpoint_dist_to_start_m = math.hypot(midpoint[0], midpoint[1])
            segments.append(
                SegmentInfo(
                    start=start,
                    end=end,
                    length_m=length_m,
                    orientation_deg=orientation_deg,
                    midpoint_dist_to_start_m=midpoint_dist_to_start_m,
                )
            )
            total_length_m += length_m
        return segments, total_length_m

    def _measure_self_overlap(
        self,
        candidate: RoundTripCandidate,
    ) -> tuple[float, float, OverlapRun | None]:
        if not candidate.segments:
            return 0.0, 0.0, None
        flags = [False] * len(candidate.segments)
        for index, segment in enumerate(candidate.segments):
            for other_index in range(index + MIN_SEGMENT_GAP, len(candidate.segments)):
                other_segment = candidate.segments[other_index]
                if self._segments_share_corridor(segment, other_segment):
                    flags[index] = True
                    flags[other_index] = True
                    break
        total_overlap_m = (
            sum(segment.length_m for flag, segment in zip(flags, candidate.segments) if flag) / 2
        )
        longest_run = self._longest_overlap_run(flags, candidate.segments)
        max_run_m = longest_run.length_m if longest_run is not None else 0.0
        return total_overlap_m, max_run_m, longest_run

    def _longest_overlap_run(
        self,
        flags: list[bool],
        segments: list[SegmentInfo],
    ) -> OverlapRun | None:
        longest_run: OverlapRun | None = None
        start_index: int | None = None
        current_length = 0.0
        for index, (flag, segment) in enumerate(zip(flags, segments)):
            if flag:
                if start_index is None:
                    start_index = index
                    current_length = 0.0
                current_length += segment.length_m
                continue
            if start_index is None:
                continue
            candidate_run = OverlapRun(
                start_segment_index=start_index,
                end_segment_index=index - 1,
                length_m=current_length,
            )
            if longest_run is None or candidate_run.length_m > longest_run.length_m:
                longest_run = candidate_run
            start_index = None
            current_length = 0.0
        if start_index is not None:
            candidate_run = OverlapRun(
                start_segment_index=start_index,
                end_segment_index=len(segments) - 1,
                length_m=current_length,
            )
            if longest_run is None or candidate_run.length_m > longest_run.length_m:
                longest_run = candidate_run
        return longest_run

    def _segments_share_corridor(self, segment: SegmentInfo, other_segment: SegmentInfo) -> bool:
        if (
            segment.midpoint_dist_to_start_m <= START_GRACE_M
            or other_segment.midpoint_dist_to_start_m <= START_GRACE_M
        ):
            return False
        if (
            self._orientation_difference(segment.orientation_deg, other_segment.orientation_deg)
            > PARALLEL_DIFF_DEG
        ):
            return False
        return self._segment_distance(segment, other_segment) <= CORRIDOR_DISTANCE_M

    def _orientation_difference(
        self, orientation_deg: float, other_orientation_deg: float
    ) -> float:
        difference = abs(orientation_deg - other_orientation_deg)
        return min(difference, 180 - difference)

    def _segment_distance(self, segment: SegmentInfo, other_segment: SegmentInfo) -> float:
        return min(
            self._point_to_segment_distance(segment.start, other_segment),
            self._point_to_segment_distance(segment.end, other_segment),
            self._point_to_segment_distance(other_segment.start, segment),
            self._point_to_segment_distance(other_segment.end, segment),
        )

    def _point_to_segment_distance(self, point: tuple[float, float], segment: SegmentInfo) -> float:
        ax, ay = segment.start
        bx, by = segment.end
        px, py = point
        dx = bx - ax
        dy = by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        nearest_x = ax + t * dx
        nearest_y = ay + t * dy
        return math.hypot(px - nearest_x, py - nearest_y)

    def _score_candidate(
        self, candidate: RoundTripCandidate, max_total_km: float, max_elevation_m: float | None
    ) -> None:
        candidate.distance_penalty = self._limit_penalty(candidate.distance_km, max_total_km)
        candidate.under_distance_penalty = self._calc_under_distance_penalty(
            candidate.distance_km, max_total_km
        )
        candidate.elevation_penalty = self._elevation_penalty(candidate.ascent_m, max_elevation_m)
        candidate.overlap_penalty = self._overlap_penalty(candidate)
        candidate.distance_bonus = self._distance_bonus(candidate.distance_km, max_total_km)
        weighted_elevation_penalty = candidate.elevation_penalty * ELEVATION_PENALTY_WEIGHT
        candidate.total_score = (
            candidate.overlap_penalty
            + candidate.distance_penalty
            + candidate.under_distance_penalty
            + weighted_elevation_penalty
            - candidate.distance_bonus
        )

    def _limit_penalty(self, actual_value: float, limit_value: float | None) -> float:
        if limit_value in (None, 0) or actual_value <= limit_value:
            return 0.0
        ratio = actual_value / limit_value
        if ratio <= SOFT_LIMIT_RATIO:
            return (ratio - 1.0) * 10.0
        hard_excess_ratio = ratio - SOFT_LIMIT_RATIO
        return 1.0 + (hard_excess_ratio * 20.0) ** 2

    def _calc_under_distance_penalty(self, distance_km: float, max_total_km: float) -> float:
        if max_total_km <= 0:
            return 0.0
        ratio = distance_km / max_total_km
        if ratio >= TARGET_MIN_RATIO:
            return 0.0
        deficit = TARGET_MIN_RATIO - ratio
        return (deficit * UNDER_DISTANCE_SCALE) ** 2

    def _elevation_penalty(self, ascent_m: float, max_elevation_m: float | None) -> float:
        if max_elevation_m in (None, 0):
            return 0.0
        if ascent_m <= max_elevation_m:
            return 0.0
        excess_ratio = ascent_m / max_elevation_m - 1.0
        return (excess_ratio * 10.0) ** 2

    def _overlap_penalty(self, candidate: RoundTripCandidate) -> float:
        return candidate.overlap_max_run_m / TARGET_OVERLAP_RUN_M + candidate.overlap_total_m / (
            TARGET_OVERLAP_TOTAL_M * 2.0
        )

    def _distance_bonus(self, distance_km: float, max_total_km: float) -> float:
        if max_total_km <= 0 or distance_km > max_total_km:
            return 0.0
        return min(distance_km / max_total_km, 1.0) * DISTANCE_BONUS_WEIGHT

    def _needs_repair(self, candidate: RoundTripCandidate) -> bool:
        return (
            candidate.overlap_max_run_m > TARGET_OVERLAP_RUN_M
            or candidate.overlap_total_m > TARGET_OVERLAP_TOTAL_M
        )

    def _build_repair_polygon(
        self,
        candidate: RoundTripCandidate,
        corridor_m: float,
        weight: float | None,
    ) -> BrouterPolygonNogo | None:
        if candidate.overlap_run is None:
            return None
        start_index = candidate.overlap_run.start_segment_index
        end_index = candidate.overlap_run.end_segment_index + 2
        repair_points = self._dedupe_points(candidate.geometry_points[start_index:end_index])
        if len(repair_points) < 2:
            return None
        polygon_points = buffer_polyline(repair_points, corridor_m)
        if len(polygon_points) < 4:
            return None
        return BrouterPolygonNogo(points=polygon_points, weight=weight)

    def _dedupe_points(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if not points:
            return []
        deduped = [points[0]]
        for point in points[1:]:
            if point != deduped[-1]:
                deduped.append(point)
        return deduped

    def _normalize_bearing(self, bearing_deg: float) -> float:
        return bearing_deg % 360

    def _select_distinct_candidates(
        self, candidates: list[RoundTripCandidate]
    ) -> list[RoundTripCandidate]:
        selected: list[RoundTripCandidate] = []
        sorted_candidates = sorted(
            candidates,
            key=lambda candidate: (
                candidate.total_score,
                candidate.overlap_penalty,
                candidate.distance_penalty,
                candidate.elevation_penalty,
                -candidate.distance_km,
                candidate.ascent_m,
            ),
        )

        for candidate in sorted_candidates:
            is_similar = False
            for selected_candidate in selected:
                shared_ratio = max(
                    self._shared_ratio(candidate, selected_candidate),
                    self._shared_ratio(selected_candidate, candidate),
                )
                if shared_ratio >= MAX_OPTION_SHARED_RATIO:
                    is_similar = True
                    break
            if is_similar:
                continue
            selected.append(candidate)
            if len(selected) >= MAX_OPTIONS:
                break
        return selected

    def _shared_ratio(
        self, candidate: RoundTripCandidate, other_candidate: RoundTripCandidate
    ) -> float:
        if not candidate.segments or not other_candidate.segments or candidate.total_length_m <= 0:
            return 0.0
        shared_length_m = 0.0
        for segment in candidate.segments:
            if segment.midpoint_dist_to_start_m <= START_GRACE_M:
                continue
            for other_segment in other_candidate.segments:
                if self._segments_share_corridor(segment, other_segment):
                    shared_length_m += segment.length_m
                    break
        return shared_length_m / candidate.total_length_m

    def _build_route_name(self, start_name: str) -> str:
        base = start_name.strip() if start_name else "round_trip"
        if "," in base and not _is_coordinate_label(base):
            base = base.split(",")[0].strip()
        return f"{base}_round_trip"


def _format_coordinate_label(latitude: float, longitude: float) -> str:
    return f"{latitude:.5f}, {longitude:.5f}"


def _is_coordinate_label(value: str) -> bool:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        return False
    try:
        float(parts[0])
        float(parts[1])
    except ValueError:
        return False
    return True
