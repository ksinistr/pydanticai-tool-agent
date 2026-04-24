from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.constants import ParseMode

from app.artifacts import artifact_store
from app.bot.formatting import render_telegram_html
from app.bot.handlers import TelegramHandlers
from app.bot.uploads import PendingTelegramDocumentStore, TelegramDocumentStore


def test_handle_text_rejects_unauthorized_username() -> None:
    service = SimpleNamespace(run=AsyncMock(), consume_artifacts=lambda session_id: [])
    handlers = TelegramHandlers(service, authorized_users=("@allowed_user",))
    message = SimpleNamespace(
        text="hello",
        reply_text=AsyncMock(),
        reply_document=AsyncMock(),
        reply_photo=AsyncMock(),
    )
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
    message = SimpleNamespace(
        text="hello",
        reply_text=AsyncMock(),
        reply_document=AsyncMock(),
        reply_photo=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=123456789, username=None),
    )

    asyncio.run(handlers.handle_text(update, None))

    service.run.assert_awaited_once_with("42", "hello")
    message.reply_text.assert_awaited_once_with("ok", parse_mode=ParseMode.HTML)
    message.reply_document.assert_awaited_once()
    message.reply_photo.assert_not_awaited()


def test_help_lists_standalone_advice_commands() -> None:
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
    assert "/daily_training_advice" in reply


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


def test_daily_training_advice_uses_standalone_service() -> None:
    agent_service = SimpleNamespace(run=AsyncMock(), consume_artifacts=lambda session_id: [])
    daily_training_advice_service = SimpleNamespace(generate=AsyncMock(return_value="advice"))
    handlers = TelegramHandlers(
        agent_service,
        daily_training_advice_service=daily_training_advice_service,
    )
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )
    context = SimpleNamespace(args=[])

    asyncio.run(handlers.daily_training_advice(update, context))

    agent_service.run.assert_not_awaited()
    daily_training_advice_service.generate.assert_awaited_once()
    message.reply_text.assert_awaited_once_with("advice", parse_mode=ParseMode.HTML)


def test_daily_training_advice_rejects_arguments() -> None:
    agent_service = SimpleNamespace(run=AsyncMock(), consume_artifacts=lambda session_id: [])
    daily_training_advice_service = SimpleNamespace(generate=AsyncMock(return_value="advice"))
    handlers = TelegramHandlers(
        agent_service,
        daily_training_advice_service=daily_training_advice_service,
    )
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )
    context = SimpleNamespace(args=["extra"])

    asyncio.run(handlers.daily_training_advice(update, context))

    daily_training_advice_service.generate.assert_not_awaited()
    message.reply_text.assert_awaited_once_with(
        "Usage: /daily_training_advice",
        parse_mode=ParseMode.HTML,
    )


def test_handle_text_formats_basic_markdown() -> None:
    service = SimpleNamespace(
        run=AsyncMock(return_value="**Title**\n- item\n`code`\n[site](https://example.com)"),
        consume_artifacts=artifact_store.consume_session_artifacts,
    )
    handlers = TelegramHandlers(service)
    message = SimpleNamespace(
        text="hello",
        reply_text=AsyncMock(),
        reply_document=AsyncMock(),
        reply_photo=AsyncMock(),
    )
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


def test_handle_text_sends_png_artifacts_as_photos(tmp_path: Path) -> None:
    artifact_path = tmp_path / "route_map.png"
    artifact_path.write_bytes(b"png")
    service = SimpleNamespace(
        run=AsyncMock(return_value="ok"),
        consume_artifacts=lambda session_id: [
            SimpleNamespace(path=artifact_path, filename=artifact_path.name)
        ],
    )
    handlers = TelegramHandlers(service)
    message = SimpleNamespace(
        text="hello",
        reply_text=AsyncMock(),
        reply_document=AsyncMock(),
        reply_photo=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )

    asyncio.run(handlers.handle_text(update, None))

    message.reply_photo.assert_awaited_once()
    message.reply_document.assert_not_awaited()


def test_handle_document_with_caption_passes_file_context_to_agent(tmp_path: Path) -> None:
    service = SimpleNamespace(
        run=AsyncMock(return_value="ok"),
        consume_artifacts=artifact_store.consume_session_artifacts,
    )
    pending_documents = PendingTelegramDocumentStore()
    handlers = TelegramHandlers(
        service,
        document_store=TelegramDocumentStore(tmp_path),
        pending_documents=pending_documents,
    )
    message = SimpleNamespace(
        caption="Render route images from this GPX file.",
        document=_document("route.gpx", "<gpx/>"),
        reply_text=AsyncMock(),
        reply_document=AsyncMock(),
        reply_photo=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )

    asyncio.run(handlers.handle_document(update, None))

    service.run.assert_awaited_once()
    prompt = service.run.await_args.args[1]
    assert "Render route images from this GPX file." in prompt
    assert "route.gpx" in prompt
    assert str(tmp_path) in prompt
    assert pending_documents.get("42") is None


def test_handle_document_without_caption_runs_default_agent_analysis(tmp_path: Path) -> None:
    service = SimpleNamespace(
        run=AsyncMock(return_value="ok"),
        consume_artifacts=artifact_store.consume_session_artifacts,
    )
    pending_documents = PendingTelegramDocumentStore()
    handlers = TelegramHandlers(
        service,
        document_store=TelegramDocumentStore(tmp_path),
        pending_documents=pending_documents,
    )
    document_message = SimpleNamespace(
        caption=None,
        document=_document("route.gpx", "<gpx/>"),
        reply_text=AsyncMock(),
        reply_document=AsyncMock(),
        reply_photo=AsyncMock(),
    )
    document_update = SimpleNamespace(
        effective_message=document_message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )

    asyncio.run(handlers.handle_document(document_update, None))

    service.run.assert_awaited_once()
    prompt = service.run.await_args.args[1]
    assert "Render route images from this GPX file" in prompt
    assert "short summary with distance, ascent, descent, and min/max elevation" in prompt
    assert "route.gpx" in prompt
    assert str(tmp_path) in prompt
    assert pending_documents.get("42") is None


def test_handle_document_rejects_non_gpx_files(tmp_path: Path) -> None:
    service = SimpleNamespace(
        run=AsyncMock(return_value="ok"),
        consume_artifacts=artifact_store.consume_session_artifacts,
    )
    handlers = TelegramHandlers(
        service,
        document_store=TelegramDocumentStore(tmp_path),
    )
    message = SimpleNamespace(
        caption="Process this file.",
        document=_document("notes.txt", "hello"),
        reply_text=AsyncMock(),
        reply_document=AsyncMock(),
        reply_photo=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )

    asyncio.run(handlers.handle_document(update, None))

    service.run.assert_not_awaited()
    message.reply_text.assert_awaited_once_with(
        "Only .gpx documents are supported right now.",
        parse_mode=ParseMode.HTML,
    )


def test_handle_document_without_caption_uses_gpx_analyzer(tmp_path: Path) -> None:
    map_path = tmp_path / "route_map.jpg"
    profile_path = tmp_path / "route_profile.png"
    enriched_path = tmp_path / "route_enriched.gpx"
    map_path.write_bytes(b"jpg")
    profile_path.write_bytes(b"png")
    enriched_path.write_text("<gpx/>", encoding="utf-8")

    class FakeGpxAnalyzer:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, bool]] = []

        def render_route_gpx_images(
            self,
            gpx_reference: str,
            track_color: str = "red",
            include_enriched_gpx: bool = False,
        ) -> str:
            self.calls.append((gpx_reference, track_color, include_enriched_gpx))
            artifact_store.register_file(map_path, map_path.name)
            artifact_store.register_file(profile_path, profile_path.name)
            artifact_store.register_file(enriched_path, enriched_path.name)
            return json.dumps(
                {
                    "source": {"filename": "route.gpx"},
                    "summary": {
                        "distance_km": 49.91,
                        "ascent_m": 1168.0,
                        "descent_m": 1142.0,
                        "min_elevation_m": 7.8,
                        "max_elevation_m": 496.0,
                    },
                    "enriched_gpx": {
                        "status": "ok",
                        "refuel_waypoints": 2,
                        "camping_waypoints": 1,
                        "attribution": "OpenStreetMap contributors",
                    },
                }
            )

    service = SimpleNamespace(
        run=AsyncMock(return_value="ok"),
        consume_artifacts=artifact_store.consume_session_artifacts,
    )
    analyzer = FakeGpxAnalyzer()
    handlers = TelegramHandlers(
        service,
        document_store=TelegramDocumentStore(tmp_path),
        gpx_document_analyzer=analyzer,
    )
    message = SimpleNamespace(
        caption=None,
        document=_document("route.gpx", "<gpx/>"),
        reply_text=AsyncMock(),
        reply_document=AsyncMock(),
        reply_photo=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42),
        effective_user=SimpleNamespace(id=7, username="allowed_user"),
    )

    asyncio.run(handlers.handle_document(update, None))

    service.run.assert_not_awaited()
    assert len(analyzer.calls) == 1
    assert analyzer.calls[0][0].endswith(".gpx")
    assert analyzer.calls[0][1] == "red"
    assert analyzer.calls[0][2] is True
    reply = message.reply_text.await_args.args[0]
    assert "GPX analysis for" in reply
    assert "Distance: 49.91 km" in reply
    assert "Ascent: 1168 m" in reply
    assert "Elevation: 7.8 m to 496 m" in reply
    assert "Map and elevation profile attached." in reply
    assert "Enriched GPX attached (2 refuel waypoints, 1 camping waypoint)." in reply
    assert "POI data: OpenStreetMap contributors." in reply
    assert message.reply_photo.await_count == 2
    message.reply_document.assert_awaited_once()
    assert message.reply_document.await_args.kwargs["filename"] == "route_enriched.gpx"


def _document(filename: str, payload: str) -> SimpleNamespace:
    async def download_to_drive(custom_path: Path, **kwargs) -> Path:
        del kwargs
        custom_path.write_text(payload)
        return custom_path

    telegram_file = SimpleNamespace(download_to_drive=AsyncMock(side_effect=download_to_drive))
    return SimpleNamespace(
        file_name=filename,
        get_file=AsyncMock(return_value=telegram_file),
    )
