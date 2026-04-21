from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.constants import ParseMode

from app.bot.formatting import render_telegram_html
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
    message.reply_text.assert_awaited_once_with(
        "You are not authorized to use this bot.",
        parse_mode=ParseMode.HTML,
    )


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
    message.reply_text.assert_awaited_once_with("ok", parse_mode=ParseMode.HTML)
    message.reply_document.assert_awaited_once()


def test_help_lists_morning_report_command() -> None:
    service = SimpleNamespace(run=AsyncMock(), consume_artifacts=lambda session_id: [])
    handlers = TelegramHandlers(service)
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )

    asyncio.run(handlers.help(update, None))

    reply = message.reply_text.await_args.args[0]
    assert "/morning_report" in reply


def test_morning_report_uses_standalone_service() -> None:
    agent_service = SimpleNamespace(run=AsyncMock(), consume_artifacts=lambda session_id: [])
    morning_report_service = SimpleNamespace(generate=AsyncMock(return_value="report"))
    handlers = TelegramHandlers(agent_service, morning_report_service=morning_report_service)
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )
    context = SimpleNamespace(args=[])

    asyncio.run(handlers.morning_report(update, context))

    agent_service.run.assert_not_awaited()
    morning_report_service.generate.assert_awaited_once()
    message.reply_text.assert_awaited_once_with("report", parse_mode=ParseMode.HTML)


def test_morning_report_rejects_arguments() -> None:
    agent_service = SimpleNamespace(run=AsyncMock(), consume_artifacts=lambda session_id: [])
    morning_report_service = SimpleNamespace(generate=AsyncMock(return_value="report"))
    handlers = TelegramHandlers(agent_service, morning_report_service=morning_report_service)
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )
    context = SimpleNamespace(args=["2026-04-20"])

    asyncio.run(handlers.morning_report(update, context))

    morning_report_service.generate.assert_not_awaited()
    message.reply_text.assert_awaited_once_with(
        "Usage: /morning_report",
        parse_mode=ParseMode.HTML,
    )


def test_handle_text_formats_basic_markdown() -> None:
    service = SimpleNamespace(
        run=AsyncMock(return_value="**Title**\n- item\n`code`\n[site](https://example.com)"),
        consume_artifacts=lambda session_id: [],
    )
    handlers = TelegramHandlers(service)
    message = SimpleNamespace(text="hello", reply_text=AsyncMock(), reply_document=AsyncMock())
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )

    asyncio.run(handlers.handle_text(update, None))

    message.reply_text.assert_awaited_once_with(
        render_telegram_html("**Title**\n- item\n`code`\n[site](https://example.com)"),
        parse_mode=ParseMode.HTML,
    )
