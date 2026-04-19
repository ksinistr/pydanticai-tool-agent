from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig, load_dotenv


def test_load_dotenv_reads_project_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENROUTER_API_KEY=test-key",
                'OPENROUTER_MODEL="openai/gpt-4.1-mini"',
                "TELEGRAM_BOT_TOKEN=test-telegram-token",
                "APP_ENABLED_PLUGINS=get_time,extra",
                "APP_WEB_HOST=0.0.0.0",
                "APP_WEB_PORT=9000",
                "INTERVALS_ICU_API_KEY=intervals-secret",
                "INTERVALS_ICU_ATHLETE_ID=athlete-1",
                "INTERVALS_ICU_BASE_URL=https://intervals.icu",
            ]
        )
    )

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("APP_ENABLED_PLUGINS", raising=False)
    monkeypatch.delenv("APP_WEB_HOST", raising=False)
    monkeypatch.delenv("APP_WEB_PORT", raising=False)
    monkeypatch.delenv("INTERVALS_ICU_API_KEY", raising=False)
    monkeypatch.delenv("INTERVALS_ICU_ATHLETE_ID", raising=False)
    monkeypatch.delenv("INTERVALS_ICU_BASE_URL", raising=False)

    load_dotenv(env_file)
    config = AppConfig.from_env()

    assert config.openrouter_api_key == "test-key"
    assert config.openrouter_model == "openai/gpt-4.1-mini"
    assert config.telegram_bot_token == "test-telegram-token"
    assert config.enabled_plugins == ("get_time", "extra")
    assert config.web_host == "0.0.0.0"
    assert config.web_port == 9000
    assert config.intervals_icu_api_key == "intervals-secret"
    assert config.intervals_icu_athlete_id == "athlete-1"
    assert config.intervals_icu_base_url == "https://intervals.icu"
