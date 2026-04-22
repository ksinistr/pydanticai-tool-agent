from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Iterable

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.agent.service import AgentService
from app.bot.formatting import render_telegram_html
from app.daily_training_advice.service import DailyTrainingAdviceService
from app.morning_report.service import MorningReportService

logger = logging.getLogger(__name__)


class TelegramHandlers:
    def __init__(
        self,
        agent_service: AgentService,
        morning_report_service: MorningReportService | None = None,
        daily_training_advice_service: DailyTrainingAdviceService | None = None,
        authorized_users: Iterable[str] = (),
    ) -> None:
        self._agent_service = agent_service
        self._morning_report_service = morning_report_service
        self._daily_training_advice_service = daily_training_advice_service
        self._authorized_user_ids, self._authorized_usernames = _parse_authorized_users(
            authorized_users
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None or not await self._authorize(update):
            return
        await self._reply_text(
            message,
            "Send me a message. I can answer normally, use tools when needed, "
            "or generate /morning_report or /daily_training_advice.",
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None or not await self._authorize(update):
            return
        await self._reply_text(
            message,
            "Commands:\n/start\n/help\n/reset\n/morning_report\n/daily_training_advice\n\nExample: What time is it in UTC?",
        )

    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None or not await self._authorize(update):
            return
        self._agent_service.reset(str(chat.id))
        await self._reply_text(message, "Conversation history cleared.")

    async def morning_report(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        message = update.effective_message
        if message is None or not await self._authorize(update):
            return
        if context.args:
            await self._reply_text(message, "Usage: /morning_report")
            return
        if self._morning_report_service is None:
            await self._reply_text(message, "Morning report is not available.")
            return

        try:
            reply = await self._morning_report_service.generate()
        except Exception:
            logger.exception("Failed to build morning report")
            await self._reply_text(
                message, "The bot hit an internal error while building the morning report."
            )
            return

        await self._reply_text(message, reply)

    async def daily_training_advice(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        message = update.effective_message
        if message is None or not await self._authorize(update):
            return
        if context.args:
            await self._reply_text(message, "Usage: /daily_training_advice")
            return
        if self._daily_training_advice_service is None:
            await self._reply_text(message, "Daily training advice is not available.")
            return

        try:
            reply = await self._daily_training_advice_service.generate()
        except Exception:
            logger.exception("Failed to build daily training advice")
            await self._reply_text(
                message,
                "The bot hit an internal error while building the daily training advice.",
            )
            return

        await self._reply_text(message, reply)

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
            await self._reply_text(
                message,
                "The bot hit an internal error while processing that message.",
            )
            return

        await self._reply_text(message, reply)
        for artifact in self._agent_service.consume_artifacts(str(chat.id)):
            if not artifact.path.exists():
                logger.warning("Generated artifact missing: %s", artifact.path)
                continue
            with Path(artifact.path).open("rb") as file_handle:
                media_type, _ = mimetypes.guess_type(artifact.filename)
                if media_type and media_type.startswith("image/"):
                    await message.reply_photo(photo=file_handle, filename=artifact.filename)
                else:
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
        await self._reply_text(message, "You are not authorized to use this bot.")
        return False

    async def _reply_text(self, message: object, text: str) -> None:
        await message.reply_text(render_telegram_html(text), parse_mode=ParseMode.HTML)


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
