from __future__ import annotations

from pathlib import Path

from app.artifacts import ArtifactStore, artifact_session


def test_artifact_store_persists_downloads_across_instances(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    artifact_path = tmp_path / "generated.gpx"
    artifact_path.write_text("<gpx/>")

    first_store = ArtifactStore(registry_dir=registry_dir)
    artifact = first_store.register_file(artifact_path, "route.gpx")

    second_store = ArtifactStore(registry_dir=registry_dir)
    resolved = second_store.resolve_download(artifact.token)

    assert resolved == artifact


def test_artifact_store_keeps_session_artifacts_in_memory(tmp_path: Path) -> None:
    store = ArtifactStore(registry_dir=tmp_path / "registry")
    artifact_path = tmp_path / "generated.gpx"
    artifact_path.write_text("<gpx/>")

    with artifact_session("chat-1"):
        artifact = store.register_file(artifact_path, "route.gpx")

    assert store.consume_session_artifacts("chat-1") == [artifact]
