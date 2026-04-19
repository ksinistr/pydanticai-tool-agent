from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    token: str
    path: Path
    filename: str

    @property
    def download_url(self) -> str:
        return f"/downloads/{self.token}"


_current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)


class ArtifactStore:
    def __init__(self) -> None:
        self._downloads: dict[str, GeneratedArtifact] = {}
        self._session_artifacts: dict[str, list[GeneratedArtifact]] = {}

    def register_file(self, path: str | Path, filename: str | None = None) -> GeneratedArtifact:
        artifact_path = Path(path).resolve()
        artifact = GeneratedArtifact(
            token=token_urlsafe(24),
            path=artifact_path,
            filename=filename or artifact_path.name,
        )
        self._downloads[artifact.token] = artifact

        session_id = _current_session_id.get()
        if session_id:
            self._session_artifacts.setdefault(session_id, []).append(artifact)

        return artifact

    def resolve_download(self, token: str) -> GeneratedArtifact | None:
        return self._downloads.get(token)

    def consume_session_artifacts(self, session_id: str) -> list[GeneratedArtifact]:
        return list(self._session_artifacts.pop(session_id, []))


artifact_store = ArtifactStore()


@contextmanager
def artifact_session(session_id: str):
    token = _current_session_id.set(session_id)
    try:
        yield
    finally:
        _current_session_id.reset(token)
