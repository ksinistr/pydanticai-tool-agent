from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
from pathlib import Path
from secrets import token_hex
from typing import Literal
import xml.etree.ElementTree as ET

import httpx

PoiKind = Literal["refuel", "camping"]

EARTH_RADIUS_M = 6_371_008.8
DEFAULT_ROUTE_DISTANCE_METERS = 500.0
DEFAULT_REFUEL_CLUSTER_RADIUS_METERS = 600.0
DEFAULT_MIN_REFUEL_CLUSTER_SIZE = 2
DEFAULT_OVERPASS_TIMEOUT_SECONDS = 25.0
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_ATTRIBUTION = "OpenStreetMap contributors"
REFUEL_SHOP_VALUES = frozenset({"supermarket", "convenience", "mini_market", "bakery"})
REFUEL_AMENITY_VALUES = frozenset({"cafe", "restaurant"})


class GpxEnrichmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RoutePoint:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class RoutePoi:
    name: str
    kind: PoiKind
    poi_type: str
    latitude: float
    longitude: float
    source_type: str
    source_id: int
    tags: dict[str, str]


@dataclass(frozen=True, slots=True)
class MatchedPoi:
    poi: RoutePoi
    distance_km: float


@dataclass(frozen=True, slots=True)
class EnrichmentWaypoint:
    name: str
    description: str
    kind: PoiKind
    latitude: float
    longitude: float
    distance_km: float
    source_poi_count: int = 1


@dataclass(frozen=True, slots=True)
class GpxEnrichmentResult:
    path: Path
    filename: str
    refuel_waypoints: int
    camping_waypoints: int
    attribution: str = OSM_ATTRIBUTION


class OverpassPoiProvider:
    def __init__(
        self,
        endpoint_url: str,
        http_client: httpx.Client,
        query_timeout_seconds: float = DEFAULT_OVERPASS_TIMEOUT_SECONDS,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._http_client = http_client
        self._query_timeout_seconds = query_timeout_seconds

    def find_pois(self, route_points: list[RoutePoint], bbox_padding_meters: float) -> list[RoutePoi]:
        if len(route_points) < 2:
            return []

        query = _build_overpass_query(
            _route_bbox(route_points, bbox_padding_meters),
            timeout_seconds=self._query_timeout_seconds,
        )
        response = self._http_client.post(self._endpoint_url, data={"data": query})
        response.raise_for_status()
        payload = response.json()
        return _parse_overpass_payload(payload)


class GpxRouteEnricher:
    def __init__(
        self,
        poi_provider: OverpassPoiProvider,
        output_dir: Path,
        route_distance_meters: float = DEFAULT_ROUTE_DISTANCE_METERS,
        refuel_cluster_radius_meters: float = DEFAULT_REFUEL_CLUSTER_RADIUS_METERS,
        min_refuel_cluster_size: int = DEFAULT_MIN_REFUEL_CLUSTER_SIZE,
    ) -> None:
        self._poi_provider = poi_provider
        self._output_dir = Path(output_dir)
        self._route_distance_meters = route_distance_meters
        self._refuel_cluster_radius_meters = refuel_cluster_radius_meters
        self._min_refuel_cluster_size = min_refuel_cluster_size

    def enrich(self, gpx_path: Path) -> GpxEnrichmentResult:
        route_points = read_gpx_route_points(gpx_path)
        pois = self._poi_provider.find_pois(route_points, self._route_distance_meters)
        matched_pois = find_route_pois(route_points, pois, self._route_distance_meters)
        waypoints = build_enrichment_waypoints(
            matched_pois,
            refuel_cluster_radius_meters=self._refuel_cluster_radius_meters,
            min_refuel_cluster_size=self._min_refuel_cluster_size,
        )

        self._output_dir.mkdir(parents=True, exist_ok=True)
        visible_filename = f"{gpx_path.stem}_enriched.gpx"
        suffix = f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{token_hex(3)}"
        output_path = self._output_dir / f"{gpx_path.stem}_enriched_{suffix}.gpx"
        write_gpx_with_waypoints(gpx_path, output_path, waypoints)
        return GpxEnrichmentResult(
            path=output_path,
            filename=visible_filename,
            refuel_waypoints=sum(1 for waypoint in waypoints if waypoint.kind == "refuel"),
            camping_waypoints=sum(1 for waypoint in waypoints if waypoint.kind == "camping"),
        )


def read_gpx_route_points(gpx_path: Path) -> list[RoutePoint]:
    try:
        root = ET.parse(gpx_path).getroot()
    except ET.ParseError as exc:
        raise GpxEnrichmentError(f"Could not parse GPX file: {exc}") from exc

    namespace = _namespace(root.tag)
    elements = root.findall(f".//{_tag(namespace, 'trkpt')}")
    if not elements:
        elements = root.findall(f".//{_tag(namespace, 'rtept')}")

    route_points: list[RoutePoint] = []
    for element in elements:
        latitude = _parse_float(element.attrib.get("lat"))
        longitude = _parse_float(element.attrib.get("lon"))
        if latitude is None or longitude is None:
            continue
        route_points.append(RoutePoint(latitude=latitude, longitude=longitude))

    if len(route_points) < 2:
        raise GpxEnrichmentError("GPX file must contain at least two track or route points.")
    return route_points


def find_route_pois(
    route_points: list[RoutePoint],
    pois: list[RoutePoi],
    max_distance_meters: float,
) -> list[MatchedPoi]:
    matched: list[MatchedPoi] = []
    for poi in _deduplicate_pois(pois):
        distance_meters, distance_along_meters = _distance_to_route(
            RoutePoint(poi.latitude, poi.longitude),
            route_points,
        )
        if distance_meters <= max_distance_meters:
            matched.append(MatchedPoi(poi=poi, distance_km=round(distance_along_meters / 1000, 1)))

    return sorted(matched, key=lambda item: item.distance_km)


def build_enrichment_waypoints(
    matched_pois: list[MatchedPoi],
    refuel_cluster_radius_meters: float = DEFAULT_REFUEL_CLUSTER_RADIUS_METERS,
    min_refuel_cluster_size: int = DEFAULT_MIN_REFUEL_CLUSTER_SIZE,
) -> list[EnrichmentWaypoint]:
    refuel_pois = [poi for poi in matched_pois if poi.poi.kind == "refuel"]
    camping_pois = [poi for poi in matched_pois if poi.poi.kind == "camping"]

    waypoints = _build_refuel_waypoints(
        refuel_pois,
        cluster_radius_meters=refuel_cluster_radius_meters,
        min_cluster_size=min_refuel_cluster_size,
    )
    waypoints.extend(_build_camping_waypoints(camping_pois))
    return sorted(waypoints, key=lambda waypoint: waypoint.distance_km)


def write_gpx_with_waypoints(
    source_gpx_path: Path,
    output_path: Path,
    waypoints: list[EnrichmentWaypoint],
) -> None:
    try:
        tree = ET.parse(source_gpx_path)
    except ET.ParseError as exc:
        raise GpxEnrichmentError(f"Could not parse GPX file: {exc}") from exc

    root = tree.getroot()
    namespace = _namespace(root.tag)
    if namespace:
        ET.register_namespace("", namespace)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

    insert_at = _waypoint_insert_index(root)
    for offset, waypoint in enumerate(waypoints):
        root.insert(insert_at + offset, _build_waypoint_element(namespace, waypoint))

    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def _build_refuel_waypoints(
    pois: list[MatchedPoi],
    cluster_radius_meters: float,
    min_cluster_size: int,
) -> list[EnrichmentWaypoint]:
    waypoints: list[EnrichmentWaypoint] = []
    for cluster in _cluster_pois(pois, cluster_radius_meters):
        if len(cluster) < min_cluster_size:
            waypoints.extend(_individual_refuel_waypoint(poi) for poi in cluster)
            continue

        latitude = sum(poi.poi.latitude for poi in cluster) / len(cluster)
        longitude = sum(poi.poi.longitude for poi in cluster) / len(cluster)
        distance_km = round(sum(poi.distance_km for poi in cluster) / len(cluster), 1)
        name = _format_refuel_cluster_name(cluster)
        waypoints.append(
            EnrichmentWaypoint(
                name=name,
                description=(
                    f"{len(cluster)} refuel places around {distance_km:.1f} km. "
                    f"Data: {OSM_ATTRIBUTION}."
                ),
                kind="refuel",
                latitude=latitude,
                longitude=longitude,
                distance_km=distance_km,
                source_poi_count=len(cluster),
            )
        )
    return waypoints


def _individual_refuel_waypoint(poi: MatchedPoi) -> EnrichmentWaypoint:
    label = _refuel_label(poi.poi.poi_type)
    return EnrichmentWaypoint(
        name=f"Refuel: {poi.poi.name} {label}",
        description=f"Refuel place around {poi.distance_km:.1f} km. Data: {OSM_ATTRIBUTION}.",
        kind="refuel",
        latitude=poi.poi.latitude,
        longitude=poi.poi.longitude,
        distance_km=poi.distance_km,
    )


def _build_camping_waypoints(pois: list[MatchedPoi]) -> list[EnrichmentWaypoint]:
    waypoints: list[EnrichmentWaypoint] = []
    for poi in pois:
        name = poi.poi.name
        if name.startswith("Unnamed "):
            name = "Camping site"
        waypoints.append(
            EnrichmentWaypoint(
                name=f"Camping: {name}",
                description=f"Camping site around {poi.distance_km:.1f} km. Data: {OSM_ATTRIBUTION}.",
                kind="camping",
                latitude=poi.poi.latitude,
                longitude=poi.poi.longitude,
                distance_km=poi.distance_km,
            )
        )
    return waypoints


def _cluster_pois(pois: list[MatchedPoi], radius_meters: float) -> list[list[MatchedPoi]]:
    if not pois:
        return []

    parent = list(range(len(pois)))
    rank = [1] * len(pois)

    def find(index: int) -> int:
        if parent[index] != index:
            parent[index] = find(parent[index])
        return parent[index]

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if rank[first_root] < rank[second_root]:
            first_root, second_root = second_root, first_root
        parent[second_root] = first_root
        if rank[first_root] == rank[second_root]:
            rank[first_root] += 1

    for first_index, first in enumerate(pois):
        for second_index in range(first_index + 1, len(pois)):
            second = pois[second_index]
            distance = _haversine_meters(
                RoutePoint(first.poi.latitude, first.poi.longitude),
                RoutePoint(second.poi.latitude, second.poi.longitude),
            )
            if distance <= radius_meters:
                union(first_index, second_index)

    groups: dict[int, list[MatchedPoi]] = {}
    for index, poi in enumerate(pois):
        groups.setdefault(find(index), []).append(poi)

    return sorted(groups.values(), key=lambda group: min(poi.distance_km for poi in group))


def _format_refuel_cluster_name(cluster: list[MatchedPoi]) -> str:
    quantifier = "Many" if len(cluster) >= 4 else "Few"
    return f"Refuel: {quantifier} {_format_refuel_types({poi.poi.poi_type for poi in cluster})}"


def _format_refuel_types(types: set[str]) -> str:
    labels: list[str] = []
    if types & {"supermarket", "convenience", "mini_market"}:
        labels.append("shops")
    if "cafe" in types:
        labels.append("cafes")
    if "restaurant" in types:
        labels.append("restaurants")
    if "bakery" in types:
        labels.append("bakeries")
    if len(labels) == 1:
        return labels[0]
    return "resupplies"


def _refuel_label(poi_type: str) -> str:
    labels = {
        "supermarket": "supermarket",
        "convenience": "convenience store",
        "mini_market": "convenience store",
        "cafe": "cafe",
        "restaurant": "restaurant",
        "bakery": "bakery",
    }
    return labels.get(poi_type, poi_type.replace("_", " "))


def _deduplicate_pois(pois: list[RoutePoi]) -> list[RoutePoi]:
    seen: set[tuple[object, ...]] = set()
    result: list[RoutePoi] = []
    for poi in pois:
        key = (poi.kind, poi.source_type, poi.source_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(poi)
    return result


def _build_waypoint_element(namespace: str | None, waypoint: EnrichmentWaypoint) -> ET.Element:
    element = ET.Element(
        _tag(namespace, "wpt"),
        {
            "lat": _format_coordinate(waypoint.latitude),
            "lon": _format_coordinate(waypoint.longitude),
        },
    )
    ET.SubElement(element, _tag(namespace, "name")).text = waypoint.name
    ET.SubElement(element, _tag(namespace, "desc")).text = waypoint.description
    ET.SubElement(element, _tag(namespace, "sym")).text = (
        "Campground" if waypoint.kind == "camping" else "Store"
    )
    ET.SubElement(element, _tag(namespace, "type")).text = waypoint.kind
    return element


def _waypoint_insert_index(root: ET.Element) -> int:
    for index, child in enumerate(list(root)):
        if _local_name(child.tag) in {"rte", "trk", "extensions"}:
            return index
    return len(root)


def _parse_overpass_payload(payload: object) -> list[RoutePoi]:
    if not isinstance(payload, dict):
        raise GpxEnrichmentError("Overpass response was not a JSON object.")

    elements = payload.get("elements")
    if not isinstance(elements, list):
        return []

    pois: list[RoutePoi] = []
    for element in elements:
        poi = _parse_overpass_element(element)
        if poi is not None:
            pois.append(poi)
    return pois


def _parse_overpass_element(element: object) -> RoutePoi | None:
    if not isinstance(element, dict):
        return None

    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None

    string_tags = {str(key): str(value) for key, value in tags.items()}
    kind_and_type = _poi_kind_and_type(string_tags)
    if kind_and_type is None:
        return None

    latitude, longitude = _element_coordinates(element)
    if latitude is None or longitude is None:
        return None

    source_type = str(element.get("type", "unknown"))
    source_id = element.get("id")
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        return None

    kind, poi_type = kind_and_type
    return RoutePoi(
        name=_poi_name(string_tags, poi_type),
        kind=kind,
        poi_type=poi_type,
        latitude=latitude,
        longitude=longitude,
        source_type=source_type,
        source_id=source_id,
        tags=string_tags,
    )


def _poi_kind_and_type(tags: dict[str, str]) -> tuple[PoiKind, str] | None:
    shop = tags.get("shop")
    if shop in REFUEL_SHOP_VALUES:
        return "refuel", shop

    amenity = tags.get("amenity")
    if amenity in REFUEL_AMENITY_VALUES:
        return "refuel", amenity

    if tags.get("tourism") == "camp_site":
        return "camping", "camp_site"

    return None


def _poi_name(tags: dict[str, str], poi_type: str) -> str:
    for key in ("name", "brand", "operator"):
        value = tags.get(key, "").strip()
        if value:
            return value
    return f"Unnamed {_refuel_label(poi_type) if poi_type != 'camp_site' else 'camping site'}"


def _element_coordinates(element: dict) -> tuple[float | None, float | None]:
    latitude = _parse_float(element.get("lat"))
    longitude = _parse_float(element.get("lon"))
    if latitude is not None and longitude is not None:
        return latitude, longitude

    center = element.get("center")
    if not isinstance(center, dict):
        return None, None
    return _parse_float(center.get("lat")), _parse_float(center.get("lon"))


def _build_overpass_query(
    bbox: tuple[float, float, float, float],
    timeout_seconds: float,
) -> str:
    south, west, north, east = (_format_query_coordinate(value) for value in bbox)
    bbox_text = f"{south},{west},{north},{east}"
    timeout = max(1, int(round(timeout_seconds)))
    selectors = [
        '["shop"~"^(supermarket|convenience|mini_market|bakery)$"]',
        '["amenity"~"^(cafe|restaurant)$"]',
        '["tourism"="camp_site"]',
    ]

    lines = [f"[out:json][timeout:{timeout}];", "("]
    for selector in selectors:
        for element_type in ("node", "way", "relation"):
            lines.append(f"  {element_type}{selector}({bbox_text});")
    lines.extend([");", "out center tags;"])
    return "\n".join(lines)


def _route_bbox(
    route_points: list[RoutePoint],
    padding_meters: float,
) -> tuple[float, float, float, float]:
    min_latitude = min(point.latitude for point in route_points)
    max_latitude = max(point.latitude for point in route_points)
    min_longitude = min(point.longitude for point in route_points)
    max_longitude = max(point.longitude for point in route_points)
    center_latitude = (min_latitude + max_latitude) / 2
    latitude_padding = padding_meters / 111_320
    longitude_padding = padding_meters / (
        111_320 * max(abs(math.cos(math.radians(center_latitude))), 0.01)
    )
    return (
        max(min_latitude - latitude_padding, -90),
        max(min_longitude - longitude_padding, -180),
        min(max_latitude + latitude_padding, 90),
        min(max_longitude + longitude_padding, 180),
    )


def _distance_to_route(point: RoutePoint, route_points: list[RoutePoint]) -> tuple[float, float]:
    cumulative_distance = 0.0
    best_distance = math.inf
    best_along = 0.0

    for start, end in zip(route_points, route_points[1:], strict=False):
        segment_length = _haversine_meters(start, end)
        distance_to_segment, projected_distance = _distance_to_segment(point, start, end)
        if distance_to_segment < best_distance:
            best_distance = distance_to_segment
            best_along = cumulative_distance + min(max(projected_distance, 0.0), segment_length)
        cumulative_distance += segment_length

    return best_distance, best_along


def _distance_to_segment(
    point: RoutePoint,
    start: RoutePoint,
    end: RoutePoint,
) -> tuple[float, float]:
    start_x, start_y = _project_relative_meters(start, point)
    end_x, end_y = _project_relative_meters(end, point)
    segment_x = end_x - start_x
    segment_y = end_y - start_y
    segment_length_squared = segment_x * segment_x + segment_y * segment_y

    if segment_length_squared == 0:
        return math.hypot(start_x, start_y), 0.0

    ratio = -(start_x * segment_x + start_y * segment_y) / segment_length_squared
    clamped_ratio = min(max(ratio, 0.0), 1.0)
    closest_x = start_x + clamped_ratio * segment_x
    closest_y = start_y + clamped_ratio * segment_y
    projected_distance = math.sqrt(segment_length_squared) * clamped_ratio
    return math.hypot(closest_x, closest_y), projected_distance


def _project_relative_meters(point: RoutePoint, origin: RoutePoint) -> tuple[float, float]:
    latitude = math.radians(origin.latitude)
    x = math.radians(point.longitude - origin.longitude) * math.cos(latitude) * EARTH_RADIUS_M
    y = math.radians(point.latitude - origin.latitude) * EARTH_RADIUS_M
    return x, y


def _haversine_meters(first: RoutePoint, second: RoutePoint) -> float:
    first_latitude = math.radians(first.latitude)
    second_latitude = math.radians(second.latitude)
    delta_latitude = second_latitude - first_latitude
    delta_longitude = math.radians(second.longitude - first.longitude)
    value = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(first_latitude)
        * math.cos(second_latitude)
        * math.sin(delta_longitude / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(value))


def _namespace(tag: str) -> str | None:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _tag(namespace: str | None, name: str) -> str:
    if namespace:
        return f"{{{namespace}}}{name}"
    return name


def _local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _parse_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _format_coordinate(value: float) -> str:
    return f"{value:.7f}"


def _format_query_coordinate(value: float) -> str:
    return f"{value:.6f}"
