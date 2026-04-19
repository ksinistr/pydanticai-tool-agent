from __future__ import annotations

import uvicorn

from app.agent.factory import build_agent
from app.config import AppConfig
from app.plugins.loader import load_plugins


def create_app(config: AppConfig | None = None):
    settings = config or AppConfig.from_env()
    agent = build_agent(settings, load_plugins(settings))
    return agent.to_web()


app = create_app()


def main() -> None:
    config = AppConfig.from_env()
    uvicorn.run(app, host=config.web_host, port=config.web_port)


if __name__ == "__main__":
    main()
