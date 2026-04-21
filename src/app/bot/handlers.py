from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from telegram import Update
from telegram.ext import ContextTypes

from app.agent.service import AgentService
from app.morning_report.service import MorningReportService

logger = logging.getLogger(__name__)


class TelegramHandlers:
    def __init__(
        self,
        agent_service: AgentService,
        morning_report_service: MorningReportService | None = None,
        authorized_users: Iterable[str] = (),
    ) -> None:
        self._agent_service = agent_service
        self._morning_report_service = morning_report_service
        self._authorized_user_ids, self._authorized_usernames = _parse_authorized_users(
            authorized_users
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None or not await self._authorize(update):
            return
        await message.reply_text(
            "Send me a message. I can answer normally, use tools when needed, "
            "or generate /morning_report."
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None or not await self._authorize(update):
            return
        await message.reply_text(
            "Commands:\n/start\n/help\n/reset\n/morning_report\n\nExample: What time is it in UTC?"
        )

    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None or not await self._authorize(update):
            return
        self._agent_service.reset(str(chat.id))
        await message.reply_text("Conversation history cleared.")

    async def morning_report(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        message = update.effective_message
        if message is None or not await self._authorize(update):
            return
        if context.args:
            await message.reply_text("Usage: /morning_report")
            return
        if self._morning_report_service is None:
            await message.reply_text("Morning report is not available.")
            return

        try:
            reply = await self._morning_report_service.generate()
        except Exception:
            logger.exception("Failed to build morning report")
            await message.reply_text(
                "The bot hit an internal error while building the morning report."
            )
            return

        await message.reply_text(reply)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat

        if message is None or chat is None or not message.text or not await self._authorize(update):
            return

        try:
            reply = await self._agent_service.run(str(chat.id), message.text)
        except Exception:
            logger.exception("Failed to process Telegram message")
            await message.reply_text("The bot hit an internal error while processing that message.")
            return

        await message.reply_text(reply)
        for artifact in self._agent_service.consume_artifacts(str(chat.id)):
            if not artifact.path.exists():
                logger.warning("Generated artifact missing: %s", artifact.path)
                continue
            with Path(artifact.path).open("rb") as file_handle:
                await message.reply_document(document=file_handle, filename=artifact.filename)

    async def _authorize(self, update: Update) -> bool:
        if not self._authorized_user_ids and not self._authorized_usernames:
            return True

        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return False
        if user.id in self._authorized_user_ids:
            return True

        username = _normalize_username(user.username)
        if username and username in self._authorized_usernames:
            return True

        logger.warning("Rejected Telegram user id=%s username=%s", user.id, user.username)
        await message.reply_text("You are not authorized to use this bot.")
        return False


def _parse_authorized_users(values: Iterable[str]) -> tuple[frozenset[int], frozenset[str]]:
    user_ids: set[int] = set()
    usernames: set[str] = set()
    for value in values:
        normalized = _normalize_username(value)
        if not normalized:
            continue
        if normalized.lstrip("-").isdigit():
            user_ids.add(int(normalized))
            continue
        usernames.add(normalized)
    return frozenset(user_ids), frozenset(usernames)


def _normalize_username(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lstrip("@").casefold()
    return normalized or None
