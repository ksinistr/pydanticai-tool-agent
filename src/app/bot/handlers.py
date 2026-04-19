from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.agent.service import AgentService

logger = logging.getLogger(__name__)


class TelegramHandlers:
    def __init__(self, agent_service: AgentService) -> None:
        self._agent_service = agent_service

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None:
            return
        await message.reply_text(
            "Send me a message. I can answer normally and use tools like get_time when needed."
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None:
            return
        await message.reply_text(
            "Commands:\n/start\n/help\n/reset\n\nExample: What time is it in UTC?"
        )

    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None:
            return
        self._agent_service.reset(str(chat.id))
        await message.reply_text("Conversation history cleared.")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat

        if message is None or chat is None or not message.text:
            return

        try:
            reply = await self._agent_service.run(str(chat.id), message.text)
        except Exception:
            logger.exception("Failed to process Telegram message")
            await message.reply_text("The bot hit an internal error while processing that message.")
            return

        await message.reply_text(reply)

