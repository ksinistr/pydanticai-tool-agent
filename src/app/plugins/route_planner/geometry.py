from __future__ import annotations

import math

from app.plugins.route_planner.geo import destination_point, haversine_distance


def decode_polyline(encoded: str, precision: int = 5) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []
    index = 0
    latitude = 0
    longitude = 0

    while index < len(encoded):
        shift = 0
        result = 0
        while True:
            value = ord(encoded[index]) - 63
            index += 1
            result |= (value & 0x1F) << shift
            shift += 5
            if value < 0x20:
                break
        delta_latitude = ~(result >> 1) if result & 1 else result >> 1
        latitude += delta_latitude

        shift = 0
        result = 0
        while True:
            value = ord(encoded[index]) - 63
            index += 1
            result |= (value & 0x1F) << shift
            shift += 5
            if value < 0x20:
                break
        delta_longitude = ~(result >> 1) if result & 1 else result >> 1
        longitude += delta_longitude
        coordinates.append((latitude / 10**precision, longitude / 10**precision))

    return coordinates


def build_radial_polygon(
    center_lat: float,
    center_lon: float,
    radius_km: float,
    vertex_count: int = 24,
) -> list[tuple[float, float]]:
    polygon = [
        destination_point(center_lat, center_lon, radius_km, vertex_index * (360 / vertex_count))
        for vertex_index in range(vertex_count)
    ]
    if polygon and polygon[0] != polygon[-1]:
        polygon.append(polygon[0])
    return polygon


def bbox_from_points(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    latitudes = [latitude for latitude, _ in points]
    longitudes = [longitude for _, longitude in points]
    return min(latitudes), min(longitudes), max(latitudes), max(longitudes)


def bboxes_intersect(
    left: tuple[float, float, float, float] | None,
    right: tuple[float, float, float, float] | None,
) -> bool:
    if left is None or right is None:
        return False
    return not (
        left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1]
    )


def point_in_polygon(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> bool:
    if len(polygon) < 3:
        return False
    latitude, longitude = point
    inside = False
    previous_latitude, previous_longitude = polygon[-1]

    for current_latitude, current_longitude in polygon:
        if (current_longitude > longitude) != (previous_longitude > longitude):
            intersection_latitude = (previous_latitude - current_latitude) * (
                longitude - current_longitude
            ) / ((previous_longitude - current_longitude) or 1e-12) + current_latitude
            if latitude < intersection_latitude:
                inside = not inside
        previous_latitude, previous_longitude = current_latitude, current_longitude

    return inside


def segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    orientation_a = _orientation(first_start, first_end, second_start)
    orientation_b = _orientation(first_start, first_end, second_end)
    orientation_c = _orientation(second_start, second_end, first_start)
    orientation_d = _orientation(second_start, second_end, first_end)

    if orientation_a == 0 and _on_segment(first_start, second_start, first_end):
        return True
    if orientation_b == 0 and _on_segment(first_start, second_end, first_end):
        return True
    if orientation_c == 0 and _on_segment(second_start, first_start, second_end):
        return True
    if orientation_d == 0 and _on_segment(second_start, first_end, second_end):
        return True

    return (orientation_a > 0) != (orientation_b > 0) and (orientation_c > 0) != (orientation_d > 0)


def segment_intersects_polygon(
    segment_start: tuple[float, float],
    segment_end: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> bool:
    if point_in_polygon(segment_start, polygon) or point_in_polygon(segment_end, polygon):
        return True
    if len(polygon) < 2:
        return False
    for edge_start, edge_end in zip(polygon, polygon[1:]):
        if segments_intersect(segment_start, segment_end, edge_start, edge_end):
            return True
    return False


def clip_polyline_to_polygon(
    points: list[tuple[float, float]],
    polygon: list[tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    if len(points) < 2 or len(polygon) < 3:
        return []

    clipped_segments: list[list[tuple[float, float]]] = []
    current_segment: list[tuple[float, float]] = []
    previous_point = points[0]
    previous_inside = point_in_polygon(previous_point, polygon)

    if previous_inside:
        current_segment.append(previous_point)

    for point in points[1:]:
        current_inside = point_in_polygon(point, polygon)
        crosses_polygon = segment_intersects_polygon(previous_point, point, polygon)

        if previous_inside or current_inside or crosses_polygon:
            if not current_segment:
                current_segment.append(previous_point)
            if point != current_segment[-1]:
                current_segment.append(point)
        elif len(current_segment) >= 2:
            clipped_segments.append(_dedupe_points(current_segment))
            current_segment = []
        else:
            current_segment = []

        if not current_inside and len(current_segment) >= 2 and not crosses_polygon:
            clipped_segments.append(_dedupe_points(current_segment))
            current_segment = []

        previous_point = point
        previous_inside = current_inside

    if len(current_segment) >= 2:
        clipped_segments.append(_dedupe_points(current_segment))

    return [segment for segment in clipped_segments if len(segment) >= 2]


def polyline_length_m(points: list[tuple[float, float]]) -> float:
    total_length_m = 0.0
    for start_point, end_point in zip(points, points[1:]):
        total_length_m += (
            haversine_distance(
                start_point[0],
                start_point[1],
                end_point[0],
                end_point[1],
            )
            * 1000
        )
    return total_length_m


def downsample_polyline(
    points: list[tuple[float, float]],
    spacing_m: float,
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points

    sampled_points = [points[0]]
    for point in points[1:-1]:
        distance_m = (
            haversine_distance(
                sampled_points[-1][0],
                sampled_points[-1][1],
                point[0],
                point[1],
            )
            * 1000
        )
        if distance_m >= spacing_m:
            sampled_points.append(point)

    if sampled_points[-1] != points[-1]:
        sampled_points.append(points[-1])

    return sampled_points


def buffer_polyline(
    points: list[tuple[float, float]],
    corridor_m: float,
) -> list[tuple[float, float]]:
    projected_points, origin_latitude, origin_longitude, cos_latitude = _project_points(points)
    projected_points = _dedupe_projected_points(projected_points)
    if len(projected_points) < 2:
        return []

    normals: list[tuple[float, float]] = []
    for start_point, end_point in zip(projected_points, projected_points[1:]):
        delta_x = end_point[0] - start_point[0]
        delta_y = end_point[1] - start_point[1]
        length_m = math.hypot(delta_x, delta_y)
        if length_m <= 0:
            continue
        normals.append((-delta_y / length_m, delta_x / length_m))

    if not normals:
        return []

    left_side: list[tuple[float, float]] = []
    right_side: list[tuple[float, float]] = []

    for point_index, point in enumerate(projected_points):
        normal_x, normal_y = _vertex_normal(normals, point_index)
        left_side.append((point[0] + normal_x * corridor_m, point[1] + normal_y * corridor_m))
        right_side.append((point[0] - normal_x * corridor_m, point[1] - normal_y * corridor_m))

    polygon = left_side + list(reversed(right_side))
    geo_polygon = [
        _unproject_point(point, origin_latitude, origin_longitude, cos_latitude)
        for point in polygon
    ]
    if geo_polygon and geo_polygon[0] != geo_polygon[-1]:
        geo_polygon.append(geo_polygon[0])
    return geo_polygon


def _orientation(
    start_point: tuple[float, float],
    middle_point: tuple[float, float],
    end_point: tuple[float, float],
) -> int:
    value = (middle_point[1] - start_point[1]) * (end_point[0] - middle_point[0]) - (
        middle_point[0] - start_point[0]
    ) * (end_point[1] - middle_point[1])
    if abs(value) < 1e-12:
        return 0
    return 1 if value > 0 else -1


def _on_segment(
    start_point: tuple[float, float],
    point: tuple[float, float],
    end_point: tuple[float, float],
) -> bool:
    return min(start_point[0], end_point[0]) <= point[0] <= max(
        start_point[0], end_point[0]
    ) and min(start_point[1], end_point[1]) <= point[1] <= max(start_point[1], end_point[1])


def _dedupe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not points:
        return []
    deduped_points = [points[0]]
    for point in points[1:]:
        if point != deduped_points[-1]:
            deduped_points.append(point)
    return deduped_points


def _project_points(
    points: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], float, float, float]:
    average_latitude = sum(latitude for latitude, _ in points) / len(points)
    cos_latitude = math.cos(math.radians(average_latitude))
    origin_latitude, origin_longitude = points[0]
    projected_points = [
        (
            (longitude - origin_longitude) * 111320.0 * cos_latitude,
            (latitude - origin_latitude) * 111320.0,
        )
        for latitude, longitude in points
    ]
    return projected_points, origin_latitude, origin_longitude, cos_latitude


def _dedupe_projected_points(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not points:
        return []
    deduped_points = [points[0]]
    for point in points[1:]:
        if math.hypot(point[0] - deduped_points[-1][0], point[1] - deduped_points[-1][1]) >= 1.0:
            deduped_points.append(point)
    return deduped_points


def _vertex_normal(
    normals: list[tuple[float, float]],
    point_index: int,
) -> tuple[float, float]:
    if point_index <= 0:
        return normals[0]
    if point_index >= len(normals):
        return normals[-1]
    previous_x, previous_y = normals[point_index - 1]
    next_x, next_y = normals[point_index]
    normal_x = previous_x + next_x
    normal_y = previous_y + next_y
    magnitude = math.hypot(normal_x, normal_y)
    if magnitude < 1e-6:
        return next_x, next_y
    return normal_x / magnitude, normal_y / magnitude


def _unproject_point(
    point: tuple[float, float],
    origin_latitude: float,
    origin_longitude: float,
    cos_latitude: float,
) -> tuple[float, float]:
    x, y = point
    latitude = origin_latitude + (y / 111320.0)
    if abs(cos_latitude) < 1e-9:
        longitude = origin_longitude
    else:
        longitude = origin_longitude + (x / (111320.0 * cos_latitude))
    return latitude, longitude
