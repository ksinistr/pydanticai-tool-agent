from __future__ import annotations

from pathlib import Path

import pytest

import app.config as config_module
from app.config import AppConfig, load_dotenv
from app.morning_report.models import (
    DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID,
    DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID,
)


def test_load_dotenv_reads_project_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "OPENAI_BASE_URL=https://provider.example.test/v1",
                'OPENAI_MODEL="gpt-4.1-mini"',
                "OPENAI_TEMPERATURE=0.3",
                "OPENAI_TOP_P=0.8",
                "TELEGRAM_BOT_TOKEN=test-telegram-token",
                "TELEGRAM_AUTHORIZED_USERS=@alice,123456789",
                "APP_ENABLED_PLUGINS=get_time,extra",
                "APP_WEB_HOST=0.0.0.0",
                "APP_WEB_PORT=9000",
                "APP_PUBLIC_BASE_URL=https://agent.example.test",
                "INTERVALS_ICU_API_KEY=intervals-secret",
                "INTERVALS_ICU_ATHLETE_ID=athlete-1",
                "INTERVALS_ICU_BASE_URL=https://intervals.icu",
                "CALDAV_SERVER_URL=https://baikal.example.test/dav.php/",
                "CALDAV_USERNAME=alice",
                "BAIKAL_PASSWORD=backup-secret",
                "CALDAV_INSECURE_SKIP_VERIFY=true",
                "MORNING_REPORT_LATITUDE=34.7765",
                "MORNING_REPORT_LONGITUDE=32.4241",
                "USER_TIMEZONE=Asia/Nicosia",
                "MORNING_REPORT_LANGUAGE=ru",
                "ROUTE_PLANNER_BROUTER_URL=http://127.0.0.1:17777/brouter",
                "STRAVA_CLIENT_ID=strava-client",
                "STRAVA_CLIENT_SECRET=strava-secret",
                "STRAVA_REDIRECT_URI=http://localhost/exchange_token",
                f"STRAVA_DATA_DIR={tmp_path / 'strava'}",
            ]
        )
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_TEMPERATURE", raising=False)
    monkeypatch.delenv("OPENAI_TOP_P", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_AUTHORIZED_USERS", raising=False)
    monkeypatch.delenv("APP_ENABLED_PLUGINS", raising=False)
    monkeypatch.delenv("APP_WEB_HOST", raising=False)
    monkeypatch.delenv("APP_WEB_PORT", raising=False)
    monkeypatch.delenv("APP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("INTERVALS_ICU_API_KEY", raising=False)
    monkeypatch.delenv("INTERVALS_ICU_ATHLETE_ID", raising=False)
    monkeypatch.delenv("INTERVALS_ICU_BASE_URL", raising=False)
    monkeypatch.delenv("CALDAV_SERVER_URL", raising=False)
    monkeypatch.delenv("CALDAV_USERNAME", raising=False)
    monkeypatch.delenv("CALDAV_PASSWORD", raising=False)
    monkeypatch.delenv("BAIKAL_PASSWORD", raising=False)
    monkeypatch.delenv("CALDAV_INSECURE_SKIP_VERIFY", raising=False)
    monkeypatch.delenv("MORNING_REPORT_LATITUDE", raising=False)
    monkeypatch.delenv("MORNING_REPORT_LONGITUDE", raising=False)
    monkeypatch.delenv("USER_TIMEZONE", raising=False)
    monkeypatch.delenv("MORNING_REPORT_LANGUAGE", raising=False)
    monkeypatch.delenv("ROUTE_PLANNER_BROUTER_URL", raising=False)
    monkeypatch.delenv("STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("STRAVA_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("STRAVA_REDIRECT_URI", raising=False)
    monkeypatch.delenv("STRAVA_DATA_DIR", raising=False)
    monkeypatch.setattr(config_module, "project_root", lambda: tmp_path)

    load_dotenv(env_file)
    config = AppConfig.from_env()

    assert config.openai_api_key == "test-key"
    assert config.openai_base_url == "https://provider.example.test/v1"
    assert config.openai_model == "gpt-4.1-mini"
    assert config.openai_temperature == 0.3
    assert config.openai_top_p == 0.8
    assert config.telegram_bot_token == "test-telegram-token"
    assert config.telegram_authorized_users == ("@alice", "123456789")
    assert config.enabled_plugins == ("get_time", "extra")
    assert config.web_host == "0.0.0.0"
    assert config.web_port == 9000
    assert config.public_base_url == "https://agent.example.test"
    assert config.intervals_icu_api_key == "intervals-secret"
    assert config.intervals_icu_athlete_id == "athlete-1"
    assert config.intervals_icu_base_url == "https://intervals.icu"
    assert config.caldav_server_url == "https://baikal.example.test/dav.php/"
    assert config.caldav_username == "alice"
    assert config.caldav_password == "backup-secret"
    assert config.caldav_insecure_skip_verify is True
    assert config.morning_report_latitude == 34.7765
    assert config.morning_report_longitude == 32.4241
    assert config.user_timezone == "Asia/Nicosia"
    assert config.morning_report_language == "ru"
    assert config.morning_report_holidays_calendar_id == DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID
    assert config.morning_report_vacation_calendar_id == DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID
    assert config.route_planner_brouter_url == "http://127.0.0.1:17777/brouter"
    assert config.strava_client_id == "strava-client"
    assert config.strava_client_secret == "strava-secret"
    assert config.strava_redirect_uri == "http://localhost/exchange_token"
    assert config.strava_data_dir == tmp_path / "strava"


def test_from_env_uses_openai_compatible_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_TEMPERATURE", raising=False)
    monkeypatch.delenv("OPENAI_TOP_P", raising=False)
    monkeypatch.delenv("CALDAV_SERVER_URL", raising=False)
    monkeypatch.delenv("CALDAV_USERNAME", raising=False)
    monkeypatch.delenv("CALDAV_PASSWORD", raising=False)
    monkeypatch.delenv("BAIKAL_PASSWORD", raising=False)
    monkeypatch.delenv("CALDAV_INSECURE_SKIP_VERIFY", raising=False)
    monkeypatch.delenv("MORNING_REPORT_LATITUDE", raising=False)
    monkeypatch.delenv("MORNING_REPORT_LONGITUDE", raising=False)
    monkeypatch.delenv("USER_TIMEZONE", raising=False)
    monkeypatch.delenv("MORNING_REPORT_LANGUAGE", raising=False)
    monkeypatch.setattr(config_module, "project_root", lambda: tmp_path)

    config = AppConfig.from_env()

    assert config.openai_api_key is None
    assert config.openai_base_url is None
    assert config.openai_model == "gpt-4.1-mini"
    assert config.openai_temperature is None
    assert config.openai_top_p is None
    assert config.morning_report_latitude is None
    assert config.morning_report_longitude is None
    assert config.user_timezone is None
    assert config.morning_report_language is None
    assert config.morning_report_holidays_calendar_id == DEFAULT_MORNING_REPORT_HOLIDAYS_CALENDAR_ID
    assert config.morning_report_vacation_calendar_id == DEFAULT_MORNING_REPORT_VACATION_CALENDAR_ID
    assert config.caldav_server_url is None
    assert config.caldav_username is None
    assert config.caldav_password is None
    assert config.caldav_insecure_skip_verify is False
    assert config.missing_morning_report_settings() == (
        "MORNING_REPORT_LATITUDE",
        "MORNING_REPORT_LONGITUDE",
        "USER_TIMEZONE",
        "MORNING_REPORT_LANGUAGE",
    )


def test_from_env_prefers_caldav_password_over_baikal_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CALDAV_SERVER_URL", "https://baikal.example.test/dav.php/")
    monkeypatch.setenv("CALDAV_USERNAME", "alice")
    monkeypatch.setenv("CALDAV_PASSWORD", "primary-secret")
    monkeypatch.setenv("BAIKAL_PASSWORD", "backup-secret")
    monkeypatch.setattr(config_module, "project_root", lambda: tmp_path)

    config = AppConfig.from_env()

    assert config.caldav_password == "primary-secret"
