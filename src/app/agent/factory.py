from __future__ import annotations

from collections.abc import Sequence

from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.config import AppConfig
from app.plugins.base import AgentPlugin

INSTRUCTIONS = """
You are a concise assistant running inside a Telegram bot and a local web chat.
Use available tools when they can answer directly.
Do not invent tool outputs.
""".strip()


def build_agent(config: AppConfig, plugins: Sequence[AgentPlugin]) -> Agent[None, str]:
    agent = Agent(build_model(config), instructions=INSTRUCTIONS)
    for plugin in plugins:
        plugin.register(agent)
    return agent


def build_model(config: AppConfig) -> OpenRouterModel:
    return OpenRouterModel(
        config.openrouter_model,
        provider=OpenRouterProvider(api_key=config.openrouter_api_key),
    )
