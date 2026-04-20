from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.openai import OpenAIChatModel

from app.agent.factory import INSTRUCTIONS, build_model
from app.config import AppConfig


def test_agent_instructions_define_default_weather_location() -> None:
    assert "Paphos, Cyprus" in INSTRUCTIONS
    assert "weather forecast requests" in INSTRUCTIONS
    assert "GPX download URLs" in INSTRUCTIONS
    assert "without rebuilding it from the filename" in INSTRUCTIONS


def test_build_model_uses_openai_compatible_provider() -> None:
    config = AppConfig(
        openai_api_key="test-key",
        openai_base_url="https://provider.example.test/v1",
        openai_model="demo-model",
        openai_temperature=None,
        openai_top_p=None,
        telegram_bot_token=None,
        telegram_authorized_users=(),
        enabled_plugins=("get_time",),
        web_host="127.0.0.1",
        web_port=8000,
        public_base_url=None,
        intervals_icu_api_key=None,
        intervals_icu_athlete_id=None,
        intervals_icu_base_url="https://intervals.icu",
        route_planner_brouter_url="http://127.0.0.1:17777/brouter",
        strava_client_id=None,
        strava_client_secret=None,
        strava_redirect_uri="http://localhost/exchange_token",
        strava_data_dir=Path("/tmp/strava"),
    )

    model = build_model(config)

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "demo-model"
    assert str(model.provider.base_url) == "https://provider.example.test/v1/"
    assert model.provider.client.api_key == "test-key"
    assert model.settings is None


def test_build_model_includes_optional_model_settings() -> None:
    config = AppConfig(
        openai_api_key="test-key",
        openai_base_url="https://provider.example.test/v1",
        openai_model="demo-model",
        openai_temperature=0.4,
        openai_top_p=0.7,
        telegram_bot_token=None,
        telegram_authorized_users=(),
        enabled_plugins=("get_time",),
        web_host="127.0.0.1",
        web_port=8000,
        public_base_url=None,
        intervals_icu_api_key=None,
        intervals_icu_athlete_id=None,
        intervals_icu_base_url="https://intervals.icu",
        route_planner_brouter_url="http://127.0.0.1:17777/brouter",
        strava_client_id=None,
        strava_client_secret=None,
        strava_redirect_uri="http://localhost/exchange_token",
        strava_data_dir=Path("/tmp/strava"),
    )

    model = build_model(config)

    assert model.settings == {"temperature": 0.4, "top_p": 0.7}
