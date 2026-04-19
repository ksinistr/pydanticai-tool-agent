from __future__ import annotations

import pytest

from app.config import AppConfig
from app.plugins.loader import UnknownPluginError, load_plugins


def test_load_plugins_returns_configured_plugins() -> None:
    config = AppConfig(
        openrouter_api_key="test-key",
        openrouter_model="openai/gpt-4.1-mini",
        telegram_bot_token=None,
        enabled_plugins=("get_time", "open_meteo"),
        web_host="127.0.0.1",
        web_port=8000,
        intervals_icu_api_key=None,
        intervals_icu_athlete_id=None,
        intervals_icu_base_url="https://intervals.icu",
    )

    plugins = load_plugins(config)

    assert [plugin.name for plugin in plugins] == ["get_time", "open_meteo"]


def test_load_plugins_raises_for_unknown_plugin() -> None:
    config = AppConfig(
        openrouter_api_key="test-key",
        openrouter_model="openai/gpt-4.1-mini",
        telegram_bot_token=None,
        enabled_plugins=("missing",),
        web_host="127.0.0.1",
        web_port=8000,
        intervals_icu_api_key=None,
        intervals_icu_athlete_id=None,
        intervals_icu_base_url="https://intervals.icu",
    )

    with pytest.raises(UnknownPluginError, match="Unknown plugin: missing"):
        load_plugins(config)
