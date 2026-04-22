from __future__ import annotations

import mimetypes

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route

from app.agent.factory import build_agent
from app.artifacts import artifact_store
from app.config import AppConfig
from app.plugins.loader import load_plugins


def create_app(config: AppConfig | None = None):
    settings = config or AppConfig.from_env()
    agent = build_agent(settings, load_plugins(settings))
    chat_app = agent.to_web()

    async def download_artifact(request) -> Response:
        token = request.path_params["token"]
        artifact = artifact_store.resolve_download(token)
        if artifact is None or not artifact.path.exists():
            return PlainTextResponse("File not found.", status_code=404)
        media_type, _ = mimetypes.guess_type(artifact.filename)
        return FileResponse(
            artifact.path,
            media_type=media_type or "application/octet-stream",
            filename=artifact.filename,
        )

    return Starlette(
        routes=[
            Route("/downloads/{token}", download_artifact, methods=["GET"]),
            Mount("/", app=chat_app),
        ]
    )


app = create_app()


def main() -> None:
    config = AppConfig.from_env()
    uvicorn.run(app, host=config.web_host, port=config.web_port)


if __name__ == "__main__":
    main()
