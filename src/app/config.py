from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    openrouter_api_key: str
    openrouter_model: str
    telegram_bot_token: str | None
    enabled_plugins: tuple[str, ...]
    web_host: str
    web_port: int
    intervals_icu_api_key: str | None
    intervals_icu_athlete_id: str | None
    intervals_icu_base_url: str

    @classmethod
    def from_env(cls) -> AppConfig:
        load_dotenv()
        return cls(
            openrouter_api_key=_require_env("OPENROUTER_API_KEY"),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini"),
            telegram_bot_token=_clean(os.getenv("TELEGRAM_BOT_TOKEN")),
            enabled_plugins=_parse_csv(os.getenv("APP_ENABLED_PLUGINS", "get_time")),
            web_host=os.getenv("APP_WEB_HOST", "127.0.0.1"),
            web_port=int(os.getenv("APP_WEB_PORT", "8000")),
            intervals_icu_api_key=_clean(os.getenv("INTERVALS_ICU_API_KEY")),
            intervals_icu_athlete_id=_clean(os.getenv("INTERVALS_ICU_ATHLETE_ID")),
            intervals_icu_base_url=os.getenv("INTERVALS_ICU_BASE_URL", "https://intervals.icu"),
        )

    def require_telegram_bot_token(self) -> str:
        if self.telegram_bot_token:
            return self.telegram_bot_token
        raise ValueError("TELEGRAM_BOT_TOKEN is required to run the Telegram bot.")

    def require_intervals_icu_api_key(self) -> str:
        if self.intervals_icu_api_key:
            return self.intervals_icu_api_key
        raise ValueError("INTERVALS_ICU_API_KEY is required to use the Intervals.icu plugin.")

    def require_intervals_icu_athlete_id(self) -> str:
        if self.intervals_icu_athlete_id:
            return self.intervals_icu_athlete_id
        raise ValueError("INTERVALS_ICU_ATHLETE_ID is required to use the Intervals.icu plugin.")


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or project_root() / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value.strip())

        if key and key not in os.environ:
            os.environ[key] = value


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require_env(name: str) -> str:
    value = _clean(os.getenv(name))
    if value:
        return value
    raise ValueError(f"{name} is required.")


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = [item.strip() for item in value.split(",")]
    return tuple(item for item in parts if item)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
