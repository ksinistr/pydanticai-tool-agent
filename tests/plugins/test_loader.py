from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig
from app.plugins.loader import UnknownPluginError, load_plugins


def test_load_plugins_returns_configured_plugins() -> None:
    config = AppConfig(
        openai_api_key="test-key",
        openai_base_url="https://provider.example.test/v1",
        openai_model="gpt-4.1-mini",
        openai_temperature=None,
        openai_top_p=None,
        telegram_bot_token=None,
        telegram_authorized_users=(),
        enabled_plugins=("get_time", "open_meteo", "route_planner", "caldav"),
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
        caldav_server_url="https://baikal.example.test/dav.php/",
        caldav_username="alice",
    )

    plugins = load_plugins(config)

    assert [plugin.name for plugin in plugins] == [
        "get_time",
        "open_meteo",
        "route_planner",
        "caldav",
    ]


def test_load_plugins_raises_for_unknown_plugin() -> None:
    config = AppConfig(
        openai_api_key="test-key",
        openai_base_url="https://provider.example.test/v1",
        openai_model="gpt-4.1-mini",
        openai_temperature=None,
        openai_top_p=None,
        telegram_bot_token=None,
        telegram_authorized_users=(),
        enabled_plugins=("missing",),
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

    with pytest.raises(UnknownPluginError, match="Unknown plugin: missing"):
        load_plugins(config)
