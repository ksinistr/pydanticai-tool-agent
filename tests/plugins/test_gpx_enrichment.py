from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from app.plugins.route_planner.gpx_enrichment import (
    EnrichmentWaypoint,
    GpxRouteEnricher,
    OverpassPoiProvider,
    RoutePoi,
    RoutePoint,
    build_enrichment_waypoints,
    find_route_pois,
    read_gpx_route_points,
    write_gpx_with_waypoints,
)


class FakeOverpassResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post(self, url: str, data: dict[str, str]) -> FakeOverpassResponse:
        self.calls.append((url, data))
        return FakeOverpassResponse(self._payload)


class FakePoiProvider:
    def __init__(self, pois: list[RoutePoi]) -> None:
        self._pois = pois
        self.calls: list[tuple[list[RoutePoint], float]] = []

    def find_pois(self, route_points: list[RoutePoint], bbox_padding_meters: float) -> list[RoutePoi]:
        self.calls.append((route_points, bbox_padding_meters))
        return self._pois


def test_build_enrichment_waypoints_clusters_refuel_but_not_camping() -> None:
    route = [RoutePoint(35.0, 33.0), RoutePoint(35.0, 33.02)]
    pois = [
        _poi("refuel", "supermarket", "Market", 35.0001, 33.0050, 1),
        _poi("refuel", "cafe", "Cafe", 35.0002, 33.0054, 2),
        _poi("refuel", "bakery", "Bakery", 35.0001, 33.0150, 3),
        _poi("camping", "camp_site", "Camp One", 35.0001, 33.0060, 4),
        _poi("camping", "camp_site", "Camp Two", 35.0002, 33.0062, 5),
        _poi("refuel", "restaurant", "Far Food", 35.02, 33.0060, 6),
    ]

    matched = find_route_pois(route, pois, max_distance_meters=500)
    waypoints = build_enrichment_waypoints(matched)

    refuel_waypoints = [waypoint for waypoint in waypoints if waypoint.kind == "refuel"]
    camping_waypoints = [waypoint for waypoint in waypoints if waypoint.kind == "camping"]

    assert len(refuel_waypoints) == 2
    assert refuel_waypoints[0].source_poi_count == 2
    assert refuel_waypoints[0].name == "Refuel: Few resupplies"
    assert refuel_waypoints[1].name == "Refuel: Bakery bakery"
    assert [waypoint.name for waypoint in camping_waypoints] == [
        "Camping: Camp One",
        "Camping: Camp Two",
    ]


def test_write_gpx_with_waypoints_preserves_route_and_adds_waypoints(tmp_path: Path) -> None:
    source_path = _write_sample_gpx(tmp_path)
    output_path = tmp_path / "enriched.gpx"
    waypoints = [
        EnrichmentWaypoint(
            name="Refuel: Few shops",
            description="2 refuel places around 0.5 km. Data: OpenStreetMap contributors.",
            kind="refuel",
            latitude=35.0001,
            longitude=33.0050,
            distance_km=0.5,
            source_poi_count=2,
        ),
        EnrichmentWaypoint(
            name="Camping: Camp One",
            description="Camping site around 0.6 km. Data: OpenStreetMap contributors.",
            kind="camping",
            latitude=35.0002,
            longitude=33.0060,
            distance_km=0.6,
        ),
    ]

    write_gpx_with_waypoints(source_path, output_path, waypoints)

    root = ET.parse(output_path).getroot()
    namespace = {"gpx": "http://www.topografix.com/GPX/1/1"}
    parsed_waypoints = root.findall("gpx:wpt", namespace)
    track_points = root.findall(".//gpx:trkpt", namespace)

    assert len(parsed_waypoints) == 2
    assert len(track_points) == 2
    assert parsed_waypoints[0].findtext("gpx:name", namespaces=namespace) == "Refuel: Few shops"
    assert parsed_waypoints[0].findtext("gpx:sym", namespaces=namespace) == "Store"
    assert parsed_waypoints[1].findtext("gpx:name", namespaces=namespace) == "Camping: Camp One"
    assert parsed_waypoints[1].findtext("gpx:sym", namespaces=namespace) == "Campground"


def test_overpass_provider_queries_resupply_and_camping_tags() -> None:
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 101,
                "lat": 35.0,
                "lon": 33.0,
                "tags": {"shop": "supermarket", "name": "Market"},
            },
            {
                "type": "way",
                "id": 102,
                "center": {"lat": 35.001, "lon": 33.001},
                "tags": {"tourism": "camp_site", "name": "Camp"},
            },
        ]
    }
    http_client = FakeHttpClient(payload)
    provider = OverpassPoiProvider(
        endpoint_url="https://overpass.example.test/api/interpreter",
        http_client=http_client,
        query_timeout_seconds=12,
    )

    pois = provider.find_pois(
        [RoutePoint(35.0, 33.0), RoutePoint(35.0, 33.01)],
        bbox_padding_meters=500,
    )

    query = http_client.calls[0][1]["data"]
    assert http_client.calls[0][0] == "https://overpass.example.test/api/interpreter"
    assert '"shop"~"^(supermarket|convenience|mini_market|bakery)$"' in query
    assert '"amenity"~"^(cafe|restaurant)$"' in query
    assert '"tourism"="camp_site"' in query
    assert [(poi.kind, poi.poi_type, poi.name) for poi in pois] == [
        ("refuel", "supermarket", "Market"),
        ("camping", "camp_site", "Camp"),
    ]


def test_gpx_route_enricher_writes_visible_enriched_filename(tmp_path: Path) -> None:
    source_path = _write_sample_gpx(tmp_path)
    provider = FakePoiProvider(
        [
            _poi("refuel", "supermarket", "Market", 35.0001, 33.0050, 1),
            _poi("camping", "camp_site", "Camp One", 35.0001, 33.0060, 2),
        ]
    )
    enricher = GpxRouteEnricher(provider, tmp_path)

    result = enricher.enrich(source_path)

    assert result.filename == "route_enriched.gpx"
    assert result.path.exists()
    assert result.refuel_waypoints == 1
    assert result.camping_waypoints == 1
    assert provider.calls[0][1] == 500.0
    assert len(read_gpx_route_points(result.path)) == 2


def _poi(
    kind: str,
    poi_type: str,
    name: str,
    latitude: float,
    longitude: float,
    source_id: int,
) -> RoutePoi:
    return RoutePoi(
        name=name,
        kind=kind,
        poi_type=poi_type,
        latitude=latitude,
        longitude=longitude,
        source_type="node",
        source_id=source_id,
        tags={"name": name},
    )


def _write_sample_gpx(tmp_path: Path) -> Path:
    path = tmp_path / "route.gpx"
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Route</name>
    <trkseg>
      <trkpt lat="35.0000000" lon="33.0000000"><ele>10</ele></trkpt>
      <trkpt lat="35.0000000" lon="33.0200000"><ele>20</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
""",
        encoding="utf-8",
    )
    return path
