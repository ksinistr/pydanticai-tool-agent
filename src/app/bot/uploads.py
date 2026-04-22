from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex

from telegram import Document


@dataclass(frozen=True, slots=True)
class SavedTelegramDocument:
    filename: str
    path: Path


class TelegramDocumentStore:
    def __init__(self, upload_dir: Path) -> None:
        self._upload_dir = Path(upload_dir)

    async def save(self, document: Document) -> SavedTelegramDocument:
        filename = _document_filename(document)
        target = self._upload_dir / _stored_filename(filename)
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        telegram_file = await document.get_file()
        saved_path = await telegram_file.download_to_drive(custom_path=target)
        return SavedTelegramDocument(filename=filename, path=Path(saved_path).resolve())


class PendingTelegramDocumentStore:
    def __init__(self) -> None:
        self._documents: dict[str, SavedTelegramDocument] = {}

    def get(self, session_id: str) -> SavedTelegramDocument | None:
        return self._documents.get(session_id)

    def put(self, session_id: str, document: SavedTelegramDocument) -> None:
        self._documents[session_id] = document

    def clear(self, session_id: str) -> None:
        self._documents.pop(session_id, None)


def is_gpx_document(document: Document) -> bool:
    return Path(_document_filename(document)).suffix.casefold() == ".gpx"


def _document_filename(document: Document) -> str:
    raw_name = (document.file_name or "").strip()
    return Path(raw_name).name or "upload.bin"


def _stored_filename(filename: str) -> str:
    source = Path(filename)
    suffix = source.suffix or ".bin"
    stem = _safe_stem(source.stem)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{timestamp}_{token_hex(3)}{suffix}"


def _safe_stem(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in value.strip()
    )
    cleaned = cleaned.strip("._")
    return cleaned or "upload"
