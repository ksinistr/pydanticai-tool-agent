from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
import math
from pathlib import Path
from secrets import token_hex
from urllib.parse import urlparse

import httpx

TILE_SIZE = 256
DEFAULT_MAP_WIDTH = 1280
DEFAULT_MAP_HEIGHT = 1280
DEFAULT_PROFILE_WIDTH = 1280
DEFAULT_PROFILE_HEIGHT = 480
DEFAULT_TILE_URL_TEMPLATE = "https://tile.opentopomap.org/{z}/{x}/{y}.png"
MAX_OUTPUT_IMAGE_BYTES = 512 * 1024
MIN_OUTPUT_IMAGE_DIMENSION = 320
PNG_PALETTE_SIZES = (256, 192, 128, 96, 64, 48, 32)
IMAGE_SCALE_FACTOR = 0.88
JPEG_QUALITY_STEPS = (88, 82, 76, 70, 64, 58, 52, 46, 40)


class GpxImageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GpxImageSummary:
    point_count: int
    distance_km: float | None
    ascent_m: float | None
    descent_m: float | None
    min_elevation_m: float | None
    max_elevation_m: float | None


@dataclass(frozen=True, slots=True)
class RenderedGpxImages:
    map_path: Path
    map_filename: str
    elevation_profile_path: Path
    elevation_profile_filename: str
    summary: GpxImageSummary


class GpxImageRenderer:
    def __init__(
        self,
        output_dir: Path,
        http_client: httpx.Client | None = None,
        tile_url_template: str = DEFAULT_TILE_URL_TEMPLATE,
        user_agent: str = "pydanticai-tool-agent/0.1",
    ) -> None:
        self._output_dir = Path(output_dir)
        self._tile_url_template = tile_url_template
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": user_agent},
            timeout=20.0,
        )

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def render(self, gpx_path: Path, track_color: str = "red") -> RenderedGpxImages:
        track = self._load_track(gpx_path)
        plotting = self._load_plotting_modules()

        latitudes, longitudes = self._coordinates(track)
        elevations = self._elevations(track)
        distances = self._distances(track, latitudes, longitudes)

        summary = GpxImageSummary(
            point_count=len(latitudes),
            distance_km=_round_or_none(distances[-1] if distances else None, 2),
            ascent_m=_round_or_none(_positive_gain(elevations), 1),
            descent_m=_round_or_none(_negative_gain(elevations), 1),
            min_elevation_m=_round_or_none(min(elevations) if elevations else None, 1),
            max_elevation_m=_round_or_none(max(elevations) if elevations else None, 1),
        )

        stem = gpx_path.stem.strip() or "track"
        suffix = f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{token_hex(3)}"
        map_filename = f"{stem}_map_{suffix}.jpg"
        elevation_profile_filename = f"{stem}_elevation_profile_{suffix}.png"
        map_path = self._output_dir / map_filename
        elevation_profile_path = self._output_dir / elevation_profile_filename

        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._render_static_map(
            plotting=plotting,
            latitudes=latitudes,
            longitudes=longitudes,
            output_path=map_path,
            track_color=track_color,
        )
        self._render_elevation_profile(
            plotting=plotting,
            distances=distances,
            elevations=elevations,
            output_path=elevation_profile_path,
            track_color=track_color,
        )
        ensure_jpeg_size_limit(map_path, MAX_OUTPUT_IMAGE_BYTES)
        ensure_png_size_limit(elevation_profile_path, MAX_OUTPUT_IMAGE_BYTES)

        return RenderedGpxImages(
            map_path=map_path,
            map_filename=map_filename,
            elevation_profile_path=elevation_profile_path,
            elevation_profile_filename=elevation_profile_filename,
            summary=summary,
        )

    def _load_track(self, gpx_path: Path):
        try:
            import gpxo
        except ImportError as exc:
            raise GpxImageError(
                "GPX image rendering requires the dependencies gpxo, matplotlib, and pillow."
            ) from exc

        try:
            return gpxo.Track(str(gpx_path))
        except Exception as exc:
            raise GpxImageError(f"Could not load GPX file: {exc}") from exc

    def _load_plotting_modules(self):
        try:
            import matplotlib

            matplotlib.use("Agg")

            import matplotlib.image as image
            import matplotlib.pyplot as pyplot
        except ImportError as exc:
            raise GpxImageError(
                "GPX image rendering requires the dependencies gpxo, matplotlib, and pillow."
            ) from exc

        return {"image": image, "pyplot": pyplot}

    def _coordinates(self, track) -> tuple[list[float], list[float]]:
        raw_latitudes = self._raw_series(track.data, "latitude (°)")
        raw_longitudes = self._raw_series(track.data, "longitude (°)")
        latitudes: list[float] = []
        longitudes: list[float] = []

        for latitude, longitude in zip(raw_latitudes, raw_longitudes, strict=False):
            if not _is_number(latitude) or not _is_number(longitude):
                continue
            latitudes.append(float(latitude))
            longitudes.append(float(longitude))

        if len(latitudes) < 2:
            raise GpxImageError("GPX file must contain at least two track points.")

        return latitudes, longitudes

    def _elevations(self, track) -> list[float]:
        raw_elevations = self._raw_series(track.data, "elevation (m)")
        elevations = [float(value) for value in raw_elevations if _is_number(value)]
        if len(elevations) < 2:
            raise GpxImageError("GPX file does not contain enough elevation data.")
        return elevations

    def _distances(
        self,
        track,
        latitudes: list[float],
        longitudes: list[float],
    ) -> list[float]:
        if "distance (km)" in track.data:
            raw_distances = self._raw_series(track.data, "distance (km)")
            distances = [float(value) for value in raw_distances if _is_number(value)]
            if len(distances) >= 2:
                return distances

        distances = [0.0]
        for previous, current in zip(
            zip(latitudes, longitudes),
            zip(latitudes[1:], longitudes[1:]),
            strict=False,
        ):
            segment_km = _haversine_km(previous, current)
            distances.append(distances[-1] + segment_km)
        return distances

    def _raw_series(self, data, column: str) -> list[object]:
        if column not in data:
            raise GpxImageError(f"GPX data is missing the '{column}' field.")
        series = data[column]
        if hasattr(series, "tolist"):
            return list(series.tolist())
        return list(series)

    def _render_static_map(
        self,
        plotting,
        latitudes: list[float],
        longitudes: list[float],
        output_path: Path,
        track_color: str,
    ) -> None:
        pyplot = plotting["pyplot"]
        image = plotting["image"]

        zoom, crop_box = _choose_map_zoom(latitudes, longitudes)
        left, right, bottom, top = crop_box
        tile_min_x = math.floor(left / TILE_SIZE)
        tile_max_x = math.floor((right - 1) / TILE_SIZE)
        tile_min_y = math.floor((-top) / TILE_SIZE)
        tile_max_y = math.floor(((-bottom) - 1) / TILE_SIZE)

        tile_count = (tile_max_x - tile_min_x + 1) * (tile_max_y - tile_min_y + 1)
        if tile_count > 64:
            raise GpxImageError("Track bounding box is too large to render with map tiles.")

        figure, axis = pyplot.subplots(
            figsize=(DEFAULT_MAP_WIDTH / 100, DEFAULT_MAP_HEIGHT / 100),
            dpi=100,
        )

        try:
            for tile_y in range(tile_min_y, tile_max_y + 1):
                for tile_x in range(tile_min_x, tile_max_x + 1):
                    tile_image = self._load_tile(image, zoom, tile_x, tile_y)
                    if tile_image is None:
                        continue
                    tile_left = tile_x * TILE_SIZE
                    tile_right = (tile_x + 1) * TILE_SIZE
                    tile_top = -(tile_y * TILE_SIZE)
                    tile_bottom = -((tile_y + 1) * TILE_SIZE)
                    axis.imshow(
                        tile_image,
                        extent=(tile_left, tile_right, tile_bottom, tile_top),
                        origin="upper",
                        interpolation="bilinear",
                    )

            xs, ys = _project_track_pixels(latitudes, longitudes, zoom)
            axis.plot(xs, ys, color=track_color, linewidth=3.0, solid_capstyle="round")
            axis.set_xlim(left, right)
            axis.set_ylim(bottom, top)
            axis.set_axis_off()
            figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
            figure.savefig(
                output_path,
                format="jpeg",
                dpi=100,
                pad_inches=0,
                facecolor="white",
                edgecolor="white",
                pil_kwargs={
                    "quality": JPEG_QUALITY_STEPS[0],
                    "optimize": True,
                    "progressive": True,
                },
            )
        except ValueError as exc:
            raise GpxImageError(f"Could not render map image: {exc}") from exc
        finally:
            pyplot.close(figure)

    def _render_elevation_profile(
        self,
        plotting,
        distances: list[float],
        elevations: list[float],
        output_path: Path,
        track_color: str,
    ) -> None:
        pyplot = plotting["pyplot"]
        figure, axis = pyplot.subplots(
            figsize=(DEFAULT_PROFILE_WIDTH / 100, DEFAULT_PROFILE_HEIGHT / 100),
            dpi=100,
        )

        try:
            baseline = min(elevations)
            axis.plot(distances[: len(elevations)], elevations, color=track_color, linewidth=2.5)
            axis.fill_between(
                distances[: len(elevations)],
                elevations,
                baseline,
                color=track_color,
                alpha=0.18,
            )
            axis.set_xlabel("Distance (km)")
            axis.set_ylabel("Elevation (m)")
            axis.grid(alpha=0.2)
            figure.tight_layout()
            figure.savefig(output_path)
        except ValueError as exc:
            raise GpxImageError(f"Could not render elevation profile: {exc}") from exc
        finally:
            pyplot.close(figure)

    def _load_tile(self, image, zoom: int, tile_x: int, tile_y: int):
        tile_limit = 2**zoom
        if tile_y < 0 or tile_y >= tile_limit:
            return None

        wrapped_x = tile_x % tile_limit
        url = self._tile_url_template.format(z=zoom, x=wrapped_x, y=tile_y)
        try:
            response = self._http_client.get(url)
            response.raise_for_status()
            return image.imread(BytesIO(response.content), format="png")
        except Exception as exc:
            raise GpxImageError(
                f"Could not load OpenTopoMap tile {zoom}/{wrapped_x}/{tile_y}: {exc}"
            )


def resolve_gpx_reference(reference: str, root_dir: Path, artifact_lookup) -> Path:
    download_token = _extract_download_token(reference)
    if download_token is not None:
        artifact = artifact_lookup(download_token)
        if artifact is None:
            raise GpxImageError(f"GPX download reference not found: {reference}")
        return artifact.path.resolve()

    candidates = [Path(reference).expanduser()]
    if not Path(reference).is_absolute():
        candidates.append((root_dir / reference).expanduser())

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    raise GpxImageError(f"GPX file not found: {reference}")


def _choose_map_zoom(
    latitudes: list[float],
    longitudes: list[float],
) -> tuple[int, tuple[float, float, float, float]]:
    zoom = 15
    while zoom >= 3:
        xs, ys = _project_track_pixels(latitudes, longitudes, zoom)
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        span_x = max(max_x - min_x, 32.0)
        span_y = max(max_y - min_y, 32.0)
        padding_x = max(span_x * 0.14, 96.0)
        padding_y = max(span_y * 0.14, 96.0)
        width = span_x + 2 * padding_x
        height = span_y + 2 * padding_y
        if width <= DEFAULT_MAP_WIDTH and height <= DEFAULT_MAP_HEIGHT:
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            crop_left = center_x - DEFAULT_MAP_WIDTH / 2
            crop_right = center_x + DEFAULT_MAP_WIDTH / 2
            crop_bottom = center_y - DEFAULT_MAP_HEIGHT / 2
            crop_top = center_y + DEFAULT_MAP_HEIGHT / 2
            return zoom, (crop_left, crop_right, crop_bottom, crop_top)
        zoom -= 1

    xs, ys = _project_track_pixels(latitudes, longitudes, 3)
    center_x = (min(xs) + max(xs)) / 2
    center_y = (min(ys) + max(ys)) / 2
    return 3, (
        center_x - DEFAULT_MAP_WIDTH / 2,
        center_x + DEFAULT_MAP_WIDTH / 2,
        center_y - DEFAULT_MAP_HEIGHT / 2,
        center_y + DEFAULT_MAP_HEIGHT / 2,
    )


def _project_track_pixels(
    latitudes: list[float],
    longitudes: list[float],
    zoom: int,
) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    scale = 2**zoom
    for latitude, longitude in zip(latitudes, longitudes, strict=False):
        world_x, world_y = _project_mercator(latitude, longitude)
        xs.append(world_x * scale)
        ys.append(-(world_y * scale))
    return xs, ys


def _project_mercator(latitude: float, longitude: float) -> tuple[float, float]:
    latitude = min(max(latitude, -85.05112878), 85.05112878)
    sin_latitude = math.sin(math.radians(latitude))
    world_x = ((longitude + 180.0) / 360.0) * TILE_SIZE
    world_y = (0.5 - math.log((1 + sin_latitude) / (1 - sin_latitude)) / (4 * math.pi)) * TILE_SIZE
    return world_x, world_y


def _extract_download_token(reference: str) -> str | None:
    parsed = urlparse(reference)
    path = parsed.path if parsed.scheme else reference
    if not path.startswith("/downloads/"):
        return None
    token = path.removeprefix("/downloads/").strip("/")
    return token or None


def _haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    first_latitude, first_longitude = first
    second_latitude, second_longitude = second
    earth_radius_km = 6371.0088
    delta_latitude = math.radians(second_latitude - first_latitude)
    delta_longitude = math.radians(second_longitude - first_longitude)
    latitude_1 = math.radians(first_latitude)
    latitude_2 = math.radians(second_latitude)
    a = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2) ** 2
    )
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def _positive_gain(elevations: list[float]) -> float | None:
    if len(elevations) < 2:
        return None
    gain = 0.0
    for previous, current in zip(elevations, elevations[1:], strict=False):
        gain += max(current - previous, 0.0)
    return gain


def _negative_gain(elevations: list[float]) -> float | None:
    if len(elevations) < 2:
        return None
    gain = 0.0
    for previous, current in zip(elevations, elevations[1:], strict=False):
        gain += max(previous - current, 0.0)
    return gain


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _is_number(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def ensure_png_size_limit(path: Path, max_bytes: int) -> None:
    if path.stat().st_size <= max_bytes:
        return

    image = _load_pillow_image_module()
    with image.open(path) as opened_image:
        working_image = opened_image.convert("RGBA" if "A" in opened_image.getbands() else "RGB")

    for size in _candidate_image_sizes(*working_image.size):
        candidate = working_image
        if size != working_image.size:
            candidate = working_image.resize(size, image.Resampling.LANCZOS)
        for colors in PNG_PALETTE_SIZES:
            payload = _encode_png(candidate, colors=colors, image_module=image)
            if len(payload) <= max_bytes:
                path.write_bytes(payload)
                return

    raise GpxImageError(f"Could not reduce image below {max_bytes} bytes: {path.name}")


def ensure_jpeg_size_limit(path: Path, max_bytes: int) -> None:
    if path.stat().st_size <= max_bytes:
        return

    image = _load_pillow_image_module()
    with image.open(path) as opened_image:
        working_image = opened_image.convert("RGB")

    for size in _candidate_image_sizes(*working_image.size):
        candidate = working_image
        if size != working_image.size:
            candidate = working_image.resize(size, image.Resampling.LANCZOS)
        for quality in JPEG_QUALITY_STEPS:
            payload = _encode_jpeg(candidate, quality=quality)
            if len(payload) <= max_bytes:
                path.write_bytes(payload)
                return

    raise GpxImageError(f"Could not reduce image below {max_bytes} bytes: {path.name}")


def _load_pillow_image_module():
    try:
        from PIL import Image
    except ImportError as exc:
        raise GpxImageError(
            "GPX image rendering requires the dependencies gpxo, matplotlib, and pillow."
        ) from exc
    return Image


def _candidate_image_sizes(width: int, height: int) -> list[tuple[int, int]]:
    sizes: list[tuple[int, int]] = [(width, height)]
    current_width = width
    current_height = height

    while current_width > MIN_OUTPUT_IMAGE_DIMENSION or current_height > MIN_OUTPUT_IMAGE_DIMENSION:
        next_width = max(MIN_OUTPUT_IMAGE_DIMENSION, int(current_width * IMAGE_SCALE_FACTOR))
        next_height = max(MIN_OUTPUT_IMAGE_DIMENSION, int(current_height * IMAGE_SCALE_FACTOR))
        next_size = (next_width, next_height)
        if next_size == sizes[-1]:
            break
        sizes.append(next_size)
        current_width, current_height = next_size

    return sizes


def _encode_png(image, colors: int, image_module) -> bytes:
    if image.mode == "RGBA":
        palette_image = image.quantize(
            colors=colors,
            method=image_module.Quantize.FASTOCTREE,
            dither=image_module.Dither.NONE,
        )
    else:
        palette_image = image.quantize(
            colors=colors,
            method=image_module.Quantize.MEDIANCUT,
            dither=image_module.Dither.NONE,
        )

    buffer = BytesIO()
    palette_image.save(buffer, format="PNG", optimize=True, compress_level=9)
    return buffer.getvalue()


def _encode_jpeg(image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
    )
    return buffer.getvalue()
