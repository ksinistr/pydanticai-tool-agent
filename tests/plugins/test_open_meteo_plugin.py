from __future__ import annotations

from app.plugins.open_meteo.plugin import OpenMeteoPlugin


class FakeOpenMeteoService:
    def __init__(self) -> None:
        self.last_request = None

    def search_locations(self, request):
        self.last_request = request
        return "ok"

    def get_forecast(self, request):
        self.last_request = request
        return "ok"


def test_open_meteo_plugin_maps_period_arguments_to_forecast_request() -> None:
    service = FakeOpenMeteoService()
    plugin = OpenMeteoPlugin(service)

    result = plugin.get_open_meteo_forecast(
        latitude=55.7558,
        longitude=37.6173,
        period_count=1,
        period_unit="days",
    )

    assert result == "ok"
    assert service.last_request.latitude == 55.7558
    assert service.last_request.longitude == 37.6173
    assert service.last_request.hours is None
    assert service.last_request.days == 1
