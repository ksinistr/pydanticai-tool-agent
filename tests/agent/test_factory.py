from __future__ import annotations

from app.agent.factory import INSTRUCTIONS


def test_agent_instructions_define_default_weather_location() -> None:
    assert "Paphos, Cyprus" in INSTRUCTIONS
    assert "weather forecast requests" in INSTRUCTIONS
