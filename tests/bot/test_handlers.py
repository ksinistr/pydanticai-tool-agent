from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot.handlers import TelegramHandlers


def test_handle_text_rejects_unauthorized_username() -> None:
    service = SimpleNamespace(run=AsyncMock(), consume_artifacts=lambda session_id: [])
    handlers = TelegramHandlers(service, authorized_users=("@allowed_user",))
    message = SimpleNamespace(text="hello", reply_text=AsyncMock(), reply_document=AsyncMock())
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7, username="blocked_user"),
    )

    asyncio.run(handlers.handle_text(update, None))

    service.run.assert_not_awaited()
    message.reply_text.assert_awaited_once_with("You are not authorized to use this bot.")


def test_handle_text_allows_authorized_user_id() -> None:
    artifact_path = Path(__file__)
    service = SimpleNamespace(
        run=AsyncMock(return_value="ok"),
        consume_artifacts=lambda session_id: [
            SimpleNamespace(path=artifact_path, filename=artifact_path.name)
        ],
    )
    handlers = TelegramHandlers(service, authorized_users=("123456789",))
    message = SimpleNamespace(text="hello", reply_text=AsyncMock(), reply_document=AsyncMock())
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=123456789, username=None),
    )

    asyncio.run(handlers.handle_text(update, None))

    service.run.assert_awaited_once_with("42", "hello")
    message.reply_text.assert_awaited_once_with("ok")
    message.reply_document.assert_awaited_once()
