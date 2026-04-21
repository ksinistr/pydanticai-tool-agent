from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from pydantic_ai import Agent

PluginCli: TypeAlias = Callable[[], int | None]


class AgentPlugin:
    name: str

    def register(self, agent: Agent[None, str]) -> None:
        raise NotImplementedError

    def build_cli(self) -> PluginCli | None:
        return None

    def healthcheck(self) -> None:
        return None
