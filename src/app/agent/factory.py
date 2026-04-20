from __future__ import annotations

from collections.abc import Sequence

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import AppConfig
from app.plugins.base import AgentPlugin

INSTRUCTIONS = """
You are a concise assistant running inside a Telegram bot and a local web chat.
Use available tools when they can answer directly.
Do not invent tool outputs.
For weather forecast requests, if the user does not specify a location and no location is already established in the conversation, assume Paphos, Cyprus.
State that assumption briefly in the answer.
When a tool returns GPX download URLs, mention those URLs explicitly in the answer.
Copy each download URL exactly as returned by the tool, without rebuilding it from the filename.
""".strip()


def build_agent(config: AppConfig, plugins: Sequence[AgentPlugin]) -> Agent[None, str]:
    agent = Agent(build_model(config), instructions=INSTRUCTIONS)
    for plugin in plugins:
        plugin.register(agent)
    return agent


def build_model(config: AppConfig) -> OpenAIChatModel:
    return OpenAIChatModel(
        config.openai_model,
        provider=OpenAIProvider(
            base_url=config.openai_base_url,
            api_key=config.openai_api_key,
        ),
    )
