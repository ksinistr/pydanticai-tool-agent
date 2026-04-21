from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_ai import Agent, ModelSettings
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
    agent = Agent(
        build_model(config),
        instructions=[INSTRUCTIONS, lambda: _date_context_instruction(config.user_timezone)],
    )
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
        settings=_build_model_settings(config),
    )


def _build_model_settings(config: AppConfig) -> ModelSettings | None:
    settings: ModelSettings = {}
    if config.openai_temperature is not None:
        settings["temperature"] = config.openai_temperature
    if config.openai_top_p is not None:
        settings["top_p"] = config.openai_top_p
    return settings or None


def _date_context_instruction(
    user_timezone: str | None,
    now: Callable[[tzinfo], datetime] | None = None,
) -> str:
    timezone = _resolve_timezone(user_timezone)
    current_time = (now or datetime.now)(timezone)
    timezone_name = getattr(timezone, "key", None) or current_time.tzname() or "UTC"
    current_date = current_time.date().isoformat()
    weekday = current_time.strftime("%A")
    current_year = current_time.year
    return (
        f"Today is {current_date} ({weekday}) in timezone {timezone_name}. "
        f"If the user asks about a month or date without a year, assume {current_year} "
        "unless the conversation clearly specifies a different year."
    )


def _resolve_timezone(value: str | None):
    if value is None:
        return datetime.now().astimezone().tzinfo or UTC
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo or UTC
