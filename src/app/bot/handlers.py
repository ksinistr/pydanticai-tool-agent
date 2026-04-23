from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Iterable, Protocol

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.agent.service import AgentService
from app.artifacts import artifact_session
from app.bot.formatting import render_telegram_html
from app.bot.uploads import (
    PendingTelegramDocumentStore,
    SavedTelegramDocument,
    TelegramDocumentStore,
    is_gpx_document,
)
from app.daily_training_advice.service import DailyTrainingAdviceService
from app.morning_report.service import MorningReportService

logger = logging.getLogger(__name__)
DEFAULT_GPX_ANALYSIS_PROMPT = (
    "Render route images from this GPX file and provide a short summary with distance, "
    "ascent, descent, and min/max elevation."
)


class GpxDocumentAnalyzer(Protocol):
    def render_route_gpx_images(self, gpx_reference: str, track_color: str = "red") -> str: ...


class TelegramHandlers:
    def __init__(
        self,
        agent_service: AgentService,
        morning_report_service: MorningReportService | None = None,
        daily_training_advice_service: DailyTrainingAdviceService | None = None,
        authorized_users: Iterable[str] = (),
        document_store: TelegramDocumentStore | None = None,
        pending_documents: PendingTelegramDocumentStore | None = None,
        gpx_document_analyzer: GpxDocumentAnalyzer | None = None,
    ) -> None:
        self._agent_service = agent_service
        self._morning_report_service = morning_report_service
        self._daily_training_advice_service = daily_training_advice_service
        self._authorized_user_ids, self._authorized_usernames = _parse_authorized_users(
            authorized_users
        )
        self._document_store = document_store
        self._pending_documents = pending_documents or PendingTelegramDocumentStore()
        self._gpx_document_analyzer = gpx_document_analyzer

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
        self._pending_documents.clear(str(chat.id))
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

        session_id = str(chat.id)
        pending_document = self._pending_documents.get(session_id)
        prompt = _build_prompt(message.text, pending_document)
        if not await self._run_agent_prompt(
            session_id=session_id,
            message=message,
            prompt=prompt,
            log_message="Failed to process Telegram message",
            user_message="The bot hit an internal error while processing that message.",
        ):
            return

        self._pending_documents.clear(session_id)

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat

        if message is None or chat is None or not await self._authorize(update):
            return

        document = message.document
        if document is None:
            return
        if self._document_store is None:
            await self._reply_text(message, "Document uploads are not configured.")
            return
        if not is_gpx_document(document):
            await self._reply_text(message, "Only .gpx documents are supported right now.")
            return

        try:
            saved_document = await self._document_store.save(document)
        except Exception:
            logger.exception("Failed to download Telegram document")
            await self._reply_text(
                message,
                "The bot hit an internal error while downloading that file.",
            )
            return

        session_id = str(chat.id)
        self._pending_documents.clear(session_id)

        caption = (message.caption or "").strip()
        if self._gpx_document_analyzer is not None and not caption:
            if not await self._run_gpx_analysis(
                session_id=session_id,
                message=message,
                document=saved_document,
            ):
                return
            return

        prompt = _build_prompt(caption or DEFAULT_GPX_ANALYSIS_PROMPT, saved_document)
        if not await self._run_agent_prompt(
            session_id=session_id,
            message=message,
            prompt=prompt,
            log_message="Failed to process Telegram document",
            user_message="The bot hit an internal error while processing that file.",
        ):
            return

        self._pending_documents.clear(session_id)

    async def _run_gpx_analysis(
        self,
        session_id: str,
        message: object,
        document: SavedTelegramDocument,
    ) -> bool:
        try:
            with artifact_session(session_id):
                reply = self._gpx_document_analyzer.render_route_gpx_images(str(document.path))
        except Exception:
            logger.exception("Failed to process Telegram GPX document")
            await self._reply_text(
                message,
                "The bot hit an internal error while processing that GPX file.",
            )
            return False

        await self._reply_text(message, _format_gpx_analysis_reply(document.filename, reply))
        await self._send_artifacts(message, session_id)
        return True

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

    async def _run_agent_prompt(
        self,
        session_id: str,
        message: object,
        prompt: str,
        log_message: str,
        user_message: str,
    ) -> bool:
        try:
            reply = await self._agent_service.run(session_id, prompt)
        except Exception:
            logger.exception(log_message)
            await self._reply_text(message, user_message)
            return False

        await self._reply_text(message, reply)
        await self._send_artifacts(message, session_id)
        return True

    async def _send_artifacts(self, message: object, session_id: str) -> None:
        for artifact in self._agent_service.consume_artifacts(session_id):
            if not artifact.path.exists():
                logger.warning("Generated artifact missing: %s", artifact.path)
                continue
            with Path(artifact.path).open("rb") as file_handle:
                media_type, _ = mimetypes.guess_type(artifact.filename)
                if media_type and media_type.startswith("image/"):
                    await message.reply_photo(photo=file_handle, filename=artifact.filename)
                else:
                    await message.reply_document(document=file_handle, filename=artifact.filename)


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


def _build_prompt(text: str, document: SavedTelegramDocument | None) -> str:
    prompt = text.strip()
    if document is None:
        return prompt
    return (
        f"{prompt}\n\n"
        f"Telegram uploaded file: {document.filename}\n"
        f"Local file path: {document.path}\n"
        "Use this local file path directly if you need the uploaded file."
    )


def _format_gpx_analysis_reply(filename: str, reply: str) -> str:
    try:
        payload = json.loads(reply)
    except json.JSONDecodeError:
        return reply

    if not isinstance(payload, dict):
        return reply

    source = payload.get("source")
    source_filename = filename
    if isinstance(source, dict) and isinstance(source.get("filename"), str):
        source_filename = source["filename"]

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return f"GPX analysis is ready for `{source_filename}`."

    lines = [f"GPX analysis for `{source_filename}`:"]
    distance_km = _format_metric(summary.get("distance_km"), "km")
    ascent_m = _format_metric(summary.get("ascent_m"), "m")
    descent_m = _format_metric(summary.get("descent_m"), "m")
    min_elevation_m = _format_metric(summary.get("min_elevation_m"), "m")
    max_elevation_m = _format_metric(summary.get("max_elevation_m"), "m")

    if distance_km is not None:
        lines.append(f"- Distance: {distance_km}")
    if ascent_m is not None:
        lines.append(f"- Ascent: {ascent_m}")
    if descent_m is not None:
        lines.append(f"- Descent: {descent_m}")
    if min_elevation_m is not None and max_elevation_m is not None:
        lines.append(f"- Elevation: {min_elevation_m} to {max_elevation_m}")
    elif min_elevation_m is not None:
        lines.append(f"- Min elevation: {min_elevation_m}")
    elif max_elevation_m is not None:
        lines.append(f"- Max elevation: {max_elevation_m}")

    lines.append("Map and elevation profile attached.")
    return "\n".join(lines)


def _format_metric(value: object, unit: str) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, int | float):
        return None
    if unit == "m":
        if float(value).is_integer():
            return f"{int(value)} {unit}"
        return f"{value:.1f} {unit}"
    return f"{value:.2f} {unit}"
