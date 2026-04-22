from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
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
    def __init__(self, registry_dir: str | Path | None = None) -> None:
        self._downloads: dict[str, GeneratedArtifact] = {}
        self._session_artifacts: dict[str, list[GeneratedArtifact]] = {}
        self._registry_dir = Path(registry_dir).resolve() if registry_dir else _default_registry_dir()

    def register_file(self, path: str | Path, filename: str | None = None) -> GeneratedArtifact:
        artifact_path = Path(path).resolve()
        artifact = GeneratedArtifact(
            token=token_urlsafe(24),
            path=artifact_path,
            filename=filename or artifact_path.name,
        )
        self._downloads[artifact.token] = artifact
        self._write_registry_entry(artifact)

        session_id = _current_session_id.get()
        if session_id:
            self._session_artifacts.setdefault(session_id, []).append(artifact)

        return artifact

    def resolve_download(self, token: str) -> GeneratedArtifact | None:
        artifact = self._downloads.get(token)
        if artifact is not None:
            return artifact

        artifact = self._read_registry_entry(token)
        if artifact is not None:
            self._downloads[token] = artifact
        return artifact

    def consume_session_artifacts(self, session_id: str) -> list[GeneratedArtifact]:
        return list(self._session_artifacts.pop(session_id, []))

    def _write_registry_entry(self, artifact: GeneratedArtifact) -> None:
        self._registry_dir.mkdir(parents=True, exist_ok=True)
        target = self._registry_path(artifact.token)
        temp = target.with_suffix(".tmp")
        temp.write_text(
            json.dumps(
                {
                    "token": artifact.token,
                    "path": str(artifact.path),
                    "filename": artifact.filename,
                },
                ensure_ascii=False,
            )
        )
        temp.replace(target)

    def _read_registry_entry(self, token: str) -> GeneratedArtifact | None:
        target = self._registry_path(token)
        if not target.exists():
            return None

        payload = json.loads(target.read_text())
        return GeneratedArtifact(
            token=str(payload["token"]),
            path=Path(payload["path"]).resolve(),
            filename=str(payload["filename"]),
        )

    def _registry_path(self, token: str) -> Path:
        return self._registry_dir / f"{token}.json"


def _default_registry_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "output" / ".artifacts"


artifact_store = ArtifactStore()


@contextmanager
def artifact_session(session_id: str):
    token = _current_session_id.set(session_id)
    try:
        yield
    finally:
        _current_session_id.reset(token)
