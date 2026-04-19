from __future__ import annotations

from collections.abc import Callable

from app.config import AppConfig
from app.plugins.base import AgentPlugin
from app.plugins.get_time.plugin import build_plugin as build_get_time_plugin
from app.plugins.intervals_icu.plugin import build_plugin as build_intervals_icu_plugin
from app.plugins.open_meteo.plugin import build_plugin as build_open_meteo_plugin

PluginFactory = Callable[[AppConfig], AgentPlugin]


class UnknownPluginError(ValueError):
    pass


PLUGIN_FACTORIES: dict[str, PluginFactory] = {
    "get_time": build_get_time_plugin,
    "intervals_icu": build_intervals_icu_plugin,
    "open_meteo": build_open_meteo_plugin,
}


def load_plugins(config: AppConfig) -> list[AgentPlugin]:
    plugins: list[AgentPlugin] = []

    for name in config.enabled_plugins:
        factory = PLUGIN_FACTORIES.get(name)
        if factory is None:
            raise UnknownPluginError(f"Unknown plugin: {name}")
        plugins.append(factory(config))

    return plugins
